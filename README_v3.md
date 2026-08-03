# BOT AUTOMATIZADOR DE APUESTAS BETPLAY v3.0

## DESCRIPCIÓN GENERAL

Bot consolidado que automatiza el trabajo de 2 personas (creador y verificador) 
con máxima fiabilidad y capacidad de repetición infinita.

### ¿Qué hace?

**Persona 1 (Creación de cuentas) → Automatizado:**
- Eliminar datos de navegación
- Cambiar MAC e IP
- Registrar usuario en Betplay
- Esperar código de confirmación (email/SMS)
- Completar registro
- Pasar credenciales al siguiente módulo

**Persona 2 (Verificación y aprovechamiento) → Automatizado:**
- Eliminar datos de navegación, cambiar IP y MAC
- Login con credenciales creadas
- Verificar si cuenta está limitada
- Revisar saldo y bonos disponibles
- Activar bono si existe
- Buscar evento importante (fútbol, NBA, béisbol)
- Realizar apuesta con el bono
- Registrar todos los datos recolectados

---

## NUEVAS CARACTERÍSTICAS v3.0

### 1. GESTIÓN DE IDENTIDAD ÚNICA (`identity_manager.py`)
- Rotación automática de MAC address (pool de MACs válidas)
- Rotación de IP/proxy residencial
- Verificación de cambios efectivos
- Limpieza completa de perfil de navegador
- Creación de perfil Chrome aislado con fingerprint único:
  - User-Agent aleatorio
  - Canvas fingerprint único
  - WebGL vendor/renderer aleatorios
  - Timezone coherente con IP
  - Language coherente con país
  - Screen resolution realista

### 2. MOTOR DE REINTENTOS (`retry_engine.py`)
- Backoff exponencial: 30s, 2min, 5min, 15min, 30min...
- Cambio completo de identidad en cada reintento
- Máximo de intentos configurable (default: 5)
- Registro detallado de motivos de fallo
- Reintento selectivo de cuentas fallidas
- Estadísticas de éxito por tipo de error

### 3. PROGRAMADOR DE CICLOS (`scheduler.py`)
- Modo loop infinito configurable
- Ejecución por lotes/ciclos
- Pausas entre ciclos (ej: 6-8 horas)
- Reporte automático al finalizar cada ciclo
- Reinicio automático con cuentas nuevas o recicladas
- Control total desde dashboard (iniciar/detener/pausar/reanudar)

---

## FLUJO POR CUENTA (PIPELINE COMPLETO)

```
[1] PREPARACIÓN DE IDENTIDAD ÚNICA
    ├─ Cambiar MAC address (rotación entre pool de MACs válidas)
    ├─ Cambiar IP (rotar proxy residencial del pool)
    ├─ Verificar que IP y MAC efectivamente cambiaron
    ├─ Limpiar perfil de navegador (eliminar user-data-dir completo)
    └─ Crear nuevo perfil Chrome aislado con fingerprint único

[2] CREACIÓN DE CUENTA
    ├─ Navegar a betplay.com.co/registro
    ├─ Llenar formulario con comportamiento humano
    ├─ Resolver CAPTCHA (manual vía dashboard)
    ├─ Enviar formulario
    ├─ Esperar código de confirmación:
    │   ├─ Opción A: Leer correo IMAP (ya implementado)
    │   └─ Opción B: Leer SMS (Twilio API / 5sim.net)
    ├─ Ingresar código y completar registro
    ├─ Validar que la cuenta quedó correctamente creada
    │   ├─ Si OK → continuar al paso 3
    │   └─ Si FALLO → reintentar desde PASO 1 con NUEVA identidad
    └─ Guardar credenciales en BD

[3] VERIFICACIÓN Y APROVECHAMIENTO
    ├─ NUEVO CAMBIO DE IDENTIDAD (anti-encadenamiento)
    ├─ Login con las credenciales creadas
    ├─ Verificar:
    │   ├─ ¿La cuenta está limitada?
    │   ├─ ¿Cuál es el saldo actual?
    │   ├─ ¿Qué bonos hay disponibles?
    │   └─ ¿Cuál es la apuesta máxima permitida?
    ├─ Si hay bono disponible:
    │   ├─ Activar el bono
    │   ├─ Buscar eventos importantes del día
    │   ├─ Crear apuesta con el bono
    │   └─ Registrar resultado
    └─ Guardar TODOS los datos en BD

[4] GESTIÓN DE REINTENTOS
    ├─ Si falla: esperar backoff exponencial
    ├─ Cambiar identidad completa
    └─ Reintentar hasta MAX_REINTENTOS

[5] MODO LOOP INFINITO
    ├─ Configurar: cuentas por ciclo, pausa entre ciclos
    ├─ Al terminar lote: reporte automático
    └─ Iniciar siguiente ciclo automáticamente
```

