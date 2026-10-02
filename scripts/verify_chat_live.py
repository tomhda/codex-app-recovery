"""Opt-in real CLI verification: only wrapper test turns; no live desktop changes."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chat_client import ChatSession

parser = argparse.ArgumentParser()
parser.add_argument('--cli', required=True)
parser.add_argument('--directory', required=True)
args = parser.parse_args()
root = Path(args.directory).resolve()
root.mkdir(parents=True, exist_ok=True)
path = root / 'live-session.json'
report = {'model': 'gpt-6.1-sol', 'effort': 'high', 'checks': [], 'events': {}}
def drain(session):
    while not session.events.empty():
        event = session.events.get_nowait()
        kind = event['type']
        report['events'][kind] = report['events'].get(kind, 0) + 1
        if kind == 'approval':
            raise RuntimeError('Unexpected approval in no-tool test; no approval granted')
def wait(session, seconds=180):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        drain(session)
        if session.state in ('idle', 'stopped', 'error', 'unknown'):
            print('terminal', json.dumps(session.diagnostics()), flush=True)
            if session.state != 'idle':
                raise RuntimeError('Non-success terminal state: ' + session.state)
            return
        time.sleep(0.1)
    raise RuntimeError('Live test deadline')
def check(session, text, expected, label):
    before = len(session.data['messages'])
    session.send(text, str(root))
    wait(session)
    answer = '\n'.join(x['text'] for x in session.data['messages'][before:] if x['role'] == 'assistant')
    passed = expected in answer
    report['checks'].append({'name': label, 'passed': passed, 'answer': answer[:300]})
    print(label, passed, answer[:300], flush=True)
    if not passed: raise RuntimeError('Answer mismatch')
s = ChatSession(path, [args.cli])
try:
    s.connect()
    print('connected', json.dumps(s.diagnostics()), flush=True)
    check(s, 'This is a read-only wrapper chat test. Do not use tools or read files. Remember marker BLUE_ORBIT_731 for this conversation. Reply exactly FIRST_OK.', 'FIRST_OK', 'first_response')
    check(s, 'Do not use tools. What marker did I ask you to remember? Reply with that marker only.', 'BLUE_ORBIT_731', 'same_thread_followup')
    s.send('Do not use tools. Reply exactly STOP_RETRY_OK.', str(root))
    try:
        s.stop()
    except Exception as error:
        print('interrupt protocol detail:', getattr(error, 'detail', None), flush=True)
        raise
    report['checks'].append({'name': 'official_interrupt', 'passed': s.state == 'stopped', 'state': s.state})
    print('stop', s.state, flush=True)
    s.retry(); wait(s)
    report['checks'].append({'name': 'explicit_retry', 'passed': 'STOP_RETRY_OK' in s.data['messages'][-1]['text']})
    s.close()
    s = ChatSession(path, [args.cli])
    s.connect()
    check(s, 'Do not use tools. Reply AFTER_RESTART_OK followed by our remembered marker.', 'BLUE_ORBIT_731', 'restart_followup')
    (root / 'diagnostic-probe.txt').write_text('READ_ONLY_TOOL_OK_827', encoding='utf-8')
    tools_before = report['events'].get('tool', 0)
    check(s, 'Use the shell tool to read ONLY diagnostic-probe.txt in the working folder. Do not read other files or change anything. Reply with its contents.', 'READ_ONLY_TOOL_OK_827', 'read_only_tool')
    if report['events'].get('tool', 0) <= tools_before:
        raise RuntimeError('No tool event observed')
    s.send('Do not use tools. Think carefully about primes below 10000, then reply exactly DISCONNECT_TEST_OK.', str(root))
    activation = time.monotonic() + 10
    while not s.turn_started and time.monotonic() < activation:
        time.sleep(0.01)
    if not s.turn_started:
        raise RuntimeError('Test turn did not activate')
    s.server.process.terminate()  # This new test child only; never the desktop.
    s.server.process.wait(timeout=10)
    disconnected = time.monotonic() + 10
    while s.connected and time.monotonic() < disconnected:
        time.sleep(0.01)
    blocked = False
    try:
        s.retry()
    except Exception:
        blocked = True
    report['checks'].append({'name': 'disconnect_blocks_blind_retry', 'passed': blocked, 'state': s.state})
    s.close()
    s = ChatSession(path, [args.cli])
    s.connect()
    print('after abrupt disconnect', json.dumps(s.diagnostics()), flush=True)
    report['checks'].append({'name': 'abrupt_disconnect_reconciliation', 'passed': s.state == 'idle', 'state': s.state})
    check(s, 'Do not use tools. Reply AFTER_DISCONNECT_OK followed by our remembered marker.', 'BLUE_ORBIT_731', 'disconnect_followup')
    report['threadId'] = s.data['threadId']
    report['diagnostics'] = s.diagnostics()
finally:
    drain(s)
    s.close()
    (root / 'live-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
