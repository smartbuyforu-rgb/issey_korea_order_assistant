@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo ==============================================
echo INSTALL STANDARD PYTHON 3.12
echo ==============================================
where winget >nul 2>nul
if errorlevel 1 goto :manual
winget install --exact --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto :manual
echo.
echo [OK] Python 3.12 installation command completed.
echo Close this window, then run 01_INSTALL.bat.
pause
exit /b 0
:manual
start "" "https://www.python.org/downloads/windows/"
echo Install standard Python 3.12, not the free-threaded option.
pause
exit /b 1
