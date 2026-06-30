@echo off
chcp 65001 >nul
setlocal
title GEO Agent Stop

echo Stopping GEO Agent...

for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":5000 .*LISTENING"') do (
    echo Stop PID %%P on port 5000
    taskkill /PID %%P /F >nul 2>&1
)

if exist server.pid (
    for /f %%P in (server.pid) do (
        echo Stop PID %%P from server.pid
        taskkill /PID %%P /F >nul 2>&1
    )
    del server.pid >nul 2>&1
)

echo Done.

