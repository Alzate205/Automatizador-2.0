import asyncio
from playwright.async_api import async_playwright, Error as PlaywrightError, TimeoutError
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

async def process_user(
    cdp_endpoint: str,
    username: str,
    password: str,
    verification_code: Optional[str] = None,
    base_url: str = "https://ejemplo-plataforma-x.com"
) -> Dict[str, Any]:
    """
    Procesa un usuario individual usando conexión CDP existente con robustez mejorada.
    """
    page = None
    browser = None
    context = None
    new_page_created = False

    try:
        async with async_playwright() as p:
            # Conectar al endpoint CDP
            browser = await p.chromium.connect_over_cdp(cdp_endpoint)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            
            # Usar página existente o crear una nueva
            if context.pages:
                page = context.pages[0]
            else:
                page = await context.new_page()
                new_page_created = True

            # Navegar a la plataforma
            await page.goto(base_url, wait_until="networkidle", timeout=30000)

            # === LOGIN ===
            await page.fill("#input-user", username)
            await page.fill("#input-pass", password)
            await page.click("#btn-submit")

            # Espera inteligente post-login
            try:
                # Esperar cambio de URL o elemento principal del dashboard
                await asyncio.wait_for(
                    page.wait_for_url("**/dashboard**", timeout=15000),
                    timeout=15
                )
            except (TimeoutError, asyncio.TimeoutError):
                try:
                    await page.locator("#main-layout").wait_for(state="visible", timeout=10000)
                except TimeoutError:
                    logger.warning("No se detectó dashboard ni #main-layout después del login")

            # === 2FA / Código de verificación ===
            if await page.locator("input#verification-code").count() > 0:
                logger.info("Esperando código de verificación...")
                verification_input = page.locator("input#verification-code")
                await verification_input.wait_for(state="visible", timeout=10000)
                
                if verification_code:
                    await verification_input.fill(verification_code)
                    await page.keyboard.press("Enter")
                    await page.wait_for_load_state("networkidle", timeout=10000)
                else:
                    logger.warning("Campo 2FA detectado pero no se proporcionó código")

            # === EXTRACCIÓN DE SALDO ===
            saldo = 0.0
            try:
                balance_locator = page.locator("#balance-text")
                await balance_locator.wait_for(state="visible", timeout=5000)
                saldo_text = await balance_locator.inner_text(timeout=3000)
                # Limpieza robusta del texto
                clean_text = ''.join(c for c in saldo_text if c.isdigit() or c in '.,-')
                saldo = float(clean_text.replace(',', '').replace('.', '') or 0)
            except (TimeoutError, PlaywrightError, ValueError):
                logger.warning("No se pudo extraer el saldo (#balance-text)")

            # === VERIFICACIÓN DE CUENTA ===
            verificada = "desconocido"
            try:
                badge_locator = page.locator(".badge-status")
                await badge_locator.wait_for(state="visible", timeout=5000)
                verificada = "si" if await badge_locator.count() > 0 else "no"
            except (TimeoutError, PlaywrightError):
                logger.warning("No se detectó badge de verificación (.badge-status)")

            # === INTERACCIÓN DE PRUEBA (MONTO) ===
            limitada = False
            try:
                # Navegar a sección de prueba (selector genérico)
                await page.click('text=Sección Prueba', timeout=5000)
                await page.wait_for_load_state("networkidle", timeout=8000)

                monto_input = page.locator("input#monto-test")
                await monto_input.wait_for(state="visible", timeout=5000)
                await monto_input.fill("1000000")
                await monto_input.press("Enter")

                # Verificar alerta de límite en 3 segundos
                alert_locator = page.locator(".alert-msg")
                await alert_locator.wait_for(state="visible", timeout=3000)
                alert_text = await alert_locator.inner_text(timeout=2000)
                if "límite" in alert_text.lower():
                    limitada = True
            except (TimeoutError, PlaywrightError):
                pass  # No es crítico

            return {
                "saldo": saldo,
                "verificada": verificada,
                "limitada": limitada
            }

    except Exception as e:
        logger.error(f"Error crítico procesando usuario: {e}")
        return {
            "saldo": 0.0,
            "verificada": "error",
            "limitada": False
        }
    finally:
        # Limpieza: cerrar solo la página si fue creada en este proceso
        if page and new_page_created:
            try:
                await page.close()
            except Exception:
                pass