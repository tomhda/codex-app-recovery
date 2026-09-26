"""Japanese/English UI text and per-user language preference."""
import json
import locale
import os
from pathlib import Path
import sys
import tempfile

EN = {
    '止まった読み込みを再取得します。入力欄のない起動スピナーが続く場合は、画面を一度だけ読み直します。再起動が必要な場合は確認します。': 'Retry stalled reads. If the startup spinner persists without an editor, reload the screen once. Reopening the app requires confirmation.',
    '黒画面／起動時のグルグル／ブラウザ・自動化が使えない': 'Black screen / startup spinner / browser or automations unavailable',
    '起動時の読み込み表示が続いています。': 'The startup loading indicator is still visible.',
    '起動時の読み込み停止を確認しました。画面を一度だけ読み直しています…': 'Startup is stuck at the loading indicator. Reloading the screen once…',
    'まだ復旧結果を確認できていません。\n\n': 'The recovery outcome has not been confirmed yet.\n\n',
    '\n\nこの表示のあと、数十秒待つとアプリが回復した報告があります。まず30〜60秒ほど待って、Codexの画面を確認してください。回復時間を保証するものではありません。\n\n画面が戻ったら「状態だけ調べる」で確認してください。戻らなければ「まず復旧を試す」をもう一度押してください。連続して再起動する必要はありません。': '\n\nA user reported that the app recovered tens of seconds after this message. First wait about 30–60 seconds, then check the Codex window. This is not a guaranteed recovery time.\n\nIf the screen returns, select Check status only. Otherwise, try Try recovery once more. Do not repeatedly restart the app.',
    'Codex 復旧': 'Codex App Recovery',
    'Codex 復旧 — 非公式 v': 'Codex App Recovery — Unofficial v',
    '症状に合う操作を選んでください。迷ったら、一番上から。': 'Choose the action that matches your issue. Start with the first one.',
    'まずはこちら': 'Start here',
    '黒画面／内蔵ブラウザ・オートメーションが使えない': 'Black screen / browser or automations unavailable',
    '止まった読み込みを取り直します。Codexを終了せずに試せます。': 'Retry stalled reads without closing Codex.',
    'モデル・effortなどの表示欠落も確認して、止まった読み込みを取り直します。接続準備が必要な場合は確認を表示します。': 'Retry stalled reads and check missing model, effort, or context controls. Connection setup asks for confirmation when needed.',
    'まず復旧を試す': 'Try recovery',
    '画面が戻らないとき': 'If the screen is still broken',
    '上の復旧を試しても、黒画面・表示崩れが残る': 'The window is still black or incorrectly displayed',
    '画面全体を読み直してから復旧を試します。未送信の文章は先に控えてください。': 'Reload the screen, then try recovery. Save unsent text first.',
    '画面を読み直す': 'Reload screen',
    '接続できないとき': 'If the tool cannot connect',
    '「接続できません」と出た／Codexが起動していない': 'Connection unavailable / Codex is not running',
    'Codexを開き直して、復旧を試します。\n終了が必要な場合、実行中のタスクは中断されます。': 'Reopen Codex and try recovery.\nIf it must close, running tasks will be interrupted.',
    'Codexを開き直して復旧': 'Reopen and recover',
    '結果・次にすること': 'Results and next steps',
    '状態だけ調べる': 'Check status only',
    '「状態だけ調べる」は確認のみ。復旧や再起動はしません。': 'Check status only does not repair or restart the app.',
    'まだ操作していません。\n\n黒画面でも、内蔵ブラウザ・オートメーションの停止でも、まず一番上の「まず復旧を試す」を押してください。\n\nここに結果と次の操作を表示します。': 'No action has been taken.\n\nFor a black screen or unavailable browser/automations, start with Try recovery.\n\nResults and suggested next steps will appear here.',
    '接続できない場合は、Codexアプリを終了して起動し直し、復旧を試します。\n実行中のタスクは中断されます。入力中の文章を控え、タスクの完了を確認してください。\n\n既に接続できる場合は、アプリを終了せず復旧を試します。\n\n続けますか？': 'If the tool cannot connect, it will close and reopen Codex, then try recovery.\nRunning tasks will be interrupted. Save unsent text and let tasks finish first.\n\nIf already connected, recovery runs without closing the app.\n\nContinue?',
    '画面の再読み込み': 'Reload screen',
    'Codexの画面を再読み込みします。\n入力中の未送信メッセージがあれば、先に控えてください。\n\n続けますか？': 'Reload the Codex screen.\nSave any unsent messages first.\n\nContinue?',
    '接続しています…': 'Connecting…',
    '処理を完了できませんでした。\n\n': 'The operation could not be completed.\n\n',
    '\n\n接続できない場合は「Codexを開き直して復旧」を使ってください。': '\n\nIf the connection is unavailable, use Reopen and recover.',
    '復旧処理中': 'Recovery in progress',
    '処理が完了するまで、このウィンドウを開いておいてください。': 'Keep this window open until the operation finishes.',
    '復旧ウィンドウは既に開いています。タスクバーから開いてください。': 'The recovery window is already open. Select it from the taskbar.',
    '画面：': 'Screen: ',
    '本文・操作ボタンが見つかりません': 'No content or visible controls found',
    '画面の内容を確認できました（実際の表示も確認してください）': 'Content found (also check the visible app window)',
    '内蔵ブラウザ：': 'In-app browser: ',
    'オートメーション：': 'Automations: ',
    '有効': 'Enabled',
    '有効を確認できません': 'Not confirmed enabled',
    '内蔵ブラウザ・オートメーション：機能一覧の読み込みが未完了です': 'Browser / automations: feature-list loading is incomplete',
    '設定の一部を読み込めていません。重要な作業の前にモデル・権限・作業先を確認してください。': 'Some settings could not be loaded. Verify the model, permissions and workspace before important work.',
    '設定の読み込みが続いています。': 'Settings are still loading.',
    '新規チャットのモデル・effort表示が一部欠けています。': 'Some model or effort controls are missing from the new chat.',
    'コンテキスト使用量は未取得です。未送信チャットでは通常の状態の場合があります。': 'Context usage is unavailable. This can be normal before a new chat has messages.',
    'コンテキスト使用量の表示は現在隠れています。未復旧の可能性があります。': 'Context usage is currently hidden and may not be recovered.',
    'コンテキスト使用量の表示状態を判断できません。': 'The context-usage display state cannot be determined.',
    'モデル・effort表示の復旧を試してください。': 'Try recovery for the model and effort controls.',
    '再読み込みを拒否しました。選んだ処理は実行していません。': 'Reload was declined. The selected action was not run.',
    'ブラウザのページ表示と、オートメーションの次回実行はアプリで確認してください。': 'Check actual browser navigation and the next automation run in Codex.',
    '「まず復旧を試す」を押してください。': 'Select Try recovery.',
    '「画面を読み直す」を試してください。': 'Try Reload screen.',
    '画面の再読み込みでも戻っていません。この結果をCodex CLIに伝えてください。': 'Reloading did not restore the screen. Share this result with Codex CLI for further diagnosis.',
    '\n次に：': '\nNext: ',
    '\n次に：モデル・effort表示の復旧を試してください。': '\nNext: Try recovery for the model and effort controls.',
    '\n次に：Codexの画面を開いて確認してください。正常なら、このウィンドウは閉じて構いません。': '\nNext: Check the Codex window. If it looks normal, you can close this recovery window.',
    'Codexの画面を再読み込みしています…': 'Reloading the Codex screen…',
    '画面と機能の状態を確認しています…': 'Checking the screen and capabilities…',
    '止まった読み込みを確認しています…': 'Checking for stalled reads…',
    '内蔵ブラウザ・オートメーション': 'Browser / automations',
    '設定の読み込み': 'Settings',
    'モデル一覧': 'Model list',
    'モデル：': 'Model: ',
    'effort：': 'Effort: ',
    'コンテキスト使用量：': 'Context usage: ',
    '表示': 'Visible',
    '未表示': 'Not visible',
    '不明': 'Unknown',
    '診断接続が必要です': 'Diagnostic connection required',
    'この起動では接続準備が必要です。続けるとCodexを終了して診断接続付きで開き直し、選んだ処理を続行します。\n\n実行中のタスクは中断されます。続けますか？': 'This launch needs connection preparation. Continuing will close Codex, reopen it with a diagnostic connection, and continue the selected action.\n\nRunning tasks will be interrupted. Continue?',
    '接続準備を拒否しました。選んだ処理は実行していません。': 'Connection preparation was declined. The selected action was not run.',
    'アプリの画面準備が完了していません。': 'The app screen is not ready yet.',
    '画面の準備': 'Screen preparation',
    'を復旧しています…': ' recovery in progress…',
    '診断ログを保存できませんでした。復旧処理の結果には影響しません。': 'Could not save the diagnostic log. The recovery result is unaffected.',
    '診断接続は既にあります。アプリを終了せず復旧します。': 'Already connected. Trying recovery without closing the app.',
    'Codexを接続可能な状態で起動しています…': 'Starting Codex with a diagnostic connection…',
    '接続を確認できませんでした。Codexを手動で開いてください。この版では診断接続を利用できない可能性があります。': 'Could not establish a connection. Open Codex manually. This build may not expose a diagnostic connection.',
    'Windows側の状態を取得できません。\n': 'Could not read Windows app state.\n',
    'このツールからCodexに接続できません。通常起動のCodexには診断接続がない場合があります。下の「Codexを開き直して復旧」を押してください。': 'The tool cannot connect to Codex. A normal Codex launch may not expose the diagnostic connection. Select Reopen and recover below.',
    'このツールからCodexに接続できません。': 'The tool cannot connect to Codex.',
    '診断ポートが別のアプリ、またはローカル以外の接続に使われています。変更せず停止しました。': 'The diagnostic port belongs to another app or is not loopback-only. Stopped without changes.',
    'Codexのメイン画面を一意に特定できません。変更せず停止しました。': 'Could not uniquely identify the Codex main page. Stopped without changes.',
    '診断接続先がローカルではありません。': 'The diagnostic endpoint is not local.',
    '診断接続の操作に失敗しました。': 'The diagnostic operation failed.',
    'アプリからの応答がありません。': 'The app did not respond.',
    'アプリの状態を読み取れませんでした。': 'Could not read app state.',
    'Codex の画面を確認できません。': 'Could not find the Codex page.',
    'このバージョンの画面構造には対応していません。': 'This app version has an unsupported page structure.',
    '対象の機能一覧を一意に特定できません。変更せず停止しました。': 'Could not uniquely identify the feature-list client. Stopped without changes.',
    '対象の機能一覧を一意に特定できません。': 'Could not identify the feature-list client.',
    '診断接続の期限を超過しました。': 'The diagnostic connection deadline was exceeded.',
    '未対応の操作です。': 'Unsupported operation.',
    '復旧対象外のクエリです。': 'This query is outside the recovery scope.',
    'スタートメニューにショートカットを追加しますか？': 'Add a shortcut to the Start menu?',
    'デスクトップにもショートカットを追加しますか？': 'Also add a desktop shortcut?',
    '言語を保存できませんでした。': 'Could not save the language preference.',
}


def settings_path():
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'CodexAppRecovery' / 'settings.json'


def system_language():
    if sys.platform == 'win32':
        try:
            import ctypes
            return 'ja' if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3ff == 0x11 else 'en'
        except (AttributeError, OSError):
            pass
    return 'ja' if (locale.getlocale()[0] or '').lower().startswith('ja') else 'en'


def resolve_language(override=None):
    if override in ('ja', 'en'):
        return override
    try:
        saved = json.loads(settings_path().read_text(encoding='utf-8')).get('language')
        if saved in ('ja', 'en'):
            return saved
    except (OSError, ValueError, AttributeError):
        pass
    return system_language()


def save_language(language):
    if language not in ('ja', 'en'):
        raise ValueError('Unsupported language')
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    data['language'] = language
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            json.dump(data, file, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


_language = resolve_language()


def set_language(language):
    global _language
    if language not in ('ja', 'en'):
        raise ValueError('Unsupported language')
    _language = language


def get_language():
    return _language


def tr(message):
    return EN.get(message, message) if _language == 'en' else message
