"""
auditor.py
==========

Orquestador principal del sistema automatizado de auditoría de cuentas.

Unifica de forma lógica y secuencial todos los módulos utilitarios del
proyecto:

    - pandas / asyncio                  -> lectura del Excel y flujo asíncrono
    - alertas_consola.py                -> progreso coloreado en terminal
    - playwright (connect_over_cdp)     -> se adjunta a un navegador externo
                                           ya abierto (mismo patrón que escuchar.py
                                           / conexion_cdp.py)
    - lector_correos.py                 -> extracción del código 2FA por correo
    - extraccion.py                     -> limpieza regex del Saldo (-> float)
    - restricciones.py                  -> detección de límites en las alertas
    - pausa.py                          -> esperas con jitter (anti-rigidez)

Flujo:
    main() lee cuentas.xlsx y, por cada fila, llama a procesar_cuenta(), que:
      1. Se adjunta al navegador externo usando el puerto de la fila (CDP).
      2. Inicia sesión con las credenciales de la fila.
      3. Resuelve el 2FA por correo si aparece el campo de token.
      4. Extrae Saldo (regex -> float) y verifica la insignia de cuenta.
      5. Escribe un monto de prueba alto y evalúa si surge una restricción.
      6. Devuelve {Saldo, Verificada, Limitada}.
    El resultado de cada cuenta se pinta en consola (verde/rojo) y se escribe
    de inmediato en historial_auditoria.csv.

IMPORTANTE: las URLs y los selectores son GENÉRICOS/abstractos a propósito.
Reemplázalos por los reales de tu infraestructura antes de ejecutar en vivo.

Requisitos:
    pip install -r requirements.txt
    playwright install chromium

Uso (requiere navegadores ya abiertos con --remote-debugging-port=<Puerto>):
    python auditor.py
"""

from __future__ import annotations

import asyncio
import csv
import logging
import os
import sys
from datetime import datetime

import pandas as pd
from colorama import Fore, Style, init as colorama_init

# --- Utilidades del proyecto (no dependen de auditor -> import directo seguro) ---
from alertas_consola import exito, advertencia, error
from extraccion import extraer_saldo
from restricciones import contiene_restriccion
from pausa import pausa_con_jitter

# Nota: lector_correos.py hace `from auditor import log`, así que se importa de
# forma DIFERIDA dentro de _resolver_2fa() para evitar un import circular.
# Playwright también se importa diferido (solo se necesita al usar el navegador).


# ---------------------------------------------------------------------------
# CONFIGURACIÓN (placeholders editables)
# ---------------------------------------------------------------------------

# URL ficticia/genérica del sitio objetivo. Reemplázala por la real.
URL_OBJETIVO = "https://ejemplo-pagina-x.com"

# Conexión CDP al navegador externo ya abierto.
HOST_CDP = "127.0.0.1"
PUERTO_POR_DEFECTO = 9222          # se usa si la fila no trae columna "Puerto"

# Remitente genérico del correo con el código 2FA.
REMITENTE_2FA = "noreply@ejemplo.com"

# Monto de prueba "alto" para forzar (si existe) la alerta de límite.
MONTO_PRUEBA = 999999.99

# Archivos de entrada (Excel) y de salida (historial CSV).
ARCHIVO_EXCEL = "cuentas.xlsx"
ARCHIVO_HISTORIAL = "historial_auditoria.csv"

# Esquema de ENTRADA del Excel de cuentas: solo lo que el orquestador necesita
# leer (credenciales, datos de 2FA y puerto CDP). Los resultados de la auditoría
# (Saldo, Verificada, Limitada) son SALIDA y se escriben en historial_auditoria.csv,
# no se leen de aquí.
COLUMNAS_ESPERADAS = [
    "Usuario",      # identificador de login (puede ser usuario o correo)
    "Password",     # contraseña de la cuenta
    "Nombre",       # nombre descriptivo (metadato para identificar la cuenta)
    "Correo",       # buzón donde llega el código 2FA
    "ClaveCorreo",  # app password del buzón de 2FA
    "Puerto",       # puerto de depuración remota (CDP) del navegador externo
]

# Tiempos de espera (ms).
TIMEOUT_MS = 15000             # operaciones normales (fill/lectura)
TIMEOUT_DETECCION_MS = 3000    # detección de elementos opcionales (2FA, alerta)

