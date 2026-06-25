"""
lector_correos.py
=================

Módulo independiente para extracción de datos desde correo (automatización de
oficina / pruebas). Se conecta a un buzón por IMAP sobre SSL y extrae un código
de verificación numérico del correo más reciente que coincida con un remitente.

Pensado para acceder a TU PROPIA cuenta (o una cuenta de prueba que controles)
usando una contraseña de aplicación (app password), no la contraseña principal.

Uso típico:
    codigo = extraer_codigo_verificacion(
        usuario="miusuario@gmail.com",
        password="xxxx xxxx xxxx xxxx",   # app password
        remitente="noreply@ejemplo.com",
    )

Llamada desde un flujo asíncrono:
    codigo = await extraer_codigo_verificacion_async(...)

Notas de seguridad:
    - Usa SIEMPRE app passwords / contraseñas de aplicación, nunca la clave
      principal de la cuenta.
    - No guardes credenciales en el código: pásalas por variables de entorno,
      un .env fuera del control de versiones, o argumentos en tiempo de
      ejecución.
"""

from __future__ import annotations

import asyncio
import email
import imaplib
import re
from email.message import Message

# Reutilizamos el logger coloreado ya configurado en auditor.py.
from auditor import log

# ---------------------------------------------------------------------------
# CONFIGURACIÓN POR DEFECTO (placeholders editables)
# ---------------------------------------------------------------------------

SERVIDOR_IMAP = "imap.gmail.com"   # p. ej. imap.gmail.com, outlook.office365.com
PUERTO_IMAP = 993                  # IMAP sobre SSL
REMITENTE_OBJETIVO = "noreply@ejemplo.com"

# Patrón de 6 dígitos continuos (código de verificación típico).
PATRON_CODIGO = r"\b(\d{6})\b"


# ---------------------------------------------------------------------------
# UTILIDADES INTERNAS
# ---------------------------------------------------------------------------

def _decodificar(part: Message) -> str:
    """Decodifica el payload de una parte del correo a texto, de forma segura."""
    contenido = part.get_payload(decode=True)
    if contenido is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    return contenido.decode(charset, errors="replace")


def _obtener_cuerpo(msg: Message) -> str:
    """
    Devuelve el texto del correo. Prefiere text/plain; si no hay, usa text/html.
    """
    if not msg.is_multipart():
        return _decodificar(msg)

    # Primera pasada: texto plano (ignorando adjuntos).
    for part in msg.walk():
        disposicion = str(part.get("Content-Disposition", ""))
        if part.get_content_type() == "text/plain" and "attachment" not in disposicion:
            return _decodificar(part)

    # Segunda pasada: HTML como respaldo.
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            return _decodificar(part)

    return ""


# ---------------------------------------------------------------------------
# FUNCIÓN PRINCIPAL (síncrona, reutilizable)
# ---------------------------------------------------------------------------

def extraer_codigo_verificacion(
    usuario: str,
    password: str,
    remitente: str = REMITENTE_OBJETIVO,
    servidor: str = SERVIDOR_IMAP,
    puerto: int = PUERTO_IMAP,
    patron: str = PATRON_CODIGO,
) -> str | None:
    """
    Conecta por IMAP/SSL, busca el correo NO LEÍDO más reciente del remitente
    indicado y extrae el primer código que coincida con `patron`.

    Devuelve el código (str) o None si no hay correo, no hay código o falla la
    conexión/credenciales. Nunca lanza: registra el problema y retorna None.

    No marca el correo como leído (usa BODY.PEEK), para no alterar el buzón.
    """
    conexion: imaplib.IMAP4_SSL | None = None
    try:
        log.info(f"Conectando por IMAP a {servidor}:{puerto} ...")
        conexion = imaplib.IMAP4_SSL(servidor, puerto)
        conexion.login(usuario, password)
        log.exito(f"Sesión IMAP iniciada para {usuario}")

        conexion.select("INBOX")

        # Buscar no leídos del remitente objetivo.
        estado, datos = conexion.search(None, "UNSEEN", "FROM", f'"{remitente}"')
        if estado != "OK":
            log.error(f"La búsqueda IMAP falló (estado: {estado})")
            return None

        ids = datos[0].split()
        if not ids:
            log.warning(f"No hay correos nuevos de {remitente}")
            return None

        # El último id es el más reciente.
        id_mas_reciente = ids[-1]
        log.info(f"Correo encontrado (id {id_mas_reciente.decode()}); leyendo cuerpo...")

        # BODY.PEEK[] no marca el correo como leído.
        estado, datos = conexion.fetch(id_mas_reciente, "(BODY.PEEK[])")
        if estado != "OK" or not datos or datos[0] is None:
            log.error("No se pudo recuperar el cuerpo del correo")
            return None

        msg = email.message_from_bytes(datos[0][1])
        cuerpo = _obtener_cuerpo(msg)

        coincidencia = re.search(patron, cuerpo)
        if coincidencia:
            codigo = coincidencia.group(1)
            log.exito(f"Código extraído: {codigo}")
            return codigo

        log.warning("Se leyó el correo pero no se encontró un código con el patrón")
        return None

    except imaplib.IMAP4.error as exc:
        # Cubre fallos de login y otros errores del protocolo IMAP.
        log.error(f"Error IMAP (¿credenciales/app password?): {exc}")
        return None
    except Exception as exc:  # noqa: BLE001
        log.error(f"Error inesperado al leer el correo: {exc}")
        return None
    finally:
        if conexion is not None:
            try:
                conexion.logout()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# WRAPPER ASÍNCRONO (para integrarlo en flujos async como auditor.py)
