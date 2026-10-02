"""Deterministic stdio peer; no external network or user Codex state."""
import json
from pathlib import Path
import sys

store = Path(sys.argv[1])
data = json.loads(store.read_text()) if store.exists() else {'turns': [], 'requests': []}
def save():
    store.write_text(json.dumps(data), encoding='utf-8')
def emit(value):
    print(json.dumps(value), flush=True)
def notify(method, **params):
    emit({'method': method, 'params': {'threadId': 'wrapper-thread', **params}})
def thread():
    return {'id': 'wrapper-thread', 'status': {'type': 'idle'}, 'turns': data['turns']}
for line in sys.stdin:
    m = json.loads(line)
    method, params = m.get('method'), m.get('params', {})
    if not method:
        data['answers'] = m.get('result'); save()
        continue
    data['requests'].append({'method': method, 'params': params}); save()
    result = {}
    if method == 'test/no-response':
        continue
    if method == 'initialize':
        result = {'userAgent': 'fake'}
    elif method == 'account/read':
        result = {'account': {'type': 'chatgpt'}}
    elif method == 'model/list':
        result = {'data': [{'model': 'gpt-6.1-sol', 'supportedReasoningEfforts': [{'reasoningEffort': 'high'}]}]}
    elif method in ('thread/start', 'thread/read', 'thread/resume'):
        result = {'thread': thread(), 'model': 'gpt-6.1-sol', 'sandbox': {'type': 'readOnly'}, 'approvalPolicy': 'on-request', 'approvalsReviewer': 'user'}
    elif method == 'turn/start':
        text = params['input'][0]['text']
        turn = {'id': 'turn-' + str(len(data['turns']) + 1), 'status': 'inProgress', 'items': [
            {'id': 'u', 'type': 'userMessage', 'clientId': params['clientUserMessageId'], 'content': params['input']}]}
        data['turns'].append(turn); save()
        if '[disconnect]' in text:
            turn['status'] = 'completed'
            turn['items'].append({'id': 'answer-' + turn['id'], 'type': 'agentMessage', 'text': 'Recovered answer'})
            save(); sys.exit(0)
        result = {'turn': turn}
        emit({'id': m['id'], 'result': result})
        notify('turn/started', turn=turn)
        if '[wait]' in text:
            continue
        if '[approval]' in text:
            emit({'id': 'approval-1', 'method': 'item/commandExecution/requestApproval', 'params': {'threadId': 'wrapper-thread', 'turnId': turn['id'], 'itemId': 'cmd', 'command': 'echo harmless', 'availableDecisions': ['accept', 'decline', 'cancel']}})
            continue
        for delta in ['Hello ', 'world']:
            notify('item/agentMessage/delta', turnId=turn['id'], itemId='answer-' + turn['id'], delta=delta)
        turn['status'] = 'completed'
        turn['items'].append({'id': 'answer-' + turn['id'], 'type': 'agentMessage', 'text': 'Hello world'})
        save()
        notify('item/completed', turnId=turn['id'], item=turn['items'][-1])
        notify('turn/completed', turn=turn)
        continue
    elif method == 'turn/interrupt':
        turn = next(t for t in data['turns'] if t['id'] == params['turnId'])
        turn['status'] = 'interrupted'; save()
        notify('turn/completed', turn=turn)
    if 'id' in m:
        emit({'id': m['id'], 'result': result})