# ---------------------------------------------------------------------------
# SELECTORES GENÉRICOS  (PERSONALIZAR según el sitio real)
# ---------------------------------------------------------------------------
SELECTOR_USUARIO = "#usuario"
SELECTOR_PASSWORD = "#password"
SELECTOR_BOTON_LOGIN = "#boton-login"
SELECTOR_CAMPO_TOKEN = "#token-2fa"
SELECTOR_BOTON_TOKEN = "#verificar-token"
SELECTOR_SALDO = "#saldo"
SELECTOR_INSIGNIA_VERIFICADA = "#insignia-verificada"
SELECTOR_CAMPO_MONTO = "#monto"
SELECTOR_BOTON_ENVIAR_MONTO = "#enviar-monto"
SELECTOR_ALERTA = "#alerta"


# ---------------------------------------------------------------------------
# SISTEMA DE LOGS VISUALES (logging + colorama)
# ---------------------------------------------------------------------------

NIVEL_EXITO = 25
logging.addLevelName(NIVEL_EXITO, "EXITO")


def _log_exito(self: logging.Logger, mensaje: str, *args, **kwargs) -> None:
    """Método extra en Logger para registrar un evento de éxito."""
    if self.isEnabledFor(NIVEL_EXITO):
        self._log(NIVEL_EXITO, mensaje, args, **kwargs)


logging.Logger.exito = _log_exito  # type: ignore[attr-defined]


class FormateadorColor(logging.Formatter):
    """Formateador que pinta cada línea según su nivel de severidad."""

    COLORES = {
        logging.DEBUG: Fore.CYAN,
        logging.INFO: Fore.YELLOW,
        NIVEL_EXITO: Fore.GREEN,
        logging.WARNING: Fore.MAGENTA,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Fore.RED + Style.BRIGHT,
    }

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORES.get(record.levelno, "")
        hora = datetime.now().strftime("%H:%M:%S")
        etiqueta = record.levelname
        mensaje = record.getMessage()
        return f"{color}[{hora}] [{etiqueta}] {mensaje}{Style.RESET_ALL}"


def configurar_logger() -> logging.Logger:
    """Inicializa colorama y devuelve un logger con salida coloreada."""
    colorama_init(autoreset=True)

    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    logger = logging.getLogger("auditor")
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(FormateadorColor())
        logger.addHandler(handler)
    return logger


log = configurar_logger()


# ---------------------------------------------------------------------------
# HISTORIAL DE EJECUCIÓN (CSV)
# ---------------------------------------------------------------------------

# Las 4 primeras columnas se conservan por compatibilidad con probar_local.py;
# las 3 últimas guardan el resultado detallado de la auditoría.
ENCABEZADO_HISTORIAL = [
    "Hora", "Usuario", "Estado", "Detalle", "Saldo", "Verificada", "Limitada",
]


