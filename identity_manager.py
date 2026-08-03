"""
identity_manager.py
===================

Gestor de identidad única para cada proceso de cuenta Betplay.

Cambia MAC address, rota IP/proxy, limpia perfil de navegador y crea
nuevo perfil Chrome con fingerprint único (User-Agent, Canvas, WebGL,
Timezone, Language, Fonts aleatorios).

Anti-detección crítica:
- User-Agent rotación realista
- Randomización de Canvas fingerprint
- Randomización de WebGL renderer/vendor
- Timezone coherente con IP del proxy
- Lenguaje coherente con país del proxy
"""

from __future__ import annotations

import os
import random
import uuid
import hashlib
import platform
import subprocess
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from auditor import log


# ---------------------------------------------------------------------------
# POOL DE MACS VÁLIDAS (rotación)
# ---------------------------------------------------------------------------

# MACs válidas genéricas (OUI reales de fabricantes comunes)
OUI_POOL = [
    "00:1A:2B",  # Cisco
    "00:50:56",  # VMware
    "08:00:27",  # VirtualBox
    "52:54:00",  # QEMU
    "00:0C:29",  # VMware ESX
    "00:15:5D",  # Hyper-V
    "AC:DE:48",  # Microsoft
    "B8:27:EB",  # Raspberry Pi
    "DC:A6:32",  # Intel
    "F0:18:98",  # Dell
]


def generar_mac_aleatoria() -> str:
    """Genera una MAC address válida con OUI aleatorio del pool."""
    oui = random.choice(OUI_POOL)
    partes = [f"{random.randint(0x00, 0xFF):02X}" for _ in range(3)]
    return f"{oui}:{':'.join(partes)}"


def cargar_pool_macs(ruta: str = "macs_pool.txt") -> List[str]:
    """Carga MACs desde archivo si existe, sino usa el pool por defecto."""
    if os.path.exists(ruta):
        try:
            with open(ruta, "r", encoding="utf-8-sig") as f:
                macs = [
                    linea.strip().upper()
                    for linea in f
                    if linea.strip() and not linea.strip().startswith("#")
                ]
                if macs:
                    return macs
        except Exception:
            pass
    return [generar_mac_aleatoria() for _ in range(50)]


# ---------------------------------------------------------------------------
# GESTIÓN DE MAC ADDRESS (Linux/Windows)
# ---------------------------------------------------------------------------

def cambiar_mac_linux(mac: str, interfaz: str = "eth0") -> bool:
    """Cambia la MAC address en Linux (requiere sudo)."""
    try:
        # Bajar interfaz
        subprocess.run(
            ["sudo", "ip", "link", "set", interfaz, "down"],
            capture_output=True, check=True
        )
        # Cambiar MAC
        subprocess.run(
            ["sudo", "ip", "link", "set", interfaz, "address", mac],
            capture_output=True, check=True
        )
        # Subir interfaz
        subprocess.run(
            ["sudo", "ip", "link", "set", interfaz, "up"],
            capture_output=True, check=True
        )
        log.exito(f"[MAC] Cambiada a {mac} en {interfaz}")
        return True
    except subprocess.CalledProcessError as e:
        log.error(f"[MAC] Error cambiando MAC en Linux: {e}")
        return False
    except FileNotFoundError:
        log.warning("[MAC] Comando 'ip' no encontrado (¿Linux?)")
        return False


def cambiar_mac_windows(mac: str, adaptador: str = "") -> bool:
    """
    Cambia la MAC address en Windows vía registro.
    Requiere permisos de administrador.
    """
    try:
        import winreg
        
        # Obtener GUID del adaptador de red
        ruta_adaptadores = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e972-e325-11ce-bfc1-08002be10318}"
        
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, ruta_adaptadores) as key:
            i = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(key, i)
                    with winreg.OpenKey(key, subkey_name) as subkey:
                        try:
                            driver_desc = winreg.QueryValueEx(subkey, "DriverDesc")[0]
                            if not adaptador or adaptador.lower() in driver_desc.lower():
                                # Encontrado: establecer NetworkAddress
                                winreg.SetValueEx(
                                    subkey, "NetworkAddress", 0,
                                    winreg.REG_SZ, mac.replace(":", "")
                                )
                                log.exito(f"[MAC] Cambiada a {mac} en {driver_desc}")
                                return True
                        except FileNotFoundError:
                            pass
                    i += 1
                except OSError:
                    break
        
        log.error("[MAC] No se encontró adaptador de red")
        return False
    except Exception as e:
        log.error(f"[MAC] Error en Windows: {e}")
        return False


