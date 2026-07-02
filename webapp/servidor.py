"""
servidor.py — Backend FastAPI del dashboard web.

Sirve la SPA estática y expone la API. Lanza main.py como subproceso y se
comunica con el bot por los archivos de control.py. Corre con cwd = raíz del
proyecto.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

import control
from webapp import datos

app = FastAPI(title="Automatizador Betplay — Dashboard")

_STATIC = Path(__file__).parent / "static"

# Handle del subproceso del bot (un solo run a la vez).
estado_proc: dict = {"proc": None}

LOG_CONSOLA = "bot_consola.log"


def _bot_vivo() -> bool:
    proc = estado_proc["proc"]
    return proc is not None and proc.poll() is None


def _lanzar_bot() -> None:
    salida = open(LOG_CONSOLA, "a", encoding="utf-8")
    estado_proc["proc"] = subprocess.Popen(
        [sys.executable, "main.py"], stdout=salida, stderr=subprocess.STDOUT
    )


# ---------------- API: control ----------------

@app.get("/api/estado")
def api_estado():
    est = control.leer_estado()
    est["proceso_vivo"] = _bot_vivo()
    return est


@app.get("/api/log")
def api_log(desde: int = 0):
    return datos.lineas_log(datos.LOG_BOT, desde)


@app.post("/api/iniciar")
async def api_iniciar(request: Request):
    if _bot_vivo():
        return JSONResponse({"error": "El bot ya está corriendo"}, status_code=409)
    cfg = await request.json()
    control.escribir_config(cfg)
    control.reset_control()
    control.escribir_estado(estado="corriendo", mensaje="Lanzando bot...",
                            indice=0, total=0, resumen={})
    _lanzar_bot()
    return {"ok": True}


@app.post("/api/detener")
def api_detener():
    control.pedir_detener()
    return {"ok": True}


@app.post("/api/continuar")
def api_continuar():
    control.pedir_continuar()
    return {"ok": True}


@app.post("/api/forzar-parada")
def api_forzar_parada():
    control.pedir_detener()
    proc = estado_proc["proc"]
    if proc is not None and proc.poll() is None:
        proc.terminate()
    return {"ok": True}


# ---------------- Estáticos (al final para no tapar /api) ----------------

app.mount("/", StaticFiles(directory=str(_STATIC), html=True), name="static")
