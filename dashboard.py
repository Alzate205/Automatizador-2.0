"""
dashboard.py v3.0 - Panel de Control Mejorado Betplay
======================================================

Panel de control ULTRA-FÁCIL de usar para el Automatizador Betplay (Streamlit).

CARACTERÍSTICAS PRINCIPALES:
    ✅ Interfaz simplificada e intuitiva
    ✅ Reporte detallado de apuestas realizadas
    ✅ Métricas en tiempo real con gráficos
    ✅ Historial completo de operaciones
    ✅ Control del loop infinito
    ✅ Alertas visuales de eventos importantes
    ✅ Vista de "Qué hizo el bot hoy" - perfecto para revisar al llegar a casa

INSTALACIÓN:
    pip install streamlit pandas openpyxl altair plotly

EJECUCIÓN:
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
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import altair as alt
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

import control

# ============================================================================
# CONFIGURACIÓN GLOBAL
# ============================================================================

RUTA_EXCEL = "cuentas.xlsx"
RUTA_RESULTADOS = "cuentas_actualizadas.xlsx"
RUTA_HISTORIAL = "historial_auditoria.csv"
LOG_CONSOLA = "bot_consola.log"
RUTA_REPORTES_APUESTAS = "reportes_apuestas.json"

COLUMNAS_SENSIBLES = ["Password", "ClaveCorreo"]

COLUMNAS_PLANTILLA = [
    "Modo", "Nombre", "Usuario", "ClaveCorreo", "Puerto",
    "Cedula",
    "ExpedicionDD", "ExpedicionMM", "ExpedicionYYYY",
    "LugarExpedicion",
    "NacimientoDD", "NacimientoMM", "NacimientoYYYY",
    "PrimerNombre", "SegundoNombre", "PrimerApellido", "SegundoApellido",
    "Genero", "Telefono", "Correo",
    "TipoVia", "Direccion1", "Direccion2", "Direccion3", "Ciudad",
    "Password",
]

# Colores del tema
COLOR_EXITO = "#2ecc71"
COLOR_ERROR = "#e74c3c"
COLOR_ADVERTENCIA = "#f39c12"
COLOR_INFO = "#3498db"
COLOR_PRIMARIO = "#9b59b6"

# ============================================================================
# UTILIDADES DE DATOS
# ============================================================================

def leer_excel(ruta: str) -> pd.DataFrame:
    """Lee un Excel local; DataFrame vacío si no existe o falla."""
    if not os.path.exists(ruta):
        return pd.DataFrame()
    try:
        return pd.read_excel(ruta)
    except Exception:
        return pd.DataFrame()


def generar_plantilla_registro(n: int = 10) -> pd.DataFrame:
    """Genera una plantilla de n cuentas en modo registro."""
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
    except Exception:
        return pd.DataFrame()


def leer_reportes_apuestas() -> List[Dict]:
    """Lee el archivo JSON con reportes detallados de apuestas."""
    if not os.path.exists(RUTA_REPORTES_APUESTAS):
        return []
    try:
        with open(RUTA_REPORTES_APUESTAS, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def guardar_reporte_apuesta(reporte: Dict) -> None:
    """Guarda un reporte de apuesta en el archivo JSON."""
    import json
    reportes = leer_reportes_apuestas()
    reportes.append(reporte)
    # Mantener solo últimos 500 reportes
    if len(reportes) > 500:
        reportes = reportes[-500:]
    with open(RUTA_REPORTES_APUESTAS, "w", encoding="utf-8") as f:
        json.dump(reportes, f, ensure_ascii=False, indent=2)


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
    """Estado de registro por fila, normalizado a minúsculas."""
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
    """Identificadores (Correo o Usuario) de cada fila."""
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
    except Exception:
        return ""


def formatear_moneda(valor: float) -> str:
    """Formatea un valor como moneda COP."""
    return f"${valor:,.0f} COP"


def formatear_fecha(fecha_str: str) -> str:
    """Formatea una fecha para mostrar."""
    try:
        fecha = datetime.fromisoformat(fecha_str.replace("Z", "+00:00"))
        return fecha.strftime("%d/%m %H:%M")
    except Exception:
        return fecha_str


# ============================================================================
# CONTROL DEL BOT
# ============================================================================

def bot_proceso_vivo() -> bool:
    proc = st.session_state.get("bot_proc")
    return proc is not None and proc.poll() is None


def bot_activo(estado: dict) -> bool:
    """True si el bot esta trabajando."""
    return (
        estado.get("estado") in ("corriendo", "esperando_captcha", "esperando_apuesta")
        or bot_proceso_vivo()
    )


def generar_reporte_parcial() -> str:
    """Copia el Excel de resultados a un archivo con timestamp."""
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


# ============================================================================
# ESTILOS CSS PERSONALIZADOS
# ============================================================================

def inject_custom_css():
    """Inyecta CSS personalizado para mejorar la apariencia."""
    st.markdown("""
    <style>
    /* Tarjetas de métricas */
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 15px;
        padding: 20px;
        color: white;
        text-align: center;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    }
    .metric-value {
        font-size: 2.5em;
        font-weight: bold;
        margin: 10px 0;
    }
    .metric-label {
        font-size: 0.9em;
        opacity: 0.9;
    }
    
    /* Alertas personalizadas */
    .alert-success {
        background-color: #d4edda;
        border-left: 5px solid #28a745;
        padding: 15px;
        border-radius: 5px;
        margin: 10px 0;
    }
    .alert-warning {
        background-color: #fff3cd;
        border-left: 5px solid #ffc107;
        padding: 15px;
        border-radius: 5px;
        margin: 10px 0;
    }
    .alert-error {
        background-color: #f8d7da;
        border-left: 5px solid #dc3545;
        padding: 15px;
        border-radius: 5px;
        margin: 10px 0;
    }
    .alert-info {
        background-color: #d1ecf1;
        border-left: 5px solid #17a2b8;
        padding: 15px;
        border-radius: 5px;
        margin: 10px 0;
    }
    
    /* Botones grandes */
    .stButton > button {
        width: 100%;
        border-radius: 10px;
        font-weight: bold;
        padding: 10px 20px;
    }
    
    /* Tabs personalizados */
    .stTabs [data-baseweb="tab-list"] {
        gap: 10px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 10px;
        padding: 10px 20px;
    }
    
    /* Ocultar footer de Streamlit */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)


