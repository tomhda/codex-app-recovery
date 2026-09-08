@echo off
setlocal
if not exist "%~dp0.venv\Scripts\pythonw.exe" goto missing
"%~dp0.venv\Scripts\python.exe" -c "import tkinter, websocket" >nul 2>&1
if errorlevel 1 goto missing
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0recovery.py"
exit /b 0
:missing
echo Setup is required. Double-click Setup.bat in this folder first.
pause
exit /b 1
