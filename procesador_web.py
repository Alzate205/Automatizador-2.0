"""
procesador_web.py
=================

Procesador web (Betplay) con comportamiento humano sobre un navegador externo
ya abierto vía CDP.

Reutiliza las utilidades del proyecto en vez de reimplementarlas:
    - extraccion.extraer_saldo        -> parseo robusto del saldo (formato es-CO)
    - restricciones.contiene_restriccion -> detección de límites sin tildes
    - pausa.pausa_con_jitter          -> esperas cortas variables (human_delay)

Mantiene la robustez de la versión previa (base_url configurable, huella es-CO,
movimiento de mouse, espera post-login, logging por etapa, manejo de errores
tipado, selectores con alternancia regex y `.first` para modo estricto).

Devuelve un dict: {saldo, verificada, limitada, estado, timestamp}.
"""

import logging
import random
import re
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, Optional

from playwright.async_api import (
    async_playwright,
    TimeoutError as PlaywrightTimeout,
    Error as PlaywrightError,
)

# Utilidades compartidas del proyecto (evitan duplicar lógica aquí).
from extraccion import extraer_saldo
from restricciones import contiene_restriccion
from pausa import pausa_con_jitter

logger = logging.getLogger(__name__)

# Errores de Playwright que tratamos como "no concluyente" sin tumbar el flujo.
ERRORES_PW = (PlaywrightTimeout, PlaywrightError)

# Configuración del sitio objetivo.
BASE_URL_POR_DEFECTO = "https://www.betplay.com.co"
MONTO_PRUEBA_LIMITE = "8000000"  # monto alto para forzar (si aplica) la alerta de límite

# Palabras (específicas de Betplay) que delatan una cuenta limitada. La
# comparación sin tildes/mayúsculas la realiza restricciones.contiene_restriccion.
PALABRAS_LIMITE_BETPLAY = (
    "límite",
    "máximo permitido",
    "excede",
    "no permitido",
)


# ==================== COMPORTAMIENTO HUMANO ====================

async def human_delay(min_sec: float = 0.8, max_sec: float = 3.0) -> None:
    """
    Pausa corta y variable (en segundos) para simular reacción humana.

    Delega en pausa.pausa_con_jitter para no duplicar la lógica de espera:
    el rango [min_sec, max_sec] se traduce a base + jitter.
    """
    jitter_ms = int(max(0.0, max_sec - min_sec) * 1000)
    await pausa_con_jitter(min_sec, jitter_ms=jitter_ms)


async def human_type(page, selector: str, text: str, delay_range=(40, 140)) -> bool:
    """
    Escribe el texto carácter a carácter con variabilidad humana.

    Devuelve True si pudo escribir, False si el selector no estaba disponible
    (así el llamador puede decidir si continuar o no).
    """
    try:
        await page.locator(selector).first.click()
        await human_delay(0.3, 0.8)
        for char in text:
            await page.keyboard.type(char, delay=random.randint(*delay_range))
            if random.random() < 0.12:
                await human_delay(0.15, 0.45)
        return True
    except ERRORES_PW:
        logger.warning(f"No se pudo escribir en: {selector}")
        return False
    
async def human_mouse_move(page, steps: int = 8):
    """Movimiento de mouse más natural"""
    for _ in range(steps):
        x = random.randint(100, 1200)
        y = random.randint(100, 700)
        await page.mouse.move(x, y, steps=random.randint(3, 8))
        await human_delay(0.1, 0.4)

async def scroll_humano(page):
    """Scroll natural"""
    await page.evaluate("window.scrollBy(0, document.body.scrollHeight * 0.3)")
    await human_delay(0.8, 2.2)
    await page.evaluate("window.scrollBy(0, -document.body.scrollHeight * 0.15)")


# ==================== PROCESADOR PRINCIPAL ====================

