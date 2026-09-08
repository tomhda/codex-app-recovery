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

    def test_translation_catalog_covers_ui_and_engine_messages(self):
        root = Path(recovery.__file__).parent
        expected = set()
        for name in ('recovery.py', 'setup_recovery.py'):
            for node in ast.walk(ast.parse((root / name).read_text(encoding='utf-8'))):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'tr':
                    if node.args and isinstance(node.args[0], ast.Constant):
                        expected.add(node.args[0].value)
        expected.update(re.findall(r"throw new Error\('([^']+)'\)", (root / 'engine.js').read_text(encoding='utf-8')))
        self.assertFalse(expected - i18n.EN.keys(), expected - i18n.EN.keys())
        self.assertTrue(all(i18n.EN[key].strip() for key in expected))

    def test_english_results_are_fully_translated(self):
        i18n.set_language('en')
        state = {'blank': True, 'settingsRead': False, 'features': {'status': 'pending', 'fetch': 'fetching'}}
        for mode in ('check', 'repair', 'reload'):
            text = recovery.describe(state, mode)
            self.assertNotRegex(text, '[\u3040-\u9fff]')
            self.assertIn('Next:', text)
        self.assertIn('permissions', recovery.describe(state))

    def test_japanese_remains_japanese(self):
        i18n.set_language('ja')
        self.assertEqual(i18n.tr('まず復旧を試す'), 'まず復旧を試す')

    def test_feature_identification_error_suggests_waiting_in_both_languages(self):
        message = '対象の機能一覧を一意に特定できません。変更せず停止しました。'
        for language in ('ja', 'en'):
            i18n.set_language(language)
            text = recovery.describe_error(recovery.RecoveryError(i18n.tr(message)))
            self.assertIn('30', text)
            self.assertNotIn(i18n.tr('Codexを開き直して復旧'), text)
            if language == 'en':
                self.assertNotRegex(text, '[\u3040-\u9fff]')
                self.assertIn('not a guaranteed', text)

    def test_other_errors_keep_their_existing_guidance(self):
        i18n.set_language('en')
        text = recovery.describe_error(recovery.RecoveryError('Connection refused'))
        self.assertIn('Connection refused', text)
        self.assertNotIn('30', text)

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
