"""
rotador_ip.py
=============

Rotación de IP móvil vía ADB (Android por cable USB).

La idea: tras registrar una cuenta, se activa el MODO AVIÓN del celular unos
segundos y luego se reactivan los datos móviles. Al reconectar la radio, el
operador suele asignar una IP pública nueva, de modo que la siguiente cuenta
navega desde otra IP (reduce la huella de "muchas cuentas desde la misma IP").

Requisitos:
    - ADB instalado (Android Platform Tools) y el celular conectado por USB con
      la "Depuración USB" activada y autorizada.
    - En el celular: los datos móviles como conexión (no Wi-Fi), si quieres que
      la rotación cambie la IP pública.

Comprobación rápida (en una terminal):
    adb devices        -> debe listar tu dispositivo como 'device'

Notas:
    - Se prueban dos estrategias de modo avión: primero `cmd connectivity`
      (Android 10+, sin root) y, si falla, el método clásico por broadcast
      (que en Android 8+ requiere root / `su`).
    - Nada aquí lanza excepción hacia el bot: ante cualquier fallo se registra
      un aviso y se continúa (una rotación fallida no debe tumbar el lote).
"""

from __future__ import annotations

import os
import random
import shutil
import subprocess
import sys
import time
import urllib.request
from typing import List, Optional

from auditor import log


# ---------------------------------------------------------------------------
# IP PÚBLICA (para verificar que la rotación cambió la IP)
# ---------------------------------------------------------------------------

# Servicios de "eco de IP": devuelven en texto plano la IP pública de quien
# consulta. Con tethering USB, esa IP es la del celular (datos móviles).
SERVICIOS_IP = (
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
    "https://icanhazip.com",
)


def obtener_ip_publica(timeout: float = 8.0) -> Optional[str]:
    """Devuelve la IP pública actual (texto) o None si ningún servicio responde."""
    for url in SERVICIOS_IP:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                ip = resp.read().decode("utf-8", "replace").strip()
                if ip and len(ip) <= 45:  # cabe IPv4/IPv6
                    return ip
        except Exception:  # noqa: BLE001
            continue
    return None


# ---------------------------------------------------------------------------
# LOCALIZACIÓN DE ADB
# ---------------------------------------------------------------------------

def encontrar_adb() -> Optional[str]:
    """
    Devuelve la ruta al ejecutable de ADB, o None si no se encuentra.

    Orden de búsqueda: variable de entorno ADB_PATH, el PATH del sistema, y
    ubicaciones típicas de instalación en Windows.
    """
    # 1) Variable de entorno explícita.
    env = os.environ.get("ADB_PATH")
    if env and os.path.exists(env):
        return env

    # 2) En el PATH.
    en_path = shutil.which("adb")
    if en_path:
        return en_path

    # 3) Ubicaciones típicas en Windows.
    candidatos: List[str] = []
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "")
        candidatos += [
            os.path.join(local, r"Android\Sdk\platform-tools\adb.exe"),
            r"C:\platform-tools\adb.exe",
            r"C:\adb\adb.exe",
            r"C:\Program Files\platform-tools\adb.exe",
            os.path.expanduser(r"~\platform-tools\adb.exe"),
            os.path.expanduser(r"~\Downloads\platform-tools\adb.exe"),
        ]
    else:
        candidatos += ["/usr/bin/adb", "/usr/local/bin/adb", os.path.expanduser("~/platform-tools/adb")]

    for ruta in candidatos:
        if ruta and os.path.exists(ruta):
            return ruta
    return None


# ---------------------------------------------------------------------------
# ROTADOR
# ---------------------------------------------------------------------------

