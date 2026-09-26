"""Independent Windows UI for narrowly scoped Codex query recovery."""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

import websocket
from i18n import tr, get_language, set_language, resolve_language, save_language

ROOT = Path(__file__).resolve().parent
PORT = 9222
APP_VERSION = '0.3.1'
ENGINE = (ROOT / 'engine.js').read_text(encoding='utf-8')
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


class RecoveryError(Exception):
    """User-safe failure carrying a machine-readable stage and error code."""
    def __init__(self, message, code='transport_error', stage='operation'):
        super().__init__(message)
        self.code = code
        self.stage = stage


def _error(message, code, stage):
    return RecoveryError(tr(message), code=code, stage=stage)


def powershell(script: str, timeout=20):
    result = subprocess.run(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
         '[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; $ErrorActionPreference="Stop"; ' + script],
        capture_output=True, encoding='utf-8', errors='replace', timeout=timeout,
        creationflags=NO_WINDOW,
    )
    if result.returncode:
        raise RecoveryError(tr('Windows側の状態を取得できません。\n') + result.stderr.strip()[:500])
    return json.loads(result.stdout.strip())


def app_state(timeout=20):
    return powershell(r'''
    $package=Get-AppxPackage OpenAI.Codex | Sort-Object Version -Descending | Select-Object -First 1
    if(-not $package){throw 'Codex package not found'}
    $exe=Join-Path $package.InstallLocation 'app\ChatGPT.exe'
    $processes=@(Get-CimInstance Win32_Process -Filter "Name='ChatGPT.exe'" |
      Where-Object {$_.ExecutablePath -eq $exe} | ForEach-Object {
        @{id=$_.ProcessId;main=($_.CommandLine -notmatch '--type=');path=$_.ExecutablePath}
      })
    $listeners=@(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
      ForEach-Object {@{pid=$_.OwningProcess;port=$_.LocalPort;address=$_.LocalAddress}})
    @{exe=$exe;version=[string]$package.Version;processes=$processes;listeners=$listeners} | ConvertTo-Json -Depth 5 -Compress
    ''', timeout=timeout)


def validate_listener(state):
    ids = {p['id'] for p in state['processes'] if p.get('main', True)}
    listeners = state['listeners']
    if not listeners:
        raise _error('このツールからCodexに接続できません。通常起動のCodexには診断接続がない場合があります。下の「Codexを開き直して復旧」を押してください。', 'no_listener', 'connect')
    for listener in listeners:
        if listener.get('port', PORT) == PORT and (listener.get('pid') not in ids or listener.get('address') not in ('127.0.0.1', '::1')):
            raise _error('診断ポートが別のアプリ、またはローカル以外の接続に使われています。変更せず停止しました。', 'unsafe_listener', 'validate_listener')
    candidates = [p for p in listeners if p.get('pid') in ids and p.get('address') in ('127.0.0.1', '::1')]
    if not candidates:
        raise _error('このツールからCodexに接続できません。通常起動のCodexには診断接続がない場合があります。下の「Codexを開き直して復旧」を押してください。', 'no_listener', 'connect')
    unique = {(p.get('pid'), p.get('port', PORT), p.get('address')): p for p in candidates}
    if len(unique) != 1:
        raise _error('Codexの診断接続先を一意に特定できません。変更せず停止しました。', 'target_ambiguous', 'validate_listener')
    return next(iter(unique.values()))


