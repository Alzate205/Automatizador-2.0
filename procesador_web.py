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

import asyncio
import logging
import os
import random
import re
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, Optional

from playwright.async_api import (
    async_playwright,
    TimeoutError as PlaywrightTimeout,
    Error as PlaywrightError,
)

# playwright-stealth: parchea la huella del navegador para evadir detección de
# automatización (navigator.webdriver, etc.). Es opcional: si no está instalado,
# el procesador sigue funcionando sin stealth (solo se registra un aviso).
#
# La API cambió entre versiones: 2.x expone la clase `Stealth` (método
# apply_stealth_async); 1.x exponía la función `stealth_async`. Soportamos ambas
# y dejamos un único callable `aplicar_stealth(page)` para el resto del código.
aplicar_stealth: Optional[Callable[[Any], Awaitable[None]]] = None
try:
    from playwright_stealth import Stealth  # API 2.x

    _stealth = Stealth()

    async def aplicar_stealth(page):  # type: ignore[no-redef]
        await _stealth.apply_stealth_async(page)
except ImportError:
    try:
        from playwright_stealth import stealth_async  # API 1.x

        async def aplicar_stealth(page):  # type: ignore[no-redef]
            await stealth_async(page)
    except ImportError:  # pragma: no cover - depende del entorno
        aplicar_stealth = None

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

# Carpeta donde se guardan los pantallazos cuando un registro falla (para auditar).
CARPETA_CAPTURAS = "capturas"

# Espera activa (ms) por una señal de resultado tras pulsar "Completar Registro".
TIMEOUT_RESULTADO_REGISTRO_MS = 20000

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
# Límite diario NORMAL de Betplay ($10.000.000). Una cuenta con un tope MENOR a
# este está limitada. (Antes el código marcaba 10.000.000 como "limitada", que
# era justo al revés: ese es el límite sano.)
LIMITE_DIARIO_NORMAL = 10_000_000
SEL_LIMITE_DIARIO = (
    "div.limit-item:has(p.limit-label:has-text('Límite Diario')) p.limit-value"
)
# Marcador negativo real de la página de bonos.
MARCADOR_SIN_BONOS = "no tienes bonos"

# --- Login: selectores reales de Betplay (Angular) ---
# El campo de usuario acepta "Usuario / Cédula" (input#userName). Para cuentas
# creadas por el bot, el usuario ES la cédula (ver registro).
SEL_LOGIN_BTN = "text=/Iniciar sesión|Iniciar sesion|Ingresar|Login/i"
SEL_EMAIL = 'input#userName, input[formcontrolname="userName"]'
SEL_PASS = 'input#password[formcontrolname="password"], input[formcontrolname="password"]'
SEL_SUBMIT = 'button#btnLoginPrimary, button.betplaycaptcha:has-text("Ingresar"), button[type="submit"]'
TEXTO_LOGIN_FALLIDO = re.compile(
    r"credencial(es)? (incorrect|invalid)|usuario o contrase|datos incorrect|"
    r"contrase\w+ incorrect|inicio de sesion fallido",
    re.IGNORECASE,
)
INTENTOS_LOGIN = 2

# --- Apuestas (Betplay usa el sportsbook KAMBI, suele correr en un iframe) ---
# Navegación a Deportes desde el home.
SEL_DEPORTES = "a.section-title"            # enlace "Deportes"
SEL_MENU_HAMBURGUESA = "i.fas.fa-bars"      # menú móvil (respaldo)

# Cuotas: los selectores estables son el atributo data-outcome-id y la clase
# plana .original-odds (NO las clases con hash de styled-components, que cambian).
SEL_CUOTA_BTN = "button[data-outcome-id]:has(.original-odds)"
SEL_CUOTA_VALOR = ".original-odds"

# Cupón (betslip) de Kambi: clases 'mod-KambiBC-*' (estables).
SEL_BETSLIP = ".mod-KambiBC-betslip-outcome__content"
SEL_BETSLIP_EVENTO = "a.mod-KambiBC-betslip-outcome__event-link"
SEL_BETSLIP_PICK = ".mod-KambiBC-betslip-outcome__outcome-label"
SEL_BETSLIP_MERCADO = ".mod-KambiBC-betslip-outcome__criteria"
SEL_BETSLIP_CUOTA = ".mod-KambiBC-betslip-outcome__odds"
SEL_MONTO_APUESTA = "input.mod-KambiBC-js-stake-input"

# Para apostar el BONO se buscan cuotas medias-altas (3.0 a 6.0): el rollover del
# bono rinde mejor. Para el saldo real (rango None) se toma la primera disponible.
RANGO_CUOTA_BONO = (3.0, 6.0)
# Cuantas cuotas candidatas inspeccionamos como maximo al buscar el rango.
MAX_CUOTAS_INSPECCIONAR = 60

# Ventana temporal de la apuesta: solo partidos de HOY/MAÑANA en la tarde-noche
# (~8 p. m.). Ajusta el rango de horas a gusto (formato 24h).
APUESTA_SOLO_HOY_MANANA = True
APUESTA_HORA_MIN = 18   # desde las 6:00 p. m.
APUESTA_HORA_MAX = 23   # hasta las 11:00 p. m. (incluye ~8 p. m.)
# Fecha/hora del evento: spans con clase 'EventDate__TimeWrapper' (día y hora van
# en spans SEPARADOS: "Hoy"/"Mañana" + "06:00 p. m."). Se leen todos y se unen.
# Vacío = no se filtra por hora.
SEL_EVENTO_HORA = '[class*="EventDate__TimeWrapper"]'


# ==================== COMPORTAMIENTO HUMANO ====================

async def human_delay(min_sec: float = 0.8, max_sec: float = 3.0) -> None:
    """
    Pausa corta y variable (en segundos) para simular reacción humana.

    Delega en pausa.pausa_con_jitter para no duplicar la lógica de espera:
    el rango [min_sec, max_sec] se traduce a base + jitter.
    """
    jitter_ms = int(max(0.0, max_sec - min_sec) * 1000)
    await pausa_con_jitter(min_sec, jitter_ms=jitter_ms)


async def _esperar_listo(page, selector, timeout_ms: int = 15000):
    """
    Espera a que un campo esté VISIBLE y HABILITADO y devuelve su Locator (o None).

    El formulario de Betplay es PASO A PASO: un campo no se habilita hasta que el
    anterior quedó bien lleno. Por eso, antes de tocar cada campo, esperamos a que
    esté realmente disponible (no solo presente en el DOM). `selector` puede ser un
    string CSS o un Locator ya acotado.
    """
    loc = (page.locator(selector) if isinstance(selector, str) else selector).first
    try:
        await loc.wait_for(state="visible", timeout=timeout_ms)
    except ERRORES_PW:
        return None
    for _ in range(max(1, int(timeout_ms / 300))):
        try:
            if await loc.is_enabled():
                return loc
        except ERRORES_PW:
            pass
        await asyncio.sleep(0.3)
    return None  # visible pero nunca se habilitó (paso anterior incompleto)


async def human_type(page, selector, text, delay_range=(90, 240), reintentos: int = 2) -> bool:
    """
    Escribe el texto carácter a carácter con variabilidad humana (lento, para no
    parecer un bot). Espera a que el campo esté HABILITADO (form paso a paso) y
    reintenta. `selector` puede ser un string CSS o un Locator ya acotado.

    Devuelve True si escribió, False si el campo no estuvo disponible.
    """
    for intento in range(1, reintentos + 1):
        loc = await _esperar_listo(page, selector)
        if loc is None:
            if intento < reintentos:
                await human_delay(0.8, 1.6)
                continue
            logger.warning(f"Campo no disponible para escribir: {selector}")
            return False
        try:
            await loc.scroll_into_view_if_needed(timeout=3000)
            await loc.click()
            await human_delay(0.4, 1.0)
            # str(text): tolera valores numéricos (Cédula/Teléfono leídos como int).
            for char in str(text):
                await page.keyboard.type(char, delay=random.randint(*delay_range))
                if random.random() < 0.15:
                    await human_delay(0.25, 0.7)  # micro-pausas de "pensar"
            await human_delay(0.5, 1.3)  # pausa al terminar el campo (más humano)
            return True
        except ERRORES_PW:
            if intento < reintentos:
                await human_delay(0.8, 1.6)
                continue
            logger.warning(f"No se pudo escribir en: {selector}")
            return False
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

