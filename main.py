"""
main.py
=======

Orquestador de alto nivel del Automatizador (Betplay 2.0).

Versión FUSIONADA del main previo + el flujo nuevo, corrigiendo todas las
referencias rotas para dejarlo ejecutable:

  - Lee cuentas.xlsx validando columnas con auditor.leer_cuentas().
  - Por cada cuenta: resuelve el endpoint CDP, obtiene el código 2FA por correo
    (lector_correos), ejecuta process_user (procesador_web), guarda el resultado
    en el DataFrame y en el historial CSV, y espera un intervalo humano largo
    entre cuentas (anti-detección).
  - Al final escribe cuentas_actualizadas.xlsx.

Estrategia de navegador (configurable con USAR_GESTOR_PERFILES):
  - False (por defecto): se conecta a navegadores YA abiertos usando el puerto
    de la columna 'Puerto' de cada fila (patrón usado en todo el proyecto;
    funciona con el cuentas.xlsx actual sin pasos extra).
  - True: lanza un Chrome con perfil aislado por cuenta vía
    gestor_perfiles.lanzar_perfil_chrome (ver notas/avisos en el README mental).

Requisitos para ejecutar en vivo:
    pip install -r requirements.txt
    playwright install chromium
    # y un navegador escuchando por cada 'Puerto' (o USAR_GESTOR_PERFILES=True)
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime

import pandas as pd

import control
from auditor import (
    ARCHIVO_HISTORIAL,
    PUERTO_POR_DEFECTO,
    imprimir_reporte_final,
    inicializar_historial,
    leer_cuentas,
    log,
    registrar_historial,
)
from conexion_cdp import construir_endpoint
from lector_correos import esperar_y_extraer_codigo
from pausa import pausa_humana
from preflight import validar_datos
from procesador_web import process_user
from rotador_ip import rotar_ip_seguro

# ---------------------------------------------------------------------------
# CONFIGURACIÓN
# ---------------------------------------------------------------------------

EXCEL_INPUT = "cuentas.xlsx"
EXCEL_OUTPUT = "cuentas_actualizadas.xlsx"
BASE_URL = "https://www.betplay.com.co"

# Remitente (o display name) del correo que trae el código 2FA.
REMITENTE_2FA = "Betplay"

# Espera anti-detección entre cuentas (en minutos).
PAUSA_MIN_MINUTOS = 4
PAUSA_MAX_MINUTOS = 12

# Estrategia de navegador. False = conectar a navegadores ya abiertos por puerto;
# True = lanzar un Chrome con perfil aislado por cuenta (gestor_perfiles).
USAR_GESTOR_PERFILES = True  # Cambiar a False si ya tienes navegadores abiertos por puerto

# Reanudación y guardado incremental.
ARCHIVO_PROGRESO = "progreso.txt"
GUARDADO_PARCIAL_CADA = 10   # cada cuantas cuentas se anuncia el guardado parcial

# Maximo de espera (segundos) por la senal "Continuar" del dashboard en el CAPTCHA.
# 15 min: el registro masivo necesita mas margen para rellenar el formulario y
# resolver el reCAPTCHA a mano antes de continuar.
TIMEOUT_CAPTCHA_SEG = 900

# Rotacion de IP movil (ADB) ANTES de procesar cada cuenta (login o registro).
# Es defensiva: sin ADB/celular/root solo avisa y sigue (rotar_ip_seguro nunca lanza).
ROTAR_IP = True                 # el dashboard puede desactivarlo (cfg["rotar_ip"])
ROTAR_IP_SEG_MIN = 5.0          # segundos en modo avion (minimo)
ROTAR_IP_SEG_MAX = 10.0         # segundos en modo avion (maximo)
ROTAR_IP_VERIFICAR = True       # consultar IP publica antes/despues para avisar si no cambio


# ---------------------------------------------------------------------------
# RESOLUCIÓN DEL NAVEGADOR (endpoint CDP)
# ---------------------------------------------------------------------------

def _puerto_de_fila(row, perfil_id: int) -> int:
    """Puerto CDP de la fila; si no es válido, rota sobre el puerto base."""
    try:
        return int(float(str(row.get("Puerto", PUERTO_POR_DEFECTO))))
    except (ValueError, TypeError):
        return PUERTO_POR_DEFECTO + (perfil_id % 8)


async def _resolver_endpoint(row, perfil_id: int) -> tuple[int, str]:
    """Devuelve (puerto, endpoint_cdp) según la estrategia configurada."""
    if USAR_GESTOR_PERFILES:
        # lanzar_perfil_chrome es BLOQUEANTE (subprocess.Popen + time.sleep),
        # así que lo ejecutamos en un hilo para no bloquear el event loop.
        from gestor_perfiles import lanzar_perfil_chrome

        proxy = str(row.get("Proxy", "") or "").strip() or None
        return await asyncio.to_thread(lanzar_perfil_chrome, perfil_id, proxy)

    puerto = _puerto_de_fila(row, perfil_id)
    return puerto, construir_endpoint(puerto=puerto)


def cargar_y_asignar_proxies(df: pd.DataFrame) -> pd.DataFrame:
    """
    Carga proxies.txt y los asigna ROTATIVAMENTE a las filas SIN proxy válido.

    Respeta las filas que ya traen un proxy en su columna 'Proxy'. Si no hay
    proxies en el archivo, devuelve el DataFrame intacto. Solo tiene efecto real
    cuando se usa el gestor de perfiles (es quien pasa --proxy-server a Chrome).
    """
    from gestor_perfiles import cargar_proxies_desde_archivo, proxy_valido

    proxies = cargar_proxies_desde_archivo()
    if not proxies:
        log.info("Sin proxies en proxies.txt; las cuentas usan su proxy propio o ninguno.")
        return df

    if "Proxy" not in df.columns:
        df["Proxy"] = ""

    proxy_idx = 0
    asignados = 0
    for i, row in df.iterrows():
        if proxy_valido(row.get("Proxy", "")) is None:
            df.at[i, "Proxy"] = proxies[proxy_idx % len(proxies)]
            proxy_idx += 1
            asignados += 1

    log.exito(
        f"Proxies: {len(proxies)} disponible(s); asignados a {asignados} cuenta(s) sin proxy."
    )
    return df


# ---------------------------------------------------------------------------
# REANUDACIÓN (progreso entre ejecuciones)
# ---------------------------------------------------------------------------

def _leer_progreso(ruta: str = ARCHIVO_PROGRESO) -> int:
    """Índice de la próxima cuenta a procesar (0 si no hay progreso previo)."""
    try:
        with open(ruta, encoding="utf-8") as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return 0


def _guardar_progreso(indice: int, ruta: str = ARCHIVO_PROGRESO) -> None:
    """Persiste el índice de la próxima cuenta a procesar."""
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(str(indice))


# ---------------------------------------------------------------------------
# LOG A ARCHIVO + ESPERA DEL CAPTCHA (control desde el dashboard)
# ---------------------------------------------------------------------------

def _configurar_log_archivo() -> None:
    """Anade un handler que vuelca todos los logs a control.LOG_BOT (para el dashboard)."""
    raiz = logging.getLogger()
    if any(getattr(h, "_es_bot_log", False) for h in raiz.handlers):
        return
    fh = logging.FileHandler(control.LOG_BOT, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    fh._es_bot_log = True  # type: ignore[attr-defined]
    raiz.addHandler(fh)
    raiz.setLevel(logging.INFO)
    logging.getLogger("procesador_web").setLevel(logging.INFO)


async def _confirmar_waiter(motivo: str = "captcha") -> None:
    """
    Pausa el bot hasta que el dashboard cree la senal "Continuar" (o se alcance
    TIMEOUT_CAPTCHA_SEG, o se pida detener). Sirve para el CAPTCHA del registro
    (motivo="captcha") y para confirmar a mano una apuesta preparada
    (motivo="apuesta").
    """
    if motivo == "apuesta":
        estado, fase = "esperando_apuesta", "apuesta"
        msg = "Revisa la apuesta en el navegador y pulsa Continuar para confirmarla"
    else:
        estado, fase = "esperando_captcha", "captcha"
        msg = "Resuelve el CAPTCHA en el navegador y pulsa Continuar"

    control.limpiar_continuar()
    control.escribir_estado(estado=estado, fase=fase, mensaje=msg)
    log.warning(f"Esperando 'Continuar' desde el dashboard ({motivo})...")
    esperado = 0
    while not control.hay_senal_continuar():
        if control.hay_senal_detener():
            break
        await asyncio.sleep(2)
        esperado += 2
        if esperado >= TIMEOUT_CAPTCHA_SEG:
            log.warning("Timeout esperando 'Continuar'; sigo de todos modos.")
            break
    control.limpiar_continuar()
    control.escribir_estado(estado="corriendo", fase="post-confirmacion", mensaje="Continuando")


# ---------------------------------------------------------------------------
# PROCESAMIENTO DE UNA FILA
# ---------------------------------------------------------------------------

async def procesar_fila(row, perfil_id: int, tareas: set, apuesta_cfg: dict) -> dict:
    """Resuelve navegador + 2FA y ejecuta process_user (login o registro)."""
    email = row.get("Correo") or row.get("Usuario")
    password = str(row.get("Password", ""))
    nombre = str(row.get("Nombre", "") or "")
    modo = "registro" if str(row.get("Modo", "")).strip().lower() == "registro" else "login"
    etiqueta = nombre or email or f"fila_{perfil_id}"

    # Usuario de LOGIN en Betplay: es la cédula ("Usuario / Cédula"). Si la fila
    # no trae Cédula, caemos al Correo/Usuario. (El correo se sigue usando para el
    # 2FA por IMAP, que es independiente de con qué se inicia sesión.)
    cedula = str(row.get("Cedula", "") or "").strip()
    usuario_login = cedula or str(email)

    # Rotacion de IP movil ANTES de tocar el navegador (login o registro). Bloqueante,
    # asi que va en un hilo para no bloquear el event loop. Defensiva: nunca lanza.
    if ROTAR_IP:
        log.info(f"[{etiqueta}] Rotando IP movil (ADB) antes de procesar...")
        control.escribir_estado(fase="rotando_ip", mensaje="Rotando IP movil (modo avion)")
        await asyncio.to_thread(
            rotar_ip_seguro,
            ROTAR_IP_SEG_MIN,
            ROTAR_IP_SEG_MAX,
            None,
            None,
            ROTAR_IP_VERIFICAR,
        )

    log.info(f"[{etiqueta}] Preparando navegador... (modo: {modo})")
    puerto, endpoint = await _resolver_endpoint(row, perfil_id)
    log.info(f"[{etiqueta}] Endpoint CDP: {endpoint}")

    # 2FA: pasamos un PROVEEDOR de código (callback) en vez de pre-buscarlo.
    # process_user lo invocará solo cuando aparezca el campo 2FA (después de
    # enviar el login), que es cuando el correo con el código ya fue disparado.
    clave_correo = str(row.get("ClaveCorreo", "") or "").strip()
    code_provider = None
    if email and clave_correo:
        async def code_provider():
            return await esperar_y_extraer_codigo(str(email), clave_correo, REMITENTE_2FA)

    # Datos para el modo registro: limpiamos NaN -> "" para no romper el tecleo.
    datos = {k: ("" if pd.isna(v) else v) for k, v in row.to_dict().items()}

    resultado = await process_user(
        cdp_endpoint=endpoint,
        username=usuario_login,
        password=password,
        nombre=nombre,
        code_provider=code_provider,
        base_url=BASE_URL,
        datos=datos,
        modo=modo,
        confirmar_waiter=_confirmar_waiter,
        tareas=tareas,
        apuesta_cfg=apuesta_cfg,
    )

    registrar_historial(
        usuario=str(email),
        estado=resultado.get("estado", "desconocido"),
        detalle=(
            f"Modo: {modo} | Reg: {resultado.get('registro', 'n/a')} | "
            f"Bono: {resultado.get('bono', 'n/a')} | "
            f"ApBono: {resultado.get('apuesta_bono', 'n/a')} | "
            f"ApSaldo: {resultado.get('apuesta_saldo', 'n/a')} | Puerto: {puerto}"
        ),
        saldo=resultado.get("saldo", 0.0),
        verificada=resultado.get("verificada", "desconocido"),
        limitada=resultado.get("limitada", False),
    )
    return resultado


# ---------------------------------------------------------------------------
# NOTIFICACIÓN FINAL POR EMAIL (opcional)
# ---------------------------------------------------------------------------

def _enviar_email_sync(reporte: dict) -> None:
    """Envío SMTP (bloqueante). Se ejecuta en un hilo desde enviar_resumen_email."""
    import smtplib
    from email.message import EmailMessage

    # Carga opcional de .env (si python-dotenv está instalado); si no, se usan
    # las variables de entorno del sistema directamente.
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv()
    except ImportError:
        pass

    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    email_from = os.getenv("EMAIL_FROM") or smtp_user
    email_to = os.getenv("EMAIL_TO") or email_from
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))

    if not all([email_from, email_to, smtp_user, smtp_pass]):
        log.warning(
            "Email no configurado (faltan SMTP_USER/SMTP_PASS/EMAIL_FROM/EMAIL_TO); "
            "se omite la notificación."
        )
        return

    total = reporte.get("Total procesadas", reporte.get("mensaje", "?"))
    msg = EmailMessage()
    msg["Subject"] = f"Betplay Bot - Corrida finalizada ({total} cuentas)"
    msg["From"] = email_from
    msg["To"] = email_to

    lineas = [f"Resumen de la corrida - {datetime.now():%Y-%m-%d %H:%M}", ""]
    lineas += [f"  {clave}: {valor}" for clave, valor in reporte.items()]
    lineas += ["", "Revisa el dashboard y historial_auditoria.csv para el detalle."]
    msg.set_content("\n".join(lineas))

    with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
    log.exito(f"Resumen enviado por email a {email_to}")


async def enviar_resumen_email(reporte: dict) -> None:
    """
    Envía un resumen de la corrida por email (SMTP) si están configuradas las
    variables de entorno. Nunca lanza: ante cualquier fallo, solo registra un
    aviso para no afectar el cierre de la corrida.
    """
    try:
        await asyncio.to_thread(_enviar_email_sync, reporte)
    except Exception as e:  # noqa: BLE001
        log.warning(f"No se pudo enviar el email de resumen: {e}")


# ---------------------------------------------------------------------------
# BUCLE PRINCIPAL
# ---------------------------------------------------------------------------

async def main() -> None:
    _configurar_log_archivo()

    # Config de la corrida (la escribe el dashboard); por defecto si no existe.
    cfg = control.leer_config()
    global USAR_GESTOR_PERFILES, ROTAR_IP
    USAR_GESTOR_PERFILES = bool(cfg.get("usar_gestor", USAR_GESTOR_PERFILES))
    pausa_min = float(cfg.get("pausa_min", PAUSA_MIN_MINUTOS))
    pausa_max = float(cfg.get("pausa_max", PAUSA_MAX_MINUTOS))
    filtro_modo = str(cfg.get("filtro_modo", "todo")).strip().lower()
    tareas = set(cfg.get("tareas", ["apuesta_maxima", "bonos"]))
    apuesta_cfg = cfg.get("apuesta", {"modo": "fijo", "valor": 0})
    # Rotación de IP móvil (ADB) ANTES de cada cuenta (login o registro). Automática
    # por defecto; el dashboard puede desactivarla con cfg["rotar_ip"] = False.
    ROTAR_IP = bool(cfg.get("rotar_ip", ROTAR_IP))
    # Seleccion explicita de cuentas desde el dashboard: lista de Correo/Usuario.
    # Vacia o ausente = procesar todas (comportamiento previo).
    seleccionadas = {str(x).strip() for x in (cfg.get("cuentas_seleccionadas") or []) if str(x).strip()}

    log.exito("Iniciando Automatizador Betplay 2.0")
    inicializar_historial()
    control.reset_control()
    control.escribir_estado(
        estado="corriendo", indice=0, total=0, cuenta="", fase="inicio",
        mensaje="Cargando cuentas...", resumen={},
    )

    # Reanudacion: si hay progreso previo y existe el Excel parcial, partimos de
    # el para conservar los resultados de las cuentas ya procesadas.
    progreso = _leer_progreso()
    fuente = EXCEL_OUTPUT if (progreso > 0 and os.path.exists(EXCEL_OUTPUT)) else EXCEL_INPUT
    try:
        df = leer_cuentas(fuente)
        log.exito(f"Cargadas {len(df)} cuenta(s) de {fuente}")
    except Exception as e:  # noqa: BLE001
        log.error(f"No se pudo leer {fuente}: {e}")
        control.escribir_estado(estado="error", mensaje=f"No se pudo leer {fuente}: {e}")
        return

    # Rotacion automatica de proxies: asigna proxies.txt a las filas sin proxy.
    df = cargar_y_asignar_proxies(df)

    # Preflight (red de seguridad): si no hay nada procesable, abortamos antes de
    # gastar intentos. Los avisos no bloquean (las filas malas se omiten luego).
    pf_errores, pf_avisos = validar_datos(df, filtro_modo)
    for aviso in pf_avisos:
        log.warning(f"[preflight] {aviso}")
    if pf_errores:
        for err in pf_errores:
            log.error(f"[preflight] {err}")
        control.escribir_estado(
            estado="error", mensaje="Preflight fallido: " + " | ".join(pf_errores)
        )
        return

    control.escribir_estado(total=len(df))
    if progreso > 0:
        log.info(f"Reanudando desde la cuenta #{progreso + 1} (progreso previo).")

    resumen: dict[str, int] = {}
    try:
        for idx, row in df.iterrows():
            # Saltar cuentas ya procesadas en una ejecucion anterior.
            if idx < progreso:
                continue

            modo_fila = "registro" if str(row.get("Modo", "")).strip().lower() == "registro" else "login"
            # Filtro de modo desde el dashboard (todo|login|registro).
            if filtro_modo in ("login", "registro") and modo_fila != filtro_modo:
                continue

            # Filtro de seleccion explicita: si el dashboard mando una lista de
            # cuentas, solo procesamos las que coincidan por Correo o Usuario.
            if seleccionadas:
                ident_correo = str(row.get("Correo", "") or "").strip()
                ident_usuario = str(row.get("Usuario", "") or "").strip()
                if ident_correo not in seleccionadas and ident_usuario not in seleccionadas:
                    continue

            # Parada solicitada desde el dashboard (entre cuentas).
            if control.hay_senal_detener():
                log.warning("Senal de detencion recibida; parando entre cuentas.")
                control.escribir_estado(estado="detenido", mensaje="Detenido por el usuario")
                break

            email = row.get("Correo") or row.get("Usuario")
            control.escribir_estado(
                estado="corriendo", indice=int(idx), total=len(df),
                cuenta=str(email), fase=modo_fila, mensaje="Procesando cuenta",
            )
            log.info("=" * 60)
            log.info(f"Cuenta {idx + 1}/{len(df)} - {datetime.now():%H:%M:%S} (modo: {modo_fila})")

            try:
                resultado = await procesar_fila(row, idx, tareas, apuesta_cfg)
                ok = resultado.get("estado") not in ("error", "login_fallido") and resultado.get("saldo", 0)
                registrar = log.exito if ok else log.warning
                registrar(
                    f"[{idx + 1}/{len(df)}] {email}  saldo=${resultado.get('saldo')}  "
                    f"bono={resultado.get('bono')}  ap_bono={resultado.get('apuesta_bono')}  "
                    f"ap_saldo={resultado.get('apuesta_saldo')}  estado={resultado.get('estado')}"
                )
            except Exception as e:  # noqa: BLE001  (aislamos el fallo por cuenta)
                log.error(f"Fallo procesando la cuenta {idx + 1}: {e}")
                resultado = {
                    "saldo": 0.0, "verificada": "error", "limitada": False,
                    "bono": "Error bonos", "apuesta_bono": "n/a", "apuesta_saldo": "n/a",
                    "registro": "n/a", "estado": "error",
                }

            estado_cuenta = resultado.get("estado", "desconocido")
            resumen[estado_cuenta] = resumen.get(estado_cuenta, 0) + 1

            df.at[idx, "Saldo"] = resultado.get("saldo", 0.0)
            df.at[idx, "Saldo_Retirable"] = resultado.get("saldo_retirable", 0.0)
            df.at[idx, "Verificada"] = resultado.get("verificada", "desconocido")
            df.at[idx, "Limitada"] = resultado.get("limitada", False)
            df.at[idx, "Bono"] = resultado.get("bono", "")
            df.at[idx, "Apuesta_Bono"] = resultado.get("apuesta_bono", "")
            df.at[idx, "Apuesta_Saldo"] = resultado.get("apuesta_saldo", "")
            df.at[idx, "Registro"] = resultado.get("registro", "n/a")
            df.at[idx, "Estado"] = estado_cuenta
            df.at[idx, "Ultima_Ejecucion"] = datetime.now()

            # Guardado incremental (resume sin perdida) + estado para el dashboard.
            df.to_excel(EXCEL_OUTPUT, index=False)
            _guardar_progreso(idx + 1)
            control.escribir_estado(resumen=resumen)
            if (idx + 1) % GUARDADO_PARCIAL_CADA == 0:
                log.info(f"Guardado parcial: {idx + 1}/{len(df)} cuentas -> {EXCEL_OUTPUT}")

            # (La rotación de IP se hace ahora al INICIO de cada cuenta en
            # procesar_fila, no aquí, para cubrir login y registro por igual.)

            # Pausa humana larga entre cuentas (no despues de la ultima).
            if idx < len(df) - 1 and not control.hay_senal_detener():
                control.escribir_estado(fase="pausa", mensaje="Pausa anti-deteccion")
                segundos = await pausa_humana(pausa_min, pausa_max)
                log.info(f"Pausa anti-deteccion: {segundos / 60:.1f} min antes de la siguiente")
    except Exception as e:  # noqa: BLE001
        log.error(f"Error inesperado en el bucle principal: {e}")
        control.escribir_estado(estado="error", mensaje=str(e))
        df.to_excel(EXCEL_OUTPUT, index=False)
        return

    df.to_excel(EXCEL_OUTPUT, index=False)
    detenido = control.hay_senal_detener()
    # Si terminamos el lote completo (no por detener), limpiamos el progreso.
    if not detenido and os.path.exists(ARCHIVO_PROGRESO):
        os.remove(ARCHIVO_PROGRESO)
    if resumen:
        log.info("Resumen: " + " - ".join(f"{k}={v}" for k, v in sorted(resumen.items())))
    estado_final = "detenido" if detenido else "finalizado"
    control.escribir_estado(estado=estado_final, fase="fin", mensaje="Proceso terminado", resumen=resumen)
    log.exito(f"Proceso terminado ({estado_final}). Resultados en {EXCEL_OUTPUT} y {ARCHIVO_HISTORIAL}")

    # Reporte final agregado (lee el historial CSV y lo pinta en el log del bot).
    try:
        reporte = imprimir_reporte_final()
        # Notificación opcional por email (solo si está configurado el SMTP).
        await enviar_resumen_email(reporte)
    except Exception as e:  # noqa: BLE001
        log.warning(f"No se pudo generar el reporte/email final: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.warning("Ejecución interrumpida por el usuario.")
