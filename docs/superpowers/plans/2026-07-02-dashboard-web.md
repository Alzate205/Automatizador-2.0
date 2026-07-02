# Dashboard Web (Automatizador Betplay 2.0) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reemplazar el panel Streamlit/Altair por una web local (FastAPI + HTML/CSS/JS) con 3 secciones (Control, Cuentas, Estadísticas), reusando el motor del bot y la comunicación por archivos de `control.py`.

**Architecture:** Un backend FastAPI (`webapp/servidor.py`) sirve una SPA estática y expone una API JSON. Toda la lógica de datos vive en `webapp/datos.py` (sin dependencias web, testeable). El bot (`main.py`) sigue corriendo como subproceso y se comunica por los archivos de `control.py`. El frontend hace polling cada ~1 s de estado y log.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, pandas, openpyxl. Frontend: HTML/CSS/JS vanilla (sin frameworks, sin CDN). Pruebas: pytest + FastAPI TestClient (httpx).

## Global Constraints

- **No romper el motor:** no modificar `main.py`, `procesador_web.py`, `control.py`, `rotador_ip.py`. Solo se consumen sus archivos e interfaces.
- **Sin internet en runtime:** nada de CDNs; gráficas con SVG/CSS propio.
- **Un solo usuario, local:** sin auth, sin BD; persistencia sigue en Excel/CSV.
- **Rutas de archivos (relativas al cwd del proyecto, igual que hoy):** `cuentas.xlsx`, `cuentas_actualizadas.xlsx`, `historial_auditoria.csv`, `bot.log`, `bot_consola.log`.
- **Columnas sensibles:** `["Password", "ClaveCorreo"]`.
- **El servidor corre con el cwd en la raíz del proyecto** (donde está `main.py` y los archivos de estado), para que `control.py` y el subproceso encuentren todo.
- **Config de corrida** (body de `/api/iniciar`), claves exactas que consume `main.py`: `filtro_modo`, `usar_gestor`, `pausa_min`, `pausa_max`, `tareas` (list), `apuesta` (`{modo, valor}`), `cuentas_seleccionadas` (list), `rotar_ip` (bool), `rotar_ip_solo_registro` (bool).

## File Structure

```
webapp/
  __init__.py
  datos.py                 # Lógica de datos pura (Excel, métricas, plantillas, log incremental)
  servidor.py              # FastAPI: estáticos + API + gestión del subproceso main.py
  static/
    index.html             # SPA: 3 secciones
    style.css              # Tema oscuro
    app.js                 # Router de secciones, polling, acciones, tablas
    graficas.js            # Gráficas SVG/CSS propias
iniciar.bat                # Doble clic: arranca uvicorn y abre el navegador
tests/
  __init__.py
  test_datos.py            # Unit tests de datos.py
  test_servidor.py         # Tests de la API con TestClient
requirements.txt           # + fastapi, uvicorn, python-multipart, httpx (test)
```

Responsabilidades:
- `datos.py`: I/O de Excel/CSV, métricas y payloads JSON. Ninguna dependencia de FastAPI.
- `servidor.py`: rutea HTTP, valida entradas, orquesta el subproceso, delega datos a `datos.py` y señales a `control.py`.
- `static/*`: presentación e interacción.

---

### Task 1: `webapp/datos.py` — lógica de datos pura

**Files:**
- Create: `webapp/__init__.py` (vacío)
- Create: `webapp/datos.py`
- Create: `tests/__init__.py` (vacío)
- Test: `tests/test_datos.py`

**Interfaces:**
- Produces:
  - `RUTA_EXCEL, RUTA_RESULTADOS, RUTA_HISTORIAL, LOG_BOT, COLUMNAS_SENSIBLES, COLUMNAS_PLANTILLA`
  - `leer_excel(ruta: str) -> pd.DataFrame`
  - `generar_plantilla_registro(n: int) -> pd.DataFrame`
  - `porcentaje_verificadas(df) -> float`
  - `contar_limitadas(df) -> int`
  - `serie_registro(df) -> pd.Series`
  - `opciones_cuentas(df) -> list[str]`
  - `lineas_log(ruta: str, desde: int) -> dict` → `{"lineas": list[str], "total": int}`
  - `cuentas_como_dict() -> dict` → `{"columnas": list[str], "filas": list[dict]}`
  - `guardar_cuentas(filas: list[dict]) -> int`
  - `anexar_cuenta(fila: dict) -> int`
  - `resultados_payload(ruta: str | None = None) -> dict`

- [ ] **Step 1: Escribir los tests que fallan**

Create `tests/__init__.py` (vacío) y `tests/test_datos.py`:

