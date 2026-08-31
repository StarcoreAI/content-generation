@echo off
chcp 65001 >nul
setlocal
title GEO Agent Dev Server

cd /d "%~dp0"

if not defined GEO_HOST set "GEO_HOST=127.0.0.1"
if not defined GEO_PORT set "GEO_PORT=5000"
if not defined PLAYWRIGHT_BROWSERS_PATH set "PLAYWRIGHT_BROWSERS_PATH=%~dp0.runtime\playwright-browsers"
if not defined GEO_NODE_CRAWLER_PLATFORMS set "GEO_NODE_CRAWLER_PLATFORMS=none"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
) else (
    echo [ERROR] .venv was not found.
    echo See README.md for first-time setup.
    exit /b 1
)

echo ====================================
echo    GEO Agent v2.3 Dev Server
echo ====================================
echo Local: http://localhost:%GEO_PORT%

if "%GEO_HOST%"=="0.0.0.0" (
    for /f "usebackq tokens=*" %%i in (`powershell -NoProfile -Command "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | Select-Object -First 1 -ExpandProperty IPAddress"`) do set "LAN_IP=%%i"
    if defined LAN_IP echo LAN:   http://%LAN_IP%:%GEO_PORT%
)

echo Host: %GEO_HOST%:%GEO_PORT%
echo Close this window to stop the app.
echo.
%PYTHON% -u app.py
