"""Read the self-heal guard log and turn records into short user-facing lines."""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path

from i18n import tr

LOG_DIR = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'CodexAppRecovery' / 'guard'

# What the request was for, in words a user recognises. Unknown methods fall
# back to a generic phrase; internal names are never shown.
_LABELS = {
    'thread/queue/list': '送信キューの読み込み',
    'thread/read': 'チャット履歴の読み込み',
    'thread/turns/list': 'チャット履歴の読み込み',
    'thread/items/list': 'チャット履歴の読み込み',
    'thread/list': 'チャット一覧の読み込み',
    'config/read': '設定の読み込み',
    'configRequirements/read': '設定の読み込み',
    'skills/list': 'スキル一覧の読み込み',
    'plugin/installed': 'プラグイン一覧の読み込み',
    'app/read': 'アプリ連携の読み込み',
    'app/installed': 'アプリ連携の読み込み',
    'account/read': 'アカウント情報の読み込み',
    'getAuthStatus': 'ログイン状態の確認',
    'model/list': 'モデル一覧の読み込み',
    'permissionProfile/list': '権限設定の読み込み',
    'thread/settings/update': '権限・モデル設定の保存',
    'thread/queue/delete': '送信キューの削除',
    'codex-home': '作業フォルダ情報の読み込み',
    'get-global-state': '保存データの読み込み',
    'set-global-state': '保存データの書き込み',
    'list-automations': 'オートメーション一覧の読み込み',
    'inbox-items': '通知の読み込み',
    'git-origins': 'Git情報の読み込み',
    'locale-info': '表示言語の読み込み',
    'codex-command-keymap-state': 'キーボードショートカットの読み込み',
    'paths-exist': 'フォルダの確認',
    'mcpServerStatus/list': 'MCPサーバーの状態確認',
    'hooks/list': 'フック一覧の読み込み',
    'experimentalFeature/list': '機能一覧の読み込み',
    'windowsSandbox/readiness': 'サンドボックスの状態確認',
}


def label(event: dict) -> str:
    key = event.get('method') or event.get('path') or ''
    return tr(_LABELS.get(key, 'アプリ内部の処理'))


def describe(event: dict) -> str | None:
    """One line for the activity list, or None for records the user need not see."""
    kind = event.get('kind')
    if kind == 'recovered':
        return tr('{what}の応答が届かなかったため、取り直しました。').format(what=label(event))
    if kind == 'failed-lost':
        return tr('{what}の応答が届かなかったため、待機を打ち切りました。画面で操作をやり直してください。').format(what=label(event))
    if kind == 'resume-fix':
        return tr('停止後の「再開」を補正して、キューを送信しました。')
    if kind == 'init-snapshot-requested':
        return tr('起動時の初期化情報を取り直しました（ロゴのまま止まる不具合の補正）。')
    if kind == 'startup-blank-reload':
        return tr('起動画面のまま止まっていたため、画面を読み直しました。')
    if kind == 'transfer-reack':
        return tr('画面への大きなデータの受け渡しが途中で止まっていたため、再開させました。')
    if kind == 'channel-stall-reload':
        return tr('Codexからの応答が画面に届かなくなっていたため、画面を読み直しました。')
    if kind == 'channel-stall':
        return tr('Codexからの応答が画面に届いていません。入力中の文章を控えてから「画面を読み直す」を押してください。')
    if kind == 'startup-blank-persist':
        return tr('起動画面のまま2分以上たっています。「今すぐ点検」を押してください。')
    return None


def recent(limit: int = 30, days: int = 2) -> list[tuple[datetime.datetime, str]]:
    """Newest-first (time, text) pairs from the last `days` daily logs."""
    lines: list[str] = []
    today = datetime.date.today()
    for offset in range(days - 1, -1, -1):
        path = LOG_DIR / ('guard-' + (today - datetime.timedelta(days=offset)).strftime('%Y%m%d') + '.jsonl')
        try:
            lines.extend(path.read_text(encoding='utf-8', errors='replace').splitlines()[-2000:])
        except OSError:
            continue
    items = []
    for line in reversed(lines):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        text = describe(event)
        if text is None:
            continue
        try:
            when = datetime.datetime.fromisoformat(event['time'])
        except (KeyError, ValueError):
            continue
        items.append((when, text))
        if len(items) >= limit:
            break
    return items


def count_today() -> int:
    today = datetime.date.today()
    return sum(1 for when, _ in recent(limit=1000, days=1) if when.date() == today)
