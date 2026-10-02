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


if __name__ == '__main__':
    unittest.main()
