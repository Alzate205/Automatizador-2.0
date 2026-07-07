# Automatizador Betplay 2.0

Bot de creación masiva y verificación de cuentas (Betplay) con panel de control
en Streamlit, comportamiento humano sobre Chrome (CDP), proxies rotativos,
validación post-registro y notificación por email.

> **Estado:** Fase 1 completa. Ver [FASE.md](FASE.md) para el checklist y la hoja
> de ruta de la Fase 2.

---

## ¿Qué hace?

- **Crear cuentas** masivamente (modo `registro`) rellenando el formulario de
  Betplay con comportamiento humano y pausa manual para el reCAPTCHA.
- **Verificar cuentas** existentes (modo `login`): saldo, estado de verificación,
  límites, bonos y preparación de apuestas (bono/saldo).
- **Validación post-registro** heurística: marca cada registro como
  `registro_ok`, `registro_incierto`, `registro_rechazado` o `error_registro`.
- **Panel web** (Streamlit) para editar cuentas, lanzar/parar el bot, ver el
  progreso en vivo y auditar resultados con métricas y gráficos.
- **Proxies rotativos** desde `proxies.txt` para las cuentas sin proxy propio.
- **Reporte final** en el log + **resumen por email** opcional.

---

## Instalación

```bash
pip install -r requirements.txt
playwright install chromium
```

Dependencias clave: `streamlit`, `pandas`, `openpyxl`, `altair`, `playwright`,
`playwright-stealth`, `colorama`, `python-dotenv`.

---

## Uso

### 1. Panel web (nuevo, recomendado)

```bash
iniciar.bat        # o: python -m uvicorn webapp.servidor:app --port 8000
```

Abre `http://localhost:8000`. Tres secciones en una sola página:

- **Control** — iniciar/detener/continuar el bot, consola en vivo con colores y
  barra de progreso.
- **Cuentas** — tabla **editable en pantalla** de `cuentas.xlsx` (agregar/borrar
  filas, selector de `Modo`, ocultar/mostrar contraseñas). Además **importar** y
  **descargar** Excel cuando lo prefieras (las dos maneras).
- **Estadísticas** — métricas, gráficas (SVG propio, sin internet) y exportación.

Reemplaza al panel Streamlit. No requiere internet en runtime (sin CDNs).

### 2. Panel Streamlit (legado)

```bash
streamlit run dashboard.py
```

Pestañas:

- **Cuentas** — editar la lista (`cuentas.xlsx`); selector de `Modo` por fila.
- **Registrar** — alta de una cuenta nueva con formulario.
- **Crear Masivas** — generar plantilla de N cuentas o subir un Excel con datos.
- **Control** — iniciar/detener el bot, resolver CAPTCHA/apuesta, ver progreso e
  indicador de proxies disponibles.
- **Resultados** — métricas, resumen de registros (OK/rechazados/inciertos),
  gráficos y exportación.

El panel lanza `main.py` como subproceso y se comunican por archivos (ver
`control.py`).

### 2. Por línea de comandos

```bash
python main.py
```

Lee la configuración que dejó el dashboard (`config_run.json`) o usa los valores
por defecto.

---

## Formato del Excel (`cuentas.xlsx`)

Identificación mínima: **`Correo` o `Usuario`**. Columnas usadas:

| Columna | Uso |
|---|---|
| `Usuario` / `Correo` | identificador de login / buzón 2FA |
| `Password` | contraseña de Betplay |
| `ClaveCorreo` | app password del buzón (para leer el código 2FA por IMAP) |
| `Modo` | `login` (verificar) o `registro` (crear) |
| `Puerto` | puerto CDP del navegador (si no usas el gestor de perfiles) |
| `Proxy` | proxy de la fila (`host:puerto`); vacío/`none` = sin proxy |
| `Cedula`, `PrimerNombre`, `PrimerApellido`, `Telefono`, `LugarExpedicion` | datos de registro |
| `ExpedicionDD/MM/YYYY`, `NacimientoDD/MM/YYYY` | fechas de registro |

Genera un ejemplo con `python crear_ejemplo.py`. La lectura es **tolerante**: las
columnas ausentes se crean vacías (`auditor.leer_cuentas`).

---

## Proxies (`proxies.txt`)

Un proxy por línea; líneas vacías y `#` se ignoran. Al iniciar, `main.py` asigna
los proxies **rotativamente** a las filas sin proxy propio. Ver
[.gitignore](.gitignore) — `proxies.txt` no se versiona (puede tener
credenciales). Plantilla incluida.

```
http://usuario:clave@ip:puerto
http://ip:puerto
socks5://ip:puerto
```

---

## Notificación por email (opcional)

Copia `.env.example` a `.env` y rellena las variables SMTP. Si no lo configuras,
el bot omite el email sin fallar.

```
EMAIL_FROM=tuemail@gmail.com
EMAIL_TO=tuemail@gmail.com
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=tuemail@gmail.com
SMTP_PASS=tu_app_password    # App Password de Gmail, no la clave normal
```

---

## Mapa de archivos

**Núcleo**

- `main.py` — orquestador: lee cuentas, asigna proxies, procesa cada fila, guarda
  resultados, reporte final y email.
- `procesador_web.py` — `process_user` / `registrar_cuenta`: login, 2FA, saldo,
  límites, bonos, apuestas, registro + validación post-registro (con stealth).
- `dashboard.py` — panel Streamlit (5 pestañas).
- `auditor.py` — logger coloreado, historial CSV, lectura tolerante del Excel y
  reportes (`generar_reporte_final`, `generar_reporte_resumen`).
- `control.py` — comunicación dashboard↔bot por archivos (estado, config, señales).
- `gestor_perfiles.py` — lanza perfiles Chrome aislados (CDP) + carga de proxies.

**Utilidades**

- `extraccion.py` — parseo del saldo (formato es-CO → float).
- `restricciones.py` — detección de límites sin tildes/mayúsculas.
- `pausa.py` — esperas con jitter (anti-rigidez).
- `lector_correos.py` / `correo_reciente.py` — extracción del código 2FA por IMAP.
- `conexion_cdp.py` / `escuchar.py` — conexión a un navegador externo vía CDP.
- `alertas_consola.py` / `colores.py` — salida coloreada.
- `crear_ejemplo.py` — genera un `cuentas.xlsx` de ejemplo.
- `leer_fila.py`, `navegacion.py`, `probar_local.py` — utilidades/pruebas.

**Generados (no se versionan)**

`cuentas_actualizadas.xlsx`, `historial_auditoria.csv`, `estado_bot.json`,
`config_run.json`, `progreso.txt`, `*.flag`, `bot.log`, `bot_consola.log`,
`perfiles/`.

---

## Notas

- El reCAPTCHA del registro se resuelve **manualmente**: el bot pausa y espera la
  señal "Continuar" del dashboard.
- Las apuestas se dejan **preparadas** y pausan para confirmación manual; el bot
  no confirma apuestas por su cuenta.
- Uso responsable: respeta los términos de servicio de las plataformas y la
  legislación aplicable.
