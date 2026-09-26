import sys
import unittest
from unittest.mock import MagicMock, patch
import recovery


def spinner(**changes):
    return {'blank': True, 'settingsRead': True, 'queries': [],
            'ui': {'startupSpinner': True, 'documentId': 'page-1'},
            'features': {'status': 'success', 'fetch': 'idle', 'browser': True, 'automation': True},
            **changes}


class StartupRecoveryTests(unittest.TestCase):
    def run_case(self, mode='repair', before=None, after=None):
        first, reloaded = MagicMock(), MagicMock()
        first.engine.side_effect = before or [spinner()] * 3
        reloaded.engine.return_value = after or spinner(blank=False, ui={})
        with patch.object(recovery, 'app_state', return_value={'version': 'test'}), \
             patch.object(recovery, 'connect_to_main', side_effect=[first, reloaded]), \
             patch.object(recovery.time, 'sleep'), patch.object(recovery, 'save_record') as save:
            recovery.run_operation(mode, lambda _: None)
        return first, reloaded, save.call_args.args[0]

    def test_ready_backend_spinner_reloads_once_without_stalled_queries(self):
        for mode in ('repair', 'prepare'):
            first, reloaded, record = self.run_case(mode)
            first.call.assert_called_once_with('Page.reload', {'ignoreCache': True})
            reloaded.call.assert_not_called()
            self.assertFalse(record['after']['blank'])
            self.assertEqual(record['actions'], [{'action': 'startup_spinner_reload'}])

    def test_persistent_spinner_is_not_reloaded_again_or_reported_visible(self):
        first, reloaded, record = self.run_case(after=spinner())
        first.call.assert_called_once()
        reloaded.call.assert_not_called()
        self.assertEqual(reloaded.engine.call_count, 8)
        self.assertTrue(record['after']['blank'])

    def test_check_is_read_only_even_for_spinner(self):
        first, reloaded, record = self.run_case(mode='check', before=[spinner()] * 2)
        first.call.assert_not_called()
        reloaded.engine.assert_not_called()
        self.assertEqual(record['actions'], [])

    def test_no_reload_for_unknown_or_changing_or_resolved_state(self):
        for changed in (spinner(blank=False), spinner(settingsRead=False),
                        spinner(ui={'startupSpinner': False, 'documentId': 'page-1'}),
                        spinner(ui={'startupSpinner': True, 'documentId': 'page-2'}),
                        spinner(ui={'startupSpinner': True}),
                        spinner(features={'status': 'pending', 'fetch': 'fetching'})):
            first, reloaded, _ = self.run_case(before=[spinner(), spinner(), changed])
            first.call.assert_not_called()
            reloaded.engine.assert_not_called()

    def test_explicit_reload_does_not_trigger_second_reload(self):
        first, reloaded, _ = self.run_case(mode='reload', after=spinner())
        first.call.assert_called_once()
        reloaded.call.assert_not_called()

    def test_reload_transport_failure_is_not_retried(self):
        connection = MagicMock()
        connection.engine.return_value = spinner()
        connection.call.side_effect = recovery.RecoveryError('closed', code='transport_error')
        with patch.object(recovery, 'app_state', return_value={}), \
             patch.object(recovery, 'connect_to_main', return_value=connection), \
             patch.object(recovery.time, 'sleep'), patch.object(recovery, 'save_record') as save:
            with self.assertRaises(recovery.RecoveryError):
                recovery.run_operation('repair', lambda _: None)
        connection.call.assert_called_once()
        self.assertEqual(save.call_args.args[0]['actions'][0]['action'], 'startup_spinner_reload')

    def activation_script(self):
        with patch.object(recovery, 'app_state', return_value={'processes': [], 'listeners': []}), \
             patch.object(recovery, 'powershell') as ps, patch.object(recovery, 'main_page'), \
             patch.object(recovery.time, 'sleep'), patch.object(recovery, 'run_operation') as op:
            recovery.prepare_connection(lambda _: None, requested_mode='repair')
        op.assert_called_once()
        return ps.call_args.args[0]

    def test_activation_uses_package_and_preflights_before_shutdown(self):
        script = self.activation_script()
        self.assertIn('ActivateApplication', script)
        self.assertIn('$package.PackageFamilyName', script)
        self.assertNotIn('Start-Process', script)
        self.assertLess(script.index('Add-Type'), script.index('taskkill.exe'))
        self.assertLess(script.index('$apps.Count -ne 1'), script.index('taskkill.exe'))

    def test_existing_connection_is_not_restarted(self):
        state = {'processes': [{'id': 1}], 'listeners': [{'pid': 1, 'port': 9222, 'address': '127.0.0.1'}]}
        with patch.object(recovery, 'app_state', return_value=state), \
             patch.object(recovery, 'powershell') as ps, patch.object(recovery, 'run_operation') as op:
            recovery.prepare_connection(lambda _: None, requested_mode='repair')
        ps.assert_not_called()
        op.assert_called_once()

    @unittest.skipUnless(sys.platform == 'win32', 'Windows PowerShell and COM')
    def test_windows_activation_preflight_compiles_without_starting_codex(self):
        script = self.activation_script()
        # Use a fake manifest, including another app first, to check selection on CI.
        prefix = '''
function Get-AppxPackage { [pscustomobject]@{Version='1.0';InstallLocation='C:\\fake';PackageFamilyName='TestFamily'} }
function Get-AppxPackageManifest { [pscustomobject]@{Package=[pscustomobject]@{Applications=[pscustomobject]@{Application=@(
 [pscustomobject]@{Id='Other';Executable='app/other.exe'},
 [pscustomobject]@{Id='Codex';Executable='app/ChatGPT.exe'})}}} }
function Test-Path { return $true }
'''
        preflight = script.split('    if(@(Get-NetTCPConnection')[0]
        result = recovery.powershell(prefix + preflight + '\n@{aumid=$aumid;compiled=([CodexPackageActivation] -ne $null)} | ConvertTo-Json -Compress')
        self.assertEqual(result, {'aumid': 'TestFamily!Codex', 'compiled': True})
