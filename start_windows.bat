@echo off
setlocal
cd /d "%~dp0"
title Badeel

rem ---------------------------------------------------------------
rem  Badeel - one-click start for Windows.
rem  First run: creates .venv, installs the libraries (needs internet),
rem  creates the database and asks you to choose the admin password.
rem  Next runs: just starts the site and opens the browser.
rem ---------------------------------------------------------------

if not exist "badeel\__init__.py" (
  echo.
  echo  [!] The project files are not next to this script.
  echo      Extract the whole zip first: right-click the zip file, choose "Extract All",
  echo      open the extracted folder, then double-click start_windows.bat again.
  echo.
  pause
  exit /b 1
)

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY goto nopython
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 goto nopython

if not exist ".venv\Scripts\python.exe" (
  echo Creating the project environment, first run only...
  %PY% -m venv .venv
  if errorlevel 1 goto fail
)
set "VPY=.venv\Scripts\python.exe"

if not exist ".venv\badeel_installed.txt" (
  echo Installing libraries, first run only. Needs internet, takes 1 to 3 minutes...
  "%VPY%" -m pip install --disable-pip-version-check -r requirements.txt
  if errorlevel 1 goto fail
  echo ok> ".venv\badeel_installed.txt"
)

"%VPY%" manage.py setup
if errorlevel 1 goto fail

echo.
set "BADEEL_OPEN_BROWSER=1"
"%VPY%" run.py
echo.
echo The site has stopped.
pause
exit /b 0

:nopython
echo.
echo  [!] Python 3.10 or newer was not found on this computer.
echo      1. Download Python from https://www.python.org/downloads/
echo      2. In the installer, tick "Add python.exe to PATH", then click Install Now.
echo      3. Close this window and double-click start_windows.bat again.
echo.
pause
exit /b 1

:fail
echo.
echo  [!] A step failed. Read the last lines above, or take a screenshot of this window.
echo.
pause
exit /b 1
