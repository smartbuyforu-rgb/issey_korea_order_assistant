@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
if not exist ".venv\Scripts\python.exe" goto :notinstalled
set /p "HANDLE=Product handle or product ID: "
if not defined HANDLE goto :error
set /p "VARIANT=Variant title, size, SKU, or variant ID (optional): "
".venv\Scripts\python.exe" issey_order_assistant.py purchase-assist --handle "%HANDLE%" --variant "%VARIANT%"
set "RC=%ERRORLEVEL%"
pause
exit /b %RC%
:notinstalled
echo [ERROR] Run 01_INSTALL.bat first.
pause
exit /b 1
:error
echo [ERROR] Product handle is required.
pause
exit /b 1
