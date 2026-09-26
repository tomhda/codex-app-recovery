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
                'updated': 0, 'eligible': True, 'kind': 'features', **changes}

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

    def test_degraded_chat_controls_allow_preparation_recovery(self):
        state = {'blank': False, 'ui': {'degraded': True}, 'queries': [self.query(kind='config-read')]}
        self.assertEqual(len(recovery.stable_candidates(state, state)), 1)

    def test_healthy_chat_controls_preserve_preparation_read(self):
        state = {'blank': False, 'ui': {'degraded': False}, 'queries': [self.query(kind='config-read')]}
        self.assertEqual(recovery.stable_candidates(state, state), [])

    def test_config_leaf_precedes_parent(self):
        leaf = self.query(kind='config-read', key=['config', 'read-response', 'local', 'cwd', True])
        parent = self.query(kind='config-parent', key=['config', 'effective', 'local', 'cwd'])
        state = {'blank': True, 'queries': [parent, leaf]}
        result = recovery.stable_candidates(state, state)
        self.assertEqual([item['kind'] for item in result], ['config-read', 'config-parent'])

    def test_unknown_context_is_not_called_unavailable(self):
        state = {'blank': False, 'ui': {'chat': True, 'modelPicker': True, 'effortPicker': True,
                                         'contextUsage': None, 'contextState': 'unknown', 'degraded': False},
                 'features': {'status': 'success', 'fetch': 'idle', 'browser': True, 'automation': True}}
        text = recovery.describe(state)
        self.assertIn('判断できません', text)
        self.assertNotIn('未取得です', text)

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

    def test_missing_endpoint_is_typed_and_does_not_mutate(self):
        state = {'processes': [{'id': 7, 'main': True}], 'listeners': []}
        with self.assertRaises(recovery.RecoveryError) as caught:
            recovery.validate_listener(state)
        self.assertEqual(caught.exception.code, 'no_listener')
        self.assertEqual(caught.exception.stage, 'connect')
        self.assertEqual(state['listeners'], [])

    def test_foreign_listener_is_typed_unsafe_failure(self):
        with self.assertRaises(recovery.RecoveryError) as caught:
            recovery.validate_listener({'processes': [{'id': 7, 'main': True}],
                                        'listeners': [{'pid': 9, 'port': 9222, 'address': '127.0.0.1'}]})
        self.assertEqual(caught.exception.code, 'unsafe_listener')

    def test_partial_settings_not_reported_as_recovered(self):
        text = recovery.describe({'blank': False, 'settingsRead': False, 'features': {'status': 'success', 'fetch': 'idle', 'browser': True, 'automation': True}})
        self.assertIn('設定の一部を読み込めていません', text)
        self.assertIn('次回実行', text)

    def test_logs_omit_cwd_and_workspace_and_error_details(self):
        raw = {'ui': {'cwd': 'C:\\Users\\example\\private-project', 'scopeCwd': 'private-project'},
               'error': 'example@example.test'}
        clean = str(recovery.redacted_record(raw))
        self.assertNotIn('private-project', clean)
        self.assertIn('<argument>', clean)

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

    def test_engine_not_ready_retries_same_connection(self):
        snapshot = {'blank': False, 'queries': [], 'features': {'status': 'success', 'fetch': 'idle', 'browser': True, 'automation': True}}
        connection = MagicMock()
        connection.engine.side_effect = [recovery.RecoveryError('準備中', code='engine_not_ready', stage='engine'), snapshot]
        with patch.object(recovery.time, 'sleep'):
            self.assertEqual(recovery._engine_snapshot(connection, attempts=2, delay=0, deadline=1), snapshot)
        self.assertEqual(connection.engine.call_count, 2)

    def test_transport_error_does_not_retry_closed_connection(self):
        connection = MagicMock()
        connection.engine.side_effect = recovery.RecoveryError('切断', code='transport_error', stage='engine')
        with self.assertRaises(recovery.RecoveryError) as caught:
            recovery._engine_snapshot(connection, attempts=8, delay=0, deadline=20)
        self.assertEqual(caught.exception.code, 'transport_error')
        self.assertEqual(connection.engine.call_count, 1)

    def test_run_operation_reconnects_before_read_after_transport_error(self):
        snapshot = {'blank': False, 'queries': [], 'features': {'status': 'success', 'fetch': 'idle', 'browser': True, 'automation': True}}
        first, second = MagicMock(), MagicMock()
        first.engine.side_effect = recovery.RecoveryError('切断', code='transport_error', stage='engine')
        second.engine.return_value = snapshot
        state = {'version': 'test', 'processes': [{'id': 10}], 'listeners': [{'pid': 10, 'address': '127.0.0.1'}]}
        with patch.object(recovery, 'app_state', return_value=state),              patch.object(recovery, 'connect_to_main', side_effect=[first, second]) as connect,              patch.object(recovery, 'save_record'):
            text = recovery.run_operation('check', lambda _: None)
        self.assertIn('画面の内容を確認できました', text)
        self.assertEqual(connect.call_count, 2)
        first.close.assert_called_once()

    def test_connection_engine_preserves_structured_readiness_code(self):
        connection = recovery.Connection.__new__(recovery.Connection)
        connection.call = MagicMock(return_value={'result': {'value': {'__recoveryError': {'code': 'engine_not_ready'}}}})
        with self.assertRaises(recovery.RecoveryError) as caught:
            connection.engine()
        self.assertEqual(caught.exception.code, 'engine_not_ready')

    def test_connect_deadline_stops_before_next_attempt(self):
        target_missing = recovery.RecoveryError('missing', code='target_missing', stage='target_discovery')
        calls = []
        with patch.object(recovery, 'app_state', side_effect=lambda **kwargs: calls.append(kwargs) or (_ for _ in ()).throw(target_missing)),              patch.object(recovery.time, 'monotonic', side_effect=[0.0, 0.0, 0.0, 21.0]),              patch.object(recovery.time, 'sleep') as sleep:
            with self.assertRaises(recovery.RecoveryError):
                recovery.connect_to_main(attempts=8, delay=1, deadline=20)
        self.assertEqual(len(calls), 1)
        sleep.assert_not_called()

    def test_close_failure_does_not_mask_result(self):
        snapshot = {'blank': False, 'queries': [], 'features': {'status': 'success', 'fetch': 'idle', 'browser': True, 'automation': True}}
        connection = MagicMock()
        connection.engine.return_value = snapshot
        connection.close.side_effect = OSError('already closed')
        state = {'version': 'test', 'processes': [{'id': 10}], 'listeners': [{'pid': 10, 'address': '127.0.0.1'}]}
        with patch.object(recovery, 'app_state', return_value=state),              patch.object(recovery, 'main_page', return_value={}),              patch.object(recovery, 'Connection', return_value=connection),              patch.object(recovery, 'save_record') as save:
            text = recovery.run_operation('check', lambda _: None)
        self.assertIn('画面の内容を確認できました', text)
        save.assert_called_once()

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
