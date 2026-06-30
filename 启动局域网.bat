@echo off
chcp 65001 >nul
setlocal
title GEO Agent LAN Launcher

echo ====================================
echo    GEO Agent 局域网演示启动
echo ====================================
echo.

if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
) else (
    set "PYTHON=python"
)

for /f "usebackq tokens=*" %%i in (`powershell -NoProfile -Command "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | Select-Object -First 1 -ExpandProperty IPAddress"`) do set "LAN_IP=%%i"

set "GEO_HOST=0.0.0.0"
set "GEO_PORT=5000"

echo 本机访问:
echo   http://localhost:%GEO_PORT%
echo.
if defined LAN_IP (
    echo 局域网访问:
    echo   http://%LAN_IP%:%GEO_PORT%
) else (
    echo 局域网访问:
    echo   请运行 ipconfig 查看 IPv4 地址，然后访问 http://IPv4地址:%GEO_PORT%
)
echo.
echo 注意:
echo - 只在可信内网使用，不要暴露到公网。
echo - 如其他电脑无法访问，请检查 Windows 防火墙是否允许 5000 端口。
echo - 关闭此窗口会停止服务。
echo.

%PYTHON% app.py
pause
