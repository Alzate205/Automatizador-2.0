"""
extraccion.py
=============

Utilidades de extracción de números desde texto mixto usando expresiones
regulares (re). Pensado para limpiar lo que se lee de la pantalla y obtener
un valor numérico utilizable (p. ej. el Saldo).
"""

import re


def extraer_numero(texto: str) -> str:
    """Devuelve solo los dígitos y el punto decimal del texto (string limpio)."""
    return re.sub(r"[^0-9.]", "", texto)


def extraer_saldo(texto: str, por_defecto: float = 0.0) -> float:
    """
    Extrae el primer número del texto y lo devuelve como float, manejando el
    formato local es-CO:

        "1.234.567"     -> 1234567.0   (punto = separador de miles)
        "1.234.567,50"  -> 1234567.5   (punto = miles, coma = decimal)
        "1234,50"       -> 1234.5       (coma = decimal)
        "1234.50"       -> 1234.5       (punto = decimal si el último grupo != 3)

    Devuelve `por_defecto` si no encuentra ningún número.
    """
    coincidencia = re.search(r"\d[\d.,]*", texto)
    if not coincidencia:
        return por_defecto
    num = coincidencia.group()

    if "." in num and "," in num:
        # es-CO: punto = miles, coma = decimal.
        num = num.replace(".", "").replace(",", ".")
    elif "," in num:
        num = num.replace(",", ".")
    else:
        partes = num.split(".")
        # Varios puntos, o un punto con grupo final de 3 dígitos => miles.
        if len(partes) > 2 or (len(partes) == 2 and len(partes[-1]) == 3):
            num = num.replace(".", "")

    try:
        return float(num)
    except ValueError:
        return por_defecto
