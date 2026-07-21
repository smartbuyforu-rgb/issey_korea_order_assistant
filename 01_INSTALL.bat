@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHONUTF8=1"
echo ==============================================
echo ISSEY KOREA ORDER ASSISTANT - INSTALL v2

echo ==============================================
set "PY_CMD="
py -3.12 -c "import sys,sysconfig; raise SystemExit(0 if sys.version_info[:2]==(3,12) and not bool(sysconfig.get_config_var('Py_GIL_DISABLED')) else 1)" >nul 2>nul
if not errorlevel 1 set "PY_CMD=py -3.12"
if not defined PY_CMD (
  py -3.13 -c "import sys,sysconfig; raise SystemExit(0 if sys.version_info[:2]==(3,13) and not bool(sysconfig.get_config_var('Py_GIL_DISABLED')) else 1)" >nul 2>nul
  if not errorlevel 1 set "PY_CMD=py -3.13"
)
if not defined PY_CMD (
  py -3.11 -c "import sys,sysconfig; raise SystemExit(0 if sys.version_info[:2]==(3,11) and not bool(sysconfig.get_config_var('Py_GIL_DISABLED')) else 1)" >nul 2>nul
  if not errorlevel 1 set "PY_CMD=py -3.11"
)
if not defined PY_CMD goto :python_required
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys,sysconfig; ok=sys.version_info[:2] in ((3,11),(3,12),(3,13)) and not bool(sysconfig.get_config_var('Py_GIL_DISABLED')); raise SystemExit(0 if ok else 1)" >nul 2>nul
  if errorlevel 1 rmdir /s /q ".venv"
)
if not exist ".venv\Scripts\python.exe" %PY_CMD% -m venv .venv
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install --only-binary=:all: -r requirements.txt
if errorlevel 1 goto :binary_error
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 goto :error
echo.
echo [OK] Installation completed.
echo Next, run 02_LOGIN.bat
pause
exit /b 0
:python_required
echo [ERROR] Compatible standard Python was not found.
echo Run 00_INSTALL_PYTHON_312.bat, then retry.
pause
exit /b 2
:binary_error
echo [ERROR] A prebuilt package could not be installed.
echo Install standard Python 3.12 and delete .venv, then retry.
pause
exit /b 3
:error
echo [ERROR] Installation failed.
pause
exit /b 1
