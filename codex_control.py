"""Control of the Codex desktop app: state, guarded launch, quit, reload, checkup.

Everything here goes through the app's own local diagnostic port
(127.0.0.1:9222) or Windows package activation. Nothing edits the app.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.parse
import urllib.request

import websocket

ROOT = Path(__file__).resolve().parent
PORT = 9222
DEBUG_ARGS = f'--remote-debugging-address=127.0.0.1 --remote-debugging-port={PORT}'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
DATA = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'CodexAppRecovery'
GUARD_SOURCE = (ROOT / 'guard.js').read_text(encoding='utf-8')
QUIT_EXPRESSION = "void window.electronBridge.sendMessageFromView({type:'quit-app',relaunch:false}); 'quit'"


class ControlError(Exception):
    """Failure with a machine-readable code; the UI maps codes to text."""

    def __init__(self, code: str, detail: str = ''):
        super().__init__(detail or code)
        self.code = code


# --- Windows package ---------------------------------------------------------

_ACTIVATE = r'''
$ErrorActionPreference='Stop'
$package=Get-AppxPackage OpenAI.Codex | Sort-Object Version -Descending | Select-Object -First 1
if(-not $package){throw 'package_missing'}
$manifest=Get-AppxPackageManifest $package
$apps=@($manifest.Package.Applications.Application | Where-Object { ($_.Executable -replace '/', '\') -ieq 'app\ChatGPT.exe' })
if($apps.Count -ne 1){throw 'package_ambiguous'}
$aumid=$package.PackageFamilyName + '!' + $apps[0].Id
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
[ComImport, Guid("45BA127D-10A8-46EA-8AB7-56EA9078943C")]
class ApplicationActivationManager {}
[ComImport, Guid("2e941141-7f97-4756-ba1d-9decde894a3d"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IApplicationActivationManager {
    [PreserveSig] int ActivateApplication([MarshalAs(UnmanagedType.LPWStr)] string appId,
        [MarshalAs(UnmanagedType.LPWStr)] string arguments, uint options, out uint processId);
}
public static class CodexActivation {
    public static uint Start(string id, string args) {
        var manager = (IApplicationActivationManager)new ApplicationActivationManager();
        uint pid;
        Marshal.ThrowExceptionForHR(manager.ActivateApplication(id, args, 0, out pid));
        return pid;
    }
}
'@
[CodexActivation]::Start($aumid, $env:CODEX_ACTIVATION_ARGS) | Out-Null
'''

_STATE = r'''
$package=Get-AppxPackage OpenAI.Codex | Sort-Object Version -Descending | Select-Object -First 1
if(-not $package){ @{installed=$false} | ConvertTo-Json -Compress; exit }
$exe=Join-Path $package.InstallLocation 'app\ChatGPT.exe'
$main=@(Get-CimInstance Win32_Process -Filter "Name='ChatGPT.exe'" | Where-Object { $_.ExecutablePath -eq $exe -and $_.CommandLine -notmatch '--type=' })
$all=@(Get-CimInstance Win32_Process -Filter "Name='ChatGPT.exe'" | Where-Object { $_.ExecutablePath -eq $exe } | ForEach-Object { $_.ProcessId })
$listener=@(Get-NetTCPConnection -State Listen -LocalPort __PORT__ -ErrorAction SilentlyContinue)
$owner=$null; $address=$null
if($listener.Count -gt 0){ $owner=[int]$listener[0].OwningProcess; $address=[string]$listener[0].LocalAddress }
@{installed=$true; version=[string]$package.Version; mainPids=@($main | ForEach-Object { [int]$_.ProcessId }); appPids=$all;
  listenerOwner=$owner; listenerAddress=$address} | ConvertTo-Json -Compress
'''.replace('__PORT__', str(PORT))


def powershell(script: str, *, args: str = '', timeout: float = 40) -> str:
    env = dict(os.environ, CODEX_ACTIVATION_ARGS=args)
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', script],
                            capture_output=True, encoding='utf-8', errors='replace', timeout=timeout,
                            creationflags=NO_WINDOW, env=env)
    if result.returncode:
        raise ControlError('powershell_failed', (result.stderr or result.stdout).strip()[:300])
    return result.stdout.strip()


def app_state() -> dict:
    """Installed version, main process ids and whether our port belongs to the app."""
    state = json.loads(powershell(_STATE) or '{}')
    state['mainPids'] = list(state.get('mainPids') or [])
    state['appPids'] = list(state.get('appPids') or [])
    state['running'] = bool(state['mainPids'])
    owner = state.get('listenerOwner')
    state['port'] = bool(owner and owner in state['appPids'] and state.get('listenerAddress') in ('127.0.0.1', '::1'))
    state['portForeign'] = bool(owner) and not state['port']
    return state


def activate(with_port: bool) -> None:
    powershell(_ACTIVATE, args=DEBUG_ARGS if with_port else '')


# --- Diagnostic port ---------------------------------------------------------

def _get_json(path: str, timeout: float = 3):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f'http://127.0.0.1:{PORT}{path}', timeout=timeout) as response:
        return json.load(response)


def list_pages() -> list[dict]:
    pages = []
    for target in _get_json('/json/list'):
        url = target.get('url', '')
        ws = target.get('webSocketDebuggerUrl', '')
        if target.get('type') == 'page' and url.startswith('app://-/') and urllib.parse.urlparse(ws).hostname == '127.0.0.1':
            pages.append(target)
    return pages


def main_page(pages=None) -> dict:
    pages = list_pages() if pages is None else pages
    main = [p for p in pages if p['url'].split('?')[0] == 'app://-/index.html' and 'initialRoute' not in p['url']]
    if len(main) != 1:
        raise ControlError('main_page_missing' if not main else 'main_page_ambiguous')
    return main[0]


def wait_for(predicate, seconds: float, step: float = 1.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if predicate():
                return True
        except Exception:
            pass
        time.sleep(step)
    return False


def port_ready() -> bool:
    try:
        return bool(list_pages())
    except Exception:
        return False


class Page:
    """One DevTools session to an app document."""

    def __init__(self, target: dict, timeout: float = 15):
        self.target = target
        self.socket = websocket.create_connection(target['webSocketDebuggerUrl'], timeout=timeout, suppress_origin=True,
                                                  http_no_proxy=['127.0.0.1', 'localhost'])
        self.counter = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        try:
            self.socket.close()
        except Exception:
            pass

    def call(self, method: str, params: dict | None = None, timeout: float = 20) -> dict:
        self.counter += 1
        mine = self.counter
        self.socket.settimeout(timeout)
        self.socket.send(json.dumps({'id': mine, 'method': method, 'params': params or {}}))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            message = json.loads(self.socket.recv())
            if message.get('id') == mine:
                if 'error' in message:
                    raise ControlError('cdp_error', str(message['error'].get('message', ''))[:200])
                return message.get('result', {})
        raise ControlError('cdp_timeout', method)

    def evaluate(self, expression: str, timeout: float = 20):
        result = self.call('Runtime.evaluate', {'expression': expression, 'returnByValue': True, 'awaitPromise': True}, timeout)
        if 'exceptionDetails' in result:
            raise ControlError('evaluate_failed')
        return result.get('result', {}).get('value')


PAGE_STATUS = """(() => {
  const g = window.__codexSelfHealGuard;
  const s = g ? g.status() : null;
  return {
    ageMs: Math.round(Date.now() - performance.timeOrigin),
    ready: document.readyState,
    blank: !!document.body && document.body.innerText.trim().length === 0 && !document.querySelector('textarea, [contenteditable="true"]'),
    guard: s ? { version: s.version, pendingMcp: s.pendingMcp, pendingFetch: s.pendingFetch,
                 oldestMs: Math.max(s.oldestMcp, s.oldestFetch), counters: s.counters } : null,
  };
})()"""


def page_status(page: Page) -> dict:
    value = page.evaluate(PAGE_STATUS)
    return value if isinstance(value, dict) else {}


# --- Guard companion -----------------------------------------------------------

def daemon_running() -> bool:
    lock = DATA / 'guard' / 'daemon.lock'
    if not lock.exists():
        return False
    import msvcrt
    try:
        with open(lock, 'a+') as handle:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return False
    except OSError:
        return True


def start_daemon() -> None:
    """Start guard_daemon.py in the background; it exits by itself if one runs."""
    pythonw = Path(sys.executable).with_name('pythonw.exe')
    subprocess.Popen([str(pythonw if pythonw.exists() else sys.executable), str(ROOT / 'guard_daemon.py')],
                     creationflags=NO_WINDOW | getattr(subprocess, 'DETACHED_PROCESS', 0), close_fds=True)


# --- Operations ----------------------------------------------------------------

def overview() -> dict:
    """Snapshot for the status panel. Never changes anything."""
    state = app_state()
    info = {'installed': state.get('installed', False), 'version': state.get('version'), 'running': state['running'],
            'port': state['port'], 'portForeign': state['portForeign'], 'daemon': daemon_running(), 'page': None}
    if state['port']:
        try:
            with Page(main_page(), timeout=5) as page:
                info['page'] = page_status(page)
        except Exception:
            info['page'] = None
    return info


def quit_app(report=lambda _: None, confirm_force=lambda: False) -> None:
    """Quit through the app's own quit request.

    Forced termination is a separate decision: confirm_force() is asked only
    when the app did not quit by itself (or has no diagnostic port), and only
    the processes seen at the start are terminated.
    """
    state = app_state()
    if not state['running']:
        return
    targets = set(state['mainPids'])
    if state['port']:
        report('quit_requested')
        try:
            with Page(main_page(), timeout=5) as page:
                page.evaluate(QUIT_EXPRESSION, timeout=5)
        except Exception:
            pass
        if wait_for(lambda: not app_state()['running'], 30, 1.5):
            return
    if not confirm_force():
        raise ControlError('quit_declined')
    report('force_quit')
    still = targets & set(app_state()['mainPids'])
    for pid in still:
        subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True, creationflags=NO_WINDOW)
    if not wait_for(lambda: not (targets & set(app_state()['mainPids'])), 20, 1.5):
        raise ControlError('quit_failed')


def launch(report=lambda _: None, confirm_restart=lambda: False, confirm_force=lambda: False) -> str:
    """Start Codex with the guard, or bring the running guarded app forward.

    Returns 'started', 'focused' or 'declined'. confirm_restart() is asked only
    when Codex runs without the diagnostic port; confirm_force() only if that
    Codex then has to be terminated.
    """
    state = app_state()
    if not state.get('installed'):
        raise ControlError('package_missing')
    if state['portForeign']:
        raise ControlError('port_in_use')
    if state['running'] and state['port']:
        start_daemon()
        activate(with_port=False)
        return 'focused'
    if state['running']:
        if not confirm_restart():
            return 'declined'
        try:
            quit_app(report, confirm_force=confirm_force)
        except ControlError as error:
            if error.code == 'quit_declined':
                return 'declined'
            raise
        time.sleep(2)
    report('starting')
    activate(with_port=True)
    if not wait_for(port_ready, 60):
        raise ControlError('port_not_ready')
    start_daemon()
    return 'started'


def reload_main(report=lambda _: None) -> None:
    with Page(main_page()) as page:
        page.call('Page.reload', {})
    report('reloaded')
    wait_for(lambda: _main_not_blank(), 40, 2)


def _main_not_blank() -> bool:
    with Page(main_page(), timeout=5) as page:
        status = page_status(page)
    return status.get('ready') == 'complete' and not status.get('blank')


def checkup(report=lambda _: None, confirm_reload=lambda: False) -> dict:
    """Make sure the guard runs and the window is usable.

    Order: guard companion, guard in the main window, the startup fixes,
    then (only if still stuck on the startup screen and the user agrees) one
    reload. Returns a summary dict for the result text.
    """
    state = app_state()
    if not state['running']:
        raise ControlError('not_running')
    if not state['port']:
        raise ControlError('no_port')
    summary = {'daemonStarted': False, 'guardInstalled': False, 'reloaded': False}
    if not daemon_running():
        start_daemon()
        summary['daemonStarted'] = True
    with Page(main_page()) as page:
        status = page_status(page)
        if not status.get('guard'):
            page.evaluate(GUARD_SOURCE)
            summary['guardInstalled'] = True
        report('checking')
        page.evaluate('window.__codexSelfHealGuard && (window.__codexSelfHealGuard.patchResume(), window.__codexSelfHealGuard.tick())')
    time.sleep(4)
    with Page(main_page()) as page:
        status = page_status(page)
    if status.get('blank') and status.get('ageMs', 0) > 20000:
        if confirm_reload():
            reload_main(report)
            summary['reloaded'] = True
            with Page(main_page()) as page:
                status = page_status(page)
    summary['status'] = status
    return summary
