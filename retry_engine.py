"""
retry_engine.py
===============

Motor de reintentos inteligente con backoff exponencial para cuentas fallidas.

Características:
- Backoff exponencial: 30s, 2min, 5min, 15min, 30min...
- Cambio completo de identidad en cada reintento (MAC + IP + perfil)
- Máximo de intentos configurable por cuenta
- Registro detallado de motivos de fallo
- Reintento selectivo de cuentas fallidas
- Estadísticas de éxito por tipo de error
"""

from __future__ import annotations

import asyncio
import json
import os
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from enum import Enum

from auditor import log


# ---------------------------------------------------------------------------
# TIPOS DE ERROR Y ESTADOS
# ---------------------------------------------------------------------------

class ErrorType(Enum):
    """Tipos de errores conocidos."""
    REGISTRO_FALLIDO = "registro_fallido"
    LOGIN_FALLIDO = "login_fallido"
    CAPTCHA_NO_RESUELTO = "captcha_no_resuelto"
    SIN_CODIGO_2FA = "sin_codigo_2fa"
    CUENTA_LIMITADA = "cuenta_limitada"
    SIN_BONO = "sin_bono"
    ERROR_RED = "error_red"
    ERROR_NAVEGADOR = "error_navegador"
    TIMEOUT = "timeout"
    DESCONOCIDO = "desconocido"


class CuentaEstado(Enum):
    """Estados posibles de una cuenta."""
    PENDIENTE = "pendiente"
    EN_PROCESO = "en_proceso"
    EXITOSA = "exitosa"
    FALLIDA = "fallida"
    REINTENTANDO = "reintentando"
    DESCARTADA = "descartada"


@dataclass
class IntentoFallido:
    """Registro de un intento fallido."""
    intento_num: int
    timestamp: str
    error_type: str
    motivo: str
    mac_usada: Optional[str] = None
    ip_usada: Optional[str] = None
    perfil_id: Optional[int] = None


