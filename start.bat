@echo off
setlocal
cd /d %~dp0

if not exist .venv (
  python -m venv .venv
)

call .venv\Scripts\python.exe -m pip install --upgrade pip
call .venv\Scripts\pip.exe install -r requirements.txt
call .venv\Scripts\python.exe scripts\bootstrap_env.py
call .venv\Scripts\python.exe run.py

endlocal
