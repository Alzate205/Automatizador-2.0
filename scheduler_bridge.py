"""
scheduler_bridge.py
===================

Puente entre el scheduler y el sistema principal del bot.

Este módulo:
1. Expone una función para iniciar el scheduler desde el dashboard
2. Unifica el control del scheduler con las señales del panel (control.py)
3. Permite ejecutar el scheduler en segundo plano sin bloquear el dashboard
4. Proporciona funciones para consultar estado y estadísticas
"""

from __future__ import annotations

import asyncio
import threading
from typing import Optional, Dict, Any
from datetime import datetime

from auditor import log
import control
from scheduler import Scheduler, ConfigCiclo, SchedulerEstado


# ---------------------------------------------------------------------------
# VARIABLES GLOBALES DE ESTADO
# ---------------------------------------------------------------------------

_scheduler_instance: Optional[Scheduler] = None
_scheduler_thread: Optional[threading.Thread] = None
_scheduler_running = False
_scheduler_lock = threading.Lock()


# ---------------------------------------------------------------------------
# FUNCIONES DE CONTROL DEL SCHEDULER
# ---------------------------------------------------------------------------

def obtener_scheduler() -> Optional[Scheduler]:
    """Obtiene la instancia actual del scheduler."""
    global _scheduler_instance
    return _scheduler_instance


def iniciar_scheduler(
    cuentas_por_ciclo: int = 10,
    pausa_min_minutos: float = 360.0,
    pausa_max_minutos: float = 480.0,
    max_ciclos: int = 0,
    reiniciar_fallidas: bool = True,
    solo_exitosas_previas: bool = False
) -> bool:
    """
    Inicia el scheduler en un hilo separado.
    
    Parámetros:
        cuentas_por_ciclo: Número de cuentas a procesar por ciclo
        pausa_min_minutos: Mínimo de minutos entre ciclos
        pausa_max_minutos: Máximo de minutos entre ciclos
        max_ciclos: Máximo de ciclos (0 = infinito)
        reiniciar_fallidas: Si reintentar cuentas fallidas previas
        solo_exitosas_previas: Si solo usar cuentas exitosas anteriores
    
    Retorna:
        True si se inició correctamente, False si ya estaba corriendo
    """
    global _scheduler_instance, _scheduler_thread, _scheduler_running
    
    with _scheduler_lock:
        if _scheduler_running:
            log.warning("[Scheduler Bridge] Ya hay un scheduler corriendo")
            return False
        
        # Crear instancia del scheduler
        _scheduler_instance = Scheduler()
        _scheduler_instance.configurar(
            cuentas_por_ciclo=cuentas_por_ciclo,
            pausa_min_minutos=pausa_min_minutos,
            pausa_max_minutos=pausa_max_minutos,
            max_ciclos=max_ciclos,
            reiniciar_fallidas=reiniciar_fallidas,
            solo_exitosas_previas=solo_exitosas_previas
        )
        
        # Importar la función de procesamiento de lotes
        from main import procesar_lote_para_scheduler
        
        # Función wrapper para ejecutar el scheduler en hilo
        def run_scheduler():
            try:
                log.info("[Scheduler Bridge] Iniciando loop del scheduler en hilo secundario")
                
                # Crear nuevo event loop para este hilo
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                async def run_loop():
                    await _scheduler_instance.iniciar_loop(procesar_lote_para_scheduler)
                
                loop.run_until_complete(run_loop())
                loop.close()
                
            except Exception as e:
                log.error(f"[Scheduler Bridge] Error en hilo del scheduler: {e}")
            finally:
                _scheduler_running = False
                control.escribir_estado(
                    estado="detenido",
                    fase="scheduler_detenido",
                    mensaje="Scheduler detenido"
                )
        
        # Iniciar hilo
        _scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        _scheduler_thread.start()
        _scheduler_running = True
        
        log.exito("[Scheduler Bridge] Scheduler iniciado en hilo secundario")
        control.escribir_estado(
            estado="corriendo",
            fase="scheduler_corriendo",
            mensaje=f"Scheduler iniciado: {cuentas_por_ciclo} cuentas/ciclo",
        )
        
        return True


