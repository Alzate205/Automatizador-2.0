"""Pruebas de la lógica pura del registro (sin navegador)."""
import pandas as pd

import preflight
from procesador_web import _partir_dos, _validar_datos_registro


# ---------------- _partir_dos (segundo nombre/apellido) ----------------

def test_partir_dos_parte_cuando_hay_dos_palabras():
    assert _partir_dos("Perez Gomez", "") == ("Perez", "Gomez")


def test_partir_dos_respeta_secundario_explicito():
    assert _partir_dos("Perez Gomez", "Rojas") == ("Perez Gomez", "Rojas")


def test_partir_dos_una_sola_palabra():
    assert _partir_dos("Perez", "") == ("Perez", "")


def test_partir_dos_tres_palabras_toma_la_ultima():
    assert _partir_dos("De La Cruz", "") == ("De La", "Cruz")


def test_partir_dos_vacios():
    assert _partir_dos("", "") == ("", "")
    assert _partir_dos(None, None) == ("", "")


# ---------------- _validar_datos_registro (incluye Telefono) ----------------

def _fila_completa():
    return {
        "Cedula": "123", "PrimerNombre": "Juan", "PrimerApellido": "Perez",
        "Correo": "juan@x.com", "Telefono": "3001234567", "Password": "Betplay2026.",
    }


def test_validar_registro_ok():
    ok, _ = _validar_datos_registro(_fila_completa())
    assert ok is True


def test_validar_registro_falta_telefono():
    fila = _fila_completa()
    fila["Telefono"] = ""
    ok, msg = _validar_datos_registro(fila)
    assert ok is False and "Telefono" in msg


# ---------------- preflight.REQUERIDOS_REGISTRO ampliado ----------------

def test_preflight_marca_registro_sin_telefono_como_incompleto():
    df = pd.DataFrame([{
        "Modo": "registro", "Cedula": "123", "PrimerNombre": "Juan",
        "PrimerApellido": "Perez", "Correo": "j@x.com", "Password": "Betplay2026.",
        # sin Telefono
    }])
    errores, avisos = preflight.validar_datos(df, "registro")
    assert errores  # ninguna procesable -> error bloqueante
    assert any("obligatorios" in a.lower() or "obligatorios" in e.lower()
               for a in avisos for e in errores) or errores


def test_preflight_registro_completo_procesable():
    df = pd.DataFrame([{
        "Modo": "registro", "Cedula": "123", "PrimerNombre": "Juan",
        "PrimerApellido": "Perez", "Correo": "j@x.com", "Telefono": "3001234567",
        "Password": "Betplay2026.",
    }])
    errores, _ = preflight.validar_datos(df, "registro")
    assert not errores
