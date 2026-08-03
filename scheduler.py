"""
scheduler.py
============

Programador de tareas para modo loop infinito del bot Betplay.

Características:
- Ejecución en ciclos configurables
- Pausas entre ciclos (ej: 6 horas)
- Máximo de ciclos configurable
- Reporte automático al finalizar cada ciclo
- Reinicio automático con cuentas nuevas o recicladas
- Control de inicio/detención desde dashboard
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, asdict
from enum import Enum

from auditor import log


# ---------------------------------------------------------------------------
# ESTADOS DEL SCHEDULER
# ---------------------------------------------------------------------------

class SchedulerEstado(Enum):
    """Estados posibles del scheduler."""
    DETENIDO = "detenido"
    CORRIENDO = "corriendo"
    PAUSADO = "pausado"
    EN_PAUSA_ENTRE_CICLOS = "en_pausa_entre_ciclos"
    FINALIZADO = "finalizado"
    ERROR = "error"


@dataclass
class ConfigCiclo:
    """Configuración de un ciclo de ejecución."""
    cuentas_por_ciclo: int = 10
    pausa_min_minutos: float = 360.0  # 6 horas
    pausa_max_minutos: float = 480.0  # 8 horas
    max_ciclos: int = 0  # 0 = infinito
    reiniciar_fallidas: bool = True
    solo_exitosas_previas: bool = False
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "ConfigCiclo":
        return cls(**data)


@dataclass
class ReporteCiclo:
    """Reporte generado al finalizar cada ciclo."""
    numero_ciclo: int
    timestamp_inicio: str
    timestamp_fin: str
    duracion_segundos: float
    cuentas_procesadas: int
    cuentas_exitosas: int
    cuentas_fallidas: int
    tasa_exito_porcentaje: float
    bonos_activados: int
    total_apostado: float
    errores_comunes: Dict[str, int]
    
    def to_dict(self) -> Dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# ARCHIVOS DE ESTADO
# ---------------------------------------------------------------------------

ARCHIVO_CONFIG = "scheduler_config.json"
ARCHIVO_ESTADO = "scheduler_estado.json"
ARCHIVO_REPORTES = "scheduler_reportes.json"


# ---------------------------------------------------------------------------
# SCHEDULER PRINCIPAL
# ---------------------------------------------------------------------------

class Scheduler:
    """
    Programador de ciclos infinitos para el bot Betplay.
    
    Uso típico:
        scheduler = Scheduler()
        scheduler.configurar(cuentas_por_ciclo=10, pausa_min=360)
        
        # Iniciar loop (desde main.py o dashboard)
        await scheduler.iniciar_loop(procesar_lote_func)
        
        # Detener desde dashboard
        scheduler.detener()
    """
    
    def __init__(self):
        self.estado = SchedulerEstado.DETENIDO
        self.config = ConfigCiclo()
        self.ciclo_actual = 0
        self.reportes: List[ReporteCiclo] = []
        self.tarea_async: Optional[asyncio.Task] = None
        self.callback_procesar_lote: Optional[Callable] = None
        
        # Cargar configuración previa si existe
        self.cargar_configuracion()
        self.cargar_estado()
    
    def configurar(
        self,
        cuentas_por_ciclo: int = 10,
        pausa_min_minutos: float = 360.0,
        pausa_max_minutos: float = 480.0,
        max_ciclos: int = 0,
        reiniciar_fallidas: bool = True,
        solo_exitosas_previas: bool = False
    ):
        """Configura los parámetros del scheduler."""
        self.config = ConfigCiclo(
            cuentas_por_ciclo=cuentas_por_ciclo,
            pausa_min_minutos=pausa_min_minutos,
            pausa_max_minutos=pausa_max_minutos,
            max_ciclos=max_ciclos,
            reiniciar_fallidas=reiniciar_fallidas,
            solo_exitosas_previas=solo_exitosas_previas,
        )
        self.guardar_configuracion()
        log.info(f"[Scheduler] Configurado: {cuentas_por_ciclo} cuentas/ciclo, "
                f"pausa {pausa_min_minutos}-{pausa_max_minutos} min")
    
    async def iniciar_loop(self, callback_procesar_lote: Callable) -> None:
        """
        Inicia el loop infinito de procesamiento.
        
        callback_procesar_lote: Función asíncrona que procesa un lote de cuentas.
                               Debe recibir (config_ciclo) y devolver (reporte_dict).
        """
        if self.estado == SchedulerEstado.CORRIENDO:
            log.warning("[Scheduler] Ya está corriendo")
            return
        
        self.callback_procesar_lote = callback_procesar_lote
        self.estado = SchedulerEstado.CORRIENDO
        self.guardar_estado()
        
        log.exito("[Scheduler] === INICIANDO LOOP INFINITO ===")
        log.info(f"[Scheduler] Configuración: {self.config.cuentas_por_ciclo} cuentas por ciclo")
        
        try:
            while self.estado == SchedulerEstado.CORRIENDO:
                # Verificar límite de ciclos
                if self.config.max_ciclos > 0 and self.ciclo_actual >= self.config.max_ciclos:
                    log.info(f"[Scheduler] Alcanzados {self.config.max_ciclos} ciclos. Finalizando.")
                    self.estado = SchedulerEstado.FINALIZADO
                    break
                
                # Ejecutar ciclo
                await self._ejecutar_ciclo()
                
                # Si fue detenido durante el ciclo, salir
                if self.estado != SchedulerEstado.CORRIENDO:
                    break
                
                # Pausa entre ciclos
                if self.estado == SchedulerEstado.CORRIENDO:
                    await self._pausa_entre_ciclos()
        
        except Exception as e:
            log.error(f"[Scheduler] Error crítico en loop: {e}")
            self.estado = SchedulerEstado.ERROR
            self.guardar_estado()
        
        finally:
            log.info("[Scheduler] Loop finalizado")
            self.guardar_estado()
    
    async def _ejecutar_ciclo(self) -> None:
        """Ejecuta un ciclo completo de procesamiento."""
        self.ciclo_actual += 1
        timestamp_inicio = datetime.now()
        
        log.info(f"\n{'='*60}")
        log.exito(f"[Scheduler] === CICLO {self.ciclo_actual} INICIANDO ===")
        log.info(f"{'='*60}\n")
        
        self.estado = SchedulerEstado.CORRIENDO
        self.guardar_estado()
        
        try:
            # Llamar al callback de procesamiento
            if not self.callback_procesar_lote:
                raise ValueError("No hay callback de procesamiento registrado")
            
            reporte_dict = await self.callback_procesar_lote(self.config)
            
            # Crear reporte del ciclo
            reporte = ReporteCiclo(
                numero_ciclo=self.ciclo_actual,
                timestamp_inicio=timestamp_inicio.isoformat(),
                timestamp_fin=datetime.now().isoformat(),
                duracion_segundos=(datetime.now() - timestamp_inicio).total_seconds(),
                cuentas_procesadas=reporte_dict.get("cuentas_procesadas", 0),
                cuentas_exitosas=reporte_dict.get("cuentas_exitosas", 0),
                cuentas_fallidas=reporte_dict.get("cuentas_fallidas", 0),
                tasa_exito_porcentaje=reporte_dict.get("tasa_exito", 0.0),
                bonos_activados=reporte_dict.get("bonos_activados", 0),
                total_apostado=reporte_dict.get("total_apostado", 0.0),
                errores_comunes=reporte_dict.get("errores_comunes", {}),
            )
            
            self.reportes.append(reporte)
            self.guardar_reportes()
            
            # Imprimir resumen del ciclo
            log.info("\n" + "="*60)
            log.exito(f"[Scheduler] === CICLO {self.ciclo_actual} COMPLETADO ===")
            log.info(f"Cuentas procesadas: {reporte.cuentas_procesadas}")
            log.info(f"Exitosas: {reporte.cuentas_exitosas} ({reporte.tasa_exito_porcentaje:.1f}%)")
            log.info(f"Fallidas: {reporte.cuentas_fallidas}")
            log.info(f"Bonos activados: {reporte.bonos_activados}")
            log.info(f"Total apostado: ${reporte.total_apostado:,.2f}")
            log.info(f"Duración: {reporte.duracion_segundos/60:.1f} minutos")
            log.info("="*60 + "\n")
        
        except Exception as e:
            log.error(f"[Scheduler] Error en ciclo {self.ciclo_actual}: {e}")
            raise
    
    async def _pausa_entre_ciclos(self) -> None:
        """Espera entre ciclos con tiempo aleatorio en el rango configurado."""
        import random
        
        pausa_minutos = random.uniform(
            self.config.pausa_min_minutos,
            self.config.pausa_max_minutos
        )
        pausa_segundos = pausa_minutos * 60
        
        self.estado = SchedulerEstado.EN_PAUSA_ENTRE_CICLOS
        self.guardar_estado()
        
        log.warning(
            f"\n[Scheduler] === PAUSA ENTRE CICLOS ===\n"
            f"Duración: {pausa_minutos:.1f} minutos ({pausa_segundos:.0f} segundos)\n"
            f"Próximo ciclo: {self.ciclo_actual + 1}\n"
            f"{'='*60}\n"
        )
        
        # Esperar con reportes periódicos
        await self._espera_con_reportes(pausa_segundos)
    
    async def _espera_con_reportes(self, segundos: float) -> None:
        """Espera mostrando reportes de progreso cada 10 minutos."""
        intervalo_reporte = 600.0  # 10 minutos
        elapsed = 0.0
        
        while elapsed < segundos:
            restante = segundos - elapsed
            restante_minutos = restante / 60
            
            log.info(
                f"[Scheduler] Pausa entre ciclos... "
                f"Faltan {restante_minutos:.1f} minutos"
            )
            
            await asyncio.sleep(min(intervalo_reporte, segundos - elapsed))
            elapsed += intervalo_reporte
        
        log.info("[Scheduler] Pausa completada. Reanudando...\n")
    
    def detener(self) -> None:
        """Detiene el scheduler (se efectuará al finalizar la operación actual)."""
        log.warning("[Scheduler] Solicitando detención...")
        if self.estado in [SchedulerEstado.CORRIENDO, SchedulerEstado.EN_PAUSA_ENTRE_CICLOS]:
            self.estado = SchedulerEstado.DETENIDO
            self.guardar_estado()
    
    def pausar(self) -> None:
        """Pausa el scheduler después del ciclo actual."""
        log.warning("[Scheduler] Solicitando pausa...")
        if self.estado == SchedulerEstado.CORRIENDO:
            self.estado = SchedulerEstado.PAUSADO
            self.guardar_estado()
    
    def reanudar(self) -> None:
        """Reanuda el scheduler desde pausa."""
        if self.estado == SchedulerEstado.PAUSADO:
            log.info("[Scheduler] Reanudando...")
            self.estado = SchedulerEstado.CORRIENDO
            self.guardar_estado()
    
    def obtener_estado(self) -> Dict[str, Any]:
        """Obtiene el estado actual del scheduler."""
        return {
            "estado": self.estado.value,
            "ciclo_actual": self.ciclo_actual,
            "config": self.config.to_dict(),
            "total_ciclos_completados": len(self.reportes),
            "ultimo_reporte": self.reportes[-1].to_dict() if self.reportes else None,
        }
    
    def guardar_configuracion(self) -> None:
        """Guarda la configuración en archivo."""
        try:
            with open(ARCHIVO_CONFIG, "w", encoding="utf-8") as f:
                json.dump(self.config.to_dict(), f, indent=2)
        except Exception as e:
            log.error(f"[Scheduler] Error guardando config: {e}")
    
    def cargar_configuracion(self) -> None:
        """Carga la configuración desde archivo."""
        if not os.path.exists(ARCHIVO_CONFIG):
            return
        
        try:
            with open(ARCHIVO_CONFIG, "r", encoding="utf-8") as f:
                datos = json.load(f)
            self.config = ConfigCiclo.from_dict(datos)
            log.info("[Scheduler] Configuración cargada desde archivo")
        except Exception as e:
            log.error(f"[Scheduler] Error cargando config: {e}")
    
    def guardar_estado(self) -> None:
        """Guarda el estado actual en archivo."""
        try:
            estado_data = {
                "estado": self.estado.value,
                "ciclo_actual": self.ciclo_actual,
                "timestamp": datetime.now().isoformat(),
            }
            with open(ARCHIVO_ESTADO, "w", encoding="utf-8") as f:
                json.dump(estado_data, f, indent=2)
        except Exception as e:
            log.error(f"[Scheduler] Error guardando estado: {e}")
    
    def cargar_estado(self) -> None:
        """Carga el estado desde archivo."""
        if not os.path.exists(ARCHIVO_ESTADO):
            return
        
        try:
            with open(ARCHIVO_ESTADO, "r", encoding="utf-8") as f:
                datos = json.load(f)
            
            estado_str = datos.get("estado", "detenido")
            try:
                self.estado = SchedulerEstado(estado_str)
            except ValueError:
                self.estado = SchedulerEstado.DETENIDO
            
            self.ciclo_actual = datos.get("ciclo_actual", 0)
            log.info(f"[Scheduler] Estado cargado: {self.estado.value}, ciclo {self.ciclo_actual}")
        except Exception as e:
            log.error(f"[Scheduler] Error cargando estado: {e}")
    
    def guardar_reportes(self) -> None:
        """Guarda todos los reportes en archivo."""
        try:
            reportes_data = [r.to_dict() for r in self.reportes]
            with open(ARCHIVO_REPORTES, "w", encoding="utf-8") as f:
                json.dump(reportes_data, f, indent=2)
        except Exception as e:
            log.error(f"[Scheduler] Error guardando reportes: {e}")
    
    def cargar_reportes(self) -> None:
        """Carga los reportes desde archivo."""
        if not os.path.exists(ARCHIVO_REPORTES):
            return
        
        try:
            with open(ARCHIVO_REPORTES, "r", encoding="utf-8") as f:
                datos = json.load(f)
            
            self.reportes = [
                ReporteCiclo(**r) if isinstance(r, dict) else r
                for r in datos
            ]
            log.info(f"[Scheduler] Cargados {len(self.reportes)} reportes")
        except Exception as e:
            log.error(f"[Scheduler] Error cargando reportes: {e}")
    
    def obtener_estadisticas_globales(self) -> Dict[str, Any]:
        """Calcula estadísticas acumuladas de todos los ciclos."""
        if not self.reportes:
            return {}
        
        total_cuentas = sum(r.cuentas_procesadas for r in self.reportes)
        total_exitosas = sum(r.cuentas_exitosas for r in self.reportes)
        total_fallidas = sum(r.cuentas_fallidas for r in self.reportes)
        total_bonos = sum(r.bonos_activados for r in self.reportes)
        total_apostado = sum(r.total_apostado for r in self.reportes)
        total_duracion = sum(r.duracion_segundos for r in self.reportes)
        
        tasa_exito_global = (total_exitosas / total_cuentas * 100) if total_cuentas > 0 else 0.0
        
        return {
            "ciclos_completados": len(self.reportes),
            "total_cuentas_procesadas": total_cuentas,
            "total_exitosas": total_exitosas,
            "total_fallidas": total_fallidas,
            "tasa_exito_global": round(tasa_exito_global, 2),
            "total_bonos_activados": total_bonos,
            "total_apostado": round(total_apostado, 2),
            "tiempo_total_horas": round(total_duracion / 3600, 2),
            "promedio_cuentas_por_ciclo": round(total_cuentas / len(self.reportes), 1),
        }


# ---------------------------------------------------------------------------
# INSTANCIA GLOBAL
# ---------------------------------------------------------------------------

_scheduler_instance: Optional[Scheduler] = None


def get_scheduler() -> Scheduler:
    """Obtiene la instancia global del scheduler."""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = Scheduler()
    return _scheduler_instance


def init_scheduler(**kwargs) -> Scheduler:
    """Inicializa el scheduler con configuración personalizada."""
    global _scheduler_instance
    _scheduler_instance = Scheduler()
    if kwargs:
        _scheduler_instance.configurar(**kwargs)
    return _scheduler_instance


# ---------------------------------------------------------------------------
# PRUEBA MANUAL
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio
    
    async def mock_procesar_lote(config):
        """Simula procesamiento de un lote."""
        log.info("[Mock] Procesando lote...")
        await asyncio.sleep(5)  # Simular trabajo
        
        return {
            "cuentas_procesadas": config.cuentas_por_ciclo,
            "cuentas_exitosas": int(config.cuentas_por_ciclo * 0.8),
            "cuentas_fallidas": int(config.cuentas_por_ciclo * 0.2),
            "tasa_exito": 80.0,
            "bonos_activados": 5,
            "total_apostado": 150000.0,
            "errores_comunes": {"timeout": 2},
        }
    
    async def main():
        scheduler = get_scheduler()
        scheduler.configurar(
            cuentas_por_ciclo=5,
            pausa_min_minutos=0.5,  # 30 segundos para prueba
            pausa_max_minutos=1.0,  # 1 minuto para prueba
            max_ciclos=3,
        )
        
        await scheduler.iniciar_loop(mock_procesar_lote)
        
        # Mostrar estadísticas
        stats = scheduler.obtener_estadisticas_globales()
        print("\n=== Estadísticas Globales ===")
        print(json.dumps(stats, indent=2))
    
    # Ejecutar prueba
    log.info("=== Prueba del Scheduler ===\n")
    asyncio.run(main())
