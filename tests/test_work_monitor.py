import datetime
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import i18n
import work_monitor

UTC = datetime.timezone.utc
THREAD = '01a0fab8-bba7-7ea3-9b8f-8b2be5cd8d2d'


def stamp(moment):
    return moment.strftime('%Y-%m-%dT%H:%M:%S.000Z')


class WorkMonitorTests(unittest.TestCase):
    def setUp(self):
        i18n.set_language('ja')
        self.addCleanup(i18n.set_language, i18n.resolve_language(None))
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name)
        self.now = datetime.datetime(2026, 10, 2, 4, 10, tzinfo=UTC)
        for name, value in (('SESSIONS', self.home / 'sessions'), ('INDEX', self.home / 'session_index.jsonl')):
            patcher = patch.object(work_monitor, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        (self.home / 'session_index.jsonl').write_text(
            json.dumps({'id': THREAD, 'thread_name': '古い名前'}) + '\n' + json.dumps({'id': THREAD, 'thread_name': 'Metaへ入稿'}) + '\n', encoding='utf-8')

    def record(self, events, thread=THREAD):
        day = self.now.astimezone()
        folder = self.home / 'sessions' / f'{day:%Y/%m/%d}'
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f'rollout-2026-10-02T12-46-45-{thread}.jsonl'
        lines = []
        for minutes_ago, record_type, payload in events:
            lines.append(json.dumps({'timestamp': stamp(self.now - datetime.timedelta(minutes=minutes_ago)), 'type': record_type, 'payload': payload}))
        path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        os.utime(path, (self.now.timestamp(), self.now.timestamp()))
        return path

    def test_running_turn_shows_title_start_and_current_step(self):
        self.record([
            (12, 'event_msg', {'type': 'task_started'}),
            (11, 'response_item', {'type': 'reasoning', 'summary': [{'type': 'summary_text', 'text': '**Planning upload**'}]}),
            (10, 'response_item', {'type': 'custom_tool_call', 'name': 'exec'}),
        ])
        text = work_monitor.summary_text(self.now)
        self.assertIn('実行中  Metaへ入稿', text)
        self.assertIn('（12分経過）', text)
        self.assertIn('最終記録 10分前・コマンドを実行中', text)
        self.assertIn('10分以上、作業の記録が増えていません', text)

    def test_stopped_and_finished_turns(self):
        self.record([(20, 'event_msg', {'type': 'task_started'}), (15, 'event_msg', {'type': 'turn_aborted', 'reason': 'interrupted'})])
        self.assertTrue(work_monitor.summary_text(self.now).startswith('停止 '))
        self.record([(8, 'event_msg', {'type': 'task_started'}), (2, 'event_msg', {'type': 'task_complete'})])
        self.assertTrue(work_monitor.summary_text(self.now).startswith('完了 '))

    def test_new_turn_after_a_stop_is_running(self):
        self.record([
            (20, 'event_msg', {'type': 'task_started'}), (15, 'event_msg', {'type': 'turn_aborted'}),
            (3, 'event_msg', {'type': 'task_started'}), (1, 'response_item', {'type': 'message', 'role': 'assistant'}),
        ])
        text = work_monitor.summary_text(self.now)
        self.assertIn('実行中', text)
        self.assertIn('返答を書いています', text)

    def test_old_finished_work_is_hidden(self):
        self.record([(90, 'event_msg', {'type': 'task_started'}), (60, 'event_msg', {'type': 'task_complete'})])
        self.assertEqual(work_monitor.summary_text(self.now), 'この30分に動いた作業はありません。')

    def test_turn_start_beyond_the_short_tail_is_found(self):
        big = [(12, 'event_msg', {'type': 'task_started'})] + [(5, 'response_item', {'type': 'message', 'role': 'user', 'content': 'x' * 1000})] * 50
        self.record(big)
        with patch.object(work_monitor, 'TAIL_BYTES', 4000):
            item = work_monitor.snapshot(self.now)[0]
        self.assertIsNotNone(item['started'])

    def test_broken_lines_are_skipped(self):
        path = self.record([(2, 'event_msg', {'type': 'task_started'})])
        with open(path, 'a', encoding='utf-8') as handle:
            handle.write('{"timestamp": broken\n')
        self.assertIn('実行中', work_monitor.summary_text(self.now))


if __name__ == '__main__':
    unittest.main()
