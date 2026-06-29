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

- [ ] Ajustar `INDICADORES_REGISTRO_OK/ERROR` con los textos/URLs reales que muestre
      Betplay al completar/rechazar un registro (hoy son heurísticas genéricas).
- [ ] Validar los selectores reales del formulario de registro contra el sitio en vivo.

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
