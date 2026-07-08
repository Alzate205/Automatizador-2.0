@echo off
cd /d "%~dp0"
start "" http://localhost:8000
rem --reload: si se actualiza el codigo (endpoints nuevos, arreglos), el servidor se
rem recarga solo. Sin esto, un endpoint nuevo (p. ej. Cancelar) no existe hasta
rem cerrar y volver a abrir esta ventana. Solo vigila archivos .py (no toca el bot).
python -m uvicorn webapp.servidor:app --host 127.0.0.1 --port 8000 --reload --reload-include *.py
