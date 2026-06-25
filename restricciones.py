"""
restricciones.py
================

Detección de palabras de restricción en un texto, ignorando mayúsculas/
minúsculas Y tildes. Útil para evaluar de forma booleana si una alerta de la
pantalla indica un límite/bloqueo tras una operación de prueba.
"""

import unicodedata

# Palabras clave que delatan una restricción/limitación de la cuenta.
PALABRAS_RESTRICCION = (
    "límite",
    "máximo",
    "restricción",
    "bloqueo",
    "suspendida",
    "excedido",
)


def _normalizar(s: str) -> str:
    """Pasa a minúsculas y elimina marcas de acento (tildes, diéresis...)."""
    sin_tildes = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in sin_tildes if not unicodedata.combining(c))


def contiene_restriccion(texto: str, palabras=PALABRAS_RESTRICCION) -> bool:
    """
    Devuelve True si el texto contiene alguna palabra de restricción.

    Ignora mayúsculas/minúsculas y tildes ('limite' == 'LÍMITE').
    """
    texto_norm = _normalizar(texto)
    return any(_normalizar(p) in texto_norm for p in palabras)
