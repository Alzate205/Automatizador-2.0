from gestor_perfiles import construir_args_chrome


def test_no_usa_flags_de_sandbox_no_admitidos():
    # Estos flags muestran el banner "marca de línea de comandos no admitida".
    args = construir_args_chrome("chrome.exe", 9222, "/tmp/perf")
    assert "--no-sandbox" not in args
    assert "--disable-setuid-sandbox" not in args


def test_incluye_puerto_y_perfil():
    args = construir_args_chrome("chrome.exe", 9230, "/tmp/perf8")
    assert "--remote-debugging-port=9230" in args
    assert "--user-data-dir=/tmp/perf8" in args


def test_proxy_y_headless_opcionales():
    base = construir_args_chrome("chrome.exe", 9222, "/tmp/p")
    assert not any(a.startswith("--proxy-server") for a in base)
    assert "--headless=new" not in base

    con = construir_args_chrome("chrome.exe", 9222, "/tmp/p", proxy="1.2.3.4:8000", headless=True)
    assert "--proxy-server=1.2.3.4:8000" in con
    assert "--headless=new" in con


def test_proxy_invalido_se_ignora():
    args = construir_args_chrome("chrome.exe", 9222, "/tmp/p", proxy="ninguno")
    assert not any(a.startswith("--proxy-server") for a in args)
