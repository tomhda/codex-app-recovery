@echo off
setlocal
where py >nul 2>&1
if errorlevel 1 goto python
py -3 "%~dp0setup_recovery.py"
goto result
:python
where python >nul 2>&1
if errorlevel 1 goto missing
python "%~dp0setup_recovery.py"
:result
if errorlevel 1 goto failed
echo.
echo Setup complete. Open Codex-Recovery.bat to start.
pause
exit /b 0
:missing
echo Python 3.10 or newer is required. Install Python with tkinter from python.org.
:failed
echo Setup did not complete. See the error above.
pause
exit /b 1