def redacted_record(value):
    """Logs retain operational states but never query arguments or error messages."""
    if isinstance(value, list):
        return [redacted_record(item) for item in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key == 'key' and isinstance(item, list):
                result['key'] = item[:2] + ['<argument>' for _ in item[2:]]
            elif key in ('error', 'reason'):
                result[key] = '<details omitted>'
            elif key in ('cwd', 'scopeCwd', 'workspace', 'workspacePath'):
                result[key] = '<argument>'
            else:
                result[key] = redacted_record(item)
        return result
    return value


def save_record(record):
    log_dir = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'CodexAppRecovery' / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    (log_dir / (stamp + '.json')).write_text(json.dumps(redacted_record(record), ensure_ascii=False, indent=2), encoding='utf-8')


def main_page(port=PORT, address='127.0.0.1', timeout=4):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f'http://[{address}]:{port}/json' if ':' in address else f'http://{address}:{port}/json', timeout=timeout) as response:
        pages = json.load(response)
    # Selecting only the main app avoids the avatar overlay and embedded websites.
    eligible = []
    for page in pages:
        url = urllib.parse.urlparse(page.get('url', ''))
        if page.get('type') == 'page' and url.scheme == 'app' and url.netloc == '-' and url.path == '/index.html':
            route = urllib.parse.parse_qs(url.query).get('initialRoute', [''])[0]
            if not any(excluded in route.lower() for excluded in ('avatar-overlay', 'global-dictation', 'hotkey')):
                eligible.append(page)
    if len(eligible) != 1:
        raise _error('Codexのメイン画面を一意に特定できません。変更せず停止しました。', 'target_missing' if not eligible else 'target_ambiguous', 'target_discovery')
    return eligible[0]


def _retryable_connection_error(error):
    if isinstance(error, RecoveryError):
        return error.code in ('target_missing', 'transport_error', 'engine_not_ready')
    return isinstance(error, (OSError, urllib.error.URLError, websocket.WebSocketException))


def _remaining(deadline_at, cap):
    remaining = deadline_at - time.monotonic()
    if remaining <= 0:
        raise RecoveryError(tr('診断接続の期限を超過しました。'), code='transport_error', stage='deadline')
    return min(cap, remaining)


def connect_to_main(attempts=8, delay=0.6, deadline=20):
    """Discover and connect to the current main page with one wall deadline."""
    deadline_at = time.monotonic() + deadline
    last = None
    for attempt in range(attempts):
        if time.monotonic() >= deadline_at:
            break
        try:
            remaining = _remaining(deadline_at, 20)
            state = app_state(timeout=remaining)
            listener = validate_listener(state)
            address = listener.get('address', '127.0.0.1')
            port = listener.get('port', PORT)
            page = main_page(port, address, timeout=_remaining(deadline_at, 4))
            return Connection(page, port, timeout=_remaining(deadline_at, 18))
        except RecoveryError as error:
            last = error
            if error.code in ('no_listener', 'unsafe_listener', 'target_ambiguous') or not _retryable_connection_error(error):
                raise
        except (OSError, urllib.error.URLError, websocket.WebSocketException) as error:
            last = RecoveryError(tr('診断接続の操作に失敗しました。'), code='transport_error', stage='connect')
        if attempt == attempts - 1 or time.monotonic() >= deadline_at:
            break
        time.sleep(min(delay * (attempt + 1), max(0.0, deadline_at - time.monotonic())))
    if last:
        raise last
    raise RecoveryError(tr('診断接続の操作に失敗しました。'), code='transport_error', stage='connect')


