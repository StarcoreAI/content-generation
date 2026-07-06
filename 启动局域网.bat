@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "GEO_HOST=0.0.0.0"
call "%~dp0run_dev.bat"
