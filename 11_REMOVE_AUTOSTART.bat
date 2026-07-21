@echo off
setlocal EnableExtensions
powershell -NoProfile -ExecutionPolicy Bypass -Command "$link=Join-Path ([Environment]::GetFolderPath('Startup')) 'ISSEY Korea Catalog Sync.lnk'; if(Test-Path $link){Remove-Item $link -Force; Write-Host '[OK] Startup shortcut removed.'}else{Write-Host '[INFO] No startup shortcut found.'}"
pause
