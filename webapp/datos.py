"""
datos.py — Lógica de datos del dashboard web (sin dependencias de la web).

Extraído/adaptado de dashboard.py (Streamlit) para reusarlo desde servidor.py.
"""
from __future__ import annotations

import io
import os
import re
from datetime import datetime

import pandas as pd

RUTA_EXCEL = "cuentas.xlsx"
RUTA_RESULTADOS = "cuentas_actualizadas.xlsx"
RUTA_HISTORIAL = "historial_auditoria.csv"
LOG_BOT = "bot.log"

COLUMNAS_SENSIBLES = ["Password", "ClaveCorreo"]

COLUMNAS_PLANTILLA = [
    "Usuario", "Password", "Nombre", "Correo", "ClaveCorreo", "Puerto", "Modo",
    "Cedula", "PrimerNombre", "PrimerApellido", "Telefono",
    "ExpedicionDD", "ExpedicionMM", "ExpedicionYYYY",
    "NacimientoDD", "NacimientoMM", "NacimientoYYYY",
    "LugarExpedicion",
]


def leer_excel(ruta: str) -> pd.DataFrame:
    if not os.path.exists(ruta):
        return pd.DataFrame()
    try:
        return pd.read_excel(ruta)
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


def generar_plantilla_registro(n: int = 10) -> pd.DataFrame:
    df = pd.DataFrame(columns=COLUMNAS_PLANTILLA)
    for i in range(int(n)):
        df.loc[i] = {
            "Usuario": "", "Password": "", "Nombre": f"Cuenta {i + 1}",
            "Correo": "", "ClaveCorreo": "", "Puerto": 9222 + i, "Modo": "registro",
            "Cedula": "", "PrimerNombre": "", "PrimerApellido": "", "Telefono": "",
            "ExpedicionDD": "15", "ExpedicionMM": "06", "ExpedicionYYYY": "1995",
            "NacimientoDD": "10", "NacimientoMM": "03", "NacimientoYYYY": "1995",
            "LugarExpedicion": "BOGOTA",
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
    if "Registro" in df.columns:
        return df["Registro"].astype(str).str.strip().str.lower()
    if "Detalle" in df.columns:
        return (
            df["Detalle"].astype(str)
            .str.extract(r"reg:\s*([a-z_]+)", flags=re.IGNORECASE, expand=False)
            .fillna("").str.lower()
        )
    return pd.Series([""] * len(df), index=df.index)


def opciones_cuentas(df: pd.DataFrame) -> list:
    if df.empty:
        return []
    opciones: list = []
    for _, fila in df.iterrows():
        ident = str(fila.get("Correo") or fila.get("Usuario") or "").strip()
        if ident and ident.lower() != "nan" and ident not in opciones:
            opciones.append(ident)
    return opciones


def lineas_log(ruta: str, desde: int = 0) -> dict:
    """Líneas del log desde el índice `desde` (log incremental)."""
    if not os.path.exists(ruta):
        return {"lineas": [], "total": 0}
    try:
        with open(ruta, encoding="utf-8", errors="replace") as f:
            todas = f.read().splitlines()
    except Exception:  # noqa: BLE001
        return {"lineas": [], "total": 0}
    desde = max(0, int(desde))
    return {"lineas": todas[desde:], "total": len(todas)}


def _limpiar_nan(df: pd.DataFrame) -> pd.DataFrame:
    return df.where(pd.notna(df), None)


def cuentas_como_dict() -> dict:
    df = leer_excel(RUTA_EXCEL)
    if df.empty:
        return {"columnas": COLUMNAS_PLANTILLA, "filas": []}
    df = _limpiar_nan(df)
    return {"columnas": list(df.columns), "filas": df.to_dict(orient="records")}


def guardar_cuentas(filas: list) -> int:
    df = pd.DataFrame(filas)
    df.to_excel(RUTA_EXCEL, index=False)
    return len(df)


def anexar_cuenta(fila: dict) -> int:
    df = leer_excel(RUTA_EXCEL)
    nueva = pd.DataFrame([fila])
    df = pd.concat([df, nueva], ignore_index=True) if not df.empty else nueva
    df.to_excel(RUTA_EXCEL, index=False)
    return len(df)


def to_excel_bytes(df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Resultados")
    return buffer.getvalue()


def resultados_payload(ruta: str | None = None, incluir_sensibles: bool = False) -> dict:
    ruta = ruta or RUTA_RESULTADOS
    df = leer_excel(ruta)
    if df.empty:
        return {"metricas": {"total": 0, "verificadas_pct": 0.0, "limitadas": 0,
                             "saldo_total": 0.0},
                "registro": {}, "saldo_por_estado": {}, "verificadas": {},
                "columnas": [], "filas": []}

    reg = serie_registro(df)
    estados_reg = ["registro_ok", "registro_incierto", "registro_rechazado", "error_registro"]
    conteo_reg = {e: int((reg == e).sum()) for e in estados_reg if (reg == e).any()}

    saldo = pd.to_numeric(df.get("Saldo", pd.Series(dtype=float)), errors="coerce").fillna(0)
    saldo_por_estado = {}
    if "Estado" in df.columns:
        tmp = df.copy()
        tmp["_saldo"] = saldo.values
        saldo_por_estado = {str(k): float(v) for k, v in
                            tmp.groupby("Estado")["_saldo"].sum().items()}

    ver = df.get("Verificada", pd.Series(dtype=str)).astype(str).str.strip().str.lower()
    verificadas = {
        "Verificada": int((ver == "si").sum()),
        "No verificada": int((ver != "si").sum()),
    }

    df_vis = df if incluir_sensibles else df[[c for c in df.columns if c not in COLUMNAS_SENSIBLES]]
    df_vis = _limpiar_nan(df_vis)

    return {
        "metricas": {
            "total": int(len(df)),
            "verificadas_pct": porcentaje_verificadas(df),
            "limitadas": contar_limitadas(df),
            "saldo_total": float(saldo.sum()),
        },
        "registro": conteo_reg,
        "saldo_por_estado": saldo_por_estado,
        "verificadas": verificadas,
        "columnas": list(df_vis.columns),
        "filas": df_vis.to_dict(orient="records"),
    }
