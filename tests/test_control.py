import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import codex_control as control
import guard_events
import i18n
import recovery


def state(**overrides):
    base = {'installed': True, 'version': '26.928.3736.0', 'mainPids': [1], 'appPids': [1, 2], 'running': True,
            'port': True, 'portForeign': False, 'listenerOwner': 1, 'listenerAddress': '127.0.0.1'}
    base.update(overrides)
    return base


class AppStateTests(unittest.TestCase):
    def parse(self, payload):
        with patch.object(control, 'powershell', return_value=json.dumps(payload)):
            return control.app_state()

    def test_port_owned_by_app_on_loopback(self):
        result = self.parse({'installed': True, 'mainPids': [10], 'appPids': [10, 11], 'listenerOwner': 11, 'listenerAddress': '127.0.0.1'})
        self.assertTrue(result['running'])
        self.assertTrue(result['port'])
        self.assertFalse(result['portForeign'])

    def test_foreign_listener_is_not_trusted(self):
        result = self.parse({'installed': True, 'mainPids': [10], 'appPids': [10], 'listenerOwner': 99, 'listenerAddress': '127.0.0.1'})
        self.assertFalse(result['port'])
        self.assertTrue(result['portForeign'])

    def test_non_loopback_listener_is_not_trusted(self):
        result = self.parse({'installed': True, 'mainPids': [10], 'appPids': [10], 'listenerOwner': 10, 'listenerAddress': '0.0.0.0'})
        self.assertFalse(result['port'])

    def test_not_running(self):
        result = self.parse({'installed': True, 'mainPids': [], 'appPids': []})
        self.assertFalse(result['running'])
        self.assertFalse(result['port'])


class LaunchTests(unittest.TestCase):
    def test_running_with_port_only_focuses(self):
        with patch.object(control, 'app_state', return_value=state()), \
             patch.object(control, 'start_daemon') as daemon, patch.object(control, 'activate') as activate, \
             patch.object(control, 'quit_app') as quit_app:
            self.assertEqual(control.launch(), 'focused')
        daemon.assert_called_once()
        activate.assert_called_once_with(with_port=False)
        quit_app.assert_not_called()

    def test_running_without_port_asks_and_respects_no(self):
        with patch.object(control, 'app_state', return_value=state(port=False)), \
             patch.object(control, 'activate') as activate, patch.object(control, 'quit_app') as quit_app:
            self.assertEqual(control.launch(confirm_restart=lambda: False), 'declined')
        activate.assert_not_called()
        quit_app.assert_not_called()

    def test_running_without_port_restarts_after_yes(self):
        with patch.object(control, 'app_state', return_value=state(port=False)), \
             patch.object(control, 'quit_app') as quit_app, patch.object(control, 'activate') as activate, \
             patch.object(control, 'wait_for', return_value=True), patch.object(control, 'start_daemon'), \
             patch.object(control.time, 'sleep'):
            self.assertEqual(control.launch(confirm_restart=lambda: True), 'started')
        quit_app.assert_called_once()
        activate.assert_called_once_with(with_port=True)

    def test_not_running_starts_with_port(self):
        with patch.object(control, 'app_state', return_value=state(running=False, mainPids=[], port=False)), \
             patch.object(control, 'activate') as activate, patch.object(control, 'wait_for', return_value=True), \
             patch.object(control, 'start_daemon') as daemon:
            self.assertEqual(control.launch(confirm_restart=lambda: self.fail('must not ask')), 'started')
        activate.assert_called_once_with(with_port=True)
        daemon.assert_called_once()

    def test_foreign_port_stops_before_anything(self):
        with patch.object(control, 'app_state', return_value=state(port=False, portForeign=True)), \
             patch.object(control, 'activate') as activate:
            with self.assertRaises(control.ControlError) as caught:
                control.launch(confirm_restart=lambda: True)
        self.assertEqual(caught.exception.code, 'port_in_use')
        activate.assert_not_called()

    def test_force_needs_its_own_consent(self):
        with patch.object(control, 'app_state', return_value=state(port=False)), patch.object(control.subprocess, 'run') as run:
            with self.assertRaises(control.ControlError) as caught:
                control.quit_app(confirm_force=lambda: False)
        self.assertEqual(caught.exception.code, 'quit_declined')
        run.assert_not_called()

    def test_restart_consent_alone_never_forces(self):
        with patch.object(control, 'app_state', return_value=state(port=False)),              patch.object(control.subprocess, 'run') as run, patch.object(control, 'activate') as activate:
            self.assertEqual(control.launch(confirm_restart=lambda: True, confirm_force=lambda: False), 'declined')
        run.assert_not_called()
        activate.assert_not_called()

    def test_force_only_targets_processes_seen_at_consent(self):
        states = iter([state(port=False, mainPids=[10]), state(port=False, mainPids=[10, 99]), state(running=False, mainPids=[])])
        with patch.object(control, 'app_state', side_effect=lambda: next(states)),              patch.object(control.subprocess, 'run') as run, patch.object(control.time, 'sleep'):
            control.quit_app(confirm_force=lambda: True)
        killed = [call.args[0][2] for call in run.call_args_list]
        self.assertEqual(killed, ['10'])


