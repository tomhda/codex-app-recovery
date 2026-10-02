"""Read-only handshake probe; no tokens or account identifiers are printed."""
import json
import queue
import subprocess
import sys
import threading

p = subprocess.Popen([sys.argv[1], 'app-server', '--stdio'], stdin=subprocess.PIPE,
                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                     text=True, encoding='utf-8', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
q = queue.Queue()
def read():
    for line in p.stdout:
        try: q.put(json.loads(line))
        except ValueError: pass
threading.Thread(target=read, daemon=True).start()
def request(n, method, params):
    p.stdin.write(json.dumps({'id': n, 'method': method, 'params': params}) + '\n'); p.stdin.flush()
    while True:
        m = q.get(timeout=30)
        if m.get('id') == n: return m
try:
    init = request(1, 'initialize', {'clientInfo': {'name': 'codex_app_recovery', 'version': '0.5.0'}})
    print('initialize', 'error' if 'error' in init else 'ok', flush=True)
    p.stdin.write('{"method":"initialized","params":{}}\n'); p.stdin.flush()
    account = request(2, 'account/read', {'refreshToken': False})
    print('account', {'signedIn': bool(account.get('result', {}).get('account')), 'errorCode': account.get('error', {}).get('code')}, flush=True)
    models = request(3, 'model/list', {})
    print('models', [{'id': m.get('id'), 'model': m.get('model'), 'efforts': m.get('supportedReasoningEfforts')} for m in models.get('result', {}).get('data', [])], flush=True)
finally:
    p.terminate(); p.wait(timeout=10)