# Validacion post-registro (heuristica). Son marcadores GENERICOS en minusculas
# que se buscan en el texto/URL de la pagina tras enviar el formulario. Afinalos
# con los textos reales que muestre Betplay al completar/rechazar un registro.
INDICADORES_REGISTRO_OK = (
    "registro exitoso", "cuenta creada", "bienvenido", "verifica tu correo",
    "/cuenta", "dashboard", "mi cuenta",
)
INDICADORES_REGISTRO_ERROR = (
    "ya registrado", "correo existe", "correo ya", "se encuentra en uso",
    "cedula ya", "cédula ya", "ya existe", "invalido", "inválido",
    "no se pudo completar", "intentalo mas tarde", "inténtalo más tarde",
)

# Mapa etiqueta -> value del <select formcontrolname="documentType"> de Betplay.
# El value es el ID de backend (estable); la etiqueta visible puede variar.
DOC_TIPO_VALORES = {
    "cedula de ciudadania": "3",
    "cedula de extranjeria": "4",
    "permiso de proteccion temporal": "544",
    "ppt": "544",
}
DOC_TIPO_POR_DEFECTO = "3"  # Cédula de ciudadanía


def _sin_tildes(texto: Any) -> str:
    """minúsculas sin tildes ni espacios extremos (para comparar etiquetas)."""
    import unicodedata

    normal = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in normal if not unicodedata.combining(c)).strip().lower()


def _valor_tipo_doc(datos: Dict[str, Any]) -> str:
    """
    value del tipo de documento. Acepta el texto ('Cédula de ciudadanía'), el
    value directo ('3'/'4'/'544') o vacío (usa el valor por defecto).
    """
    bruto = str(datos.get("TipoDocumento", "") or "").strip()
    if not bruto:
        return DOC_TIPO_POR_DEFECTO
    if bruto in ("3", "4", "544"):
        return bruto
    return DOC_TIPO_VALORES.get(_sin_tildes(bruto), DOC_TIPO_POR_DEFECTO)


# <select formcontrolname="gender">: 1=Masculino, 2=Femenino.
GENERO_VALORES = {
    "masculino": "1", "m": "1", "hombre": "1",
    "femenino": "2", "f": "2", "mujer": "2",
}

# <select formcontrolname="addressType">: value (sigla) por tipo de vía.
TIPO_VIA_VALORES = {
    "avenida calle": "AC", "avenida carrera": "AK", "autopista": "AUT",
    "avenida": "AV", "calle": "CL", "circunvalar": "CRV", "diagonal": "DG",
    "transversal": "TV", "kilometro": "KM", "carrera": "CR", "circular": "CIR",
}
TIPO_VIA_SIGLAS = {"AC", "AK", "AUT", "AV", "CL", "CRV", "DG", "TV", "KM", "CR", "CIR"}

# Etiquetas visibles (para desplegables PERSONALIZADOS donde value != texto).
DOC_TIPO_LABEL = {
    "3": "Cedula de ciudadania", "4": "Cedula de extranjeria",
    "544": "Permiso de proteccion temporal",
}
GENERO_LABEL = {"1": "Masculino", "2": "Femenino"}
_TIPO_VIA_LABEL = {v: k for k, v in TIPO_VIA_VALORES.items()}  # sigla -> nombre


def _label_tipo_via(sigla: str) -> str:
    return _TIPO_VIA_LABEL.get(str(sigla).upper(), "").title()


def _valor_genero(datos: Dict[str, Any]) -> str:
    """value del género. Acepta texto ('Masculino'/'F'), el value ('1'/'2') o vacío."""
    bruto = str(datos.get("Genero", "") or "").strip()
    if bruto in ("1", "2"):
        return bruto
    return GENERO_VALORES.get(_sin_tildes(bruto), "1")  # por defecto Masculino


def _valor_tipo_via(datos: Dict[str, Any]) -> str:
    """value del tipo de vía. Acepta texto ('Calle'), la sigla ('CL') o vacío."""
    bruto = str(datos.get("TipoVia", "") or "").strip()
    if bruto.upper() in TIPO_VIA_SIGLAS:
        return bruto.upper()
    return TIPO_VIA_VALORES.get(_sin_tildes(bruto), "CL")  # por defecto Calle


def _ciudad_lugar_expedicion(valor: Any) -> str:
    """Texto que se TECLEA en el autocompletar: la ciudad, sin el departamento.

    'ARMENIA (QUINDIO)' -> 'ARMENIA'; 'ARMENIA, QUINDIO' -> 'ARMENIA'.
    """
    ciudad = re.split(r"[(,]", str(valor or ""))[0].strip()
    return ciudad or "BOGOTA"


def _claves_lugar_expedicion(valor: Any) -> list:
    """Palabras que la opción del autocompletar debe contener (ciudad + depto).

    'ARMENIA (QUINDIO)' -> ['armenia', 'quindio']; 'BOGOTA' -> ['bogota'].
    Sirve para elegir la opción correcta cuando hay ciudades homónimas.
    """
    return [p for p in re.split(r"[()\s,]+", _sin_tildes(valor)) if p]


def _norm_dia(valor: Any, defecto: str = "") -> str:
    """Día SIN cero a la izquierda: los <option> de expeditionDay usan '1'..'31'."""
    try:
        return str(int(float(str(valor).strip())))
    except (ValueError, TypeError):
        return defecto


def _norm_mes(valor: Any, defecto: str = "") -> str:
    """Mes con DOS dígitos: los <option> de expeditionMonth usan '01'..'12'."""
    try:
        return f"{int(float(str(valor).strip())):02d}"
    except (ValueError, TypeError):
        return defecto


def _norm_anio(valor: Any, defecto: str = "") -> str:
    """Año de 4 dígitos: los <option> de expeditionYear usan '1995', etc."""
    try:
        return str(int(float(str(valor).strip())))
    except (ValueError, TypeError):
        return defecto


MESES_NOMBRE = {
    "01": "enero", "02": "febrero", "03": "marzo", "04": "abril",
    "05": "mayo", "06": "junio", "07": "julio", "08": "agosto",
    "09": "septiembre", "10": "octubre", "11": "noviembre", "12": "diciembre",
}


def _coincide_opcion(texto_opcion: str, objetivos: list) -> bool:
    """True si el texto de la opción coincide con alguno de los objetivos.

    Exacto para valores cortos (días/meses numéricos: '1' no debe casar con '10');
    por inclusión para etiquetas largas ('calle' dentro de 'cl - calle').
    """
    t = _sin_tildes(texto_opcion)
    for o in objetivos:
        o = _sin_tildes(o)
        if not o:
            continue
        if o == t:
            return True
        if len(o) >= 3 and (o in t or t in o):
            return True
    return False


async def _seleccionar_opcion(page, selector: str, valor: str, etiqueta: str = "",
                              textos=None, timeout_ms: int = 15000) -> bool:
    """
    Elige una opción en un desplegable, sea <select> NATIVO o uno PERSONALIZADO
    (Angular Material, PrimeNG, ng-select, etc.).

    1) Nativo: select_option por value y por label.
    2) Personalizado: hace CLIC en el control para abrirlo y CLIC en la opción que
       coincida (por value o por alguna etiqueta de `textos`).

    `valor` es el value de backend (p. ej. '3', '06'); `textos` son las etiquetas
    visibles aceptables (p. ej. ['Cédula de ciudadanía'] o ['06','6','junio']).
    Devuelve True si logró seleccionar.
    """
    if valor is None or str(valor).strip() == "":
        return False
    valor = str(valor).strip()
    textos = [str(t) for t in (textos or []) if str(t).strip()]
    objetivos = [valor] + textos

    # El form es PASO A PASO: esperamos a que el desplegable esté HABILITADO. Si no
    # se habilita, es que un campo anterior no quedó bien lleno; reintentamos poco.
    for intento in range(1, 3):
        ctrl = await _esperar_listo(page, selector, timeout_ms=timeout_ms)
        if ctrl is None:
            if intento < 2:
                await human_delay(0.8, 1.6)
                continue
            logger.warning(f"[{etiqueta}] Desplegable no disponible/habilitado: {selector}")
            return False
        try:
            await ctrl.scroll_into_view_if_needed(timeout=3000)
        except ERRORES_PW:
            pass

        # 1) <select> NATIVO: por value y por cada etiqueta.
        for kw in [{"value": valor}] + [{"label": t} for t in textos]:
            try:
                await page.select_option(selector, **kw)
                await human_delay(0.6, 1.4)
                return True
            except Exception:  # noqa: BLE001  (no es <select> nativo o value inexistente)
                pass

        # 2) PERSONALIZADO: abrir el control y hacer clic en la opción.
        try:
            await ctrl.click()
            await human_delay(0.5, 1.2)
        except ERRORES_PW:
            pass
        contenedores = [
            page.get_by_role("option"),
            page.locator("mat-option, [role='option'], .mat-option, .p-dropdown-item, "
                         "ng-dropdown-panel .ng-option, .ng-option, ul.dropdown-menu li, "
                         "li[role='option'], .select2-results__option, option"),
        ]
        for loc in contenedores:
            try:
                n = await loc.count()
            except Exception:  # noqa: BLE001
                continue
            for i in range(min(n, 80)):
                op = loc.nth(i)
                try:
                    if not await op.is_visible():
                        continue
                    txt = await op.inner_text(timeout=800)
                except Exception:  # noqa: BLE001
                    continue
                if _coincide_opcion(txt, objetivos):
                    try:
                        await op.click(timeout=3000)
                        await human_delay(0.5, 1.2)
                        return True
                    except ERRORES_PW:
                        continue
        # No se encontró la opción en este intento; cerramos y reintentamos.
        if intento < 2:
            try:
                await page.keyboard.press("Escape")
            except ERRORES_PW:
                pass
            await human_delay(0.6, 1.2)

    logger.warning(f"[{etiqueta}] No se pudo seleccionar '{textos or valor}' en {selector}")
    return False


