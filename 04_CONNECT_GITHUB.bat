@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
echo ==============================================
echo CONNECT TO GITHUB
echo ==============================================
where git >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Git for Windows was not found.
  echo Install: winget install --id Git.Git -e --source winget
  pause
  exit /b 1
)
echo Create an empty PUBLIC repository first.
set /p "REPO_URL=Repository HTTPS URL: "
if not defined REPO_URL goto :error
set /p "GITHUB_USER=GitHub username for this repository: "
if not exist ".git" git init
if errorlevel 1 goto :error
git branch -M main
for /f "delims=" %%A in ('git remote 2^>nul') do if /I "%%A"=="origin" git remote remove origin
git remote add origin "%REPO_URL%"
if errorlevel 1 goto :error
if defined GITHUB_USER git config credential.username "%GITHUB_USER%"
git config credential.gitHubAccountFiltering false
git config user.name >nul 2>nul
if errorlevel 1 git config user.name "issey-catalog"
git config user.email >nul 2>nul
if errorlevel 1 git config user.email "catalog@users.noreply.github.com"
git add .
git commit -m "Initial ISSEY Korea catalog"
if errorlevel 1 (
  git status --porcelain | findstr . >nul
  if not errorlevel 1 goto :error
)
echo Approve the correct GitHub account in the browser sign-in window.
git push -u origin main
if errorlevel 1 goto :autherror
echo [OK] GitHub connection completed.
echo Enable Pages: Settings - Pages - main - root.
pause
exit /b 0
:autherror
echo [ERROR] Push failed. A different GitHub account may be cached.
echo Open Windows Credential Manager and remove git:https://github.com, then retry.
pause
exit /b 2
:error
echo [ERROR] GitHub connection failed.
pause
exit /b 1
