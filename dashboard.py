"""
dashboard.py
============

Interfaz gráfica local (Dashboard) con Streamlit para administrar y visualizar
el inventario de registros de auditoría (cuentas.xlsx).

Funciones:
    1. Carga de datos vía st.file_uploader.
    2. Panel de métricas (st.metric): total de usuarios, suma de 'Saldo' y
       % de cuentas verificadas.
    3. Buscador (por 'Usuario' o 'Correo') + filtro por 'Estado'.
    4. Exportación de la tabla filtrada a CSV o Excel.

Instalación:
    pip install streamlit pandas openpyxl

Ejecución (abre el navegador automáticamente en http://localhost:8501):
    streamlit run dashboard.py
"""

from __future__ import annotations

import io
import os

import altair as alt
import pandas as pd
import streamlit as st

# Columnas que contienen datos sensibles: se ocultan por defecto en la vista.
COLUMNAS_SENSIBLES = ["Password"]

# Ruta del Excel local donde se persisten las ediciones.
RUTA_EXCEL = "cuentas.xlsx"

# Cargar preferentemente el historial de auditoría
RUTA_HISTORIAL = "historial_auditoria.csv"

@st.cache_data(show_spinner=False)
def cargar_historial() -> pd.DataFrame:
    """Carga historial_auditoria.csv si existe; si no, DataFrame vacío."""
    if os.path.exists(RUTA_HISTORIAL):
        return pd.read_csv(RUTA_HISTORIAL)
    return pd.DataFrame()


# ---------------------------------------------------------------------------
# UTILIDADES
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def cargar_excel(contenido: bytes) -> pd.DataFrame:
    """Lee el Excel cargado (en bytes) y devuelve un DataFrame."""
    return pd.read_excel(io.BytesIO(contenido))


def calcular_porcentaje_verificadas(df: pd.DataFrame) -> float:
    """Devuelve el % de filas con Verificada == 'si' (sin distinguir mayúsculas)."""
    if "Verificada" not in df.columns or len(df) == 0:
        return 0.0
    verificadas = df["Verificada"].astype(str).str.strip().str.lower().eq("si").sum()
    return round(verificadas / len(df) * 100, 1)


def _contar_limitadas(df: pd.DataFrame) -> int:
    """Cuenta filas con Limitada verdadero, tolerando bool o texto (True/si/1)."""
    if "Limitada" not in df.columns:
        return 0
    valores = df["Limitada"].astype(str).str.strip().str.lower()
    return int(valores.isin(["true", "si", "sí", "1", "limitada"]).sum())


