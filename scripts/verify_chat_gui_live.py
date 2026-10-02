"""Opt-in integration test of our Tk window/buttons with a dedicated CLI thread."""
import argparse
import json
from pathlib import Path
import sys
import time
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import recovery
from chat_client import ChatSession
from chat_ui import ChatPanel

parser = argparse.ArgumentParser()
parser.add_argument('--cli', required=True)
parser.add_argument('--directory', required=True)
args = parser.parse_args()
folder = Path(args.directory).resolve()
folder.mkdir(parents=True, exist_ok=True)
session = ChatSession(folder / 'gui-session.json', [args.cli])
report = {'checks': [], 'error': None}
original = tk.Tk
step = 0
deadline = time.monotonic() + 180
def factory(*a, **kw):
    app = original(*a, **kw)
    def widgets(widget):
        yield widget
        for child in widget.winfo_children():
            yield from widgets(child)
    def tick():
        global step
        panel = None
        try:
            panel = next((w for w in widgets(app) if isinstance(w, ChatPanel)), None)
            if time.monotonic() > deadline:
                report['lastState'] = {'step': step, 'session': session.diagnostics(),
                    'working': panel.working if panel else None,
                    'inputLength': len(panel.input.get('1.0', 'end-1c')) if panel else None,
                    'outputLength': len(panel.output.get('1.0', 'end')) if panel else None}
                raise RuntimeError('GUI integration deadline')
            if panel is None:
                app.after(50, tick); return
            notebook = next(w for w in widgets(app) if isinstance(w, ttk.Notebook))
            if step == 0:
                notebook.select(panel)
                panel.cwd.set(str(folder))
                panel.connect_button.invoke()
                step = 1
                print('GUI connecting', flush=True)
            elif step == 1 and session.state == 'idle' and not panel.working:
                panel.input.insert('1.0', 'Do not use tools. Remember GUI_MARKER_619 and reply exactly GUI_FIRST_OK.')
                panel.send_button.invoke(); step = 2
                print('GUI first sent', flush=True)
            elif step == 2 and session.state == 'idle' and not panel.working and not panel.input.get('1.0', 'end-1c'):
                if 'GUI_FIRST_OK' not in panel.output.get('1.0', 'end'):
                    app.after(50, tick); return
                report['checks'].append({'name': 'gui_first_visible', 'passed': True})
                panel.input.insert('1.0', 'Do not use tools. Reply with our remembered marker only.')
                panel.send_button.invoke(); step = 3
                print('GUI followup sent', flush=True)
            elif step == 3 and session.state == 'idle' and not panel.working and not panel.input.get('1.0', 'end-1c'):
                output = panel.output.get('1.0', 'end')
                if output.count('GUI_MARKER_619') < 2:
                    app.after(50, tick); return
                report['checks'].append({'name': 'gui_followup_visible', 'passed': True})
                report['checks'].append({'name': 'send_control_visible', 'passed': panel.send_button.winfo_rooty() + panel.send_button.winfo_height() <= app.winfo_rooty() + app.winfo_height()})
                report['windowTitle'] = app.title()
                report['diagnostics'] = session.diagnostics()
                print(json.dumps(report, ensure_ascii=False), flush=True)
                app.eval(app.protocol('WM_DELETE_WINDOW'))
                return
            elif session.state in ('error', 'unknown', 'approval'):
                raise RuntimeError('GUI state: ' + session.state + ' / ' + str(session.error))
        except Exception as error:
            report['error'] = str(error)
            if panel:
                panel.shutdown()
            session.close()
            app.destroy()
            return
        app.after(50, tick)
    app.after(100, tick)
    return app
try:
    with patch.object(tk, 'Tk', factory), patch('chat_ui.ChatSession', return_value=session):
        recovery.gui()
finally:
    session.close()
    (folder / 'gui-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
if report['error'] or not report['checks'] or not all(x['passed'] for x in report['checks']):
    raise SystemExit('GUI integration failed: ' + str(report['error']))
