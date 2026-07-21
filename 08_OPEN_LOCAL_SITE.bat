@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto :notinstalled
start "" "http://127.0.0.1:8765/"
echo Local site: http://127.0.0.1:8765/
echo Press Ctrl+C to stop the server.
".venv\Scripts\python.exe" -m http.server 8765
exit /b %ERRORLEVEL%
:notinstalled
echo [ERROR] Run 01_INSTALL.bat first.
pause
exit /b 1
