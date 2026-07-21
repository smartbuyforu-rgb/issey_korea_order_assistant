@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
if not exist ".venv\Scripts\python.exe" goto :notinstalled
title ISSEY KOREA CATALOG SYNC
".venv\Scripts\python.exe" issey_order_assistant.py monitor --publish
set "RC=%ERRORLEVEL%"
pause
exit /b %RC%
:notinstalled
echo [ERROR] Run 01_INSTALL.bat first.
pause
exit /b 1
