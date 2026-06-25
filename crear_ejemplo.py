"""
crear_ejemplo.py
================

Genera un archivo cuentas.xlsx de ejemplo con datos ficticios secuenciales,
100% compatible con el esquema de 9 columnas del orquestador (auditor.py):

    Usuario, Password, Correo, ClaveCorreo, Puerto, Estado, Saldo,
    Verificada, Limitada

Sirve para probar el flujo (lectura, historial y consola) sin datos reales y
sin tener que rellenar el Excel a mano: los puertos CDP se asignan de forma
secuencial (9222, 9223, ...) y cada cuenta trae una app password ficticia.

Uso:
    python crear_ejemplo.py
"""

import pandas as pd

# COLUMNAS_ESPERADAS es la fuente única de verdad del esquema; importarla
# mantiene este generador automáticamente sincronizado con el orquestador.
from auditor import ARCHIVO_EXCEL, COLUMNAS_ESPERADAS, PUERTO_POR_DEFECTO

# Cuántas cuentas ficticias generar.
NUM_CUENTAS = 3


def construir_datos(n: int) -> list[dict]:
    """
    Crea `n` registros ficticios con valores secuenciales/variados, de modo que
    el flujo de pruebas ejercite ambos caminos (verificada/no, limitada/no).
    """
    filas = []
    for i in range(1, n + 1):
        filas.append(
            {
                "Usuario": f"usuario_demo_{i:02d}",
                "Password": f"clave-ficticia-{i}",
                "Correo": f"demo{i:02d}@ejemplo.com",
                # App password ficticia con el formato típico (4 grupos de 4).
                "ClaveCorreo": f"abcd efgh ijkl {i:04d}",
                # Puerto de depuración remota secuencial: 9222, 9223, 9224, ...
                "Puerto": PUERTO_POR_DEFECTO + (i - 1),
                "Estado": "pendiente",
                # Saldo ficticio creciente: 0.0, 125.5, 251.0, ...
                "Saldo": round((i - 1) * 125.5, 2),
                # Alterna sí/no para ver ambos estados en las pruebas.
                "Verificada": "si" if i % 2 == 1 else "no",
                "Limitada": "si" if i % 3 == 0 else "no",
            }
        )
    return filas


def main() -> None:
    # columns=COLUMNAS_ESPERADAS fuerza el orden exacto y valida que las claves
    # coincidan con el esquema del orquestador.
    df = pd.DataFrame(construir_datos(NUM_CUENTAS), columns=COLUMNAS_ESPERADAS)
    df.to_excel(ARCHIVO_EXCEL, index=False)
    print(f"Archivo de ejemplo creado: {ARCHIVO_EXCEL} ({len(df)} filas)")
    print(f"Columnas: {', '.join(df.columns)}")


if __name__ == "__main__":
    main()
