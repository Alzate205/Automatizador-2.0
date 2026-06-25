import subprocess
import os
import time
import random
from typing import Optional, Tuple

def lanzar_perfil_chrome(perfil_id: int, proxy: Optional[str] = None) -> Tuple[int, str]:
    """Lanza Chrome con perfil aislado y proxy (rotación)"""
    puerto = 9222 + (perfil_id % 8)  # rota entre varios puertos
    user_dir = f"./perfiles/perfil_{perfil_id}"
    os.makedirs(user_dir, exist_ok=True)

    cmd = [
        "google-chrome",  # Cambia a "chromium-browser" si usas Linux
        f"--remote-debugging-port={puerto}",
        f"--user-data-dir={user_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        "--start-maximized",
        "--disable-extensions",
        "--lang=es-CO"
    ]
    if proxy:
        cmd.append(f"--proxy-server={proxy}")

    subprocess.Popen(cmd)
    time.sleep(5 + random.uniform(0, 2))  # Espera humana
    return puerto, f"http://127.0.0.1:{puerto}"