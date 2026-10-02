import ast
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
import i18n
import recovery


class LanguageTests(unittest.TestCase):
    def setUp(self):
        self.previous = i18n.get_language()
        self.addCleanup(i18n.set_language, self.previous)

    def test_catalog_covers_every_japanese_ui_string(self):
        root = Path(recovery.__file__).parent
        japanese = re.compile('[぀-ヿ一-鿿]')
        expected = set()
        for name in ('recovery.py', 'guard_events.py'):
            for node in ast.walk(ast.parse((root / name).read_text(encoding='utf-8'))):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and japanese.search(node.value):
                    expected.add(node.value)
        for name in ('chat_ui.py', 'setup_recovery.py'):
            for node in ast.walk(ast.parse((root / name).read_text(encoding='utf-8'))):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'tr':
                    if node.args and isinstance(node.args[0], ast.Constant):
                        expected.add(node.args[0].value)
        self.assertFalse(expected - i18n.EN.keys(), expected - i18n.EN.keys())
        self.assertTrue(all(i18n.EN[key].strip() for key in expected))

    def test_english_status_and_errors_have_no_japanese(self):
        i18n.set_language('en')
        described = recovery.describe_overview({'installed': True, 'running': True, 'port': True, 'daemon': True,
                                                'page': {'blank': True, 'ageMs': 5000, 'guard': {'version': '1'}}})
        texts = [described['codex'], described['guard'], described['screen'],
                 recovery.error_text(recovery.control.ControlError('no_port')),
                 recovery.checkup_text({'status': {'blank': False, 'guard': {}}})]
        for text in texts:
            self.assertNotRegex(text, '[぀-鿿]')

    def test_japanese_remains_japanese(self):
        i18n.set_language('ja')
        self.assertEqual(i18n.tr('今すぐ点検'), '今すぐ点検')

    def test_preference_overrides_os_but_cli_override_wins(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            with patch.object(i18n, 'settings_path', return_value=path), patch.object(i18n, 'system_language', return_value='en'):
                self.assertEqual(i18n.resolve_language(), 'en')
                i18n.save_language('ja')
                self.assertEqual(i18n.resolve_language(), 'ja')
                self.assertEqual(i18n.resolve_language('en'), 'en')
                self.assertEqual(json.loads(path.read_text())['language'], 'ja')

    def test_malformed_preference_falls_back_to_os(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            with patch.object(i18n, 'settings_path', return_value=path), patch.object(i18n, 'system_language', return_value='ja'):
                for value in ('not json', '[]', '{"language":"fr"}'):
                    path.write_text(value, encoding='utf-8')
                    self.assertEqual(i18n.resolve_language(), 'ja')

    def test_save_preserves_unrelated_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            path.write_text('{"other":42}', encoding='utf-8')
            with patch.object(i18n, 'settings_path', return_value=path):
                i18n.save_language('en')
            self.assertEqual(json.loads(path.read_text()), {'other': 42, 'language': 'en'})
