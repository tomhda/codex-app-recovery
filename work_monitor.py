"""What Codex is working on, read from its own conversation records.

The records under ~/.codex/sessions are written by the app-server while it
works, independently of the Codex window. They answer "is it still working?"
even when the window shows nothing new.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path

from i18n import tr

CODEX_HOME = Path.home() / '.codex'
SESSIONS = CODEX_HOME / 'sessions'
INDEX = CODEX_HOME / 'session_index.jsonl'
TAIL_BYTES = 2 * 1024 * 1024
FIRST_SCAN_BYTES = 256 * 1024 * 1024  # turn start/end markers: scanned once, then only appended bytes
LOOKBACK_SECONDS = 6 * 3600     # records older than this are not read
SHOW_ENDED_SECONDS = 30 * 60    # finished or stopped work stays listed this long
QUIET_SECONDS = 5 * 60          # running work with no record for this long is flagged


def _tail(path: Path, size: int) -> bytes:
    with open(path, 'rb') as handle:
        handle.seek(0, 2)
        length = handle.tell()
        handle.seek(max(0, length - size))
        data = handle.read()
    if length > size:
        data = data.split(b'\n', 1)[1] if b'\n' in data else b''
    return data


def _records(path: Path, size: int = TAIL_BYTES):
    for line in _tail(path, size).splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            yield record


def _time(value) -> datetime.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None


def titles() -> dict[str, str]:
    names = {}
    if not INDEX.exists():
        return names
    for record in _records(INDEX, 1024 * 1024):
        if isinstance(record.get('id'), str) and isinstance(record.get('thread_name'), str):
            names[record['id']] = record['thread_name']
    return names


HEAD_BYTES = 512 * 1024
_marks: dict[str, dict] = {}
_MARKER_KINDS = (b'"task_started"', b'"task_complete"', b'"turn_aborted"')


def markers(path: Path) -> dict:
    """Latest turn start/end in the whole record; only new bytes are read after the first call."""
    key = str(path)
    mark = _marks.setdefault(key, {'pos': 0, 'state': None, 'started': None, 'ended': None})
    with open(path, 'rb') as handle:
        handle.seek(0, 2)
        size = handle.tell()
        if size < mark['pos']:
            mark.update(pos=0, state=None, started=None, ended=None)
        start = max(mark['pos'], size - FIRST_SCAN_BYTES)
        handle.seek(start)
        data = handle.read(size - start)
    end = data.rfind(b'\n') + 1
    for line in data[:end].splitlines():
        if not any(kind in line for kind in _MARKER_KINDS):
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        payload = record.get('payload') if isinstance(record.get('payload'), dict) else {}
        when = _time(record.get('timestamp'))
        if record.get('type') != 'event_msg' or when is None:
            continue
        if payload.get('type') == 'task_started':
            mark.update(state='running', started=when, ended=None)
        elif payload.get('type') == 'task_complete':
            mark.update(state='done', ended=when)
        elif payload.get('type') == 'turn_aborted':
            mark.update(state='stopped', ended=when)
    mark['pos'] = start + end
    return mark


_heads: dict[str, dict] = {}


def head_info(path: Path) -> dict:
    """Who started the record and its first instruction (cached once known)."""
    key = str(path)
    if key in _heads:
        return _heads[key]
    info = {'kind': 'chat', 'prompt': None}
    with open(path, 'rb') as handle:
        data = handle.read(HEAD_BYTES)
    for line in data.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        payload = record.get('payload') if isinstance(record, dict) and isinstance(record.get('payload'), dict) else {}
        if record.get('type') == 'session_meta':
            source = payload.get('source')
            if payload.get('thread_source') == 'guardian_review' or (isinstance(source, dict) and 'subagent' in source):
                info['kind'] = 'subagent'
            elif source == 'exec':
                info['kind'] = 'exec'
        item = payload.get('item') if isinstance(payload.get('item'), dict) else {}
        if record.get('type') == 'event_msg' and payload.get('type') == 'item_completed' and item.get('type') == 'UserMessage':
            texts = [part.get('text') for part in item.get('content') or [] if isinstance(part, dict) and isinstance(part.get('text'), str)]
            lines = [text.strip().lstrip('#').strip() for text in '\n'.join(texts).splitlines()]
            first = next((text for text in lines if text), '')
            info['prompt'] = first[:40] + ('…' if len(first) > 40 else '') if first else None
            break
    if info['prompt'] or info['kind'] != 'chat' or len(data) >= HEAD_BYTES:
        _heads[key] = info
    return info


def read_thread(path: Path, size: int = TAIL_BYTES) -> dict:
    """The latest turn in one conversation record."""
    turn = {'state': None, 'started': None, 'ended': None, 'last': None, 'step': None, 'tools': 0}
    for record in _records(path, size):
        when = _time(record.get('timestamp'))
        if when is None:
            continue
        turn['last'] = when
        payload = record.get('payload') if isinstance(record.get('payload'), dict) else {}
        kind = payload.get('type')
        if record.get('type') == 'event_msg':
            if kind == 'task_started':
                turn.update(state='running', started=when, ended=None, step=None, tools=0)
            elif kind == 'task_complete':
                turn.update(state='done', ended=when)
            elif kind == 'turn_aborted':
                turn.update(state='stopped', ended=when)
        elif record.get('type') == 'response_item' and turn['state'] in (None, 'running'):
            if kind == 'reasoning':
                summary = [s.get('text') for s in payload.get('summary') or [] if isinstance(s, dict) and s.get('text')]
                turn['step'] = ('thinking', summary[-1].strip('* ') if summary else None)
            elif kind in ('custom_tool_call', 'function_call'):
                turn['step'] = ('tool', payload.get('name'))
                turn['tools'] += 1
            elif kind in ('custom_tool_call_output', 'function_call_output'):
                turn['step'] = ('result', None)
            elif kind == 'message' and payload.get('role') == 'assistant':
                turn['step'] = ('writing', None)
    if turn['state'] is None and turn['last'] is not None:
        # The turn began before the part of the record that was read.
        turn['state'] = 'running'
    return turn


def snapshot(now: datetime.datetime | None = None, limit: int = 5) -> list[dict]:
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if not SESSIONS.exists():
        return []
    folders = {SESSIONS / f'{day:%Y/%m/%d}' for day in (now.astimezone(), now.astimezone() - datetime.timedelta(days=1))}
    names = titles()
    items = []
    for folder in folders:
        if not folder.is_dir():
            continue
        for path in folder.glob('rollout-*.jsonl'):
            try:
                if now.timestamp() - path.stat().st_mtime > LOOKBACK_SECONDS:
                    continue
                turn = read_thread(path)
                if turn['state'] == 'running' and turn['started'] is None:
                    marks = markers(path)
                    if marks['state'] == 'running':
                        turn['started'] = marks['started']
                    elif marks['state'] is not None:
                        turn.update(state=marks['state'], ended=marks['ended'])
            except OSError:
                continue
            if turn['last'] is None:
                continue
            head = head_info(path)
            if head['kind'] == 'subagent':
                continue  # Codex's own helpers (for example approval reviews) belong to another chat
            if turn['state'] != 'running' and (now - (turn['ended'] or turn['last'])).total_seconds() > SHOW_ENDED_SECONDS:
                continue
            thread_id = path.stem[-36:]
            title = names.get(thread_id) or head['prompt'] or tr('（名前のない会話）')
            if head['kind'] == 'exec':
                title = tr('［コマンドラインのCodex］{title}').format(title=head['prompt'] or tr('（指示を読めません）'))
            items.append({**turn, 'id': thread_id, 'title': title})
    items.sort(key=lambda item: (item['state'] != 'running', -(item['last'].timestamp())))
    return items[:limit]


def _span(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return tr('{n}秒').format(n=seconds)
    if seconds < 3600:
        return tr('{n}分').format(n=seconds // 60)
    return tr('{h}時間{m}分').format(h=seconds // 3600, m=seconds % 3600 // 60)


def _step(step) -> str:
    if not step:
        return tr('準備中')
    kind, detail = step
    if kind == 'thinking':
        return tr('考え中：{summary}').format(summary=detail) if detail else tr('考え中')
    if kind == 'tool':
        return tr('コマンドを実行中') if detail in ('exec', 'shell', 'exec_command') else tr('ツールを実行中（{name}）').format(name=detail)
    if kind == 'result':
        return tr('実行結果を確認中')
    return tr('返答を書いています')


def describe(item: dict, now: datetime.datetime | None = None) -> str:
    now = now or datetime.datetime.now(datetime.timezone.utc)
    local = lambda moment: moment.astimezone().strftime('%H:%M')
    if item['state'] == 'done':
        return tr('完了 {time}  {title}').format(time=local(item['ended']), title=item['title'])
    if item['state'] == 'stopped':
        return tr('停止 {time}  {title}').format(time=local(item['ended']), title=item['title'])
    quiet = (now - item['last']).total_seconds()
    lines = [tr('実行中  {title}').format(title=item['title'])]
    started = tr('{time}開始（{span}経過）').format(time=local(item['started']), span=_span((now - item['started']).total_seconds())) if item['started'] else ''
    detail = tr('最終記録 {span}前・{step}').format(span=_span(quiet), step=_step(item['step']))
    lines.append('    ' + tr('・').join(part for part in (started, detail) if part))
    if quiet >= QUIET_SECONDS:
        lines.append('    ' + tr('{n}分以上、作業の記録が増えていません。長いコマンドの実行中か、止まっている可能性があります。').format(n=int(quiet // 60)))
    return '\n'.join(lines)


def summary_text(now: datetime.datetime | None = None) -> str:
    items = snapshot(now)
    if not items:
        return tr('この30分に動いた作業はありません。')
    return '\n'.join(describe(item, now) for item in items)