```python
import pandas as pd
from webapp import datos


def test_porcentaje_verificadas():
    df = pd.DataFrame({"Verificada": ["si", "no", "SI", ""]})
    assert datos.porcentaje_verificadas(df) == 50.0


def test_porcentaje_verificadas_vacio():
    assert datos.porcentaje_verificadas(pd.DataFrame()) == 0.0


def test_contar_limitadas():
    df = pd.DataFrame({"Limitada": ["True", "false", "si", "1", ""]})
    assert datos.contar_limitadas(df) == 3


def test_serie_registro_desde_columna():
    df = pd.DataFrame({"Registro": ["registro_ok", "N/A", "registro_rechazado"]})
    s = datos.serie_registro(df)
    assert list(s) == ["registro_ok", "n/a", "registro_rechazado"]


def test_generar_plantilla_registro():
    df = datos.generar_plantilla_registro(3)
    assert len(df) == 3
    assert list(df["Modo"].unique()) == ["registro"]
    assert set(datos.COLUMNAS_PLANTILLA) <= set(df.columns)


def test_lineas_log_incremental(tmp_path):
    p = tmp_path / "bot.log"
    p.write_text("l1\nl2\nl3\n", encoding="utf-8")
    r = datos.lineas_log(str(p), desde=0)
    assert r["total"] == 3
    assert r["lineas"] == ["l1", "l2", "l3"]
    r2 = datos.lineas_log(str(p), desde=3)
    assert r2["lineas"] == []
    assert r2["total"] == 3


def test_lineas_log_inexistente(tmp_path):
    r = datos.lineas_log(str(tmp_path / "no.log"), desde=0)
    assert r == {"lineas": [], "total": 0}


def test_guardar_y_leer_cuentas(tmp_path, monkeypatch):
    ruta = tmp_path / "cuentas.xlsx"
    monkeypatch.setattr(datos, "RUTA_EXCEL", str(ruta))
    datos.guardar_cuentas([{"Usuario": "a@b.com", "Modo": "login"}])
    d = datos.cuentas_como_dict()
    assert d["filas"][0]["Usuario"] == "a@b.com"
    assert "Usuario" in d["columnas"]


def test_anexar_cuenta(tmp_path, monkeypatch):
    ruta = tmp_path / "cuentas.xlsx"
    monkeypatch.setattr(datos, "RUTA_EXCEL", str(ruta))
    datos.guardar_cuentas([{"Usuario": "a@b.com"}])
    n = datos.anexar_cuenta({"Usuario": "c@d.com"})
    assert n == 2


def test_resultados_payload(tmp_path, monkeypatch):
    ruta = tmp_path / "res.xlsx"
    pd.DataFrame({
        "Usuario": ["a", "b"], "Estado": ["exitosa", "revisar"],
        "Saldo": [1000, 0], "Verificada": ["si", "no"],
        "Limitada": [False, True], "Registro": ["registro_ok", "registro_rechazado"],
        "Password": ["x", "y"],
    }).to_excel(ruta, index=False)
    p = datos.resultados_payload(str(ruta))
    assert p["metricas"]["total"] == 2
    assert p["metricas"]["verificadas_pct"] == 50.0
    assert p["metricas"]["limitadas"] == 1
    assert p["registro"]["registro_ok"] == 1
    assert "Password" not in p["columnas"]  # sensibles fuera por defecto
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `cd "D:/Automatizador 2.0" && python -m pytest tests/test_datos.py -v`
Expected: FAIL (ModuleNotFoundError: webapp.datos).

- [ ] **Step 3: Implementar `webapp/datos.py`**

Create `webapp/__init__.py` vacío. Create `webapp/datos.py`:

```python
"""
datos.py — Lógica de datos del dashboard web (sin dependencias de la web).

Extraído/adaptado de dashboard.py (Streamlit) para reusarlo desde servidor.py.
"""
from __future__ import annotations

import io
import os
import re
from datetime import datetime

import pandas as pd

RUTA_EXCEL = "cuentas.xlsx"
RUTA_RESULTADOS = "cuentas_actualizadas.xlsx"
RUTA_HISTORIAL = "historial_auditoria.csv"
LOG_BOT = "bot.log"

COLUMNAS_SENSIBLES = ["Password", "ClaveCorreo"]

COLUMNAS_PLANTILLA = [
    "Usuario", "Password", "Nombre", "Correo", "ClaveCorreo", "Puerto", "Modo",
    "Cedula", "PrimerNombre", "PrimerApellido", "Telefono",
    "ExpedicionDD", "ExpedicionMM", "ExpedicionYYYY",
    "NacimientoDD", "NacimientoMM", "NacimientoYYYY",
    "LugarExpedicion",
]


def leer_excel(ruta: str) -> pd.DataFrame:
    if not os.path.exists(ruta):
        return pd.DataFrame()
    try:
        return pd.read_excel(ruta)
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


def generar_plantilla_registro(n: int = 10) -> pd.DataFrame:
    df = pd.DataFrame(columns=COLUMNAS_PLANTILLA)
    for i in range(int(n)):
        df.loc[i] = {
            "Usuario": "", "Password": "", "Nombre": f"Cuenta {i + 1}",
            "Correo": "", "ClaveCorreo": "", "Puerto": 9222 + i, "Modo": "registro",
            "Cedula": "", "PrimerNombre": "", "PrimerApellido": "", "Telefono": "",
            "ExpedicionDD": "15", "ExpedicionMM": "06", "ExpedicionYYYY": "1995",
            "NacimientoDD": "10", "NacimientoMM": "03", "NacimientoYYYY": "1995",
            "LugarExpedicion": "BOGOTA",
        }
    return df


def leer_historial() -> pd.DataFrame:
    if not os.path.exists(RUTA_HISTORIAL):
        return pd.DataFrame()
    try:
        return pd.read_csv(RUTA_HISTORIAL)
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


def porcentaje_verificadas(df: pd.DataFrame) -> float:
    if "Verificada" not in df.columns or len(df) == 0:
        return 0.0
    ver = df["Verificada"].astype(str).str.strip().str.lower().eq("si").sum()
    return round(ver / len(df) * 100, 1)


def contar_limitadas(df: pd.DataFrame) -> int:
    if "Limitada" not in df.columns:
        return 0
    valores = df["Limitada"].astype(str).str.strip().str.lower()
    return int(valores.isin(["true", "si", "1", "limitada"]).sum())


def serie_registro(df: pd.DataFrame) -> pd.Series:
    if "Registro" in df.columns:
        return df["Registro"].astype(str).str.strip().str.lower()
    if "Detalle" in df.columns:
        return (
            df["Detalle"].astype(str)
            .str.extract(r"reg:\s*([a-z_]+)", flags=re.IGNORECASE, expand=False)
            .fillna("").str.lower()
        )
    return pd.Series([""] * len(df), index=df.index)


def opciones_cuentas(df: pd.DataFrame) -> list:
    if df.empty:
        return []
    opciones: list = []
    for _, fila in df.iterrows():
        ident = str(fila.get("Correo") or fila.get("Usuario") or "").strip()
        if ident and ident.lower() != "nan" and ident not in opciones:
            opciones.append(ident)
    return opciones


def lineas_log(ruta: str, desde: int = 0) -> dict:
    """Líneas del log desde el índice `desde` (log incremental)."""
    if not os.path.exists(ruta):
        return {"lineas": [], "total": 0}
    try:
        with open(ruta, encoding="utf-8", errors="replace") as f:
            todas = f.read().splitlines()
    except Exception:  # noqa: BLE001
        return {"lineas": [], "total": 0}
    desde = max(0, int(desde))
    return {"lineas": todas[desde:], "total": len(todas)}


def _limpiar_nan(df: pd.DataFrame) -> pd.DataFrame:
    return df.where(pd.notna(df), None)


def cuentas_como_dict() -> dict:
    df = leer_excel(RUTA_EXCEL)
    if df.empty:
        return {"columnas": COLUMNAS_PLANTILLA, "filas": []}
    df = _limpiar_nan(df)
    return {"columnas": list(df.columns), "filas": df.to_dict(orient="records")}


