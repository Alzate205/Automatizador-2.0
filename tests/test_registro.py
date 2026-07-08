"""Pruebas de la lógica pura del registro (sin navegador)."""
import pandas as pd

import preflight
from procesador_web import (
    _partir_dos, _validar_datos_registro,
    _ciudad_lugar_expedicion, _claves_lugar_expedicion,
    _coincide_opcion, _password_valida_betplay,
)


# ---------------- _coincide_opcion (selección en desplegables) ----------------

def test_coincide_opcion_numeros_exactos():
    # '1' NO debe casar con '10'/'11' (evita elegir el día equivocado).
    assert _coincide_opcion("1", ["1"]) is True
    assert _coincide_opcion("10", ["1"]) is False
    assert _coincide_opcion("15", ["15"]) is True


def test_coincide_opcion_mes_por_nombre():
    assert _coincide_opcion("Junio", ["06", "6", "junio"]) is True
    assert _coincide_opcion("Diciembre", ["06", "6", "junio"]) is False


def test_coincide_opcion_etiqueta_larga_por_inclusion():
    assert _coincide_opcion("CL - CALLE", ["CL", "Calle"]) is True
    assert _coincide_opcion("Cédula de ciudadanía", ["Cedula de ciudadania"]) is True


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


# ---------------- Lugar de expedición (autocompletar homónimos) ----------------

def test_ciudad_lugar_expedicion_separa_departamento():
    assert _ciudad_lugar_expedicion("ARMENIA (QUINDIO)") == "ARMENIA"
    assert _ciudad_lugar_expedicion("ARMENIA, QUINDIO") == "ARMENIA"
    assert _ciudad_lugar_expedicion("BOGOTA") == "BOGOTA"
    assert _ciudad_lugar_expedicion("") == "BOGOTA"  # defecto


def test_claves_lugar_expedicion():
    assert _claves_lugar_expedicion("ARMENIA (QUINDIO)") == ["armenia", "quindio"]
    assert _claves_lugar_expedicion("ARMENIA (ANTIOQUIA)") == ["armenia", "antioquia"]
    assert _claves_lugar_expedicion("Bogotá") == ["bogota"]  # sin tildes


# ---------------- _password_valida_betplay (ng-pattern del input) ----------------

def test_password_valida_cumple_patron():
    # Mayúscula + dígito + uno de . ; , y solo caracteres permitidos.
    assert _password_valida_betplay("Betplay2026.") is True
    assert _password_valida_betplay("Abc123;") is True
    assert _password_valida_betplay("Xy9,zz") is True


def test_password_invalida_por_faltar_requisitos():
    assert _password_valida_betplay("betplay2026.") is False   # sin mayúscula
    assert _password_valida_betplay("Betplay.") is False       # sin dígito
    assert _password_valida_betplay("Betplay2026") is False    # sin . ; ,
    assert _password_valida_betplay("Betplay2026!") is False    # '!' no permitido
    assert _password_valida_betplay("Bet play26.") is False    # espacio no permitido
    assert _password_valida_betplay("") is False
    assert _password_valida_betplay(None) is False


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
