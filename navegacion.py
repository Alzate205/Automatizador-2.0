import asyncio
import pandas as pd
from playwright.async_api import async_playwright, Error as PlaywrightError
from typing import Dict, Optional, Any
import logging

# Configuración de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def process_user(
    cdp_endpoint: str,
    username: str,
    password: str,
    base_url: str = "https://ejemplo-plataforma-x.com"
) -> Dict[str, Any]:
    """
    Procesa un usuario individual usando conexión CDP existente.
    Retorna el diccionario con los resultados.
    """
    async with async_playwright() as p:
        try:
            # Conectar al endpoint CDP
            browser = await p.chromium.connect_over_cdp(cdp_endpoint)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = context.pages[0] if context.pages else await context.new_page()

            # Navegar a la plataforma
            await page.goto(base_url, wait_until="networkidle", timeout=30000)

            # Login
            await page.fill("#input-user", username)
            await page.fill("#input-pass", password)
            await page.click("#btn-submit")
            
            # Esperar a que cargue después del login
            await page.wait_for_load_state("networkidle", timeout=15000)

            # Extraer saldo
            saldo_text = await page.locator("#balance-text").inner_text(timeout=10000)
            try:
                saldo = float(''.join(filter(lambda x: x.isdigit() or x in '.,-', saldo_text.replace(',', '').replace('.', ''))))
            except ValueError:
                saldo = 0.0

            # Verificar cuenta validada
            verificada = "si" if await page.locator(".badge-status").count() > 0 else "no"

            # Simular interacción en sección interna (ajusta el selector de navegación si es necesario)
            # Ejemplo genérico: asumir que hay un link o botón para ir a la sección de prueba
            await page.click('text=Sección Prueba')  # Selector genérico; ajusta según UI real
            await page.wait_for_load_state("networkidle")

            # Llenar monto
            monto_input = page.locator("input#monto-test")
            await monto_input.fill("1000000")
            await monto_input.press("Enter")  # o click en submit si aplica

            # Verificar alerta en los siguientes 3 segundos
            limitada = False
            try:
                alert_locator = page.locator(".alert-msg")
                await alert_locator.wait_for(state="visible", timeout=3000)
                alert_text = await alert_locator.inner_text(timeout=1000)
                if "límite" in alert_text.lower():
                    limitada = True
            except PlaywrightError:
                # Timeout o no aparece alerta
                pass

            return {
                "saldo": saldo,
                "verificada": verificada,
                "limitada": limitada
            }

        except Exception as e:
            logger.error(f"Error procesando usuario: {e}")
            return {
                "saldo": 0.0,
                "verificada": "error",
                "limitada": False
            }
        finally:
            # No cerrar browser/context si es CDP compartido
            pass


async def main(excel_path: str, output_path: str):
    """
    Función principal: lee Excel, procesa cada fila y actualiza resultados.
    """
    # Leer Excel
    df = pd.read_excel(excel_path)
    
    # Asumir columnas necesarias: cdp_endpoint, username, password (ajusta nombres según tu Excel)
    required_cols = ["cdp_endpoint", "username", "password"]
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"Columna requerida faltante: {col}")

    results = []
    for idx, row in df.iterrows():
        logger.info(f"Procesando fila {idx + 1}/{len(df)}")
        
        result = await process_user(
            cdp_endpoint=row["cdp_endpoint"],
            username=row["username"],
            password=row["password"]
        )
        
        results.append(result)

    # Actualizar DataFrame
    result_df = pd.DataFrame(results)
    for col in result_df.columns:
        df[col] = result_df[col]

    # Guardar Excel actualizado
    df.to_excel(output_path, index=False)
    logger.info(f"Procesamiento completado. Archivo guardado en: {output_path}")


if __name__ == "__main__":
    # Ejemplo de uso
    asyncio.run(main("usuarios.xlsx", "usuarios_actualizados.xlsx"))