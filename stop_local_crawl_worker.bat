@echo off
setlocal
cd /d "%~dp0"

if /I "%~1"=="--logged" goto Main
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_with_operator_log.ps1" -Name stop-worker -ScriptPath "%~f0"
set "GEO_EXIT=%ERRORLEVEL%"
pause
exit /b %GEO_EXIT%

:Main
echo [GEO] stopping local crawl worker...

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_local_crawl_worker.ps1"
if errorlevel 1 (
  echo [ERROR] failed to stop local crawl worker.
  exit /b 1
)

echo [GEO] local crawl worker stopped.
exit /b 0
