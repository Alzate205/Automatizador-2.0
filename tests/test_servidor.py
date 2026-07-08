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


def test_forzar_parada_resetea_estado_y_flags(tmp_path, monkeypatch):
    import control
    c = _client(tmp_path, monkeypatch)
    # Estado colgado (bot murió a mitad) + señales sueltas.
    control.escribir_estado(estado="corriendo", fase="rotando_ip", cuenta="x@y.com")
    control.pedir_continuar(); control.pedir_cancelar()
    r = c.post("/api/forzar-parada")
    assert r.status_code == 200
    assert c.get("/api/estado").json()["estado"] == "inactivo"
    assert control.hay_senal_continuar() is False
    assert control.hay_senal_cancelar() is False
    assert control.hay_senal_detener() is False


def test_estaticos_no_cache(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/app.js")
    assert r.status_code == 200
    assert "no-store" in r.headers.get("cache-control", "")


def test_cancelar_espera_crea_senal_y_desbloquea(tmp_path, monkeypatch):
    import control
    c = _client(tmp_path, monkeypatch)
    # Estado atascado en 'esperando_captcha' (el bot puede correr en OTRO proceso).
    control.escribir_estado(estado="esperando_captcha", fase="captcha", cuenta="x@y.com")
    r = c.post("/api/cancelar-espera")
    assert r.status_code == 200 and r.json()["ok"] is True
    # La señal DEBE persistir para que el bot (aunque el servidor no lo haya lanzado)
    # la consuma y aborte; se desbloquea el panel pasando el estado a inactivo.
    assert control.hay_senal_cancelar() is True
    assert c.get("/api/estado").json()["estado"] == "inactivo"


def test_cancelar_espera_no_toca_estado_si_no_esperaba(tmp_path, monkeypatch):
    import control
    c = _client(tmp_path, monkeypatch)
    control.escribir_estado(estado="corriendo", fase="registro", cuenta="x@y.com")
    c.post("/api/cancelar-espera")
    # No estaba esperando: no forzamos inactivo (el bot maneja su propio estado).
    assert c.get("/api/estado").json()["estado"] == "corriendo"
    assert control.hay_senal_cancelar() is True


def test_log_limpiar_trunca(tmp_path, monkeypatch):
    (tmp_path / "bot.log").write_text("a\nb\nc\n", encoding="utf-8")
    c = _client(tmp_path, monkeypatch)
    assert c.get("/api/log", params={"desde": 0}).json()["total"] == 3
    r = c.post("/api/log/limpiar")
    assert r.status_code == 200 and r.json()["ok"] is True
    despues = c.get("/api/log", params={"desde": 0}).json()
    assert despues["total"] == 0 and despues["lineas"] == []


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
