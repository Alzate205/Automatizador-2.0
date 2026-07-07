// graficas.js — gráficas simples con SVG/CSS puro (sin librerías, sin CDN).
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
    // datos: { etiqueta: valor }; dibuja una dona SVG con leyenda.
    const el = document.getElementById(elId);
    const pares = Object.entries(datos).filter(p => p[1] > 0);
    if (!pares.length) { el.innerHTML = '<p style="color:#8a92a6">Sin datos</p>'; return; }
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
    el.innerHTML = `<div style="display:flex;gap:14px;align-items:center;flex-wrap:wrap">
      <svg width="160" height="160">${segs}</svg><div>${leyenda}</div></div>`;
  },
};
