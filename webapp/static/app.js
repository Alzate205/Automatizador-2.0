const $ = (s) => document.querySelector(s);

const COLUMNAS_SENSIBLES = ['Password', 'ClaveCorreo'];
// Orden de las columnas siguiendo el formulario real de Betplay (los primeros
// 5 son de gestión del bot y no están en el formulario).
const COLUMNAS_BASE = [
  'Modo', 'Nombre', 'Usuario', 'ClaveCorreo', 'Puerto',
  'Cedula',
  'ExpedicionDD', 'ExpedicionMM', 'ExpedicionYYYY',
  'LugarExpedicion',
  'NacimientoDD', 'NacimientoMM', 'NacimientoYYYY',
  'PrimerNombre', 'SegundoNombre', 'PrimerApellido', 'SegundoApellido',
  'Genero', 'Telefono', 'Correo',
  'TipoVia', 'Direccion1', 'Direccion2', 'Direccion3', 'Ciudad',
  'Password',
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
$('#btn-continuar-2').onclick = () => post('/api/continuar');
$('#btn-cancelar-espera').onclick = () => post('/api/cancelar-espera');
$('#btn-forzar').onclick = () => post('/api/forzar-parada');

// Limpiar consola: BORRA bot.log de verdad (para que no vuelva ni al recargar) y
// limpia la vista. Congelamos el índice en un valor enorme para que ningún sondeo
// intermedio vuelva a pegar lo viejo mientras se procesa.
$('#btn-limpiar-consola').onclick = async () => {
  window.__logDesde = Number.MAX_SAFE_INTEGER;  // frena el re-pegado inmediato
  $('#consola').textContent = '';
  try { await post('/api/log/limpiar'); } catch (e) { /* ignorar */ }
  try {
    const r = await (await fetch('/api/log?desde=999999999')).json();
    window.__logDesde = r.total || 0;  // 0 si se truncó; total actual si estaba en uso
  } catch (e) { window.__logDesde = 0; }
};

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
    $('#estado-texto').textContent =
      `${e.estado} — ${e.fase || ''} — ${e.cuenta || ''} (${e.indice || 0}/${e.total || 0})`;
    const pct = e.total ? Math.round((e.indice / e.total) * 100) : 0;
    $('#barra-progreso').style.width = pct + '%';
    const corriendo = e.proceso_vivo || ['corriendo', 'esperando_captcha', 'esperando_apuesta', 'esperando_codigo'].includes(e.estado);
    // 'esperando_codigo' también muestra el banner con Continuar: el usuario puede
    // escribir el código en el NAVEGADOR y pulsar Continuar (o usar la casilla de abajo).
    const esperando = ['esperando_captcha', 'esperando_apuesta', 'esperando_codigo'].includes(e.estado);
    $('#btn-iniciar').disabled = corriendo;
    $('#btn-detener').disabled = !corriendo;
    $('#btn-continuar').disabled = !esperando;

    // Banner de acción: cuando el bot espera al usuario (captcha o revisar apuesta)
    // NO está trabado; mostramos la instrucción del bot y un Continuar visible, para
    // que no parezca colgado. Sin él, el usuario ve 'esperando_captcha' y no sabe qué hacer.
    const accionWrap = $('#accion-wrap');
    if (esperando) {
      $('#accion-msg').textContent = e.mensaje ||
        'Resuelve el CAPTCHA en el navegador (Chrome del bot) y pulsa Continuar.';
      if (accionWrap.hidden) accionWrap.hidden = false;
    } else if (!accionWrap.hidden) {
      accionWrap.hidden = true;
    }

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

function celdaSelect(col, v, opciones) {
  const actual = v.toLowerCase();
  const ops = opciones.map(o => {
    const sel = actual === o.toLowerCase() ? ' selected' : '';
    return `<option value="${escaparHtml(o)}"${sel}>${o || '(elegir)'}</option>`;
  }).join('');
  return `<select data-col="${escaparHtml(col)}">${ops}</select>`;
}

function celda(col, valor, verSensibles) {
  const v = valor == null ? '' : String(valor);
  if (col === 'Modo') return celdaSelect(col, v, ['login', 'registro']);
  if (col === 'Genero') return celdaSelect(col, v, ['', 'Masculino', 'Femenino']);
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
    btn.onclick = () => { btn.closest('tr').remove(); autoguardarCuentas(); };
  });
  // Autoguardado: al salir de una casilla (change = blur con cambio) se guarda
  // solo, por si se recarga la página. No genera respaldo (auto=true).
  $('#tabla-cuentas').querySelectorAll('[data-col]').forEach(inp => {
    inp.addEventListener('change', autoguardarCuentas);
  });
}