async def _verificar_celular(
    page,
    code_provider: Optional[Callable[[], Awaitable[Optional[str]]]] = None,
    timeout_campo_ms: int = 15000,
) -> bool:
    """
    Maneja la verificación de celular post-registro de Betplay: detecta el campo
    input[formcontrolname="verificationCode"], obtiene el código vía code_provider
    (lector de correo) y lo escribe, luego intenta enviarlo.

    El código llega por SMS y también por correo ("El código para poder
    registrarte es: 771160"); code_provider lo saca del correo con el patrón de
    6 dígitos ya existente. Devuelve True si escribió un código, False si no.
    """
    # Rechazo temprano: "El correo ya se encuentra en uso." (solo botón Aceptar).
    # Si aparece, no habrá paso de código; salimos ya sin esperar el timeout largo.
    try:
        await page.get_by_text(
            re.compile(r"se encuentra en uso", re.IGNORECASE)
        ).first.wait_for(state="visible", timeout=3000)
        logger.warning("Registro rechazado: el correo ya se encuentra en uso.")
        return False
    except ERRORES_PW:
        pass

    try:
        campo = page.locator('input[formcontrolname="verificationCode"]').first
        await campo.wait_for(state="visible", timeout=timeout_campo_ms)
    except ERRORES_PW:
        logger.info("Sin paso de verificación de celular (el campo no apareció).")
        return False

    logger.info("Verificación de celular detectada; solicitando código por correo...")
    if code_provider is None:
        logger.warning(
            "No hay proveedor de código (¿ClaveCorreo vacía?); "
            "escribe el código MANUALMENTE en el navegador."
        )
        return False

    codigo = None
    try:
        codigo = await code_provider()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"El proveedor de código de registro falló: {e}")

    if not codigo:
        logger.warning("No se pudo obtener el código de verificación de registro.")
        return False

    await human_type(page, 'input[formcontrolname="verificationCode"]', codigo)
    await human_delay(1, 2)

    # Enviar el código: botón real de Betplay (input[type=submit] value="Validar").
    # Si no está, probamos por rol/texto y, en último caso, Enter.
    try:
        await page.locator('input[type="submit"][value="Validar"]').first.click(timeout=6000)
    except ERRORES_PW:
        try:
            await page.get_by_role(
                "button",
                name=re.compile(r"Validar|Verificar|Confirmar|Continuar|Completar", re.IGNORECASE),
            ).first.click(timeout=6000)
        except ERRORES_PW:
            try:
                await page.keyboard.press("Enter")
            except ERRORES_PW:
                pass
    await human_delay(4, 7)
    logger.info(f"Código de verificación enviado: {codigo}")
    return True


# Patrón de contraseña que EXIGE Betplay (mayúscula + dígito + un signo .;, y solo
# esos caracteres). Igual al ng-pattern del campo 'password' del registro.
PATRON_PASSWORD_BETPLAY = re.compile(r"^(?=.*[A-Z])(?=.*\d)(?=.*[.;,])[A-Za-z\d.;,]+$")


def _validar_datos_registro(datos: Dict[str, Any]) -> tuple:
    """
    Verifica los datos MÍNIMOS de un registro ANTES de tocar el formulario, para no
    gastar un intento (captcha + verificación por SMS/correo) en una fila incompleta
    o con una contraseña que Betplay va a rechazar. Devuelve (ok: bool, mensaje).
    """
    obligatorios = ("Cedula", "PrimerNombre", "PrimerApellido", "Correo", "Telefono", "Password")
    faltantes = [c for c in obligatorios if not str(datos.get(c, "") or "").strip()]
    if faltantes:
        return False, f"Faltan datos obligatorios: {', '.join(faltantes)}"
    correo = str(datos.get("Correo", ""))
    if "@" not in correo or "." not in correo:
        return False, f"Correo con formato inválido: {correo!r}"
    pwd = str(datos.get("Password", ""))
    if not PATRON_PASSWORD_BETPLAY.match(pwd):
        return False, (
            "La contraseña no cumple el patrón de Betplay (mayúscula + dígito + un "
            "signo . ; , y solo esos caracteres, sin espacios). Ej válido: 'Betplay2026.'"
        )
    return True, "ok"


def _partir_dos(principal, secundario) -> tuple:
    """
    Reparte un nombre/apellido en (primero, segundo) SOLO si hace falta.

    Si `secundario` ya trae valor, se respeta. Si viene vacío y `principal` trae
    dos o más palabras (p. ej. "Perez Gomez"), se toma la última como segundo
    ("Perez", "Gomez"). Sirve para llenar firstName2/lastName2 "cuando sea
    necesario" sin obligar a tener columnas separadas.
    """
    principal = str(principal or "").strip()
    secundario = str(secundario or "").strip()
    if secundario or " " not in principal:
        return principal, secundario
    partes = principal.split()
    return " ".join(partes[:-1]), partes[-1]


async def _elegir_lugar_expedicion(page, valor: Any, etq: str) -> bool:
    """
    Llena el AUTOCOMPLETAR de "Lugar de expedición": escribe la ciudad, espera la
    lista y hace clic en la opción correcta.

    Hay ciudades homónimas (p. ej. ARMENIA en Quindío y en Antioquia). Para elegir
    bien, pon en LugarExpedicion el texto con el departamento como aparece en la
    lista: 'ARMENIA (QUINDIO)'. Si solo pones la ciudad y hay varias opciones, se
    toma la primera que coincida (con aviso). Devuelve True si hizo clic.
    """
    campo = 'input[formcontrolname="expeditionPlace"]'
    ciudad = _ciudad_lugar_expedicion(valor)
    claves = _claves_lugar_expedicion(valor)  # ['armenia','quindio'] o ['bogota']

    # El desplegable REAL de Betplay es <div class="suggestion-box"> con hijos
    # <div class="suggestion"> ARMENIA (QUINDIO) </div>. Es lo que confirmó el HTML
    # en vivo, así que lo atacamos con prioridad. Clave: comparación SIN TILDES y en
    # MINÚSCULAS (las opciones vienen en MAYÚSCULA; los datos pueden venir mezclados,
    # por eso get_by_text —sensible a mayúsculas— no es fiable aquí).
    #
    # Es PASO A PASO: si no se elige de la lista, la fecha de nacimiento (el siguiente
    # <select>) queda DESHABILITADA. Reintentamos tecleando por si la lista no cargó.
    selectores_sugerencia = (
        ".suggestion-box .suggestion, [appsuggestedsearch] .suggestion, .suggestion, "
        "mat-option, [role='option'], .mat-option, .p-dropdown-item, .ng-option, "
        "li[role='option'], .autocomplete-option, ngb-typeahead-window button, "
        ".dropdown-item, [class*='suggestion'], [class*='option'], [class*='result']"
    )

    for intento in range(1, 4):
        # Limpiamos por si un intento previo dejó texto (evita "ARMENIAARMENIA").
        try:
            await page.fill(campo, "")
        except ERRORES_PW:
            pass
        await human_type(page, campo, ciudad)
        await human_delay(1.4, 2.6)  # deja cargar el desplegable

        loc = page.locator(selectores_sugerencia)
        try:
            n = await loc.count()
        except Exception:  # noqa: BLE001
            n = 0

        exacta = None
        solo_ciudad = None
        for i in range(min(n, 60)):
            op = loc.nth(i)
            try:
                if not await op.is_visible():
                    continue
                txt = _sin_tildes(await op.inner_text(timeout=800))
            except Exception:  # noqa: BLE001
                continue
            if not txt:
                continue
            if claves and all(k in txt for k in claves):
                exacta = op
                break
            if claves and claves[0] in txt and solo_ciudad is None:
                solo_ciudad = op

        # Si hay homónimos y no llegó el departamento, NO adivinamos (evita elegir la
        # ciudad equivocada); solo tomamos "solo ciudad" cuando no hay ambigüedad.
        elegida = exacta if exacta is not None else (solo_ciudad if len(claves) <= 1 else None)
        if elegida is not None:
            try:
                await elegida.scroll_into_view_if_needed(timeout=1500)
                await elegida.click(timeout=4000)
                await human_delay(0.6, 1.2)
                if exacta is None:
                    logger.warning(
                        f"[{etq}] Lugar de expedicion AMBIGUO ('{valor}'): sin "
                        "departamento; se tomo la primera opcion. Usa 'CIUDAD (DEPTO)'."
                    )
                else:
                    logger.info(f"[{etq}] Lugar de expedicion elegido: {valor}")
                return True
            except ERRORES_PW:
                pass

        if intento < 3:
            logger.info(f"[{etq}] Autocompletar de lugar aun sin opciones; reintento {intento}.")
            await human_delay(0.6, 1.2)

    logger.warning(
        f"[{etq}] No se pudo elegir '{valor}' del autocompletar de lugar de "
        "expedicion (¿cambió la lista o el texto no coincide?); se deja el texto tecleado."
    )
    return False


