"""Capture only the idle tool UI for README; never connect to Codex."""
import ctypes
import argparse
from pathlib import Path
import sys
import tkinter as tk
from PIL import ImageGrab

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import recovery
from i18n import set_language

parser = argparse.ArgumentParser()
parser.add_argument('--lang', choices=('ja', 'en'), default='ja')
options = parser.parse_args()
set_language(options.lang)
captured = False

original = tk.Tk


def factory(*args, **kwargs):
    app = original(*args, **kwargs)
    def capture():
        global captured
        app.update_idletasks()
        user32 = ctypes.windll.user32
        user32.GetParent.argtypes = [ctypes.c_void_p]
        user32.GetParent.restype = ctypes.c_void_p
        output = ROOT / 'docs' / ('screenshot.png' if options.lang == 'ja' else 'screenshot-en.png')
        output.parent.mkdir(exist_ok=True)
        ImageGrab.grab(window=user32.GetParent(app.winfo_id())).save(output)
        captured = True
    app.after(500, capture)
    return app


tk.Tk = factory
recovery.gui(smoke_test=True)
if not captured:
    raise SystemExit('UI capture failed')
