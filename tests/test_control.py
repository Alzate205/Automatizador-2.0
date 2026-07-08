import control


def test_canal_codigo_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert control.hay_codigo() is False
    assert control.leer_codigo() is None

    control.guardar_codigo("  123456 ")
    assert control.hay_codigo() is True
    assert control.leer_codigo() == "123456"  # se recorta el espacio

    control.limpiar_codigo()
    assert control.hay_codigo() is False
    assert control.leer_codigo() is None


def test_senal_cancelar_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert control.hay_senal_cancelar() is False
    control.pedir_cancelar()
    assert control.hay_senal_cancelar() is True
    control.limpiar_cancelar()
    assert control.hay_senal_cancelar() is False


def test_reset_control_limpia_codigo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    control.guardar_codigo("999000")
    control.pedir_continuar()
    control.pedir_detener()
    control.pedir_cancelar()
    control.reset_control()
    assert control.hay_codigo() is False
    assert control.hay_senal_continuar() is False
    assert control.hay_senal_detener() is False
    assert control.hay_senal_cancelar() is False