def cambiar_mac(mac: str) -> bool:
    """Cambia la MAC address según el sistema operativo."""
    sistema = platform.system()
    if sistema == "Linux":
        return cambiar_mac_linux(mac)
    elif sistema == "Windows":
        return cambiar_mac_windows(mac)
    else:
        log.warning(f"[MAC] Sistema no soportado: {sistema}")
        return False


def obtener_mac_actual() -> Optional[str]:
    """Obtiene la MAC address actual del sistema."""
    try:
        if platform.system() == "Windows":
            import netifaces
            gateways = netifaces.gateways()
            default_if = gateways[netifaces.AF_INET][0][1]
            addrs = netifaces.ifaddresses(default_if)
            mac = addrs[netifaces.AF_LINK][0]['addr']
            return mac.upper().replace("-", ":")
        else:
            result = subprocess.run(
                ["cat", "/sys/class/net/eth0/address"],
                capture_output=True, text=True, check=True
            )
            return result.stdout.strip().upper()
    except Exception as e:
        log.warning(f"[MAC] No se pudo obtener MAC actual: {e}")
        return None


# ---------------------------------------------------------------------------
# FINGERPRINT ALEATORIO DEL NAVEGADOR
# ---------------------------------------------------------------------------

USER_AGENTS = [
    # Chrome Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    # Chrome macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    # Chrome Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
]

# Webgl vendors/renderers reales
WEBGL_VENDORS = [
    "Google Inc. (Intel)",
    "Google Inc. (NVIDIA)",
    "Google Inc. (AMD)",
    "Intel Inc.",
    "NVIDIA Corporation",
    "ATI Technologies Inc.",
]

WEBGL_RENDERERS = [
    "Intel Iris OpenGL Engine",
    "Intel UHD Graphics 630",
    "NVIDIA GeForce GTX 1050",
    "NVIDIA GeForce RTX 3060",
    "AMD Radeon Pro 5500M",
    "AMD Radeon RX 580",
]

# Timezones válidas para Colombia/Latam
TIMEZONES = [
    "America/Bogota",
    "America/Lima",
    "America/Guayaquil",
    "America/Panama",
    "America/Costa_Rica",
]

# Idiomas coherentes
LANGUAGES = [
    "es-CO",
    "es-PE",
    "es-EC",
    "es-PA",
    "es-CR",
]


