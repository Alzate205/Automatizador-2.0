"""
correo_reciente.py
==================

Script básico con imaplib: se conecta a un servidor de correo por IMAP sobre
SSL, busca los mensajes de un remitente dado y devuelve el TEXTO PLANO del
correo más reciente.

Pensado para TU PROPIA cuenta (o una de prueba que controles), usando una
contraseña de aplicación (app password), nunca la clave principal.

Uso:
    from correo_reciente import obtener_texto_correo_reciente

    texto = obtener_texto_correo_reciente(
        usuario="miusuario@gmail.com",
        password="xxxx xxxx xxxx xxxx",   # app password
        remitente="noreply@ejemplo.com",
    )

Prueba manual (credenciales por variables de entorno):
    PowerShell:  $env:IMAP_USER='tu@gmail.com'; $env:IMAP_PASS='app password'
    python correo_reciente.py noreply@ejemplo.com
"""

from __future__ import annotations

import email
import imaplib
from email.message import Message

SERVIDOR_IMAP = "imap.gmail.com"   # p. ej. imap.gmail.com, outlook.office365.com
PUERTO_IMAP = 993                  # IMAP sobre SSL


def _obtener_texto_plano(msg: Message) -> str:
    """Devuelve el texto plano del mensaje (text/plain), decodificado de forma segura."""
    if msg.is_multipart():
        for part in msg.walk():
            disposicion = str(part.get("Content-Disposition", ""))
            if part.get_content_type() == "text/plain" and "attachment" not in disposicion:
                msg = part
                break
        else:
            return ""  # no hay parte de texto plano
    contenido = msg.get_payload(decode=True)
    if contenido is None:
        return ""
    return contenido.decode(msg.get_content_charset() or "utf-8", errors="replace")


def obtener_texto_correo_reciente(
    usuario: str,
    password: str,
    remitente: str,
    servidor: str = SERVIDOR_IMAP,
    puerto: int = PUERTO_IMAP,
) -> str | None:
    """
    Conecta por IMAP/SSL, busca los correos del remitente indicado y devuelve el
    texto plano del más reciente. Devuelve None si no hay correos o falla algo.
    """
    conexion: imaplib.IMAP4_SSL | None = None
    try:
        conexion = imaplib.IMAP4_SSL(servidor, puerto)
        conexion.login(usuario, password)
        conexion.select("INBOX")

        estado, datos = conexion.search(None, "FROM", f'"{remitente}"')
        if estado != "OK":
            return None

        ids = datos[0].split()
        if not ids:
            return None  # no hay correos de ese remitente

        # El último id es el más reciente. BODY.PEEK[] no lo marca como leído.
        estado, datos = conexion.fetch(ids[-1], "(BODY.PEEK[])")
        if estado != "OK" or not datos or datos[0] is None:
            return None

        msg = email.message_from_bytes(datos[0][1])
        return _obtener_texto_plano(msg)

    except imaplib.IMAP4.error as exc:
        print(f"Error IMAP (¿credenciales / app password?): {exc}")
        return None
    finally:
        if conexion is not None:
            try:
                conexion.logout()
            except Exception:  # noqa: BLE001
                pass


if __name__ == "__main__":
    import os
    import sys

    usuario = os.environ.get("IMAP_USER", "")
    password = os.environ.get("IMAP_PASS", "")
    remitente = sys.argv[1] if len(sys.argv) > 1 else "noreply@ejemplo.com"

    if not usuario or not password:
        print(
            "Define IMAP_USER e IMAP_PASS como variables de entorno para probar.\n"
            "PowerShell:  $env:IMAP_USER='tu@gmail.com'; $env:IMAP_PASS='app password'"
        )
    else:
        texto = obtener_texto_correo_reciente(usuario, password, remitente)
        print(texto if texto else "Sin resultados.")