# ============================================================================
# PESTAÑA: QUÉ HIZO EL BOT HOY (Resumen diario de apuestas)
# ============================================================================

def tab_que_hizo_hoy() -> None:
    """Muestra un resumen claro de lo que el bot hizo hoy - ideal para revisar al llegar a casa."""
    st.subheader("📊 ¿Qué hizo el bot hoy?")
    st.caption("Resumen automático de todas las operaciones realizadas en la última sesión")
    
    # Leer reportes de apuestas
    reportes = leer_reportes_apuestas()
    
    # Filtrar solo los de hoy
    hoy = datetime.now().date()
    reportes_hoy = []
    for rep in reportes:
        try:
            fecha_rep = datetime.fromisoformat(rep.get("fecha", "")).date()
            if fecha_rep == hoy:
                reportes_hoy.append(rep)
        except Exception:
            continue
    
    # Métricas principales del día
    m1, m2, m3, m4, m5 = st.columns(5)
    
    total_apuestas = len(reportes_hoy)
    apuestas_ganadas = sum(1 for r in reportes_hoy if r.get("resultado") == "ganada")
    apuestas_perdidas = sum(1 for r in reportes_hoy if r.get("resultado") == "perdida")
    total_apostado = sum(float(r.get("monto_apostado", 0)) for r in reportes_hoy)
    bonos_activados = sum(1 for r in reportes_hoy if r.get("tipo", "") == "bono")
    
    m1.metric("🎯 Apuestas Totales", f"{total_apuestas}")
    m2.metric("✅ Ganadas", f"{apuestas_ganadas}", delta=f"{apuestas_ganadas/total_apuestas*100:.1f}%" if total_apuestas > 0 else "0%")
    m3.metric("❌ Perdidas", f"{apuestas_perdidas}")
    m4.metric("💰 Total Apostado", formatear_moneda(total_apostado))
    m5.metric("🎁 Bonos Usados", f"{bonos_activados}")
    
    st.divider()
    
    # Gráfico de distribución por deporte
    if reportes_hoy:
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.markdown("### 📝 Detalle de Apuestas Realizadas")
            
            # Crear DataFrame para mostrar
            df_apuestas = pd.DataFrame(reportes_hoy)
            
            if not df_apuestas.empty:
                # Columnas a mostrar
                cols_mostrar = []
                if "cuenta" in df_apuestas.columns:
                    cols_mostrar.append("cuenta")
                if "deporte" in df_apuestas.columns:
                    cols_mostrar.append("deporte")
                if "evento" in df_apuestas.columns:
                    cols_mostrar.append("evento")
                if "tipo_apuesta" in df_apuestas.columns:
                    cols_mostrar.append("tipo_apuesta")
                if "monto_apostado" in df_apuestas.columns:
                    cols_mostrar.append("monto_apostado")
                if "cuota" in df_apuestas.columns:
                    cols_mostrar.append("cuota")
                if "resultado" in df_apuestas.columns:
                    cols_mostrar.append("resultado")
                if "hora" in df_apuestas.columns:
                    cols_mostrar.append("hora")
                
                if cols_mostrar:
                    df_display = df_apuestas[cols_mostrar].copy()
                    
                    # Formatear columnas
                    if "monto_apostado" in df_display.columns:
                        df_display["monto_apostado"] = df_display["monto_apostado"].apply(
                            lambda x: formatear_moneda(float(x)) if pd.notna(x) else ""
                        )
                    if "cuota" in df_display.columns:
                        df_display["cuota"] = df_display["cuota"].apply(
                            lambda x: f"{float(x):.2f}" if pd.notna(x) else ""
                        )
                    if "hora" in df_display.columns:
                        df_display["hora"] = df_display["hora"].apply(
                            lambda x: formatear_fecha(x) if pd.notna(x) and x else ""
                        )
                    
                    # Renombrar columnas para mostrar
                    nombres_columnas = {
                        "cuenta": "Cuenta",
                        "deporte": "Deporte",
                        "evento": "Evento",
                        "tipo_apuesta": "Tipo",
                        "monto_apostado": "Monto",
                        "cuota": "Cuota",
                        "resultado": "Resultado",
                        "hora": "Hora"
                    }
                    df_display = df_display.rename(columns=nombres_columnas)
                    
                    st.dataframe(df_display, use_container_width=True, hide_index=True)
                    
                    # Botón de exportar
                    csv_export = df_apuestas.to_csv(index=False, encoding='utf-8-sig')
                    st.download_button(
                        label="📥 Descargar detalle (CSV)",
                        data=csv_export,
                        file_name=f"apuestas_hoy_{hoy.strftime('%Y%m%d')}.csv",
                        mime="text/csv"
                    )
        
        with col2:
            st.markdown("### 📈 Distribución por Deporte")
            
            # Contar apuestas por deporte
            if "deporte" in df_apuestas.columns:
                deporte_counts = df_apuestas["deporte"].value_counts().reset_index()
                deporte_counts.columns = ["Deporte", "Cantidad"]
                
                fig_pie = px.pie(
                    deporte_counts,
                    values="Cantidad",
                    names="Deporte",
                    color_discrete_sequence=px.colors.qualitative.Set3
                )
                fig_pie.update_layout(height=400, showlegend=True)
                st.plotly_chart(fig_pie, use_container_width=True)
            
            st.markdown("### 🎯 Tipo de Apuesta")
            
            if "tipo" in df_apuestas.columns:
                tipo_counts = df_apuestas["tipo"].value_counts().reset_index()
                tipo_counts.columns = ["Tipo", "Cantidad"]
                
                fig_bar = px.bar(
                    tipo_counts,
                    x="Tipo",
                    y="Cantidad",
                    color="Tipo",
                    color_discrete_sequence=px.colors.qualitative.Bold
                )
                fig_bar.update_layout(height=300, showlegend=False)
                st.plotly_chart(fig_bar, use_container_width=True)
    
    else:
        st.info("📭 No hay apuestas registradas para hoy. Ejecuta el bot con las tareas de apuesta activadas.")
    
    # Historial de los últimos días
    st.divider()
    st.markdown("### 📅 Historial de Últimos 7 Días")
    
    if reportes:
        # Agrupar por día
        df_todos = pd.DataFrame(reportes)
        df_todos["fecha"] = pd.to_datetime(df_todos["fecha"]).dt.date
        
        grupo_dia = df_todos.groupby("fecha").agg({
            "monto_apostado": "sum",
            "cuenta": "count"
        }).reset_index()
        grupo_dia.columns = ["Fecha", "Total Apostado", "Apuestas"]
        grupo_dia["Fecha"] = grupo_dia["Fecha"].astype(str)
        grupo_dia = grupo_dia.tail(7)
        
        col_hist1, col_hist2 = st.columns(2)
        
        with col_hist1:
            fig_line = px.line(
                grupo_dia,
                x="Fecha",
                y="Apuestas",
                title="Apuestas por Día",
                markers=True
            )
            fig_line.update_traces(line_color=COLOR_PRIMARIO, marker_size=10)
            st.plotly_chart(fig_line, use_container_width=True)
        
        with col_hist2:
            fig_area = px.area(
                grupo_dia,
                x="Fecha",
                y="Total Apostado",
                title="Monto Apostado por Día",
            )
            fig_area.update_traces(line_color=COLOR_EXITO)
            st.plotly_chart(fig_area, use_container_width=True)


