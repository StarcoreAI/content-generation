@echo off
chcp 65001 >nul
setlocal

if exist ".venv\Scripts\python.exe" (
    set PYTHON=.venv\Scripts\python.exe
) else (
    set PYTHON=python
)

echo [1/2] Python compile check
%PYTHON% -m py_compile app.py base_crawler.py deepseek_crawler.py doubao_crawler.py qwen_crawler.py yuanbao_crawler.py scripts\full_regression.py
if errorlevel 1 exit /b 1

echo [2/2] Unit tests
%PYTHON% -m unittest discover -s tests -p "test_*.py" -v
exit /b %errorlevel%