def guardar_cuentas(filas: list) -> int:
    df = pd.DataFrame(filas)
    df.to_excel(RUTA_EXCEL, index=False)
    return len(df)


def anexar_cuenta(fila: dict) -> int:
    df = leer_excel(RUTA_EXCEL)
    nueva = pd.DataFrame([fila])
    df = pd.concat([df, nueva], ignore_index=True) if not df.empty else nueva
    df.to_excel(RUTA_EXCEL, index=False)
    return len(df)


def to_excel_bytes(df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Resultados")
    return buffer.getvalue()


def resultados_payload(ruta: str | None = None, incluir_sensibles: bool = False) -> dict:
    ruta = ruta or RUTA_RESULTADOS
    df = leer_excel(ruta)
    if df.empty:
        return {"metricas": {"total": 0, "verificadas_pct": 0.0, "limitadas": 0,
                             "saldo_total": 0.0},
                "registro": {}, "saldo_por_estado": {}, "verificadas": {},
                "columnas": [], "filas": []}

    reg = serie_registro(df)
    estados_reg = ["registro_ok", "registro_incierto", "registro_rechazado", "error_registro"]
    conteo_reg = {e: int((reg == e).sum()) for e in estados_reg if (reg == e).any()}

    saldo = pd.to_numeric(df.get("Saldo", pd.Series(dtype=float)), errors="coerce").fillna(0)
    saldo_por_estado = {}
    if "Estado" in df.columns:
        tmp = df.copy()
        tmp["_saldo"] = saldo.values
        saldo_por_estado = {str(k): float(v) for k, v in
                            tmp.groupby("Estado")["_saldo"].sum().items()}

    ver = df.get("Verificada", pd.Series(dtype=str)).astype(str).str.strip().str.lower()
    verificadas = {
        "Verificada": int((ver == "si").sum()),
        "No verificada": int((ver != "si").sum()),
    }

    df_vis = df if incluir_sensibles else df[[c for c in df.columns if c not in COLUMNAS_SENSIBLES]]
    df_vis = _limpiar_nan(df_vis)

    return {
        "metricas": {
            "total": int(len(df)),
            "verificadas_pct": porcentaje_verificadas(df),
            "limitadas": contar_limitadas(df),
            "saldo_total": float(saldo.sum()),
        },
        "registro": conteo_reg,
        "saldo_por_estado": saldo_por_estado,
        "verificadas": verificadas,
        "columnas": list(df_vis.columns),
        "filas": df_vis.to_dict(orient="records"),
    }
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `cd "D:/Automatizador 2.0" && python -m pytest tests/test_datos.py -v`
Expected: PASS (10 tests).

- [ ] **Step 5: Commit**

```bash
git add webapp/__init__.py webapp/datos.py tests/__init__.py tests/test_datos.py
git commit -m "feat(webapp): lógica de datos del dashboard (datos.py) con tests"
```

---

### Task 2: `webapp/servidor.py` — FastAPI + control del bot

**Files:**
- Create: `webapp/servidor.py`
- Modify: `requirements.txt` (añadir dependencias)
- Test: `tests/test_servidor.py`

**Interfaces:**
- Consumes: `webapp.datos.*`, `control.*` (leer_estado, escribir_config, reset_control, escribir_estado, pedir_detener, pedir_continuar).
- Produces: `app` (FastAPI), endpoints `/api/estado`, `/api/log`, `/api/iniciar`, `/api/detener`, `/api/continuar`, `/api/forzar-parada`. Estado del subproceso en `estado_proc` (dict de módulo con clave `"proc"`).

- [ ] **Step 1: Añadir dependencias a `requirements.txt`**

Append al final de `requirements.txt`:

```
fastapi
uvicorn[standard]
python-multipart
httpx
```

Install: `cd "D:/Automatizador 2.0" && pip install fastapi "uvicorn[standard]" python-multipart httpx`

- [ ] **Step 2: Escribir los tests que fallan**

Create `tests/test_servidor.py`:

```python
import os
import pandas as pd
from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch):
    # El servidor y control.py trabajan con cwd = raíz del proyecto.
    monkeypatch.chdir(tmp_path)
    from webapp import servidor
    return TestClient(servidor.app)


def test_estado_por_defecto(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/estado")
    assert r.status_code == 200
    assert r.json()["estado"] == "inactivo"


def test_log_incremental(tmp_path, monkeypatch):
    (tmp_path / "bot.log").write_text("a\nb\n", encoding="utf-8")
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/log", params={"desde": 0})
    assert r.json()["lineas"] == ["a", "b"]
    assert r.json()["total"] == 2


def test_iniciar_escribe_config_sin_lanzar(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    from webapp import servidor
    # No lanzar el bot real: parcheamos el lanzador.
    monkeypatch.setattr(servidor, "_lanzar_bot", lambda: None)
    cfg = {"filtro_modo": "registro", "tareas": ["bonos"], "rotar_ip": True}
    r = c.post("/api/iniciar", json=cfg)
    assert r.status_code == 200
    import json
    guardada = json.loads((tmp_path / "config_run.json").read_text(encoding="utf-8"))
    assert guardada["filtro_modo"] == "registro"
    assert guardada["rotar_ip"] is True


def test_detener_y_continuar_crean_senales(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert c.post("/api/detener").status_code == 200
    assert os.path.exists(tmp_path / "senal_detener.flag")
    assert c.post("/api/continuar").status_code == 200
    assert os.path.exists(tmp_path / "senal_continuar.flag")
```

- [ ] **Step 3: Correr los tests y verificar que fallan**

Run: `cd "D:/Automatizador 2.0" && python -m pytest tests/test_servidor.py -v`
Expected: FAIL (ModuleNotFoundError: webapp.servidor).

- [ ] **Step 4: Implementar `webapp/servidor.py` (base + control)**

Create `webapp/servidor.py`:

```python
"""
servidor.py — Backend FastAPI del dashboard web.

Sirve la SPA estática y expone la API. Lanza main.py como subproceso y se
comunica con el bot por los archivos de control.py. Corre con cwd = raíz del
proyecto.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

import control
from webapp import datos

app = FastAPI(title="Automatizador Betplay — Dashboard")

_STATIC = Path(__file__).parent / "static"

# Handle del subproceso del bot (un solo run a la vez).
estado_proc: dict = {"proc": None}

LOG_CONSOLA = "bot_consola.log"


def _bot_vivo() -> bool:
    proc = estado_proc["proc"]
    return proc is not None and proc.poll() is None


def _lanzar_bot() -> None:
    salida = open(LOG_CONSOLA, "a", encoding="utf-8")
    estado_proc["proc"] = subprocess.Popen(
        [sys.executable, "main.py"], stdout=salida, stderr=subprocess.STDOUT
    )


# ---------------- API: control ----------------

@app.get("/api/estado")
def api_estado():
    est = control.leer_estado()
    est["proceso_vivo"] = _bot_vivo()
    return est


@app.get("/api/log")
def api_log(desde: int = 0):
    return datos.lineas_log(datos.LOG_BOT, desde)


@app.post("/api/iniciar")
async def api_iniciar(request: Request):
    if _bot_vivo():
        return JSONResponse({"error": "El bot ya está corriendo"}, status_code=409)
    cfg = await request.json()
    control.escribir_config(cfg)
    control.reset_control()
    control.escribir_estado(estado="corriendo", mensaje="Lanzando bot...",
                            indice=0, total=0, resumen={})
    _lanzar_bot()
    return {"ok": True}


@app.post("/api/detener")
def api_detener():
    control.pedir_detener()
    return {"ok": True}


@app.post("/api/continuar")
def api_continuar():
    control.pedir_continuar()
    return {"ok": True}


@app.post("/api/forzar-parada")
def api_forzar_parada():
    control.pedir_detener()
    proc = estado_proc["proc"]
    if proc is not None and proc.poll() is None:
        proc.terminate()
    return {"ok": True}


# ---------------- Estáticos (al final para no tapar /api) ----------------

app.mount("/", StaticFiles(directory=str(_STATIC), html=True), name="static")
```

Nota: crear `webapp/static/` con un `index.html` mínimo temporal para que el mount no falle:
`echo "<!doctype html><title>ok</title>" > webapp/static/index.html`

- [ ] **Step 5: Correr los tests y verificar que pasan**

Run: `cd "D:/Automatizador 2.0" && python -m pytest tests/test_servidor.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add requirements.txt webapp/servidor.py webapp/static/index.html tests/test_servidor.py
git commit -m "feat(webapp): servidor FastAPI con endpoints de control + tests"
```

---

### Task 3: Endpoints de cuentas

**Files:**
- Modify: `webapp/servidor.py`
- Test: `tests/test_servidor.py` (añadir tests)

**Interfaces:**
- Consumes: `datos.cuentas_como_dict`, `datos.guardar_cuentas`, `datos.generar_plantilla_registro`, `datos.anexar_cuenta`, `datos.leer_excel`, `datos.RUTA_EXCEL`.
- Produces: `/api/cuentas` (GET/POST), `/api/cuentas/plantilla` (POST), `/api/cuentas/importar` (POST multipart), `/api/cuentas/registrar` (POST).

- [ ] **Step 1: Añadir tests que fallan**

Append a `tests/test_servidor.py`:

```python
def test_cuentas_get_post(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/cuentas", json={"filas": [{"Usuario": "a@b.com", "Modo": "login"}]})
    assert r.status_code == 200 and r.json()["guardadas"] == 1
    g = c.get("/api/cuentas")
    assert g.json()["filas"][0]["Usuario"] == "a@b.com"


def test_cuentas_plantilla(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/cuentas/plantilla", json={"n": 4})
    assert r.status_code == 200 and r.json()["guardadas"] == 4
    assert c.get("/api/cuentas").json()["filas"][0]["Modo"] == "registro"


def test_cuentas_registrar(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    c.post("/api/cuentas", json={"filas": [{"Usuario": "a@b.com"}]})
    r = c.post("/api/cuentas/registrar", json={"Usuario": "c@d.com", "Modo": "registro"})
    assert r.status_code == 200 and r.json()["total"] == 2


def test_cuentas_importar(tmp_path, monkeypatch):
    import io, pandas as pd
    c = _client(tmp_path, monkeypatch)
    buf = io.BytesIO()
    pd.DataFrame({"Usuario": ["x@y.com"]}).to_excel(buf, index=False)
    buf.seek(0)
    r = c.post("/api/cuentas/importar",
               files={"archivo": ("cuentas.xlsx", buf.getvalue(),
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200 and r.json()["guardadas"] == 1
    assert c.get("/api/cuentas").json()["filas"][0]["Usuario"] == "x@y.com"
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `cd "D:/Automatizador 2.0" && python -m pytest tests/test_servidor.py -k cuentas -v`
Expected: FAIL (404 / atributo inexistente).

- [ ] **Step 3: Implementar los endpoints de cuentas**

En `webapp/servidor.py`, ANTES de la línea `app.mount("/", ...)`, insertar:

```python
import io as _io
import pandas as _pd
from fastapi import UploadFile, File


@app.get("/api/cuentas")
def api_cuentas_get():
    return datos.cuentas_como_dict()


@app.post("/api/cuentas")
async def api_cuentas_post(request: Request):
    body = await request.json()
    n = datos.guardar_cuentas(body.get("filas", []))
    return {"ok": True, "guardadas": n}


@app.post("/api/cuentas/plantilla")
async def api_cuentas_plantilla(request: Request):
    body = await request.json()
    df = datos.generar_plantilla_registro(int(body.get("n", 10)))
    df.to_excel(datos.RUTA_EXCEL, index=False)
    return {"ok": True, "guardadas": len(df)}


@app.post("/api/cuentas/registrar")
async def api_cuentas_registrar(request: Request):
    fila = await request.json()
    total = datos.anexar_cuenta(fila)
    return {"ok": True, "total": total}


@app.post("/api/cuentas/importar")
async def api_cuentas_importar(archivo: UploadFile = File(...)):
    contenido = await archivo.read()
    df = _pd.read_excel(_io.BytesIO(contenido))
    df.to_excel(datos.RUTA_EXCEL, index=False)
    return {"ok": True, "guardadas": len(df)}
```

- [ ] **Step 4: Correr y verificar que pasan**

Run: `cd "D:/Automatizador 2.0" && python -m pytest tests/test_servidor.py -v`
Expected: PASS (todos).

- [ ] **Step 5: Commit**

```bash
git add webapp/servidor.py tests/test_servidor.py
git commit -m "feat(webapp): endpoints de cuentas (CRUD, plantilla, importar, registrar)"
```

---

### Task 4: Endpoint de resultados

**Files:**
- Modify: `webapp/servidor.py`
- Test: `tests/test_servidor.py` (añadir test)

**Interfaces:**
- Consumes: `datos.resultados_payload`, `datos.leer_excel`, `datos.to_excel_bytes`, `datos.RUTA_RESULTADOS`.
- Produces: `/api/resultados` (GET), `/api/resultados/exportar` (GET → xlsx).

- [ ] **Step 1: Añadir test que falla**

Append a `tests/test_servidor.py`:

```python
def test_resultados(tmp_path, monkeypatch):
    import pandas as pd
    pd.DataFrame({"Usuario": ["a"], "Estado": ["exitosa"], "Saldo": [500],
                  "Verificada": ["si"], "Limitada": [False],
                  "Registro": ["registro_ok"]}).to_excel(
        tmp_path / "cuentas_actualizadas.xlsx", index=False)
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/resultados")
    assert r.status_code == 200
    assert r.json()["metricas"]["total"] == 1
    assert r.json()["registro"]["registro_ok"] == 1
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `cd "D:/Automatizador 2.0" && python -m pytest tests/test_servidor.py -k resultados -v`
Expected: FAIL (404).

- [ ] **Step 3: Implementar los endpoints de resultados**

En `webapp/servidor.py`, antes de `app.mount(...)`, añadir:

```python
from fastapi.responses import Response


@app.get("/api/resultados")
def api_resultados():
    return datos.resultados_payload()


@app.get("/api/resultados/exportar")
def api_resultados_exportar():
    df = datos.leer_excel(datos.RUTA_RESULTADOS)
    contenido = datos.to_excel_bytes(df)
    return Response(
        content=contenido,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=resultados.xlsx"},
    )
```

- [ ] **Step 4: Correr y verificar que pasan**

Run: `cd "D:/Automatizador 2.0" && python -m pytest tests/ -v`
Expected: PASS (todos).

- [ ] **Step 5: Commit**

```bash
git add webapp/servidor.py tests/test_servidor.py
git commit -m "feat(webapp): endpoints de resultados + exportar Excel"
```

---

### Task 5: Frontend — HTML + CSS (estructura y tema oscuro)

**Files:**
- Modify: `webapp/static/index.html` (reemplazar el placeholder)
- Create: `webapp/static/style.css`

**Interfaces:**
- Produces: estructura DOM con `#nav` (3 secciones), `#seccion-control`, `#seccion-cuentas`, `#seccion-estadisticas`; sidebar `#sidebar`; consola `#consola`; barra `#barra-progreso`; cabecera `#cabecera`.

- [ ] **Step 1: Escribir `index.html`**

Reemplazar el contenido de `webapp/static/index.html`:

```html
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Automatizador Betplay</title>
  <link rel="stylesheet" href="/style.css">
</head>
<body>
  <header id="cabecera">
    <h1>Bot Verificador Betplay</h1>
    <span id="contador-cuentas">0 cuentas cargadas</span>
    <nav id="nav">
      <button data-sec="control" class="activo">Control</button>
      <button data-sec="cuentas">Cuentas</button>
      <button data-sec="estadisticas">Estadísticas</button>
    </nav>
  </header>

  <main>
    <!-- CONTROL -->
    <section id="seccion-control" class="seccion activa">
      <aside id="sidebar">
        <h2>Acciones</h2>
        <button id="btn-iniciar" class="accion primaria">Iniciar</button>
        <button id="btn-detener" class="accion" disabled>Detener</button>
        <button id="btn-continuar" class="accion continuar" disabled>Continuar</button>
        <button id="btn-forzar" class="accion peligro">Forzar parada</button>
        <hr>
        <h3>Tareas</h3>
        <label><input type="checkbox" id="t-bonos" checked> Verificar bonos</label>
        <label><input type="checkbox" id="t-limite" checked> Verificar límite</label>
        <label><input type="checkbox" id="t-apbono"> Apostar bono</label>
        <label><input type="checkbox" id="t-apsaldo"> Apostar saldo</label>
        <hr>
        <h3>Monto apuesta</h3>
        <select id="monto-modo"><option value="fijo">Fijo</option><option value="porcentaje">Porcentaje</option></select>
        <input type="number" id="monto-valor" value="2000" step="500">
        <hr>
        <h3>Rotación de IP</h3>
        <label><input type="checkbox" id="rotar-ip"> Rotar IP entre cuentas</label>
        <label><input type="checkbox" id="rotar-solo-reg" checked> Solo tras registros</label>
        <hr>
        <h3>Otros</h3>
        <label>Filtro modo
          <select id="filtro-modo"><option value="todo">Todo</option><option value="login">Login</option><option value="registro">Registro</option></select>
        </label>
        <label><input type="checkbox" id="usar-gestor" checked> Usar gestor de perfiles</label>
      </aside>
      <div id="panel">
        <div id="cabecera-estado">Inactivo</div>
        <div id="progreso-wrap"><div id="barra-progreso"></div></div>
        <pre id="consola"></pre>
      </div>
    </section>

    <!-- CUENTAS -->
    <section id="seccion-cuentas" class="seccion">
      <div class="barra-acciones">
        <button id="btn-guardar-cuentas" class="accion primaria">Guardar cambios</button>
        <label>Plantilla N <input type="number" id="plantilla-n" value="10" min="1" style="width:70px"></label>
        <button id="btn-plantilla" class="accion">Generar plantilla</button>
        <label class="importar">Importar Excel <input type="file" id="importar-archivo" accept=".xlsx"></label>
      </div>
      <div id="tabla-cuentas"></div>
    </section>

    <!-- ESTADISTICAS -->
    <section id="seccion-estadisticas" class="seccion">
      <div id="tarjetas-metricas" class="tarjetas"></div>
      <div class="graficas">
        <div class="grafica"><h3>Estados de registro</h3><div id="g-registro"></div></div>
        <div class="grafica"><h3>Verificadas</h3><div id="g-verificadas"></div></div>
        <div class="grafica"><h3>Saldo por estado</h3><div id="g-saldo"></div></div>
      </div>
      <button id="btn-exportar" class="accion">Descargar Excel</button>
      <div id="tabla-resultados"></div>
    </section>
  </main>

  <script src="/graficas.js"></script>
  <script src="/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Escribir `style.css`**

Create `webapp/static/style.css`:

```css
:root{
  --bg:#12151c; --panel:#1b1f2a; --panel2:#232838; --txt:#e6e9f0; --muted:#8a92a6;
  --azul:#3b82f6; --verde:#22c55e; --amarillo:#eab308; --rojo:#ef4444; --borde:#2b3142;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);font-family:Segoe UI,system-ui,sans-serif;font-size:14px}
#cabecera{display:flex;align-items:center;gap:20px;padding:12px 20px;background:var(--panel);border-bottom:1px solid var(--borde)}
#cabecera h1{font-size:18px;margin:0;color:var(--azul)}
#contador-cuentas{color:var(--verde);margin-left:auto}
#nav{display:flex;gap:6px}
#nav button{background:transparent;color:var(--muted);border:none;padding:8px 14px;border-radius:6px;cursor:pointer}
#nav button.activo{background:var(--panel2);color:var(--txt)}
.seccion{display:none;padding:16px}
.seccion.activa{display:block}
#seccion-control.activa{display:flex;gap:16px;height:calc(100vh - 120px)}
#sidebar{width:240px;background:var(--panel);border:1px solid var(--borde);border-radius:10px;padding:14px;overflow:auto;flex-shrink:0}
#sidebar h2{font-size:13px;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin:0 0 10px}
#sidebar h3{font-size:12px;color:var(--muted);margin:14px 0 6px}
#sidebar label{display:block;margin:6px 0;color:var(--txt)}
#sidebar hr{border:none;border-top:1px solid var(--borde);margin:12px 0}
.accion{display:block;width:100%;margin:6px 0;padding:10px;border:none;border-radius:8px;background:var(--panel2);color:var(--txt);cursor:pointer;font-weight:600}
.accion:hover{filter:brightness(1.15)}
.accion:disabled{opacity:.4;cursor:not-allowed}
.accion.primaria{background:var(--azul)}
.accion.continuar{background:var(--verde)}
.accion.peligro{background:var(--rojo)}
#panel{flex:1;display:flex;flex-direction:column;background:var(--panel);border:1px solid var(--borde);border-radius:10px;overflow:hidden}
#cabecera-estado{padding:10px 14px;border-bottom:1px solid var(--borde);font-weight:600}
#progreso-wrap{height:8px;background:var(--panel2)}
#barra-progreso{height:100%;width:0;background:var(--verde);transition:width .3s}
#consola{flex:1;margin:0;padding:14px;overflow:auto;font-family:Consolas,monospace;font-size:13px;line-height:1.5;white-space:pre-wrap}
.log-info{color:var(--txt)} .log-exito{color:var(--verde)} .log-aviso{color:var(--amarillo)} .log-error{color:var(--rojo)}
.barra-acciones{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin-bottom:14px}
.tarjetas{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:18px}
.tarjeta{background:var(--panel);border:1px solid var(--borde);border-radius:10px;padding:16px;min-width:150px}
.tarjeta .valor{font-size:26px;font-weight:700}
.tarjeta .etq{color:var(--muted);font-size:12px}
.graficas{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:18px}
.grafica{background:var(--panel);border:1px solid var(--borde);border-radius:10px;padding:14px;flex:1;min-width:280px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{border:1px solid var(--borde);padding:6px 8px;text-align:left}
th{background:var(--panel2)}
td input{width:100%;background:transparent;border:none;color:var(--txt)}
.tabla-scroll{overflow-x:auto}
```

- [ ] **Step 3: Verificación manual**

Run: `cd "D:/Automatizador 2.0" && python -m uvicorn webapp.servidor:app --port 8000`
Abre `http://localhost:8000`. Verificar: se ve el tema oscuro, la cabecera, la navegación de 3 secciones (aunque sin datos aún), el sidebar y la consola vacía. Ctrl+C para detener.

- [ ] **Step 4: Commit**

```bash
git add webapp/static/index.html webapp/static/style.css
git commit -m "feat(webapp): estructura HTML + tema oscuro (3 secciones)"
```

---

### Task 6: Frontend — `app.js` sección Control (polling + acciones)

**Files:**
- Create: `webapp/static/app.js`

**Interfaces:**
- Consumes: `/api/estado`, `/api/log`, `/api/iniciar`, `/api/detener`, `/api/continuar`, `/api/forzar-parada`, `/api/cuentas` (para el contador).
- Produces: navegación entre secciones; loop de polling; `window.__logDesde` (índice del log).

- [ ] **Step 1: Escribir `app.js`**

Create `webapp/static/app.js`:

```javascript
const $ = (s) => document.querySelector(s);

// --- Navegación entre secciones ---
document.querySelectorAll('#nav button').forEach(b => {
  b.onclick = () => {
    document.querySelectorAll('#nav button').forEach(x => x.classList.remove('activo'));
    b.classList.add('activo');
    document.querySelectorAll('.seccion').forEach(s => s.classList.remove('activa'));
    $('#seccion-' + b.dataset.sec).classList.add('activa');
    if (b.dataset.sec === 'cuentas') cargarCuentas();
    if (b.dataset.sec === 'estadisticas') cargarEstadisticas();
  };
});

// --- Config de corrida desde el sidebar ---
function leerConfig() {
  const tareas = [];
  if ($('#t-bonos').checked) tareas.push('bonos');
  if ($('#t-limite').checked) tareas.push('apuesta_maxima');
  if ($('#t-apbono').checked) tareas.push('apostar_bono');
  if ($('#t-apsaldo').checked) tareas.push('apostar_saldo');
  return {
    filtro_modo: $('#filtro-modo').value,
    usar_gestor: $('#usar-gestor').checked,
    pausa_min: 4, pausa_max: 12,
    tareas,
    apuesta: { modo: $('#monto-modo').value, valor: parseFloat($('#monto-valor').value) || 0 },
    cuentas_seleccionadas: [],
    rotar_ip: $('#rotar-ip').checked,
    rotar_ip_solo_registro: $('#rotar-solo-reg').checked,
  };
}

async function post(url, body) {
  const r = await fetch(url, {
    method: 'POST',
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  return r.json().catch(() => ({}));
}

$('#btn-iniciar').onclick = () => { window.__logDesde = 0; $('#consola').textContent = ''; post('/api/iniciar', leerConfig()); };
$('#btn-detener').onclick = () => post('/api/detener');
$('#btn-continuar').onclick = () => post('/api/continuar');
$('#btn-forzar').onclick = () => post('/api/forzar-parada');

// --- Consola: colorear por nivel ---
function claseLinea(l) {
  if (/\[ERROR\]/.test(l)) return 'log-error';
  if (/\[WARNING\]/.test(l)) return 'log-aviso';
  if (/\[EXITO\]|✓|rotada OK|IP rotada|exito/i.test(l)) return 'log-exito';
  return 'log-info';
}

window.__logDesde = 0;
async function pollLog() {
  try {
    const r = await (await fetch('/api/log?desde=' + window.__logDesde)).json();
    if (r.lineas && r.lineas.length) {
      const con = $('#consola');
      const pegado = con.scrollTop + con.clientHeight >= con.scrollHeight - 20;
      for (const l of r.lineas) {
        const span = document.createElement('span');
        span.className = claseLinea(l);
        span.textContent = l + '\n';
        con.appendChild(span);
      }
      window.__logDesde = r.total;
      if (pegado) con.scrollTop = con.scrollHeight;
    }
  } catch (e) {}
}

async function pollEstado() {
  try {
    const e = await (await fetch('/api/estado')).json();
    $('#cabecera-estado').textContent =
      `${e.estado} — ${e.fase || ''} — ${e.cuenta || ''} (${e.indice || 0}/${e.total || 0})`;
    const pct = e.total ? Math.round((e.indice / e.total) * 100) : 0;
    $('#barra-progreso').style.width = pct + '%';
    const corriendo = e.proceso_vivo || ['corriendo', 'esperando_captcha', 'esperando_apuesta'].includes(e.estado);
    const esperando = ['esperando_captcha', 'esperando_apuesta'].includes(e.estado);
    $('#btn-iniciar').disabled = corriendo;
    $('#btn-detener').disabled = !corriendo;
    $('#btn-continuar').disabled = !esperando;
  } catch (e) {}
}

async function actualizarContador() {
  try {
    const c = await (await fetch('/api/cuentas')).json();
    $('#contador-cuentas').textContent = (c.filas ? c.filas.length : 0) + ' cuentas cargadas';
  } catch (e) {}
}

setInterval(pollLog, 1000);
setInterval(pollEstado, 1000);
actualizarContador();
```

- [ ] **Step 2: Verificación manual**

Run: `cd "D:/Automatizador 2.0" && python -m uvicorn webapp.servidor:app --port 8000`
Abre `http://localhost:8000`. La cabecera de estado y el contador de cuentas deben poblarse. Los botones deben habilitarse/deshabilitarse según el estado. (No inicies el bot todavía; solo verifica el polling.) Ctrl+C.

- [ ] **Step 3: Commit**

```bash
git add webapp/static/app.js
git commit -m "feat(webapp): sección Control (polling estado/log, acciones, consola)"
```

---

### Task 7: Frontend — sección Cuentas (tabla editable)

**Files:**
- Modify: `webapp/static/app.js` (añadir funciones de cuentas)

**Interfaces:**
- Consumes: `/api/cuentas` (GET/POST), `/api/cuentas/plantilla`, `/api/cuentas/importar`.
- Produces: `cargarCuentas()`, render de tabla editable en `#tabla-cuentas`.

- [ ] **Step 1: Añadir el código de cuentas a `app.js`**

Append a `webapp/static/app.js`:

```javascript
// --- Sección Cuentas ---
let _colsCuentas = [];
async function cargarCuentas() {
  const d = await (await fetch('/api/cuentas')).json();
  _colsCuentas = d.columnas;
  const filas = d.filas || [];
  let html = '<div class="tabla-scroll"><table><thead><tr>';
  for (const c of _colsCuentas) html += `<th>${c}</th>`;
  html += '</tr></thead><tbody>';
  filas.forEach((fila, i) => {
    html += '<tr>';
    for (const c of _colsCuentas) {
      const v = fila[c] == null ? '' : String(fila[c]);
      html += `<td><input data-fila="${i}" data-col="${c}" value="${v.replace(/"/g, '&quot;')}"></td>`;
    }
    html += '</tr>';
  });
  html += '</tbody></table></div>';
  $('#tabla-cuentas').innerHTML = html;
}

