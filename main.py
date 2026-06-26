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
import logging
import os
from datetime import datetime

import pandas as pd

import control
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

# Reanudación y guardado incremental.
ARCHIVO_PROGRESO = "progreso.txt"
GUARDADO_PARCIAL_CADA = 10   # cada cuantas cuentas se anuncia el guardado parcial

# Maximo de espera (segundos) por la senal "Continuar" del dashboard en el CAPTCHA.
TIMEOUT_CAPTCHA_SEG = 600


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
# REANUDACIÓN (progreso entre ejecuciones)
# ---------------------------------------------------------------------------

def _leer_progreso(ruta: str = ARCHIVO_PROGRESO) -> int:
    """Índice de la próxima cuenta a procesar (0 si no hay progreso previo)."""
    try:
        with open(ruta, encoding="utf-8") as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return 0


def _guardar_progreso(indice: int, ruta: str = ARCHIVO_PROGRESO) -> None:
    """Persiste el índice de la próxima cuenta a procesar."""
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(str(indice))


# ---------------------------------------------------------------------------
# LOG A ARCHIVO + ESPERA DEL CAPTCHA (control desde el dashboard)
# ---------------------------------------------------------------------------

def _configurar_log_archivo() -> None:
    """Anade un handler que vuelca todos los logs a control.LOG_BOT (para el dashboard)."""
    raiz = logging.getLogger()
    if any(getattr(h, "_es_bot_log", False) for h in raiz.handlers):
        return
    fh = logging.FileHandler(control.LOG_BOT, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    fh._es_bot_log = True  # type: ignore[attr-defined]
    raiz.addHandler(fh)
    raiz.setLevel(logging.INFO)
    logging.getLogger("procesador_web").setLevel(logging.INFO)


async def _captcha_waiter() -> None:
    """
    Pausa el bot en el CAPTCHA hasta que el dashboard cree la senal "Continuar"
    (o se alcance TIMEOUT_CAPTCHA_SEG, o se pida detener).
    """
    control.limpiar_continuar()
    control.escribir_estado(
        estado="esperando_captcha", fase="captcha",
        mensaje="Resuelve el CAPTCHA en el navegador y pulsa Continuar",
    )
    log.warning("Esperando 'Continuar' desde el dashboard para el CAPTCHA...")
    esperado = 0
    while not control.hay_senal_continuar():
        if control.hay_senal_detener():
            break
        await asyncio.sleep(2)
        esperado += 2
        if esperado >= TIMEOUT_CAPTCHA_SEG:
            log.warning("Timeout esperando 'Continuar'; sigo de todos modos.")
            break
    control.limpiar_continuar()
    control.escribir_estado(estado="corriendo", fase="registro", mensaje="Continuando registro")


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
        captcha_waiter=_captcha_waiter,
    )

    registrar_historial(
        usuario=str(email),
        estado=resultado.get("estado", "desconocido"),
        detalle=f"Modo: {modo} | Bono: {resultado.get('bono', 'n/a')} | Puerto: {puerto}",
        saldo=resultado.get("saldo", 0.0),
        verificada=resultado.get("verificada", "desconocido"),
        limitada=resultado.get("limitada", False),
    )
    return resultado


# ---------------------------------------------------------------------------
# BUCLE PRINCIPAL
# ---------------------------------------------------------------------------