async def _click_boton_registro(page, etq: str) -> bool:
    """
    Hace clic en "Registrarse" de la home de Betplay de forma robusta.

    En la práctica hay variantes del botón (móvil/escritorio) y la primera que
    resuelve el selector puede estar OCULTA (Playwright falla con "element is not
    visible"). Aquí probamos varios selectores prefiriendo los VISIBLES, con
    scroll hacia el elemento y, como último recurso, un clic forzado.
    """
    selectores = [
        "button#register:visible",
        "button.btn-registro:visible",
        "a#register:visible",
        "button:has-text('Registrarse'):visible",
        "a:has-text('Registrarse'):visible",
        "button:has-text('Crear cuenta'):visible",
    ]
    for sel in selectores:
        loc = page.locator(sel).first
        try:
            await loc.wait_for(state="visible", timeout=3000)
        except ERRORES_PW:
            continue
        try:
            await loc.scroll_into_view_if_needed(timeout=2000)
        except ERRORES_PW:
            pass
        try:
            await loc.click(timeout=5000)
            logger.info(f"[{etq}] Click en 'Registrarse' ({sel}).")
            return True
        except ERRORES_PW:
            continue

    # Respaldo por rol accesible (button o link).
    for rol in ("button", "link"):
        try:
            await page.get_by_role(rol, name=re.compile(r"Registr", re.I)).first.click(timeout=4000)
            logger.info(f"[{etq}] Click en 'Registrarse' (rol {rol}).")
            return True
        except ERRORES_PW:
            continue

    # Respaldo por TEXTO EXACTO visible (cualquier etiqueta clickeable).
    try:
        loc = page.get_by_text(re.compile(r"^\s*Registrarse\s*$", re.I))
        n = await loc.count()
        for i in range(min(n, 10)):
            el = loc.nth(i)
            try:
                if not await el.is_visible():
                    continue
                await el.scroll_into_view_if_needed(timeout=2000)
                await el.click(timeout=4000)
                logger.info(f"[{etq}] Click en 'Registrarse' (texto exacto visible).")
                return True
            except ERRORES_PW:
                continue
    except ERRORES_PW:
        pass

    # Último recurso: clic FORZADO aunque se reporte 'no visible'.
    for sel in ("button#register", "button.btn-registro"):
        try:
            await page.locator(sel).first.click(force=True, timeout=4000)
            logger.warning(f"[{etq}] Click FORZADO en 'Registrarse' ({sel}).")
            return True
        except ERRORES_PW:
            continue
    return False


