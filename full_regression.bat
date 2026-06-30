@echo off
chcp 65001 >nul
setlocal
title GEO Agent Full Regression

if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
) else (
    set "PYTHON=python"
)

echo Running unattended GEO Agent regression...
echo Reports will be written to the reports folder.
echo.

%PYTHON% scripts\full_regression.py %*
set "CODE=%ERRORLEVEL%"

echo.
if "%CODE%"=="0" (
    echo Regression finished.
) else (
    echo Regression finished with errors. Check the report for details.
)
exit /b %CODE%