class RotadorIP:
    """Envuelve las llamadas ADB para rotar la IP móvil de un Android por USB."""

    def __init__(self, adb_path: Optional[str] = None, serial: Optional[str] = None):
        self.adb = adb_path or encontrar_adb()
        # 'serial' permite fijar un dispositivo concreto si hay varios conectados.
        self.serial = serial or os.environ.get("ADB_SERIAL")

    # --- utilidades internas -------------------------------------------------

    def _adb_args(self, *args: str) -> List[str]:
        base = [self.adb]
        if self.serial:
            base += ["-s", self.serial]
        return base + list(args)

    def _run(self, *args: str, timeout: int = 20) -> subprocess.CompletedProcess:
        """Ejecuta un comando ADB y devuelve el CompletedProcess (nunca lanza)."""
        try:
            return subprocess.run(
                self._adb_args(*args),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except Exception as e:  # noqa: BLE001
            log.warning(f"[rotador] Fallo ejecutando ADB {' '.join(args)}: {e}")
            return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr=str(e))

    # --- estado del dispositivo ---------------------------------------------

    def disponible(self) -> bool:
        """True si ADB existe y hay al menos un dispositivo autorizado ('device')."""
        if not self.adb:
            log.error(
                "[rotador] No se encontró ADB. Instala Android Platform Tools y/o "
                "define ADB_PATH con la ruta a adb.exe."
            )
            return False
        salida = self._run("devices").stdout.strip().splitlines()
        # La primera línea es el encabezado 'List of devices attached'.
        dispositivos = [l for l in salida[1:] if l.strip() and "\tdevice" in l]
        if not dispositivos:
            no_autorizados = [l for l in salida[1:] if "unauthorized" in l]
            if no_autorizados:
                log.error("[rotador] Dispositivo conectado pero NO autorizado. Acepta el "
                          "aviso de 'Depuración USB' en el celular.")
            else:
                log.error("[rotador] No hay ningún dispositivo Android conectado por USB.")
            return False
        return True

    # --- toggles -------------------------------------------------------------

    def _airplane(self, activar: bool) -> bool:
        """
        Activa/desactiva el modo avión. Devuelve True si el comando reportó éxito.

        Estrategia 1 (Android 10+, sin root): `cmd connectivity airplane-mode`.
        Estrategia 2 (clásica, requiere root en Android 8+): setting + broadcast.
        """
        estado = "enable" if activar else "disable"
        r = self._run("shell", "cmd", "connectivity", "airplane-mode", estado)
        if r.returncode == 0 and "error" not in (r.stderr or "").lower():
            return True

        # Fallback clásico (setting + broadcast). Necesita 'su' en Android moderno.
        valor = "1" if activar else "0"
        self._run("shell", "settings", "put", "global", "airplane_mode_on", valor)
        booleano = "true" if activar else "false"
        r2 = self._run(
            "shell", "su", "-c",
            f"am broadcast -a android.intent.action.AIRPLANE_MODE --ez state {booleano}",
        )
        return r2.returncode == 0

    def _datos_moviles(self, activar: bool) -> bool:
        """Activa/desactiva los datos móviles con `svc data` (puede requerir root)."""
        estado = "enable" if activar else "disable"
        r = self._run("shell", "svc", "data", estado)
        return r.returncode == 0

    # --- acción principal ----------------------------------------------------

    def rotar_ip(
        self,
        segundos_min: float = 5.0,
        segundos_max: float = 10.0,
        verificar_ip: bool = True,
    ) -> bool:
        """
        Ciclo de rotación: modo avión ON -> espera 5-10 s -> modo avión OFF y
        reactivar datos móviles. Devuelve True si el ciclo se ejecutó.

        Con verificar_ip=True consulta la IP pública antes y después y avisa si
        NO cambió (útil para detectar que el tethering no está activo o que el
        operador reasignó la misma IP).
        """
        if not self.disponible():
            return False

        ip_antes = obtener_ip_publica() if verificar_ip else None
        if verificar_ip:
            log.info(f"[rotador] IP antes: {ip_antes or 'desconocida'}")

        espera = random.uniform(segundos_min, segundos_max)
        log.info(f"[rotador] Activando modo avión ({espera:.1f}s) para rotar IP...")

        if not self._airplane(True):
            log.warning("[rotador] No se pudo activar el modo avión (¿requiere root?).")
            # Intento alternativo: al menos apagar los datos móviles.
            self._datos_moviles(False)

        time.sleep(espera)

        # Reactivar la radio y asegurar los datos móviles encendidos.
        self._airplane(False)
        time.sleep(1.5)
        self._datos_moviles(True)

        # Margen para que el operador re-registre la red y asigne IP nueva.
        time.sleep(5)

        if not verificar_ip:
            log.exito("[rotador] IP rotada (modo avión OFF + datos móviles ON).")
            return True

        # Verificación: reintenta unos segundos porque la red tarda en volver.
        ip_despues = None
        for _ in range(4):
            ip_despues = obtener_ip_publica()
            if ip_despues and ip_despues != ip_antes:
                break
            time.sleep(3)

        if not ip_despues:
            log.warning("[rotador] No se pudo verificar la IP pública tras la rotación "
                        "(¿sin internet por el tethering?).")
        elif ip_antes and ip_despues == ip_antes:
            log.warning(f"[rotador] La IP NO cambió (sigue {ip_despues}). Revisa que el "
                        "tethering USB esté activo y que navegues por datos móviles.")
        else:
            log.exito(f"[rotador] IP rotada OK: {ip_antes or '?'} -> {ip_despues}")
        return True


# ---------------------------------------------------------------------------
# API DE CONVENIENCIA (para llamar desde main.py sin que nada lance)
# ---------------------------------------------------------------------------

def rotar_ip_seguro(
    segundos_min: float = 5.0,
    segundos_max: float = 10.0,
    adb_path: Optional[str] = None,
    serial: Optional[str] = None,
    verificar_ip: bool = True,
) -> bool:
    """
    Rota la IP móvil de forma DEFENSIVA: ante cualquier problema (sin ADB, sin
    dispositivo, sin root) registra un aviso y devuelve False, sin lanzar. Pensado
    para llamarse entre cuentas sin arriesgar el lote.
    """
    try:
        return RotadorIP(adb_path=adb_path, serial=serial).rotar_ip(
            segundos_min, segundos_max, verificar_ip=verificar_ip
        )
    except Exception as e:  # noqa: BLE001
        log.warning(f"[rotador] Rotación de IP omitida por un error: {e}")
        return False


# ---------------------------------------------------------------------------
# PRUEBA MANUAL
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    log.info("=== Prueba del rotador de IP (ADB) ===")
    adb = encontrar_adb()
    log.info(f"ADB: {adb or 'NO ENCONTRADO'}")
    rot = RotadorIP()
    if rot.disponible():
        rot.rotar_ip()
    else:
        log.error("No se pudo rotar: revisa la conexión USB y la depuración.")