---

## INSTALACIÓN

### Requisitos previos

```bash
# Python 3.11+
python --version

# Instalar dependencias
pip install -r requirements.txt

# Instalar Playwright browsers
playwright install chromium

# (Opcional) Para rotación de MAC en Linux
sudo apt-get install iproute2

# (Opcional) Para rotación de IP móvil
# Instalar Android Platform Tools (ADB)
```

### Dependencias adicionales recomendadas

```bash
# Para gestión de proxies residenciales
pip install smartproxy-client

# Para lectura de SMS virtuales
pip install twilio

# Para base de datos PostgreSQL (opcional, usa SQLite por defecto)
pip install psycopg2-binary
```

---

## USO

### 1. Configuración inicial

#### Pool de MACs (`macs_pool.txt`)
```
# Agrega MACs válidas una por línea
00:50:56:00:00:01
00:0C:29:00:00:02
...
```

#### Pool de Proxies (`proxies.txt`)
```
http://usuario:clave@ip:puerto
socks5://ip:puerto
...
```

#### Configuración de email (`.env`)
```env
EMAIL_FROM=tuemail@gmail.com
EMAIL_TO=tuemail@gmail.com
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=tuemail@gmail.com
SMTP_PASS=tu_app_password
```

### 2. Panel Web (Dashboard)

```bash
# Iniciar servidor web
python -m uvicorn webapp.servidor:app --port 8000

# O usar el batch file
iniciar.bat
```

Abre `http://localhost:8000` en tu navegador.

### 3. Dashboard Streamlit (alternativo)

```bash
streamlit run dashboard.py
```

### 4. Línea de comandos

```bash
python main.py
```

---

## ESTRUCTURA DE ARCHIVOS

### Módulos principales

| Archivo | Descripción |
|---------|-------------|
| `main.py` | Orquestador principal del bot |
| `identity_manager.py` | Gestión de identidad única (MAC, IP, fingerprint) |
| `retry_engine.py` | Motor de reintentos con backoff exponencial |
| `scheduler.py` | Programador de ciclos infinitos |
| `procesador_web.py` | Procesamiento web (login, registro, apuestas) |
| `gestor_perfiles.py` | Lanzamiento de perfiles Chrome aislados |
| `rotador_ip.py` | Rotación de IP móvil vía ADB |
| `dashboard.py` | Panel de control Streamlit |
| `webapp/servidor.py` | Servidor web del dashboard |

### Archivos de configuración

| Archivo | Descripción |
|---------|-------------|
| `cuentas.xlsx` | Lista de cuentas a procesar |
| `proxies.txt` | Pool de proxies rotativos |
| `macs_pool.txt` | Pool de MAC addresses válidas |
| `.env` | Credenciales SMTP y otras config |

### Archivos generados (no versionar)

