"""Japanese/English UI text and per-user language preference."""
import json
import locale
import os
from pathlib import Path
import sys
import tempfile

EN = {
    'Codex 復旧': 'Codex Recovery',
    'Codexからの承認・回答依頼': 'Codex approval / question',
    'Codexがガードなしで起動しています。「ガード付きで開き直す」を押してください。': 'Codex is running without the guard. Select Restart with guard.',
    'Codexがガードなしで起動しています。いったん終了して、ガード付きで起動し直しますか？実行中の作業は中断されます。': 'Codex is running without the guard. Close it and start it again with the guard? Running work will be interrupted.',
    'Codexが応答しないため、強制的に終了しています…': 'Codex is not responding; forcing it to close…',
    'Codexが起動していません。「Codexを起動」を押してください。': 'Codex is not running. Select Start Codex.',
    'Codexが起動画面のまま止まっています。画面を一度読み直しますか？': 'Codex is stuck on the startup screen. Reload the window once?',
    'Codexのメイン画面が見つかりません。少し待ってから、もう一度お試しください。': 'The Codex main window was not found. Wait a moment and try again.',
    'Codexのメイン画面を特定できません。少し待ってから、もう一度お試しください。': 'The Codex main window could not be identified. Wait a moment and try again.',
    'Codexの画面を読み直します。実行中の作業は続きますが、入力中の未送信の文章は消えることがあります。\n\n続けますか？': 'The Codex window will reload. Running work continues, but unsent text in the message box may be lost.\n\nContinue?',
    'Codexはガード付きで起動しています。': 'Codex is already running with the guard.',
    'Codexは自己修復ガードなしで起動しています。\n\nガードを付けるには、Codexをいったん終了して起動し直します。実行中の作業がある場合は「いいえ」を選び、区切りがついてから開き直してください。\n\n今すぐ開き直しますか？': 'Codex is running without the self-heal guard.\n\nAdding the guard requires closing and restarting Codex. If work is running, choose No and restart once it reaches a stopping point.\n\nRestart now?',
    'Codexは起動しましたが、ガードを接続できませんでした。もう一度「Codexを起動」を押してください。': 'Codex started, but the guard could not connect. Select Start Codex again.',
    'Codexをいったん終了して、ガード付きで起動し直します。\n実行中の作業は中断されます。入力中の文章を控え、作業の区切りを確認してから続けてください。\n\n続けますか？': 'Codex will close and start again with the guard.\nRunning work will be interrupted. Copy any unsent text and make sure your work is at a stopping point first.\n\nContinue?',
    'Codexをガード付きで起動しています…': 'Starting Codex with the guard…',
    'Codexをガード付きで起動しました。': 'Started Codex with the guard.',
    'Codexを終了しています…': 'Closing Codex…',
    'Codexを終了できませんでした。通知領域のCodexアイコンから終了してから、もう一度お試しください。': 'Codex could not be closed. Quit it from its notification-area icon, then try again.',
    'Codexを起動': 'Start Codex',
    'Codexアプリが見つかりません。Microsoft StoreでChatGPTをインストールしてください。': 'The Codex app was not found. Install ChatGPT from the Microsoft Store.',
    'Codex（ガード付き）': 'Codex (guarded)',
    'Git情報の読み込み': 'loading Git information',
    'Language / 言語': 'Language / 言語',
    'MCPサーバーの状態確認': 'checking MCP server status',
    '{count}件': '{count}',
    '{what}の応答が届かなかったため、取り直しました。': 'The reply to {what} never arrived, so it was requested again.',
    '{what}の応答が届かなかったため、待機を打ち切りました。画面で操作をやり直してください。': 'The reply to {what} never arrived, so the wait was ended. Repeat the action in Codex.',
    'あなた': 'You',
    'ここに操作の結果を表示します。': 'Results appear here.',
    'まだありません。': 'None yet.',
    'アカウント情報の読み込み': 'loading account information',
    'アプリ内部の処理': 'an internal app request',
    'アプリ連携の読み込み': 'loading connected apps',
    'エラー': 'Error',
    'オートメーション一覧の読み込み': 'loading automations',
    'ガード付きで開き直す': 'Restart with guard',
    'キーボードショートカットの読み込み': 'loading keyboard shortcuts',
    'サンドボックスの状態確認': 'checking the sandbox',
    'スキル一覧の読み込み': 'loading skills',
    'スタートメニューにショートカットを追加しますか？': 'Add a shortcut to the Start menu?',
    'チャット一覧の読み込み': 'loading the chat list',
    'チャット履歴の読み込み': 'loading chat history',
    'デスクトップにもショートカットを追加しますか？': 'Also add a desktop shortcut?',
    'フォルダの確認': 'checking folders',
    'フック一覧の読み込み': 'loading hooks',
    'プラグイン一覧の読み込み': 'loading plugins',
    'メッセージ（Ctrl+Enterで送信）': 'Message (Ctrl+Enter to send)',
    'モデル一覧の読み込み': 'loading models',
    'ログイン状態の確認': 'checking sign-in status',
    '・ガード：有効': '• Guard: on',
    '・応答待ち：{count}件（届かない応答はガードが自動で取り直します）': '• Waiting for replies: {count} (the guard re-requests replies that never arrive)',
    '・応答待ち：なし': '• Waiting for replies: none',
    '・画面：表示中': '• Window: showing',
    '・画面：起動画面のまま止まっていたため、読み直しました': '• Window: it was stuck on the startup screen and was reloaded',
    '・画面：起動画面のまま止まっています': '• Window: stuck on the startup screen',
    '予備チャット': 'Backup chat',
    '今すぐ点検': 'Check now',
    '今回だけ承認・回答': 'Approve once / answer',
    '今日の自動修復': 'Automatic fixes today',
    '作業フォルダ': 'Working folder',
    '作業フォルダ情報の読み込み': 'loading working-folder information',
    '使えません（ポート9222が他のプログラムに使われています）': 'Unavailable (another program is using port 9222)',
    '保存データの書き込み': 'saving app data',
    '保存データの読み込み': 'loading saved app data',
    '停止': 'Stop',
    '停止しました': 'Stopped',
    '停止を確認しています': 'Confirming interruption',
    '停止後の「再開」を補正して、キューを送信しました。': 'Corrected Resume after a stop and sent the queue.',
    '公式CLIの独立接続を使います。既存のデスクトップ送信キューは経由しません。': 'Uses an independent official CLI connection, separate from the desktop message queue.',
    '再接続は再送しません。受信が不明な送信は照合が済むまで再送できません。': 'Reconnecting does not resend. Uncertain sends cannot be retried until their receipt is reconciled.',
    '処理が終わるまで、このウィンドウを開いておいてください。': 'Keep this window open until the operation finishes.',
    '処理しています…': 'Working…',
    '受信・実行状態が不明です。接続診断と再接続で確認してください。': 'Receipt / execution state unknown. Check diagnostics and reconnect.',
    '実行中・応答を受信しています': 'Running; receiving response',
    '復旧アプリからCodexとチャット': 'Chat with Codex from Recovery',
    '復旧ウィンドウは既に開いています。タスクバーから開いてください。': 'The recovery window is already open. Use the taskbar to show it.',
    '応答待ち': 'Waiting for response',
    '承認・回答を待っています': 'Waiting for approval / answer',
    '拒否・停止': 'Decline / stop',
    '接続しています…': 'Connecting…',
    '接続・会話を復元': 'Connect / restore conversation',
    '接続診断': 'Connection diagnostics',
    '操作できません': 'Not available',
    '操作を完了できませんでした。': 'The operation could not be completed.',
    '新しい会話': 'New conversation',
    '日本語': '日本語',
    '普段はスタートメニューの「Codex（ガード付き）」から起動してください。通常のChatGPTアイコンから起動するとガードは働きません。': 'Start Codex from "Codex (guarded)" in the Start menu. The guard does not run when Codex is opened from the regular ChatGPT icon.',
    '最後の入力を再送': 'Resend last input',
    '最後の入力を同じ会話へもう一度送信します。続けますか？': 'Send the last input again to this conversation. Continue?',
    '最近の自動修復': 'Recent automatic fixes',
    '有効': 'On',
    '未接続': 'Disconnected',
    '権限・モデル設定の保存': 'saving permission and model settings',
    '権限設定の読み込み': 'loading permission settings',
    '機能一覧の読み込み': 'loading features',
    '準備中（「今すぐ点検」で有効にします）': 'Starting (Check now turns it on)',
    '点検が終わりました。': 'Check finished.',
    '無効（ガードなしで起動しています）': 'Off (Codex is running without the guard)',
    '状態と修復': 'Status & repair',
    '状態を確認しています…': 'Checking status…',
    '状態通知': 'Status',
    '独立チャット接続を閉じます。未確認の送信状態は保存し、次回接続時に照合します。実行中なら先に「停止」を使ってください。終了しますか？': 'Close the independent chat connection? Uncertain sends are saved and reconciled on the next connection. Use Stop first if a turn is running.',
    '画面': 'Window',
    '画面とガードを点検しています…': 'Checking the window and the guard…',
    '画面を読み直しました。': 'Reloaded the window.',
    '画面を読み直しました。表示を待っています…': 'Reloaded the window. Waiting for it to appear…',
    '画面を読み直す': 'Reload window',
    '確認できません': 'Unknown',
    '自己修復ガード': 'Self-heal guard',
    '表示中': 'Showing',
    '表示言語の読み込み': 'loading language settings',
    '見つかりません': 'Not found',
    '言語を保存できませんでした。': 'The language setting could not be saved.',
    '設定の読み込み': 'loading settings',
    '診断用のポート9222を別のプログラムが使っています。そのプログラムを終了してから、もう一度お試しください。': 'Another program is using diagnostic port 9222. Close that program and try again.',
    '読み取り専用から開始・操作は公式の承認に従います': 'Starts read-only; operations follow official approvals',
    '起動していません': 'Not running',
    '起動中': 'Running',
    '起動時の初期化情報を取り直しました（ロゴのまま止まる不具合の補正）。': 'Re-requested startup information (fix for getting stuck on the logo).',
    '起動画面のまま2分以上たっています。「今すぐ点検」を押してください。': 'The startup screen has shown for over 2 minutes. Select Check now.',
    '起動画面のまま止まっていたため、画面を読み直しました。': 'The window was stuck on the startup screen, so it was reloaded.',
    '起動画面のまま（{seconds}秒）': 'Stuck on the startup screen ({seconds}s)',
    '応答が届いていません（「画面を読み直す」で直ります）': 'Replies are not arriving (Reload window fixes it)',
    '作業の進み具合': 'Work in progress',
    '・': ' · ',
    'Codexの画面ではなく、会話の記録から読んでいます': 'Read from the conversation records, not from the Codex window',
    '会話の記録を読めませんでした。': 'Could not read the conversation records.',
    '（名前のない会話）': '(Untitled chat)',
    '［コマンドラインのCodex］{title}': '[Codex on the command line] {title}',
    '（指示を読めません）': '(instruction not readable)',
    '{n}秒': '{n}s',
    '{n}分': '{n} min',
    '{h}時間{m}分': '{h} h {m} min',
    '準備中': 'Getting ready',
    '考え中：{summary}': 'Thinking: {summary}',
    '考え中': 'Thinking',
    'コマンドを実行中': 'Running a command',
    'ツールを実行中（{name}）': 'Running a tool ({name})',
    '実行結果を確認中': 'Reading the result',
    '返答を書いています': 'Writing the reply',
    '完了 {time}  {title}': 'Done {time}  {title}',
    '停止 {time}  {title}': 'Stopped {time}  {title}',
    '実行中  {title}': 'Working  {title}',
    '{time}開始（{span}経過）': 'Started {time} ({span} ago)',
    '最終記録 {span}前・{step}': 'Last record {span} ago · {step}',
    '{n}分以上、作業の記録が増えていません。長いコマンドの実行中か、止まっている可能性があります。': 'No new record for {n} min or more. A long command may be running, or the work may have stopped.',
    'この30分に動いた作業はありません。': 'No work in the last 30 minutes.',
    '画面への大きなデータの受け渡しが途中で止まっていたため、再開させました。': 'A large transfer to the window had stopped partway, so it was restarted.',
    'Codexからの応答が画面に届かなくなっていたため、画面を読み直しました。': 'Replies from Codex had stopped reaching the window, so the window was reloaded.',
    'Codexからの応答が画面に届いていません。入力中の文章を控えてから「画面を読み直す」を押してください。': 'Replies from Codex are not reaching the window. Copy any text you are typing, then select Reload window.',
    '送信': 'Send',
    '送信できます': 'Ready to send',
    '送信キューの削除': 'deleting a queued message',
    '送信キューの読み込み': 'loading the message queue',
    '送信中・受信確認を待っています': 'Sending; waiting for receipt',
    '通知の読み込み': 'loading notifications',
    '選択': 'Choose',
    '開き直しを取りやめました。': 'Restart cancelled.',
    '（常駐プロセスを起動しました）': ' (started the background helper)',
    '（最終イベントから {seconds} 秒）': ' ({seconds}s since last event)',
    'Codexが終了の要求に応答しません。強制的に終了すると、未保存の作業や実行中の処理が失われることがあります。\n\n強制的に終了して、ガード付きで起動し直しますか？': 'Codex did not respond to the quit request. Forcing it to close can lose unsaved work and running tasks.\n\nForce it to close and start again with the guard?',
    '強制終了の確認': 'Confirm forced close',
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
