"""
conexion_cdp.py
===============

Conexión a un navegador ya en ejecución mediante CDP (Chrome DevTools
Protocol) sobre WebSocket, usando Playwright en modo asíncrono.

A diferencia de p.chromium.launch() —que arranca un Chromium nuevo y aislado—,
aquí usamos p.chromium.connect_over_cdp() para adjuntarnos a un navegador que
YA está corriendo localmente y expone un puerto de depuración remota
(remote debugging port). Es el patrón habitual en entornos de QA cuando quieres
reutilizar una instancia ya levantada en lugar de crear una desde cero.

Requisito: que exista un navegador escuchando en el puerto indicado, p. ej.
arrancado con:

    chrome.exe --remote-debugging-port=9222

Uso de prueba:
    python conexion_cdp.py
"""

from __future__ import annotations

# Reutilizamos el logger coloreado ya configurado en auditor.py.
from auditor import log

# ---------------------------------------------------------------------------
# CONFIGURACIÓN (placeholders editables)
# ---------------------------------------------------------------------------

# Host y puerto donde el navegador expone el CDP.
HOST_CDP = "127.0.0.1"
PUERTO_CDP = 9222

# Identificador lógico del perfil (solo para trazas/logs; te permite saber a
# qué perfil te estás conectando si manejas varios puertos).
PERFIL_ID = "qa_perfil_01"

# URL genérica de prueba para verificar que la conexión y la navegación van.
URL_PRUEBA = "https://example.com"


def construir_endpoint(host: str = HOST_CDP, puerto: int = PUERTO_CDP) -> str:
    """Construye el endpoint HTTP del CDP que Playwright resolverá a WS."""
    return f"http://{host}:{puerto}"


# ---------------------------------------------------------------------------
# CONEXIÓN
# ---------------------------------------------------------------------------

async def conectar_perfil_existente(
    host: str = HOST_CDP,
    puerto: int = PUERTO_CDP,
    perfil_id: str = PERFIL_ID,
    url_prueba: str = URL_PRUEBA,
) -> bool:
    """
    Se conecta a un navegador ya en ejecución vía CDP, abre una pestaña nueva
    y navega a una URL de prueba para verificar la conexión.

    Devuelve True si la verificación fue exitosa, False si falló.

    Notas de diseño:
        - Import diferido de Playwright (igual que en auditor.py) para no
          acoplar el resto del flujo al navegador.
        - NO cerramos el navegador (browser.close() solo nos desconecta del
          proceso remoto), pero tampoco lo matamos: él sigue vivo. Solo
          cerramos la pestaña que abrimos.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log.error(
            "Playwright no está instalado. Ejecuta: "
            "pip install playwright  &&  playwright install chromium"
        )
        return False

    endpoint = construir_endpoint(host, puerto)
    log.info(f"[{perfil_id}] Conectando por CDP a {endpoint} ...")

    async with async_playwright() as p:
        try:
            navegador = await p.chromium.connect_over_cdp(endpoint)
        except Exception as exc:  # noqa: BLE001
            log.error(
                f"[{perfil_id}] No se pudo conectar al CDP en {endpoint}: {exc}"
            )
            log.info(
                "Sugerencia: arranca el navegador con "
                "--remote-debugging-port=" + str(puerto)
            )
            return False

        log.exito(f"[{perfil_id}] Conexión CDP establecida")

        # Reutilizamos el contexto ya existente del navegador si lo hay; si no,
        # creamos uno nuevo. Así la pestaña vive dentro del perfil ya cargado.
        if navegador.contexts:
            context = navegador.contexts[0]
            log.info(f"[{perfil_id}] Reutilizando contexto existente")
        else:
            context = await navegador.new_context()
            log.info(f"[{perfil_id}] Sin contexto previo; se creó uno nuevo")

        pagina = None
        try:
            pagina = await context.new_page()
            log.info(f"[{perfil_id}] Pestaña nueva abierta")

            log.info(f"[{perfil_id}] Navegando a {url_prueba} ...")
            await pagina.goto(url_prueba, wait_until="domcontentloaded")

            titulo = await pagina.title()
            log.exito(f"[{perfil_id}] Conexión verificada. Título: '{titulo}'")
            return True

        except Exception as exc:  # noqa: BLE001
            log.error(f"[{perfil_id}] Fallo durante la navegación: {exc}")
            return False

        finally:
            # Cerramos solo nuestra pestaña; el navegador remoto sigue vivo.
            if pagina is not None:
                await pagina.close()
            await navegador.close()  # desconecta de la sesión CDP, no la mata
            log.info(f"[{perfil_id}] Desconectado del CDP")


# ---------------------------------------------------------------------------
# PRUEBA STANDALONE
# ---------------------------------------------------------------------------

async def _main() -> None:
    log.info("=== Prueba de conexión CDP ===")
    ok = await conectar_perfil_existente()
    if ok:
        log.exito("=== Verificación CDP completada ===")
    else:
        log.error("=== Verificación CDP fallida ===")


if __name__ == "__main__":
    import asyncio

    asyncio.run(_main())
