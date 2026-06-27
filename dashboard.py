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

# Esquema base para crear una lista de cuentas desde cero.
COLUMNAS_PLANTILLA = [
    "Usuario", "Password", "Nombre", "Correo", "ClaveCorreo", "Puerto", "Modo",
    "Cedula", "PrimerNombre", "PrimerApellido", "Telefono",
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


def to_excel_bytes(df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Resultados")
    return buffer.getvalue()


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

    editado = st.data_editor(df, num_rows="dynamic", width="stretch", key="editor_cuentas")

    if st.button("Guardar cuentas", type="primary"):
        try:
            editado.to_excel(RUTA_EXCEL, index=False)
            st.success(f"Guardado {RUTA_EXCEL} ({len(editado)} cuenta(s)).")
        except Exception as exc:  # noqa: BLE001
            st.error(f"No se pudo guardar: {exc}")


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

    tareas = []
    if t_bonos:
        tareas.append("bonos")
    if t_limite:
        tareas.append("apuesta_maxima")
    if t_ap_bono:
        tareas.append("apostar_bono")
    if t_ap_saldo:
        tareas.append("apostar_saldo")

    # --- Botones de control ---
    b1, b2, b3 = st.columns(3)
    if b1.button("Iniciar", type="primary", disabled=activo):
        iniciar_bot({
            "filtro_modo": filtro,
            "usar_gestor": bool(usar_gestor),
            "pausa_min": float(pausa_min),
            "pausa_max": float(pausa_max),
            "tareas": tareas,
            "apuesta": {"modo": modo_monto, "valor": float(valor_monto)},
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
# APP
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title="Automatizador Betplay", layout="wide")
    st.title("Automatizador Betplay - Panel de control")

    t1, t2, t3 = st.tabs(["Cuentas", "Control", "Resultados"])
    with t1:
        tab_cuentas()
    with t2:
        tab_control()
    with t3:
        tab_resultados()


if __name__ == "__main__":
    main()