class Connection:
    def __init__(self, page, port=PORT, timeout=18):
        url = page['webSocketDebuggerUrl']
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != 'ws' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1') or parsed.port != port:
            raise _error('診断接続先がローカルではありません。', 'unsafe_listener', 'connect')
        self.socket = websocket.create_connection(url, timeout=timeout, suppress_origin=True, http_no_proxy=['127.0.0.1', 'localhost', '::1'])
        self.counter = 0

    def close(self):
        self.socket.close()

    def call(self, method, params=None, timeout=20):
        self.counter += 1
        deadline = time.monotonic() + timeout
        self.socket.settimeout(max(0.05, timeout))
        self.socket.send(json.dumps({'id': self.counter, 'method': method, 'params': params or {}}))
        while time.monotonic() < deadline:
            self.socket.settimeout(max(0.1, deadline - time.monotonic()))
            message = json.loads(self.socket.recv())
            if message.get('id') == self.counter:
                if 'error' in message:
                    raise RecoveryError(tr('診断接続の操作に失敗しました。'), code='transport_error', stage='cdp')
                return message.get('result', {})
        raise RecoveryError(tr('アプリからの応答がありません。'), code='transport_error', stage='cdp')

    def engine(self, action='snapshot', timeout=20, **kwargs):
        request = json.dumps({'action': action, **kwargs}, ensure_ascii=True)
        expression = f"(async()=>{{try{{return await ({ENGINE})({request})}}catch(error){{return {{__recoveryError:{{code:typeof error?.code==='string'?error.code:'engine_error'}}}}}}}})()"
        result = self.call('Runtime.evaluate', {'expression': expression, 'returnByValue': True, 'awaitPromise': True}, timeout=timeout)
        if 'exceptionDetails' in result:
            raise RecoveryError(tr('アプリの状態を読み取れませんでした。'), code='transport_error', stage='engine')
        value = result.get('result', {}).get('value')
        if isinstance(value, dict) and value.get('__recoveryError'):
            code = value['__recoveryError'].get('code')
            messages = {'engine_not_ready': 'アプリの画面準備が完了していません。', 'ambiguous_client': '対象を一意に特定できません。'}
            raise RecoveryError(tr(messages.get(code, 'アプリの状態を読み取れませんでした。')), code=code or 'engine_error', stage='engine')
        if not isinstance(value, dict):
            raise RecoveryError(tr('アプリの状態を読み取れませんでした。'), code='engine_error', stage='engine')
        return value


def stable_candidates(first, second):
    earlier = {json.dumps(q['key'], ensure_ascii=True): q for q in first.get('queries', [])}
    result = []
    for query in second['queries']:
        previous = earlier.get(json.dumps(query['key'], ensure_ascii=True))
        if previous and all(query.get(k) == previous.get(k) for k in ('queryId', 'promiseId', 'status', 'fetch', 'updated')):
            if (query.get('eligible') is True and query.get('status') == 'pending' and
                    query.get('fetch') == 'fetching' and query.get('updated') == 0):
                if query.get('kind') in ('features', 'models', 'config-parent') or second.get('blank') or second.get('ui', {}).get('degraded', False):
                    result.append(query)
    order = {'features': 0, 'models': 1, 'config-read': 2, 'config-parent': 3, 'prepare': 4}
    return sorted(result, key=lambda q: order[q['kind']])


def stable_startup_spinner(*snapshots):
    """Reload only a repeatedly observed empty startup spinner with a ready backend."""
    if len(snapshots) < 2:
        return False
    document_ids = {item.get('ui', {}).get('documentId') for item in snapshots}
    return (None not in document_ids and len(document_ids) == 1 and
            all(item.get('blank') and item.get('ui', {}).get('startupSpinner') is True and
                item.get('settingsRead') is True and
                item.get('features', {}).get('status') == 'success' and
                item.get('features', {}).get('fetch') == 'idle' for item in snapshots))