def inicializar_historial(ruta: str = ARCHIVO_HISTORIAL) -> None:
    """Crea el CSV de historial con su encabezado si aún no existe."""
    if not os.path.exists(ruta):
        with open(ruta, mode="w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(ENCABEZADO_HISTORIAL)


def registrar_historial(
    usuario: str,
    estado: str,
    detalle: str = "",
    saldo: object = "",
    verificada: object = "",
    limitada: object = "",
    ruta: str = ARCHIVO_HISTORIAL,
) -> None:
    """
    Agrega una fila al historial de auditoría.

    Firma compatible hacia atrás: (usuario, estado, detalle) siguen siendo los
    tres primeros argumentos posicionales. Los campos saldo/verificada/limitada
    son opcionales y registran el resultado detallado de cada cuenta.
    """
    hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(ruta, mode="a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(
            [hora, usuario, estado, detalle, saldo, verificada, limitada]
        )


# ---------------------------------------------------------------------------
# LECTURA DE DATOS
# ---------------------------------------------------------------------------

def leer_cuentas(ruta: str = ARCHIVO_EXCEL) -> pd.DataFrame:
    """
    Lee el Excel de cuentas de forma TOLERANTE (apto para login y registro masivo).

    - Normaliza los nombres de columna (quita espacios).
    - Exige al menos una columna de identificación ('Correo' o 'Usuario').
    - Garantiza que existan las columnas esperadas + 'Modo'/'Proxy' (las ausentes
      se crean vacías; 'Modo' por defecto = 'login').
    - Limpia NaN -> "" y normaliza 'Modo' a minúsculas.

    Lanza FileNotFoundError si el archivo no existe, o ValueError si no hay
    ninguna columna de identificación.
    """
    if not os.path.exists(ruta):
        raise FileNotFoundError(f"No se encontró el archivo de cuentas: {ruta}")

    df = pd.read_excel(ruta)
    df.columns = [str(col).strip() for col in df.columns]

    if "Correo" not in df.columns and "Usuario" not in df.columns:
        raise ValueError(
            "El Excel no tiene columnas de identificación: se requiere 'Correo' o 'Usuario'."
        )

    # Garantizar columnas útiles para login/registro (ausentes -> vacías).
    for col in (*COLUMNAS_ESPERADAS, "Modo", "Proxy"):
        if col not in df.columns:
            df[col] = "login" if col == "Modo" else ""

    df = df.fillna("")
    df["Modo"] = (
        df["Modo"].astype(str).str.strip().str.lower().replace("", "login")
    )

    n_reg = int((df["Modo"] == "registro").sum())
    n_log = int((df["Modo"] == "login").sum())
    log.exito(f"Cargadas {len(df)} cuenta(s). Registros: {n_reg} | Logins: {n_log}")
    return df


def generar_reporte_resumen(df: pd.DataFrame) -> dict:
    """Estadísticas rápidas del DataFrame de cuentas (para el dashboard)."""
    modo = df.get("Modo", pd.Series(dtype=str)).astype(str)
    proxy = df.get("Proxy", pd.Series(dtype=str)).astype(str).str.strip()
    saldo = pd.to_numeric(df.get("Saldo", pd.Series(dtype=float)), errors="coerce")
    return {
        "total": len(df),
        "registros": int((modo == "registro").sum()),
        "logins": int((modo == "login").sum()),
        "con_proxy": int((proxy != "").sum()),
        "saldo_promedio": float(saldo.mean()) if saldo.notna().any() else 0.0,
    }


def generar_reporte_final(ruta: str = ARCHIVO_HISTORIAL) -> dict:
    """
    Resumen agregado de la corrida, leído del historial CSV.

    Robusto ante los formatos reales del historial:
      - 'Estado' usa etiquetas como 'exitosa'/'error'/'fallo_registro'/'login_fallido'.
      - El modo (registro/login) vive en 'Detalle' ("Modo: registro"), no en 'Estado'.
      - 'Limitada' se guarda como texto/bool; 'Saldo' puede traer valores no numéricos.

    Devuelve un dict listo para imprimir o mostrar en el dashboard.
    """
    if not os.path.exists(ruta):
        return {"mensaje": "No hay historial aún."}
    try:
        df = pd.read_csv(ruta)
    except Exception:  # noqa: BLE001
        return {"mensaje": "No se pudo leer el historial."}
    if df.empty:
        return {"mensaje": "Historial vacío."}

    estado = df.get("Estado", pd.Series(dtype=str)).astype(str).str.lower()
    detalle = df.get("Detalle", pd.Series(dtype=str)).astype(str).str.lower()
    verificada = df.get("Verificada", pd.Series(dtype=str)).astype(str).str.lower()
    limitada = df.get("Limitada", pd.Series(dtype=str)).astype(str).str.lower()
    saldo = pd.to_numeric(df.get("Saldo", pd.Series(dtype=float)), errors="coerce").fillna(0)

    es_registro = detalle.str.contains("modo: registro", na=False)
    es_exitosa = estado.eq("exitosa")

    return {
        "Total procesadas": len(df),
        "Exitosas": int(es_exitosa.sum()),
        "Fallidas": int(estado.str.contains("error|fallo|fallid|rechaz", na=False).sum()),
        "Registros exitosos": int((es_registro & es_exitosa).sum()),
        "Verificadas": int(verificada.isin(["si", "sí", "yes", "true"]).sum()),
        "Limitadas": int(limitada.isin(["true", "si", "sí", "1", "limitada"]).sum()),
        "Saldo total": round(float(saldo.sum()), 2),
    }


def imprimir_reporte_final(ruta: str = ARCHIVO_HISTORIAL) -> dict:
    """Calcula generar_reporte_final y lo pinta en el log con formato legible."""
    reporte = generar_reporte_final(ruta)
    log.info("=" * 50)
    log.info("REPORTE FINAL DE LA CORRIDA")
    log.info("=" * 50)
    for clave, valor in reporte.items():
        log.info(f"  {clave}: {valor}")
    log.info("=" * 50)
    return reporte


def _puerto_de_fila(fila: pd.Series) -> int:
    """Obtiene el puerto CDP de la fila; usa el valor por defecto si no aplica."""
    valor = fila.get("Puerto", PUERTO_POR_DEFECTO)
    try:
        return int(float(str(valor)))
    except (ValueError, TypeError):
        return PUERTO_POR_DEFECTO


# ---------------------------------------------------------------------------
# PASOS DE LA AUDITORÍA (coroutines auxiliares sobre la página)
# ---------------------------------------------------------------------------

async def _esta_visible(pagina, selector: str, timeout_ms: int = TIMEOUT_DETECCION_MS) -> bool:
    """True si el selector aparece visible dentro del timeout; False si no."""
    try:
        await pagina.wait_for_selector(selector, state="visible", timeout=timeout_ms)
        return True
    except Exception:  # noqa: BLE001  (timeout / elemento ausente -> no visible)
        return False


async def _iniciar_sesion(pagina, usuario: str, password: str) -> None:
    """Paso 2: rellena credenciales y envía el formulario de login."""
    await pagina.fill(SELECTOR_USUARIO, usuario, timeout=TIMEOUT_MS)
    await pagina.fill(SELECTOR_PASSWORD, password, timeout=TIMEOUT_MS)
    await pagina.click(SELECTOR_BOTON_LOGIN, timeout=TIMEOUT_MS)
    await pausa_con_jitter(1.0)  # pequeña pausa humana tras enviar el login


async def _resolver_2fa(pagina, fila: pd.Series, usuario: str) -> None:
    """
    Paso 3: si aparece el campo de token, obtiene el código por correo
    (esperar_y_extraer_codigo) y lo ingresa. Si no hay 2FA, no hace nada.
    """
    if not await _esta_visible(pagina, SELECTOR_CAMPO_TOKEN):
        return  # esta cuenta no pidió 2FA

    correo = str(fila.get("Correo", "")).strip()
    clave_correo = str(fila.get("ClaveCorreo", "")).strip()
    if not correo or not clave_correo:
        log.warning(
            f"{usuario}: se pidió 2FA pero faltan credenciales de correo "
            "(columnas 'Correo' y/o 'ClaveCorreo'). Se omite el paso."
        )
        return

    log.info(f"{usuario}: 2FA detectado, buscando el código por correo...")
    from lector_correos import esperar_y_extraer_codigo  # import diferido (circular)

    codigo = await esperar_y_extraer_codigo(correo, clave_correo, REMITENTE_2FA)
    if not codigo:
        log.warning(f"{usuario}: no se obtuvo el código 2FA a tiempo.")
        return

    await pagina.fill(SELECTOR_CAMPO_TOKEN, codigo, timeout=TIMEOUT_MS)
    await pagina.click(SELECTOR_BOTON_TOKEN, timeout=TIMEOUT_MS)
    await pausa_con_jitter(1.0)


async def _leer_saldo(pagina) -> float:
    """Paso 4a: lee el texto del saldo y lo limpia con regex -> float."""
    try:
        texto = await pagina.locator(SELECTOR_SALDO).inner_text(timeout=TIMEOUT_MS)
    except Exception:  # noqa: BLE001
        log.warning("No se pudo leer el saldo en pantalla; se asume 0.0")
        return 0.0
    return extraer_saldo(texto)


async def _esta_verificada(pagina) -> bool:
    """Paso 4b: True si la insignia de verificación está presente/visible."""
    return await _esta_visible(pagina, SELECTOR_INSIGNIA_VERIFICADA)


async def _evaluar_limite(pagina) -> bool:
    """
    Paso 5: escribe el monto de prueba alto, lo envía y evalúa de forma
    booleana si la alerta resultante contiene palabras de restricción.
    """
    try:
        await pagina.fill(SELECTOR_CAMPO_MONTO, str(MONTO_PRUEBA), timeout=TIMEOUT_MS)
        await pagina.click(SELECTOR_BOTON_ENVIAR_MONTO, timeout=TIMEOUT_MS)
        await pausa_con_jitter(1.0)
        texto_alerta = await pagina.locator(SELECTOR_ALERTA).inner_text(
            timeout=TIMEOUT_DETECCION_MS
        )
    except Exception:  # noqa: BLE001  (sin campo de monto o sin alerta -> sin límite)
        return False
    return contiene_restriccion(texto_alerta)


# ---------------------------------------------------------------------------
# PROCESAMIENTO DE CADA CUENTA
# ---------------------------------------------------------------------------

async def procesar_cuenta(fila: pd.Series, indice: int) -> dict:
    """
    Audita una sola cuenta adjuntándose a su navegador externo vía CDP.

    Devuelve un diccionario con: {"Saldo": float, "Verificada": bool,
    "Limitada": bool}. Propaga la excepción si la conexión o el login fallan,
    para que main() lo marque como cuenta fallida.
    """
    usuario = str(fila.get("Usuario", f"fila_{indice}"))
    password = str(fila.get("Password", ""))
    puerto = _puerto_de_fila(fila)
    endpoint = f"http://{HOST_CDP}:{puerto}"

    resultado = {"Saldo": 0.0, "Verificada": False, "Limitada": False}

    from playwright.async_api import async_playwright  # import diferido

    async with async_playwright() as p:
        # Paso 1: adjuntarse al navegador externo ya abierto (no lanza uno nuevo).
        log.info(f"{usuario}: adjuntando al navegador externo en {endpoint} ...")
        navegador = await p.chromium.connect_over_cdp(endpoint)
        try:
            context = (
                navegador.contexts[0]
                if navegador.contexts
                else await navegador.new_context()
            )
            pagina = context.pages[0] if context.pages else await context.new_page()

            # Posicionarse en la página objetivo (genérica) antes del login.
            await pagina.goto(URL_OBJETIVO, wait_until="domcontentloaded")

            # Paso 2: inicio de sesión.
            await _iniciar_sesion(pagina, usuario, password)

            # Paso 3: 2FA si aplica.
            await _resolver_2fa(pagina, fila, usuario)

            # Paso 4: extracción de datos.
            resultado["Saldo"] = await _leer_saldo(pagina)
            resultado["Verificada"] = await _esta_verificada(pagina)

            # Paso 5: validación de límites.
            resultado["Limitada"] = await _evaluar_limite(pagina)

        finally:
            # close() solo nos desconecta del CDP; el navegador remoto sigue vivo.
            await navegador.close()

    return resultado


# ---------------------------------------------------------------------------
# BUCLE ORQUESTADOR
# ---------------------------------------------------------------------------

async def main() -> None:
    """Lee el Excel y audita cada cuenta, pintando el progreso y guardando el CSV."""
    log.info("=== Iniciando auditor automatizado ===")
    inicializar_historial()

    # 1) Leer el Excel de cuentas.
    try:
        cuentas = leer_cuentas()
        exito(f"Excel leído: {len(cuentas)} cuenta(s) encontradas")
    except Exception as exc:  # noqa: BLE001
        error(f"No se pudo leer {ARCHIVO_EXCEL}: {exc}")
        return

    if len(cuentas) == 0:
        advertencia("El Excel no contiene cuentas para procesar.")
        return

    # 2) Recorrer cada fila, auditarla y registrar el resultado de inmediato.
    for indice, fila in cuentas.iterrows():
        usuario = str(fila.get("Usuario", f"fila_{indice}"))
        log.info(f"--- Cuenta #{indice + 1}: {usuario} ---")
        try:
            resultado = await procesar_cuenta(fila, indice)
            detalle = (
                f"Saldo={resultado['Saldo']}; "
                f"Verificada={resultado['Verificada']}; "
                f"Limitada={resultado['Limitada']}"
            )
            exito(f"[OK] {usuario} -> {detalle}")
            registrar_historial(
                usuario,
                "EXITO",
                detalle,
                saldo=resultado["Saldo"],
                verificada=resultado["Verificada"],
                limitada=resultado["Limitada"],
            )
        except Exception as exc:  # noqa: BLE001  (aislamos el fallo por cuenta)
            error(f"[FALLO] {usuario}: {exc}")
            registrar_historial(usuario, "ERROR", str(exc))

    exito(f"=== Proceso finalizado. Revisa {ARCHIVO_HISTORIAL} ===")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.warning("Ejecución interrumpida por el usuario.")
