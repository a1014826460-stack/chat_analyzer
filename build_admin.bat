@echo off
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
    python -m venv .venv
)
.venv\Scripts\python.exe tools\build.py --admin