async def process_user(
    cdp_endpoint: str,
    username: str,
    password: str,
    nombre: str = "",
    verification_code: Optional[str] = None,
    code_provider: Optional[Callable[[], Awaitable[Optional[str]]]] = None,
    base_url: str = BASE_URL_POR_DEFECTO,
) -> Dict[str, Any]:
    """
    Se adjunta a un navegador externo (CDP), inicia sesión, resuelve el 2FA si
    aparece, extrae el saldo, verifica el estado de la cuenta y prueba el límite.

    El código 2FA se resuelve EN EL MOMENTO correcto (cuando aparece el campo,
    tras enviar el login): si se pasa `code_provider` (callable async que
    devuelve el código), se invoca en ese instante; en su defecto se usa el
    `verification_code` estático.

    Devuelve {saldo, verificada, limitada, estado, timestamp}. Nunca lanza:
    ante un fallo crítico devuelve estado "error".
    """
    etiqueta = nombre or username
    page = None
    new_page_created = False

    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(cdp_endpoint)

            # Reutilizar contexto existente o crear uno nuevo con huella es-CO.
            if browser.contexts:
                context = browser.contexts[0]
            else:
                context = await browser.new_context(
                    viewport={"width": 1366, "height": random.randint(768, 900)},
                    locale="es-CO",
                    timezone_id="America/Bogota",
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/126.0.0.0 Safari/537.36"
                    ),
                )

            if context.pages:
                page = context.pages[0]
            else:
                page = await context.new_page()
                new_page_created = True

            # ---------- Navegación inicial ----------
            logger.info(f"[{etiqueta}] Navegando a {base_url}")
            await page.goto(base_url, wait_until="domcontentloaded", timeout=45000)
            await human_delay(2.5, 5)
            await page.mouse.move(random.randint(100, 800), random.randint(100, 500))
            await human_delay(1, 2.5)

            # ---------- Login / Registro ----------
            try:
                await page.click(
                    "text=/Iniciar sesión|Registrarse|Crear cuenta|Registro|Sign up/i",
                    timeout=8000,
                )
                await human_delay(2, 4)
            except ERRORES_PW:
                logger.warning(f"[{etiqueta}] No se encontró botón de login/registro visible")

            if await human_type(
                page,
                'input[name*="email"], input#email, input[placeholder*="orreo"], input[placeholder*="mail"]',
                username,
            ):
                await human_delay(1, 2)
                await human_type(
                    page,
                    'input[name*="password"], input#password, input[placeholder*="ontraseña"]',
                    password,
                )
                await human_delay(1, 2.5)
                try:
                    await page.click(
                        'button[type="submit"], button:has-text("Ingresar"), button:has-text("Registrarse")'
                    )
                    await human_delay(3, 6)
                except ERRORES_PW as e:
                    logger.warning(f"[{etiqueta}] No se pudo enviar el login: {e}")

            # ---------- 2FA / código de verificación ----------
            # Detectamos el campo DESPUÉS del login: solo en este punto el sitio
            # ya envió el correo con el código, así que es el momento correcto
            # para pedirlo (vía code_provider) en lugar de pre-buscarlo.
            hay_2fa = False
            try:
                await page.locator(
                    'input[placeholder*="ódigo"], #verification-code, #code, input[name*="code"]'
                ).first.wait_for(state="visible", timeout=8000)
                hay_2fa = True
            except ERRORES_PW:
                pass  # esta cuenta no pidió 2FA

            if hay_2fa:
                logger.info(f"[{etiqueta}] 🔐 Campo de verificación 2FA detectado")
                await human_delay(2, 4)
                codigo = await _obtener_codigo_2fa(verification_code, code_provider, etiqueta)
                if codigo:
                    await human_type(
                        page,
                        'input[placeholder*="ódigo"], #verification-code, #code',
                        codigo,
                    )
                    await page.keyboard.press("Enter")
                    await human_delay(4, 7)
                else:
                    logger.warning(f"[{etiqueta}] 2FA presente pero sin código disponible")

            # ---------- Espera post-login ----------
            try:
                await page.wait_for_url("**/account**|**/dashboard**|**/deportes**", timeout=15000)
            except ERRORES_PW:
                try:
                    await page.locator("body").wait_for(timeout=10000)
                except ERRORES_PW:
                    pass

            # ---------- Comportamiento humano (mouse + scroll) ----------
            # No crítico: si falla, no debe tumbar la lectura de datos.
            try:
                await human_mouse_move(page)
                await scroll_humano(page)
                await human_delay(2, 5)
            except ERRORES_PW:
                pass

            # ---------- Extraer saldo (utilidad compartida) ----------
            saldo = 0.0
            try:
                # CSS + texto combinados con .or_(): mezclar 'text=' dentro de una
                # lista CSS por comas no es válido en Playwright. El fallback de
                # texto busca un patrón monetario ("$ 1.234.567"), no un "$" suelto.
                saldo_locator = page.locator("#balance, .balance, .user-balance").or_(
                    page.get_by_text(re.compile(r"\$\s*[\d.,]+"))
                ).first
                await saldo_locator.wait_for(state="visible", timeout=8000)
                saldo_text = await saldo_locator.inner_text(timeout=5000)
                saldo = extraer_saldo(saldo_text)
                logger.info(f"[{etiqueta}] Saldo extraído: ${saldo:,.2f}")
            except ERRORES_PW:
                logger.warning(f"[{etiqueta}] No se pudo extraer el saldo")

            # ---------- Verificación de cuenta ----------
            # Selectores más cercanos a Betplay. Combinamos CSS + texto con
            # .or_(get_by_text(...)) porque mezclar 'text=' dentro de una lista
            # CSS separada por comas NO es válido en Playwright.
            verificada = "no"
            try:
                verificada_loc = page.locator(
                    ".badge-verified, .verified-badge, .status-success"
                ).or_(
                    page.get_by_text(
                        re.compile(
                            r"Verificad[ao]|Cuenta verificada|Identidad confirmada",
                            re.IGNORECASE,
                        )
                    )
                ).first
                await verificada_loc.wait_for(state="visible", timeout=6000)
                verificada = "si"
                logger.info(f"[{etiqueta}] Cuenta verificada: si")
            except ERRORES_PW:
                logger.info(f"[{etiqueta}] Sin insignia de verificación visible (no)")

            # ---------- Prueba de límite ----------
            limitada = await _probar_limite(page, base_url, etiqueta)

            return {
                "saldo": saldo,
                "verificada": verificada,
                "limitada": limitada,
                "estado": "exitosa" if saldo > 0 else "revisar",
                "timestamp": datetime.now().isoformat(),
            }

    except Exception as e:  # noqa: BLE001  (aislamos el fallo para no tumbar el lote)
        logger.error(f"[{etiqueta}] Error crítico en process_user: {e}")
        return {
            "saldo": 0.0,
            "verificada": "error",
            "limitada": False,
            "estado": "error",
            "timestamp": datetime.now().isoformat(),
        }
    finally:
        # Solo cerramos la pestaña si la abrimos nosotros; el navegador remoto sigue vivo.
        if page and new_page_created:
            try:
                await page.close()
            except ERRORES_PW:
                pass


