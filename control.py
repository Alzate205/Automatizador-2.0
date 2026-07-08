"""
control.py
==========

Contrato de comunicacion por archivos entre el dashboard (Streamlit) y el bot
(main.py), que corren como procesos separados.

Archivos:
    estado_bot.json   -> el bot publica su estado; el dashboard lo lee.
    config_run.json   -> el dashboard publica la config de la corrida; el bot la lee.
    senal_detener.flag    -> el dashboard pide al bot que pare (entre cuentas).
    senal_continuar.flag  -> el dashboard avisa que ya resolvio el CAPTCHA.
    bot.log           -> log del bot (lo escribe main.py; el dashboard lo muestra).

Todas las escrituras de JSON son atomicas (escribe .tmp y reemplaza).
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict

ESTADO_JSON = "estado_bot.json"
CONFIG_JSON = "config_run.json"
SENAL_DETENER = "senal_detener.flag"
SENAL_CONTINUAR = "senal_continuar.flag"
SENAL_CANCELAR = "senal_cancelar.flag"
CODIGO_2FA = "codigo_2fa.txt"
LOG_BOT = "bot.log"

ESTADO_POR_DEFECTO: Dict[str, Any] = {
    "estado": "inactivo",   # inactivo|corriendo|esperando_captcha|esperando_codigo|detenido|finalizado|error
    "indice": 0,
    "total": 0,
    "cuenta": "",
    "fase": "",
    "mensaje": "",
    "resumen": {},
    "actualizado": "",
}


# ---------------------------------------------------------------------------
# JSON atomico
# ---------------------------------------------------------------------------

def _escribir_json_atomico(ruta: str, datos: dict) -> None:
    tmp = f"{ruta}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ruta)


# ---------------------------------------------------------------------------
# Estado del bot
# ---------------------------------------------------------------------------

def leer_estado() -> Dict[str, Any]:
    """Lee estado_bot.json combinado con los valores por defecto."""
    try:
        with open(ESTADO_JSON, encoding="utf-8") as f:
            base = dict(ESTADO_POR_DEFECTO)
            base.update(json.load(f))
            return base
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(ESTADO_POR_DEFECTO)


def escribir_estado(**campos: Any) -> Dict[str, Any]:
    """Combina los campos dados con el estado actual y lo persiste."""
    estado = leer_estado()
    estado.update(campos)
    estado["actualizado"] = datetime.now().isoformat(timespec="seconds")
    _escribir_json_atomico(ESTADO_JSON, estado)
    return estado


# ---------------------------------------------------------------------------
# Config de la corrida
# ---------------------------------------------------------------------------

def leer_config() -> Dict[str, Any]:
    """Lee config_run.json; {} si no existe o esta corrupto."""
    try:
        with open(CONFIG_JSON, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def escribir_config(config: Dict[str, Any]) -> None:
    _escribir_json_atomico(CONFIG_JSON, config)


# ---------------------------------------------------------------------------
# Senales (archivos-bandera)
# ---------------------------------------------------------------------------

def _crear(ruta: str) -> None:
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(datetime.now().isoformat())


def _existe(ruta: str) -> bool:
    return os.path.exists(ruta)


def _borrar(ruta: str) -> None:
    try:
        os.remove(ruta)
    except FileNotFoundError:
        pass


def pedir_detener() -> None:
    _crear(SENAL_DETENER)


def hay_senal_detener() -> bool:
    return _existe(SENAL_DETENER)


def limpiar_detener() -> None:
    _borrar(SENAL_DETENER)


def pedir_continuar() -> None:
    _crear(SENAL_CONTINUAR)


def hay_senal_continuar() -> bool:
    return _existe(SENAL_CONTINUAR)


def limpiar_continuar() -> None:
    _borrar(SENAL_CONTINUAR)


def pedir_cancelar() -> None:
    """Cancela una espera de captcha/apuesta: el bot aborta la cuenta SIN enviar."""
    _crear(SENAL_CANCELAR)


def hay_senal_cancelar() -> bool:
    return _existe(SENAL_CANCELAR)


def limpiar_cancelar() -> None:
    _borrar(SENAL_CANCELAR)


# ---------------------------------------------------------------------------
# Canal del codigo 2FA manual (dashboard -> bot)
# ---------------------------------------------------------------------------
#
# codigo_2fa.txt: el panel escribe aqui el codigo que el usuario ingreso a mano
# (cuentas sin ClaveCorreo, con "codigo_manual" activado). Su existencia indica
# que hay un codigo pendiente; su contenido es el codigo. El bot lo lee y lo borra.

def guardar_codigo(codigo: str) -> None:
    with open(CODIGO_2FA, "w", encoding="utf-8") as f:
        f.write(str(codigo).strip())


def hay_codigo() -> bool:
    return _existe(CODIGO_2FA)


def leer_codigo() -> str | None:
    """Devuelve el codigo pendiente (recortado) o None si no hay."""
    try:
        with open(CODIGO_2FA, encoding="utf-8") as f:
            valor = f.read().strip()
    except FileNotFoundError:
        return None
    return valor or None


def limpiar_codigo() -> None:
    _borrar(CODIGO_2FA)


def reset_control() -> None:
    """Limpia las senales antes de una nueva corrida."""
    limpiar_detener()
    limpiar_continuar()
    limpiar_cancelar()
    limpiar_codigo()