function recogerFilasCuentas() {
  const inputs = $('#tabla-cuentas').querySelectorAll('input[data-fila]');
  const filas = {};
  inputs.forEach(inp => {
    const i = inp.dataset.fila;
    filas[i] = filas[i] || {};
    filas[i][inp.dataset.col] = inp.value;
  });
  return Object.values(filas);
}

$('#btn-guardar-cuentas').onclick = async () => {
  const r = await post('/api/cuentas', { filas: recogerFilasCuentas() });
  alert('Guardadas: ' + (r.guardadas ?? '?'));
  actualizarContador();
};

$('#btn-plantilla').onclick = async () => {
  await post('/api/cuentas/plantilla', { n: parseInt($('#plantilla-n').value) || 10 });
  cargarCuentas(); actualizarContador();
};

$('#importar-archivo').onchange = async (ev) => {
  const f = ev.target.files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append('archivo', f);
  await fetch('/api/cuentas/importar', { method: 'POST', body: fd });
  cargarCuentas(); actualizarContador();
};
```

- [ ] **Step 2: Verificación manual**

Run el servidor, ve a la sección Cuentas. Genera una plantilla de 3, edita una celda, Guardar cambios; recarga y verifica que persiste en `cuentas.xlsx`.

- [ ] **Step 3: Commit**

```bash
git add webapp/static/app.js
git commit -m "feat(webapp): sección Cuentas (tabla editable, plantilla, importar)"
```

---

### Task 8: Frontend — sección Estadísticas + gráficas SVG

**Files:**
- Create: `webapp/static/graficas.js`
- Modify: `webapp/static/app.js` (añadir `cargarEstadisticas`)

**Interfaces:**
- Consumes: `/api/resultados`, `/api/resultados/exportar`.
- Produces: `Graficas.barras(elId, datos)`, `Graficas.dona(elId, datos)`; `cargarEstadisticas()`.

- [ ] **Step 1: Escribir `graficas.js` (SVG puro, sin librerías)**

Create `webapp/static/graficas.js`:

```javascript
const Graficas = {
  _colores: ['#3b82f6', '#22c55e', '#eab308', '#ef4444', '#a855f7', '#14b8a6'],

  barras(elId, datos) {
    // datos: { etiqueta: valor }
    const el = document.getElementById(elId);
    const pares = Object.entries(datos);
    if (!pares.length) { el.innerHTML = '<p style="color:#8a92a6">Sin datos</p>'; return; }
    const max = Math.max(...pares.map(p => p[1])) || 1;
    let h = '';
    pares.forEach(([k, v], i) => {
      const pct = Math.round((v / max) * 100);
      const col = this._colores[i % this._colores.length];
      h += `<div style="margin:6px 0">
        <div style="display:flex;justify-content:space-between;font-size:12px">
          <span>${k}</span><span>${(+v).toLocaleString()}</span></div>
        <div style="background:#232838;border-radius:4px;height:14px">
          <div style="width:${pct}%;height:100%;background:${col};border-radius:4px"></div></div>
      </div>`;
    });
    el.innerHTML = h;
  },

  dona(elId, datos) {
    // datos: { etiqueta: valor } (2 categorías); dibuja una dona SVG.
    const el = document.getElementById(elId);
    const pares = Object.entries(datos);
    const total = pares.reduce((s, p) => s + p[1], 0) || 1;
    let acum = 0, segs = '';
    const R = 60, C = 2 * Math.PI * R;
    pares.forEach(([k, v], i) => {
      const frac = v / total;
      const col = this._colores[i % this._colores.length];
      segs += `<circle r="${R}" cx="80" cy="80" fill="transparent" stroke="${col}"
        stroke-width="28" stroke-dasharray="${frac * C} ${C}"
        stroke-dashoffset="${-acum * C}" transform="rotate(-90 80 80)"></circle>`;
      acum += frac;
    });
    const leyenda = pares.map(([k, v], i) =>
      `<div style="font-size:12px"><span style="color:${this._colores[i % this._colores.length]}">■</span> ${k}: ${v}</div>`).join('');
    el.innerHTML = `<svg width="160" height="160">${segs}</svg><div>${leyenda}</div>`;
  },
};
```

- [ ] **Step 2: Añadir `cargarEstadisticas` a `app.js`**

Append a `webapp/static/app.js`:

```javascript
// --- Sección Estadísticas ---
async function cargarEstadisticas() {
  const d = await (await fetch('/api/resultados')).json();
  const m = d.metricas || {};
  $('#tarjetas-metricas').innerHTML = [
    ['Total', m.total ?? 0],
    ['Verificadas', (m.verificadas_pct ?? 0) + ' %'],
    ['Limitadas', m.limitadas ?? 0],
    ['Saldo total', (m.saldo_total ?? 0).toLocaleString()],
  ].map(([e, v]) => `<div class="tarjeta"><div class="valor">${v}</div><div class="etq">${e}</div></div>`).join('');

  Graficas.barras('g-registro', d.registro || {});
  Graficas.dona('g-verificadas', d.verificadas || {});
  Graficas.barras('g-saldo', d.saldo_por_estado || {});

  const cols = d.columnas || [], filas = d.filas || [];
  let html = '<div class="tabla-scroll"><table><thead><tr>';
  for (const c of cols) html += `<th>${c}</th>`;
  html += '</tr></thead><tbody>';
  for (const fila of filas) {
    html += '<tr>';
    for (const c of cols) html += `<td>${fila[c] == null ? '' : fila[c]}</td>`;
    html += '</tr>';
  }
  html += '</tbody></table></div>';
  $('#tabla-resultados').innerHTML = html;
}

