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

from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import io as _io
import pandas as _pd

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


# ---------------- API: cuentas ----------------

@app.get("/api/cuentas")
def api_cuentas_get():
    return datos.cuentas_como_dict()


@app.post("/api/cuentas")
async def api_cuentas_post(request: Request):
    body = await request.json()
    n = datos.guardar_cuentas(body.get("filas", []))
    return {"ok": True, "guardadas": n}


@app.post("/api/cuentas/plantilla")
async def api_cuentas_plantilla(request: Request):
    body = await request.json()
    df = datos.generar_plantilla_registro(int(body.get("n", 10)))
    df.to_excel(datos.RUTA_EXCEL, index=False)
    return {"ok": True, "guardadas": len(df)}


@app.post("/api/cuentas/registrar")
async def api_cuentas_registrar(request: Request):
    fila = await request.json()
    total = datos.anexar_cuenta(fila)
    return {"ok": True, "total": total}


@app.post("/api/cuentas/importar")
async def api_cuentas_importar(archivo: UploadFile = File(...)):
    contenido = await archivo.read()
    df = _pd.read_excel(_io.BytesIO(contenido))
    df.to_excel(datos.RUTA_EXCEL, index=False)
    return {"ok": True, "guardadas": len(df)}


# ---------------- Estáticos (al final para no tapar /api) ----------------

app.mount("/", StaticFiles(directory=str(_STATIC), html=True), name="static")
