import os
import pandas as pd
from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch):
    # El servidor y control.py trabajan con cwd = raíz del proyecto.
    monkeypatch.chdir(tmp_path)
    from webapp import servidor
    return TestClient(servidor.app)


def test_estado_por_defecto(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/estado")
    assert r.status_code == 200
    assert r.json()["estado"] == "inactivo"


def test_log_incremental(tmp_path, monkeypatch):
    (tmp_path / "bot.log").write_text("a\nb\n", encoding="utf-8")
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/log", params={"desde": 0})
    assert r.json()["lineas"] == ["a", "b"]
    assert r.json()["total"] == 2


def test_iniciar_escribe_config_sin_lanzar(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    from webapp import servidor
    # No lanzar el bot real: parcheamos el lanzador.
    monkeypatch.setattr(servidor, "_lanzar_bot", lambda: None)
    cfg = {"filtro_modo": "registro", "tareas": ["bonos"], "rotar_ip": True}
    r = c.post("/api/iniciar", json=cfg)
    assert r.status_code == 200
    import json
    guardada = json.loads((tmp_path / "config_run.json").read_text(encoding="utf-8"))
    assert guardada["filtro_modo"] == "registro"
    assert guardada["rotar_ip"] is True


def test_detener_y_continuar_crean_senales(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert c.post("/api/detener").status_code == 200
    assert os.path.exists(tmp_path / "senal_detener.flag")
    assert c.post("/api/continuar").status_code == 200
    assert os.path.exists(tmp_path / "senal_continuar.flag")


def test_enviar_codigo(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/codigo", json={"codigo": "123456"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert (tmp_path / "codigo_2fa.txt").read_text(encoding="utf-8").strip() == "123456"


def test_cuentas_get_post(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/cuentas", json={"filas": [{"Usuario": "a@b.com", "Modo": "login"}]})
    assert r.status_code == 200 and r.json()["guardadas"] == 1
    g = c.get("/api/cuentas")
    assert g.json()["filas"][0]["Usuario"] == "a@b.com"


def test_cuentas_autoguardado_sin_backup(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    c.post("/api/cuentas", json={"filas": [{"Usuario": "a@b.com"}]})
    r = c.post("/api/cuentas", json={"filas": [{"Usuario": "b@c.com"}], "auto": True})
    assert r.status_code == 200
    bk = tmp_path / "backups_cuentas"
    assert not bk.exists() or not list(bk.glob("cuentas_*.xlsx"))
    assert c.get("/api/cuentas").json()["filas"][0]["Usuario"] == "b@c.com"


def test_cuentas_plantilla(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/cuentas/plantilla", json={"n": 4})
    assert r.status_code == 200 and r.json()["guardadas"] == 4
    assert c.get("/api/cuentas").json()["filas"][0]["Modo"] == "registro"


def test_cuentas_registrar(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    c.post("/api/cuentas", json={"filas": [{"Usuario": "a@b.com"}]})
    r = c.post("/api/cuentas/registrar", json={"Usuario": "c@d.com", "Modo": "registro"})
    assert r.status_code == 200 and r.json()["total"] == 2


def test_cuentas_importar(tmp_path, monkeypatch):
    import io, pandas as pd
    c = _client(tmp_path, monkeypatch)
    buf = io.BytesIO()
    pd.DataFrame({"Usuario": ["x@y.com"]}).to_excel(buf, index=False)
    buf.seek(0)
    r = c.post("/api/cuentas/importar",
               files={"archivo": ("cuentas.xlsx", buf.getvalue(),
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200 and r.json()["guardadas"] == 1
    assert c.get("/api/cuentas").json()["filas"][0]["Usuario"] == "x@y.com"


def test_cuentas_exportar(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    c.post("/api/cuentas", json={"filas": [{"Usuario": "a@b.com", "Modo": "login"}]})
    r = c.get("/api/cuentas/exportar")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert len(r.content) > 0


def test_resultados(tmp_path, monkeypatch):
    pd.DataFrame({"Usuario": ["a"], "Estado": ["exitosa"], "Saldo": [500],
                  "Verificada": ["si"], "Limitada": [False],
                  "Registro": ["registro_ok"]}).to_excel(
        tmp_path / "cuentas_actualizadas.xlsx", index=False)
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/resultados")
    assert r.status_code == 200
    assert r.json()["metricas"]["total"] == 1
    assert r.json()["registro"]["registro_ok"] == 1


def test_resultados_exportar(tmp_path, monkeypatch):
    pd.DataFrame({"Usuario": ["a"], "Saldo": [500]}).to_excel(
        tmp_path / "cuentas_actualizadas.xlsx", index=False)
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/resultados/exportar")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert len(r.content) > 0
