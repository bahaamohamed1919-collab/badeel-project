@echo off
setlocal
cd /d "%~dp0"
title Badeel - portable copy
rem ---------------------------------------------------------------
rem  Makes the folder Badeel_Portable next to this project folder.
rem  It runs on another Windows PC with nothing installed.
rem  Run start_windows.bat once before this (it creates .venv).
rem ---------------------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo  [!] Run start_windows.bat once first, then run this file again.
  echo.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" tools\make_portable.py
echo.
pause