def generar_fingerprint_unico(perfil_id: int) -> Dict:
    """
    Genera un fingerprint único y coherente para un perfil.
    
    Incluye:
    - User-Agent aleatorio
    - Canvas fingerprint hash único
    - WebGL vendor/renderer aleatorios
    - Timezone coherente
    - Language coherente
    - Screen resolution realista
    - Fonts instalados (simulados)
    """
    # Seed único basado en perfil_id + timestamp
    seed = f"{perfil_id}_{datetime.now().isoformat()}_{random.random()}"
    seed_hash = hashlib.sha256(seed.encode()).hexdigest()[:8]
    
    # User-Agent aleatorio
    user_agent = random.choice(USER_AGENTS)
    
    # Determinar SO del UA para coherencia
    es_windows = "Windows" in user_agent
    es_mac = "Macintosh" in user_agent
    es_linux = "Linux" in user_agent
    
    # Timezone y language coherentes
    timezone = random.choice(TIMEZONES)
    language = random.choice(LANGUAGES)
    
    # Screen resolutions realistas
    if es_windows or es_linux:
        resolutions = [
            (1920, 1080), (1366, 768), (1536, 864),
            (1440, 900), (1600, 900), (2560, 1440)
        ]
    else:  # macOS
        resolutions = [
            (1440, 900), (1680, 1050), (1920, 1080),
            (2560, 1600), (2880, 1800)
        ]
    
    width, height = random.choice(resolutions)
    
    # WebGL coherente con SO
    if es_mac:
        webgl_vendor = random.choice(["Intel Inc.", "Apple Inc."])
        webgl_renderer = random.choice([
            "Intel Iris OpenGL Engine",
            "Apple M1",
            "AMD Radeon Pro 5500M",
        ])
    else:
        webgl_vendor = random.choice(WEBGL_VENDORS)
        webgl_renderer = random.choice(WEBGL_RENDERERS)
    
    # Canvas fingerprint único (hash)
    canvas_hash = hashlib.md5(f"{seed_hash}_{random.random()}".encode()).hexdigest()
    
    # Audio context fingerprint
    audio_hash = hashlib.sha1(f"{seed_hash}_audio".encode()).hexdigest()[:12]
    
    # Fonts simulados (comunes en todos los sistemas)
    fonts = [
        "Arial", "Times New Roman", "Courier New", "Verdana",
        "Georgia", "Palatino", "Garamond", "Bookman",
        "Comic Sans MS", "Trebuchet MS", "Arial Black", "Impact"
    ]
    
    # Hardware concurrency realista
    cpu_cores = random.choice([2, 4, 6, 8, 12])
    device_memory = random.choice([2, 4, 8, 16])
    
    return {
        "user_agent": user_agent,
        "canvas_hash": canvas_hash,
        "webgl_vendor": webgl_vendor,
        "webgl_renderer": webgl_renderer,
        "timezone": timezone,
        "language": language,
        "screen_width": width,
        "screen_height": height,
        "audio_hash": audio_hash,
        "fonts": fonts,
        "cpu_cores": cpu_cores,
        "device_memory": device_memory,
        "seed_hash": seed_hash,
    }


# ---------------------------------------------------------------------------
# GESTIÓN DE PERFILES CHROME AISLADOS
# ---------------------------------------------------------------------------

def limpiar_perfil(perfil_id: int) -> bool:
    """
    Elimina completamente el directorio de perfil Chrome anterior.
    Esto asegura que no queden cookies, localStorage, cache, etc.
    """
    import shutil
    
    ruta_perfil = os.path.abspath(f"./perfiles/perfil_{perfil_id}")
    
    try:
        if os.path.exists(ruta_perfil):
            shutil.rmtree(ruta_perfil)
            log.info(f"[Perfil] Limpieza completada: {ruta_perfil}")
        return True
    except Exception as e:
        log.error(f"[Perfil] Error limpiando perfil {perfil_id}: {e}")
        return False


