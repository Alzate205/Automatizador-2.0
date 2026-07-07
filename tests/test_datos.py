import pandas as pd
from webapp import datos


def test_porcentaje_verificadas():
    df = pd.DataFrame({"Verificada": ["si", "no", "SI", ""]})
    assert datos.porcentaje_verificadas(df) == 50.0


def test_porcentaje_verificadas_vacio():
    assert datos.porcentaje_verificadas(pd.DataFrame()) == 0.0


def test_contar_limitadas():
    df = pd.DataFrame({"Limitada": ["True", "false", "si", "1", ""]})
    assert datos.contar_limitadas(df) == 3


def test_serie_registro_desde_columna():
    df = pd.DataFrame({"Registro": ["registro_ok", "N/A", "registro_rechazado"]})
    s = datos.serie_registro(df)
    assert list(s) == ["registro_ok", "n/a", "registro_rechazado"]


def test_generar_plantilla_registro():
    df = datos.generar_plantilla_registro(3)
    assert len(df) == 3
    assert list(df["Modo"].unique()) == ["registro"]
    assert set(datos.COLUMNAS_PLANTILLA) <= set(df.columns)


def test_lineas_log_incremental(tmp_path):
    p = tmp_path / "bot.log"
    p.write_text("l1\nl2\nl3\n", encoding="utf-8")
    r = datos.lineas_log(str(p), desde=0)
    assert r["total"] == 3
    assert r["lineas"] == ["l1", "l2", "l3"]
    r2 = datos.lineas_log(str(p), desde=3)
    assert r2["lineas"] == []
    assert r2["total"] == 3


def test_lineas_log_inexistente(tmp_path):
    r = datos.lineas_log(str(tmp_path / "no.log"), desde=0)
    assert r == {"lineas": [], "total": 0}


def test_guardar_y_leer_cuentas(tmp_path, monkeypatch):
    ruta = tmp_path / "cuentas.xlsx"
    monkeypatch.setattr(datos, "RUTA_EXCEL", str(ruta))
    datos.guardar_cuentas([{"Usuario": "a@b.com", "Modo": "login"}])
    d = datos.cuentas_como_dict()
    assert d["filas"][0]["Usuario"] == "a@b.com"
    assert "Usuario" in d["columnas"]


def test_guardar_hace_backup_atomico(tmp_path, monkeypatch):
    ruta = tmp_path / "cuentas.xlsx"
    monkeypatch.setattr(datos, "RUTA_EXCEL", str(ruta))
    # Primer guardado: no hay backup (el archivo no existía).
    datos.guardar_cuentas([{"Usuario": "a@b.com"}])
    carpeta_bk = tmp_path / datos.CARPETA_BACKUPS
    assert not carpeta_bk.exists() or not list(carpeta_bk.glob("cuentas_*.xlsx"))
    # Segundo guardado (sobrescribe): debe respaldar la versión previa.
    datos.guardar_cuentas([{"Usuario": "c@d.com"}])
    backups = list(carpeta_bk.glob("cuentas_*.xlsx"))
    assert len(backups) == 1
    prev = pd.read_excel(backups[0])
    assert prev["Usuario"].iloc[0] == "a@b.com"  # el backup tiene lo ANTERIOR
    # No queda ningún temporal tras la escritura atómica.
    assert not list(tmp_path.glob(".tmp_*"))


def test_anexar_cuenta(tmp_path, monkeypatch):
    ruta = tmp_path / "cuentas.xlsx"
    monkeypatch.setattr(datos, "RUTA_EXCEL", str(ruta))
    datos.guardar_cuentas([{"Usuario": "a@b.com"}])
    n = datos.anexar_cuenta({"Usuario": "c@d.com"})
    assert n == 2


def test_resultados_payload(tmp_path, monkeypatch):
    ruta = tmp_path / "res.xlsx"
    pd.DataFrame({
        "Usuario": ["a", "b"], "Estado": ["exitosa", "revisar"],
        "Saldo": [1000, 0], "Verificada": ["si", "no"],
        "Limitada": [False, True], "Registro": ["registro_ok", "registro_rechazado"],
        "Password": ["x", "y"],
    }).to_excel(ruta, index=False)
    p = datos.resultados_payload(str(ruta))
    assert p["metricas"]["total"] == 2
    assert p["metricas"]["verificadas_pct"] == 50.0
    assert p["metricas"]["limitadas"] == 1
    assert p["registro"]["registro_ok"] == 1
    assert "Password" not in p["columnas"]  # sensibles fuera por defecto
