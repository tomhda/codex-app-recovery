import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

from chat_client import ChatSession


@unittest.skipUnless(sys.platform == 'win32', 'Windows Tk UI')
class ChatGuiTests(unittest.TestCase):
    def test_input_stream_followup_controls_stop_retry_and_restore(self):
        import tkinter as tk
        from chat_ui import ChatPanel
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            command = [sys.executable, str(Path(__file__).with_name('fake_app_server.py')), str(path / 'peer.json')]
            session = ChatSession(path / 'session.json', command)
            root = tk.Tk()
            root.geometry('820x850')
            panel = ChatPanel(root, session)
            panel.pack(fill='both', expand=True)
            panel.cwd.set(folder)
            def pump(condition):
                deadline = time.monotonic() + 6
                while time.monotonic() < deadline:
                    root.update()
                    if condition(): return
                    time.sleep(0.02)
                self.fail('UI condition timeout: ' + panel.status.get())
            try:
                panel.connect_button.invoke()
                pump(lambda: not panel.working and session.connected)
                for text in ('first from UI', 'followup from UI'):
                    panel.input.insert('1.0', text)
                    panel.send_button.invoke()
                    pump(lambda: not panel.working and session.state == 'idle' and not panel.input.get('1.0', 'end-1c'))
                self.assertIn('Hello world', panel.output.get('1.0', 'end'))
                self.assertIn('followup from UI', panel.output.get('1.0', 'end'))
                panel.input.insert('1.0', '[wait]')
                panel.send_button.invoke()
                pump(lambda: session.state == 'running' and not panel.working)
                self.assertTrue(panel.send_button.instate(['disabled']))
                panel.stop_button.invoke()
                pump(lambda: session.state == 'stopped' and not panel.retry_button.instate(['disabled']))
                with patch('chat_ui.messagebox.askyesno', return_value=True):
                    panel.retry_button.invoke()
                pump(lambda: session.turn_id == 'turn-4' and not panel.working)
                panel.stop_button.invoke()
                pump(lambda: session.state == 'stopped')
                self.assertLess(panel.send_button.winfo_rooty() + panel.send_button.winfo_height(), root.winfo_rooty() + root.winfo_height())
                self.assertEqual(len(json.loads((path / 'peer.json').read_text())['turns']), 4)
            finally:
                panel.shutdown()
                session.close()
                root.destroy()
