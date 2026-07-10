@echo off
setlocal
cd /d "%~dp0"

echo [GEO] exporting operator diagnostics...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\export_operator_diagnostics.ps1"
if errorlevel 1 (
  echo [ERROR] failed to export diagnostics.
  pause
  exit /b 1
)

pause
