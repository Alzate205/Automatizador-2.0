"""
leer_fila.py
============

Utilidad sencilla para leer una fila concreta de un archivo Excel y
devolverla como diccionario de Python.

Uso:
    from leer_fila import leer_fila

    registro = leer_fila(0)            # primera fila de datos.xlsx
    registro = leer_fila(3, "otro.xlsx")
"""

import os

import pandas as pd

ARCHIVO_POR_DEFECTO = "datos.xlsx"


def leer_fila(indice: int, ruta: str = ARCHIVO_POR_DEFECTO) -> dict:
    """
    Abre un Excel y devuelve la fila indicada como diccionario {columna: valor}.

    Parámetros:
        indice: posición de la fila (basada en 0, igual que iloc).
        ruta:   ruta del archivo Excel (por defecto 'datos.xlsx').

    Devuelve:
        Un diccionario con los datos de la fila.

    Lanza:
        FileNotFoundError: si el archivo no existe.
        IndexError:        si el índice está fuera de rango.
    """
    if not os.path.exists(ruta):
        raise FileNotFoundError(f"No se encontró el archivo: {ruta}")

    df = pd.read_excel(ruta)

    if not -len(df) <= indice < len(df):
        raise IndexError(
            f"Índice {indice} fuera de rango (el archivo tiene {len(df)} filas)."
        )

    return df.iloc[indice].to_dict()


if __name__ == "__main__":
    # Demostración rápida: imprime la primera fila de datos.xlsx.
    print(leer_fila(0))