$('#btn-exportar').onclick = () => { window.location = '/api/resultados/exportar'; };
```

- [ ] **Step 3: Verificación manual**

Con un `cuentas_actualizadas.xlsx` de prueba (puedes copiar/renombrar uno existente o crear uno), abre la sección Estadísticas y verifica tarjetas, las 3 gráficas y la tabla. Prueba "Descargar Excel".

- [ ] **Step 4: Commit**

```bash
git add webapp/static/graficas.js webapp/static/app.js
git commit -m "feat(webapp): sección Estadísticas con gráficas SVG propias"
```

---

### Task 9: Arranque (`iniciar.bat`) + verificación integral

**Files:**
- Create: `iniciar.bat`
- Modify: `README.md` (sección de uso)

**Interfaces:**
- Produces: script de arranque que levanta uvicorn y abre el navegador.

- [ ] **Step 1: Crear `iniciar.bat`**

Create `iniciar.bat` (en la raíz del proyecto):

```bat
@echo off
cd /d "%~dp0"
start "" http://localhost:8000
python -m uvicorn webapp.servidor:app --host 127.0.0.1 --port 8000
```

- [ ] **Step 2: Actualizar `README.md`**

En `README.md`, bajo "Uso", añadir antes de la sección de Streamlit:

```markdown
### Panel web (nuevo, recomendado)

