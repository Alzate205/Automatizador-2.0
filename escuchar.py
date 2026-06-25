"""
escuchar.py
===========

Bloque autocontenido que se ADJUNTA (no lanza) a un navegador ya en
ejecución vía CDP usando Playwright asíncrono, sobre 127.0.0.1 y un puerto
que se recibe como argumento de línea de comandos.

Requisito: tener un navegador escuchando en ese puerto de depuración, p. ej.:
    chrome.exe --remote-debugging-port=9222

Uso:
    python escuchar.py 9222     # puerto explícito
    python escuchar.py          # usa 9222 por defecto
"""

import sys
import asyncio

from playwright.async_api import async_playwright

PUERTO_POR_DEFECTO = 9222


async def escuchar(puerto: int) -> None:
    """Se adjunta a la sesión abierta en 127.0.0.1:<puerto> y muestra el título."""
    async with async_playwright() as p:
        navegador = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{puerto}")
        context = navegador.contexts[0] if navegador.contexts else await navegador.new_context()
        pagina = context.pages[0] if context.pages else await context.new_page()
        print("Adjuntado. Título actual:", await pagina.title())
        await navegador.close()  # se desconecta; NO cierra el navegador remoto


if __name__ == "__main__":
    puerto = int(sys.argv[1]) if len(sys.argv) > 1 else PUERTO_POR_DEFECTO
    asyncio.run(escuchar(puerto))
