# Hoja de ruta — Automatizador Betplay 2.0

## Fase 1 — Completa ✅

Pipeline funcional de creación masiva + verificación, controlado desde el panel.

- [x] **Registro masivo** con comportamiento humano (`procesador_web.registrar_cuenta`).
- [x] **Stealth** de navegador (`playwright-stealth`) para reducir huella de automatización.
- [x] **Validación post-registro** heurística → `registro_ok` / `registro_incierto` /
      `registro_rechazado` / `error_registro` (indicadores en
      `INDICADORES_REGISTRO_OK/ERROR`).
- [x] **Proxies rotativos** desde `proxies.txt` (`gestor_perfiles.cargar_proxies_desde_archivo`,
      `main.cargar_y_asignar_proxies`); normalización `proxy_valido` (ignora `none`/vacío)
      y lectura robusta con BOM (`utf-8-sig`).
- [x] **Lectura tolerante del Excel** (`auditor.leer_cuentas`): columnas ausentes se
      crean vacías; exige `Correo` o `Usuario`.
- [x] **Panel Streamlit** con 5 pestañas (Cuentas, Registrar, Crear Masivas, Control,
      Resultados), incluyendo plantilla masiva y subida de Excel.
- [x] **Auditoría visual**: resumen de registros (OK/rechazados/inciertos) + gráficos.
- [x] **Reporte final** en log (`auditor.generar_reporte_final` / `imprimir_reporte_final`).
- [x] **Notificación por email** opcional vía SMTP + `.env` (`main.enviar_resumen_email`).
- [x] **Reanudación** entre corridas (`progreso.txt`) y guardado incremental del Excel.
- [x] **README** + este checklist.

### Pendientes menores de Fase 1 (afinar con datos reales)

- [x] Clasificación de registro anclada en señales reales de Betplay:
      - **Rechazo**: "El correo ya se encuentra en uso" (detección temprana en
        `_verificar_celular` + indicador en `INDICADORES_REGISTRO_ERROR`).
      - **Éxito**: llegar al paso de verificación de celular y validar el código
        (`registro_ok`). Si el correo estuviera en uso, nunca se llega a ese paso.
      - `INDICADORES_REGISTRO_OK` queda como respaldo para cuando no hay lectura de
        código (p. ej. sin `ClaveCorreo`).
- [x] Validar los selectores reales del formulario de registro contra el sitio en vivo.
      Se migró todo el formulario a los `formcontrolname` reales de Betplay (Angular):
      documentType, documentNumber, expedition/born Day/Month/Year, expeditionPlace,
      firstName(2), lastName(2), gender, mobilePhoneNumber, email, addressType,
      address1/2/3, cityAddress, password, cnfPassword, ludopath, pep, checkboxes y el
      botón `.betplaycaptcha` "Completar Registro". Las fechas, género, tipo de vía,
      ludopatía y PEP son `<select>` (van por value, no por tecleo).
- [x] Verificación de celular post-registro: campo `verificationCode`, código leído
      del correo (patrón 6 díg.) y enviado con `input[type=submit][value="Validar"]`.
- [x] Flujo de LOGIN y lectura con selectores reales:
      - Login por **cédula** (`input#userName`, `input#password`, `#btnLoginPrimary`);
        `main.py` usa `Cedula` como usuario (fallback Correo/Usuario).
      - Saldo **total** (`td.balance-td`) y **retirable** (`<td>` hermano) → columna
        `Saldo_Retirable`.
      - Límite diario real (`.limit-value`): limitada si el tope < $10.000.000
        (antes la lógica estaba invertida).
      - Verificada = **no limitada**.
      - Bonos por marcador negativo real ("No tienes bonos actualmente").
      - Navegación a Límites/Bonos por **clics** ("Mi cuenta" → opción) con respaldo URL.
- [x] Apuesta con selectores reales de **Kambi** (sportsbook de Betplay):
      Deportes (`a.section-title`) → cuota (`button[data-outcome-id]` + `.original-odds`,
      rango 3-6 para bono) → cupón (`mod-KambiBC-*`) → monto (`input.mod-KambiBC-js-stake-input`)
      → **pausa** para confirmación manual. Busca en iframes (Kambi corre embebido).

- [x] Filtro temporal de la apuesta: solo partidos de **hoy/mañana** en la franja
      **tarde-noche** (18:00–23:00, incluye ~8 p. m.). `_evento_en_ventana` parsea la
      fecha/hora (`EventDate__TimeWrapper`, día y hora en spans separados, formato
      "06:00 p. m.") y `_elegir_cuota` descarta los partidos fuera de la ventana.
      Configurable: `APUESTA_HORA_MIN/MAX`, `APUESTA_SOLO_HOY_MANANA`.

- [x] Red de seguridad previa al registro (`_validar_datos_registro`): omite la fila
      SIN tocar el formulario si faltan datos obligatorios (Cédula, nombres, correo,
      contraseña) o si la contraseña no cumple el patrón de Betplay. Evita gastar el
      intento + la verificación por SMS/correo en filas inservibles.
- [x] Login 2FA con el campo real `verificationCode` + botón "Validar".

### Por confirmar en pruebas en vivo

- [ ] Si el cupón/cuotas de Kambi están en iframe, `_frame_con` ya los busca; validar.
- [ ] Confirmar que los spans `EventDate__TimeWrapper` cuelgan de un ancestro
      `EventListItem` (así los ubica `_cuota_en_horario`); si no, ajustar el ancestro.
- [ ] Confirmar textos exactos de navegación "Mi cuenta"/"Deportes" (si el clic falla,
      cae a URL / se registra en el log).

---

## Fase 2 — Arquitectura (incremental, no big-bang)

Objetivo: ordenar la persistencia y, solo si hace falta, exponer una API.

### 2.1 — SQLite como capa de datos (detrás de las funciones actuales)

Reemplazar Excel/CSV por SQLite **sin** cambiar la UI de golpe:

- [ ] Esquema `cuentas`, `resultados`, `historial` en SQLite.
- [ ] Capa `db.py` con las mismas firmas que hoy (`leer_cuentas`, `registrar_historial`,
      guardar resultado) para minimizar cambios en `main.py`/`dashboard.py`.
- [ ] Import/export Excel para no perder el flujo actual de carga.
- [ ] Migrar el dashboard a leer de SQLite pestaña por pestaña.

### 2.2 — API (solo si surge la necesidad)

Disparadores reales para FastAPI: acceso remoto, varios usuarios, o integración
con terceros. Mientras sea local + un usuario, Streamlit basta.

- [ ] FastAPI con endpoints de corrida (iniciar/estado/detener) reemplazando la
      comunicación por archivos (`control.py`).
- [ ] (Opcional) cola de trabajos si se requiere concurrencia real.

---

## Convenciones

- Commits en ramas, no directo a `main`.
- Secretos fuera de git: `proxies.txt`, `.env` (ver `.gitignore`).
- Cambios defensivos: ningún paso crítico debe tumbar el lote completo.