def detener_scheduler() -> bool:
    """
    Solicita la detención del scheduler.
    
    Retorna:
        True si se solicitó la detención, False si no había scheduler corriendo
    """
    global _scheduler_instance, _scheduler_running
    
    with _scheduler_lock:
        if not _scheduler_running or _scheduler_instance is None:
            log.warning("[Scheduler Bridge] No hay scheduler corriendo para detener")
            return False
        
        # Señalar detención al scheduler
        _scheduler_instance.detener()
        
        # También señalar desde control para que main.py lo respete
        control.escribir_senal_detener()
        
        log.warning("[Scheduler Bridge] Solicitada detención del scheduler")
        return True


def pausar_scheduler() -> bool:
    """
    Solicita la pausa del scheduler después del ciclo actual.
    
    Retorna:
        True si se solicitó la pausa, False si no había scheduler corriendo
    """
    global _scheduler_instance, _scheduler_running
    
    with _scheduler_lock:
        if not _scheduler_running or _scheduler_instance is None:
            return False
        
        _scheduler_instance.pausar()
        log.warning("[Scheduler Bridge] Solicitada pausa del scheduler")
        return True


def reanudar_scheduler() -> bool:
    """
    Reanuda el scheduler desde pausa.
    
    Retorna:
        True si se reanudó, False si no estaba pausado
    """
    global _scheduler_instance, _scheduler_running
    
    with _scheduler_lock:
        if not _scheduler_running or _scheduler_instance is None:
            return False
        
        _scheduler_instance.reanudar()
        log.info("[Scheduler Bridge] Scheduler reanudado")
        return True


def obtener_estado_scheduler() -> Dict[str, Any]:
    """
    Obtiene el estado actual del scheduler para mostrar en el dashboard.
    
    Retorna:
        Dict con estado, ciclo actual, configuración y estadísticas
    """
    global _scheduler_instance, _scheduler_running
    
    if not _scheduler_running or _scheduler_instance is None:
        return {
            "estado": "inactivo",
            "ciclo_actual": 0,
            "config": {},
            "total_ciclos_completados": 0,
            "ultimo_reporte": None,
            "estadisticas_globales": {},
        }
    
    estado_data = _scheduler_instance.obtener_estado()
    estadisticas = _scheduler_instance.obtener_estadisticas_globales()
    
    return {
        "estado": estado_data["estado"],
        "ciclo_actual": estado_data["ciclo_actual"],
        "config": estado_data["config"],
        "total_ciclos_completados": estado_data["total_ciclos_completados"],
        "ultimo_reporte": estado_data["ultimo_reporte"],
        "estadisticas_globales": estadisticas,
        "running": _scheduler_running,
    }


def esta_corriendo() -> bool:
    """Verifica si el scheduler está actualmente corriendo."""
    return _scheduler_running


# ---------------------------------------------------------------------------
# FUNCIONES DE UTILIDAD PARA EL DASHBOARD
# ---------------------------------------------------------------------------

def formatear_estado_para_dashboard(estado_data: Dict[str, Any]) -> Dict[str, str]:
    """
    Formatea el estado del scheduler para mostrar en el dashboard.
    
    Retorna dict con textos legibles y colores sugeridos.
    """
    estado_raw = estado_data.get("estado", "inactivo")
    
    mapas_estado = {
        "detenido": {"texto": "Detenido", "color": "gray"},
        "corriendo": {"texto": "Corriendo", "color": "green"},
        "pausado": {"texto": "Pausado", "color": "orange"},
        "en_pausa_entre_ciclos": {"texto": "En pausa entre ciclos", "color": "blue"},
        "finalizado": {"texto": "Finalizado", "color": "success"},
        "error": {"texto": "Error", "color": "red"},
        "inactivo": {"texto": "Inactivo", "color": "gray"},
    }
    
    info = mapas_estado.get(estado_raw, {"texto": estado_raw, "color": "gray"})
    
    return {
        "estado_texto": info["texto"],
        "estado_color": info["color"],
        "ciclo_actual": str(estado_data.get("ciclo_actual", 0)),
        "total_ciclos": str(estado_data.get("total_ciclos_completados", 0)),
        "configuracion": _formatear_configuracion(estado_data.get("config", {})),
    }