def describe(snapshot, mode='check'):
    lines = [tr('画面：') + (tr('本文・操作ボタンが見つかりません') if snapshot['blank'] else tr('画面の内容を確認できました（実際の表示も確認してください）'))]
    features = snapshot['features']
    if snapshot.get('ui', {}).get('startupSpinner'):
        lines.append(tr('起動時の読み込み表示が続いています。'))
    if features['status'] == 'success' and features['fetch'] == 'idle':
        lines.append(tr('内蔵ブラウザ：') + (tr('有効') if features['browser'] is True else tr('有効を確認できません')))
        lines.append(tr('オートメーション：') + (tr('有効') if features['automation'] is True else tr('有効を確認できません')))
    else:
        lines.append(tr('内蔵ブラウザ・オートメーション：機能一覧の読み込みが未完了です'))
    ui = snapshot.get('ui') or {}
    if ui.get('chat'):
        for label, key in (('モデル：', 'modelPicker'), ('effort：', 'effortPicker'), ('コンテキスト使用量：', 'contextUsage')):
            value = ui.get(key)
            if value is True:
                state = '表示'
            elif value is False:
                state = '未表示'
            else:
                state = '不明'
            lines.append(tr(label) + tr(state))
        if ui.get('modelPicker') is False or ui.get('effortPicker') is False:
            lines.append(tr('新規チャットのモデル・effort表示が一部欠けています。'))
        if ui.get('contextState') == 'no_data':
            lines.append(tr('コンテキスト使用量は未取得です。未送信チャットでは通常の状態の場合があります。'))
        elif ui.get('contextState') == 'hidden':
            lines.append(tr('コンテキスト使用量の表示は現在隠れています。未復旧の可能性があります。'))
        elif ui.get('contextState') == 'unknown':
            lines.append(tr('コンテキスト使用量の表示状態を判断できません。'))
    if snapshot.get('settingsRead') is False:
        lines.append(tr('設定の一部を読み込めていません。重要な作業の前にモデル・権限・作業先を確認してください。'))
    elif snapshot.get('settingsFetching'):
        lines.append(tr('設定の読み込みが続いています。'))
    lines.append(tr('ブラウザのページ表示と、オートメーションの次回実行はアプリで確認してください。'))
    if snapshot['blank']:
        next_step = tr('「まず復旧を試す」を押してください。') if mode == 'check' else tr('「画面を読み直す」を試してください。')
        if mode == 'reload':
            next_step = tr('画面の再読み込みでも戻っていません。この結果をCodex CLIに伝えてください。')
        lines.append(tr('\n次に：') + next_step)
    elif ui.get('modelPicker') is False or ui.get('effortPicker') is False:
        next_step = (tr('「まず復旧を試す」を押してください。') if mode == 'check' else
                     tr('「画面を読み直す」を試してください。') if mode == 'repair' else
                     tr('画面の再読み込みでも戻っていません。この結果をCodex CLIに伝えてください。'))
        lines.append(tr('\n次に：') + next_step)
    else:
        lines.append(tr('\n次に：Codexの画面を開いて確認してください。正常なら、このウィンドウは閉じて構いません。'))
    return '\n'.join(lines)


def describe_error(error):
    details = str(error)[:600]
    if getattr(error, 'code', None) in ('ambiguous_client', 'target_ambiguous') or details.strip() == tr('対象の機能一覧を一意に特定できません。変更せず停止しました。'):
        return tr('まだ復旧結果を確認できていません。\n\n') + details + tr('\n\nこの表示のあと、数十秒待つとアプリが回復した報告があります。まず30〜60秒ほど待って、Codexの画面を確認してください。回復時間を保証するものではありません。\n\n画面が戻ったら「状態だけ調べる」で確認してください。戻らなければ「まず復旧を試す」をもう一度押してください。連続して再起動する必要はありません。')
    return tr('処理を完了できませんでした。\n\n') + details + tr('\n\n接続できない場合は「Codexを開き直して復旧」を使ってください。')


def _engine_snapshot(connection, attempts=8, delay=0.8, deadline=20):
    started = time.monotonic()
    last = None
    for attempt in range(attempts):
        try:
            return connection.engine(timeout=_remaining(started + deadline, 20))
        except RecoveryError as error:
            if error.code == 'transport_error':
                raise
            last = error
            if error.code != 'engine_not_ready':
                raise
        except (OSError, websocket.WebSocketException) as error:
            raise RecoveryError(tr('診断接続の操作に失敗しました。'), code='transport_error', stage='engine') from error
        elapsed = time.monotonic() - started
        if elapsed >= deadline or attempt == attempts - 1:
            raise RecoveryError(tr('アプリの画面準備が完了していません。'), code='engine_not_ready', stage='engine') from last
        time.sleep(min(delay * (attempt + 1), max(0.0, deadline - elapsed)))
    raise RecoveryError(tr('アプリの画面準備が完了していません。'), code='engine_not_ready', stage='engine') from last


