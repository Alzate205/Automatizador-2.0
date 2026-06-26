"""
probar_local.py
===============

Verifica que las TRES piezas locales de auditor.py funcionen de forma
impecable, sin abrir ningún navegador:

    1. Lectura del Excel (cuentas.xlsx)         -> leer_cuentas()
    2. Interfaz visual coloreada en consola      -> logger + colorama
    3. Actualización del historial en CSV        -> registrar_historial()

No realiza ningún login ni navegación: simula el resultado de cada fila
para comprobar que el flujo de datos local es correcto.

Uso:
    python crear_ejemplo.py     # si aún no tienes cuentas.xlsx
    python probar_local.py
"""

import os
from random import random

from auditor import (
    ARCHIVO_HISTORIAL,
    inicializar_historial,
    leer_cuentas,
    log,
    registrar_historial,
)


def main() -> None:
    log.info("=== PRUEBA LOCAL (sin navegador) ===")

    # Empieza con un historial limpio para que la prueba sea reproducible.
    if os.path.exists(ARCHIVO_HISTORIAL):
        os.remove(ARCHIVO_HISTORIAL)
    inicializar_historial()

    # 1) Lectura del Excel.
    try:
        cuentas = leer_cuentas()
        log.exito(f"Excel leído correctamente: {len(cuentas)} fila(s)")
        log.info(f"Columnas detectadas: {list(cuentas.columns)}")
    except Exception as exc:  # noqa: BLE001
        log.error(f"No se pudo leer el Excel: {exc}")
        return

    # 2) Recorrido + 3) historial. Simula un resultado por fila para
    #    ejercitar tanto el camino de ÉXITO (verde) como el de ERROR (rojo).
    for indice, fila in cuentas.iterrows():
        usuario = str(fila.get("Usuario", f"fila_{indice}"))
        log.info(f"Procesando (simulado) #{indice + 1}: {usuario}")

        # Regla de demostración: las cuentas "Verificada == si" se marcan
        # como éxito; el resto como error simulado. Es solo para ver ambos
        # colores y ambos estados en el CSV.
        verificada = str(fila.get("Verificada", "no")).strip().lower()
        if verificada == "si":
            log.exito(f"{usuario}: verificación OK (simulada)")
            registrar_historial(usuario, "EXITO", "Cuenta verificada (simulado)")
        else:
            log.error(f"{usuario}: sin verificar (simulado)")
            registrar_historial(usuario, "ERROR", "Cuenta no verificada (simulado)")
        
    # En probar_local.py - dentro del bucle
    for idx, row in df.iterrows():
    # Simulación de resultado (para pruebas locales)
        resultado_simulado = {
            "saldo": random.uniform(50000, 2500000),
            "verificada": "si" if idx % 3 != 0 else "no",   # Alterna resultados
            "limitada": idx % 5 == 0,
            "estado": "exitosa" if idx % 4 != 0 else "revisar"
        }
    
    # Registrar en auditoría
        registrar_historial(
            usuario=row.get("Usuario") or row.get("Correo"),
            estado=resultado_simulado["estado"],
            saldo=resultado_simulado["saldo"],
            verificada=resultado_simulado["verificada"],
            limitada=resultado_simulado["limitada"],
            notas=f"Prueba local - Perfil {row.get('Puerto', 'N/A')}"
        )
    
    print(f"{row.get('Usuario')} → Saldo: ${resultado_simulado['saldo']:,.0f} | Verificada: {resultado_simulado['verificada']} | Limitada: {resultado_simulado['limitada']}")

    log.exito("=== Prueba finalizada ===")

    # Muestra el contenido final del CSV para confirmar que se escribió bien.
    log.info(f"Contenido de {ARCHIVO_HISTORIAL}:")
    with open(ARCHIVO_HISTORIAL, encoding="utf-8") as f:
        print(f.read())


if __name__ == "__main__":
    main()
