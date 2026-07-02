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
