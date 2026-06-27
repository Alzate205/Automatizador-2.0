"""
procesador_web.py
=================

Procesador web (Betplay) con comportamiento humano sobre un navegador externo
ya abierto vía CDP.

Reutiliza las utilidades del proyecto en vez de reimplementarlas:
    - extraccion.extraer_saldo        -> parseo robusto del saldo (formato es-CO)
    - restricciones.contiene_restriccion -> detección de límites sin tildes
    - pausa.pausa_con_jitter          -> esperas cortas variables (human_delay)

Mantiene la robustez previa (base_url configurable, huella es-CO, movimiento de
mouse, espera post-login, logging por etapa, errores tipados, selectores con
alternancia regex y `.first` para modo estricto) e incluye registro con pausa
manual de reCAPTCHA y detección de límite por la página oficial del usuario.

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

# Pausa (segundos, rango aleatorio) para resolver el reCAPTCHA MANUALMENTE en el
# navegador durante el registro. Ajústalo según el tiempo que necesites.
ESPERA_CAPTCHA_SEG = (40, 70)

# Palabras (específicas de Betplay) que delatan una cuenta limitada. La
# comparación sin tildes/mayúsculas la realiza restricciones.contiene_restriccion.
PALABRAS_LIMITE_BETPLAY = (
    "límite",
    "máximo permitido",
    "excede",
    "no permitido",
)

# --- Punto 6: selectores candidatos (de más específico a más amplio). Se unen
# en una sola lista CSS y se combinan con get_by_text vía .or_().
# 'td.balance-td' es el selector real visto en la captura del usuario. ---
SELECTORES_SALDO = (
    "td.balance-td, #balance, .balance-amount, .user-balance, .saldo, .balance, "
    '[class*="balance"], [data-testid*="balance"]'
)
SELECTORES_VERIFICADA = (
    ".verified-badge, .badge-verified, .status-verified, .status-success, "
    '[class*="verified"], [data-testid*="verified"]'
)

# --- Punto 9: detección de límite leyendo la página OFICIAL de límites del
# usuario (más fiable que simular una apuesta). ---
RUTA_LIMITES = "/menuusuario?optionMenu=1"
RUTA_BONOS = "/menuusuario?optionMenu=4"
# Marcadores literales de un tope diario bajo (señal de cuenta limitada).
# PALABRAS_LIMITE_BETPLAY ya cubre "límite/máximo/...".
MARCADORES_LIMITE = ("10.000.000", "10000000")

# --- Login: selectores y deteccion de credenciales incorrectas ---
SEL_LOGIN_BTN = "text=/Iniciar sesión|Iniciar sesion|Ingresar|Login/i"
SEL_EMAIL = 'input[name*="email" i], input#email, input[placeholder*="correo" i], input[placeholder*="mail" i]'
SEL_PASS = 'input[name*="password" i], input#password, input[placeholder*="contraseña" i]'
SEL_SUBMIT = 'button[type="submit"], button:has-text("Ingresar"), button:has-text("Login")'
TEXTO_LOGIN_FALLIDO = re.compile(
    r"credencial(es)? (incorrect|invalid)|usuario o contrase|datos incorrect|"
    r"contrase\w+ incorrect|inicio de sesion fallido",
    re.IGNORECASE,
)
INTENTOS_LOGIN = 2

# --- Apuestas (Apostar Bono / Apostar Saldo) ---
RUTA_FUTBOL = "/deportes/futbol"
LIGAS_REGEX = r"Liga BetPlay|Primera A|BetPlay Cup|Colombia"
SEL_CUOTA = "button, div"           # se filtra por un patron de cuota (1.85, 2.0, ...)
SEL_MONTO_APUESTA = 'input[placeholder*="Monto" i], input[name*="stake" i], input[type="number"]'


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
        # str(text): tolera valores numéricos (p. ej. Cédula/Teléfono leídos del
        # Excel como int) sin romper el tecleo carácter a carácter.
        for char in str(text):
            await page.keyboard.type(char, delay=random.randint(*delay_range))
            if random.random() < 0.12:
                await human_delay(0.15, 0.45)
        return True
    except ERRORES_PW:
        logger.warning(f"No se pudo escribir en: {selector}")
        return False


async def human_mouse_move(page, steps: int = 8):
    """Movimiento de mouse más natural."""
    for _ in range(steps):
        x = random.randint(100, 1200)
        y = random.randint(100, 700)
        await page.mouse.move(x, y, steps=random.randint(3, 8))
        await human_delay(0.1, 0.4)


async def scroll_humano(page):
    """Scroll natural."""
    await page.evaluate("window.scrollBy(0, document.body.scrollHeight * 0.3)")
    await human_delay(0.8, 2.2)
    await page.evaluate("window.scrollBy(0, -document.body.scrollHeight * 0.15)")


# ==================== REGISTRO COMPLETO (BETPLAY) ====================

async def registrar_cuenta(
    page,
    datos: Dict[str, Any],
    base_url: str = BASE_URL_POR_DEFECTO,
    captcha_waiter: Optional[Callable[[], Awaitable[None]]] = None,
) -> bool:
    """
    Registro completo con los selectores reales de Betplay.

    `datos` admite las claves: Cedula, ExpedicionDD/MM/YYYY, LugarExpedicion,
    NacimientoDD/MM/YYYY, PrimerNombre, PrimerApellido, Telefono, Correo, Password.

    Antes del envío hace una PAUSA MANUAL para que resuelvas el reCAPTCHA a mano
    en el navegador (ver ESPERA_CAPTCHA_SEG). Devuelve True si envió el
    formulario, False ante cualquier fallo.
    """
    try:
        logger.info("Iniciando registro completo...")
        await page.goto(base_url, wait_until="domcontentloaded", timeout=45000)
        await human_delay(3, 6)

        # Boton de registro: selector real de Betplay (.btn-registro) o por texto.
        await page.locator("button.btn-registro").or_(
            page.get_by_text(re.compile(r"Registrarse|Crear cuenta|Registro", re.IGNORECASE))
        ).first.click(timeout=12000)
        await human_delay(3, 5)

        # Tipo de documento (se selecciona por etiqueta visible, no por value).
        await page.select_option(
            'select[name*="tipoDocumento"], select#tipoDocumento',
            label="Cédula de ciudadanía",
        )
        await human_delay(1, 2)

        # Número de identificación (cédula).
        await human_type(
            page,
            'input[name*="numeroIdentificacion"], input#numeroIdentificacion',
            datos.get("Cedula", ""),
        )

        # Fecha de expedición (con valores por defecto si no vienen en datos).
        await human_type(page, 'input[placeholder*="DD"][name*="expedicion"], input[name*="fechaExpedicionDD"]', datos.get("ExpedicionDD", "15"))
        await human_type(page, 'input[placeholder*="MM"][name*="expedicion"], input[name*="fechaExpedicionMM"]', datos.get("ExpedicionMM", "06"))
        await human_type(page, 'input[placeholder*="YYYY"][name*="expedicion"], input[name*="fechaExpedicionYYYY"]', datos.get("ExpedicionYYYY", "1995"))

        await human_type(page, 'input[name*="lugarExpedicion"], input#lugarExpedicion', datos.get("LugarExpedicion", "BOGOTA"))

        # Fecha de nacimiento.
        await human_type(page, 'input[placeholder*="DD"][name*="nacimiento"], input[name*="fechaNacimientoDD"]', datos.get("NacimientoDD", "10"))
        await human_type(page, 'input[placeholder*="MM"][name*="nacimiento"], input[name*="fechaNacimientoMM"]', datos.get("NacimientoMM", "03"))
        await human_type(page, 'input[placeholder*="YYYY"][name*="nacimiento"], input[name*="fechaNacimientoYYYY"]', datos.get("NacimientoYYYY", "1995"))

        await human_type(page, 'input[name*="primerNombre"], input#primerNombre', datos.get("PrimerNombre", ""))
        await human_type(page, 'input[name*="primerApellido"], input#primerApellido', datos.get("PrimerApellido", ""))

        # Contacto.
        await human_type(page, 'input[name*="telefono"], input#telefonoMovil', datos.get("Telefono", ""))
        await human_type(page, 'input[name*="email"], input#correoElectronico, input[placeholder*="orreo"]', datos.get("Correo", ""))

        # Contraseña + confirmación.
        pwd = datos.get("Password", "")
        await human_type(page, 'input[name*="password"], input#contrasena', pwd)
        await human_type(page, 'input[name*="confirmPassword"], input#confirmarContrasena', pwd)

        # PEP (Persona Expuesta Políticamente).
        await page.select_option('select[name*="pep"], select#pep', label="No")

        # Aceptar todos los checkboxes (términos, mayoría de edad, etc.).
        for checkbox in await page.locator('input[type="checkbox"]').all():
            try:
                await checkbox.check()
                await human_delay(0.4, 0.8)
            except ERRORES_PW:
                pass

        # ---------- CAPTCHA MANUAL ----------
        # Betplay usa reCAPTCHA; no lo resolvemos automaticamente. Si el dashboard
        # inyecta un captcha_waiter, esperamos a que el usuario pulse "Continuar";
        # si no, hacemos una pausa fija como respaldo.
        logger.warning("Si aparece un reCAPTCHA, resuelvelo MANUALMENTE en el navegador.")
        if captcha_waiter is not None:
            await captcha_waiter()
        else:
            logger.info(
                f"Esperando ~{ESPERA_CAPTCHA_SEG[0]}-{ESPERA_CAPTCHA_SEG[1]} s para la resolucion manual..."
            )
            await human_delay(*ESPERA_CAPTCHA_SEG)

        # Botón final.
        await page.click('button:has-text("Completar Registro"), button[type="submit"]', timeout=15000)
        await human_delay(6, 10)

        logger.info("Formulario de registro enviado")
        return True

    except ERRORES_PW as e:
        logger.error(f"Error en registro (Playwright): {e}")
        return False
    except Exception as e:  # noqa: BLE001
        logger.error(f"Error inesperado en registro: {e}")
        return False


# ==================== PROCESADOR PRINCIPAL ====================

async def process_user(
    cdp_endpoint: str,
    username: str,
    password: str,
    nombre: str = "",
    verification_code: Optional[str] = None,
    code_provider: Optional[Callable[[], Awaitable[Optional[str]]]] = None,
    base_url: str = BASE_URL_POR_DEFECTO,
    datos: Optional[Dict[str, Any]] = None,
    modo: str = "login",
    confirmar_waiter: Optional[Callable[..., Awaitable[None]]] = None,
    tareas: Optional[set] = None,
    apuesta_cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Se adjunta a un navegador externo (CDP). Con modo="registro" crea primero la
    cuenta (registrar_cuenta usando `datos`); luego inicia sesión, resuelve el
    2FA si aparece, extrae el saldo, verifica el estado y prueba el límite.

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

            # ---------- Registro (opcional) ----------
            if modo == "registro":
                if not await registrar_cuenta(page, datos or {}, base_url, confirmar_waiter):
                    return {
                        "saldo": 0.0,
                        "verificada": "no",
                        "limitada": False,
                        "bono": "desconocido",
                        "apuesta_bono": "n/a",
                        "apuesta_saldo": "n/a",
                        "estado": "fallo_registro",
                        "timestamp": datetime.now().isoformat(),
                    }

            # ---------- Navegación inicial ----------
            logger.info(f"[{etiqueta}] Navegando a {base_url}")
            await page.goto(base_url, wait_until="domcontentloaded", timeout=45000)
            await human_delay(2.5, 5)
            await page.mouse.move(random.randint(100, 800), random.randint(100, 500))
            await human_delay(1, 2.5)

            # ---------- Login (con reintentos + deteccion de credenciales) ----------
            try:
                await page.click(SEL_LOGIN_BTN, timeout=8000)
                await human_delay(2, 4)
            except ERRORES_PW:
                logger.warning(f"[{etiqueta}] No se encontro boton de login visible")

            logueado = False
            for intento in range(1, INTENTOS_LOGIN + 1):
                await _rellenar_login(page, username, password, etiqueta, limpiar=(intento > 1))
                if await _login_fallido(page):
                    logger.warning(
                        f"[{etiqueta}] Credenciales incorrectas (intento {intento}/{INTENTOS_LOGIN})"
                    )
                    await human_delay(1, 2)
                    continue
                logueado = True
                break

            if not logueado:
                logger.error(f"[{etiqueta}] Login fallido: credenciales incorrectas")
                return {
                    "saldo": 0.0, "verificada": "no", "limitada": False, "bono": "n/a",
                    "apuesta_bono": "n/a", "apuesta_saldo": "n/a",
                    "estado": "login_fallido", "timestamp": datetime.now().isoformat(),
                }

            # ---------- 2FA / código de verificación ----------
            # Detectamos el campo DESPUÉS del login: solo en este punto el sitio
            # ya envió el correo con el código, así que es el momento correcto
            # para pedirlo (vía code_provider) en lugar de pre-buscarlo.
            hay_2fa = False
            try:
                await page.locator(
                    'input[placeholder*="código" i], #verification-code, #code, input[name*="code" i]'
                ).first.wait_for(state="visible", timeout=8000)
                hay_2fa = True
            except ERRORES_PW:
                pass  # esta cuenta no pidió 2FA

            if hay_2fa:
                logger.info(f"[{etiqueta}] Campo de verificación 2FA detectado")
                await human_delay(2, 4)
                codigo = await _obtener_codigo_2fa(verification_code, code_provider, etiqueta)
                if codigo:
                    await human_type(
                        page,
                        'input[placeholder*="código" i], #verification-code, #code',
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

            # ---------- Saldo + Verificacion (siempre) ----------
            info = await extraer_info_cuenta(page, etiqueta)

            # ---------- Tareas seleccionadas (hibrido) ----------
            # Por defecto (sin config) corre verificacion de limite y bonos.
            seleccion = tareas if tareas is not None else {"apuesta_maxima", "bonos"}
            limitada = False
            bono = "n/a"
            apuesta_bono = "n/a"
            apuesta_saldo = "n/a"

            if "apuesta_maxima" in seleccion:
                limitada = await probar_limite(page, base_url, etiqueta)
            if "bonos" in seleccion:
                bono = await verificar_bonos(page, base_url, etiqueta)
            if "apostar_bono" in seleccion:
                monto = _calcular_monto(apuesta_cfg, info["saldo"])
                apuesta_bono = await apostar(page, base_url, etiqueta, monto, confirmar_waiter, "bono")
            if "apostar_saldo" in seleccion:
                monto = _calcular_monto(apuesta_cfg, info["saldo"])
                apuesta_saldo = await apostar(page, base_url, etiqueta, monto, confirmar_waiter, "saldo")

            return {
                "saldo": info["saldo"],
                "verificada": info["verificada"],
                "limitada": limitada,
                "bono": bono,
                "apuesta_bono": apuesta_bono,
                "apuesta_saldo": apuesta_saldo,
                # Umbral de negocio: una cuenta con saldo > 500 (COP) se da por buena.
                "estado": "exitosa" if info["saldo"] > 500 else "revisar",
                "timestamp": datetime.now().isoformat(),
            }

    except Exception as e:  # noqa: BLE001  (aislamos el fallo para no tumbar el lote)
        logger.error(f"[{etiqueta}] Error crítico en process_user: {e}")
        return {
            "saldo": 0.0,
            "verificada": "error",
            "limitada": False,
            "bono": "Error bonos",
            "apuesta_bono": "n/a",
            "apuesta_saldo": "n/a",
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


async def extraer_info_cuenta(page, etiqueta: str = "") -> Dict[str, Any]:
    """
    Punto 6: extrae el saldo (parser es-CO) y el estado de verificación, usando
    listas amplias de selectores combinadas con get_by_text vía .or_().

    Devuelve {"saldo": float, "verificada": "si"|"no"}.
    """
    saldo = 0.0
    try:
        saldo_locator = page.locator(SELECTORES_SALDO).or_(
            page.get_by_text(re.compile(r"\$\s*[\d.,]+"))
        ).first
        await saldo_locator.wait_for(state="visible", timeout=8000)
        saldo = extraer_saldo(await saldo_locator.inner_text(timeout=5000))
        logger.info(f"[{etiqueta}] Saldo extraído: ${saldo:,.2f}")
    except ERRORES_PW:
        logger.warning(f"[{etiqueta}] No se pudo extraer el saldo")

    verificada = "no"
    try:
        verificada_loc = page.locator(SELECTORES_VERIFICADA).or_(
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

    return {"saldo": saldo, "verificada": verificada}


async def probar_limite(page, base_url: str, etiqueta: str) -> bool:
    """
    Punto 9: revisa la página OFICIAL de límites del usuario y detecta si la
    cuenta está limitada (texto de límite, vía contiene_restriccion, o un tope
    diario bajo según MARCADORES_LIMITE). Más fiable que simular una apuesta.
    """
    try:
        logger.info(f"[{etiqueta}] Revisando límites oficiales del usuario...")
        await page.goto(f"{base_url}{RUTA_LIMITES}", wait_until="networkidle", timeout=20000)
        await human_delay(3, 6)

        texto = await page.locator("body").inner_text(timeout=10000)

        if contiene_restriccion(texto, PALABRAS_LIMITE_BETPLAY) or any(
            marcador in texto for marcador in MARCADORES_LIMITE
        ):
            logger.info(f"[{etiqueta}] Cuenta LIMITADA detectada (límite diario bajo)")
            return True

        logger.info(f"[{etiqueta}] Sin límites restrictivos aparentes")
        return False
    except ERRORES_PW as e:
        logger.debug(f"[{etiqueta}] Prueba de límite no concluyente: {e}")
        return False


async def verificar_bonos(page, base_url: str, etiqueta: str) -> str:
    """
    Revisa la página de bonos del usuario (RUTA_BONOS). Devuelve 'Tiene Bono',
    'Sin bonos', o 'Error bonos' si no se pudo consultar.
    """
    try:
        logger.info(f"[{etiqueta}] Revisando bonos del usuario...")
        await page.goto(f"{base_url}{RUTA_BONOS}", wait_until="networkidle", timeout=20000)
        await human_delay(3, 5)
        texto = await page.locator("body").inner_text(timeout=10000)
        if "Bono Activo" in texto or "Bono Pendiente" in texto:
            logger.info(f"[{etiqueta}] Bono detectado")
            return "Tiene Bono"
        return "Sin bonos"
    except ERRORES_PW as e:
        logger.debug(f"[{etiqueta}] No se pudo verificar bonos: {e}")
        return "Error bonos"


# ==================== LOGIN: RELLENO + DETECCION DE FALLO ====================

async def _rellenar_login(page, username: str, password: str, etiqueta: str = "", limpiar: bool = False) -> None:
    """Rellena correo+contrasena y envia. Con limpiar=True borra los campos antes (reintento)."""
    if limpiar:
        for sel in (SEL_EMAIL, SEL_PASS):
            try:
                await page.locator(sel).first.fill("")
            except ERRORES_PW:
                pass
    if await human_type(page, SEL_EMAIL, username):
        await human_delay(1, 2)
        await human_type(page, SEL_PASS, password)
        await human_delay(1, 2.5)
        try:
            await page.click(SEL_SUBMIT)
            await human_delay(3, 6)
        except ERRORES_PW as e:
            logger.warning(f"[{etiqueta}] No se pudo enviar el login: {e}")


async def _login_fallido(page) -> bool:
    """True si la pagina muestra un mensaje de credenciales incorrectas."""
    try:
        cuerpo = await page.locator("body").inner_text(timeout=4000)
    except ERRORES_PW:
        return False
    return bool(TEXTO_LOGIN_FALLIDO.search(cuerpo))


# ==================== APUESTAS (preparar y pausar) ====================

def _calcular_monto(apuesta_cfg: Optional[Dict[str, Any]], saldo: float) -> float:
    """
    Calcula el stake segun la config: modo 'fijo' (valor exacto) o 'porcentaje'
    (valor % del saldo leido). Devuelve 0.0 si no hay config valida.
    """
    cfg = apuesta_cfg or {}
    try:
        valor = float(cfg.get("valor", 0) or 0)
    except (ValueError, TypeError):
        return 0.0
    if str(cfg.get("modo", "fijo")).strip().lower() == "porcentaje":
        return round(max(saldo, 0.0) * valor / 100.0, 0)
    return valor


async def apostar(
    page,
    base_url: str,
    etiqueta: str,
    monto: float,
    confirmar_waiter: Optional[Callable[..., Awaitable[None]]] = None,
    tipo: str = "saldo",
) -> str:
    """
    Prepara una apuesta (evento + cuota + monto) y PAUSA para que el usuario de
    el clic final de 'Apostar' (preparar y pausar). No confirma la apuesta.

    Devuelve: 'preparada', 'sin_monto' o 'error'.
    """
    if not monto or monto <= 0:
        logger.warning(f"[{etiqueta}] Apostar {tipo}: monto invalido ({monto}); se omite.")
        return "sin_monto"
    try:
        logger.info(f"[{etiqueta}] Apostar {tipo}: preparando cupon por {monto:,.0f}...")
        await page.goto(f"{base_url}{RUTA_FUTBOL}", wait_until="networkidle", timeout=20000)
        await human_delay(3, 6)

        # Evento popular + una cuota cualquiera (numero con decimales tipo 1.85).
        await page.locator(f"text=/{LIGAS_REGEX}/i").first.click()
        await human_delay(2.5, 5)
        await page.locator(SEL_CUOTA).filter(has_text=re.compile(r"\d\.\d{1,2}")).first.click()
        await human_delay(2, 4)

        # Escribir el monto en el cupon.
        await page.locator(SEL_MONTO_APUESTA).first.fill(str(int(monto)))
        await human_delay(1.5, 3)

        # Preparar y pausar: el usuario confirma manualmente (mismo mecanismo del CAPTCHA).
        logger.warning(f"[{etiqueta}] Apuesta {tipo} preparada por {monto:,.0f}. Revisa y confirma a mano.")
        if confirmar_waiter is not None:
            await confirmar_waiter("apuesta")
        return "preparada"
    except ERRORES_PW as e:
        logger.warning(f"[{etiqueta}] No se pudo preparar la apuesta {tipo}: {e}")
        return "error"
