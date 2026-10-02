"""Capture the window for the README with sample data; never connects to Codex.

--live captures the real current state instead (read-only) to a given path.
"""
import argparse
import ctypes
import datetime
from pathlib import Path
import sys
import tkinter as tk
from unittest.mock import patch

from PIL import ImageGrab

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import recovery  # noqa: E402
from i18n import set_language, tr  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument('--lang', choices=('ja', 'en'), default='ja')
parser.add_argument('--live', metavar='PNG', help='Capture the real state to this file.')
options = parser.parse_args()
set_language(options.lang)
captured = False
original = tk.Tk

SAMPLE_OVERVIEW = {'installed': True, 'running': True, 'port': True, 'portForeign': False, 'daemon': True,
                   'page': {'blank': False, 'ageMs': 600000, 'guard': {'version': '1.3.0'}}}
now = datetime.datetime.now().replace(second=0, microsecond=0)
SAMPLE_EVENTS = [
    (now, tr('停止後の「再開」を補正して、キューを送信しました。')),
    (now - datetime.timedelta(minutes=12), tr('{what}の応答が届かなかったため、取り直しました。').format(what=tr('送信キューの読み込み'))),
    (now - datetime.timedelta(minutes=40), tr('起動時の初期化情報を取り直しました（ロゴのまま止まる不具合の補正）。')),
]


def factory(*args, **kwargs):
    app = original(*args, **kwargs)

    def capture():
        global captured
        app.update_idletasks()
        user32 = ctypes.windll.user32
        user32.GetParent.argtypes = [ctypes.c_void_p]
        user32.GetParent.restype = ctypes.c_void_p
        if options.live:
            output = Path(options.live)
        else:
            output = ROOT / 'docs' / ('screenshot.png' if options.lang == 'ja' else 'screenshot-en.png')
        output.parent.mkdir(exist_ok=True)
        ImageGrab.grab(window=user32.GetParent(app.winfo_id())).save(output)
        captured = True
    app.after(6000 if options.live else 1200, capture)
    return app


tk.Tk = factory
if options.live:
    recovery.gui(smoke_test=True, smoke_ms=7000)
else:
    with patch.object(recovery.control, 'overview', return_value=SAMPLE_OVERVIEW), \
         patch.object(recovery.guard_events, 'recent', return_value=SAMPLE_EVENTS):
        recovery.gui(smoke_test=True)
if not captured:
    raise SystemExit('UI capture failed')