# ============================================================================
# PESTAÑA: CONTROL DEL LOOP INFINITO
# ============================================================================

def tab_loop_infinito() -> None:
    """Permite configurar y controlar el modo loop infinito del scheduler."""
    import scheduler_bridge
    
    st.subheader("Loop Infinito")
    st.caption("Configura ciclos automáticos de procesamiento con pausas entre ellos")
    
    # Leer configuración actual del scheduler
    config_path = "scheduler_config.json"
    config_actual = {}
    if os.path.exists(config_path):
        try:
            import json
            with open(config_path, "r", encoding="utf-8") as f:
                config_actual = json.load(f)
        except Exception:
            pass
    
    with st.form("config_loop"):
        st.markdown("### Configuración del Ciclo")
        
        c1, c2 = st.columns(2)
        
        cuentas_por_ciclo = c1.number_input(
            "Cuentas por ciclo",
            min_value=1,
            max_value=100,
            value=int(config_actual.get("cuentas_por_ciclo", 10)),
            help="Número de cuentas a procesar en cada ciclo"
        )
        
        pausa_min_horas = c2.number_input(
            "Pausa mínima entre ciclos (horas)",
            min_value=0.1,
            max_value=24.0,
            value=float(config_actual.get("pausa_min_horas", 6.0)),
            step=0.5,
            help="Tiempo mínimo de espera entre ciclos"
        )
        
        pausa_max_horas = c2.number_input(
            "Pausa máxima entre ciclos (horas)",
            min_value=0.1,
            max_value=24.0,
            value=float(config_actual.get("pausa_max_horas", 8.0)),
            step=0.5,
            help="Tiempo máximo de espera entre ciclos (aleatorio)"
        )
        
        max_ciclos = c1.number_input(
            "Máximo de ciclos (0 = infinito)",
            min_value=0,
            max_value=1000,
            value=int(config_actual.get("max_ciclos", 0)),
            help="0 significa que se ejecutará indefinidamente"
        )
        
        st.markdown("### Opciones Avanzadas")
        
        reiniciar_fallidas = st.checkbox(
            "Reintentar cuentas fallidas",
            value=config_actual.get("reiniciar_fallidas", True),
            help="Prioriza cuentas que fallaron en ciclos anteriores"
        )
        
        solo_exitosas_previas = st.checkbox(
            "Solo cuentas exitosas previas",
            value=config_actual.get("solo_exitosas_previas", False),
            help="Si está marcado, solo procesa cuentas que ya fueron exitosas"
        )
        
        enviado = st.form_submit_button("Guardar Configuración", type="primary", use_container_width=True)
        
        if enviado:
            import json
            nueva_config = {
                "cuentas_por_ciclo": int(cuentas_por_ciclo),
                "pausa_min_horas": float(pausa_min_horas),
                "pausa_max_horas": float(pausa_max_horas),
                "max_ciclos": int(max_ciclos),
                "reiniciar_fallidas": reiniciar_fallidas,
                "solo_exitosas_previas": solo_exitosas_previas,
                "ultima_actualizacion": datetime.now().isoformat()
            }
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(nueva_config, f, indent=2, ensure_ascii=False)
            st.success("Configuración guardada exitosamente")
    
    st.divider()
    
    # Estado actual del scheduler
    st.markdown("### Estado del Scheduler")
    
    # Obtener estado real del scheduler bridge
    estado_scheduler = scheduler_bridge.obtener_estado_scheduler()
    estado_formateado = scheduler_bridge.formatear_estado_para_dashboard(estado_scheduler)
    
    s1, s2, s3, s4 = st.columns(4)
    
    s1.metric(
        "Estado",
        estado_formateado["estado_texto"],
        delta=None
    )
    s2.metric(
        "Ciclo Actual",
        estado_formateado["ciclo_actual"]
    )
    s3.metric(
        "Ciclos Completados",
        estado_formateado["total_ciclos"]
    )
    
    # Mostrar configuración resumida
    s4.metric(
        "Cuentas/Ciclo",
        str(estado_scheduler.get("config", {}).get("cuentas_por_ciclo", "N/A"))
    )
    
    # Mostrar configuración completa en expander
    with st.expander("Ver configuración detallada"):
        st.code(estado_formateado["configuracion"])
    
    # Botones de control
    col_btn1, col_btn2, col_btn3 = st.columns(3)
    
    scheduler_corriendo = scheduler_bridge.esta_corriendo()
    
    with col_btn1:
        btn_iniciar = st.button(
            "Iniciar Loop",
            type="primary",
            use_container_width=True,
            disabled=scheduler_corriendo
        )
        if btn_iniciar:
            # Leer configuración
            config = config_actual or {
                "cuentas_por_ciclo": 10,
                "pausa_min_horas": 6.0,
                "pausa_max_horas": 8.0,
                "max_ciclos": 0,
                "reiniciar_fallidas": True,
                "solo_exitosas_previas": False
            }
            
            # Convertir horas a minutos para el scheduler
            exito = scheduler_bridge.iniciar_scheduler(
                cuentas_por_ciclo=config.get("cuentas_por_ciclo", 10),
                pausa_min_minutos=config.get("pausa_min_horas", 6.0) * 60,
                pausa_max_minutos=config.get("pausa_max_horas", 8.0) * 60,
                max_ciclos=config.get("max_ciclos", 0),
                reiniciar_fallidas=config.get("reiniciar_fallidas", True),
                solo_exitosas_previas=config.get("solo_exitosas_previas", False)
            )
            
            if exito:
                st.success("Scheduler iniciado correctamente")
                st.rerun()
            else:
                st.error("No se pudo iniciar el scheduler")
    
    with col_btn2:
        btn_pausar = st.button(
            "Pausar Loop",
            type="warning",
            use_container_width=True,
            disabled=not scheduler_corriendo
        )
        if btn_pausar:
            scheduler_bridge.pausar_scheduler()
            st.warning("Solicitada pausa del scheduler")
            st.rerun()
    
    with col_btn3:
        btn_detener = st.button(
            "Detener Loop",
            type="error",
            use_container_width=True,
            disabled=not scheduler_corriendo
        )
        if btn_detener:
            scheduler_bridge.detener_scheduler()
            st.error("Solicitada detención del scheduler")
            st.rerun()
    
    # Si hay botón de reanudar (cuando está pausado)
    if estado_scheduler.get("estado") == "pausado":
        col_btn4 = st.columns(1)[0]
        with col_btn4:
            btn_reanudar = st.button(
                "Reanudar Loop",
                type="success",
                use_container_width=True
            )
            if btn_reanudar:
                scheduler_bridge.reanudar_scheduler()
                st.success("Scheduler reanudado")
                st.rerun()
    
    # Progreso del ciclo actual
    if scheduler_corriendo and estado_scheduler.get("ultimo_reporte"):
        st.divider()
        st.markdown("### Último Reporte del Ciclo")
        
        ultimo_reporte = estado_scheduler.get("ultimo_reporte", {})
        
        rep_col1, rep_col2, rep_col3, rep_col4 = st.columns(4)
        
        rep_col1.metric(
            "Cuentas Procesadas",
            str(ultimo_reporte.get("cuentas_procesadas", 0))
        )
        rep_col2.metric(
            "Exitosas",
            str(ultimo_reporte.get("cuentas_exitosas", 0)),
            delta=f"{ultimo_reporte.get('tasa_exito_porcentaje', 0):.1f}%"
        )
        rep_col3.metric(
            "Bonos Activados",
            str(ultimo_reporte.get("bonos_activados", 0))
        )
        rep_col4.metric(
            "Total Apostado",
            f"${ultimo_reporte.get('total_apostado', 0):,.2f}"
        )
        
        # Mostrar errores comunes si los hay
        errores_comunes = ultimo_reporte.get("errores_comunes", {})
        if errores_comunes:
            with st.expander(f"Errores comunes ({sum(errores_comunes.values())} total)"):
                for error, cantidad in errores_comunes.items():
                    st.write(f"- **{error}**: {cantidad}")
    
    # Estadísticas globales
    if estado_scheduler.get("estadisticas_globales"):
        st.divider()
        st.markdown("### Estadísticas Globales Acumuladas")
        
        stats = estado_scheduler.get("estadisticas_globales", {})
        
        stat_col1, stat_col2, stat_col3, stat_col4 = st.columns(4)
        
        stat_col1.metric(
            "Total Ciclos",
            str(stats.get("ciclos_completados", 0))
        )
        stat_col2.metric(
            "Total Cuentas",
            str(stats.get("total_cuentas_procesadas", 0))
        )
        stat_col3.metric(
            "Tasa Éxito Global",
            f"{stats.get('tasa_exito_global', 0):.1f}%"
        )
        stat_col4.metric(
            "Tiempo Total",
            f"{stats.get('tiempo_total_horas', 0):.1f} hrs"
        )


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


