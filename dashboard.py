"""
dashboard.py
============

Panel de control + visor del Automatizador Betplay (Streamlit).

Permite manejar TODO el bot desde el navegador:
  - Pestana "Cuentas": editar/crear la lista de cuentas (login o registro).
  - Pestana "Control": Iniciar / Detener / Continuar (CAPTCHA) y ver el progreso
    en vivo (estado, cuenta actual, log) mientras el bot corre como proceso aparte.
  - Pestana "Resultados": metricas, graficos y exportacion de los resultados.

El bot (main.py) se lanza como subproceso y se comunica con este panel por
archivos (ver control.py): estado_bot.json, config_run.json, senales y bot.log.

Instalacion:
    pip install streamlit pandas openpyxl altair

Ejecucion:
    streamlit run dashboard.py
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st

import control

# Archivos del proyecto.
RUTA_EXCEL = "cuentas.xlsx"
RUTA_RESULTADOS = "cuentas_actualizadas.xlsx"
RUTA_HISTORIAL = "historial_auditoria.csv"
LOG_CONSOLA = "bot_consola.log"

# Columnas sensibles (se pueden ocultar en la vista de resultados).
COLUMNAS_SENSIBLES = ["Password", "ClaveCorreo"]

# Esquema base para crear una lista de cuentas desde cero. Incluye los campos de
# registro (fechas y lugar de expedicion) que usan tab_registrar y el registro masivo.
COLUMNAS_PLANTILLA = [
    "Usuario", "Password", "Nombre", "Correo", "ClaveCorreo", "Puerto", "Modo",
    "Cedula", "PrimerNombre", "SegundoNombre", "PrimerApellido", "SegundoApellido",
    "Genero", "Telefono",
    "ExpedicionDD", "ExpedicionMM", "ExpedicionYYYY",
    "NacimientoDD", "NacimientoMM", "NacimientoYYYY",
    "LugarExpedicion",
    "TipoVia", "Direccion1", "Direccion2", "Direccion3", "Ciudad",
]


# ---------------------------------------------------------------------------
# UTILIDADES DE DATOS
# ---------------------------------------------------------------------------

def leer_excel(ruta: str) -> pd.DataFrame:
    """Lee un Excel local; DataFrame vacio si no existe o falla."""
    if not os.path.exists(ruta):
        return pd.DataFrame()
    try:
        return pd.read_excel(ruta)
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


def generar_plantilla_registro(n: int = 10) -> pd.DataFrame:
    """Genera una plantilla de n cuentas en modo registro, lista para rellenar.

    Asigna puertos CDP consecutivos (9222, 9223, ...) y valores por defecto
    razonables en las fechas/lugar de expedicion; los datos personales quedan
    vacios para que los completes.
    """
    df = pd.DataFrame(columns=COLUMNAS_PLANTILLA)
    for i in range(int(n)):
        df.loc[i] = {
            "Usuario": "",
            "Password": "",
            "Nombre": f"Cuenta {i + 1}",
            "Correo": "",
            "ClaveCorreo": "",
            "Puerto": 9222 + i,
            "Modo": "registro",
            "Cedula": "",
            "PrimerNombre": "",
            "SegundoNombre": "",
            "PrimerApellido": "",
            "SegundoApellido": "",
            "Genero": "",
            "Telefono": "",
            "ExpedicionDD": "15", "ExpedicionMM": "06", "ExpedicionYYYY": "1995",
            "NacimientoDD": "10", "NacimientoMM": "03", "NacimientoYYYY": "1995",
            "LugarExpedicion": "BOGOTA",
            "TipoVia": "", "Direccion1": "", "Direccion2": "", "Direccion3": "",
            "Ciudad": "BOGOTA",
        }
    return df


def leer_historial() -> pd.DataFrame:
    if not os.path.exists(RUTA_HISTORIAL):
        return pd.DataFrame()
    try:
        return pd.read_csv(RUTA_HISTORIAL)
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


def porcentaje_verificadas(df: pd.DataFrame) -> float:
    if "Verificada" not in df.columns or len(df) == 0:
        return 0.0
    ver = df["Verificada"].astype(str).str.strip().str.lower().eq("si").sum()
    return round(ver / len(df) * 100, 1)


def contar_limitadas(df: pd.DataFrame) -> int:
    if "Limitada" not in df.columns:
        return 0
    valores = df["Limitada"].astype(str).str.strip().str.lower()
    return int(valores.isin(["true", "si", "1", "limitada"]).sum())


def serie_registro(df: pd.DataFrame) -> pd.Series:
    """
    Estado de registro por fila, normalizado a minúsculas.

    Lo toma de la columna 'Registro' (Excel de resultados) o, en su defecto, lo
    parsea de 'Reg: <estado>' dentro de 'Detalle' (historial CSV). Devuelve ""
    para filas sin dato (p. ej. cuentas en modo login).
    """
    if "Registro" in df.columns:
        return df["Registro"].astype(str).str.strip().str.lower()
    if "Detalle" in df.columns:
        return (
            df["Detalle"].astype(str)
            .str.extract(r"reg:\s*([a-z_]+)", flags=re.IGNORECASE, expand=False)
            .fillna("")
            .str.lower()
        )
    return pd.Series([""] * len(df), index=df.index)


def to_excel_bytes(df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Resultados")
    return buffer.getvalue()


def _opciones_cuentas(df: pd.DataFrame) -> list[str]:
    """Identificadores (Correo o Usuario) de cada fila, para seleccionar cuentas."""
    if df.empty:
        return []
    opciones: list[str] = []
    for _, fila in df.iterrows():
        ident = str(fila.get("Correo") or fila.get("Usuario") or "").strip()
        if ident and ident.lower() != "nan" and ident not in opciones:
            opciones.append(ident)
    return opciones


def cola_log(ruta: str, n: int = 40) -> str:
    """Devuelve las ultimas n lineas de un log de texto."""
    if not os.path.exists(ruta):
        return ""
    try:
        with open(ruta, encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-n:])
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# CONTROL DEL BOT (subproceso)
# ---------------------------------------------------------------------------

def bot_proceso_vivo() -> bool:
    proc = st.session_state.get("bot_proc")
    return proc is not None and proc.poll() is None


def bot_activo(estado: dict) -> bool:
    """True si el bot esta trabajando (por estado publicado o proceso vivo)."""
    return (
        estado.get("estado") in ("corriendo", "esperando_captcha", "esperando_apuesta")
        or bot_proceso_vivo()
    )


def generar_reporte_parcial() -> str:
    """Copia el Excel de resultados a un archivo con timestamp. Devuelve la ruta o ''."""
    if not os.path.exists(RUTA_RESULTADOS):
        return ""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    destino = f"reporte_PARCIAL_{ts}.xlsx"
    shutil.copy(RUTA_RESULTADOS, destino)
    return destino


def iniciar_bot(config: dict) -> None:
    control.escribir_config(config)
    control.reset_control()
    control.escribir_estado(estado="corriendo", mensaje="Lanzando bot...", indice=0, total=0, resumen={})
    salida = open(LOG_CONSOLA, "a", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "main.py"],
        stdout=salida,
        stderr=subprocess.STDOUT,
    )
    st.session_state.bot_proc = proc


def detener_bot() -> None:
    control.pedir_detener()


def forzar_parada() -> None:
    control.pedir_detener()
    proc = st.session_state.get("bot_proc")
    if proc is not None and proc.poll() is None:
        proc.terminate()


# ---------------------------------------------------------------------------
# PESTANA: CUENTAS
# ---------------------------------------------------------------------------

def tab_cuentas() -> None:
    st.subheader("Lista de cuentas")
    st.caption(
        "Edita o crea cuentas. Marca 'Modo' = registro para CREAR una cuenta "
        "(rellena Cedula, PrimerNombre, etc.) o 'Modo' = login para verificar una existente."
    )

    df = leer_excel(RUTA_EXCEL)
    if df.empty:
        df = pd.DataFrame(columns=COLUMNAS_PLANTILLA)

    editado = st.data_editor(
        df,
        num_rows="dynamic",
        width="stretch",
        key="editor_cuentas",
        column_config={
            "Modo": st.column_config.SelectboxColumn(
                "Modo", options=["login", "registro"], help="login = verificar; registro = crear cuenta"
            ),
        },
    )

    c1, c2 = st.columns(2)
    if c1.button("Guardar cuentas", type="primary"):
        try:
            editado.to_excel(RUTA_EXCEL, index=False)
            st.success(f"Guardado {RUTA_EXCEL} ({len(editado)} cuenta(s)).")
        except Exception as exc:  # noqa: BLE001
            st.error(f"No se pudo guardar: {exc}")

    # Reemplaza la lista por una plantilla limpia (operacion destructiva).
    if c2.button("Reemplazar por plantilla (5 cuentas)"):
        try:
            generar_plantilla_registro(5).to_excel(RUTA_EXCEL, index=False)
            st.warning("La lista se reemplazo por una plantilla de 5 cuentas en modo registro.")
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"No se pudo generar la plantilla: {exc}")


# ---------------------------------------------------------------------------
# PESTANA: CREAR MASIVAS
# ---------------------------------------------------------------------------

def tab_crear_cuentas() -> None:
    st.subheader("Crear cuentas masivas")
    st.caption(
        "Genera una plantilla de varias cuentas en modo registro, o sube un Excel "
        "con datos personales para anexarlos a la lista actual."
    )

    opcion = st.radio(
        "Como quieres crear las cuentas?",
        ["Generar plantilla", "Subir Excel con datos"],
        horizontal=True,
    )

    if opcion == "Generar plantilla":
        num = st.number_input(
            "Numero de cuentas a generar", min_value=1, max_value=200, value=10, step=1
        )
        sobrescribir = st.checkbox(
            "Reemplazar la lista actual (si no, se anexan)", value=False
        )
        if st.button("Generar plantilla", type="primary"):
            plantilla = generar_plantilla_registro(int(num))
            try:
                if sobrescribir:
                    df_final = plantilla
                else:
                    df_actual = leer_excel(RUTA_EXCEL)
                    df_final = (
                        plantilla if df_actual.empty
                        else pd.concat([df_actual, plantilla], ignore_index=True)
                    )
                df_final.to_excel(RUTA_EXCEL, index=False)
                st.success(
                    f"Plantilla de {int(num)} cuenta(s) "
                    f"{'guardada' if sobrescribir else 'anexada'}; total {len(df_final)}."
                )
                st.download_button(
                    "Descargar plantilla (Excel)",
                    to_excel_bytes(plantilla),
                    "plantilla_registro.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            except Exception as exc:  # noqa: BLE001
                st.error(f"No se pudo guardar la plantilla: {exc}")

    else:
        subido = st.file_uploader(
            "Sube un Excel con datos (Cedula, PrimerNombre, Correo, etc.)", type=["xlsx"]
        )
        if subido is not None:
            try:
                df_nuevo = pd.read_excel(subido)
            except Exception as exc:  # noqa: BLE001
                st.error(f"No se pudo leer el Excel: {exc}")
                return
            st.dataframe(df_nuevo.head(20), width="stretch", hide_index=True)
            if st.button("Anexar a la lista del bot", type="primary"):
                try:
                    df_actual = leer_excel(RUTA_EXCEL)
                    df_combinado = (
                        df_nuevo if df_actual.empty
                        else pd.concat([df_actual, df_nuevo], ignore_index=True)
                    )
                    df_combinado.to_excel(RUTA_EXCEL, index=False)
                    st.success(
                        f"Se anexaron {len(df_nuevo)} cuenta(s); total {len(df_combinado)}."
                    )
                except Exception as exc:  # noqa: BLE001
                    st.error(f"No se pudo anexar: {exc}")


# ---------------------------------------------------------------------------
# PESTANA: CONTROL
# ---------------------------------------------------------------------------

def tab_control() -> None:
    estado = control.leer_estado()
    activo = bot_activo(estado)

    st.subheader("Control del bot")

    # --- Configuracion de la corrida ---
    with st.expander("Configuracion de la corrida", expanded=not activo):
        c1, c2 = st.columns(2)
        usar_gestor = c1.toggle("Lanzar Chrome por cuenta (gestor_perfiles)", value=True)
        filtro = c2.selectbox("Filtrar cuentas por modo", ["todo", "login", "registro"], index=0)

        # Proxies disponibles (proxies.txt) para la rotacion automatica en main.py.
        try:
            from gestor_perfiles import cargar_proxies_desde_archivo
            n_proxies = len(cargar_proxies_desde_archivo())
        except Exception:  # noqa: BLE001
            n_proxies = 0
        pc1, pc2 = st.columns([4, 1])
        if n_proxies:
            pc1.success(
                f"Proxies disponibles en proxies.txt: {n_proxies} "
                "(se asignan rotativamente a las cuentas sin proxy)."
            )
        else:
            pc1.info(
                "Sin proxies en proxies.txt. Agrega uno por linea para activar la "
                "rotacion automatica (las cuentas correran sin proxy)."
            )
        if pc2.button("Recargar proxies"):
            st.rerun()

        # Seleccion explicita de cuentas a procesar. Vacio = todas (respeta el
        # filtro por modo de arriba). Cada opcion es el Correo o Usuario de la fila.
        opciones_cuentas = _opciones_cuentas(leer_excel(RUTA_EXCEL))
        cuentas_sel = st.multiselect(
            "Cuentas a procesar (vacio = todas las del modo elegido)",
            opciones_cuentas,
            help="Marca cuentas concretas para revisar/apostar solo esas (Review Selected).",
        )

        st.markdown("**Tareas por cuenta**")
        t1, t2, t3, t4 = st.columns(4)
        t_bonos = t1.checkbox("Verificar bonos", value=True)
        t_limite = t2.checkbox("Verificar apuesta maxima", value=True)
        t_ap_bono = t3.checkbox("Apostar bono", value=False)
        t_ap_saldo = t4.checkbox("Apostar saldo", value=False)

        st.markdown("**Monto de apuesta** (solo para Apostar bono/saldo)")
        a1, a2 = st.columns(2)
        modo_monto = a1.selectbox("Modo de monto", ["fijo", "porcentaje"], index=0)
        valor_monto = a2.number_input(
            "Valor (COP si fijo, % del saldo si porcentaje)", min_value=0.0, value=2000.0, step=500.0
        )

        p1, p2 = st.columns(2)
        pausa_min = p1.number_input("Pausa min (min)", min_value=0.0, value=4.0, step=0.5)
        pausa_max = p2.number_input("Pausa max (min)", min_value=0.0, value=12.0, step=0.5)

        st.markdown("**Rotacion de IP movil (ADB / celular por USB)**")
        rotar_ip = st.checkbox(
            "Rotar IP antes de cada cuenta (login o registro)", value=True,
            help="Antes de procesar cada cuenta: activa modo avion 5-10s y reactiva "
                 "datos moviles para obtener IP nueva. Requiere celular Android por USB "
                 "con depuracion USB y ADB instalado. Si no hay celular/ADB, se omite "
                 "automaticamente sin fallar.",
        )

    tareas = []
    if t_bonos:
        tareas.append("bonos")
    if t_limite:
        tareas.append("apuesta_maxima")
    if t_ap_bono:
        tareas.append("apostar_bono")
    if t_ap_saldo:
        tareas.append("apostar_saldo")

    # --- Preflight: valida datos y entorno antes de permitir iniciar ---
    from preflight import validar_datos, chromium_disponible

    errores, avisos = validar_datos(leer_excel(RUTA_EXCEL), filtro)
    for msg in errores:
        st.error(msg)
    for msg in avisos:
        st.warning(msg)
    if usar_gestor and not chromium_disponible():
        errores.append("Chromium no está instalado (ejecuta: playwright install chromium).")
        st.error("Chromium de Playwright no encontrado. Ejecuta: `playwright install chromium`.")
    if not errores and not avisos:
        st.caption("Preflight OK: la lista tiene cuentas procesables.")

    # --- Botones de control ---
    b1, b2, b3 = st.columns(3)
    if b1.button("Iniciar", type="primary", disabled=activo or bool(errores)):
        iniciar_bot({
            "filtro_modo": filtro,
            "usar_gestor": bool(usar_gestor),
            "pausa_min": float(pausa_min),
            "pausa_max": float(pausa_max),
            "tareas": tareas,
            "apuesta": {"modo": modo_monto, "valor": float(valor_monto)},
            "cuentas_seleccionadas": cuentas_sel,
            "rotar_ip": bool(rotar_ip),
        })
        st.rerun()

    if b2.button("Detener (al terminar la cuenta)", disabled=not activo):
        detener_bot()
        st.warning("Detencion solicitada; el bot parara al terminar la cuenta actual.")

    estado_actual = estado.get("estado")
    esperando = estado_actual in ("esperando_captcha", "esperando_apuesta")
    etiqueta_cont = (
        "Continuar (apuesta lista)" if estado_actual == "esperando_apuesta"
        else "Continuar (CAPTCHA resuelto)"
    )
    if b3.button(etiqueta_cont, type="primary", disabled=not esperando):
        control.pedir_continuar()
        st.success("Senal enviada; el bot continuara.")

    cf1, cf2 = st.columns(2)
    if cf1.button("Forzar parada", disabled=not bot_proceso_vivo()):
        forzar_parada()
        st.warning("Proceso terminado a la fuerza.")
    if cf2.button("Generar reporte parcial"):
        ruta = generar_reporte_parcial()
        if ruta:
            st.success(f"Reporte parcial guardado: {ruta}")
        else:
            st.info("Aun no hay resultados para copiar (falta cuentas_actualizadas.xlsx).")

    st.divider()

    # --- Estado en vivo ---
    st.subheader("Estado en vivo")
    if estado_actual == "esperando_captcha":
        st.warning("El bot espera que resuelvas el reCAPTCHA en el navegador. "
                   "Cuando termines, pulsa 'Continuar (CAPTCHA resuelto)'.")
    elif estado_actual == "esperando_apuesta":
        st.warning("El bot dejo una apuesta PREPARADA. Revisala en el navegador y pulsa "
                   "'Continuar (apuesta lista)' para confirmarla a mano.")

    m1, m2, m3 = st.columns(3)
    m1.metric("Estado", estado.get("estado", "inactivo"))
    total = int(estado.get("total", 0) or 0)
    indice = int(estado.get("indice", 0) or 0)
    m2.metric("Progreso", f"{indice + 1 if total else 0}/{total}")
    m3.metric("Cuenta actual", str(estado.get("cuenta", "") or "-"))

    if total:
        st.progress(min((indice + 1) / total, 1.0))

    st.caption(f"Fase: {estado.get('fase', '-')} | {estado.get('mensaje', '')}")

    resumen = estado.get("resumen") or {}
    if resumen:
        st.write("Resumen:", "  ".join(f"{k}={v}" for k, v in sorted(resumen.items())))

    with st.expander("Log del bot (bot.log)", expanded=True):
        st.code(cola_log(control.LOG_BOT, 40) or "(sin log todavia)", language="text")
    consola = cola_log(LOG_CONSOLA, 15)
    if consola and not bot_proceso_vivo() and estado.get("estado") not in ("finalizado", "detenido"):
        with st.expander("Salida de consola del bot (posible error de arranque)"):
            st.code(consola, language="text")

    # --- Auto-refresco mientras el bot trabaja ---
    auto = st.toggle("Auto-refrescar (cada 3 s)", value=True)
    if auto and bot_activo(estado):
        time.sleep(3)
        st.rerun()


# ---------------------------------------------------------------------------
# PESTANA: RESULTADOS
# ---------------------------------------------------------------------------

def tab_resultados() -> None:
    st.subheader("Resultados")

    fuentes = {
        "Resultados del bot (cuentas_actualizadas.xlsx)": ("excel", RUTA_RESULTADOS),
        "Historial (historial_auditoria.csv)": ("csv", RUTA_HISTORIAL),
        "Cuentas (cuentas.xlsx)": ("excel", RUTA_EXCEL),
    }
    eleccion = st.selectbox("Fuente de datos", list(fuentes.keys()))
    tipo, ruta = fuentes[eleccion]
    df = leer_historial() if tipo == "csv" else leer_excel(ruta)

    if df.empty:
        st.info("No hay datos en esa fuente todavia.")
        return

    # --- Resumen de registros (auditoria rapida tras corridas de registro) ---
    reg = serie_registro(df)
    es_registro = reg.isin(
        {"registro_ok", "registro_incierto", "registro_rechazado", "error_registro"}
    )
    n_reg = int(es_registro.sum())
    if n_reg:
        st.markdown("### Resumen de registros")
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Registro OK", int((reg == "registro_ok").sum()))
        r2.metric(
            "Rechazados",
            int(reg.isin({"registro_rechazado", "error_registro"}).sum()),
        )
        r3.metric("Inciertos", int((reg == "registro_incierto").sum()))
        r4.metric("Total registros", n_reg)
        st.bar_chart(reg[es_registro].value_counts())
        st.divider()

    # Filtros.
    f1, f2 = st.columns([2, 1])
    busqueda = f1.text_input("Buscar por Usuario o Correo", placeholder="Escribe para filtrar...")
    estados = ["Todos"]
    if "Estado" in df.columns:
        estados += sorted(df["Estado"].dropna().astype(str).unique().tolist())
    estado_sel = f2.selectbox("Filtrar por Estado", estados)

    df_f = df.copy()
    if busqueda:
        texto = busqueda.strip().lower()
        mask = pd.Series(False, index=df_f.index)
        for col in ("Usuario", "Correo"):
            if col in df_f.columns:
                mask |= df_f[col].astype(str).str.lower().str.contains(texto, na=False)
        df_f = df_f[mask]
    if estado_sel != "Todos" and "Estado" in df_f.columns:
        df_f = df_f[df_f["Estado"].astype(str) == estado_sel]

    # Metricas.
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total", f"{len(df_f):,}")
    if "Saldo" in df_f.columns:
        total_saldo = pd.to_numeric(df_f["Saldo"], errors="coerce").fillna(0).sum()
        c2.metric("Saldo total", f"{total_saldo:,.2f}")
    else:
        c2.metric("Saldo total", "N/D")
    c3.metric("Verificadas", f"{porcentaje_verificadas(df_f)} %")
    c4.metric("Limitadas", f"{contar_limitadas(df_f)}")

    st.divider()

    # Graficos.
    g1, g2 = st.columns(2)
    with g1:
        st.markdown("**Saldo por Estado**")
        if {"Estado", "Saldo"} <= set(df_f.columns) and not df_f.empty:
            tmp = df_f.copy()
            tmp["Saldo"] = pd.to_numeric(tmp["Saldo"], errors="coerce").fillna(0)
            st.bar_chart(tmp.groupby("Estado")["Saldo"].sum().sort_values(ascending=False),
                         width="stretch")
        else:
            st.info("Faltan columnas 'Estado'/'Saldo'.")
    with g2:
        st.markdown("**Verificadas vs no verificadas**")
        if "Verificada" in df_f.columns and not df_f.empty:
            etiquetas = (
                df_f["Verificada"].astype(str).str.strip().str.lower()
                .map({"si": "Verificada"}).fillna("No verificada")
            )
            conteo = etiquetas.value_counts().rename_axis("Categoria").reset_index(name="Cantidad")
            dona = (
                alt.Chart(conteo)
                .mark_arc(innerRadius=70)
                .encode(
                    theta=alt.Theta("Cantidad:Q", stack=True),
                    color=alt.Color("Categoria:N", scale=alt.Scale(
                        domain=["Verificada", "No verificada"], range=["#2ecc71", "#e57373"])),
                    tooltip=["Categoria:N", "Cantidad:Q"],
                )
            )
            st.altair_chart(dona, width="stretch")
        else:
            st.info("Falta la columna 'Verificada'.")

    st.divider()

    # Tabla + exportacion.
    mostrar_sensibles = st.toggle("Mostrar columnas sensibles", value=False)
    columnas = [c for c in df_f.columns if mostrar_sensibles or c not in COLUMNAS_SENSIBLES]
    vista = df_f[columnas]
    st.dataframe(vista, width="stretch", hide_index=True)

    e1, e2 = st.columns(2)
    e1.download_button("Descargar CSV", vista.to_csv(index=False).encode("utf-8-sig"),
                       "resultados.csv", "text/csv")
    e2.download_button("Descargar Excel", to_excel_bytes(vista),
                       "resultados.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ---------------------------------------------------------------------------
# PESTANA: REGISTRAR (alta de una cuenta nueva con formulario)
# ---------------------------------------------------------------------------

def _anexar_cuenta(fila: dict) -> int:
    """Agrega una fila a cuentas.xlsx conservando las columnas existentes.

    Devuelve el numero total de cuentas tras el alta.
    """
    df = leer_excel(RUTA_EXCEL)
    if df.empty:
        df = pd.DataFrame(columns=COLUMNAS_PLANTILLA)
    # Garantizamos que existan todas las columnas que toca la fila nueva.
    for col in fila:
        if col not in df.columns:
            df[col] = ""
    df = pd.concat([df, pd.DataFrame([fila])], ignore_index=True)
    df.to_excel(RUTA_EXCEL, index=False)
    return len(df)


def tab_registrar() -> None:
    st.subheader("Registrar una cuenta nueva")
    st.caption(
        "Crea una cuenta nueva en Betplay con perfil aislado y comportamiento "
        "humano. Se agrega a cuentas.xlsx con Modo = registro; luego inicia la "
        "corrida desde la pestana Control (el bot resolvera el reCAPTCHA con tu "
        "ayuda y el 2FA por correo automaticamente)."
    )

    with st.form("form_registrar", clear_on_submit=False):
        st.markdown("**Datos de la cuenta**")
        c1, c2 = st.columns(2)
        correo = c1.text_input("Correo *", placeholder="cuenta@gmail.com")
        clave_correo = c2.text_input(
            "Clave del correo (app password) *", type="password",
            help="Contrasena de aplicacion del buzon, para leer el codigo 2FA por IMAP.",
        )
        c3, c4 = st.columns(2)
        password = c3.text_input("Password de Betplay *", type="password")
        nombre = c4.text_input("Nombre (etiqueta)", placeholder="Cuenta Juan")

        st.markdown("**Datos personales (para el registro)**")
        d1, d2, d3 = st.columns(3)
        cedula = d1.text_input("Cedula")
        primer_nombre = d2.text_input("Primer nombre")
        primer_apellido = d3.text_input("Primer apellido")

        e1, e2 = st.columns(2)
        telefono = e1.text_input("Telefono")
        lugar_exp = e2.text_input("Lugar de expedicion", value="BOGOTA")

        st.markdown("**Fecha de expedicion de la cedula**")
        f1, f2, f3 = st.columns(3)
        exp_dd = f1.text_input("Dia (DD)", value="15", key="exp_dd")
        exp_mm = f2.text_input("Mes (MM)", value="06", key="exp_mm")
        exp_yyyy = f3.text_input("Ano (YYYY)", value="1995", key="exp_yyyy")

        st.markdown("**Fecha de nacimiento**")
        g1, g2, g3 = st.columns(3)
        nac_dd = g1.text_input("Dia (DD)", value="10", key="nac_dd")
        nac_mm = g2.text_input("Mes (MM)", value="03", key="nac_mm")
        nac_yyyy = g3.text_input("Ano (YYYY)", value="1995", key="nac_yyyy")

        st.markdown("**Navegador / red**")
        h1, h2 = st.columns(2)
        puerto = h1.number_input("Puerto CDP", min_value=0, value=9222, step=1)
        proxy = h2.text_input(
            "Proxy (opcional)", placeholder="host:puerto",
            help="Para rotacion de IP. Se pasa a Chrome como --proxy-server.",
        )

        enviado = st.form_submit_button("Agregar cuenta a la lista", type="primary")

    if enviado:
        if not (correo and clave_correo and password):
            st.error("Correo, clave del correo y password de Betplay son obligatorios.")
            return
        fila = {
            "Usuario": correo,
            "Password": password,
            "Nombre": nombre or correo,
            "Correo": correo,
            "ClaveCorreo": clave_correo,
            "Puerto": int(puerto),
            "Modo": "registro",
            "Cedula": cedula,
            "PrimerNombre": primer_nombre,
            "PrimerApellido": primer_apellido,
            "Telefono": telefono,
            "LugarExpedicion": lugar_exp,
            "ExpedicionDD": exp_dd, "ExpedicionMM": exp_mm, "ExpedicionYYYY": exp_yyyy,
            "NacimientoDD": nac_dd, "NacimientoMM": nac_mm, "NacimientoYYYY": nac_yyyy,
            "Proxy": proxy,
        }
        try:
            total = _anexar_cuenta(fila)
            st.success(
                f"Cuenta '{correo}' agregada (Modo = registro). "
                f"Ahora hay {total} cuenta(s). Ve a Control para iniciar la corrida."
            )
        except Exception as exc:  # noqa: BLE001
            st.error(f"No se pudo guardar la cuenta: {exc}")

    st.divider()
    st.markdown("**Cuentas en modo registro pendientes**")
    df = leer_excel(RUTA_EXCEL)
    if not df.empty and "Modo" in df.columns:
        pendientes = df[df["Modo"].astype(str).str.strip().str.lower() == "registro"]
        if not pendientes.empty:
            cols = [c for c in ("Nombre", "Correo", "Telefono", "Puerto") if c in pendientes.columns]
            st.dataframe(pendientes[cols] if cols else pendientes, width="stretch", hide_index=True)
        else:
            st.info("No hay cuentas en modo registro todavia.")
    else:
        st.info("Aun no hay cuentas guardadas.")


# ---------------------------------------------------------------------------
# APP
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title="Automatizador Betplay", layout="wide")
    st.title("Automatizador Betplay - Panel de control")

    t1, t2, t3, t4, t5 = st.tabs(
        ["Cuentas", "Registrar", "Crear Masivas", "Control", "Resultados"]
    )
    with t1:
        tab_cuentas()
    with t2:
        tab_registrar()
    with t3:
        tab_crear_cuentas()
    with t4:
        tab_control()
    with t5:
        tab_resultados()


if __name__ == "__main__":
    main()