# ---------------------------------------------------------------------------

async def extraer_codigo_verificacion_async(
    usuario: str,
    password: str,
    remitente: str = REMITENTE_OBJETIVO,
    servidor: str = SERVIDOR_IMAP,
    puerto: int = PUERTO_IMAP,
    patron: str = PATRON_CODIGO,
) -> str | None:
    """
    Versión asíncrona: ejecuta la función síncrona en un hilo aparte para no
    bloquear el bucle de eventos. Misma firma y mismo valor de retorno.
    """
    return await asyncio.to_thread(
        extraer_codigo_verificacion,
        usuario, password, remitente, servidor, puerto, patron,
    )


# ---------------------------------------------------------------------------
# CONTENEDOR DE ALTO NIVEL: SONDEO CON ESPERA (POLLING)
# ---------------------------------------------------------------------------

async def esperar_y_extraer_codigo(
    usuario: str,
    password: str,
    remitente: str = REMITENTE_OBJETIVO,
    servidor: str = SERVIDOR_IMAP,
    puerto: int = PUERTO_IMAP,
    patron: str = PATRON_CODIGO,
    max_intentos: int = 6,
    espera_segundos: int = 10,
) -> str | None:
    """
    Sondea el buzón hasta `max_intentos` veces esperando a que llegue el código.

    Llama a extraer_codigo_verificacion_async repetidamente. Si en un intento
    obtiene un código, lo retorna de inmediato (rompe el bucle). Si recibe None
    (el correo aún no llegó), espera `espera_segundos` y reintenta. Si agota los
    intentos sin éxito, retorna None.

    Tiempo máximo de espera ≈ (max_intentos - 1) * espera_segundos.
    """
    for intento in range(1, max_intentos + 1):
        codigo = await extraer_codigo_verificacion_async(
            usuario, password, remitente, servidor, puerto, patron,
        )

        if codigo:
            log.exito(f"Código obtenido en el intento {intento}/{max_intentos}: {codigo}")
            return codigo

        # Solo esperamos si aún quedan intentos por delante.
        if intento < max_intentos:
            log.warning(
                f"Correo no encontrado aún. Intento {intento} de {max_intentos}. "
                f"Esperando {espera_segundos}s..."
            )
            await asyncio.sleep(espera_segundos)

    log.error(f"Se agotaron los {max_intentos} intentos sin encontrar el código.")
    return None


# ---------------------------------------------------------------------------
# PRUEBA MANUAL
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Demostración: toma credenciales de variables de entorno para no
    # escribirlas en el código.
    import os

    usuario_demo = os.environ.get("IMAP_USER", "")
    password_demo = os.environ.get("IMAP_PASS", "")

    if not usuario_demo or not password_demo:
        log.warning(
            "Define IMAP_USER e IMAP_PASS como variables de entorno para probar. "
            "Ejemplo (PowerShell): $env:IMAP_USER='tu@gmail.com'; $env:IMAP_PASS='app password'"
        )
    else:
        resultado = extraer_codigo_verificacion(usuario_demo, password_demo)
        log.info(f"Resultado de la prueba: {resultado}")
