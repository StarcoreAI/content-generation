@echo off
chcp 65001 >nul
setlocal
title GEO Agent Launcher

echo ====================================
echo    GEO Agent v2.3 Launcher
echo ====================================
echo.

if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
    goto :check_deps
)

python --version >nul 2>&1
if %errorlevel% == 0 (
    python -m venv .venv
    set "PYTHON=.venv\Scripts\python.exe"
    goto :check_deps
)

py --version >nul 2>&1
if %errorlevel% == 0 (
    py -m venv .venv
    set "PYTHON=.venv\Scripts\python.exe"
    goto :check_deps
)

echo [ERROR] Python 3.10+ was not found. Install Python and add it to PATH.
pause
exit /b 1

:check_deps
echo [1/3] Python version
%PYTHON% --version
echo.

echo [2/3] Install dependencies
%PYTHON% -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
if errorlevel 1 (
    echo [WARN] pip install failed. Continuing anyway.
)
%PYTHON% -m playwright install chromium
echo.

echo [3/3] Start GEO Agent
echo Local: http://localhost:5000
for /f "usebackq tokens=*" %%i in (`powershell -NoProfile -Command "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | Select-Object -First 1 -ExpandProperty IPAddress"`) do set "LAN_IP=%%i"
if defined LAN_IP echo LAN:   http://%LAN_IP%:5000
echo Close this window to stop the app.
echo.
%PYTHON% app.py
pause

