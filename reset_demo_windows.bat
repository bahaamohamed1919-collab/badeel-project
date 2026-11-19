@echo off
setlocal
cd /d "%~dp0"
title Badeel - reset demo
if not exist ".venv\Scripts\python.exe" (
  echo Run start_windows.bat first.
  pause
  exit /b 1
)
echo.
echo This deletes every account except the admin, all searches, saved medicines,
echo security events and the change log, then reloads the demo drugs.
echo Use it after a rehearsal, so the real presentation starts clean.
echo.
".venv\Scripts\python.exe" manage.py reset-demo
echo.
pause
