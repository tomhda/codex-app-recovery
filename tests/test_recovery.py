import unittest
from unittest.mock import patch, MagicMock
import recovery


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.previous_language = recovery.get_language()
        recovery.set_language('ja')
        self.addCleanup(recovery.set_language, self.previous_language)

    def query(self, **changes):
        return {'key': ['experimental-features', 'list', 'local'], 'queryId': 1,
                'promiseId': 2, 'status': 'pending', 'fetch': 'fetching',
                'updated': 0, 'kind': 'features', **changes}

    def test_stable_feature(self):
        state = {'blank': False, 'queries': [self.query()]}
        self.assertEqual(len(recovery.stable_candidates(state, state)), 1)

    def test_new_request_excluded(self):
        first = {'blank': True, 'queries': [self.query()]}
        second = {'blank': True, 'queries': [self.query(promiseId=3)]}
        self.assertEqual(recovery.stable_candidates(first, second), [])

    def test_visible_screen_preserves_config(self):
        state = {'blank': False, 'queries': [self.query(kind='config-read')]}
        self.assertEqual(recovery.stable_candidates(state, state), [])

    def test_idle_excluded(self):
        state = {'blank': True, 'queries': [self.query(fetch='idle')]}
        self.assertEqual(recovery.stable_candidates(state, state), [])

    def test_foreign_port_rejected(self):
        with self.assertRaises(recovery.RecoveryError):
            recovery.validate_listener({'processes': [{'id': 1}], 'listeners': [{'pid': 2, 'address': '127.0.0.1'}]})

    def test_non_loopback_rejected(self):
        with self.assertRaises(recovery.RecoveryError):
            recovery.validate_listener({'processes': [{'id': 1}], 'listeners': [{'pid': 1, 'address': '0.0.0.0'}]})

    def test_missing_endpoint(self):
        with self.assertRaisesRegex(recovery.RecoveryError, 'Codexを開き直して復旧'):
            recovery.validate_listener({'processes': [], 'listeners': []})

    def test_partial_settings_not_reported_as_recovered(self):
        text = recovery.describe({'blank': False, 'settingsRead': False, 'features': {'status': 'success', 'fetch': 'idle', 'browser': True, 'automation': True}})
        self.assertIn('設定の一部を読み込めていません', text)
        self.assertIn('次回実行', text)

    def test_logs_omit_workspace_and_error_details(self):
        raw = {'actions': [{'before': {'key': ['config', 'read-response', 'local', 'C:\\Users\\example\\private-project', True]},
                            'reason': 'failure in private-project'}], 'error': 'example@example.test'}
        clean = str(recovery.redacted_record(raw))
        self.assertNotIn('private-project', clean)
        self.assertNotIn('example@example.test', clean)
        self.assertIn('read-response', clean)

    def test_blackscreen_result_gives_next_step(self):
        state = {'blank': True, 'features': {'status': 'pending', 'fetch': 'fetching'}}
        self.assertIn('まず復旧を試す', recovery.describe(state, 'check'))
        self.assertIn('画面を読み直す', recovery.describe(state, 'repair'))
        self.assertIn('Codex CLI', recovery.describe(state, 'reload'))

    def test_check_never_recovers_reloads_or_restarts(self):
        snapshot = {'blank': False, 'queries': [], 'features': {'status': 'success', 'fetch': 'idle', 'browser': True, 'automation': True}}
        connection = MagicMock()
        connection.engine.return_value = snapshot
        state = {'version': 'test', 'processes': [{'id': 10}], 'listeners': [{'pid': 10, 'address': '127.0.0.1'}]}
        with patch.object(recovery, 'app_state', return_value=state), \
             patch.object(recovery, 'main_page', return_value={}), \
             patch.object(recovery, 'Connection', return_value=connection), \
             patch.object(recovery, 'save_record') as save, \
             patch.object(recovery, 'prepare_connection') as prepare:
            recovery.run_operation('check', lambda _: None)
        connection.call.assert_not_called()
        self.assertTrue(all(not call.args for call in connection.engine.call_args_list))
        prepare.assert_not_called()
        save.assert_called_once()
        connection.close.assert_called_once()

    def test_logging_failure_does_not_hide_recovery_result(self):
        snapshot = {'blank': False, 'queries': [], 'features': {'status': 'success', 'fetch': 'idle', 'browser': True, 'automation': True}}
        connection = MagicMock()
        connection.engine.return_value = snapshot
        state = {'version': 'test', 'processes': [{'id': 10}], 'listeners': [{'pid': 10, 'address': '127.0.0.1'}]}
        with patch.object(recovery, 'app_state', return_value=state), \
             patch.object(recovery, 'main_page', return_value={}), \
             patch.object(recovery, 'Connection', return_value=connection), \
             patch.object(recovery, 'save_record', side_effect=OSError('read-only filesystem')):
            text = recovery.run_operation('check', lambda _: None)
        self.assertIn('画面の内容を確認できました', text)


if __name__ == '__main__':
    unittest.main()