def run_operation(mode, report):
    record = {'time': datetime.datetime.now().astimezone().isoformat(), 'version': None, 'mode': mode, 'actions': []}
    connection = None
    try:
        state = app_state()
        record['version'] = state.get('version')
        connection = connect_to_main()
        def snapshot():
            nonlocal connection
            try:
                return _engine_snapshot(connection)
            except RecoveryError as error:
                if error.code not in ('engine_not_ready', 'transport_error'):
                    raise
                old = connection
                try:
                    connection = connect_to_main(attempts=4, delay=0.5, deadline=8)
                finally:
                    try:
                        old.close()
                    except Exception:
                        pass
                return _engine_snapshot(connection, attempts=4, delay=0.5, deadline=8)
        if mode == 'reload':
            report(tr('Codexの画面を再読み込みしています…'))
            connection.call('Page.reload', {'ignoreCache': True})
            time.sleep(2)
            connection.close()
            connection = connect_to_main(attempts=8, delay=0.8)
        report(tr('画面と機能の状態を確認しています…'))
        first = snapshot()
        record['before'] = first
        if mode != 'check':
            report(tr('止まった読み込みを確認しています…'))
            time.sleep(5)
            second = snapshot()
            candidates = stable_candidates(first, second)
            for query in candidates:
                label = {'features': tr('内蔵ブラウザ・オートメーション'), 'config-read': tr('設定の読み込み'), 'config-parent': tr('設定の読み込み'), 'models': tr('モデル一覧'), 'prepare': tr('画面の準備')}[query['kind']]
                report(label + tr('を復旧しています…'))
                result = connection.engine('repair', key=query['key'], queryId=query['queryId'], promiseId=query['promiseId'])
                record['actions'].append(result)
                time.sleep(0.3)
            time.sleep(2)
        after = snapshot()
        if mode in ('repair', 'prepare') and stable_startup_spinner(first, second, after):
            report(tr('起動時の読み込み停止を確認しました。画面を一度だけ読み直しています…'))
            # Record the attempt before sending; never resend a possibly delivered reload.
            record['actions'].append({'action': 'startup_spinner_reload'})
            connection.call('Page.reload', {'ignoreCache': True})
            connection.close()
            connection = connect_to_main(attempts=8, delay=0.8)
            # Observe startup for a bounded period. Do not send a second reload.
            for attempt in range(8):
                time.sleep(2)
                after = snapshot()
                if not after.get('blank'):
                    break
        record['after'] = after
        return describe(after, mode)
    except RecoveryError as error:
        record['errorCode'] = error.code
        record['stage'] = error.stage
        raise
    except Exception as error:
        record['errorCode'] = 'transport_error'
        record['stage'] = 'operation'
        record['error'] = str(error)[:500]
        raise
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                record.setdefault('closeError', True)
        try:
            save_record(record)
        except OSError:
            report(tr('診断ログを保存できませんでした。復旧処理の結果には影響しません。'))