async def main() -> None:
    _configurar_log_archivo()

    # Config de la corrida (la escribe el dashboard); por defecto si no existe.
    cfg = control.leer_config()
    global USAR_GESTOR_PERFILES
    USAR_GESTOR_PERFILES = bool(cfg.get("usar_gestor", USAR_GESTOR_PERFILES))
    pausa_min = float(cfg.get("pausa_min", PAUSA_MIN_MINUTOS))
    pausa_max = float(cfg.get("pausa_max", PAUSA_MAX_MINUTOS))
    filtro_modo = str(cfg.get("filtro_modo", "todo")).strip().lower()

    log.exito("Iniciando Automatizador Betplay 2.0")
    inicializar_historial()
    control.reset_control()
    control.escribir_estado(
        estado="corriendo", indice=0, total=0, cuenta="", fase="inicio",
        mensaje="Cargando cuentas...", resumen={},
    )

    # Reanudacion: si hay progreso previo y existe el Excel parcial, partimos de
    # el para conservar los resultados de las cuentas ya procesadas.
    progreso = _leer_progreso()
    fuente = EXCEL_OUTPUT if (progreso > 0 and os.path.exists(EXCEL_OUTPUT)) else EXCEL_INPUT
    try:
        df = leer_cuentas(fuente)
        log.exito(f"Cargadas {len(df)} cuenta(s) de {fuente}")
    except Exception as e:  # noqa: BLE001
        log.error(f"No se pudo leer {fuente}: {e}")
        control.escribir_estado(estado="error", mensaje=f"No se pudo leer {fuente}: {e}")
        return

    control.escribir_estado(total=len(df))
    if progreso > 0:
        log.info(f"Reanudando desde la cuenta #{progreso + 1} (progreso previo).")

    resumen: dict[str, int] = {}
    try:
        for idx, row in df.iterrows():
            # Saltar cuentas ya procesadas en una ejecucion anterior.
            if idx < progreso:
                continue

            modo_fila = "registro" if str(row.get("Modo", "")).strip().lower() == "registro" else "login"
            # Filtro de modo desde el dashboard (todo|login|registro).
            if filtro_modo in ("login", "registro") and modo_fila != filtro_modo:
                continue

            # Parada solicitada desde el dashboard (entre cuentas).
            if control.hay_senal_detener():
                log.warning("Senal de detencion recibida; parando entre cuentas.")
                control.escribir_estado(estado="detenido", mensaje="Detenido por el usuario")
                break

            email = row.get("Correo") or row.get("Usuario")
            control.escribir_estado(
                estado="corriendo", indice=int(idx), total=len(df),
                cuenta=str(email), fase=modo_fila, mensaje="Procesando cuenta",
            )
            log.info("=" * 60)
            log.info(f"Cuenta {idx + 1}/{len(df)} - {datetime.now():%H:%M:%S} (modo: {modo_fila})")

            try:
                resultado = await procesar_fila(row, perfil_id=idx)
                ok = resultado.get("estado") != "error" and resultado.get("saldo", 0)
                registrar = log.exito if ok else log.warning
                registrar(
                    f"Resultado -> saldo={resultado.get('saldo')} "
                    f"verificada={resultado.get('verificada')} "
                    f"limitada={resultado.get('limitada')} bono={resultado.get('bono')} "
                    f"estado={resultado.get('estado')}"
                )
            except Exception as e:  # noqa: BLE001  (aislamos el fallo por cuenta)
                log.error(f"Fallo procesando la cuenta {idx + 1}: {e}")
                resultado = {
                    "saldo": 0.0, "verificada": "error", "limitada": False,
                    "bono": "Error bonos", "estado": "error",
                }

            estado_cuenta = resultado.get("estado", "desconocido")
            resumen[estado_cuenta] = resumen.get(estado_cuenta, 0) + 1

            df.at[idx, "Saldo"] = resultado.get("saldo", 0.0)
            df.at[idx, "Verificada"] = resultado.get("verificada", "desconocido")
            df.at[idx, "Limitada"] = resultado.get("limitada", False)
            df.at[idx, "Bono"] = resultado.get("bono", "")
            df.at[idx, "Estado"] = estado_cuenta
            df.at[idx, "Ultima_Ejecucion"] = datetime.now()

            # Guardado incremental (resume sin perdida) + estado para el dashboard.
            df.to_excel(EXCEL_OUTPUT, index=False)
            _guardar_progreso(idx + 1)
            control.escribir_estado(resumen=resumen)
            if (idx + 1) % GUARDADO_PARCIAL_CADA == 0:
                log.info(f"Guardado parcial: {idx + 1}/{len(df)} cuentas -> {EXCEL_OUTPUT}")

            # Pausa humana larga entre cuentas (no despues de la ultima).
            if idx < len(df) - 1 and not control.hay_senal_detener():
                control.escribir_estado(fase="pausa", mensaje="Pausa anti-deteccion")
                segundos = await pausa_humana(pausa_min, pausa_max)
                log.info(f"Pausa anti-deteccion: {segundos / 60:.1f} min antes de la siguiente")
    except Exception as e:  # noqa: BLE001
        log.error(f"Error inesperado en el bucle principal: {e}")
        control.escribir_estado(estado="error", mensaje=str(e))
        df.to_excel(EXCEL_OUTPUT, index=False)
        return

    df.to_excel(EXCEL_OUTPUT, index=False)
    detenido = control.hay_senal_detener()
    # Si terminamos el lote completo (no por detener), limpiamos el progreso.
    if not detenido and os.path.exists(ARCHIVO_PROGRESO):
        os.remove(ARCHIVO_PROGRESO)
    if resumen:
        log.info("Resumen: " + " - ".join(f"{k}={v}" for k, v in sorted(resumen.items())))
    estado_final = "detenido" if detenido else "finalizado"
    control.escribir_estado(estado=estado_final, fase="fin", mensaje="Proceso terminado", resumen=resumen)
    log.exito(f"Proceso terminado ({estado_final}). Resultados en {EXCEL_OUTPUT} y {ARCHIVO_HISTORIAL}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.warning("Ejecución interrumpida por el usuario.")
