@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
if not exist ".venv\Scripts\python.exe" goto :notinstalled
".venv\Scripts\python.exe" issey_order_assistant.py collect
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" (
  echo [OK] Collection completed.
  start "" "%CD%\index.html"
) else (
  echo [ERROR] Collection failed. Run 07_DIAGNOSE.bat.
)
pause
exit /b %RC%
:notinstalled
echo [ERROR] Run 01_INSTALL.bat first.
pause
exit /b 1
