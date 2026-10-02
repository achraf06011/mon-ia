@echo off
cd /d "%~dp0"
start "" http://localhost:8002
python web.py
