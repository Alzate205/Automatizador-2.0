# Diseño — Código 2FA manual (cuentas sin ClaveCorreo)

**Fecha:** 2026-07-06
**Estado:** Aprobado.

## 1. Objetivo

Permitir ingresar el código 2FA/verificación **a mano desde el panel** cuando una
cuenta no tiene `ClaveCorreo` (contraseña de aplicación para leer el código por
IMAP), activándolo con un **interruptor previo**. Las cuentas con `ClaveCorreo`
siguen leyendo el código automáticamente por correo, sin cambios.

## 2. Comportamiento

- Interruptor nuevo en el panel Control: **"Código de correo manual"**, guardado en
  `config_run.json` como `codigo_manual` (bool). Apagado por defecto → sin cambios.
- Selección del proveedor de código en `main.py` (`procesar_fila`):
  1. cuenta con `Correo` + `ClaveCorreo` → proveedor IMAP (como hoy);
  2. sin `ClaveCorreo` y `codigo_manual` encendido → **proveedor manual** (nuevo);
  3. ninguno → `None` (como hoy).
- Flujo manual (reusa el patrón del CAPTCHA `_confirmar_waiter`):
  1. el bot se pausa en un estado nuevo `esperando_codigo` y publica un mensaje con
     la cuenta;
  2. el panel muestra una casilla + botón "Enviar código" cuando ve ese estado;
  3. el usuario lee el código en su correo, lo escribe y lo envía;
  4. el bot recibe el código, lo **teclea y confirma solo** en Betplay (reusa la
     lógica de envío existente) y continúa;
  5. timeout largo igual que el CAPTCHA (`TIMEOUT_CAPTCHA_SEG`): si no llega el
     código, sigue de largo sin fallar.

## 3. Piezas

| Archivo | Cambio |
|---|---|
| `control.py` | Canal de archivo `codigo_2fa.txt`: `guardar_codigo`, `leer_codigo`, `hay_codigo`, `limpiar_codigo`; limpiarlo en `reset_control`. |
| `main.py` | Leer `codigo_manual` de la config (global); `_codigo_manual_waiter(etiqueta)` (espejo de `_confirmar_waiter`, devuelve el código o `None`); enchufarlo como `code_provider`. |
| `webapp/servidor.py` | `POST /api/codigo` (body `{codigo}`) → `control.guardar_codigo`. |
| `webapp/static/*` | Toggle en el sidebar; casilla de código que aparece en estado `esperando_codigo`. |

## 4. Canal de archivo

`codigo_2fa.txt` (en la raíz del proyecto, junto a las otras señales de `control.py`).
Existencia = hay un código pendiente; su contenido = el código. El proveedor manual
lo sondea, lo lee y lo borra tras usarlo. `reset_control()` lo limpia al iniciar.

## 5. Fuera de alcance (YAGNI)

- Panel Streamlit (legado): no se toca.
- Modos "manual para todas" o "manual como respaldo": no se implementan.
- No se persiste el código en ningún lado (se usa y se borra).

## 6. Pruebas

- `control.py`: round-trip del canal de código (guardar/leer/hay/limpiar) con
  archivos temporales; `reset_control` lo limpia.
- `webapp/servidor.py`: `POST /api/codigo` escribe `codigo_2fa.txt` (TestClient).
- `main.py`: no se automatiza (motor con navegador); verificación manual del flujo.
