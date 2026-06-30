@echo off
chcp 65001 >nul
setlocal
title GEO Agent Restart

call stop.bat

if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
) else (
    set "PYTHON=python"
)

if not exist logs mkdir logs
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_server.ps1"
if errorlevel 1 (
    echo Failed to start GEO Agent.
    exit /b 1
)