```bash
iniciar.bat        # o: python -m uvicorn webapp.servidor:app --port 8000
```

Abre `http://localhost:8000`. Tres secciones: **Control** (iniciar/detener/continuar +
consola en vivo), **Cuentas** (editar/importar/plantilla/registrar) y **Estadísticas**
(métricas y gráficas). Reemplaza al panel Streamlit (`dashboard.py`, legado).
```

- [ ] **Step 3: Verificación integral (manual)**

1. `cd "D:/Automatizador 2.0" && python -m pytest tests/ -v` → todos PASAN.
2. Doble clic en `iniciar.bat` → abre el navegador en el dashboard.
3. Sección Cuentas: generar plantilla, editar, guardar.
4. Sección Control: con navegador Chrome y una cuenta de prueba, **Iniciar**; verificar consola en vivo con colores, barra de progreso, y que **Continuar** se habilita en el CAPTCHA.
5. Sección Estadísticas: tras una corrida, ver métricas y gráficas.

- [ ] **Step 4: Commit**

```bash
git add iniciar.bat README.md
git commit -m "feat(webapp): arranque iniciar.bat + doc de uso del panel web"
```

---

## Notas de ejecución

- **Orden:** las tareas 1-4 (backend) son independientes del frontend y totalmente testeables; hacerlas primero. Las 5-8 (frontend) dependen de que el backend exista. La 9 cierra.
- **No tocar el motor:** si alguna tarea parece requerir cambiar `main.py`/`control.py`/`procesador_web.py`, detenerse y revisar — el diseño dice que no debe hacer falta.
- **`dashboard.py` (Streamlit)** queda como legado hasta validar la web; no se borra en este plan.
