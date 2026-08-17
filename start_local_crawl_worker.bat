@echo off
setlocal
cd /d "%~dp0"

if /I "%~1"=="--logged" goto Main

set "GEO_WORKER_USERNAME="
set "GEO_WORKER_PASSWORD="

:AskCloudUsername
set /p "GEO_WORKER_USERNAME=Cloud username: "
if "%GEO_WORKER_USERNAME%"=="" (
  echo [GEO] Cloud username is required.
  goto AskCloudUsername
)

:AskCloudPassword
set /p "GEO_WORKER_PASSWORD=Cloud password: "
if "%GEO_WORKER_PASSWORD%"=="" (
  echo [GEO] Cloud password is required.
  goto AskCloudPassword
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_with_operator_log.ps1" -Name worker -ScriptPath "%~f0"
set "GEO_EXIT=%ERRORLEVEL%"
pause
exit /b %GEO_EXIT%

:Main
echo [GEO] starting local crawl worker...

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python was not found.
  exit /b 1
)

where node >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Node.js was not found.
  exit /b 1
)

if "%GEO_WORKER_BASE_URL%"=="" set "GEO_WORKER_BASE_URL=http://8.160.116.86:18080"
set "GEO_WORKER_PLATFORMS=all"

if "%GEO_WORKER_USERNAME%"=="" (
  echo [ERROR] Cloud username was not provided.
  exit /b 1
)

if "%GEO_WORKER_PASSWORD%"=="" (
  echo [ERROR] Cloud password was not provided.
  exit /b 1
)

echo [GEO] detecting local crawler folder...
set "GEO_NODE_CRAWLER_ROOT="
for /f "usebackq delims=" %%I in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\resolve_node_crawler_root.ps1"`) do set "GEO_NODE_CRAWLER_ROOT=%%I"

if not exist "%GEO_NODE_CRAWLER_ROOT%\src\adapters\index.js" (
  echo [ERROR] Node crawler folder was not found automatically.
  echo Please keep geo_v2-pro and ai-search-crawler in the same parent folder.
  exit /b 1
)

if not exist "%GEO_NODE_CRAWLER_ROOT%\storage" mkdir "%GEO_NODE_CRAWLER_ROOT%\storage"
set "STORAGE_STATE_PATH=%GEO_NODE_CRAWLER_ROOT%\storage\state.json"

echo [GEO] environment preflight check...
python scripts\local_crawl_worker.py --base-url "%GEO_WORKER_BASE_URL%" --platforms "%GEO_WORKER_PLATFORMS%" --check --auth-mode none
if errorlevel 1 (
  echo [ERROR] preflight check failed.
  exit /b 1
)

echo [GEO] opening local control panel...
start "GEO Local Crawler Control" powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0scripts\local_worker_control_panel.ps1"

echo [GEO] waiting for cloud crawl jobs...
python scripts\local_crawl_worker.py --base-url "%GEO_WORKER_BASE_URL%" --platforms "%GEO_WORKER_PLATFORMS%"
set "GEO_EXIT=%ERRORLEVEL%"

echo [GEO] worker exited.
exit /b %GEO_EXIT%
