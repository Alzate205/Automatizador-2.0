@echo off
cd /d "%~dp0"
start "" http://localhost:8000
python -m uvicorn webapp.servidor:app --host 127.0.0.1 --port 8000
