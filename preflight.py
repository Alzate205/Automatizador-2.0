"""
preflight.py
============

Chequeos previos a una corrida: validan que la lista de cuentas tenga los datos
necesarios (según el modo) y que el entorno esté listo, ANTES de gastar intentos.

- `validar_datos(df, filtro_modo)` es pura (solo pandas): segura tanto en el
  dashboard (síncrono) como dentro del bucle asíncrono de main.py.
- `chromium_disponible()` usa Playwright síncrono: llamar SOLO desde contexto
  síncrono (dashboard), nunca dentro de un loop asyncio.
"""

from __future__ import annotations

import os

import pandas as pd

# Campos obligatorios para poder intentar un registro en Betplay.
REQUERIDOS_REGISTRO = ("Cedula", "PrimerNombre", "Correo", "Password")
# Identificadores válidos para un login (basta uno).
IDENTIFICADORES_LOGIN = ("Cedula", "Correo", "Usuario")


def _vacio(valor) -> bool:
    """True si el valor está vacío o es un marcador nulo (nan/none)."""
    s = "" if valor is None else str(valor).strip()
    return s == "" or s.lower() in ("nan", "none")


def _modo_de_fila(row) -> str:
    return "registro" if str(row.get("Modo", "")).strip().lower() == "registro" else "login"


def _fila_procesable(modo: str, row) -> bool:
    """True si la fila tiene lo mínimo para intentarse según su modo."""
    if modo == "registro":
        return all(not _vacio(row.get(c)) for c in REQUERIDOS_REGISTRO)
    # login: un identificador + password
    tiene_id = any(not _vacio(row.get(c)) for c in IDENTIFICADORES_LOGIN)
    return tiene_id and not _vacio(row.get("Password"))


def validar_datos(df: pd.DataFrame, filtro_modo: str = "todo") -> tuple[list[str], list[str]]:
    """
    Valida la lista de cuentas para la corrida.

    Devuelve (errores, avisos):
      - errores: bloqueantes (nada que procesar) -> conviene NO iniciar.
      - avisos: no bloqueantes (filas que se omitirán, 2FA sin clave, etc.).
    """
    errores: list[str] = []
    avisos: list[str] = []

    if df is None or df.empty:
        errores.append("La lista de cuentas está vacía.")
        return errores, avisos

    filtro = str(filtro_modo).strip().lower()
    en_alcance = []
    for _, row in df.iterrows():
        modo = _modo_de_fila(row)
        if filtro in ("login", "registro") and modo != filtro:
            continue
        en_alcance.append((modo, row))

    if not en_alcance:
        errores.append(f"Ninguna cuenta coincide con el filtro de modo '{filtro}'.")
        return errores, avisos

    procesables = 0
    reg_incompletos = 0
    login_incompletos = 0
    sin_2fa = 0
    for modo, row in en_alcance:
        if _fila_procesable(modo, row):
            procesables += 1
        elif modo == "registro":
            reg_incompletos += 1
        else:
            login_incompletos += 1
        if _vacio(row.get("ClaveCorreo")):
            sin_2fa += 1

    if procesables == 0:
        errores.append(
            "Ninguna cuenta en alcance tiene los datos mínimos para procesarse "
            f"(registro requiere {', '.join(REQUERIDOS_REGISTRO)}; login requiere "
            "identificador + Password)."
        )
    if reg_incompletos:
        avisos.append(
            f"{reg_incompletos} cuenta(s) de registro sin datos obligatorios "
            f"({', '.join(REQUERIDOS_REGISTRO)}); se omitirán."
        )
    if login_incompletos:
        avisos.append(
            f"{login_incompletos} cuenta(s) de login sin identificador "
            "(Cédula/Correo/Usuario) o sin Password; se omitirán."
        )
    if sin_2fa:
        avisos.append(
            f"{sin_2fa} cuenta(s) sin 'ClaveCorreo': si Betplay pide código 2FA, no "
            "se podrá leer automáticamente del correo."
        )
    return errores, avisos


def chromium_disponible() -> bool:
    """
    True si el navegador Chromium de Playwright está instalado.

    Usa Playwright SÍNCRONO: llamar solo desde contexto síncrono (dashboard),
    nunca dentro de un loop asyncio. Ante cualquier problema devuelve False.
    """
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            ruta = p.chromium.executable_path
            return bool(ruta) and os.path.exists(ruta)
    except Exception:  # noqa: BLE001
        return False
