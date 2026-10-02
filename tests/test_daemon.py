import datetime
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import guard_daemon


class HostRoutedTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.log = Path(self.directory.name) / 'codex-desktop-x-t0-1.log'
        patcher = patch.object(guard_daemon, 'host_log_files', return_value=[self.log])
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, *lines):
        self.log.write_bytes(('\n'.join(lines) + '\n').encode())

    def line(self, when, request_id, destroyed='false'):
        return (f'{when.strftime("%Y-%m-%dT%H:%M:%S.000Z")} info [AppServerConnection] response_routed broadcastFallback=false '
                f'conversationId=null durationMs=3 method=thread/queue/list queueWaitMs=0 requestId={request_id} targetDestroyed={destroyed}')

    def test_matches_routed_reply_after_start(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        self.write(self.line(now, 'abc12345-0000'))
        self.assertTrue(guard_daemon.host_routed('abc12345-0000', (now.timestamp() - 5) * 1000))

    def test_ignores_old_lines_destroyed_targets_and_prefix_ids(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        old = now - datetime.timedelta(hours=1)
        self.write(self.line(old, 'abc12345-0000'), self.line(now, 'abc12345-1111', 'true'), self.line(now, 'abc12345-22220'))
        start = (now.timestamp() - 5) * 1000
        self.assertFalse(guard_daemon.host_routed('abc12345-0000', start))
        self.assertFalse(guard_daemon.host_routed('abc12345-1111', start))
        self.assertFalse(guard_daemon.host_routed('abc12345-2222', start))


@unittest.skipUnless(sys.platform == 'win32', 'msvcrt lock')
class LockTests(unittest.TestCase):
    def test_second_instance_is_refused(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(guard_daemon, 'DATA', Path(folder)):
            first = guard_daemon.single_instance()
            self.assertIsNotNone(first)
            try:
                self.assertIsNone(guard_daemon.single_instance())
            finally:
                first.close()
            again = guard_daemon.single_instance()
            self.assertIsNotNone(again)
            again.close()


class StallReloadTests(unittest.TestCase):
    def session(self, main=True):
        session = guard_daemon.Session.__new__(guard_daemon.Session)
        session.target_id = 'T' * 16
        session.is_main = main
        session.candidates = {}
        session.stall_reloads = []
        session.stall_logged_at = 0.0
        session.calls = []
        session.call = lambda method, params=None, timeout=15: session.calls.append(method)
        return session

    def setUp(self):
        patcher = patch.object(guard_daemon, 'log')
        self.log = patcher.start()
        self.addCleanup(patcher.stop)
        self.clock = [1000.0]
        clock = patch.object(guard_daemon.time, 'monotonic', side_effect=lambda: self.clock[0])
        clock.start()
        self.addCleanup(clock.stop)

    def test_stalled_main_window_is_reloaded(self):
        session = self.session()
        self.assertTrue(session.handle_stall({'stalled': True, 'sinceInputMs': None, 'silentMs': 20000}))
        self.assertEqual(session.calls, ['Page.reload'])

    def test_not_stalled_does_nothing(self):
        session = self.session()
        self.assertFalse(session.handle_stall({'stalled': False}))
        self.assertEqual(session.calls, [])

    def test_recent_typing_or_other_windows_only_log(self):
        typing = self.session()
        self.assertFalse(typing.handle_stall({'stalled': True, 'sinceInputMs': 2000}))
        other = self.session(main=False)
        self.assertFalse(other.handle_stall({'stalled': True, 'sinceInputMs': None}))
        self.assertEqual(typing.calls + other.calls, [])
        kinds = [c.args[0]['kind'] for c in self.log.call_args_list]
        self.assertEqual(kinds, ['channel-stall', 'channel-stall'])

    def test_reloads_are_spaced_and_bounded(self):
        session = self.session()
        status = {'stalled': True, 'sinceInputMs': None}
        self.assertTrue(session.handle_stall(status))
        self.clock[0] += 30
        self.assertFalse(session.handle_stall(status), 'too soon')
        for _ in range(2):
            self.clock[0] += 61
            self.assertTrue(session.handle_stall(status))
        self.clock[0] += 61
        self.assertFalse(session.handle_stall(status), 'at most three per half hour')
        self.clock[0] += 1800
        self.assertTrue(session.handle_stall(status))


if __name__ == '__main__':
    unittest.main()
