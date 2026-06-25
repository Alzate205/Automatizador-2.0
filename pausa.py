"""
pausa.py
========

Helper asíncrono para pausas con jitter: añade un margen aleatorio de
milisegundos al tiempo base para que las esperas no sean perfectamente
rígidas (útil para simular comportamiento humano en automatización).

Uso:
    from pausa import pausa_con_jitter, pausa_humana

    await pausa_con_jitter(2)            # ~2 s + 0..500 ms de jitter (micro-pausa)
    await pausa_con_jitter(1, 800)       # ~1 s + 0..800 ms de jitter
    await pausa_humana(3, 10)            # entre 3 y 10 MINUTOS (anti-detección)
"""

import asyncio
import random


async def pausa_con_jitter(segundos_base: float, jitter_ms: int = 500) -> float:
    """
    Espera 'segundos_base' más un margen aleatorio de 0..jitter_ms milisegundos.

    Devuelve el tiempo total dormido (en segundos), por si se quiere registrar.
    """
    espera = segundos_base + random.uniform(0, jitter_ms) / 1000
    await asyncio.sleep(espera)
    return espera


async def pausa_humana(min_minutos: float = 2.0, max_minutos: float = 7.0) -> float:
    """
    Pausa larga y aleatoria expresada en MINUTOS, pensada como espera
    anti-detección entre cuentas. Devuelve los segundos dormidos.
    """
    segundos = random.uniform(min_minutos, max_minutos) * 60
    await asyncio.sleep(segundos)
    return segundos