async def _obtener_codigo_2fa(
    verification_code: Optional[str],
    code_provider: Optional[Callable[[], Awaitable[Optional[str]]]],
    etiqueta: str,
) -> Optional[str]:
    """
    Resuelve el código 2FA en el momento correcto (campo ya visible tras el login).

    Prioriza `code_provider` (obtención fresca, p. ej. por correo); si no hay
    proveedor, usa el `verification_code` estático. Nunca lanza: ante un fallo
    del proveedor devuelve None.
    """
    if code_provider is not None:
        logger.info(f"[{etiqueta}] Solicitando código 2FA al proveedor (correo)...")
        try:
            return await code_provider()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[{etiqueta}] El proveedor de código 2FA falló: {e}")
            return None
    return verification_code


async def _probar_limite(page, base_url: str, etiqueta: str) -> bool:
    try:
        logger.info(f"[{etiqueta}] Iniciando prueba de límite...")
        await page.goto(f"{base_url}/deportes/futbol", wait_until="networkidle", timeout=25000)
        await human_delay(3, 6)

        # Partido popular
        await page.locator("text=/Liga BetPlay|Primera A|BetPlay Cup/i").first.click()
        await human_delay(2.5, 5)

        # Seleccionar cualquier cuota
        await page.locator("button, div").filter(has_text=re.compile(r"\d\.\d{1,2}")).first.click()
        await human_delay(2, 4)

        # Monto alto
        monto_input = page.locator('input[placeholder*="Monto"], input[name*="stake"], input[type="number"]').first
        await monto_input.fill("10000000")
        await human_delay(2, 3.5)

        # Buscar alerta en toda la página
        cuerpo = await page.locator("body").inner_text(timeout=8000)
        if contiene_restriccion(cuerpo, PALABRAS_LIMITE_BETPLAY):
            logger.info(f"[{etiqueta}] ✅ CUENTA LIMITADA DETECTADA")
            return True

        logger.info(f"[{etiqueta}] No se detectó límite")
        return False
    except ERRORES_PW as e:
        logger.debug(f"[{etiqueta}] Prueba de límite falló (no crítico): {e}")
        return False
