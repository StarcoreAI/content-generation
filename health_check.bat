@echo off
chcp 65001 >nul
setlocal
title GEO Agent Health Check

if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
) else (
    set "PYTHON=python"
)

echo [1/3] Port 5000
netstat -ano | findstr /R /C:":5000 .*LISTENING"
if errorlevel 1 (
    echo Port 5000 is not listening.
) else (
    echo Port 5000 is listening.
)
echo.

echo [2/3] API health
%PYTHON% -c "import json, urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:5000/api/health', timeout=5)), ensure_ascii=False, indent=2))"
if errorlevel 1 (
    echo API health check failed.
    exit /b 1
)
echo.

echo [3/3] Platform login states
%PYTHON% -c "import json, urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:5000/api/platform/list', timeout=5)), ensure_ascii=False, indent=2))"
exit /b %errorlevel%

