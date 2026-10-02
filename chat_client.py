"""Independent official Codex app-server client. No desktop queue or HTTP listener.

Only this client's child process/turn may be stopped. Uncertain sends are
reconciled by client message ID before allowing another turn.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time
import uuid

MODEL = 'gpt-6.1-sol'
EFFORT = 'high'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


class ChatError(Exception):
    def __init__(self, code, uncertain=False, detail=None):
        super().__init__(code)
        self.code, self.uncertain = str(code), uncertain
        self.detail = detail


def redact(text):
    text = str(text)
    text = re.sub(r'(?i)(bearer\s+|(?:api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|password|secret)\s*[=:]\s*["\']?)[^\s,"\'}]+', r'\1[redacted]', text)
    return re.sub(r'\b(?:sk-[A-Za-z0-9_-]{16,}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b', '[redacted]', text)


def discover_codex():
    """Discover the installed CLI on every new connection (updates move it)."""
    direct = shutil.which('codex.exe' if os.name == 'nt' else 'codex')
    if direct and Path(direct).is_file():
        return [direct]
    if os.name == 'nt':
        base = Path(os.environ.get('LOCALAPPDATA', '')) / 'OpenAI' / 'Codex' / 'bin'
        installed = sorted(base.glob('*/codex.exe'), key=lambda p: p.stat().st_mtime, reverse=True)
        if installed:
            return [str(installed[0])]
    raise ChatError('cli_missing')


class AppServer:
    def __init__(self, callback, command=None, timeout=30):
        self.callback, self.timeout = callback, timeout
        self.lock, self.write_lock = threading.Lock(), threading.Lock()
        self.pending, self.counter = {}, 0
        self.closed = False
        self.process = subprocess.Popen((command or discover_codex()) + ['app-server', '--stdio'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', errors='replace', bufsize=1, creationflags=NO_WINDOW)
        threading.Thread(target=self._read, daemon=True).start()
        # Drain stderr, but do not expose or persist raw server/config/token errors.
        threading.Thread(target=self._drain, daemon=True).start()

    def _drain(self):
        for _ in self.process.stderr:
            pass

    def _read(self):
        try:
            for line in self.process.stdout:
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(message, dict):
                    continue
                if 'method' not in message and 'id' in message:
                    with self.lock:
                        target = self.pending.pop(message['id'], None)
                    if target:
                        target.put(message)
                else:
                    self.callback(message)
        finally:
            with self.lock:
                targets = list(self.pending.values())
                self.pending.clear()
            for target in targets:
                target.put({'error': {'code': 'disconnected'}})
            if not self.closed:
                self.callback({'method': '_disconnected', 'params': {}})

    def write(self, value):
        try:
            with self.write_lock:
                if self.closed or self.process.poll() is not None:
                    raise ChatError('disconnected', True)
                self.process.stdin.write(json.dumps(value, ensure_ascii=False) + '\n')
                self.process.stdin.flush()
        except (OSError, ValueError):
            raise ChatError('disconnected', True) from None

    def request(self, method, params=None, timeout=None):
        with self.lock:
            self.counter += 1
            n = self.counter
            target = self.pending[n] = queue.Queue()
        try:
            self.write({'id': n, 'method': method, 'params': params or {}})
            try:
                response = target.get(timeout=timeout or self.timeout)
            except queue.Empty:
                raise ChatError('request_timeout', method == 'turn/start') from None
            if 'error' in response:
                code = response['error'].get('code', 'server_error')
                raise ChatError('rpc_' + str(code), code == 'disconnected', redact(response['error'].get('message', '')))
            return response.get('result', {})
        finally:
            with self.lock:
                self.pending.pop(n, None)

    def reply(self, request_id, result):
        self.write({'id': request_id, 'result': result})

    def close(self):
        self.closed = True
        if self.process.poll() is None:
            # No taskkill /T, process-name matching, or desktop process changes.
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()


def session_path():
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'CodexAppRecovery' / 'chat-session.json'


class ChatSession:
    def __init__(self, path=None, command=None, idle_timeout=120, turn_timeout=1800, request_timeout=30):
        self.path = Path(path) if path else session_path()
        self.command, self.request_timeout = command, request_timeout
        self.idle_timeout, self.turn_timeout = idle_timeout, turn_timeout
        self.events, self.lock, self.operation_lock = queue.Queue(), threading.RLock(), threading.Lock()
        self.server, self.connected, self.closed = None, False, False
        self.state, self.error = 'disconnected', None
        self.execution_policy = None
        self.data = {'threadId': None, 'cwd': None, 'messages': [], 'pending': None}
        self.turn_id, self.turn_started, self.approvals, self.items = None, False, {}, {}
        self.last_activity = self.started = time.monotonic()
        try:
            value = json.loads(self.path.read_text(encoding='utf-8'))
            if isinstance(value, dict) and isinstance(value.get('messages'), list):
                self.data.update({k: value.get(k) for k in self.data})
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            self.error = 'session_unreadable'
            self.state = 'error'
        if self.data['pending']:
            self.state = 'unknown'
        threading.Thread(target=self._watch, daemon=True).start()

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
        try:
            with tmp.open('x', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        finally:
            tmp.unlink(missing_ok=True)

    def _state(self, state, error=None):
        self.state, self.error = state, error
        self.events.put({'type': 'state', 'state': state, 'error': error})

    def _message(self, role, text, item_id=None):
        text = redact(text)
        entry = {'role': role, 'text': text, 'itemId': item_id}
        self.data['messages'].append(entry)
        self.events.put({'type': 'message', **entry})

    def _watch(self):
        while not self.closed:
            time.sleep(0.25)
            with self.lock:
                if self.state not in ('sending', 'running', 'waiting'):
                    continue
                now = time.monotonic()
                if now - self.last_activity > self.idle_timeout or now - self.started > self.turn_timeout:
                    # Receipt remains pending. No blind re-send, no endless spinner.
                    self._state('unknown', 'activity_timeout')
                    self.events.put({'type': 'diagnostic', 'code': 'reconnect_before_retry'})

    def _notification(self, message):
        method, params = message.get('method', ''), message.get('params', {})
        with self.lock:
            if method == '_disconnected':
                self.connected = False
                self.approvals.clear()
                self._state('unknown' if self.data['pending'] else 'disconnected', 'disconnected')
                return
            if params.get('threadId') and params['threadId'] != self.data['threadId']:
                if 'id' in message:
                    self.server.write({'id': message['id'], 'error': {'code': -32601, 'message': 'Unowned thread'}})
                return
            if 'id' in message:
                self._server_request(message)
                return
            if method == 'serverRequest/resolved':
                self.approvals.pop(params.get('requestId'), None)
                self.events.put({'type': 'approval_resolved', 'id': params.get('requestId')})
                return
            if method == 'model/rerouted' and params.get('toModel') != MODEL:
                self._state('unknown', 'model_rerouted')
                self.events.put({'type': 'diagnostic', 'code': 'model_rerouted'})
                def cancel_rerouted():
                    try:
                        self.stop()
                    except ChatError:
                        pass
                threading.Thread(target=cancel_rerouted, daemon=True).start()
                return
            if params.get('turnId') and self.turn_id and params['turnId'] != self.turn_id:
                return
            if not self.data['pending']:
                return
            self.last_activity = time.monotonic()
            if method == 'turn/started':
                self.turn_id = params['turn']['id']
                self.turn_started = True
                self.data['pending']['turnId'] = self.turn_id
                self._state('running')
                self._save()
            elif method == 'item/agentMessage/delta':
                item_id = params['itemId']
                entry = self.items.get(item_id)
                if entry is None:
                    self._message('assistant', '', item_id)
                    entry = self.items[item_id] = self.data['messages'][-1]
                # Re-redact the full accumulated text; secrets can span chunks.
                entry['text'] = redact(entry['text'] + params.get('delta', ''))
                self.events.put({'type': 'transcript'})
            elif method in ('item/started', 'item/completed'):
                item = params.get('item', {})
                if item.get('type') == 'agentMessage' and method == 'item/completed':
                    item_id = item['id']
                    if item_id in self.items:
                        self.items[item_id]['text'] = redact(item.get('text', ''))
                        self.events.put({'type': 'transcript'})
                    else:
                        self._message('assistant', item.get('text', ''), item_id)
                elif item.get('type') in ('commandExecution', 'fileChange', 'mcpToolCall', 'webSearch'):
                    self.events.put({'type': 'tool', 'kind': item['type'], 'status': item.get('status', method)})
                    # Show command and patch previews for informed approval, no raw stdout.
                    self.items[item.get('id')] = item
                if method == 'item/completed':
                    self._save()
            elif method == 'turn/completed':
                self._finish(params['turn'])
            elif method == 'error':
                self.events.put({'type': 'diagnostic', 'code': 'upstream_retrying' if params.get('willRetry') else 'upstream_error'})
                if not params.get('willRetry'):
                    self._state('unknown', 'upstream_error')

    def _finish(self, turn):
        status = turn.get('status', 'unknown')
        self.data['pending'] = None
        self.approvals.clear()
        self._state('idle' if status == 'completed' else 'stopped' if status == 'interrupted' else 'error',
                    'turn_failed' if status == 'failed' else None)
        self._save()

    def _server_request(self, message):
        method, params, request_id = message['method'], message.get('params', {}), message['id']
        allowed = ('item/commandExecution/requestApproval', 'item/fileChange/requestApproval', 'item/tool/requestUserInput')
        if method not in allowed:
            # Permission grants, authentication, and unknown protocols fail closed.
            self.server.write({'id': request_id, 'error': {'code': -32601, 'message': 'Unsupported request; no permission granted'}})
            self.events.put({'type': 'diagnostic', 'code': 'unsupported_request'})
            return
        self.approvals[request_id] = message
        preview = {'method': method, **params, 'item': self.items.get(params.get('itemId'), {})}
        self._state('approval')
        self.events.put({'type': 'approval', 'id': request_id, 'preview': redact(json.dumps(preview, ensure_ascii=False, indent=2))})

    def answer(self, request_id, accept=False, answers=None):
        with self.lock:
            message = self.approvals.get(request_id)
            if not message or not self.server:
                raise ChatError('approval_expired')
            if message['method'] == 'item/tool/requestUserInput':
                if answers is None:
                    raise ChatError('answer_required')
                result = {'answers': {k: {'answers': v} for k, v in answers.items()}}
            else:
                available = message['params'].get('availableDecisions')
                decision = 'accept' if accept else 'decline'
                if available and decision not in available:
                    raise ChatError('approval_unsupported')
                result = {'decision': decision}
            self.server.reply(request_id, result)
            self.approvals.pop(request_id, None)
            self.last_activity = time.monotonic()
            self._state('approval' if self.approvals else 'running')

    def connect(self):
        with self.operation_lock:
            if self.closed:
                raise ChatError('closed')
            with self.lock:
                if self.error == 'session_unreadable':
                    raise ChatError(self.error)
                self._state('connecting')
            try:
                if self.server:
                    self.server.close()
                self.connected = False
                self.server = AppServer(self._notification, self.command, self.request_timeout)
                self.server.request('initialize', {'clientInfo': {'name': 'codex_app_recovery', 'title': 'Codex App Recovery', 'version': '0.5.0'}})
                self.server.write({'method': 'initialized', 'params': {}})
                account = self.server.request('account/read', {'refreshToken': False})
                if not account.get('account'):
                    raise ChatError('authentication_required')
                models = self.server.request('model/list').get('data', [])
                if not any(m.get('model') == MODEL and any(e.get('reasoningEffort') == EFFORT for e in m.get('supportedReasoningEfforts', [])) for m in models):
                    raise ChatError('model_unavailable')
                self.connected = True
                if self.data['threadId']:
                    # Inspect only a thread created by this wrapper, never desktop chats.
                    snapshot = self.server.request('thread/read', {'threadId': self.data['threadId'], 'includeTurns': True})
                    thread = snapshot['thread']
                    if thread.get('status', {}).get('type') == 'active':
                        self._state('unknown', 'thread_active')
                        return
                    result = self.server.request('thread/resume', {'threadId': self.data['threadId'], 'model': MODEL,
                        'sandbox': 'read-only', 'approvalPolicy': 'on-request', 'approvalsReviewer': 'user'})
                    self._verify_policy(result)
                    self._hydrate(result.get('thread', thread))
                with self.lock:
                    self._state('idle')
            except Exception as error:
                self.connected = False
                with self.lock:
                    self._state('unknown' if self.data['pending'] else 'error', getattr(error, 'code', 'connection_failed'))
                raise

    def _verify_policy(self, result):
        policy = {'model': result.get('model'), 'sandbox': result.get('sandbox', {}).get('type'),
            'approvalPolicy': result.get('approvalPolicy'), 'approvalsReviewer': result.get('approvalsReviewer')}
        if policy != {'model': MODEL, 'sandbox': 'readOnly', 'approvalPolicy': 'on-request', 'approvalsReviewer': 'user'}:
            raise ChatError('execution_policy_mismatch')
        self.execution_policy = policy

    def _hydrate(self, thread):
        with self.lock:
            turns = thread.get('turns', [])
            pending = self.data['pending']
            if pending:
                matches = [t for t in turns if t.get('id') == pending.get('turnId') or any(
                    i.get('type') == 'userMessage' and i.get('clientId') == pending['clientId'] for i in t.get('items', []))]
                if matches:
                    turn = matches[-1]
                    if turn.get('status') not in ('completed', 'interrupted', 'failed'):
                        self._state('unknown', 'thread_active')
                        raise ChatError('thread_active')
                    for item in turn.get('items', []):
                        if item.get('type') == 'agentMessage':
                            existing = next((x for x in self.data['messages'] if x.get('itemId') == item['id']), None)
                            if existing:
                                existing['text'] = redact(item.get('text', ''))
                            else:
                                self._message('assistant', item.get('text', ''), item['id'])
                    self.events.put({'type': 'diagnostic', 'code': 'already_received'})
                elif pending.get('submitted'):
                    # Missing receipt is not evidence of non-delivery (pagination/version).
                    self._state('unknown', 'receipt_unknown')
                    raise ChatError('receipt_unknown')
                self.data['pending'] = None
            self._save()
            self.events.put({'type': 'transcript'})

    def send(self, text, cwd):
        if not text.strip():
            raise ChatError('empty_input')
        with self.operation_lock:
            with self.lock:
                if not self.connected or self.state not in ('idle', 'stopped', 'error') or self.data['pending']:
                    raise ChatError('not_ready')
                if not Path(cwd).is_dir():
                    raise ChatError('cwd_missing')
                if self.data['cwd'] and str(Path(cwd).resolve()) != self.data['cwd']:
                    raise ChatError('cwd_changed')
                self._state('sending')
                self.started = self.last_activity = time.monotonic()
            try:
                if not self.data['threadId']:
                    result = self.server.request('thread/start', {'model': MODEL, 'cwd': str(Path(cwd).resolve()),
                        'sandbox': 'read-only', 'approvalPolicy': 'on-request', 'approvalsReviewer': 'user',
                        'developerInstructions': 'You are the agent in Codex App Recovery. Diagnose and operate the local Codex app only as requested. Start with read-only checks. Do not read or expose auth.json, .env, tokens, passwords or secret values. Do not delete conversations, change live databases, force-cancel existing desktop turns or terminate desktop processes without specific user authorization explaining impact. Keep official sandbox and approvals. Never change persistent authentication or security settings.'})
                    with self.lock:
                        self.data['threadId'] = result['thread']['id']
                        self.data['cwd'] = str(Path(cwd).resolve())
                        self._save()
                    self._verify_policy(result)
                with self.lock:
                    self.turn_id = None
                    self.turn_started = False
                    self.items = {}
                    self._message('user', text)
                    self.data['pending'] = {'clientId': str(uuid.uuid4()), 'text': redact(text), 'submitted': False}
                    self._save()
                    self.data['pending']['submitted'] = True
                    self._save()  # Persist BEFORE writing a mutating RPC.
                    params = {'threadId': self.data['threadId'], 'model': MODEL, 'effort': EFFORT,
                        'clientUserMessageId': self.data['pending']['clientId'], 'input': [{'type': 'text', 'text': text}]}
                result = self.server.request('turn/start', params)
                with self.lock:
                    if self.data['pending']:
                        self.turn_id = result['turn']['id']
                        self.data['pending']['turnId'] = self.turn_id
                        if self.state == 'sending':
                            self._state('waiting')
                        self._save()
            except Exception as error:
                with self.lock:
                    if getattr(error, 'code', '') == 'execution_policy_mismatch':
                        self.connected = False
                    if self.data['pending'] and not getattr(error, 'uncertain', True):
                        self.data['pending'] = None
                        self._save()
                    self._state('unknown' if self.data['pending'] else 'error', getattr(error, 'code', 'send_failed'))
                raise

    def stop(self):
        # Interrupt is scoped to the wrapper's stored thread and known turn ID.
        with self.lock:
            pending = self.data['pending']
            turn_id = self.turn_id or (pending or {}).get('turnId')
            if not pending or not turn_id or not self.connected:
                raise ChatError('stop_unknown')
            self._state('stopping')
        try:
            # turn/start acknowledges before runtime activation on the native
            # server. Interrupting before turn/started returns "no active turn".
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                with self.lock:
                    if not self.data['pending']:
                        return  # Natural completion won the race.
                    if self.turn_started:
                        break
                time.sleep(0.05)
            else:
                raise ChatError('activation_timeout', True)
            self.server.request('turn/interrupt', {'threadId': self.data['threadId'], 'turnId': turn_id}, timeout=10)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                with self.lock:
                    if not self.data['pending']:
                        return
                time.sleep(0.05)
            raise ChatError('stop_timeout', True)
        except Exception as error:
            with self.lock:
                self._state('unknown', getattr(error, 'code', 'stop_failed'))
            raise

    def retry(self):
        # Explicit retry only after receipt reconciliation and a terminal turn.
        with self.lock:
            if self.data['pending'] or self.state not in ('idle', 'stopped', 'error'):
                raise ChatError('reconnect_before_retry')
            last = next((x['text'] for x in reversed(self.data['messages']) if x['role'] == 'user'), None)
        if not last:
            raise ChatError('no_retry_input')
        self.send(last, self.data['cwd'])

    def new_conversation(self):
        with self.operation_lock, self.lock:
            if self.data['pending']:
                raise ChatError('reconnect_before_retry')
            self.data = {'threadId': None, 'cwd': None, 'messages': [], 'pending': None}
            self._save()
            self._state('idle' if self.connected else 'disconnected')
            self.events.put({'type': 'transcript'})

    def diagnostics(self):
        with self.lock:
            return {'transport': 'official app-server stdio', 'model': MODEL, 'effort': EFFORT,
                'state': self.state, 'error': self.error, 'connected': self.connected,
                'ownedThread': bool(self.data['threadId']), 'pendingReceipt': bool(self.data['pending']),
                'executionPolicy': self.execution_policy,
                'secondsSinceEvent': int(time.monotonic() - self.last_activity),
                'desktopFollowupHealth': 'unknown'}

    def close(self):
        self.closed = True
        if self.server:
            self.server.close()