| Archivo | Descripción |
|---------|-------------|
| `reintentos.json` | Cola de cuentas para reintentar |
| `scheduler_config.json` | Configuración del scheduler |
| `scheduler_estado.json` | Estado actual del scheduler |
| `scheduler_reportes.json` | Reportes históricos de ciclos |
| `perfiles/` | Directorio de perfiles Chrome |
| `historial_auditoria.csv` | Historial de procesamiento |

---

## CONFIGURACIÓN DEL SCHEDULER

Desde el dashboard puedes configurar:

```python
{
    "cuentas_por_ciclo": 10,      # Cuentas a procesar por ciclo
    "pausa_min_minutos": 360.0,   # Mínimo entre ciclos (6 horas)
    "pausa_max_minutos": 480.0,   # Máximo entre ciclos (8 horas)
    "max_ciclos": 0,              # 0 = infinito
    "reiniciar_fallidas": True,   # Reintentar cuentas fallidas
    "solo_exitosas_previas": False # Solo reciclar exitosas
}
```

---

## ANTI-DETECCIÓN CRÍTICA

El bot implementa las siguientes técnicas anti-detección:

1. **Rotación de identidad completa** entre cada cuenta:
   - MAC address diferente
   - IP/proxy diferente
   - Perfil Chrome completamente limpio

2. **Fingerprint aleatorio** por sesión:
   - User-Agent realista rotativo
   - Canvas fingerprint único
   - WebGL vendor/renderer aleatorios
   - Timezone coherente con ubicación del proxy
   - Language coherente con país

3. **Comportamiento humano**:
   - Pausas aleatorias entre acciones
   - Movimientos de mouse no lineales
   - Velocidad de typing variable
   - Scrolls naturales

4. **Límites responsables**:
   - Máximo 3-5 cuentas por IP/MAC al día
   - Pausas largas entre ciclos (6-8 horas)
   - Backoff exponencial en fallos

---

## MÉTRICAS Y REPORTES

El dashboard muestra en tiempo real:

- ✅ Cuentas exitosas vs fallidas
- 💰 Total apostado acumulado
- 🎁 Bonos activados
- ⏱️ Tiempo total de ejecución
- 📊 Tasa de éxito por ciclo
- 🔄 Reintentos pendientes
- 📈 Gráficos de progreso

---

## SOLUCIÓN DE PROBLEMAS

### El bot no cambia la MAC
- **Linux**: Verifica permisos sudo para `ip link`
- **Windows**: Ejecuta como administrador
- **Alternativa**: Usa solo rotación de IP/proxy

### La IP no cambia tras rotación
- Verifica que el celular esté conectado por USB
- Asegura que la depuración USB esté activada
- Confirma que los datos móviles estén activos (no WiFi)

### Cuentas fallidas repetidamente
- Revisa el pool de proxies (pueden estar quemados)
- Aumenta el tiempo entre ciclos
- Reduce la cantidad de cuentas por ciclo
- Verifica que los fingerprints sean variados

### CAPTCHA muy difícil
- El dashboard permite resolución manual
- Considera usar servicio tipo CapSolver
- Aumenta el tiempo de espera para resolver

---

## NOTAS IMPORTANTES

⚠️ **Uso responsable**: Este bot está diseñado para uso personal y educativo. 
Respeta los términos de servicio de las plataformas y la legislación aplicable.

⚠️ **No garantizamos resultados**: El éxito del bot depende de múltiples factores 
externos (disponibilidad de bonos, cambios en la plataforma, etc.).

⚠️ **Riesgo de bloqueo**: Aunque implementamos anti-detección avanzada, siempre 
existe riesgo de que las cuentas sean bloqueadas. Usa bajo tu propia responsabilidad.

---

## SOPORTE

Para reportar errores o sugerencias:
1. Revisa los logs en `bot.log` y `bot_consola.log`
2. Consulta el historial en `historial_auditoria.csv`
3. Usa la pestaña "Resultados" del dashboard para diagnóstico

---

## LICENCIA

Uso interno exclusivo. No distribuir.
