"""
crear_ejemplo.py
================

Genera un archivo cuentas.xlsx de ejemplo con datos ficticios secuenciales,
100% compatible con el esquema de ENTRADA del orquestador (auditor.py):

    Usuario, Password, Nombre, Correo, ClaveCorreo, Puerto

(Saldo, Verificada y Limitada NO van aquí: son resultados de la auditoría y se
escriben en historial_auditoria.csv.)

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
                "Nombre": f"Nombre Demo {i:02d}",
                "Correo": f"demo{i:02d}@ejemplo.com",
                # App password ficticia con el formato típico (4 grupos de 4).
                "ClaveCorreo": f"abcd efgh ijkl {i:04d}",
                # Puerto de depuración remota secuencial: 9222, 9223, 9224, ...
                "Puerto": PUERTO_POR_DEFECTO + (i - 1),
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