# ============================================================================
# PESTAÑA: INICIO (Dashboard principal con resumen rápido)
# ============================================================================

def tab_inicio() -> None:
    """Página de inicio con resumen ejecutivo del estado del bot."""
    st.markdown("### 👋 Bienvenido al Automatizador Betplay v3.0")
    
    # Estado actual del bot
    estado = control.leer_estado()
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Estado del Bot", estado.get("estado", "inactivo"))
    
    with col2:
        total = int(estado.get("total", 0) or 0)
        indice = int(estado.get("indice", 0) or 0)
        st.metric("Progreso", f"{indice + 1 if total else 0}/{total}")
    
    with col3:
        st.metric("Cuenta Actual", str(estado.get("cuenta", "-") or "-"))
    
    st.divider()
    
    # Acciones rápidas
    st.markdown("### ⚡ Acciones Rápidas")
    
    col_acc1, col_acc2, col_acc3 = st.columns(3)
    
    with col_acc1:
        if st.button("▶️ Iniciar Bot", type="primary", use_container_width=True):
            st.info("Ve a la pestaña Control para configurar e iniciar")
    
    with col_acc2:
        if st.button("📊 Ver Apuestas Hoy", use_container_width=True):
            st.info("Ve a la pestaña Qué Hizo Hoy para ver el resumen")
    
    with col_acc3:
        if st.button("🔄 Configurar Loop", use_container_width=True):
            st.info("Ve a la pestaña Loop Infinito para configurar ciclos")
    
    st.divider()
    
    # Resumen del día
    st.markdown("### 📈 Resumen del Día")
    
    reportes = leer_reportes_apuestas()
    hoy = datetime.now().date()
    
    reportes_hoy = []
    for rep in reportes:
        try:
            fecha_rep = datetime.fromisoformat(rep.get("fecha", "")).date()
            if fecha_rep == hoy:
                reportes_hoy.append(rep)
        except Exception:
            continue
    
    if reportes_hoy:
        total_apostado = sum(float(r.get("monto_apostado", 0)) for r in reportes_hoy)
        total_apuestas = len(reportes_hoy)
        
        col_res1, col_res2 = st.columns(2)
        col_res1.success(f"💰 Total Apostado Hoy: {formatear_moneda(total_apostado)}")
        col_res2.info(f"🎯 Apuestas Realizadas: {total_apuestas}")
    else:
        st.info("📭 No hay actividad registrada hoy aún")
    
    st.divider()
    
    # Enlaces rápidos a documentación
    st.markdown("### 📚 Recursos")
    
    st.markdown("""
    - **Documentación**: Consulta `README_v3.md` para instrucciones detalladas
    - **Soporte**: Revisa los logs en `bot.log` si encuentras errores
    - **Configuración**: Los pools de MAC y proxies están en `macs_pool.txt` y `proxies.txt`
    """)