async def _captura_fallo(page, etiqueta: str, motivo: str = "") -> str:
    """
    Guarda un pantallazo del estado actual en CARPETA_CAPTURAS cuando un registro
    falla. Defensivo: ante cualquier problema solo avisa y devuelve "".
    """
    try:
        os.makedirs(CARPETA_CAPTURAS, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        seguro = re.sub(r"[^\w.-]+", "_", str(etiqueta))[:40] or "cuenta"
        ruta = os.path.join(CARPETA_CAPTURAS, f"registro_FALLO_{seguro}_{ts}.png")
        await page.screenshot(path=ruta, full_page=True)
        logger.warning(f"Captura de fallo guardada: {ruta}"
                       + (f" ({motivo})" if motivo else ""))
        return ruta
    except Exception as e:  # noqa: BLE001
        logger.warning(f"No se pudo guardar la captura de fallo: {e}")
        return ""


async def _esperar_resultado_registro(page, timeout_ms: int = TIMEOUT_RESULTADO_REGISTRO_MS) -> str:
    """
    Tras enviar el formulario, espera activamente la PRIMERA señal entre:
    texto de error, campo de código de verificación, o texto de éxito.

    Devuelve "error" | "codigo" | "ok" | "timeout". Así el resultado se detecta
    apenas aparece (en vez de una pausa fija) y un registro sin ninguna señal se
    puede marcar como fallo en lugar de quedar "incierto".
    """
    async def _texto(indicadores):
        patron = re.compile("|".join(re.escape(i) for i in indicadores), re.IGNORECASE)
        await page.get_by_text(patron).first.wait_for(state="visible", timeout=timeout_ms)

    async def _campo_codigo():
        await page.locator('input[formcontrolname="verificationCode"]').first.wait_for(
            state="visible", timeout=timeout_ms)

    async def _etiquetado(clave, coro):
        await coro
        return clave

    tareas = [
        asyncio.ensure_future(_etiquetado("error", _texto(INDICADORES_REGISTRO_ERROR))),
        asyncio.ensure_future(_etiquetado("codigo", _campo_codigo())),
        asyncio.ensure_future(_etiquetado("ok", _texto(INDICADORES_REGISTRO_OK))),
    ]
    encontrados = set()
    try:
        done, _pending = await asyncio.wait(
            tareas, timeout=timeout_ms / 1000 + 2, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            if not t.cancelled() and t.exception() is None:
                encontrados.add(t.result())
    finally:
        for t in tareas:
            if not t.done():
                t.cancel()
        await asyncio.gather(*tareas, return_exceptions=True)

    for clave in ("error", "codigo", "ok"):  # prioridad si coinciden varias
        if clave in encontrados:
            return clave
    return "timeout"


async def _abortar_paso(page, etq: str, paso: str) -> Dict[str, Any]:
    """Detiene el registro cuando un PASO obligatorio no se completó.

    Como el formulario es paso a paso, seguir es inútil (el siguiente campo no se
    habilita). Guarda captura y devuelve el resultado de error indicando el paso.
    """
    await _captura_fallo(page, etq, f"paso no completado: {paso}")
    msg = (f"Paso '{paso}' no se pudo completar. El formulario es paso a paso: si un "
           "campo no queda bien lleno, el siguiente no se habilita.")
    logger.error(f"[{etq}] {msg}")
    return {"ok": False, "estado": "error_registro", "mensaje": msg}


async def registrar_cuenta(
    page,
    datos: Dict[str, Any],
    base_url: str = BASE_URL_POR_DEFECTO,
    captcha_waiter: Optional[Callable[[], Awaitable[None]]] = None,
    code_provider: Optional[Callable[[], Awaitable[Optional[str]]]] = None,
) -> Dict[str, Any]:
    """
    Registro completo con los selectores reales de Betplay.

    `datos` admite las claves: TipoDocumento, Cedula, ExpedicionDD/MM/YYYY,
    LugarExpedicion, NacimientoDD/MM/YYYY, PrimerNombre, SegundoNombre,
    PrimerApellido, SegundoApellido, Genero, Telefono, Correo, TipoVia,
    Direccion1/2/3, Ciudad, Password. Las opcionales (segundo nombre/apellido) se
    omiten si vienen vacías; el resto usa un valor por defecto sensato.

    Antes del envío hace una PAUSA MANUAL para que resuelvas el reCAPTCHA a mano
    en el navegador (ver ESPERA_CAPTCHA_SEG). Tras enviar el formulario hace una
    validacion post-registro heuristica.

    Devuelve un dict {"ok": bool, "estado": str, "mensaje": str}, con estado en
    {"registro_ok", "registro_rechazado", "registro_incierto", "error_registro"}.
    """
    try:
        logger.info("Iniciando registro completo...")
        etq = str(datos.get("Correo", "") or datos.get("PrimerNombre", "") or "registro")

        # Validación previa: si faltan datos o la contraseña no cumple, NO tocamos el
        # formulario (evita gastar el intento y la verificación por SMS/correo).
        ok_datos, msg_datos = _validar_datos_registro(datos)
        if not ok_datos:
            logger.error(f"[{etq}] Registro OMITIDO por datos inválidos: {msg_datos}")
            return {"ok": False, "estado": "error_registro", "mensaje": msg_datos}

        await page.goto(base_url, wait_until="domcontentloaded", timeout=45000)
        await human_delay(3, 6)

        # Boton de registro: robusto ante variantes ocultas (movil/escritorio).
        if not await _click_boton_registro(page, etq):
            await _captura_fallo(page, etq, "no se pudo abrir el registro (boton Registrarse)")
            return {"ok": False, "estado": "error_registro",
                    "mensaje": "No se pudo hacer clic en 'Registrarse' (boton no visible)"}
        await human_delay(3, 5)

        # A partir de aquí, cada campo es un PASO: si uno falla, el siguiente no se
        # habilita, así que nos detenemos ahí con un mensaje claro (no seguimos a lo
        # loco). Los pasos opcionales (segundo nombre/apellido) no detienen.

        # 1) Tipo de documento (SIEMPRE se selecciona, aunque sea el default).
        val_doc = _valor_tipo_doc(datos)
        if not await _seleccionar_opcion(
            page, 'select[formcontrolname="documentType"]', val_doc, etq,
            textos=[DOC_TIPO_LABEL.get(val_doc, "Cedula de ciudadania"),
                    str(datos.get("TipoDocumento", ""))],
        ):
            return await _abortar_paso(page, etq, "Tipo de documento")
        await human_delay(1, 2)

        # 2) Número de identificación (cédula).
        if not await human_type(page, 'input[formcontrolname="documentNumber"]', datos.get("Cedula", "")):
            return await _abortar_paso(page, etq, "Número de identificación (cédula)")

        # 3) Fecha de expedición (día / mes / año).
        exp_dd = _norm_dia(datos.get("ExpedicionDD"), "15")
        exp_mm = _norm_mes(datos.get("ExpedicionMM"), "06")
        exp_yy = _norm_anio(datos.get("ExpedicionYYYY"), "1995")
        if not await _seleccionar_opcion(page, 'select[formcontrolname="expeditionDay"]', exp_dd, etq, textos=[exp_dd]):
            return await _abortar_paso(page, etq, "Fecha de expedición (día)")
        if not await _seleccionar_opcion(page, 'select[formcontrolname="expeditionMonth"]', exp_mm, etq,
                                         textos=[exp_mm, str(int(exp_mm)), MESES_NOMBRE.get(exp_mm, "")]):
            return await _abortar_paso(page, etq, "Fecha de expedición (mes)")
        if not await _seleccionar_opcion(page, 'select[formcontrolname="expeditionYear"]', exp_yy, etq, textos=[exp_yy]):
            return await _abortar_paso(page, etq, "Fecha de expedición (año)")

        # 4) Lugar de expedición (autocompletar de homónimos).
        if not await _elegir_lugar_expedicion(page, datos.get("LugarExpedicion", "BOGOTA"), etq):
            return await _abortar_paso(page, etq, "Lugar de expedición")

        # 5) Fecha de nacimiento (día / mes / año).
        nac_dd = _norm_dia(datos.get("NacimientoDD"), "10")
        nac_mm = _norm_mes(datos.get("NacimientoMM"), "03")
        nac_yy = _norm_anio(datos.get("NacimientoYYYY"), "1995")
        if not await _seleccionar_opcion(page, 'select[formcontrolname="bornDay"]', nac_dd, etq, textos=[nac_dd]):
            return await _abortar_paso(page, etq, "Fecha de nacimiento (día)")
        if not await _seleccionar_opcion(page, 'select[formcontrolname="bornMonth"]', nac_mm, etq,
                                         textos=[nac_mm, str(int(nac_mm)), MESES_NOMBRE.get(nac_mm, "")]):
            return await _abortar_paso(page, etq, "Fecha de nacimiento (mes)")
        if not await _seleccionar_opcion(page, 'select[formcontrolname="bornYear"]', nac_yy, etq, textos=[nac_yy]):
            return await _abortar_paso(page, etq, "Fecha de nacimiento (año)")

        # 6) Nombres (segundo nombre es OPCIONAL, no detiene).
        primer_nombre, segundo_nombre = _partir_dos(
            datos.get("PrimerNombre", ""), datos.get("SegundoNombre", ""))
        if not await human_type(page, 'input[formcontrolname="firstName"]', primer_nombre):
            return await _abortar_paso(page, etq, "Primer nombre")
        if segundo_nombre:
            await human_type(page, 'input[formcontrolname="firstName2"]', segundo_nombre)

        # 7) Apellidos (segundo apellido OPCIONAL).
        primer_apellido, segundo_apellido = _partir_dos(
            datos.get("PrimerApellido", ""), datos.get("SegundoApellido", ""))
        if not await human_type(page, 'input[formcontrolname="lastName"]', primer_apellido):
            return await _abortar_paso(page, etq, "Primer apellido")
        if segundo_apellido:
            await human_type(page, 'input[formcontrolname="lastName2"]', segundo_apellido)

        # 8) Nacionalidad: suele venir PRE-LLENADA con COLOMBIA (campo fijo, no un
        #    <select>). Intento seleccionarla por si en algún caso es desplegable,
        #    pero NO detengo el registro si no aplica (ya está puesta). Espera corta
        #    para no perder tiempo si el campo no existe como select.
        if not await _seleccionar_opcion(
            page,
            'select[formcontrolname="nationality"], select[formcontrolname="nacionalidad"], '
            'select[formcontrolname="country"], select[formcontrolname="pais"]',
            "COLOMBIA", etq, textos=["COLOMBIA", "Colombia"], timeout_ms=4000,
        ):
            logger.info(f"[{etq}] Nacionalidad no es un select o ya está puesta (COLOMBIA); se continúa.")

        # 9) Género.
        val_gen = _valor_genero(datos)
        if not await _seleccionar_opcion(page, 'select[formcontrolname="gender"]', val_gen, etq,
                                         textos=[GENERO_LABEL.get(val_gen, ""), str(datos.get("Genero", ""))]):
            return await _abortar_paso(page, etq, "Género")

        # 10) Contacto: teléfono + correo.
        if not await human_type(page, 'input[formcontrolname="mobilePhoneNumber"]', datos.get("Telefono", "")):
            return await _abortar_paso(page, etq, "Teléfono móvil")
        if not await human_type(page, 'input[formcontrolname="email"]', datos.get("Correo", "")):
            return await _abortar_paso(page, etq, "Correo electrónico")

        # 11) Dirección: tipo de vía + tres campos + municipio.
        val_via = _valor_tipo_via(datos)
        if not await _seleccionar_opcion(page, 'select[formcontrolname="addressType"]', val_via, etq,
                                         textos=[str(datos.get("TipoVia", "")), _label_tipo_via(val_via)]):
            return await _abortar_paso(page, etq, "Dirección (tipo de vía)")
        if not await human_type(page, 'input[formcontrolname="address1"]', datos.get("Direccion1", "26D")):
            return await _abortar_paso(page, etq, "Dirección (parte 1)")
        if not await human_type(page, 'input[formcontrolname="address2"]', datos.get("Direccion2", "57D")):
            return await _abortar_paso(page, etq, "Dirección (parte 2)")
        if not await human_type(page, 'input[formcontrolname="address3"]', datos.get("Direccion3", "87")):
            return await _abortar_paso(page, etq, "Dirección (parte 3)")
        if not await human_type(page, 'input[formcontrolname="cityAddress"]', datos.get("Ciudad", "BOGOTA")):
            return await _abortar_paso(page, etq, "Municipio")

        # Contraseña + confirmación. OJO: hay DOS campos 'password' en la página (el
        # login del header y el del registro); acotamos al FORMULARIO DE REGISTRO
        # (el que contiene cnfPassword) para no escribir en el login por error.
        # Betplay exige mayúscula, dígito y un signo [.;,] (ej. "Betplay2026.").
        pwd = datos.get("Password", "")
        reg_form = page.locator('form:has(input[formcontrolname="cnfPassword"])')
        if await reg_form.count():
            campo_pass = reg_form.first.locator('input[formcontrolname="password"]')
            campo_cnf = reg_form.first.locator('input[formcontrolname="cnfPassword"]')
        else:
            # Respaldo: el password del registro es el ÚLTIMO (el del login va primero).
            campo_pass = page.locator('input[formcontrolname="password"]').last
            campo_cnf = page.locator('input[formcontrolname="cnfPassword"]').last
        # La contraseña también es un PASO: si el campo está deshabilitado, es que
        # un campo anterior no quedó válido. Detenemos con captura (que muestra el
        # formulario y revela el campo culpable) en vez de seguir a un captcha
        # fantasma con el formulario incompleto.
        if not await human_type(page, campo_pass, pwd):
            return await _abortar_paso(page, etq, "Contraseña (¿un campo anterior quedó inválido?)")
        if not await human_type(page, campo_cnf, pwd):
            return await _abortar_paso(page, etq, "Confirmar contraseña")

        # Interdicto / Ludopatía y PEP: a "No" (value 2) por defecto.
        await _seleccionar_opcion(page, 'select[formcontrolname="ludopath"]', "2", etq, textos=["No"])
        await _seleccionar_opcion(page, 'select[formcontrolname="pep"]', "2", etq, textos=["No"])

        # Checkboxes (tratamiento de datos, promociones, términos, origen de fondos).
        # Son checkboxes Angular con estilo propio: si el click normal falla por
        # actionability, reintentamos con force.
        for checkbox in await page.locator('input[type="checkbox"]').all():
            try:
                if not await checkbox.is_checked():
                    await checkbox.check(timeout=4000)
            except ERRORES_PW:
                try:
                    await checkbox.check(force=True, timeout=4000)
                except ERRORES_PW:
                    pass
            await human_delay(0.3, 0.7)

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

        # Botón final: button.betplaycaptcha "Completar Registro" (se habilita tras
        # resolver el reCAPTCHA manualmente).
        await page.click(
            'button.betplaycaptcha:has-text("Completar Registro"), '
            'button:has-text("Completar Registro"), button[type="submit"]',
            timeout=15000,
        )
        await human_delay(3, 5)
        logger.info("Formulario de registro enviado")

        # ---------- ESPERA ACTIVA DEL RESULTADO ----------
        # Tras "Completar Registro" esperamos la PRIMERA señal entre: texto de
        # error, campo de código de verificación, o texto de éxito. Si no aparece
        # ninguna dentro del timeout, se marca como fallo (no como "incierto").
        senal = await _esperar_resultado_registro(page)

        # DIAGNÓSTICO: registra en bot.log la URL y el texto REAL que muestra
        # Betplay al decidir. Sirve para afinar INDICADORES_REGISTRO_OK/ERROR con
        # las palabras exactas del sitio (revisar estas líneas tras una corrida).
        try:
            _diag = (await page.locator("body").inner_text(timeout=4000)).strip()
            _diag = re.sub(r"\s+", " ", _diag)
        except ERRORES_PW:
            _diag = ""
        logger.info(f"[DIAG registro] senal={senal} | url={page.url}")
        logger.info(f"[DIAG registro] texto en pantalla (primeros 500): {_diag[:500]!r}")

        if senal == "error":
            await _captura_fallo(page, etq, "indicador de error tras enviar")
            logger.warning("Registro RECHAZADO: indicador de error detectado en la pagina.")
            return {"ok": False, "estado": "registro_rechazado",
                    "mensaje": "Error detectado en la pagina tras enviar el registro"}

        if senal == "codigo":
            # Betplay pide el codigo (SMS/correo). Lo resolvemos con el proveedor
            # (lector de correo o codigo manual del panel).
            codigo_enviado = await _verificar_celular(page, code_provider)
            if codigo_enviado:
                logger.info("Registro OK: código de verificación de celular validado.")
                return {"ok": True, "estado": "registro_ok",
                        "mensaje": "Registro completado (código de celular validado)"}
            await _captura_fallo(page, etq, "campo de codigo presente pero sin completar")
            logger.warning("Campo de código presente pero no se completó; queda incierto.")
            return {"ok": True, "estado": "registro_incierto",
                    "mensaje": "Campo de código presente; no se completó (revisar manualmente)"}

        if senal == "ok":
            logger.info("Registro detectado como EXITOSO.")
            return {"ok": True, "estado": "registro_ok", "mensaje": "Registro completado"}

        # senal == "timeout": red de seguridad -> una última lectura del texto por
        # si el indicador no matcheó como elemento visible; si nada, es fallo.
        try:
            cuerpo = (await page.locator("body").inner_text(timeout=5000)).lower()
        except ERRORES_PW:
            cuerpo = ""
        if any(ind in cuerpo for ind in INDICADORES_REGISTRO_OK):
            logger.info("Registro EXITOSO (detectado en el texto final).")
            return {"ok": True, "estado": "registro_ok", "mensaje": "Registro completado"}
        if any(ind in cuerpo for ind in INDICADORES_REGISTRO_ERROR):
            await _captura_fallo(page, etq, "error en texto final")
            logger.warning("Registro RECHAZADO: error detectado en el texto final.")
            return {"ok": False, "estado": "registro_rechazado",
                    "mensaje": "Error detectado en la pagina tras enviar el registro"}
        await _captura_fallo(page, etq, "sin confirmacion de exito (timeout)")
        logger.warning("Registro SIN confirmacion de exito tras 'Completar Registro'; marcado como RECHAZADO.")
        return {"ok": False, "estado": "registro_rechazado",
                "mensaje": "Sin confirmacion de exito tras Completar Registro (timeout)"}

    except ERRORES_PW as e:
        logger.error(f"Error en registro (Playwright): {e}")
        await _captura_fallo(page, etq, "excepcion de Playwright")
        return {"ok": False, "estado": "error_registro", "mensaje": str(e)}
    except Exception as e:  # noqa: BLE001
        logger.error(f"Error inesperado en registro: {e}")
        await _captura_fallo(page, etq, "excepcion inesperada")
        return {"ok": False, "estado": "error_registro", "mensaje": str(e)}


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
    # Estado del registro (sobrevive al login para poder auditarlo). "n/a" en modo login.
    registro_estado = "n/a"

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

            # Aplicar stealth a la página (si el paquete está disponible) para
            # reducir la huella de automatización antes de navegar.
            if aplicar_stealth is not None:
                try:
                    await aplicar_stealth(page)
                    logger.info(f"[{etiqueta}] Stealth aplicado a la página")
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[{etiqueta}] No se pudo aplicar stealth: {e}")
            else:
                logger.debug(
                    "playwright-stealth no instalado; se continúa sin stealth "
                    "(pip install playwright-stealth)"
                )

            # ---------- Registro (opcional) ----------
            if modo == "registro":
                reg = await registrar_cuenta(page, datos or {}, base_url, confirmar_waiter, code_provider)
                registro_estado = reg.get("estado", "error_registro")
                logger.info(
                    f"[{etiqueta}] Registro -> estado={registro_estado} "
                    f"({reg.get('mensaje')})"
                )
                # Solo abortamos si el registro NO fue ok (rechazado o error). Si
                # quedo 'registro_incierto' (ok=True) seguimos al login para confirmar.
                if not reg.get("ok"):
                    return {
                        "saldo": 0.0,
                        "verificada": "no",
                        "limitada": False,
                        "bono": "desconocido",
                        "apuesta_bono": "n/a",
                        "apuesta_saldo": "n/a",
                        "registro": registro_estado,
                        "estado": registro_estado,
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
            sel_codigo = (
                'input[formcontrolname="verificationCode"], '
                'input[placeholder*="código" i], #verification-code, #code, input[name*="code" i]'
            )
            try:
                await page.locator(sel_codigo).first.wait_for(state="visible", timeout=8000)
                hay_2fa = True
            except ERRORES_PW:
                pass  # esta cuenta no pidió 2FA

            if hay_2fa:
                logger.info(f"[{etiqueta}] Campo de verificación 2FA detectado")
                await human_delay(2, 4)
                codigo = await _obtener_codigo_2fa(verification_code, code_provider, etiqueta)
                if codigo:
                    await human_type(page, sel_codigo, codigo)
                    # Enviar: botón "Validar" real de Betplay o Enter como respaldo.
                    try:
                        await page.locator('input[type="submit"][value="Validar"]').first.click(timeout=5000)
                    except ERRORES_PW:
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

            limite_revisado = False
            if "apuesta_maxima" in seleccion:
                limitada = await probar_limite(page, base_url, etiqueta)
                limite_revisado = True
            if "bonos" in seleccion:
                bono = await verificar_bonos(page, base_url, etiqueta)

            # Verificación derivada del límite: si la cuenta NO está limitada, se
            # considera verificada. Si no revisamos el límite, usamos la insignia.
            if limite_revisado:
                verificada = "no" if limitada else "si"
            else:
                verificada = info["verificada"]
            if "apostar_bono" in seleccion:
                # Apostamos el bono SOLO en cuentas que efectivamente tienen bono.
                # Si la tarea 'bonos' no corrio antes, lo verificamos aqui mismo.
                if bono == "n/a":
                    bono = await verificar_bonos(page, base_url, etiqueta)
                if bono == "Tiene Bono":
                    monto = _calcular_monto(apuesta_cfg, info["saldo"])
                    apuesta_bono = await apostar(page, base_url, etiqueta, monto, confirmar_waiter, "bono")
                else:
                    logger.info(f"[{etiqueta}] Sin bono activo; se omite apostar el bono.")
                    apuesta_bono = "sin_bono"
            if "apostar_saldo" in seleccion:
                monto = _calcular_monto(apuesta_cfg, info["saldo"])
                apuesta_saldo = await apostar(page, base_url, etiqueta, monto, confirmar_waiter, "saldo")

            return {
                "saldo": info["saldo"],
                "saldo_retirable": info.get("saldo_retirable", 0.0),
                "verificada": verificada,
                "limitada": limitada,
                "bono": bono,
                "apuesta_bono": apuesta_bono,
                "apuesta_saldo": apuesta_saldo,
                "registro": registro_estado,
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
            "registro": registro_estado,
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
    Extrae el saldo TOTAL (td.balance-td), el saldo RETIRABLE (el <td> hermano
    inmediato) y el estado de verificación.

    En la tabla de saldo de Betplay las celdas van: total (td.balance-td),
    retirable, bono activo, bono pendiente. El retirable es "plata real".

    Devuelve {"saldo": float, "saldo_retirable": float, "verificada": "si"|"no"}.
    """
    saldo = 0.0
    saldo_retirable = 0.0
    try:
        saldo_locator = page.locator(SELECTORES_SALDO).or_(
            page.get_by_text(re.compile(r"\$\s*[\d.,]+"))
        ).first
        await saldo_locator.wait_for(state="visible", timeout=8000)
        saldo = extraer_saldo(await saldo_locator.inner_text(timeout=5000))
        logger.info(f"[{etiqueta}] Saldo total extraído: ${saldo:,.2f}")

        # Saldo retirable: el <td> hermano inmediato a td.balance-td.
        try:
            retirable_loc = page.locator("td.balance-td").locator(
                "xpath=following-sibling::td[1]"
            ).first
            saldo_retirable = extraer_saldo(await retirable_loc.inner_text(timeout=4000))
            logger.info(f"[{etiqueta}] Saldo retirable extraído: ${saldo_retirable:,.2f}")
        except ERRORES_PW:
            logger.debug(f"[{etiqueta}] No se pudo leer el saldo retirable")
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

    return {"saldo": saldo, "saldo_retirable": saldo_retirable, "verificada": verificada}


async def _navegar_seccion_cuenta(
    page, base_url: str, opcion_regex: str, ruta_fallback: str, etiqueta: str = ""
) -> None:
    """
    Navega a una sección de la cuenta por CLICS (más robusto que URLs directas):
    abre el menú "Mi cuenta" y hace clic en la opción; si no aparece, intenta el
    clic directo; y como último respaldo va por la URL directa.
    """
    opcion = re.compile(opcion_regex, re.IGNORECASE)
    try:
        await page.get_by_text(
            re.compile(r"^\s*Mi cuenta\s*$", re.IGNORECASE)
        ).first.click(timeout=6000)
        await human_delay(1, 2)
    except ERRORES_PW:
        pass
    try:
        await page.get_by_text(opcion).first.click(timeout=6000)
        await human_delay(2, 4)
        return
    except ERRORES_PW:
        logger.debug(f"[{etiqueta}] Navegación por clic falló; uso URL {ruta_fallback}")
    await page.goto(f"{base_url}{ruta_fallback}", wait_until="networkidle", timeout=20000)
    await human_delay(2, 4)


async def probar_limite(page, base_url: str, etiqueta: str) -> bool:
    """
    Lee la página oficial de Límites de Usuario y determina si la cuenta está
    limitada comparando el "Límite Diario" real contra el normal ($10.000.000):
    un tope MENOR al normal = cuenta limitada. Devuelve True si está limitada.
    """
    try:
        logger.info(f"[{etiqueta}] Revisando límite diario del usuario...")
        await _navegar_seccion_cuenta(
            page, base_url, r"Límites de Usuario", RUTA_LIMITES, etiqueta
        )
        await human_delay(2, 4)

        # Valor real del "Límite Diario" (p. ej. "$10.000.000").
        try:
            valor_txt = await page.locator(SEL_LIMITE_DIARIO).first.inner_text(timeout=8000)
            limite = extraer_saldo(valor_txt)
            logger.info(f"[{etiqueta}] Límite diario leído: ${limite:,.0f}")
            if 0 < limite < LIMITE_DIARIO_NORMAL:
                logger.info(
                    f"[{etiqueta}] Cuenta LIMITADA (tope ${limite:,.0f} < "
                    f"normal ${LIMITE_DIARIO_NORMAL:,.0f})"
                )
                return True
            return False
        except ERRORES_PW:
            # Respaldo: si no se pudo leer el valor, usamos el texto de la página.
            texto = await page.locator("body").inner_text(timeout=8000)
            if contiene_restriccion(texto, PALABRAS_LIMITE_BETPLAY):
                logger.info(f"[{etiqueta}] Cuenta LIMITADA (texto de restricción)")
                return True
            logger.info(f"[{etiqueta}] Sin límite bajo aparente")
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
        await _navegar_seccion_cuenta(
            page, base_url, r"Redimir Promoción|Redimir Promocion|Bonos|Promociones",
            RUTA_BONOS, etiqueta,
        )
        await human_delay(2, 4)
        cuerpo = (await page.locator("body").inner_text(timeout=10000)).lower()
        if MARCADOR_SIN_BONOS in cuerpo:
            logger.info(f"[{etiqueta}] Sin bonos ('No tienes bonos actualmente')")
            return "Sin bonos"
        if "bono activo" in cuerpo or "bono pendiente" in cuerpo:
            logger.info(f"[{etiqueta}] Bono detectado")
            return "Tiene Bono"
        logger.info(f"[{etiqueta}] Sin señal clara de bono; se asume Sin bonos")
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


def _evento_en_ventana(
    texto: str,
    ahora: Optional[datetime] = None,
    hora_min: int = APUESTA_HORA_MIN,
    hora_max: int = APUESTA_HORA_MAX,
    solo_hoy_manana: bool = APUESTA_SOLO_HOY_MANANA,
) -> bool:
    """
    Decide si el texto de fecha/hora de un evento cae en la ventana deseada: hoy o
    mañana (si solo_hoy_manana) y con hora de inicio en [hora_min, hora_max] (24h).

    Tolera formatos como 'Hoy 20:00', 'Mañana 8:00 PM', '05/07 20:30',
    '05.07. 20:00'. Si no logra extraer una hora, devuelve False (no arriesga).
    """
    if not texto:
        return False
    t = texto.strip().lower()
    ahora = ahora or datetime.now()

    # --- Hora (12h con am/pm o 24h) ---
    hh = None
    mm = 0
    m12 = re.search(r"(\d{1,2}):(\d{2})\s*(a\.?\s*m\.?|p\.?\s*m\.?)", t)
    if m12:
        hh, mm = int(m12.group(1)), int(m12.group(2))
        marca = m12.group(3).replace(" ", "")
        if marca.startswith("p") and hh < 12:
            hh += 12
        if marca.startswith("a") and hh == 12:
            hh = 0
    else:
        m24 = re.search(r"(\d{1,2}):(\d{2})", t)
        if m24:
            hh, mm = int(m24.group(1)), int(m24.group(2))
    if hh is None:
        return False

    # --- Día (hoy/mañana o fecha DD/MM) ---
    dia_ok = True
    if solo_hoy_manana:
        hoy = ahora.date()
        manana = (ahora + timedelta(days=1)).date()
        if any(k in t for k in ("hoy", "today")):
            dia_ok = True
        elif any(k in t for k in ("mañana", "manana", "tomorrow")):
            dia_ok = True
        else:
            mfecha = re.search(r"(\d{1,2})[/.](\d{1,2})", t)
            if mfecha:
                d, mth = int(mfecha.group(1)), int(mfecha.group(2))
                dia_ok = (d, mth) in {(hoy.day, hoy.month), (manana.day, manana.month)}
            # Sin marca de día explícita: asumimos próximo (hoy/mañana) -> dia_ok True.

    return dia_ok and (hora_min <= hh <= hora_max)


async def _frame_con(page, selector: str, timeout: int = 8000):
    """
    Devuelve el frame (la propia página o un iframe hijo) donde el selector es
    visible. Kambi suele estar en un iframe, así que buscamos en todos. None si
    no aparece en ninguno.
    """
    try:
        await page.locator(selector).first.wait_for(state="visible", timeout=timeout)
        return page
    except ERRORES_PW:
        pass
    for fr in page.frames:
        try:
            await fr.locator(selector).first.wait_for(state="visible", timeout=1500)
            return fr
        except ERRORES_PW:
            continue
    return None


async def _ir_a_deportes(page, base_url: str, etiqueta: str = "") -> None:
    """Navega al home y entra a la sección Deportes (clic directo o vía menú)."""
    await page.goto(base_url, wait_until="domcontentloaded", timeout=45000)
    await human_delay(2, 4)
    try:
        await page.locator(SEL_DEPORTES).filter(
            has_text=re.compile("Deportes", re.IGNORECASE)
        ).first.click(timeout=6000)
        return
    except ERRORES_PW:
        pass
    # Respaldo: abrir el menú hamburguesa y luego "Deportes".
    try:
        await page.locator(SEL_MENU_HAMBURGUESA).first.click(timeout=4000)
        await human_delay(1, 2)
        await page.get_by_text(re.compile(r"^\s*Deportes\s*$", re.IGNORECASE)).first.click(timeout=6000)
    except ERRORES_PW:
        logger.warning(f"[{etiqueta}] No se pudo navegar a Deportes por clic.")


async def _cuota_en_horario(boton, etiqueta: str = "") -> bool:
    """
    True si el evento del botón de cuota cae en la ventana horaria deseada. Sube a
    la tarjeta del evento (EventListItem) y une TODOS los spans de fecha/hora
    (día y hora vienen separados: "Hoy" + "06:00 p. m."). Si no se puede leer la
    hora, devuelve False (no arriesga apostar fuera de rango).
    """
    try:
        tarjeta = boton.locator("xpath=ancestor::*[contains(@class,'EventListItem')][1]")
        spans = tarjeta.locator(SEL_EVENTO_HORA)
        n = await spans.count()
        partes = []
        for i in range(min(n, 4)):
            try:
                partes.append((await spans.nth(i).inner_text(timeout=1500)).strip())
            except ERRORES_PW:
                continue
        hora_txt = " ".join(p for p in partes if p)
    except ERRORES_PW:
        return False
    if not hora_txt:
        return False
    ok = _evento_en_ventana(hora_txt)
    if not ok:
        logger.debug(f"[{etiqueta}] Evento fuera de la ventana horaria: {hora_txt!r}")
    return ok


async def _elegir_cuota(page, etiqueta: str, rango: Optional[tuple] = None) -> Optional[float]:
    """
    Hace clic en una cuota (botón Kambi con data-outcome-id + .original-odds) cuyo
    valor esté dentro de `rango`. Si `rango` es None, toma la primera disponible.
    Devuelve el valor de la cuota elegida, o None si no encontró ninguna.
    """
    frame = await _frame_con(page, SEL_CUOTA_BTN, timeout=10000)
    if frame is None:
        logger.warning(f"[{etiqueta}] No se encontraron cuotas en la página.")
        return None

    botones = frame.locator(SEL_CUOTA_BTN)
    try:
        total = await botones.count()
    except ERRORES_PW:
        return None

    for i in range(min(total, MAX_CUOTAS_INSPECCIONAR)):
        btn = botones.nth(i)
        try:
            texto = (await btn.locator(SEL_CUOTA_VALOR).first.inner_text(timeout=2000)).strip()
        except ERRORES_PW:
            continue
        m = re.search(r"(\d+\.\d{1,2})", texto)
        if not m:
            continue
        valor = float(m.group(1))
        if rango is None or (rango[0] <= valor <= rango[1]):
            # Filtro horario (hoy/mañana + tarde-noche) si hay selector de hora.
            if SEL_EVENTO_HORA and not await _cuota_en_horario(btn, etiqueta):
                continue
            try:
                await btn.click(timeout=4000)
                logger.info(f"[{etiqueta}] Cuota elegida: {valor}")
                return valor
            except ERRORES_PW:
                continue
    return None


async def _leer_betslip(page, etiqueta: str = "") -> str:
    """
    Extrae del cupón (betslip Kambi) qué se apostó: evento, mercado, selección y
    cuota, para mostrárselo al usuario. Devuelve una descripción legible.
    """
    frame = await _frame_con(page, SEL_BETSLIP, timeout=8000)
    if frame is None:
        return "apuesta"

    async def _txt(sel: str) -> str:
        try:
            return (await frame.locator(sel).first.inner_text(timeout=3000)).strip()
        except ERRORES_PW:
            return ""

    evento = await _txt(SEL_BETSLIP_EVENTO)
    pick = await _txt(SEL_BETSLIP_PICK)
    mercado = await _txt(SEL_BETSLIP_MERCADO)
    cuota = await _txt(SEL_BETSLIP_CUOTA)
    detalle = " | ".join(p for p in (evento, f"{mercado}: {pick}".strip(": "), f"@{cuota}" if cuota else "") if p)
    logger.info(f"[{etiqueta}] Cupón armado: {detalle}")
    return detalle or "apuesta"


async def _escribir_monto_betslip(page, etiqueta: str, monto: float) -> bool:
    """Escribe el stake en el input del cupón Kambi. True si lo logró."""
    frame = await _frame_con(page, SEL_MONTO_APUESTA, timeout=8000)
    if frame is None:
        logger.warning(f"[{etiqueta}] No se encontró el campo de monto del cupón.")
        return False
    try:
        campo = frame.locator(SEL_MONTO_APUESTA).first
        await campo.click(timeout=4000)
        await campo.fill(str(int(monto)))
        await human_delay(1, 2)
        return True
    except ERRORES_PW as e:
        logger.warning(f"[{etiqueta}] No se pudo escribir el monto: {e}")
        return False


async def apostar(
    page,
    base_url: str,
    etiqueta: str,
    monto: float,
    confirmar_waiter: Optional[Callable[..., Awaitable[None]]] = None,
    tipo: str = "saldo",
) -> str:
    """
    Prepara una apuesta (Deportes → cuota → monto en el cupón) y PAUSA para que el
    usuario dé el clic final de 'Apostar'. No confirma la apuesta por su cuenta.

    Para tipo="bono" busca una cuota 3.0-6.0 (RANGO_CUOTA_BONO); para tipo="saldo"
    toma la primera disponible. Devuelve una descripción ('preparada: <detalle>')
    o un estado: 'sin_monto', 'sin_cuota' o 'error'.
    """
    if not monto or monto <= 0:
        logger.warning(f"[{etiqueta}] Apostar {tipo}: monto invalido ({monto}); se omite.")
        return "sin_monto"
    try:
        logger.info(f"[{etiqueta}] Apostar {tipo}: preparando cupón por {monto:,.0f}...")
        await _ir_a_deportes(page, base_url, etiqueta)
        await human_delay(3, 6)

        # Elegir una cuota (en rango para bono, primera para saldo) y clicarla.
        rango = RANGO_CUOTA_BONO if tipo == "bono" else None
        cuota = await _elegir_cuota(page, etiqueta, rango)
        if cuota is None:
            destino = f"{rango[0]}-{rango[1]}" if rango else "cualquiera"
            logger.warning(f"[{etiqueta}] No se encontró cuota en el rango {destino}; se omite.")
            return "sin_cuota"
        await human_delay(2, 4)

        # Leer del cupón qué se armó (para reportarlo al usuario).
        detalle = await _leer_betslip(page, etiqueta)

        # Escribir el monto en el cupón.
        if not await _escribir_monto_betslip(page, etiqueta, monto):
            return "sin_monto"

        # Preparar y pausar: el usuario confirma manualmente (mismo mecanismo del CAPTCHA).
        logger.warning(
            f"[{etiqueta}] Apuesta {tipo} PREPARADA: {detalle} por {monto:,.0f}. "
            "Revisa y confirma a mano."
        )
        if confirmar_waiter is not None:
            await confirmar_waiter("apuesta")
        return f"preparada: {detalle}"
    except ERRORES_PW as e:
        logger.warning(f"[{etiqueta}] No se pudo preparar la apuesta {tipo}: {e}")
        return "error"
