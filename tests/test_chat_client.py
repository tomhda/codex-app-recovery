import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from chat_client import AppServer, ChatError, ChatSession, redact


def wait_for(fn, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fn():
            return
        time.sleep(0.02)
    raise AssertionError('Condition timed out')


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = self.root / 'fake.json'
        self.command = [sys.executable, str(Path(__file__).with_name('fake_app_server.py')), str(self.store)]
        self.session = self.make_session()
        self.session.connect()

    def make_session(self, **options):
        session = ChatSession(self.root / 'session.json', self.command, **options)
        self.addCleanup(session.close)
        return session

    def test_stream_and_followup_use_same_thread_exact_model_effort(self):
        for text in ('first', 'followup'):
            self.session.send(text, self.tmp.name)
            wait_for(lambda: self.session.state == 'idle')
        records = json.loads(self.store.read_text())
        starts = [x for x in records['requests'] if x['method'] == 'turn/start']
        self.assertEqual(len(starts), 2)
        self.assertTrue(all(x['params']['threadId'] == 'wrapper-thread' for x in starts))
        self.assertTrue(all(x['params']['model'] == 'gpt-6.1-sol' and x['params']['effort'] == 'high' for x in starts))
        thread = next(x['params'] for x in records['requests'] if x['method'] == 'thread/start')
        self.assertEqual(thread['sandbox'], 'read-only')
        self.assertEqual(thread['approvalPolicy'], 'on-request')
        self.assertEqual(thread['approvalsReviewer'], 'user')
        self.assertEqual([m['text'] for m in self.session.data['messages'] if m['role'] == 'assistant'], ['Hello world', 'Hello world'])

    def test_busy_input_is_rejected_without_queue(self):
        self.session.send('[wait]', self.tmp.name)
        with self.assertRaises(ChatError):
            self.session.send('second', self.tmp.name)
        self.assertEqual(len(json.loads(self.store.read_text())['turns']), 1)
        self.session.stop()
        self.assertEqual(self.session.state, 'stopped')

    def test_stop_and_explicit_retry(self):
        self.session.send('[wait]', self.tmp.name)
        self.session.stop()
        self.session.retry()
        wait_for(lambda: self.session.turn_id == 'turn-2')
        self.session.stop()
        records = json.loads(self.store.read_text())
        self.assertEqual(len(records['turns']), 2)
        self.assertTrue(all(t['status'] == 'interrupted' for t in records['turns']))

    def test_idle_deadline_becomes_unknown_and_prevents_blind_retry(self):
        self.session.idle_timeout = 0.15
        self.session.send('[wait]', self.tmp.name)
        wait_for(lambda: self.session.state == 'unknown')
        self.assertEqual(self.session.error, 'activity_timeout')
        with self.assertRaises(ChatError): self.session.retry()
        self.session.stop()

    def test_relaunch_restores_completed_conversation(self):
        self.session.send('first', self.tmp.name)
        wait_for(lambda: self.session.state == 'idle')
        self.session.close()
        restored = self.make_session()
        restored.connect()
        restored.send('followup after restart', self.tmp.name)
        wait_for(lambda: restored.state == 'idle')
        self.assertEqual(len(json.loads(self.store.read_text())['turns']), 2)

    def test_lost_receipt_reconciles_without_resend(self):
        with self.assertRaises(ChatError): self.session.send('[disconnect]', self.tmp.name)
        wait_for(lambda: self.session.state == 'unknown')
        self.session.connect()
        self.assertEqual(self.session.state, 'idle')
        self.assertIsNone(self.session.data['pending'])
        self.assertIn('Recovered answer', [x['text'] for x in self.session.data['messages']])
        self.assertEqual(len(json.loads(self.store.read_text())['turns']), 1)

    def test_unknown_receipt_fails_closed(self):
        self.session.send('first', self.tmp.name)
        wait_for(lambda: self.session.state == 'idle')
        self.session.data['pending'] = {'clientId': 'not-in-history', 'submitted': True}
        self.session._save()
        with self.assertRaises(ChatError): self.session.connect()
        self.assertEqual(self.session.state, 'unknown')
        self.assertEqual(self.session.error, 'receipt_unknown')
        with self.assertRaises(ChatError): self.session.retry()

    def test_approval_is_not_automatic_or_persistent(self):
        self.session.send('[approval]', self.tmp.name)
        wait_for(lambda: self.session.state == 'approval')
        self.assertNotIn('answers', json.loads(self.store.read_text()))
        self.session.answer('approval-1', accept=False)
        wait_for(lambda: 'answers' in json.loads(self.store.read_text()))
        self.assertEqual(json.loads(self.store.read_text())['answers'], {'decision': 'decline'})
        self.session.stop()

    def test_permission_and_auth_requests_fail_closed(self):
        for method in ('item/permissions/requestApproval', 'account/chatgptAuthTokens/refresh', 'unknown/request'):
            self.session._notification({'id': 'unsupported', 'method': method, 'params': {}})
        wait_for(lambda: any(x.get('type') == 'diagnostic' for x in list(self.session.events.queue)))
        self.assertEqual(self.session.state, 'idle')

    def test_new_conversation_does_not_delete_native_history(self):
        self.session.send('first', self.tmp.name)
        wait_for(lambda: self.session.state == 'idle')
        self.session.new_conversation()
        self.assertIsNone(self.session.data['threadId'])
        self.assertEqual(len(json.loads(self.store.read_text())['turns']), 1)

    def test_diagnostics_contain_no_prompt_content_or_health_claim(self):
        self.session.send('private user text', self.tmp.name)
        wait_for(lambda: self.session.state == 'idle')
        result = json.dumps(self.session.diagnostics())
        self.assertNotIn('private', result)
        self.assertEqual(self.session.diagnostics()['desktopFollowupHealth'], 'unknown')

    def test_redaction(self):
        text = redact('access_token=supersecret bearer secret-value sk-abcdefghijklmnopqrstuvwxyz')
        for value in ('supersecret', 'secret-value', 'sk-abcdefghijklmnopqrstuvwxyz'):
            self.assertNotIn(value, text)

    def test_cwd_cannot_change_mid_conversation(self):
        self.session.send('first', self.tmp.name)
        wait_for(lambda: self.session.state == 'idle')
        with self.assertRaises(ChatError): self.session.send('next', str(Path.cwd()))

    def test_request_timeout_is_bounded(self):
        with self.assertRaises(ChatError) as error:
            self.session.server.request('test/no-response', timeout=0.1)
        self.assertEqual(error.exception.code, 'request_timeout')

    def test_mismatched_execution_policy_blocks_turn_and_next_send(self):
        original = self.session.server.request
        def mismatched(method, params=None, **kwargs):
            result = original(method, params, **kwargs)
            if method == 'thread/start':
                result['sandbox'] = {'type': 'dangerFullAccess'}
            return result
        with patch.object(self.session.server, 'request', side_effect=mismatched):
            with self.assertRaises(ChatError) as error:
                self.session.send('first', self.tmp.name)
        self.assertEqual(error.exception.code, 'execution_policy_mismatch')
        self.assertFalse(self.session.connected)
        with self.assertRaises(ChatError): self.session.send('second', self.tmp.name)
        self.assertEqual(json.loads(self.store.read_text())['turns'], [])

    def test_persistent_only_approval_is_not_accepted(self):
        self.session.send('[approval]', self.tmp.name)
        wait_for(lambda: self.session.state == 'approval')
        self.session.approvals['approval-1']['params']['availableDecisions'] = ['acceptForSession']
        with self.assertRaises(ChatError): self.session.answer('approval-1', accept=True)
        self.assertIn('approval-1', self.session.approvals)
        self.assertNotIn('answers', json.loads(self.store.read_text()))
        self.session.stop()

    def test_no_new_authentication_when_account_missing(self):
        self.session.close()
        missing = self.make_session()
        original = AppServer.request
        def no_account(peer, method, params=None, **kwargs):
            if method == 'account/read': return {'account': None}
            return original(peer, method, params, **kwargs)
        with patch.object(AppServer, 'request', no_account):
            with self.assertRaises(ChatError) as error: missing.connect()
        self.assertEqual(error.exception.code, 'authentication_required')
        self.assertFalse(missing.connected)
        methods = [x['method'] for x in json.loads(self.store.read_text())['requests']]
        self.assertFalse(any('login' in x.lower() for x in methods))


if __name__ == '__main__':
    unittest.main()
