import subprocess
import os
import time
import random
import sys
from typing import Optional, Tuple

def encontrar_chrome_exe() -> str:
    """Detecta automáticamente Chrome en Windows/Linux/macOS"""
    if sys.platform == "win32":
        posibles = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
        ]
    elif sys.platform == "darwin":
        posibles = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    else:  # Linux
        posibles = ["google-chrome", "google-chrome-stable", "chromium-browser"]

    for ruta in posibles:
        if os.path.exists(ruta):
            return ruta
        # Para comandos en PATH (Linux)
        if sys.platform != "win32":
            try:
                if subprocess.run(["which", ruta], capture_output=True, text=True).stdout.strip():
                    return ruta
            except:
                continue
    raise FileNotFoundError("❌ No se encontró Google Chrome. Instálalo o configura la ruta manualmente.")


def lanzar_perfil_chrome(
    perfil_id: int, 
    proxy: Optional[str] = None,
    headless: bool = False
) -> Tuple[int, str]:
    """
    Lanza un perfil Chrome aislado con CDP - Versión estable y multiplataforma.
    """
    chrome_exe = encontrar_chrome_exe()
    puerto = 9222 + perfil_id   # Sin módulo para evitar colisiones en lotes grandes

    user_dir = os.path.abspath(f"./perfiles/perfil_{perfil_id}")
    os.makedirs(user_dir, exist_ok=True)

    cmd = [
        chrome_exe,
        f"--remote-debugging-port={puerto}",
        f"--user-data-dir={user_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        "--disable-extensions",
        "--lang=es-CO",
        "--start-maximized",
        "--disable-popup-blocking",
    ]

    if proxy:
        cmd.append(f"--proxy-server={proxy}")

    if headless:
        cmd.append("--headless=new")

    try:
        print(f"🚀 Lanzando perfil {perfil_id} | Puerto: {puerto} | Proxy: {proxy or 'Ninguno'}")
        subprocess.Popen(cmd)
        
        # Espera humana realista
        time.sleep(5 + random.uniform(1.5, 3.5))
        
        endpoint = f"http://127.0.0.1:{puerto}"
        print(f"✅ Perfil {perfil_id} listo → {endpoint}")
        return puerto, endpoint

    except Exception as e:
        raise RuntimeError(f"Error al lanzar Chrome (perfil {perfil_id}): {e}")


def cerrar_todos_perfiles():
    """Cierre de emergencia (opcional) - útil al final de ejecución grande"""
    try:
        if sys.platform == "win32":
            subprocess.call("taskkill /F /IM chrome.exe /T", shell=True)
        else:
            subprocess.call("pkill -f 'chrome.*remote-debugging-port'", shell=True)
        print("🧹 Todos los procesos de Chrome han sido cerrados.")
    except:
        pass