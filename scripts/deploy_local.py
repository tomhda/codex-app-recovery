"""Install this working copy for the current user without a virtual environment.

Copies the runtime files to %USERPROFILE%\\.codex\\tools\\app-recovery (or --target),
moves anything else that was there into a dated backup folder, recreates the
two Start-menu shortcuts with the current Python, and restarts the guard
companion so it runs the new files. Requires websocket-client in this Python.
"""
from __future__ import annotations

import argparse
import datetime
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RUNTIME = ['recovery.py', 'codex_control.py', 'guard_events.py', 'work_monitor.py', 'guard.js', 'guard_daemon.py', 'i18n.py', 'chat_client.py', 'chat_ui.py']
OLD_SHORTCUTS = ['Codex（自己修復ガード付き）.lnk', 'Codex App Recovery.lnk']


def stop_daemon(target: Path) -> None:
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' or Name='python.exe'\" | "
        "Where-Object { $_.CommandLine -like ('*' + $env:GUARD_PATH + '*') } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
    )
    subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                   env=dict(os.environ, GUARD_PATH=str(target / 'guard_daemon.py')), capture_output=True, timeout=30)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', default=str(Path.home() / '.codex' / 'tools' / 'app-recovery'))
    parser.add_argument('--no-shortcuts', action='store_true')
    args = parser.parse_args()
    import websocket  # noqa: F401  (fail before touching anything)
    target = Path(args.target)
    target.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    backup = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'CodexAppRecovery' / 'backups' / f'{stamp}-app-recovery-before-deploy'
    stop_daemon(target)
    time.sleep(1)
    moved = 0
    for item in list(target.iterdir()):
        if item.name in ('logs',):
            continue
        backup.mkdir(parents=True, exist_ok=True)
        shutil.move(str(item), str(backup / item.name))
        moved += 1
    for name in RUNTIME:
        shutil.copy2(ROOT / name, target / name)
    print(f'Installed {len(RUNTIME)} files to {target}' + (f'; previous files moved to {backup}' if moved else ''))
    if not args.no_shortcuts:
        from setup_recovery import create_shortcuts
        programs = Path(os.environ['APPDATA']) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs'
        for name in OLD_SHORTCUTS:
            (programs / name).unlink(missing_ok=True)
        pythonw = Path(sys.executable).with_name('pythonw.exe')
        for name in ('Codex（ガード付き）.lnk', 'Codex 復旧.lnk'):
            (programs / name).unlink(missing_ok=True)
        for path in create_shortcuts(pythonw, root=target):
            print('Shortcut:', path)
    subprocess.Popen([str(Path(sys.executable).with_name('pythonw.exe')), str(target / 'guard_daemon.py')],
                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) | getattr(subprocess, 'DETACHED_PROCESS', 0), close_fds=True)
    print('Guard companion restarted.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
