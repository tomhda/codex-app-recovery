"""Capture only the idle tool UI for README; never connect to Codex."""
import ctypes
from pathlib import Path
import sys
import tkinter as tk
from PIL import ImageGrab

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import recovery

original = tk.Tk


def factory(*args, **kwargs):
    app = original(*args, **kwargs)
    def capture():
        app.update_idletasks()
        user32 = ctypes.windll.user32
        user32.GetParent.argtypes = [ctypes.c_void_p]
        user32.GetParent.restype = ctypes.c_void_p
        output = ROOT / 'docs' / 'screenshot.png'
        output.parent.mkdir(exist_ok=True)
        ImageGrab.grab(window=user32.GetParent(app.winfo_id())).save(output)
    app.after(500, capture)
    return app


tk.Tk = factory
recovery.gui(smoke_test=True)