class OverviewTextTests(unittest.TestCase):
    def setUp(self):
        self.previous = i18n.get_language()
        self.addCleanup(i18n.set_language, self.previous)
        i18n.set_language('ja')

    def test_actions_follow_state(self):
        self.assertEqual(recovery.describe_overview({'installed': True, 'running': False, 'port': False})['action'], 'launch')
        self.assertEqual(recovery.describe_overview({'installed': True, 'running': True, 'port': False})['action'], 'restart')
        self.assertIsNone(recovery.describe_overview({'installed': True, 'running': True, 'port': False, 'portForeign': True})['action'])
        guarded = recovery.describe_overview({'installed': True, 'running': True, 'port': True, 'daemon': True,
                                              'page': {'blank': False, 'guard': {'version': '1.3.0'}}})
        self.assertEqual(guarded['action'], 'checkup')
        self.assertEqual(guarded['guard'], '有効')
        self.assertEqual(guarded['screen'], '表示中')

    def test_blank_screen_shows_seconds(self):
        described = recovery.describe_overview({'installed': True, 'running': True, 'port': True, 'daemon': True,
                                                'page': {'blank': True, 'ageMs': 61000, 'guard': {'version': '1'}}})
        self.assertIn('61', described['screen'])

    def test_error_codes_have_messages(self):
        for code in ('package_missing', 'port_in_use', 'port_not_ready', 'quit_failed', 'quit_declined', 'not_running', 'no_port', 'main_page_missing'):
            text = recovery.error_text(control.ControlError(code))
            self.assertNotIn(code, text)

    def test_checkup_text(self):
        text = recovery.checkup_text({'daemonStarted': True, 'reloaded': False,
                                      'status': {'blank': False, 'guard': {'pendingMcp': 1, 'pendingFetch': 0}}})
        self.assertIn('常駐プロセス', text)
        self.assertIn('1件', text)


class GuardEventTests(unittest.TestCase):
    def setUp(self):
        self.previous = i18n.get_language()
        self.addCleanup(i18n.set_language, self.previous)
        i18n.set_language('ja')
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        patcher = patch.object(guard_events, 'LOG_DIR', Path(self.directory.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, events):
        path = Path(self.directory.name) / ('guard-' + datetime.date.today().strftime('%Y%m%d') + '.jsonl')
        now = datetime.datetime.now().astimezone()
        with path.open('w', encoding='utf-8') as handle:
            for event in events:
                handle.write(json.dumps({'time': now.isoformat(timespec='seconds'), **event}, ensure_ascii=False) + '\n')

    def test_user_lines_hide_internal_names(self):
        self.write([
            {'kind': 'installed', 'version': '1.3.0'},
            {'kind': 'recovered', 'bus': 'mcp', 'method': 'thread/queue/list'},
            {'kind': 'recovered', 'bus': 'mcp', 'method': 'some/unknown'},
            {'kind': 'init-snapshot-requested'},
            {'kind': 'resume-fix'},
            'broken' and {'kind': 'candidate', 'method': 'config/read'},
        ])
        lines = [text for _, text in guard_events.recent()]
        self.assertEqual(len(lines), 4)
        joined = '\n'.join(lines)
        self.assertIn('送信キューの読み込み', joined)
        self.assertIn('アプリ内部の処理', joined)
        self.assertNotIn('thread/', joined)
        self.assertNotIn('some/unknown', joined)

    def test_missing_log_is_empty(self):
        self.assertEqual(guard_events.recent(), [])


if __name__ == '__main__':
    unittest.main()
