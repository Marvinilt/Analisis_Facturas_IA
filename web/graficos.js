"use strict";
/* Gráficos SVG sin dependencias: columnas apiladas, barras horizontales y líneas mínimas.
   Los colores salen de variables CSS, así que cambian solos con el tema. */

const Graficos = (() => {
  const NS = "http://www.w3.org/2000/svg";
  const tip = () => document.getElementById("tooltip");
  const escT = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function mostrarTip(html, x, y) {
    const t = tip(); t.innerHTML = html; t.hidden = false;
    const r = t.getBoundingClientRect();
    let left = x + 14, top = y - r.height - 12;
    if (left + r.width > innerWidth - 8) left = x - r.width - 14;
    if (top < 8) top = y + 16;
    t.style.left = `${Math.max(8, left)}px`; t.style.top = `${top}px`;
  }
  const ocultarTip = () => { tip().hidden = true; };

  function el(nombre, attrs = {}, padre) {
    const n = document.createElementNS(NS, nombre);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (padre) padre.appendChild(n);
    return n;
  }

  function escalaBonita(max) {
    if (max <= 0) return { tope: 4, paso: 1 };
    const crudo = max / 4, mag = 10 ** Math.floor(Math.log10(crudo));
    const paso = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((p) => p >= crudo) || 10 * mag;
    return { tope: Math.ceil(max / paso) * paso, paso: Math.max(1, Math.round(paso)) };
  }

  // Rectángulo con las dos esquinas superiores redondeadas (la base queda recta sobre el eje).
  function columna(x, y, w, h, r) {
    r = Math.min(r, w / 2, h);
    if (h <= 0) return "";
    return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
  }

  /* Columnas apiladas por día. series: [{clave, nombre, color}] */
  function columnasApiladas(cont, datos, series, opciones = {}) {
    const dibujar = () => {
      cont.innerHTML = "";
      const total = datos.reduce((s, d) => s + series.reduce((a, se) => a + (d[se.clave] || 0), 0), 0);
      if (!datos.length || !total) {
        cont.innerHTML = `<div class="vacio-g">${opciones.vacio || "Sin datos en este periodo"}</div>`;
        return;
      }
      const W = Math.max(cont.clientWidth, 280), H = opciones.alto || 260;
      const m = { t: 10, r: 6, b: 28, l: 34 };
      const iw = W - m.l - m.r, ih = H - m.t - m.b;
      const maximo = Math.max(...datos.map((d) => series.reduce((a, se) => a + (d[se.clave] || 0), 0)));
      const { tope, paso } = escalaBonita(maximo);
      const y = (v) => m.t + ih - (v / tope) * ih;
      const banda = iw / datos.length;
      const ancho = Math.max(2, Math.min(26, banda * 0.64));
      const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": opciones.titulo || "Gráfico" }, cont);

      const rej = el("g", { class: "rejilla" }, svg);
      for (let v = paso; v <= tope; v += paso) {
        el("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v) }, rej);
        el("text", { x: m.l - 8, y: y(v) + 4, "text-anchor": "end", class: "eje" }, svg).textContent = v;
      }
      el("text", { x: m.l - 8, y: y(0) + 4, "text-anchor": "end", class: "eje" }, svg).textContent = 0;

      // Etiquetas del eje x: como mucho ~8, siempre la primera y la última.
      const cada = Math.max(1, Math.ceil(datos.length / Math.max(2, Math.floor(iw / 70))));
      datos.forEach((d, i) => {
        const cx = m.l + banda * i + banda / 2;
        const g = el("g", { class: "col", tabindex: "-1" }, svg);
        el("rect", { class: "banda", x: m.l + banda * i, y: m.t, width: banda, height: ih, rx: 6 }, g);
        let acumulado = 0;
        const visibles = series.filter((se) => d[se.clave] > 0);
        visibles.forEach((se, j) => {
          const v = d[se.clave];
          const yTop = y(acumulado + v), yBase = y(acumulado);
          const hueco = j > 0 ? 2 : 0; // separación de 2 px entre segmentos
          const alto = Math.max(0, yBase - yTop - hueco);
          const ultimo = j === visibles.length - 1;
          el("path", { d: ultimo ? columna(cx - ancho / 2, yTop, ancho, alto, 4) : `M${cx - ancho / 2},${yTop}h${ancho}v${alto}h${-ancho}Z`,
            style: `fill:${se.color}` }, g);
          acumulado += v;
        });
        if (i % cada === 0 || i === datos.length - 1) {
          if (i === datos.length - 1 && i % cada !== 0 && i % cada < cada / 2) { /* evita choque con la anterior */ }
          else el("text", { x: cx, y: H - 8, "text-anchor": "middle", class: "eje" }, svg).textContent = opciones.etiquetaX ? opciones.etiquetaX(d) : i;
        }
        // Zona de contacto más grande que la marca.
        const hit = el("rect", { x: m.l + banda * i, y: m.t, width: banda, height: ih + m.b, fill: "transparent" }, g);
        hit.addEventListener("mousemove", (ev) => {
          const filas = series.map((se) => `<div class="fila"><span><i style="background:${se.color}"></i>${escT(se.nombre)}</span><em>${d[se.clave] || 0}</em></div>`).join("");
          mostrarTip(`<b>${escT(opciones.titulo_tip ? opciones.titulo_tip(d) : "")}</b>${filas}`, ev.clientX, ev.clientY);
          g.classList.add("activa");
        });
        hit.addEventListener("mouseleave", () => { ocultarTip(); g.classList.remove("activa"); });
      });
      el("line", { x1: m.l, x2: W - m.r, y1: y(0), y2: y(0), class: "base" }, svg);
    };
    dibujar();
    observar(cont, dibujar);
  }

  /* Barras horizontales ordenadas (HTML, se adaptan solas al ancho). */
  function barrasH(cont, items, opciones = {}) {
    if (!items.length) { cont.innerHTML = `<div class="vacio-g">${opciones.vacio || "Sin datos"}</div>`; return; }
    const max = Math.max(...items.map((x) => x.valor));
    const total = items.reduce((s, x) => s + x.valor, 0);
    cont.innerHTML = `<div class="barras-h">${items.map((x) => `
      <div class="barra-h" data-tip="${escT(x.etiqueta)}|${x.valor}|${Math.round((100 * x.valor) / total)}">
        <div class="barra-h-t"><span>${escT(x.etiqueta)}</span><b>${x.valor}<small>${Math.round((100 * x.valor) / total)} %</small></b></div>
        <div class="pista"><i style="width:0%;${opciones.color ? `background:${opciones.color}` : ""}" data-w="${(100 * x.valor) / max}"></i></div>
      </div>`).join("")}</div>`;
    requestAnimationFrame(() => cont.querySelectorAll(".pista i").forEach((i) => (i.style.width = `${i.dataset.w}%`)));
    cont.querySelectorAll(".barra-h").forEach((b) => {
      b.addEventListener("mousemove", (ev) => {
        const [n, v, p] = b.dataset.tip.split("|");
        mostrarTip(`<b>${escT(n)}</b><div class="fila"><span>Facturas</span><em>${v}</em></div><div class="fila"><span>Del total en revisión</span><em>${p} %</em></div>`, ev.clientX, ev.clientY);
      });
      b.addEventListener("mouseleave", ocultarTip);
    });
  }

  /* Línea mínima para las tarjetas de indicadores. */
  function chispa(cont, valores, color) {
    if (!valores.length || valores.every((v) => !v)) { cont.innerHTML = ""; return; }
    const W = 200, H = 30, max = Math.max(...valores, 1);
    const pts = valores.map((v, i) => [valores.length === 1 ? W : (i / (valores.length - 1)) * W, H - 3 - (v / max) * (H - 6)]);
    const linea = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("");
    cont.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
      <path d="${linea}L${W},${H}L0,${H}Z" style="fill:${color};opacity:.12"/>
      <path d="${linea}" style="fill:none;stroke:${color};stroke-width:2;stroke-linejoin:round;stroke-linecap:round" vector-effect="non-scaling-stroke"/></svg>`;
  }

  const observados = new WeakMap();
  function observar(cont, fn) {
    if (!("ResizeObserver" in window)) return;
    observados.get(cont)?.disconnect();
    let ancho = cont.clientWidth, t;
    const ro = new ResizeObserver(() => {
      if (Math.abs(cont.clientWidth - ancho) < 4) return;
      ancho = cont.clientWidth; clearTimeout(t); t = setTimeout(fn, 60);
    });
    ro.observe(cont); observados.set(cont, ro);
  }

  return { columnasApiladas, barrasH, chispa, mostrarTip, ocultarTip };
})();
