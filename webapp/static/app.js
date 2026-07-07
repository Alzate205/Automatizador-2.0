const $ = (s) => document.querySelector(s);

const COLUMNAS_SENSIBLES = ['Password', 'ClaveCorreo'];
const COLUMNAS_BASE = [
  'Usuario', 'Password', 'Nombre', 'Correo', 'ClaveCorreo', 'Puerto', 'Modo',
  'Cedula', 'PrimerNombre', 'PrimerApellido', 'Telefono',
  'ExpedicionDD', 'ExpedicionMM', 'ExpedicionYYYY',
  'NacimientoDD', 'NacimientoMM', 'NacimientoYYYY', 'LugarExpedicion',
];

function escaparHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;')
    .replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

async function post(url, body) {
  const r = await fetch(url, {
    method: 'POST',
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  return r.json().catch(() => ({}));
}

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

// ============================ SECCIÓN CONTROL ============================

function leerConfig() {
  const tareas = [];
  if ($('#t-bonos').checked) tareas.push('bonos');
  if ($('#t-limite').checked) tareas.push('apuesta_maxima');
  if ($('#t-apbono').checked) tareas.push('apostar_bono');
  if ($('#t-apsaldo').checked) tareas.push('apostar_saldo');
  return {
    filtro_modo: $('#filtro-modo').value,
    usar_gestor: $('#usar-gestor').checked,
    pausa_min: parseFloat($('#pausa-min').value) || 0,
    pausa_max: parseFloat($('#pausa-max').value) || 0,
    tareas,
    apuesta: { modo: $('#monto-modo').value, valor: parseFloat($('#monto-valor').value) || 0 },
    cuentas_seleccionadas: Array.from($('#cuentas-sel').selectedOptions).map(o => o.value),
    rotar_ip: $('#rotar-ip').checked,
    rotar_ip_solo_registro: $('#rotar-solo-reg').checked,
    codigo_manual: $('#codigo-manual').checked,
  };
}

$('#btn-iniciar').onclick = () => {
  window.__logDesde = 0;
  $('#consola').textContent = '';
  post('/api/iniciar', leerConfig());
};
$('#btn-detener').onclick = () => post('/api/detener');
$('#btn-continuar').onclick = () => post('/api/continuar');
$('#btn-forzar').onclick = () => post('/api/forzar-parada');

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
  } catch (e) { /* servidor ocupado; reintenta al próximo tick */ }
}

async function pollEstado() {
  try {
    const e = await (await fetch('/api/estado')).json();
    $('#cabecera-estado').textContent =
      `${e.estado} — ${e.fase || ''} — ${e.cuenta || ''} (${e.indice || 0}/${e.total || 0})`;
    const pct = e.total ? Math.round((e.indice / e.total) * 100) : 0;
    $('#barra-progreso').style.width = pct + '%';
    const corriendo = e.proceso_vivo || ['corriendo', 'esperando_captcha', 'esperando_apuesta', 'esperando_codigo'].includes(e.estado);
    const esperando = ['esperando_captcha', 'esperando_apuesta'].includes(e.estado);
    $('#btn-iniciar').disabled = corriendo;
    $('#btn-detener').disabled = !corriendo;
    $('#btn-continuar').disabled = !esperando;

    // Casilla de código 2FA manual: aparece solo cuando el bot lo pide.
    const pideCodigo = e.estado === 'esperando_codigo';
    const wrap = $('#codigo-wrap');
    if (pideCodigo) {
      if (wrap.hidden) { wrap.hidden = false; $('#codigo-input').focus(); }
      $('#codigo-msg').textContent = e.mensaje || 'El bot espera el código de correo.';
    } else if (!wrap.hidden) {
      wrap.hidden = true;
      $('#codigo-input').value = '';
    }
  } catch (e) { /* ídem */ }
}

async function enviarCodigo() {
  const val = $('#codigo-input').value.trim();
  if (!val) return;
  await post('/api/codigo', { codigo: val });
  $('#codigo-input').value = '';
  $('#codigo-wrap').hidden = true;  // el próximo pollEstado confirma el cambio de estado
}
$('#btn-enviar-codigo').onclick = enviarCodigo;
$('#codigo-input').addEventListener('keydown', (ev) => { if (ev.key === 'Enter') enviarCodigo(); });

async function actualizarContador() {
  try {
    const c = await (await fetch('/api/cuentas')).json();
    $('#contador-cuentas').textContent = (c.filas ? c.filas.length : 0) + ' cuentas cargadas';
    poblarSelectorCuentas(c.filas || []);
  } catch (e) { /* ídem */ }
}

// Rellena el selector "Cuentas a procesar" con el Correo o Usuario de cada fila,
// conservando lo que ya estuviera seleccionado.
function poblarSelectorCuentas(filas) {
  const sel = $('#cuentas-sel');
  if (!sel) return;
  const seleccionadas = new Set(Array.from(sel.selectedOptions).map(o => o.value));
  const ids = [];
  for (const fila of filas) {
    const id = String(fila.Correo || fila.Usuario || '').trim();
    if (id && id.toLowerCase() !== 'nan' && !ids.includes(id)) ids.push(id);
  }
  sel.innerHTML = ids.map(id =>
    `<option value="${escaparHtml(id)}"${seleccionadas.has(id) ? ' selected' : ''}>${escaparHtml(id)}</option>`
  ).join('');
}

