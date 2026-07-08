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
    raise FileNotFoundError("No se encontró Google Chrome. Instálalo o configura la ruta manualmente.")


RUTA_PROXIES = "proxies.txt"


def cargar_proxies_desde_archivo(ruta: str = RUTA_PROXIES) -> list:
    """
    Carga proxies desde un archivo de texto (uno por línea).

    Ignora líneas vacías y comentarios (que empiezan con '#'). Devuelve una lista
    vacía si el archivo no existe. Útil para asignar proxies a los perfiles cuando
    el Excel no trae la columna 'Proxy'.
    """
    if not os.path.exists(ruta):
        return []
    try:
        # utf-8-sig: tolera el BOM que agregan el Bloc de notas / PowerShell, que
        # de lo contrario contaminaria el primer proxy con '﻿'.
        with open(ruta, "r", encoding="utf-8-sig") as f:
            return [
                linea.strip()
                for linea in f
                if linea.strip() and not linea.strip().startswith("#")
            ]
    except Exception:
        return []


def proxy_valido(proxy: Optional[str]) -> Optional[str]:
    """Normaliza el valor de proxy: devuelve None si está vacío o es 'none'/'nan'."""
    if not proxy:
        return None
    limpio = str(proxy).strip()
    if not limpio or limpio.lower() in ("none", "nan", "ninguno", "sin proxy"):
        return None
    return limpio


def construir_args_chrome(
    chrome_exe: str,
    puerto: int,
    user_dir: str,
    proxy: Optional[str] = None,
    headless: bool = False,
) -> list:
    """
    Arma la lista de argumentos para lanzar Chrome.

    Evita los flags que muestran el banner amarillo "marca de línea de comandos no
    admitida": --no-sandbox, --disable-setuid-sandbox y
    --disable-blink-features=AutomationControlled. La ocultación de la automación
    (navigator.webdriver, etc.) la hace playwright-stealth por JavaScript en la
    página (ver aplicar_stealth en procesador_web), que es más efectivo y NO
    dispara el banner.
    """
    cmd = [
        chrome_exe,
        f"--remote-debugging-port={puerto}",
        f"--user-data-dir={user_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--lang=es-CO",
        "--start-maximized",
        "--disable-popup-blocking",
        # Reduce el aislamiento de sitios (no muestra banner de flag no admitido).
        "--disable-features=IsolateOrigins,site-per-process",
    ]
    proxy = proxy_valido(proxy)
    if proxy:
        cmd.append(f"--proxy-server={proxy}")
    if headless:
        cmd.append("--headless=new")
    return cmd


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

    cmd = construir_args_chrome(chrome_exe, puerto, user_dir, proxy, headless)

    try:
        print(f"Lanzando perfil {perfil_id} | Puerto: {puerto} | Proxy: {proxy or 'Ninguno'}")
        subprocess.Popen(cmd)

        # Espera humana realista (margen para que el endpoint CDP quede listo)
        time.sleep(5 + random.uniform(2.0, 4.5))

        endpoint = f"http://127.0.0.1:{puerto}"
        print(f"Perfil {perfil_id} listo → {endpoint}")
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
        print("Todos los procesos de Chrome han sido cerrados.")
    except:
        pass