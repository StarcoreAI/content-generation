@echo off
setlocal
cd /d "%~dp0"

if /I "%~1"=="--logged" goto Main
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_with_operator_log.ps1" -Name setup -ScriptPath "%~f0"
set "GEO_EXIT=%ERRORLEVEL%"
pause
exit /b %GEO_EXIT%

:Main
echo [GEO] Windows operator setup...

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_operator_windows.ps1"
if errorlevel 1 (
  echo [ERROR] setup failed. Read the message above, then run this file again.
  exit /b 1
)

echo [GEO] setup finished. Starting first platform login...
call "%~dp0scripts\first_login_all_platforms.bat" --no-pause
if errorlevel 1 (
  echo [ERROR] first login failed. Run setup_operator_windows.bat again later.
  exit /b 1
)

echo [GEO] setup and first login finished.
echo [GEO] Next: run start_local_crawl_worker.bat
exit /b 0
