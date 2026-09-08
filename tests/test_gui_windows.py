import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import i18n
import recovery


@unittest.skipUnless(sys.platform == 'win32', 'Windows Tk UI')
class LanguageSwitchTests(unittest.TestCase):
    def test_language_selector_redraws_and_saves_without_recovery(self):
        import tkinter as tk
        from tkinter import ttk
        original = tk.Tk
        previous = i18n.get_language()
        self.addCleanup(i18n.set_language, previous)
        i18n.set_language('ja')
        titles, errors = [], []
        def factory(*args, **kwargs):
            app = original(*args, **kwargs)
            def interact():
                try:
                    titles.append(app.title())
                    if len(titles) == 1:
                        stack = list(app.winfo_children())
                        while stack:
                            widget = stack.pop()
                            if isinstance(widget, ttk.Combobox):
                                widget.set('English')
                                widget.event_generate('<<ComboboxSelected>>')
                                return
                            stack.extend(widget.winfo_children())
                        raise AssertionError('Language selector missing')
                    app.eval(app.protocol('WM_DELETE_WINDOW'))
                except Exception as error:
                    errors.append(str(error))
                    app.destroy()
            app.after(200, interact)
            return app
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            with patch.object(i18n, 'settings_path', return_value=path), patch.object(tk, 'Tk', factory), \
                 patch.object(recovery, 'run_operation') as operation:
                recovery.gui()
            operation.assert_not_called()
            self.assertEqual(errors, [])
            self.assertEqual(len(titles), 2)
            self.assertIn('Codex 復旧', titles[0])
            self.assertIn('Codex App Recovery', titles[1])
            self.assertEqual(json.loads(path.read_text())['language'], 'en')
