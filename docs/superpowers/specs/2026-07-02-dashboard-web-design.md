# Diseño — Dashboard web del Automatizador Betplay 2.0

**Fecha:** 2026-07-02
**Estado:** Aprobado (diseño), pendiente de plan de implementación.

## 1. Objetivo

Reemplazar el panel actual de **Streamlit + Altair** por una **interfaz web propia
(HTML/CSS/JS)** servida por un backend liviano, con mejor apariencia y facilidad de
uso, inspirada en una app de referencia (tema oscuro, barra lateral de acciones,
consola de log grande, barra de progreso). Las gráficas van en una sección
**separada**.

**Principio rector:** lo visual es solo mejora de UX. El **motor del bot no cambia**
(`main.py`, `procesador_web.py`, `rotador_ip.py`, `lector_correos.py`, etc.). La web
se comunica con el bot por los **mismos archivos** que ya usa `control.py`.

## 2. Restricción de arquitectura (importante)

La web corre en **la misma PC** que el bot, se abre en el navegador como
`localhost`. No es alojable en internet para uso remoto, porque el bot controla el
**Chrome local (CDP)** y el **teléfono por USB (ADB)** de esa máquina. Es una "app
web local": mini-servidor en la PC + HTML/CSS/JS en el navegador.

## 3. Arquitectura

Carpeta nueva `webapp/`:

```
webapp/
  servidor.py            # Backend FastAPI: sirve la página, API, lanza/detiene main.py
  datos.py               # Lógica de datos reutilizable (Excel, métricas, plantillas)
  static/
    index.html           # Una sola página con 3 secciones (Control, Cuentas, Estadísticas)
    style.css            # Tema oscuro propio
    app.js               # Polling de estado/log, acciones, render de tablas y gráficas
    vendor/chart.umd.js  # Chart.js incluido LOCALMENTE (sin CDN, sin internet)
iniciar.bat              # Doble clic: arranca el servidor y abre el navegador
```

- **`servidor.py`** (FastAPI + uvicorn, 1 worker): sirve `index.html` y los estáticos,
  expone la API (sección 5), y gestiona el subproceso `main.py` (arrancar/detener/
  ¿vivo?) con un handle global de módulo.
- **`datos.py`**: se extrae de `dashboard.py` toda la lógica de datos (leer/guardar
  `cuentas.xlsx`, métricas `porcentaje_verificadas`/`contar_limitadas`/`serie_registro`,
  `generar_plantilla_registro`, anexar una cuenta, tail de `bot.log`). Sin dependencias
  de Streamlit.
- **Comunicación con el bot:** exclusivamente vía `control.py` (`estado_bot.json`,
  `config_run.json`, `senal_detener.flag`, `senal_continuar.flag`, `bot.log`). Igual
  que hoy.

## 4. Flujo de datos

```
Navegador (HTML/CSS/JS)  ⇄  FastAPI (servidor.py)  ⇄  archivos  ⇄  main.py (subproceso)
```

- El frontend hace **polling cada ~1 s** de `GET /api/estado` (progreso, cuenta
  actual, fase, resumen) y de `GET /api/log?desde=N` (solo líneas nuevas).
- Al **Iniciar**, el front manda la config; el servidor la escribe en
  `config_run.json` y lanza `python main.py` como subproceso.
- **Detener/Continuar** crean las señales de `control.py`. **Forzar parada** mata el
  subproceso.

## 5. API (endpoints)

| Método | Ruta | Uso |
|---|---|---|
| GET | `/` | Sirve `index.html`. |
| GET | `/static/*` | Estáticos (CSS/JS/vendor). |
| GET | `/api/estado` | `control.leer_estado()` → JSON de estado en vivo. |
| GET | `/api/log?desde=N` | Devuelve `{ lineas: [...], total: M }` con las líneas de `bot.log` desde el índice N (log incremental). |
| POST | `/api/iniciar` | Body = config de corrida; escribe `config_run.json` y lanza `main.py`. |
| POST | `/api/detener` | `control.pedir_detener()`. |
| POST | `/api/continuar` | `control.pedir_continuar()`. |
| POST | `/api/forzar-parada` | Mata el subproceso del bot. |
| GET | `/api/cuentas` | `cuentas.xlsx` como JSON (filas + columnas). |
| POST | `/api/cuentas` | Guarda las filas editadas en `cuentas.xlsx`. |
| POST | `/api/cuentas/plantilla` | Body = `{n}`; genera plantilla de N cuentas registro. |
| POST | `/api/cuentas/importar` | Sube un Excel y **reemplaza** `cuentas.xlsx` (igual que el flujo actual del dashboard). |
| POST | `/api/cuentas/registrar` | Anexa una cuenta nueva (formulario). |
| GET | `/api/resultados` | Métricas + datos para gráficas + filas (de `cuentas_actualizadas.xlsx` e historial). |
| GET | `/api/resultados/exportar` | Descarga el Excel de resultados. |