// ============================ SECCIÓN CUENTAS ============================

let _colsCuentas = [];

function tipoInput(col, verSensibles) {
  if (COLUMNAS_SENSIBLES.includes(col) && !verSensibles) return 'password';
  return 'text';
}

function celda(col, valor, verSensibles) {
  const v = valor == null ? '' : String(valor);
  if (col === 'Modo') {
    const login = v.toLowerCase() === 'login' ? ' selected' : '';
    const reg = v.toLowerCase() === 'registro' ? ' selected' : '';
    return `<select data-col="${col}"><option value="login"${login}>login</option>` +
      `<option value="registro"${reg}>registro</option></select>`;
  }
  const tipo = tipoInput(col, verSensibles);
  return `<input type="${tipo}" data-col="${col}" value="${escaparHtml(v)}">`;
}

function pintarTabla(filas) {
  const verSensibles = $('#ver-sensibles').checked;
  let html = '<div class="tabla-scroll"><table><thead><tr>';
  for (const c of _colsCuentas) html += `<th>${escaparHtml(c)}</th>`;
  html += '<th></th></tr></thead><tbody>';
  filas.forEach((fila) => {
    html += '<tr>';
    for (const c of _colsCuentas) html += `<td>${celda(c, fila[c], verSensibles)}</td>`;
    html += '<td class="col-borrar"><button class="btn-borrar" title="Borrar fila">✕</button></td>';
    html += '</tr>';
  });
  html += '</tbody></table></div>';
  $('#tabla-cuentas').innerHTML = html;

  $('#tabla-cuentas').querySelectorAll('.btn-borrar').forEach(btn => {
    btn.onclick = () => { btn.closest('tr').remove(); };
  });
}

async function cargarCuentas() {
  const d = await (await fetch('/api/cuentas')).json();
  _colsCuentas = (d.columnas && d.columnas.length) ? d.columnas : COLUMNAS_BASE.slice();
  pintarTabla(d.filas || []);
}

function recogerFilasCuentas() {
  const filas = [];
  $('#tabla-cuentas').querySelectorAll('tbody tr').forEach(tr => {
    const fila = {};
    tr.querySelectorAll('[data-col]').forEach(inp => { fila[inp.dataset.col] = inp.value; });
    filas.push(fila);
  });
  return filas;
}

function filaVacia() {
  const fila = {};
  _colsCuentas.forEach(c => { fila[c] = c === 'Modo' ? 'registro' : ''; });
  return fila;
}

$('#ver-sensibles').onchange = () => pintarTabla(recogerFilasCuentas());

$('#btn-agregar-fila').onclick = () => {
  if (!_colsCuentas.length) _colsCuentas = COLUMNAS_BASE.slice();
  pintarTabla([...recogerFilasCuentas(), filaVacia()]);
};

$('#btn-guardar-cuentas').onclick = async () => {
  const r = await post('/api/cuentas', { filas: recogerFilasCuentas() });
  $('#estado-cuentas').textContent = 'Guardadas: ' + (r.guardadas ?? '?');
  setTimeout(() => { $('#estado-cuentas').textContent = ''; }, 3000);
  actualizarContador();
};

$('#btn-plantilla').onclick = async () => {
  const n = parseInt($('#plantilla-n').value) || 10;
  if (!confirm(`Esto REEMPLAZA la lista actual por una plantilla de ${n} cuenta(s).\n` +
               `Se guarda un respaldo automático antes. ¿Continuar?`)) return;
  await post('/api/cuentas/plantilla', { n });
  cargarCuentas();
  actualizarContador();
};

$('.importar').onclick = () => $('#importar-archivo').click();
$('#importar-archivo').onchange = async (ev) => {
  const f = ev.target.files[0];
  if (!f) return;
  if (!confirm(`Importar "${f.name}" REEMPLAZA toda la lista actual de cuentas.\n` +
               `Se guarda un respaldo automático antes. ¿Continuar?`)) {
    ev.target.value = '';
    return;
  }
  const fd = new FormData();
  fd.append('archivo', f);
  await fetch('/api/cuentas/importar', { method: 'POST', body: fd });
  ev.target.value = '';
  cargarCuentas();
  actualizarContador();
};

$('#btn-exportar-cuentas').onclick = () => { window.location = '/api/cuentas/exportar'; };

// ============================ SECCIÓN ESTADÍSTICAS ============================

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
  for (const c of cols) html += `<th>${escaparHtml(c)}</th>`;
  html += '</tr></thead><tbody>';
  for (const fila of filas) {
    html += '<tr>';
    for (const c of cols) html += `<td>${fila[c] == null ? '' : escaparHtml(fila[c])}</td>`;
    html += '</tr>';
  }
  html += '</tbody></table></div>';
  $('#tabla-resultados').innerHTML = html;
}

$('#btn-exportar').onclick = () => { window.location = '/api/resultados/exportar'; };

// ============================ ARRANQUE ============================

setInterval(pollLog, 1000);
setInterval(pollEstado, 1000);
actualizarContador();
