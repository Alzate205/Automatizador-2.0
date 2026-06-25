"""
main.py
=======

Orquestador de alto nivel del Automatizador (Betplay 2.0).

Versión FUSIONADA del main previo + el flujo nuevo, corrigiendo todas las
referencias rotas para dejarlo ejecutable:

  - Lee cuentas.xlsx validando columnas con auditor.leer_cuentas().
  - Por cada cuenta: resuelve el endpoint CDP, obtiene el código 2FA por correo
    (lector_correos), ejecuta process_user (procesador_web), guarda el resultado
    en el DataFrame y en el historial CSV, y espera un intervalo humano largo
    entre cuentas (anti-detección).
  - Al final escribe cuentas_actualizadas.xlsx.

Estrategia de navegador (configurable con USAR_GESTOR_PERFILES):
  - False (por defecto): se conecta a navegadores YA abiertos usando el puerto
    de la columna 'Puerto' de cada fila (patrón usado en todo el proyecto;
    funciona con el cuentas.xlsx actual sin pasos extra).
  - True: lanza un Chrome con perfil aislado por cuenta vía
    gestor_perfiles.lanzar_perfil_chrome (ver notas/avisos en el README mental).

Requisitos para ejecutar en vivo:
    pip install -r requirements.txt
    playwright install chromium
    # y un navegador escuchando por cada 'Puerto' (o USAR_GESTOR_PERFILES=True)
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import pandas as pd

from auditor import (
    ARCHIVO_HISTORIAL,
    PUERTO_POR_DEFECTO,
    inicializar_historial,
    leer_cuentas,
    log,
    registrar_historial,
)
from conexion_cdp import construir_endpoint
from lector_correos import esperar_y_extraer_codigo
from pausa import pausa_humana
from procesador_web import process_user

# ---------------------------------------------------------------------------
# CONFIGURACIÓN
# ---------------------------------------------------------------------------

EXCEL_INPUT = "cuentas.xlsx"
EXCEL_OUTPUT = "cuentas_actualizadas.xlsx"
BASE_URL = "https://www.betplay.com.co"

# Remitente (o display name) del correo que trae el código 2FA.
REMITENTE_2FA = "Betplay"

# Espera anti-detección entre cuentas (en minutos).
PAUSA_MIN_MINUTOS = 4
PAUSA_MAX_MINUTOS = 12

# Estrategia de navegador. False = conectar a navegadores ya abiertos por puerto;
# True = lanzar un Chrome con perfil aislado por cuenta (gestor_perfiles).
USAR_GESTOR_PERFILES = True  # Cambiar a False si ya tienes navegadores abiertos por puerto


# ---------------------------------------------------------------------------
# RESOLUCIÓN DEL NAVEGADOR (endpoint CDP)
# ---------------------------------------------------------------------------

def _puerto_de_fila(row, perfil_id: int) -> int:
    """Puerto CDP de la fila; si no es válido, rota sobre el puerto base."""
    try:
        return int(float(str(row.get("Puerto", PUERTO_POR_DEFECTO))))
    except (ValueError, TypeError):
        return PUERTO_POR_DEFECTO + (perfil_id % 8)


async def _resolver_endpoint(row, perfil_id: int) -> tuple[int, str]:
    """Devuelve (puerto, endpoint_cdp) según la estrategia configurada."""
    if USAR_GESTOR_PERFILES:
        # lanzar_perfil_chrome es BLOQUEANTE (subprocess.Popen + time.sleep),
        # así que lo ejecutamos en un hilo para no bloquear el event loop.
        from gestor_perfiles import lanzar_perfil_chrome

        proxy = str(row.get("Proxy", "") or "").strip() or None
        return await asyncio.to_thread(lanzar_perfil_chrome, perfil_id, proxy)

    puerto = _puerto_de_fila(row, perfil_id)
    return puerto, construir_endpoint(puerto=puerto)


# ---------------------------------------------------------------------------
# PROCESAMIENTO DE UNA FILA
# ---------------------------------------------------------------------------

async def procesar_fila(row, perfil_id: int) -> dict:
    """Resuelve navegador + 2FA y ejecuta process_user (login o registro)."""
    email = row.get("Correo") or row.get("Usuario")
    password = str(row.get("Password", ""))
    nombre = str(row.get("Nombre", "") or "")
    modo = "registro" if str(row.get("Modo", "")).strip().lower() == "registro" else "login"
    etiqueta = nombre or email or f"fila_{perfil_id}"

    log.info(f"[{etiqueta}] Preparando navegador... (modo: {modo})")
    puerto, endpoint = await _resolver_endpoint(row, perfil_id)
    log.info(f"[{etiqueta}] Endpoint CDP: {endpoint}")

    # 2FA: pasamos un PROVEEDOR de código (callback) en vez de pre-buscarlo.
    # process_user lo invocará solo cuando aparezca el campo 2FA (después de
    # enviar el login), que es cuando el correo con el código ya fue disparado.
    clave_correo = str(row.get("ClaveCorreo", "") or "").strip()
    code_provider = None
    if email and clave_correo:
        async def code_provider():
            return await esperar_y_extraer_codigo(str(email), clave_correo, REMITENTE_2FA)

    # Datos para el modo registro: limpiamos NaN -> "" para no romper el tecleo.
    datos = {k: ("" if pd.isna(v) else v) for k, v in row.to_dict().items()}

    resultado = await process_user(
        cdp_endpoint=endpoint,
        username=str(email),
        password=password,
        nombre=nombre,
        code_provider=code_provider,
        base_url=BASE_URL,
        datos=datos,
        modo=modo,
    )

    registrar_historial(
        usuario=str(email),
        estado=resultado.get("estado", "desconocido"),
        detalle=f"Modo: {modo} | Perfil/puerto: {puerto}",
        saldo=resultado.get("saldo", 0.0),
        verificada=resultado.get("verificada", "desconocido"),
        limitada=resultado.get("limitada", False),
    )
    return resultado


# ---------------------------------------------------------------------------
# BUCLE PRINCIPAL
# ---------------------------------------------------------------------------

async def main() -> None:
    log.exito("🚀 Iniciando Automatizador Betplay 2.0")
    inicializar_historial()

    try:
        df = leer_cuentas(EXCEL_INPUT)
        log.exito(f"Cargadas {len(df)} cuenta(s) de {EXCEL_INPUT}")
    except Exception as e:  # noqa: BLE001
        log.error(f"No se pudo leer {EXCEL_INPUT}: {e}")
        return

    resumen: dict[str, int] = {}
    for idx, row in df.iterrows():
        log.info("=" * 60)
        log.info(f"Cuenta {idx + 1}/{len(df)}  ·  {datetime.now():%H:%M:%S}")

        try:
            resultado = await procesar_fila(row, perfil_id=idx)
            exito = resultado.get("estado") != "error" and resultado.get("saldo", 0)
            registrar = log.exito if exito else log.warning
            registrar(
                f"Resultado → saldo={resultado.get('saldo')} "
                f"verificada={resultado.get('verificada')} "
                f"limitada={resultado.get('limitada')} estado={resultado.get('estado')}"
            )
        except Exception as e:  # noqa: BLE001  (aislamos el fallo para no tumbar el lote)
            log.error(f"Fallo procesando la cuenta {idx + 1}: {e}")
            resultado = {"saldo": 0.0, "verificada": "error", "limitada": False, "estado": "error"}

        # Conteo para el resumen final.
        estado = resultado.get("estado", "desconocido")
        resumen[estado] = resumen.get(estado, 0) + 1

        # Guardar resultados (columnas de SALIDA) en el DataFrame.
        df.at[idx, "Saldo"] = resultado.get("saldo", 0.0)
        df.at[idx, "Verificada"] = resultado.get("verificada", "desconocido")
        df.at[idx, "Limitada"] = resultado.get("limitada", False)
        df.at[idx, "Estado"] = resultado.get("estado", "desconocido")
        df.at[idx, "Ultima_Ejecucion"] = datetime.now()

        # Pausa humana larga entre cuentas (no después de la última).
        if idx < len(df) - 1:
            segundos = await pausa_humana(PAUSA_MIN_MINUTOS, PAUSA_MAX_MINUTOS)
            log.info(f"Pausa anti-detección: {segundos / 60:.1f} min antes de la siguiente")

    df.to_excel(EXCEL_OUTPUT, index=False)
    if resumen:
        log.info("Resumen: " + " · ".join(f"{k}={v}" for k, v in sorted(resumen.items())))
    log.exito(f"✅ Proceso completado. Resultados en {EXCEL_OUTPUT} y {ARCHIVO_HISTORIAL}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.warning("Ejecución interrumpida por el usuario.")
