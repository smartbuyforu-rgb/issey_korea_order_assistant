@echo off
setlocal EnableExtensions
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$startup=[Environment]::GetFolderPath('Startup'); $target=Join-Path '%~dp0' '05_START_CATALOG_SYNC.bat'; $ws=New-Object -ComObject WScript.Shell; $link=Join-Path $startup 'ISSEY Korea Catalog Sync.lnk'; $lnk=$ws.CreateShortcut($link); $lnk.TargetPath=$target; $lnk.WorkingDirectory='%~dp0'; $lnk.WindowStyle=7; $lnk.Save(); Write-Host '[OK] Startup shortcut created.'"
pause