def _formatear_configuracion(config: Dict[str, Any]) -> str:
    """Formatea la configuración como texto legible."""
    if not config:
        return "No configurado"
    
    lineas = [
        f"Cuentas por ciclo: {config.get('cuentas_por_ciclo', 'N/A')}",
        f"Pausa: {config.get('pausa_min_minutos', 0):.0f}-{config.get('pausa_max_minutos', 0):.0f} min",
        f"Máx ciclos: {'Infinito' if config.get('max_ciclos', 0) == 0 else config.get('max_ciclos', 0)}",
    ]
    
    return " | ".join(lineas)


# ---------------------------------------------------------------------------
# INTEGRACIÓN CON SEÑALES DE CONTROL
# ---------------------------------------------------------------------------

def verificar_senales_control() -> None:
    """
    Verifica las señales de control.py y las propaga al scheduler.
    
    Esta función debe ser llamada periódicamente para sincronizar
    el estado del scheduler con los botones del dashboard.
    """
    global _scheduler_instance
    
    if not _scheduler_running:
        return
    
    # Si el usuario presionó "Detener" en el dashboard
    if control.hay_senal_detener():
        log.info("[Scheduler Bridge] Detectada señal de detener desde control")
        detener_scheduler()
        control.limpiar_senal_detener()
    
    # Si el usuario presionó "Pausar" en el dashboard
    if control.hay_senal_pausar():
        log.info("[Scheduler Bridge] Detectada señal de pausar desde control")
        pausar_scheduler()
        control.limpiar_senal_pausar()
    
    # Si el usuario presionó "Reanudar" en el dashboard
    if control.hay_senal_reanudar():
        log.info("[Scheduler Bridge] Detectada señal de reanudar desde control")
        reanudar_scheduler()
        control.limpiar_senal_reanudar()


# ---------------------------------------------------------------------------
# INICIALIZACIÓN Y LIMPIEZA
# ---------------------------------------------------------------------------

def inicializar() -> None:
    """Inicializa el bridge del scheduler."""
    log.info("[Scheduler Bridge] Inicializado")


def limpiar() -> None:
    """Limpia recursos del scheduler."""
    global _scheduler_instance, _scheduler_thread, _scheduler_running
    
    if _scheduler_running:
        log.info("[Scheduler Bridge] Limpiando scheduler...")
        detener_scheduler()
        
        # Esperar a que el hilo termine (máximo 5 segundos)
        if _scheduler_thread and _scheduler_thread.is_alive():
            _scheduler_thread.join(timeout=5.0)
    
    _scheduler_instance = None
    _scheduler_thread = None
    _scheduler_running = False
    
    log.info("[Scheduler Bridge] Limpieza completada")


# ---------------------------------------------------------------------------
# MAIN DE PRUEBA
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Prueba básica del scheduler bridge
    print("=== Prueba del Scheduler Bridge ===\n")
    
    inicializar()
    
    print("1. Iniciando scheduler con configuración de prueba...")
    exito = iniciar_scheduler(
        cuentas_por_ciclo=5,
        pausa_min_minutos=1.0,  # 1 minuto para prueba
        pausa_max_minutos=2.0,
        max_ciclos=2,
        reiniciar_fallidas=True
    )
    
    if exito:
        print("✓ Scheduler iniciado\n")
        
        # Esperar un poco y mostrar estado
        import time
        time.sleep(3)
        
        print("2. Estado actual:")
        estado = obtener_estado_scheduler()
        for key, value in estado.items():
            print(f"   {key}: {value}")
        
        print("\n3. Deteniendo scheduler...")
        detener_scheduler()
        time.sleep(2)
        
        print("✓ Scheduler detenido")
    else:
        print("✗ No se pudo iniciar el scheduler")
    
    limpiar()
    print("\n=== Prueba finalizada ===")
