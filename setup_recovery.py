"""Create an isolated environment and optional Windows shortcuts."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import venv
from i18n import tr, set_language, resolve_language

ROOT = Path(__file__).resolve().parent


def create_shortcuts(pythonw, *, desktop=False, root=ROOT):
    """Create 'Codex (guarded)' (daily start) and 'Codex Recovery' shortcuts.

    Paths are passed as environment values, never interpolated into shell code.
    """
    env = os.environ.copy()
    env['CODEX_RECOVERY_PYTHON'] = str(pythonw)
    env['CODEX_RECOVERY_ROOT'] = str(root)
    env['CODEX_RECOVERY_DESKTOP'] = '1' if desktop else '0'
    env['CODEX_RECOVERY_NAMES'] = json.dumps([tr('Codex（ガード付き）'), tr('Codex 復旧')], ensure_ascii=False)
    script = r'''
    [Console]::OutputEncoding=[System.Text.Encoding]::UTF8
    $ErrorActionPreference='Stop'
    $shell=New-Object -ComObject WScript.Shell
    $names=ConvertFrom-Json $env:CODEX_RECOVERY_NAMES
    $folders=@([Environment]::GetFolderPath('Programs'))
    if($env:CODEX_RECOVERY_DESKTOP -eq '1'){$folders+= [Environment]::GetFolderPath('Desktop')}
    $entry=Join-Path $env:CODEX_RECOVERY_ROOT 'recovery.py'
    $package=Get-AppxPackage OpenAI.Codex -ErrorAction SilentlyContinue | Sort-Object Version -Descending | Select-Object -First 1
    $specs=@(@{name=$names[0]; args='"'+$entry+'" --launch'; desc='Start Codex with the self-heal guard'},
             @{name=$names[1]; args='"'+$entry+'"'; desc='Codex status, repair and backup chat'})
    $created=@()
    foreach($folder in $folders){
      foreach($spec in $specs){
        $path=Join-Path $folder ($spec.name+'.lnk')
        if(Test-Path -LiteralPath $path){
          $old=$shell.CreateShortcut($path)
          if($old.TargetPath -ne $env:CODEX_RECOVERY_PYTHON){throw ('A shortcut from a different installation already exists: '+$path)}
        }
        $shortcut=$shell.CreateShortcut($path)
        $shortcut.TargetPath=$env:CODEX_RECOVERY_PYTHON
        $shortcut.Arguments=$spec.args
        $shortcut.WorkingDirectory=$env:CODEX_RECOVERY_ROOT
        $shortcut.Description=$spec.desc
        if($package -and $spec.args -like '*--launch'){ $shortcut.IconLocation=(Join-Path $package.InstallLocation 'app\ChatGPT.exe')+',0' }
        $shortcut.Save()
        $created+=$path
      }
    }
    ConvertTo-Json -InputObject $created -Compress
    '''
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                            env=env, capture_output=True, encoding='utf-8', errors='replace', timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-shortcuts', action='store_true', help='Only create the local Python environment.')
    parser.add_argument('--lang', choices=('ja', 'en'), help='Setup dialog language.')
    args = parser.parse_args()
    set_language(resolve_language(args.lang))
    if sys.platform != 'win32' or sys.version_info < (3, 10):
        parser.exit(1, 'Windows and Python 3.10+ are required.\n')
    import tkinter  # Fail before installation if Tcl/Tk was omitted.
    tkinter.Tcl()
    environment = ROOT / '.venv'
    python = environment / 'Scripts' / 'python.exe'
    if not python.exists():
        print('Creating a local Python environment...', flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)
    print('Installing websocket-client from the configured Python package index...', flush=True)
    subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(ROOT / 'requirements.txt')], check=True)
    subprocess.run([str(python), '-c', 'import tkinter, websocket; tkinter.Tcl()'], check=True)
    if not args.no_shortcuts:
        from tkinter import messagebox
        app = tkinter.Tk()
        app.withdraw()
        try:
            if messagebox.askyesno('Codex App Recovery', tr('スタートメニューにショートカットを追加しますか？'), parent=app):
                desktop = messagebox.askyesno('Codex App Recovery', tr('デスクトップにもショートカットを追加しますか？'), parent=app)
                for path in create_shortcuts(environment / 'Scripts' / 'pythonw.exe', desktop=desktop):
                    print('Created:', path)
        finally:
            app.destroy()
    print('Ready. Open Codex-Recovery.bat. Keep this folder in its current location.')


if __name__ == '__main__':
    main()