async function cargarCuentas() {
  const d = await (await fetch('/api/cuentas')).json();
  const enArchivo = (d.columnas && d.columnas.length) ? d.columnas : [];
  // Mostramos SIEMPRE en el orden del formulario de Betplay (COLUMNAS_BASE), sin
  // importar en qué orden esté guardado el archivo; las columnas extra que traiga
  // el archivo (y no estén en la plantilla) se muestran al final.
  _colsCuentas = COLUMNAS_BASE.slice();
  for (const c of enArchivo) if (!_colsCuentas.includes(c)) _colsCuentas.push(c);
  pintarTabla(d.filas || []);
}

let _autosaveTimer = null;
function autoguardarCuentas() {
  clearTimeout(_autosaveTimer);
  _autosaveTimer = setTimeout(async () => {
    try {
      await post('/api/cuentas', { filas: recogerFilasCuentas(), auto: true });
      $('#estado-cuentas').textContent = 'Guardado automático ✓';
      setTimeout(() => {
        if ($('#estado-cuentas').textContent === 'Guardado automático ✓')
          $('#estado-cuentas').textContent = '';
      }, 2000);
      actualizarContador();
    } catch (e) { /* reintenta en el próximo cambio */ }
  }, 400);
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

// Mismo patrón que exige Betplay (y que valida el bot): mayúscula + dígito + uno
// de . ; , y SOLO letras/dígitos/.;, sin espacios. Ej válido: "Betplay2026."
const RE_PASSWORD_BETPLAY = /^(?=.*[A-Z])(?=.*\d)(?=.*[.;,])[A-Za-z\d.;,]+$/;

function avisosCuentas(filas) {
  const esReg = f => String(f.Modo || 'registro').toLowerCase() === 'registro';
  const idf = f => f.Usuario || f.Correo || f.Cedula || '(sin id)';
  const reg = filas.filter(esReg);
  const sinClave = reg.filter(f => !String(f.ClaveCorreo || '').trim());
  const passMal = reg.filter(f => {
    const p = String(f.Password || '').trim();
    return p && !RE_PASSWORD_BETPLAY.test(p);
  });
  const passVacia = reg.filter(f => !String(f.Password || '').trim());
  const av = [];
  if (sinClave.length) av.push(
    `• ${sinClave.length} cuenta(s) SIN "Clave correo": tendrás que ingresar el CÓDIGO ` +
    `de verificación A MANO. El bot se detiene en el paso del código y espera a que lo ` +
    `escribas en el navegador y pulses Continuar (o lo pongas en la casilla del panel).\n` +
    `    → ${sinClave.map(idf).join(', ')}`);
  if (passMal.length) av.push(
    `• ${passMal.length} cuenta(s) con CONTRASEÑA que NO cumple el formato de Betplay:\n` +
    `    debe tener al menos una MAYÚSCULA, un DÍGITO y uno de . ; ,  y solo letras, ` +
    `dígitos y . ; ,  (sin espacios ni otros símbolos). Ej: "Betplay2026."\n` +
    `    → ${passMal.map(idf).join(', ')}`);
  if (passVacia.length) av.push(`• ${passVacia.length} cuenta(s) de registro SIN contraseña.`);
  return av;
}

$('#btn-guardar-cuentas').onclick = async () => {
  const filas = recogerFilasCuentas();
  const r = await post('/api/cuentas', { filas });
  $('#estado-cuentas').textContent = 'Guardadas: ' + (r.guardadas ?? '?');
  setTimeout(() => { $('#estado-cuentas').textContent = ''; }, 3000);
  actualizarContador();
  const av = avisosCuentas(filas);
  if (av.length) alert('Guardado ✔\n\nTen en cuenta:\n\n' + av.join('\n\n'));
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
