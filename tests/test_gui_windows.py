import sys
import unittest
from unittest.mock import patch

import i18n
import recovery


@unittest.skipUnless(sys.platform == 'win32', 'Windows Tk UI')
class WindowTests(unittest.TestCase):
    def test_window_opens_in_both_languages_without_touching_codex(self):
        previous = i18n.get_language()
        self.addCleanup(i18n.set_language, previous)
        overview = {'installed': True, 'running': False, 'port': False, 'portForeign': False, 'daemon': False, 'page': None}
        for language in ('ja', 'en'):
            i18n.set_language(language)
            with patch.object(recovery.control, 'overview', return_value=overview), \
                 patch.object(recovery.control, 'launch') as launch, patch.object(recovery.control, 'checkup') as checkup:
                recovery.gui(smoke_test=True)
            launch.assert_not_called()
            checkup.assert_not_called()


if __name__ == '__main__':
    unittest.main()
