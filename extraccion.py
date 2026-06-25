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
    Extrae el primer número (entero o decimal) del texto y lo devuelve como float.

    Acepta coma o punto como separador decimal. Si no encuentra ningún número
    válido, devuelve `por_defecto`.
    """
    coincidencia = re.search(r"\d+(?:[.,]\d+)?", texto)
    if not coincidencia:
        return por_defecto
    try:
        return float(coincidencia.group().replace(",", "."))
    except ValueError:
        return por_defecto