@dataclass
class CuentaReintento:
    """Información completa de una cuenta para reintentos."""
    fila_index: int
    datos_cuenta: Dict[str, Any]
    estado: str = CuentaEstado.PENDIENTE.value
    intentos_fallidos: List[IntentoFallido] = field(default_factory=list)
    ultimo_intento: Optional[str] = None
    proximo_reintento: Optional[str] = None
    exito_final: bool = False
    resultado_final: Optional[Dict] = None
    
    # Configuración específica
    max_intentos: int = 5
    backoff_base_segundos: float = 30.0
    backoff_max_segundos: float = 1800.0  # 30 minutos
    
    def to_dict(self) -> Dict:
        """Convierte a dict para serialización JSON."""
        return {
            "fila_index": self.fila_index,
            "datos_cuenta": self.datos_cuenta,
            "estado": self.estado,
            "intentos_fallidos": [asdict(i) for i in self.intentos_fallidos],
            "ultimo_intento": self.ultimo_intento,
            "proximo_reintento": self.proximo_reintento,
            "exito_final": self.exito_final,
            "resultado_final": self.resultado_final,
            "max_intentos": self.max_intentos,
            "backoff_base_segundos": self.backoff_base_segundos,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "CuentaReintento":
        """Crea instancia desde dict."""
        intentos = [
            IntentoFallido(**i) if isinstance(i, dict) else i
            for i in data.get("intentos_fallidos", [])
        ]
        return cls(
            fila_index=data["fila_index"],
            datos_cuenta=data["datos_cuenta"],
            estado=data.get("estado", CuentaEstado.PENDIENTE.value),
            intentos_fallidos=intentos,
            ultimo_intento=data.get("ultimo_intento"),
            proximo_reintento=data.get("proximo_reintento"),
            exito_final=data.get("exito_final", False),
            resultado_final=data.get("resultado_final"),
            max_intentos=data.get("max_intentos", 5),
            backoff_base_segundos=data.get("backoff_base_segundos", 30.0),
        )


# ---------------------------------------------------------------------------
# CÁLCULO DE BACKOFF EXPONENCIAL
# ---------------------------------------------------------------------------

def calcular_backoff_exponencial(
    intento_num: int,
    base_segundos: float = 30.0,
    max_segundos: float = 1800.0,
    jitter: bool = True
) -> float:
    """
    Calcula el tiempo de espera con backoff exponencial.
    
    Fórmula: min(base * 2^(intento-1), max) + jitter
    
    Ejemplos:
    - Intento 1: 30s
    - Intento 2: 60s (1 min)
    - Intento 3: 120s (2 min)
    - Intento 4: 240s (4 min)
    - Intento 5: 480s (8 min)
    - Intento 6+: max (30 min)
    """
    wait_time = base_segundos * (2 ** (intento_num - 1))
    wait_time = min(wait_time, max_segundos)
    
    # Añadir jitter aleatorio (±20%) para evitar sincronización
    if jitter:
        jitter_factor = random.uniform(0.8, 1.2)
        wait_time *= jitter_factor
    
    return round(wait_time, 2)


def calcular_tiempo_proximo_reintento(
    intento_num: int,
    base_segundos: float = 30.0,
    max_segundos: float = 1800.0
) -> str:
    """Calcula el timestamp del próximo reintento permitido."""
    wait_seconds = calcular_backoff_exponencial(intento_num, base_segundos, max_segundos)
    proximo = datetime.now() + timedelta(seconds=wait_seconds)
    return proximo.isoformat()


# ---------------------------------------------------------------------------
# GESTIÓN DE COLA DE REINTENTOS
# ---------------------------------------------------------------------------

ARCHIVO_REINTENTOS = "reintentos.json"
ARCHIVO_ESTADISTICAS = "estadisticas_reintentos.json"


class RetryEngine:
    """
    Motor de reintentos con backoff exponencial.
    
    Uso típico:
        engine = RetryEngine(max_intentos=5)
        
        # Registrar fallo
        engine.registrar_fallo(cuenta_datos, error_type, motivo, fila_index)
        
        # Verificar si se puede reintentar
        if engine.puede_reintentar(fila_index):
            engine.preparar_reintento(fila_index)
            # ... ejecutar proceso de creación ...
            
        # Registrar éxito
        engine.registrar_exito(fila_index, resultado)
    """
    
    def __init__(
        self,
        max_intentos: int = 5,
        backoff_base: float = 30.0,
        backoff_max: float = 1800.0,
        archivo_guardado: str = ARCHIVO_REINTENTOS
    ):
        self.max_intentos = max_intentos
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        self.archivo_guardado = archivo_guardado
        
        # Cola de reintentos: fila_index -> CuentaReintento
        self.cuentas: Dict[int, CuentaReintento] = {}
        
        # Cargar estado previo si existe
        self.cargar_desde_archivo()
    
    def registrar_fallo(
        self,
        datos_cuenta: Dict[str, Any],
        error_type: ErrorType | str,
        motivo: str,
        fila_index: int,
        mac_usada: Optional[str] = None,
        ip_usada: Optional[str] = None,
        perfil_id: Optional[int] = None
    ) -> CuentaReintento:
        """Registra un intento fallido y programa el próximo reintento."""
        
        # Convertir error_type a string si es Enum
        if isinstance(error_type, ErrorType):
            error_type_str = error_type.value
        else:
            error_type_str = str(error_type)
        
        # Obtener o crear registro de cuenta
        if fila_index not in self.cuentas:
            cuenta = CuentaReintento(
                fila_index=fila_index,
                datos_cuenta=datos_cuenta,
                max_intentos=self.max_intentos,
                backoff_base_segundos=self.backoff_base,
                backoff_max_segundos=self.backoff_max,
            )
            self.cuentas[fila_index] = cuenta
        else:
            cuenta = self.cuentas[fila_index]
        
        # Registrar intento fallido
        intento = IntentoFallido(
            intento_num=len(cuenta.intentos_fallidos) + 1,
            timestamp=datetime.now().isoformat(),
            error_type=error_type_str,
            motivo=motivo,
            mac_usada=mac_usada,
            ip_usada=ip_usada,
            perfil_id=perfil_id,
        )
        cuenta.intentos_fallidos.append(intento)
        cuenta.ultimo_intento = intento.timestamp
        cuenta.estado = CuentaEstado.FALLIDA.value
        
        # Calcular próximo reintento
        if len(cuenta.intentos_fallidos) < cuenta.max_intentos:
            cuenta.proximo_reintento = calcular_tiempo_proximo_reintento(
                len(cuenta.intentos_fallidos),
                self.backoff_base,
                self.backoff_max
            )
            cuenta.estado = CuentaEstado.REINTENTANDO.value
            
            wait_seconds = calcular_backoff_exponencial(
                len(cuenta.intentos_fallidos),
                self.backoff_base,
                self.backoff_max
            )
            log.warning(
                f"[Reintento] Cuenta {fila_index} falló ({error_type_str}). "
                f"Próximo reintento en {wait_seconds:.0f}s ({cuenta.proximo_reintento})"
            )
        else:
            cuenta.estado = CuentaEstado.DESCARTADA.value
            cuenta.proximo_reintento = None
            log.error(
                f"[Reintento] Cuenta {fila_index} DESCARTADA tras {cuenta.max_intentos} intentos fallidos. "
                f"Último error: {error_type_str}"
            )
        
        # Guardar estado
        self.guardar_en_archivo()
        
        return cuenta
    
    def puede_reintentar(self, fila_index: int) -> bool:
        """Verifica si una cuenta puede ser reintentada."""
        if fila_index not in self.cuentas:
            return False
        
        cuenta = self.cuentas[fila_index]
        
        if cuenta.estado != CuentaEstado.REINTENTANDO.value:
            return False
        
        if not cuenta.proximo_reintento:
            return False
        
        # Verificar si ya pasó el tiempo de backoff
        try:
            proximo_dt = datetime.fromisoformat(cuenta.proximo_reintento)
            if datetime.now() >= proximo_dt:
                return True
            else:
                restante = (proximo_dt - datetime.now()).total_seconds()
                log.info(f"[Reintento] Cuenta {fila_index}: esperar {restante:.0f}s más")
                return False
        except ValueError:
            return False
    
    def preparar_reintento(self, fila_index: int) -> Optional[CuentaReintento]:
        """Prepara una cuenta para reintento (cambia estado)."""
        if not self.puede_reintentar(fila_index):
            return None
        
        cuenta = self.cuentas[fila_index]
        cuenta.estado = CuentaEstado.PENDIENTE.value
        cuenta.proximo_reintento = None
        
        log.info(f"[Reintento] Cuenta {fila_index} lista para nuevo intento")
        
        return cuenta
    
    def registrar_exito(
        self,
        fila_index: int,
        resultado: Dict[str, Any]
    ) -> bool:
        """Registra un éxito final de cuenta."""
        if fila_index not in self.cuentas:
            # Éxito en primer intento, no estaba en cola
            return True
        
        cuenta = self.cuentas[fila_index]
        cuenta.exito_final = True
        cuenta.resultado_final = resultado
        cuenta.estado = CuentaEstado.EXITOSA.value
        
        num_intentos = len(cuenta.intentos_fallidos) + 1
        log.exito(
            f"[Reintento] Cuenta {fila_index} EXITOSA tras {num_intentos} intento(s)"
        )
        
        # Eliminar de la cola de reintentos (ya no se necesita)
        del self.cuentas[fila_index]
        self.guardar_en_archivo()
        
        return True
    
    def obtener_cuentas_pendientes(self) -> List[CuentaReintento]:
        """Obtiene todas las cuentas listas para reintentar."""
        pendientes = []
        for fila_index, cuenta in self.cuentas.items():
            if self.puede_reintentar(fila_index):
                pendientes.append(cuenta)
        return pendientes
    
    def obtener_estadisticas(self) -> Dict[str, Any]:
        """Obtiene estadísticas de reintentos."""
        total_cuentas = len(self.cuentas)
        estados = {}
        errores = {}
        
        for cuenta in self.cuentas.values():
            # Contar por estado
            estado = cuenta.estado
            estados[estado] = estados.get(estado, 0) + 1
            
            # Contar por tipo de error
            for intento in cuenta.intentos_fallidos:
                error = intento.error_type
                errores[error] = errores.get(error, 0) + 1
        
        return {
            "total_en_cola": total_cuentas,
            "por_estado": estados,
            "por_tipo_error": errores,
            "timestamp": datetime.now().isoformat(),
        }
    
    def guardar_en_archivo(self):
        """Guarda el estado actual en archivo JSON."""
        try:
            os.makedirs(os.path.dirname(self.archivo_guardado) if os.path.dirname(self.archivo_guardado) else ".", exist_ok=True)
            datos = {
                index: cuenta.to_dict()
                for index, cuenta in self.cuentas.items()
            }
            with open(self.archivo_guardado, "w", encoding="utf-8") as f:
                json.dump(datos, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.error(f"[Reintento] Error guardando archivo: {e}")
    
    def cargar_desde_archivo(self):
        """Carga el estado desde archivo JSON."""
        if not os.path.exists(self.archivo_guardado):
            return
        
        try:
            with open(self.archivo_guardado, "r", encoding="utf-8") as f:
                datos = json.load(f)
            
            self.cuentas = {
                int(index): CuentaReintento.from_dict(cuenta_data)
                for index, cuenta_data in datos.items()
            }
            
            log.info(f"[Reintento] Cargadas {len(self.cuentas)} cuentas desde archivo")
        except Exception as e:
            log.error(f"[Reintento] Error cargando archivo: {e}")
            self.cuentas = {}
    
    def limpiar_archivo(self):
        """Limpia el archivo de reintentos (para comenzar de cero)."""
        if os.path.exists(self.archivo_guardado):
            os.remove(self.archivo_guardado)
        self.cuentas = {}
        log.info("[Reintento] Archivo de reintentos limpiado")


# ---------------------------------------------------------------------------
# ESPERA ASÍNCRONA CON PROGRESO
# ---------------------------------------------------------------------------

async def esperar_con_progreso(
    segundos: float,
    mensaje: str = "Esperando...",
    intervalo_reporte: float = 10.0
) -> None:
    """
    Espera mostrando progreso periódico en los logs.
    
    Útil para waits largos de backoff donde el usuario quiere ver
    que el bot sigue activo.
    """
    elapsed = 0.0
    while elapsed < segundos:
        await asyncio.sleep(min(intervalo_reporte, segundos - elapsed))
        elapsed += intervalo_reporte
        restante = segundos - elapsed
        if restante > 0:
            log.info(f"{mensaje} Faltan {restante:.0f}s...")


# ---------------------------------------------------------------------------
# FUNCIONES DE CONVENIENCIA
# ---------------------------------------------------------------------------

# Instancia global única (singleton)
_retry_engine_instance: Optional[RetryEngine] = None


def get_retry_engine() -> RetryEngine:
    """Obtiene la instancia global del RetryEngine."""
    global _retry_engine_instance
    if _retry_engine_instance is None:
        _retry_engine_instance = RetryEngine()
    return _retry_engine_instance


def init_retry_engine(
    max_intentos: int = 5,
    backoff_base: float = 30.0,
    backoff_max: float = 1800.0
) -> RetryEngine:
    """Inicializa el RetryEngine con configuración personalizada."""
    global _retry_engine_instance
    _retry_engine_instance = RetryEngine(
        max_intentos=max_intentos,
        backoff_base=backoff_base,
        backoff_max=backoff_max,
    )
    return _retry_engine_instance


def registrar_fallo_cuenta(
    datos_cuenta: Dict,
    error_type: ErrorType | str,
    motivo: str,
    fila_index: int,
    **kwargs
) -> CuentaReintento:
    """Función de alto nivel para registrar fallo."""
    engine = get_retry_engine()
    return engine.registrar_fallo(
        datos_cuenta, error_type, motivo, fila_index, **kwargs
    )


def verificar_y_preparar_reintento(fila_index: int) -> Optional[CuentaReintento]:
    """Verifica si hay reintento pendiente y lo prepara."""
    engine = get_retry_engine()
    return engine.preparar_reintento(fila_index)


# ---------------------------------------------------------------------------
# PRUEBA MANUAL
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio
    
    log.info("=== Prueba del Retry Engine ===\n")
    
    engine = RetryEngine(max_intentos=5, backoff_base=10.0, backoff_max=120.0)
    
    # Simular fallos consecutivos
    datos_prueba = {"correo": "test@example.com", "nombre": "Test"}
    
    for i in range(4):
        log.info(f"\n--- Registrando fallo {i+1} ---")
        cuenta = engine.registrar_fallo(
            datos_cuenta=datos_prueba,
            error_type=ErrorType.REGISTRO_FALLIDO,
            motivo=f"Error de prueba {i+1}",
            fila_index=123,
        )
        
        print(f"Estado: {cuenta.estado}")
        print(f"Intentos: {len(cuenta.intentos_fallidos)}")
        print(f"Próximo reintento: {cuenta.proximo_reintento}")
        
        if i < 3:
            # Esperar un poco para simular paso del tiempo
            time.sleep(11)  # Un poco más que el backoff base
    
    # Verificar estadísticas
    stats = engine.obtener_estadisticas()
    print("\n=== Estadísticas ===")
    print(json.dumps(stats, indent=2))
    
    log.info("\n=== Prueba completada ===")