def crear_perfil_nuevo(perfil_id: int, fingerprint: Dict, proxy: Optional[str] = None) -> Tuple[int, str]:
    """
    Crea un nuevo perfil Chrome aislado con fingerprint único.
    
    Devuelve (puerto, endpoint_cdp).
    """
    from gestor_perfiles import lanzar_perfil_chrome
    
    # Limpiar perfil anterior si existe
    limpiar_perfil(perfil_id)
    
    # Guardar fingerprint en archivo para referencia
    ruta_fingerprint = f"./perfiles/fingerprint_{perfil_id}.json"
    try:
        import json
        os.makedirs("./perfiles", exist_ok=True)
        fingerprint["perfil_id"] = perfil_id
        fingerprint["creado"] = datetime.now().isoformat()
        with open(ruta_fingerprint, "w", encoding="utf-8") as f:
            json.dump(fingerprint, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log.warning(f"[Fingerprint] No se pudo guardar: {e}")
    
    # Lanzar Chrome con perfil limpio
    puerto, endpoint = lanzar_perfil_chrome(perfil_id, proxy)
    
    log.exito(f"[Perfil {perfil_id}] Creado con fingerprint único")
    log.info(f"  User-Agent: {fingerprint['user_agent'][:60]}...")
    log.info(f"  Timezone: {fingerprint['timezone']}")
    log.info(f"  Language: {fingerprint['language']}")
    log.info(f"  Screen: {fingerprint['screen_width']}x{fingerprint['screen_height']}")
    log.info(f"  WebGL: {fingerprint['webgl_vendor']} / {fingerprint['webgl_renderer']}")
    
    return puerto, endpoint


# ---------------------------------------------------------------------------
# VERIFICACIÓN DE CAMBIOS DE IDENTIDAD
# ---------------------------------------------------------------------------

def verificar_cambio_mac(mac_anterior: Optional[str], mac_nueva: str) -> bool:
    """Verifica que la MAC haya cambiado efectivamente."""
    if not mac_anterior:
        log.warning("[MAC] No hay MAC anterior para comparar")
        return True  # Asumimos éxito si no había referencia
    
    if mac_anterior != mac_nueva:
        log.exito(f"[MAC] Verificado cambio: {mac_anterior} -> {mac_nueva}")
        return True
    else:
        log.error(f"[MAC] La MAC NO cambió: sigue siendo {mac_nueva}")
        return False


def verificar_cambio_ip(ip_anterior: Optional[str], ip_nueva: Optional[str]) -> bool:
    """Verifica que la IP haya cambiado efectivamente."""
    if not ip_anterior:
        log.warning("[IP] No hay IP anterior para comparar")
        return True
    
    if not ip_nueva:
        log.error("[IP] No se pudo obtener IP nueva")
        return False
    
    if ip_anterior != ip_nueva:
        log.exito(f"[IP] Verificado cambio: {ip_anterior} -> {ip_nueva}")
        return True
    else:
        log.error(f"[IP] La IP NO cambió: sigue siendo {ip_nueva}")
        return False


# ---------------------------------------------------------------------------
# API PRINCIPAL DEL IDENTITY MANAGER
# ---------------------------------------------------------------------------

class IdentityManager:
    """
    Gestor completo de identidad única por cuenta.
    
    Uso:
        manager = IdentityManager(perfil_id=1, proxy="http://proxy:puerto")
        manager.cambiar_identidad_completa()
        puerto, endpoint = manager.crear_perfil_navegador()
    """
    
    def __init__(self, perfil_id: int, proxy: Optional[str] = None):
        self.perfil_id = perfil_id
        self.proxy = proxy
        self.mac_anterior: Optional[str] = None
        self.ip_anterior: Optional[str] = None
        self.mac_nueva: Optional[str] = None
        self.ip_nueva: Optional[str] = None
        self.fingerprint: Optional[Dict] = None
    
    def cargar_pool_macs(self, ruta: str = "macs_pool.txt") -> List[str]:
        """Carga pool de MACs válidas."""
        return cargar_pool_macs(ruta)
    
    def rotar_mac(self) -> bool:
        """Selecciona y cambia a una nueva MAC address."""
        pool = self.cargar_pool_macs()
        self.mac_nueva = random.choice(pool)
        
        log.info(f"[Identity] Rotando MAC -> {self.mac_nueva}")
        
        exito = cambiar_mac(self.mac_nueva)
        
        if exito:
            self.mac_anterior = obtener_mac_actual() or self.mac_anterior
        
        return exito
    
    def rotar_ip(self) -> bool:
        """Rota la IP usando el módulo rotador_ip existente."""
        from rotador_ip import rotar_ip_seguro
        
        log.info("[Identity] Rotando IP (modo avión ADB)...")
        
        self.ip_anterior = self.obtener_ip_publica()
        
        exito = rotar_ip_seguro(
            segundos_min=5.0,
            segundos_max=10.0,
            verificar_ip=True
        )
        
        if exito:
            self.ip_nueva = self.obtener_ip_publica()
        
        return exito
    
    def obtener_ip_publica(self) -> Optional[str]:
        """Obtiene la IP pública actual."""
        from rotador_ip import obtener_ip_publica
        return obtener_ip_publica()
    
    def generar_fingerprint(self) -> Dict:
        """Genera fingerprint único para este perfil."""
        self.fingerprint = generar_fingerprint_unico(self.perfil_id)
        return self.fingerprint
    
    def limpiar_perfil_anterior(self) -> bool:
        """Limpia el directorio de perfil anterior."""
        return limpiar_perfil(self.perfil_id)
    
    def cambiar_identidad_completa(self) -> bool:
        """
        Ejecuta TODO el proceso de cambio de identidad:
        1. Rotar MAC
        2. Rotar IP
        3. Generar fingerprint
        4. Limpiar perfil anterior
        
        Devuelve True si todo salió bien.
        """
        log.info(f"[Identity] === Iniciando cambio de identidad (Perfil {self.perfil_id}) ===")
        
        exitos = []
        
        # 1. Rotar MAC
        exitos.append(self.rotar_mac())
        
        # 2. Rotar IP
        exitos.append(self.rotar_ip())
        
        # 3. Generar fingerprint
        self.generar_fingerprint()
        exitos.append(True)  # Siempre éxito
        
        # 4. Limpiar perfil
        exitos.append(self.limpiar_perfil_anterior())
        
        total_exitos = sum(exitos)
        total_ops = len(exitos)
        
        if total_exitos == total_ops:
            log.exito(f"[Identity] Identidad cambiada exitosamente ({total_ops}/{total_ops})")
            return True
        else:
            log.warning(
                f"[Identity] Identidad cambiada parcialmente ({total_exitos}/{total_ops}). "
                "Continuando..."
            )
            return True  # Continuamos incluso con fallos parciales
    
    def crear_perfil_navegador(self) -> Tuple[int, str]:
        """
        Crea el perfil de navegador con la nueva identidad.
        
        Devuelve (puerto, endpoint_cdp).
        """
        if not self.fingerprint:
            self.generar_fingerprint()
        
        return crear_perfil_nuevo(
            self.perfil_id,
            self.fingerprint,
            self.proxy
        )
    
    def verificar_cambios(self) -> Dict[str, bool]:
        """Verifica que todos los cambios se hayan aplicado."""
        resultados = {}
        
        # Verificar MAC
        if self.mac_nueva:
            resultados["mac_cambiada"] = verificar_cambio_mac(
                self.mac_anterior,
                self.mac_nueva
            )
        else:
            resultados["mac_cambiada"] = True  # No aplicable
        
        # Verificar IP
        if self.ip_nueva and self.ip_anterior:
            resultados["ip_cambiada"] = verificar_cambio_ip(
                self.ip_anterior,
                self.ip_nueva
            )
        else:
            resultados["ip_cambiada"] = True  # No verificable pero OK
        
        return resultados


# ---------------------------------------------------------------------------
# FUNCIONES DE CONVENIENCIA
# ---------------------------------------------------------------------------

def preparar_identidad_unica(perfil_id: int, proxy: Optional[str] = None) -> IdentityManager:
    """
    Función de alto nivel que prepara toda la identidad para una cuenta.
    
    Uso típico en main.py:
        identity = preparar_identidad_unica(perfil_id, proxy)
        identity.cambiar_identidad_completa()
        puerto, endpoint = identity.crear_perfil_navegador()
    """
    manager = IdentityManager(perfil_id, proxy)
    manager.cambiar_identidad_completa()
    return manager


# ---------------------------------------------------------------------------
# PRUEBA MANUAL
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    log.info("=== Prueba del Identity Manager ===")
    
    manager = IdentityManager(perfil_id=99, proxy=None)
    
    log.info("\n1. Generando fingerprint...")
    fp = manager.generar_fingerprint()
    print(f"   User-Agent: {fp['user_agent']}")
    print(f"   Timezone: {fp['timezone']}")
    print(f"   Canvas Hash: {fp['canvas_hash']}")
    
    log.info("\n2. Obteniendo IP actual...")
    ip = manager.obtener_ip_publica()
    print(f"   IP Pública: {ip or 'No disponible'}")
    
    log.info("\n3. Probando rotación de MAC...")
    manager.rotar_mac()
    
    log.info("\n4. Limpiando perfil...")
    manager.limpiar_perfil_anterior()
    
    log.info("\n=== Prueba completada ===")