def prepare_connection(report, requested_mode='repair'):
    state = app_state()
    try:
        validate_listener(state)
    except RecoveryError as error:
        if error.code != 'no_listener':
            raise
    else:
        report(tr('診断接続は既にあります。アプリを終了せず復旧します。'))
        return run_operation(requested_mode, report)
    report(tr('Codexを接続可能な状態で起動しています…'))
    # Resolve the executable and process IDs again immediately before termination.
    powershell(r'''
    $package=Get-AppxPackage OpenAI.Codex | Sort-Object Version -Descending | Select-Object -First 1
    if(-not $package){throw 'Codex package not found'}
    $exe=Join-Path $package.InstallLocation 'app\ChatGPT.exe'
    if(-not (Test-Path -LiteralPath $exe)){throw 'Executable missing'}
    # Resolve the app by executable, not manifest order. Compile before closing Codex.
    $manifest=Get-AppxPackageManifest $package
    $apps=@($manifest.Package.Applications.Application | Where-Object { ($_.Executable -replace '/', '\') -ieq 'app\ChatGPT.exe' })
    if($apps.Count -ne 1){throw 'Codex package application is ambiguous'}
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
public static class CodexPackageActivation {
    public static uint Start(string id) {
        var manager = (IApplicationActivationManager)new ApplicationActivationManager();
        uint pid;
        int result = manager.ActivateApplication(id,
            "--remote-debugging-address=127.0.0.1 --remote-debugging-port=9222", 0, out pid);
        Marshal.ThrowExceptionForHR(result);
        return pid;
    }
}
'@
    if(@(Get-NetTCPConnection -State Listen -LocalPort 9222 -ErrorAction SilentlyContinue).Count){throw 'Port is already in use'}
    $targets=@(Get-CimInstance Win32_Process -Filter "Name='ChatGPT.exe'" | Where-Object {$_.ExecutablePath -eq $exe -and $_.CommandLine -notmatch '--type='})
    foreach($target in $targets){
      $current=Get-CimInstance Win32_Process -Filter "ProcessId=$($target.ProcessId)"
      if($current.ExecutablePath -ne $exe){throw 'Process changed'}
      & "$env:SystemRoot\System32\taskkill.exe" /PID $target.ProcessId /T /F | Out-Null
      if($LASTEXITCODE -ne 0){throw 'Could not close app'}
    }
    Start-Sleep -Seconds 2
    if(@(Get-CimInstance Win32_Process -Filter "Name='ChatGPT.exe'" | Where-Object {$_.ExecutablePath -eq $exe}).Count){throw 'App processes remain'}
    $activatedPid=[CodexPackageActivation]::Start($aumid)
    @{started=$true;pid=$activatedPid} | ConvertTo-Json -Compress
    ''', timeout=30)
    for _ in range(30):
        time.sleep(2)
        try:
            main_page()
            break
        except Exception:
            continue
    else:
        raise RecoveryError(tr('接続を確認できませんでした。Codexを手動で開いてください。この版では診断接続を利用できない可能性があります。'))
    time.sleep(5)
    return run_operation(requested_mode, report)


def gui(smoke_test=False):
    while _gui_once(smoke_test):
        pass


