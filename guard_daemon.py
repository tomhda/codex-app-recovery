"""Companion process for the Codex self-heal guard.

Keeps guard.js loaded in every Codex app document (also across reloads)
through the local diagnostic port, records its reports, and tells the guard
when the host log shows a reply was already routed while the request is still
waiting. It never sends chat messages, never touches queues, never reloads
and never restarts the app.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import threading
import time
import urllib.request
from pathlib import Path

import websocket

ROOT = Path(__file__).resolve().parent
GUARD = (ROOT / 'guard.js').read_text(encoding='utf-8')
# Marks documents that received the guard before any app script ran.
GUARD_AT_START = 'window.__codexGuardInjectedAtStart = true;\n' + GUARD
PORT = 9222
DATA = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'CodexAppRecovery' / 'guard'
HOST_LOGS = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Packages' / 'OpenAI.Codex_2p2nqsd0c76g0' / 'LocalCache' / 'Local' / 'Codex' / 'Logs'
POLL_SECONDS = 5
GIVE_UP_WITHOUT_APP_SECONDS = 120
GIVE_UP_WITHOUT_PORT_SECONDS = 600
CONFIRM_WINDOW_SECONDS = 240
LOG_TAIL_BYTES = 6 * 1024 * 1024
STARTUP_BLANK_LOG_SECONDS = 120
_ROUTED = re.compile(rb'^(\S+) .*\bresponse_routed\b.*\brequestId=(\S+) .*\btargetDestroyed=false\b')


def log(event: dict) -> None:
    """Best effort: a failing log write must never stop the guard."""
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        record = {'time': datetime.datetime.now().astimezone().isoformat(timespec='seconds'), **event}
        path = DATA / ('guard-' + datetime.date.today().strftime('%Y%m%d') + '.jsonl')
        with path.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + '\n')
    except Exception:
        pass


def list_targets(port=PORT):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f'http://127.0.0.1:{port}/json/list', timeout=3) as response:
        return json.load(response)


def is_app_document(target) -> bool:
    url = target.get('url', '')
    return target.get('type') == 'page' and url.startswith('app://-/') and target.get('webSocketDebuggerUrl', '').startswith('ws://127.0.0.1:')


def host_log_files():
    """Current host logs (main process); newest first."""
    files = []
    for day in (datetime.date.today(), datetime.date.today() - datetime.timedelta(days=1)):
        folder = HOST_LOGS / f'{day:%Y}' / f'{day:%m}' / f'{day:%d}'
        if folder.is_dir():
            files.extend(folder.glob('codex-desktop-*-t0-*.log'))
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:3]


def host_routed(request_id: str, started_at_ms: float | None) -> bool:
    """True when the host logged routing this reply to a live window after the
    request started. This shows the host sent it; it does not prove where it
    was lost, and the guard only uses it to re-read sooner."""
    if not re.fullmatch(r'[0-9a-zA-Z:-]{8,80}', request_id):
        return False
    wanted = request_id.encode()
    not_before = (started_at_ms or 0) / 1000 - 2
    for path in host_log_files():
        try:
            with path.open('rb') as handle:
                size = handle.seek(0, os.SEEK_END)
                handle.seek(max(0, size - LOG_TAIL_BYTES))
                for line in handle.read().splitlines():
                    if b'response_routed' not in line or wanted not in line:
                        continue
                    match = _ROUTED.match(line)
                    if not match or match.group(2) != wanted:
                        continue
                    try:
                        stamp = datetime.datetime.fromisoformat(match.group(1).decode().replace('Z', '+00:00')).timestamp()
                    except ValueError:
                        continue
                    if stamp >= not_before:
                        return True
        except OSError:
            continue
    return False


class Session:
    """One persistent DevTools session per app document."""

    def __init__(self, target):
        self.target_id = target['id']
        self.url = target.get('url', '')
        self.socket = websocket.create_connection(target['webSocketDebuggerUrl'], timeout=15, suppress_origin=True,
                                                  http_no_proxy=['127.0.0.1', 'localhost'])
        self.counter = 0
        self.lock = threading.Lock()
        self.candidates: dict[str, tuple[float, float | None]] = {}
        parsed = self.url.split('?', 1)
        self.is_main = parsed[0] == 'app://-/index.html' and 'initialRoute' not in (parsed[1] if len(parsed) > 1 else '')
        self.blank_logged_for = None

    def call(self, method, params=None, timeout=15):
        with self.lock:
            self.counter += 1
            mine = self.counter
            self.socket.settimeout(timeout)
            self.socket.send(json.dumps({'id': mine, 'method': method, 'params': params or {}}))
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                message = json.loads(self.socket.recv())
                if message.get('id') == mine:
                    if 'error' in message:
                        raise RuntimeError(message['error'].get('message', 'cdp error'))
                    return message.get('result', {})
            raise TimeoutError(method)

    def evaluate(self, expression, timeout=15):
        result = self.call('Runtime.evaluate', {'expression': expression, 'returnByValue': True, 'awaitPromise': True}, timeout)
        if 'exceptionDetails' in result:
            raise RuntimeError('evaluate failed')
        return result.get('result', {}).get('value')

    def install(self):
        # Registered for every future document of this target (reloads included).
        # The registration only takes effect while the Page domain is enabled.
        self.call('Page.enable')
        self.call('Page.addScriptToEvaluateOnNewDocument', {'source': GUARD_AT_START})
        status = self.evaluate(GUARD)
        log({'kind': 'attached', 'target': self.target_id[:8], 'url': self.url[:80], 'guard': status and status.get('version')})

    def poll(self):
        value = self.evaluate("""(() => {
          const g = window.__codexSelfHealGuard;
          const editors = [...document.querySelectorAll('textarea, [contenteditable="true"]')];
          return { drained: g ? g.drain() : null, ready: document.readyState,
                   ageMs: Math.round(Date.now() - performance.timeOrigin),
                   blank: !!document.body && document.body.innerText.trim().length === 0 && !editors.length };
        })()""", timeout=20)
        if not isinstance(value, dict):
            return
        if self.is_main and value.get('blank') and value.get('ready') == 'complete' and value.get('ageMs', 0) > STARTUP_BLANK_LOG_SECONDS * 1000:
            # Recorded only. Reloading automatically could discard work.
            marker = value.get('ageMs') // 600000
            if self.blank_logged_for != marker:
                self.blank_logged_for = marker
                log({'kind': 'startup-blank-persist', 'target': self.target_id[:8], 'ageMs': value.get('ageMs')})
        drained = value.get('drained')
        if drained is None:
            if value.get('ready') != 'loading':
                # The document was replaced before the new-document script ran.
                self.evaluate(GUARD)
            return
        for event in drained.get('events', []):
            event = {k: v for k, v in event.items() if k not in ('t', 'startedAt')}
            log({'target': self.target_id[:8], **event})
        for event in drained.get('events', []):
            if event.get('kind') == 'candidate' and event.get('bus') == 'mcp' and isinstance(event.get('id'), str):
                self.candidates[event['id']] = (time.monotonic(), event.get('startedAt'))
        now = time.monotonic()
        for request_id, (since, started_at) in list(self.candidates.items()):
            if now - since > CONFIRM_WINDOW_SECONDS:
                self.candidates.pop(request_id, None)
                continue
            if host_routed(request_id, started_at):
                accepted = self.evaluate(f'window.__codexSelfHealGuard ? window.__codexSelfHealGuard.confirmLost({json.dumps(request_id)}) : false')
                if accepted:  # False means the reply arrived meanwhile
                    log({'kind': 'confirmed-lost', 'target': self.target_id[:8]})
                self.candidates.pop(request_id, None)

    def close(self):
        try:
            self.socket.close()
        except Exception:
            pass


def single_instance():
    """Lock byte 0 of a dedicated file; the pid goes to a separate file."""
    import msvcrt
    DATA.mkdir(parents=True, exist_ok=True)
    handle = open(DATA / 'daemon.lock', 'a+b')
    handle.seek(0)
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        return None
    try:
        (DATA / 'daemon.pid').write_text(str(os.getpid()), encoding='ascii')
    except OSError:
        pass
    return handle


def run(port=PORT, once=False):
    lock = single_instance()
    if lock is None:
        print('already running')
        return 0
    log({'kind': 'daemon-start', 'pid': os.getpid()})
    sessions: dict[str, Session] = {}
    last_seen = last_answer = time.monotonic()
    try:
        while True:
            try:
                targets = [t for t in list_targets(port) if is_app_document(t)]
                last_answer = time.monotonic()
            except Exception:
                # The port did not answer: keep the sessions and try again.
                if time.monotonic() - last_answer > GIVE_UP_WITHOUT_PORT_SECONDS:
                    log({'kind': 'daemon-exit', 'reason': 'port-unreachable'})
                    return 0
                time.sleep(POLL_SECONDS)
                continue
            if targets:
                last_seen = time.monotonic()
            elif time.monotonic() - last_seen > GIVE_UP_WITHOUT_APP_SECONDS:
                log({'kind': 'daemon-exit', 'reason': 'app-gone'})
                return 0
            live = {t['id'] for t in targets}
            for target_id in list(sessions):
                if target_id not in live:
                    sessions.pop(target_id).close()
            for target in targets:
                if target['id'] in sessions:
                    continue
                session = None
                try:
                    session = Session(target)
                    session.install()
                    sessions[target['id']] = session
                except Exception as error:
                    if session is not None:
                        session.close()
                    log({'kind': 'attach-failed', 'target': target['id'][:8], 'error': type(error).__name__})
            for target_id, session in list(sessions.items()):
                try:
                    session.poll()
                except Exception as error:
                    log({'kind': 'poll-failed', 'target': target_id[:8], 'error': type(error).__name__})
                    sessions.pop(target_id).close()
            if once:
                return 0
            time.sleep(POLL_SECONDS)
    finally:
        for session in sessions.values():
            session.close()
        lock.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=PORT)
    parser.add_argument('--once', action='store_true', help='Attach, poll once and exit (for checks).')
    args = parser.parse_args(argv)
    return run(args.port, args.once)


if __name__ == '__main__':
    sys.exit(main())
