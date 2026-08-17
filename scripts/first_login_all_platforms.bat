@echo off
setlocal
cd /d "%~dp0.."

echo [GEO] first login for all crawler platforms...

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python was not found. Run setup_operator_windows.bat first.
  exit /b 1
)

where node >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Node.js was not found. Run setup_operator_windows.bat first.
  exit /b 1
)

set "GEO_WORKER_PLATFORMS=all"

echo [GEO] detecting local crawler folder...
set "GEO_NODE_CRAWLER_ROOT="
for /f "usebackq delims=" %%I in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\scripts\resolve_node_crawler_root.ps1"`) do set "GEO_NODE_CRAWLER_ROOT=%%I"

if not exist "%GEO_NODE_CRAWLER_ROOT%\src\adapters\index.js" (
  echo [ERROR] Node crawler folder was not found automatically.
  echo Please keep geo_v2-pro and ai-search-crawler in the same parent folder.
  exit /b 1
)

if not exist "%GEO_NODE_CRAWLER_ROOT%\storage" mkdir "%GEO_NODE_CRAWLER_ROOT%\storage"
set "STORAGE_STATE_PATH=%GEO_NODE_CRAWLER_ROOT%\storage\state.json"

echo [GEO] opening each platform for login...
echo [GEO] Finish login in the browser and DO NOT close it manually.
echo [GEO] The browser closes only after the login state is saved, then the next platform opens.
python scripts\local_crawl_worker.py --platforms "%GEO_WORKER_PLATFORMS%" --local-login-only
if errorlevel 1 (
  echo [ERROR] first login failed.
  exit /b 1
)

echo [GEO] first login finished.
if /I "%~1"=="--no-pause" exit /b 0
pause