def _gui_once(smoke_test=False):
    import tkinter as tk
    from tkinter import messagebox, ttk
    app = tk.Tk()
    app.title(tr('Codex 復旧 — 非公式 v') + APP_VERSION)
    icon = ROOT / 'assets' / 'recovery.ico'
    if icon.exists():
        app.iconbitmap(str(icon))
    app.geometry('800x740')
    app.minsize(760, 700)
    style = ttk.Style()
    style.theme_use('vista')
    style.configure('TButton', font=('Yu Gothic UI', 11), padding=(12, 10))
    style.configure('Primary.TButton', font=('Yu Gothic UI', 11, 'bold'), padding=(12, 10))
    style.configure('TLabel', font=('Yu Gothic UI', 11))
    frame = ttk.Frame(app, padding=24)
    frame.pack(fill='both', expand=True)
    header = ttk.Frame(frame)
    header.pack(fill='x')
    ttk.Label(header, text=tr('Codex 復旧'), font=('Yu Gothic UI', 20, 'bold')).pack(side='left')
    language = ttk.Combobox(header, values=('日本語', 'English'), state='readonly', width=10)
    language.set('日本語' if get_language() == 'ja' else 'English')
    language.pack(side='right')
    ttk.Label(header, text='Language / 言語', font=('Yu Gothic UI', 9), padding=(0, 0, 8, 0)).pack(side='right')
    ttk.Label(frame, text=tr('症状に合う操作を選んでください。迷ったら、一番上から。'), padding=(0, 6, 0, 16)).pack(anchor='w')
    messages = queue.Queue()
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    busy = False
    restart = False
    poll_timer = None
    buttons = []
    output = tk.Text(frame, height=9, wrap='word', font=('Yu Gothic UI', 10), relief='flat', padx=12, pady=12, background='#f3f4f6')

    def show(text):
        output.configure(state='normal')
        output.delete('1.0', 'end')
        output.insert('1.0', text)
        output.configure(state='disabled')

    def start(mode):
        nonlocal busy
        if busy:
            return
        if mode == 'prepare' and not messagebox.askyesno(tr('Codexを開き直して復旧'), tr('接続できない場合は、Codexアプリを終了して起動し直し、復旧を試します。\n実行中のタスクは中断されます。入力中の文章を控え、タスクの完了を確認してください。\n\n既に接続できる場合は、アプリを終了せず復旧を試します。\n\n続けますか？'), parent=app):
            return
        busy = True
        language.configure(state='disabled')
        for button in buttons:
            button.configure(state='disabled')
        show(tr('接続しています…'))

        def worker():
            report = lambda text: messages.put(('progress', text))
            try:
                if mode == 'reload':
                    probe = connect_to_main()
                    probe.close()
                    messages.put(('reload_required', mode))
                    return
                result = prepare_connection(report, requested_mode=mode) if mode == 'prepare' else run_operation(mode, report)
                messages.put(('done', result))
            except RecoveryError as error:
                if error.code == 'no_listener' and mode in ('repair', 'reload'):
                    messages.put(('connection_required', mode))
                else:
                    messages.put(('done', describe_error(error)))
            except Exception as error:
                messages.put(('done', describe_error(error)))
        pool.submit(worker)

    actions = [
        (tr('まずはこちら'), tr('黒画面／起動時のグルグル／ブラウザ・自動化が使えない'),
         tr('止まった読み込みを再取得します。入力欄のない起動スピナーが続く場合は、画面を一度だけ読み直します。再起動が必要な場合は確認します。'),
         tr('まず復旧を試す'), 'repair'),
        (tr('画面が戻らないとき'), tr('上の復旧を試しても、黒画面・表示崩れが残る'),
         tr('画面全体を読み直してから復旧を試します。未送信の文章は先に控えてください。'),
         tr('画面を読み直す'), 'reload'),
        (tr('接続できないとき'), tr('「接続できません」と出た／Codexが起動していない'),
         tr('Codexを開き直して、復旧を試します。\n終了が必要な場合、実行中のタスクは中断されます。'),
         tr('Codexを開き直して復旧'), 'prepare'),
    ]
    for tag, symptom, explanation, text, mode in actions:
        card = ttk.Frame(frame, padding=(12, 10), relief='solid', borderwidth=1)
        card.pack(fill='x', pady=(0, 10))
        card.columnconfigure(0, weight=1)
        ttk.Label(card, text=tag, foreground='#526078', font=('Yu Gothic UI', 9)).grid(row=0, column=0, sticky='w')
        ttk.Label(card, text=symptom, font=('Yu Gothic UI', 10, 'bold'), wraplength=475).grid(row=1, column=0, sticky='w', pady=(2, 3))
        ttk.Label(card, text=explanation, font=('Yu Gothic UI', 10), wraplength=475).grid(row=2, column=0, sticky='w')
        button = ttk.Button(card, text=text, style='Primary.TButton' if mode == 'repair' else 'TButton', command=lambda m=mode: start(m))
        button.grid(row=0, column=1, rowspan=3, padx=(12, 0), sticky='e')
        buttons.append(button)
    result_header = ttk.Frame(frame)
    result_header.pack(fill='x', pady=(2, 6))
    ttk.Label(result_header, text=tr('結果・次にすること'), font=('Yu Gothic UI', 11, 'bold')).pack(side='left')
    check = ttk.Button(result_header, text=tr('状態だけ調べる'), command=lambda: start('check'))
    check.pack(side='right')
    buttons.append(check)
    output.pack(fill='both', expand=True)
    ttk.Label(frame, text=tr('「状態だけ調べる」は確認のみ。復旧や再起動はしません。'), foreground='#555555', font=('Yu Gothic UI', 10), padding=(0, 8, 0, 0)).pack(anchor='w')
    show(tr('まだ操作していません。\n\n黒画面でも、内蔵ブラウザ・オートメーションの停止でも、まず一番上の「まず復旧を試す」を押してください。\n\nここに結果と次の操作を表示します。'))

    def _prepare_after_consent(requested_mode):
        try:
            result = prepare_connection(lambda text: messages.put(('progress', text)), requested_mode=requested_mode)
            messages.put(('done', result))
        except Exception as error:
            messages.put(('done', describe_error(error)))

    def _run_after_confirmation(requested_mode):
        try:
            result = run_operation(requested_mode, lambda text: messages.put(('progress', text)))
            messages.put(('done', result))
        except Exception as error:
            messages.put(('done', describe_error(error)))

    def poll():
        nonlocal busy, poll_timer
        while True:
            try:
                event, text = messages.get_nowait()
            except queue.Empty:
                break
            if event == 'reload_required':
                if messagebox.askyesno(tr('画面の再読み込み'), tr('Codexの画面を再読み込みします。\n入力中の未送信メッセージがあれば、先に控えてください。\n\n続けますか？'), parent=app):
                    pool.submit(lambda: _run_after_confirmation('reload'))
                else:
                    busy = False
                    language.configure(state='readonly')
                    for button in buttons:
                        button.configure(state='normal')
                    show(tr('再読み込みを拒否しました。選んだ処理は実行していません。'))
            elif event == 'connection_required':
                requested_mode = text
                if messagebox.askyesno(tr('診断接続が必要です'), tr('この起動では接続準備が必要です。続けるとCodexを終了して診断接続付きで開き直し、選んだ処理を続行します。\n\n実行中のタスクは中断されます。続けますか？'), parent=app):
                    show(tr('Codexを接続可能な状態で起動しています…'))
                    pool.submit(lambda: _prepare_after_consent(requested_mode))
                else:
                    busy = False
                    language.configure(state='readonly')
                    for button in buttons:
                        button.configure(state='normal')
                    show(tr('接続準備を拒否しました。選んだ処理は実行していません。'))
            else:
                show(text)
            if event == 'done':
                busy = False
                language.configure(state='readonly')
                for button in buttons:
                    button.configure(state='normal')
        poll_timer = app.after(100, poll)

    def close():
        if busy:
            messagebox.showinfo(tr('復旧処理中'), tr('処理が完了するまで、このウィンドウを開いておいてください。'), parent=app)
            return
        pool.shutdown(wait=False)
        if poll_timer:
            app.after_cancel(poll_timer)
        app.destroy()
    app.protocol('WM_DELETE_WINDOW', close)
    def change_language(_event):
        nonlocal restart
        selected = 'ja' if language.get() == '日本語' else 'en'
        if busy or selected == get_language():
            return
        try:
            save_language(selected)
        except OSError:
            messagebox.showerror(tr('Codex 復旧'), tr('言語を保存できませんでした。'), parent=app)
            language.set('日本語' if get_language() == 'ja' else 'English')
            return
        set_language(selected)
        restart = True
        close()
    language.bind('<<ComboboxSelected>>', change_language)
    poll()
    if smoke_test:
        app.after(800, close)
    app.mainloop()
    return restart


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true', help='Read-only check; never restart or repair.')
    parser.add_argument('--gui-smoke', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--version', action='version', version=APP_VERSION)
    parser.add_argument('--lang', choices=('ja', 'en'), help='Display language for this launch (does not overwrite the saved choice).')
    args = parser.parse_args()
    set_language(resolve_language(args.lang))
    if sys.platform != 'win32':
        parser.exit(1, 'Codex App Recovery currently supports Windows only.\n')
    if args.check:
        sys.stdout.reconfigure(encoding='utf-8')
        print(run_operation('check', lambda _: None))
    else:
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.restype = ctypes.c_void_p
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        mutex = kernel.CreateMutexW(None, False, 'Local\\CodexAppRecoveryTool')
        if not mutex:
            raise OSError('Could not create recovery lock')
        try:
            if ctypes.get_last_error() == 183:
                ctypes.windll.user32.MessageBoxW(None, tr('復旧ウィンドウは既に開いています。タスクバーから開いてください。'), tr('Codex 復旧'), 0)
            else:
                gui(smoke_test=args.gui_smoke)
        finally:
            kernel.CloseHandle(mutex)
