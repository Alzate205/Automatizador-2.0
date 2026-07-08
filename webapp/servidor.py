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
from fastapi.responses import JSONResponse, Response
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


@app.post("/api/log/limpiar")
def api_log_limpiar():
    """Vacía bot.log (truncar). El bot lo escribe en modo append, así que si está
    corriendo, sigue agregando desde el nuevo final sin problema."""
    try:
        with open(datos.LOG_BOT, "w", encoding="utf-8"):
            pass
    except OSError:
        pass
    return {"ok": True}


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


@app.post("/api/cancelar-espera")
def api_cancelar_espera():
    """Cancela una espera de captcha/apuesta/código.

    Crea la señal senal_cancelar.flag que el BOT consume para abortar la cuenta SIN
    enviar. NO la borramos aquí: la comunicación es por archivos justamente para que
    funcione aunque el bot corra en OTRO proceso (p. ej. si se reinició el servidor y
    perdió el handle del subproceso). Si la borráramos según `_bot_vivo()`, mataríamos
    la señal antes de que el bot la lea y el botón "no haría nada".

    Además desbloqueamos el panel: si el estado estaba en una espera, lo pasamos a
    inactivo (el bot, si sigue vivo, escribirá luego su resultado real). Cualquier
    señal que quede sin consumir se limpia en reset_control() al iniciar la próxima
    corrida."""
    control.pedir_cancelar()
    est = control.leer_estado()
    if est.get("estado") in ("esperando_captcha", "esperando_apuesta", "esperando_codigo"):
        control.escribir_estado(estado="inactivo", fase="", cuenta="",
                                mensaje="Espera cancelada por el usuario")
    return {"ok": True}


@app.post("/api/forzar-parada")
def api_forzar_parada():
    control.pedir_detener()
    proc = estado_proc["proc"]
    if proc is not None and proc.poll() is None:
        proc.terminate()
    return {"ok": True}


@app.post("/api/codigo")
async def api_codigo(request: Request):
    """Recibe el código 2FA que el usuario ingresó a mano (modo manual)."""
    body = await request.json()
    codigo = str(body.get("codigo", "")).strip()
    if not codigo:
        return JSONResponse({"error": "Código vacío"}, status_code=400)
    control.guardar_codigo(codigo)
    return {"ok": True}


# ---------------- API: cuentas ----------------

@app.get("/api/cuentas")
def api_cuentas_get():
    return datos.cuentas_como_dict()


@app.post("/api/cuentas")
async def api_cuentas_post(request: Request):
    body = await request.json()
    # auto=True (autoguardado al salir de una casilla) no genera respaldo.
    respaldar = not bool(body.get("auto", False))
    n = datos.guardar_cuentas(body.get("filas", []), respaldar=respaldar)
    return {"ok": True, "guardadas": n}


@app.post("/api/cuentas/plantilla")
async def api_cuentas_plantilla(request: Request):
    body = await request.json()
    df = datos.generar_plantilla_registro(int(body.get("n", 10)))
    datos.guardar_excel_seguro(df, datos.RUTA_EXCEL)
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
    datos.guardar_excel_seguro(df, datos.RUTA_EXCEL)
    return {"ok": True, "guardadas": len(df)}


@app.get("/api/cuentas/exportar")
def api_cuentas_exportar():
    df = datos.leer_excel(datos.RUTA_EXCEL)
    contenido = datos.to_excel_bytes(df)
    return Response(
        content=contenido,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=cuentas.xlsx"},
    )


# ---------------- API: resultados ----------------

@app.get("/api/resultados")
def api_resultados():
    return datos.resultados_payload()


@app.get("/api/resultados/exportar")
def api_resultados_exportar():
    df = datos.leer_excel(datos.RUTA_RESULTADOS)
    contenido = datos.to_excel_bytes(df)
    return Response(
        content=contenido,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=resultados.xlsx"},
    )


# ---------------- Estáticos (al final para no tapar /api) ----------------

app.mount("/", StaticFiles(directory=str(_STATIC), html=True), name="static")