**Config de corrida** (body de `/api/iniciar`) — misma forma que hoy consume
`main.py`: `filtro_modo`, `usar_gestor`, `pausa_min`, `pausa_max`, `tareas`
(lista), `apuesta` (`{modo, valor}`), `cuentas_seleccionadas`, `rotar_ip`,
`rotar_ip_solo_registro`.

## 6. Log en vivo (mecanismo)

- El servidor lee `bot.log` y devuelve sus líneas. El frontend guarda el índice de
  la última línea recibida y pide `GET /api/log?desde=N`; el servidor responde solo
  con `lineas[N:]` y el nuevo total. Así la consola crece sin recargar todo.
- **Coloreado en el frontend** por nivel/palabras: rojo para `[ERROR]`, amarillo para
  `[WARNING]`, verde para éxito (`[EXITO]`, `✓`, "exito", "OK"), gris claro para el
  resto. Auto-scroll al final salvo que el usuario suba manualmente.

## 7. Las 3 secciones (UI)

Una sola página con navegación entre 3 vistas (sin recargar):

1. **Control** (principal, estilo de la referencia):
   - Barra lateral: botones **Iniciar / Detener / Continuar** (el de Continuar se
     habilita solo en `esperando_captcha`/`esperando_apuesta`), **Forzar parada**, y
     los controles de corrida: filtro de modo, switches de **tareas** (verificar
     bonos, verificar límite, apostar bono, apostar saldo), monto de apuesta, pausas,
     usar gestor de perfiles, **rotar IP** (+ "solo tras registros"), y selección de
     cuentas.
   - Área principal: **consola de log** grande con auto-scroll y colores + **barra de
     progreso** (indice/total) + cabecera "X/Y — fase — cuenta actual".
2. **Cuentas**:
   - Tabla **editable** de `cuentas.xlsx` (login y registro), con guardar.
   - **Importar Excel**, **generar plantilla masiva** (N cuentas registro), y
     **registrar una cuenta** (formulario con los campos de registro).
   - Columnas sensibles (`Password`, `ClaveCorreo`) ocultables.
3. **Estadísticas** (separada):
   - Tarjetas de métricas: total procesadas, % verificadas, limitadas, registros
     OK/rechazados/inciertos.
   - Gráficas con **Chart.js local**: barras de estados de registro, dona
     verificadas vs no, limitadas, y distribución de saldos. Exportar Excel.

## 8. Diseño visual

- Tema **oscuro** propio (no plantilla): fondo grafito, acentos en azul/verde,
  tipografía sans clara para UI y monoespaciada para la consola.
- Sidebar fija (~240px) a la izquierda; contenido a la derecha; responsive dentro de
  la ventana (sin scroll horizontal del body).
- Estados de los botones reflejan el estado del bot (p. ej. Iniciar deshabilitado si
  ya corre; Continuar resaltado cuando el bot espera).

## 9. Dependencias

- Nuevas: `fastapi`, `uvicorn`, `python-multipart` (subida de Excel).
- Ya presentes: `pandas`, `openpyxl`.
- Se retiran del flujo: `streamlit`, `altair` (el archivo `dashboard.py` queda como
  legado; se puede borrar cuando la web esté validada).
- `Chart.js` se **incluye como archivo local** en `static/vendor/` (sin CDN).

## 10. Fuera de alcance (YAGNI)

- Acceso remoto / multiusuario / autenticación (es local, un usuario).
- Base de datos (sigue con Excel/CSV; SQLite es Fase 2 aparte).
- WebSockets/SSE (el polling cada ~1 s es suficiente y más robusto).
- Empaquetado a `.exe` (posible después con PyInstaller; no ahora).

## 11. Pruebas

- **`datos.py`**: pruebas unitarias de métricas, plantilla y lectura/guardado de
  Excel con archivos temporales (sin depender de la web).
- **API**: pruebas con el `TestClient` de FastAPI para cada endpoint (estado, log
  incremental, iniciar escribe config, señales, cuentas CRUD, resultados) usando
  archivos de prueba, **sin** lanzar el bot real ni el navegador.
- **Manual**: arrancar `iniciar.bat`, verificar las 3 secciones, una corrida de
  prueba con el log en vivo y el progreso.
- No se automatiza el navegador ni el bot real en las pruebas.

## 12. Migración / compatibilidad

- El backend reutiliza `control.py` sin cambios; `main.py` no cambia.
- La lógica de datos se **mueve** de `dashboard.py` a `webapp/datos.py`; `dashboard.py`
  se conserva hasta validar la web y luego se puede eliminar.