# ============================================================================
# APP PRINCIPAL
# ============================================================================

def main() -> None:
    st.set_page_config(
        page_title="Betplay Bot v3.0",
        page_icon="🎯",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Inyectar CSS personalizado
    inject_custom_css()
    
    # Header con logo/título estilizado
    st.markdown("""
    <div style='text-align: center; padding: 20px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 15px; margin-bottom: 30px;'>
        <h1 style='color: white; margin: 0;'>🎯 Automatizador Betplay v3.0</h1>
        <p style='color: rgba(255,255,255,0.9); margin: 10px 0 0 0;'>Panel de Control Inteligente</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Navegación principal con iconos
    t1, t2, t3, t4, t5, t6, t7 = st.tabs([
        "🏠 Inicio",
        "📋 Cuentas",
        "➕ Registrar",
        "📊 Qué Hizo Hoy",
        "🎮 Control",
        "🔄 Loop Infinito",
        "📈 Resultados"
    ])
    
    with t1:
        tab_inicio()
    with t2:
        tab_cuentas()
    with t3:
        tab_registrar()
    with t4:
        tab_que_hizo_hoy()
    with t5:
        tab_control()
    with t6:
        tab_loop_infinito()
    with t7:
        tab_resultados()


if __name__ == "__main__":
    main()