def to_excel_bytes(df: pd.DataFrame) -> bytes:
    """Serializa un DataFrame a bytes de Excel para el botón de descarga."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Auditoria")
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# INTERFAZ
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title="Auditoría — Dashboard", page_icon="📊", layout="wide")
    st.title("📊 Dashboard de Auditoría de Cuentas")
    st.caption("Visualiza el archivo cuentas.xlsx subido o el historial de auditoría.")

    # --- 1) Fuente de datos --------------------------------------------------
    fuente = st.radio(
        "Fuente de datos",
        ["Archivo subido (cuentas.xlsx)", "Historial de auditoría (historial_auditoria.csv)"],
        horizontal=True,
    )
    usando_historial = fuente.startswith("Historial")

    if usando_historial:
        # Vista de SOLO LECTURA del historial generado por el auditor.
        df = cargar_historial()
        if df.empty:
            st.info(
                "No hay historial todavía. Ejecuta el auditor para generar "
                "historial_auditoria.csv."
            )
            return
        st.caption(f"📜 Mostrando el historial de auditoría: {len(df)} registro(s).")
    else:
        archivo = st.file_uploader("Cargar archivo Excel (cuentas.xlsx)", type=["xlsx"])
        if archivo is None:
            st.info("Esperando que cargues un archivo .xlsx para mostrar el panel.")
            return

        # Carga el archivo a session_state UNA sola vez por archivo subido. Así las
        # ediciones posteriores persisten entre reruns y no las pisa la caché.
        file_id = f"{archivo.name}:{len(archivo.getvalue())}"
        if st.session_state.get("file_id") != file_id:
            try:
                st.session_state.df = cargar_excel(archivo.getvalue())
            except Exception as exc:  # noqa: BLE001
                st.error(f"No se pudo leer el archivo: {exc}")
                return
            st.session_state.file_id = file_id

        df = st.session_state.df
        if df.empty:
            st.warning("El archivo se cargó pero no contiene filas.")
            return

    # --- 2) Buscador y filtros (se aplican a métricas, gráficos y tabla) -----
    st.subheader("Buscar y filtrar")
    f1, f2 = st.columns([2, 1])

    busqueda = f1.text_input("🔍 Buscar por Usuario o Correo", placeholder="Escribe para filtrar...")

    estados = ["Todos"]
    if "Estado" in df.columns:
        estados += sorted(df["Estado"].dropna().astype(str).unique().tolist())
    estado_sel = f2.selectbox("Filtrar por Estado", estados)

    # Aplica los filtros sobre una copia. Todo lo que sigue (métricas, gráficos
    # y tabla) usa este df_filtrado, así que se recalcula al cambiar el filtro.
    df_filtrado = df.copy()

    if busqueda:
        texto = busqueda.strip().lower()
        mask = pd.Series(False, index=df_filtrado.index)
        for col in ("Usuario", "Correo"):
            if col in df_filtrado.columns:
                mask |= df_filtrado[col].astype(str).str.lower().str.contains(texto, na=False)
        df_filtrado = df_filtrado[mask]

    if estado_sel != "Todos" and "Estado" in df_filtrado.columns:
        df_filtrado = df_filtrado[df_filtrado["Estado"].astype(str) == estado_sel]

    st.caption(f"Filtro activo: **{len(df_filtrado)}** de **{len(df)}** registros.")
    st.divider()

    # --- 3) Panel de métricas (sobre los datos filtrados) -------------------
    st.subheader("Resumen")
    col1, col2, col3, col4 = st.columns(4)

    col1.metric("👥 Total de usuarios", f"{len(df_filtrado):,}")

    if "Saldo" in df_filtrado.columns:
        saldo_total = pd.to_numeric(df_filtrado["Saldo"], errors="coerce").fillna(0).sum()
        col2.metric("💰 Saldo total", f"{saldo_total:,.2f}")
    else:
        col2.metric("💰 Saldo total", "N/D")

    col3.metric("✅ Cuentas verificadas", f"{calcular_porcentaje_verificadas(df_filtrado)} %")

    col4.metric("🚫 Cuentas Limitadas", f"{_contar_limitadas(df_filtrado)}")

    st.divider()

    # --- 4) Análisis gráfico (reacciona a los filtros) ----------------------
    st.subheader("Análisis gráfico")
    g1, g2 = st.columns(2)

    with g1:
        st.markdown("**Saldo total por Estado**")
        if {"Estado", "Saldo"} <= set(df_filtrado.columns) and not df_filtrado.empty:
            tmp = df_filtrado.copy()
            tmp["Saldo"] = pd.to_numeric(tmp["Saldo"], errors="coerce").fillna(0)
            saldo_por_estado = (
                tmp.groupby("Estado")["Saldo"].sum().sort_values(ascending=False)
            )
            st.bar_chart(saldo_por_estado)
        else:
            st.info("Sin datos suficientes (faltan 'Estado'/'Saldo' o no hay filas).")

    with g2:
        st.markdown("**Cuentas verificadas vs. no verificadas**")
        if "Verificada" in df_filtrado.columns and not df_filtrado.empty:
            etiquetas = (
                df_filtrado["Verificada"].astype(str).str.strip().str.lower()
                .map({"si": "Verificada"}).fillna("No verificada")
            )
            # DataFrame con dos columnas (Categoria, Cantidad) para Altair.
            conteo = (
                etiquetas.value_counts()
                .rename_axis("Categoria")
                .reset_index(name="Cantidad")
            )

            # Dona: mark_arc con innerRadius > 0 deja el centro vacío.
            dona = (
                alt.Chart(conteo)
                .mark_arc(innerRadius=70)
                .encode(
                    theta=alt.Theta("Cantidad:Q", stack=True),
                    color=alt.Color(
                        "Categoria:N",
                        scale=alt.Scale(
                            domain=["Verificada", "No verificada"],
                            range=["#2ecc71", "#e57373"],  # verde / rojo claro
                        ),
                        legend=alt.Legend(title="Verificación"),
                    ),
                    tooltip=[
                        alt.Tooltip("Categoria:N", title="Categoría"),
                        alt.Tooltip("Cantidad:Q", title="Cuentas"),
                    ],
                )
            )
            st.altair_chart(dona, use_container_width=True)
        else:
            st.info("Sin datos suficientes (falta 'Verificada' o no hay filas).")

    st.divider()

    # --- 5) Tabla de detalle -------------------------------------------------
    # Oculta columnas sensibles salvo que el usuario lo active explícitamente.
    mostrar_sensibles = st.toggle("Mostrar columnas sensibles (Password)", value=False)
    columnas_vista = [
        c for c in df_filtrado.columns
        if mostrar_sensibles or c not in COLUMNAS_SENSIBLES
    ]
    df_vista = df_filtrado[columnas_vista]

    st.write(f"Mostrando **{len(df_vista)}** de **{len(df)}** registros.")
    st.dataframe(df_vista, use_container_width=True, hide_index=True)

    # --- 5b) Edición de registros (persiste en el Excel local) --------------
    st.divider()
    st.subheader("✏️ Editar registro")

    if usando_historial:
        st.info("La edición solo aplica al archivo cuentas.xlsx subido, no al historial (solo lectura).")
    elif "Usuario" not in df.columns:
        st.info("No hay columna 'Usuario' para seleccionar registros.")
    else:
        # Lista todos los usuarios del DataFrame cargado (no solo los filtrados).
        usuarios = df["Usuario"].astype(str).tolist()
        usuario_sel = st.selectbox("Selecciona un usuario para modificar", usuarios)

        # Localiza la fila (primera coincidencia si hubiera usuarios repetidos).
        idx = df.index[df["Usuario"].astype(str) == usuario_sel][0]
        fila = df.loc[idx]

        with st.form("form_edicion"):
            # Saldo: precargado y convertido a float de forma segura.
            saldo_actual = pd.to_numeric(
                pd.Series([fila.get("Saldo", 0.0)]), errors="coerce"
            ).fillna(0.0).iloc[0]
            nuevo_saldo = st.number_input(
                "Saldo", value=float(saldo_actual), step=1.0, format="%.2f"
            )

            # Verificada: selector si/no, precargado con el valor actual.
            opciones_ver = ["si", "no"]
            ver_actual = str(fila.get("Verificada", "no")).strip().lower()
            idx_ver = opciones_ver.index(ver_actual) if ver_actual in opciones_ver else 1
            nueva_ver = st.selectbox("Verificada", opciones_ver, index=idx_ver)

            # Estado / nota de control: opciones base + el valor actual si no está.
            opciones_estado = ["Activa", "Limitada", "Revisar", "pendiente"]
            estado_actual = str(fila.get("Estado", "")).strip()
            if estado_actual and estado_actual not in opciones_estado:
                opciones_estado = [estado_actual] + opciones_estado
            idx_est = (
                opciones_estado.index(estado_actual)
                if estado_actual in opciones_estado else 0
            )
            nuevo_estado = st.selectbox("Estado", opciones_estado, index=idx_est)

            guardar = st.form_submit_button("💾 Guardar Cambios")

        if guardar:
            # 1) Modifica la fila en el DataFrame en memoria (session_state).
            st.session_state.df.loc[idx, "Saldo"] = nuevo_saldo
            st.session_state.df.loc[idx, "Verificada"] = nueva_ver
            st.session_state.df.loc[idx, "Estado"] = nuevo_estado

            # 2) Guarda el DataFrame de regreso en el Excel local.
            try:
                st.session_state.df.to_excel(RUTA_EXCEL, index=False)
            except Exception as exc:  # noqa: BLE001
                st.error(f"No se pudo guardar el Excel: {exc}")
            else:
                # 3) Éxito + rerun: métricas y gráficos se recalculan al instante.
                st.success("Registro actualizado correctamente")
                st.rerun()

    # --- 6) Exportación ------------------------------------------------------
    st.subheader("Exportar tabla filtrada")
    e1, e2 = st.columns(2)

    e1.download_button(
        label="⬇️ Descargar CSV",
        data=df_vista.to_csv(index=False).encode("utf-8-sig"),
        file_name="auditoria_filtrada.csv",
        mime="text/csv",
    )

    e2.download_button(
        label="⬇️ Descargar Excel",
        data=to_excel_bytes(df_vista),
        file_name="auditoria_filtrada.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


if __name__ == "__main__":
    main()
