# Diseño — Robustez del flujo de registro

**Fecha:** 2026-07-06
**Estado:** Aprobado e implementado.

## Objetivo

Cuatro mejoras al registro de Betplay para que falle de forma clara y auditable.

## Cambios

1. **Segundo nombre/apellido "cuando sea necesario"** (`procesador_web.py`).
   `_partir_dos(principal, secundario)`: respeta `SegundoNombre`/`SegundoApellido`
   si vienen; si no, y `PrimerNombre`/`PrimerApellido` trae dos palabras, toma la
   última como segundo ("Perez Gomez" → `lastName`=Perez, `lastName2`=Gomez).

2. **Espera activa del resultado tras "Completar Registro"** (`procesador_web.py`).
   `_esperar_resultado_registro(page)` corre en paralelo tres esperas y devuelve la
   primera: texto de error, campo de código de verificación, o texto de éxito
   ("Registro exitoso", "Verifica tu correo", …). Si ninguna aparece dentro de
   `TIMEOUT_RESULTADO_REGISTRO_MS` (20 s) → una última lectura del texto y, si nada,
   se marca **`registro_rechazado`** (antes quedaba `registro_incierto`).

3. **Pantallazos en fallo** (`procesador_web.py`).
   `_captura_fallo(page, etiqueta, motivo)` guarda `capturas/registro_FALLO_<cuenta>_<ts>.png`
   en cada salida de fallo (rechazado, timeout, excepción). Defensivo: nunca lanza.
   `capturas/` está en `.gitignore`.

4. **Campos obligatorios de registro**.
   - `preflight.REQUERIDOS_REGISTRO` y `procesador_web._validar_datos_registro`
     ampliados a: **Cedula, PrimerNombre, PrimerApellido, Correo, Telefono, Password**.
   - `main.py` (`procesar_fila`): guarda temprana — una fila de registro sin esos
     campos se descarta ANTES de rotar IP / abrir Chrome y se registra como
     `registro_rechazado` (no gasta un intento).

## Decisiones

- El fallo por falta de confirmación reusa el estado existente `registro_rechazado`
  (cuenta en "Rechazados" del panel; no rompe métricas).

## Pruebas

- `tests/test_registro.py`: `_partir_dos` (varios casos), `_validar_datos_registro`
  (incluye Telefono), `preflight.validar_datos` con la lista ampliada.
- Simulación con `page` falso (fuera de la suite): las 4 ramas de
  `_esperar_resultado_registro` (ok/error/codigo/timeout) y la captura.
- Simulación de la guarda temprana de `main.py` con una fila sin Telefono.
- No se automatiza el navegador real.
