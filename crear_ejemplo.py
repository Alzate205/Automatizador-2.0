"""
crear_ejemplo.py
================

Genera un archivo cuentas.xlsx de ejemplo con datos ficticios secuenciales,
listo para probar AMBOS flujos del orquestador sin editar el Excel a mano:

  - Columnas base (esquema de entrada de auditor.py):
        Usuario, Password, Nombre, Correo, ClaveCorreo, Puerto
  - Columna de control de flujo:
        Modo   ("login" o "registro")
  - Columnas para el modo registro (las usa procesador_web.registrar_cuenta):
        Cedula, PrimerNombre, PrimerApellido, Telefono,
        ExpedicionDD/MM/YYYY, LugarExpedicion, NacimientoDD/MM/YYYY

(Saldo, Verificada y Limitada NO van aquí: son resultados de la auditoría y se
escriben en historial_auditoria.csv / cuentas_actualizadas.xlsx.)

Por defecto genera varias cuentas en modo "login" y la última en modo
"registro", para ejercitar los dos caminos.

Uso:
    python crear_ejemplo.py
"""

import pandas as pd

# COLUMNAS_ESPERADAS es la fuente única de verdad del esquema base; importarla
# mantiene este generador sincronizado con el orquestador.
from auditor import ARCHIVO_EXCEL, COLUMNAS_ESPERADAS, PUERTO_POR_DEFECTO

# Cuántas cuentas ficticias generar.
NUM_CUENTAS = 3

# Columnas extra (no obligatorias para auditor.leer_cuentas, que solo valida las
# base): controlan el modo y alimentan el formulario de registro de Betplay.
COLUMNAS_REGISTRO = [
    "Modo",
    "Cedula",
    "PrimerNombre",
    "PrimerApellido",
    "Telefono",
    "ExpedicionDD",
    "ExpedicionMM",
    "ExpedicionYYYY",
    "LugarExpedicion",
    "NacimientoDD",
    "NacimientoMM",
    "NacimientoYYYY",
]


def construir_datos(n: int) -> list[dict]:
    """
    Crea `n` registros ficticios. La última cuenta se marca como "registro"
    (con datos de formulario completos) y el resto como "login", para ejercitar
    ambos caminos del orquestador.
    """
    filas = []
    for i in range(1, n + 1):
        modo = "registro" if i == n else "login"
        filas.append(
            {
                # --- Base ---
                "Usuario": f"usuario_demo_{i:02d}",
                "Password": f"clave-ficticia-{i}",
                "Nombre": f"Nombre Demo {i:02d}",
                "Correo": f"demo{i:02d}@ejemplo.com",
                # App password ficticia con el formato típico (4 grupos de 4).
                "ClaveCorreo": f"abcd efgh ijkl {i:04d}",
                # Puerto de depuración remota secuencial: 9222, 9223, 9224, ...
                "Puerto": PUERTO_POR_DEFECTO + (i - 1),
                # --- Control de flujo ---
                "Modo": modo,
                # --- Datos de registro (ficticios) ---
                "Cedula": f"100{i:07d}",
                "PrimerNombre": f"NombreDemo{i:02d}",
                "PrimerApellido": f"ApellidoDemo{i:02d}",
                "Telefono": f"30012345{i:02d}",
                "ExpedicionDD": "15",
                "ExpedicionMM": "06",
                "ExpedicionYYYY": "2013",
                "LugarExpedicion": "BOGOTA",
                "NacimientoDD": "10",
                "NacimientoMM": "03",
                "NacimientoYYYY": "1995",
            }
        )
    return filas


def main() -> None:
    # Orden explícito: columnas base + columnas de registro.
    columnas = COLUMNAS_ESPERADAS + COLUMNAS_REGISTRO
    df = pd.DataFrame(construir_datos(NUM_CUENTAS), columns=columnas)
    df.to_excel(ARCHIVO_EXCEL, index=False)
    print(f"Archivo de ejemplo creado: {ARCHIVO_EXCEL} ({len(df)} filas)")
    print(f"Columnas ({len(df.columns)}): {', '.join(df.columns)}")
    print(f"Modos: {df['Modo'].value_counts().to_dict()}")


if __name__ == "__main__":
    main()
