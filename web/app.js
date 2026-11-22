"use strict";
/* Facturas IA — frontend sin dependencias. */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const dinero = (v) => (v === null || v === undefined || v === "" ? "—" : Number(v).toLocaleString("es", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const hora = (iso) => (iso ? new Date(iso).toLocaleString("es", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—");
const ESTADOS = { procesada: "Procesada", revision: "Revisión manual", pendiente: "Pendiente", en_proceso: "En proceso",
  escrita: "Registrada, sin mover", revision_sin_mover: "A revisión, sin mover", completada: "Completada",
  detenida: "Detenida", error: "Error", cancelada: "Cancelada", "en curso": "En curso" };

async function api(ruta, opciones = {}) {
  const r = await fetch(ruta, { headers: opciones.body && !(opciones.body instanceof FormData) ? { "Content-Type": "application/json" } : {}, ...opciones });
  let datos = null;
  try { datos = await r.json(); } catch { /* sin cuerpo */ }
  if (!r.ok) {
    const det = datos?.detail;
    const msg = det?.errores ? det.errores.join(" · ") : typeof det === "string" ? det : `Error ${r.status}`;
    const e = new Error(msg); e.errores = det?.errores; throw e;
  }
  return datos;
}

function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg; t.className = "toast" + (err ? " err" : ""); t.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => (t.hidden = true), err ? 6000 : 3000);
}

/* ── pestañas ─────────────────────────────────────────── */
let tabActual = "panel";
function abrirTab(tab) {
  tabActual = tab;
  $$(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
  $$(".tab").forEach((s) => (s.hidden = s.id !== `tab-${tab}`));
  if (tab === "facturas") cargarFacturas();
  if (tab === "config") abrirConfig(cfgActual);
  try { localStorage.setItem("tab", tab); } catch { /* sin almacenamiento */ }
}
$$(".tabs button").forEach((b) => b.addEventListener("click", () => abrirTab(b.dataset.tab)));

/* ── panel ────────────────────────────────────────────── */
let config = null;
let ultimoEstado = null;

async function refrescarEstado() {
  let e;
  try { e = await api("/api/estado"); } catch { $("#estadoRun").textContent = "Servidor sin respuesta"; return; }
  ultimoEstado = e;
  const s = e.servicio, c = e.contadores || {};
  const run = $("#estadoRun");
  run.className = "estado-run" + (s.corriendo ? " activo" : e.alertas.some((a) => a.clave === "modelos") ? " detenido" : "");
  run.textContent = s.corriendo ? `${s.paso || "Procesando"}${s.archivo ? " · " + s.archivo : ""}`
    : s.programado ? `En espera · próxima revisión ${hora(s.proxima)}` : "En espera · revisión automática apagada";
  $("#bProcesar").disabled = s.corriendo;
  $("#bDetener").hidden = !s.corriendo;
  $("#bDetener").disabled = s.deteniendo;

  $("#cPend").textContent = c.pendientes ?? "—";
  $("#cProc").textContent = c.procesadas ?? "—";
  $("#cRev").textContent = c.revision ?? "—";
  $("#cIgn").textContent = c.ignorados ? `${c.ignorados} archivo(s) de otro tipo se ignoran` : "PDF, JPG, PNG o WEBP";
  $("#cAct").textContent = c.actualizado ? `Conteo del ${hora(c.actualizado)}` : "Sin conteo todavía";
  const l = $("#lHoja");
  if (c.resultados) {
    l.textContent = config?.drive.archivo_resultados || "Abrir"; l.href = c.resultados.startsWith("http") ? c.resultados : "#";
    l.title = c.resultados;
  }

  $("#alertas").innerHTML = e.alertas.map((a) => `<div class="alerta ${a.nivel === "aviso" ? "aviso" : ""}">
      <div><b>${a.clave === "modelos" ? "Proceso detenido" : a.clave === "drive" ? "Google Drive" : "Aviso"}</b> · ${esc(a.mensaje)}
      <div class="muted" style="font-size:12px">${hora(a.ts)}</div></div>
      <button class="btn sm ghost" data-cerrar="${a.id}">Descartar</button></div>`).join("");

  const u = e.ultima_corrida;
  $("#procesoInfo").innerHTML = (s.corriendo ? `<div class="paso-actual"><b>${esc(s.paso || "Iniciando")}</b>${esc(s.archivo || "")}</div>` : "") + `
    <div class="fila"><span>Revisión automática</span><span>${s.programado ? `cada ${config?.frecuencia.cada_minutos ?? "?"} min · próxima ${hora(s.proxima)}` : "apagada"}</span></div>
    <div class="fila"><span>Última corrida</span><span>${u ? `${hora(u.inicio)} · <span class="pill ${esc(u.estado)}">${esc(ESTADOS[u.estado] || u.estado)}</span>` : "—"}</span></div>
    ${u?.detalle ? `<div class="muted" style="font-size:13px">${esc(u.detalle)}</div>` : ""}
    <div class="fila"><span>Facturas en el registro</span><span>${Object.entries(e.por_estado).map(([k, v]) => `${v} ${ESTADOS[k]?.toLowerCase() || k}`).join(" · ") || "ninguna"}</span></div>`;

  if (tabActual === "panel") await refrescarCorridas(u);
}

let corridaMostrada = null, eventosMostrados = 0;
async function refrescarCorridas(u) {
  const cs = await api("/api/corridas?limite=8");
  $("#tCorridas tbody").innerHTML = cs.length ? cs.map((c) => `<tr><td>${hora(c.inicio)}</td><td>${esc(c.origen)}</td>
      <td><span class="pill ${esc(c.estado)}">${esc(ESTADOS[c.estado] || c.estado)}</span></td>
      <td class="n">${c.encontrados ?? 0}</td><td class="n">${c.procesadas ?? 0}</td><td class="n">${c.revision ?? 0}</td></tr>`).join("")
    : `<tr><td colspan="6" class="vacio">Sin corridas todavía</td></tr>`;
  if (!u) { $("#bitacora").innerHTML = ""; return; }
  const ev = await api(`/api/eventos?corrida_id=${u.id}`);
  if (corridaMostrada === u.id && eventosMostrados === ev.length) return;
  corridaMostrada = u.id; eventosMostrados = ev.length;
  $("#bitInfo").textContent = `Corrida #${u.id} · ${ev.length} evento(s)`;
  const lista = $("#bitacora");
  lista.innerHTML = ev.map((x) => `<li class="${esc(x.nivel)}"><span class="ts">${new Date(x.ts).toLocaleTimeString("es")}</span>
      <span class="ps">${esc(x.paso)}</span><span class="msg">${esc(x.mensaje)}</span></li>`).join("");
  lista.scrollTop = lista.scrollHeight;
}

$("#alertas").addEventListener("click", async (ev) => {
  const b = ev.target.closest("[data-cerrar]"); if (!b) return;
  await api(`/api/alertas/${b.dataset.cerrar}/cerrar`, { method: "POST" }); refrescarEstado();
});
$("#bProcesar").addEventListener("click", async () => {
  try { await api("/api/procesar", { method: "POST" }); toast("Corrida iniciada"); } catch (e) { toast(e.message, true); }
  refrescarEstado();
});
$("#bDetener").addEventListener("click", async () => { await api("/api/detener", { method: "POST" }); toast("Se detendrá al terminar la factura actual"); refrescarEstado(); });
$("#bContar").addEventListener("click", async (ev) => {
  ev.target.disabled = true;
  try { const r = await api("/api/probar/drive", { method: "POST" }); r.ok ? toast("Conteo actualizado") : toast(r.error, true); }
  finally { ev.target.disabled = false; refrescarEstado(); }
});

/* ── facturas ─────────────────────────────────────────── */
let filtro = "";
async function cargarFacturas() {
  const filas = await api(`/api/archivos${filtro ? "?estado=" + filtro : ""}`);
  $("#tFacturas tbody").innerHTML = filas.length ? filas.map((f) => `<tr class="click" data-id="${esc(f.file_id)}">
      <td>${esc(f.nombre)}</td><td><span class="pill ${esc(f.estado)}">${esc(ESTADOS[f.estado] || f.estado)}</span></td>
      <td>${esc(f.numero_factura || "—")}</td><td>${esc(f.emisor || "—")}</td>
      <td class="n">${dinero(f.total)}</td><td class="n">${dinero(f.total_catalogo)}</td>
      <td>${esc(f.modelo || (f.estado === "revision" ? (f.motivo || "").slice(0, 60) : "—"))}</td><td>${hora(f.actualizado)}</td></tr>`).join("")
    : `<tr><td colspan="8" class="vacio">No hay facturas con este estado.</td></tr>`;
}
$$(".filtros .chip").forEach((b) => b.addEventListener("click", () => {
  filtro = b.dataset.f; $$(".filtros .chip").forEach((x) => x.classList.toggle("on", x === b)); cargarFacturas();
}));
$("#tFacturas").addEventListener("click", (ev) => { const tr = ev.target.closest("tr[data-id]"); if (tr) abrirFactura(tr.dataset.id); });

async function abrirFactura(id) {
  const f = await api(`/api/archivos/${encodeURIComponent(id)}`);
  const d = f.datos_json || {}, r = f.resultado_json || {}, ev = r.evaluacion || {}, cat = r.catalogo;
  $("#dTitulo").textContent = f.nombre;
  const escalares = Object.entries(d).filter(([, v]) => typeof v !== "object" || v === null);
  const lineas = Array.isArray(d.lineas) ? d.lineas : [];
  const marcas = cat?.lineas || [];
  $("#dCuerpo").innerHTML = `
    <div class="card"><div class="card-h"><span class="pill ${esc(f.estado)}">${esc(ESTADOS[f.estado] || f.estado)}</span>
      ${f.enlace?.startsWith("http") ? `<a href="${esc(f.enlace)}" target="_blank" rel="noopener">Abrir archivo en Drive ↗</a>` : ""}</div>
      ${f.motivo ? `<p class="${f.estado === "procesada" ? "muted" : ""}" style="margin:0">${esc(f.motivo)}</p>` : ""}
      ${f.modelo ? `<p class="muted" style="margin:6px 0 0">Leída con ${esc(f.modelo)} · ${f.intentos} intento(s)</p>` : ""}</div>
    ${escalares.length ? `<div class="card"><h3>Datos extraídos</h3><div class="kv" style="margin-top:10px">${escalares.map(([k, v]) =>
      `<div><span>${esc(k)}</span>${typeof v === "number" ? dinero(v) : esc(v ?? "—")}</div>`).join("")}
      ${cat ? `<div><span>total_catalogo</span><b class="hit">${dinero(cat.total_catalogo)}</b></div>` : ""}</div></div>` : ""}
    ${lineas.length ? `<div class="card"><h3>Líneas${cat ? ` · ${cat.lineas_catalogo} de ${cat.lineas_total} en el catálogo` : ""}</h3>
      <div class="tabla-wrap"><table class="tabla"><thead><tr><th>#</th><th>Descripción</th><th class="n">Cant.</th><th class="n">P. unit.</th><th class="n">Importe</th><th>Catálogo</th></tr></thead><tbody>
      ${lineas.map((l, i) => { const m = marcas[i]; return `<tr><td>${i + 1}</td><td>${esc(l.descripcion)}</td><td class="n">${esc(l.cantidad)}</td>
        <td class="n">${dinero(l.precio_unitario)}</td><td class="n">${dinero(l.importe)}</td>
        <td>${m?.producto ? `<span class="hit">${esc(m.producto)}</span> <span class="muted">${esc(m.coincidencia)}</span>` : "—"}</td></tr>`; }).join("")}
      </tbody></table></div></div>` : ""}
    ${ev.reglas?.length || ev.errores_esquema?.length ? `<div class="card"><h3>Validación</h3><div style="display:grid;gap:6px;margin-top:10px">
      ${(ev.errores_esquema || []).map((x) => `<div class="regla"><span class="no">✗</span>${esc(x)}</div>`).join("")}
      ${(ev.reglas || []).map((x) => `<div class="regla"><span class="${x.ok ? "si" : "no"}">${x.ok ? "✓" : "✗"}</span><span>${esc(x.regla)}${x.ok ? "" : ` — ${esc(x.detalle)}`}</span></div>`).join("")}
      </div></div>` : ""}
    ${r.historial?.length ? `<div class="card"><h3>Intentos</h3><div class="tabla-wrap"><table class="tabla"><thead><tr><th>#</th><th>Modelo</th><th>Resultado</th><th class="n">Seg.</th><th>Motivo</th></tr></thead><tbody>
      ${r.historial.map((h) => `<tr><td>${h.intento}</td><td>${esc(h.modelo)}</td><td>${esc(h.resultado)}</td><td class="n">${h.segundos ?? "—"}</td><td>${esc(h.resultado === "válida" ? "" : h.motivo)}</td></tr>`).join("")}
      </tbody></table></div></div>` : ""}
    ${r.texto_ocr ? `<div class="card"><details><summary>Texto reconocido (OCR)</summary><pre class="bloque" style="margin-top:10px">${esc(r.texto_ocr)}</pre></details></div>` : ""}
    <div class="card"><h3>Bitácora</h3><ol class="bitacora" style="margin-top:8px">${f.eventos.map((x) => `<li class="${esc(x.nivel)}"><span class="ts">${new Date(x.ts).toLocaleTimeString("es")}</span><span class="ps">${esc(x.paso)}</span><span class="msg">${esc(x.mensaje)}</span></li>`).join("")}</ol></div>`;
  $("#drawer").hidden = false;
}
$("#dCerrar").addEventListener("click", () => ($("#drawer").hidden = true));
$("#drawer").addEventListener("click", (e) => { if (e.target.id === "drawer") $("#drawer").hidden = true; });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("#drawer").hidden = true; });

/* ── configuración ────────────────────────────────────── */
let cfgActual = "conexion";
$("#cnav").addEventListener("click", (e) => { const b = e.target.closest("button[data-c]"); if (b) abrirConfig(b.dataset.c); });

async function cargarConfig() {
  const r = await api("/api/config");
  config = r.config; config._defecto = r.defecto;
  $("#nEntrada").textContent = config.drive.carpeta_entrada;
  $("#nProc").textContent = config.drive.carpeta_procesadas;
  $("#nRev").textContent = config.drive.carpeta_revision;
}

async function guardarSeccion(seccion, valor, mensaje = "Guardado") {
  const caja = $("#cErrores");
  try {
    const r = await api(`/api/config/${seccion}`, { method: "PUT", body: JSON.stringify(valor) });
    const def = config._defecto; config = r.config; config._defecto = def;
    if (caja) caja.hidden = true;
    toast(mensaje); await cargarConfig(); return true;
  } catch (e) {
    if (caja) { caja.hidden = false; caja.innerHTML = `<b>No se guardó:</b><ul>${(e.errores || [e.message]).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`; }
    else toast(e.message, true);
    return false;
  }
}

const VISTAS = {};
function abrirConfig(c) {
  cfgActual = c;
  $$("#cnav button").forEach((b) => b.classList.toggle("on", b.dataset.c === c));
  if (!config) return;
  // Panel nuevo en cada vista: así no se acumulan listeners de vistas anteriores.
  const viejo = $("#cpanel"), p = viejo.cloneNode(false);
  viejo.replaceWith(p);
  VISTAS[c](p);
}
const errBox = `<div class="errores" id="cErrores" hidden></div>`;
const val = (id) => $("#" + id).value.trim();
const num = (id) => Number($("#" + id).value);
const chk = (id) => $("#" + id).checked;

async function bloqueSecreto(nombre, etiqueta, ayuda) {
  const s = (await api("/api/secretos"))[nombre];
  return `<div class="secreto">
    <label class="campo">${esc(etiqueta)} <small>${ayuda}</small>
      <input type="password" id="s_${nombre}" placeholder="${s.configurada ? "••••••••" + esc(s.final) + " (déjalo vacío para mantenerla)" : "Pega la clave aquí"}" autocomplete="off"></label>
    <button class="btn" data-guardar-secreto="${nombre}" type="button">Guardar clave</button>
    <span class="estado-clave ${s.configurada ? "si" : ""}">${s.configurada ? `Configurada desde ${s.origen === "app" ? "esta app (cifrada)" : "el archivo .env"} · termina en ${esc(s.final)}` : "Sin configurar"}</span>
  </div>`;
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-guardar-secreto]"); if (!b) return;
  const n = b.dataset.guardarSecreto, v = $("#s_" + n).value.trim();
  if (!v) return toast("Escribe la clave primero", true);
  await api(`/api/secretos/${n}`, { method: "PUT", body: JSON.stringify({ valor: v }) });
  toast("Clave guardada cifrada en el servidor"); abrirConfig(cfgActual);
});

VISTAS.conexion = async (p) => {
  const d = config.drive;
  const secreto = await bloqueSecreto("composio_api_key", "API key de Composio Connect", "Prefijo ck_. Las cuentas de Google se conectan en composio.dev.");
  if (!p.isConnected) return; // el usuario ya cambió de sección
  p.innerHTML = `<div><h2>Conexión con Google Drive</h2><p class="intro">El sistema usa Composio Connect para leer, mover archivos y escribir la hoja con tu cuenta de Google.
    Solo trabaja dentro de la carpeta «${esc(d.carpeta_entrada)}» y sus subcarpetas.</p></div>${errBox}
    <div class="campos"><label class="campo">Origen de las facturas
      <select id="d_prov"><option value="composio">Google Drive (Composio)</option><option value="local">Carpeta local (pruebas)</option></select></label>
      <label class="campo" id="w_local">Carpeta local <small>Solo en modo local. La carpeta «${esc(d.carpeta_entrada)}» va dentro.</small><input type="text" id="d_local" value="${esc(d.carpeta_local)}"></label></div>
    ${secreto}
    <div class="acciones"><button class="btn primario" id="bGuardarCx">Guardar</button><button class="btn" id="bProbarCx">Probar conexión</button><span class="muted" id="cxEstado"></span></div>
    <div id="cxRes"></div>`;
  $("#d_prov").value = d.proveedor;
  const vis = () => ($("#w_local").hidden = $("#d_prov").value !== "local"); vis(); $("#d_prov").onchange = vis;
  $("#bGuardarCx").onclick = () => guardarSeccion("drive", { ...config.drive, proveedor: $("#d_prov").value, carpeta_local: val("d_local") });
  $("#bProbarCx").onclick = async () => {
    $("#cxEstado").textContent = "Probando…"; $("#cxRes").innerHTML = "";
    const r = await api("/api/probar/drive", { method: "POST" });
    $("#cxEstado").textContent = "";
    $("#cxRes").innerHTML = r.ok ? `<div class="ok-box"><b>Conexión correcta</b>
        ${r.cuentas ? Object.entries(r.cuentas).map(([k, v]) => `<span>${k === "googledrive" ? "Google Drive" : "Google Sheets"}: ${esc(v.estado)} · ${esc(v.cuenta || "")}</span>`).join("") : ""}
        <span>Carpeta «${esc(r.carpeta)}»: ${r.conteo.pendientes} pendiente(s), ${r.conteo.procesadas} procesada(s), ${r.conteo.revision} en revisión.</span>
        ${r.info.creadas?.length ? `<span>Se crearon: ${esc(r.info.creadas.join(", "))}</span>` : ""}
        <span>Resultados: ${r.resultados?.startsWith("http") ? `<a href="${esc(r.resultados)}" target="_blank" rel="noopener">${esc(config.drive.archivo_resultados)} ↗</a>` : esc(r.resultados)}</span></div>`
      : `<div class="errores"><b>No se pudo conectar:</b> ${esc(r.error)}</div>`;
    refrescarEstado();
  };
};

VISTAS.carpetas = (p) => {
  const d = config.drive;
  p.innerHTML = `<div><h2>Carpetas y archivo de resultados</h2><p class="intro">Nombres dentro de tu Google Drive. Las subcarpetas y la hoja se crean dentro de la carpeta de entrada si no existen.</p></div>${errBox}
    <div class="campos">
      <label class="campo">Carpeta de entrada <small>Donde subes las facturas</small><input type="text" id="c_ent" value="${esc(d.carpeta_entrada)}"></label>
      <label class="campo">Subcarpeta de procesadas<input type="text" id="c_proc" value="${esc(d.carpeta_procesadas)}"></label>
      <label class="campo">Subcarpeta de revisión manual<input type="text" id="c_rev" value="${esc(d.carpeta_revision)}"></label>
      <label class="campo">Hoja de resultados <small>Google Sheets dentro de la carpeta de entrada</small><input type="text" id="c_res" value="${esc(d.archivo_resultados)}"></label>
    </div>
    <label class="check"><input type="checkbox" id="c_ren" ${d.renombrar_al_mover ? "checked" : ""}> Renombrar al mover a Procesadas (AAAA-MM-DD_Emisor_Número)</label>
    <div class="acciones"><button class="btn primario" id="bG">Guardar</button></div>`;
  $("#bG").onclick = () => guardarSeccion("drive", { ...config.drive, carpeta_entrada: val("c_ent"), carpeta_procesadas: val("c_proc"),
    carpeta_revision: val("c_rev"), archivo_resultados: val("c_res"), renombrar_al_mover: chk("c_ren") });
};

VISTAS.frecuencia = (p) => {
  const f = config.frecuencia;
  p.innerHTML = `<div><h2>Frecuencia</h2><p class="intro">Cada cuánto se revisa la carpeta. «Procesar ahora» funciona aunque la revisión automática esté apagada.</p></div>${errBox}
    <label class="check"><input type="checkbox" id="f_act" ${f.activo ? "checked" : ""}> Revisar la carpeta automáticamente</label>
    <div class="campos">
      <label class="campo">Revisar cada (minutos)<input type="number" min="1" id="f_min" value="${f.cada_minutos}"></label>
      <label class="campo">Desde<input type="time" id="f_ini" value="${esc(f.hora_inicio)}"></label>
      <label class="campo">Hasta<input type="time" id="f_fin" value="${esc(f.hora_fin)}"></label>
      <label class="campo">Máximo de facturas por corrida<input type="number" min="1" id="f_max" value="${f.max_por_corrida}"></label>
    </div><div class="acciones"><button class="btn primario" id="bG">Guardar</button></div>`;
  $("#bG").onclick = () => guardarSeccion("frecuencia", { activo: chk("f_act"), cada_minutos: num("f_min"), hora_inicio: val("f_ini"),
    hora_fin: val("f_fin"), max_por_corrida: num("f_max") });
};

VISTAS.modelos = async (p) => {
  const m = structuredClone(config.modelos);
  const ollama = await api("/api/modelos/ollama").catch(() => ({ ok: false }));
  const secreto = await bloqueSecreto("openai_api_key", "API key de OpenAI", "Se usa para el estructurador y el modelo de respaldo.");
  if (!p.isConnected) return; // el usuario ya cambió de sección
  const pinta = () => {
    $("#mLista").innerHTML = m.cadena.map((x, i) => `<div class="modelo ${x.activo ? "" : "inactivo"}" data-i="${i}">
      <div class="modelo-h"><span class="orden">${i === 0 ? "Primario" : "Respaldo " + i}</span><b>${esc(x.nombre)}</b>
        <label class="check"><input type="checkbox" data-k="activo" ${x.activo ? "checked" : ""}> Activo</label>
        <button class="btn sm ghost" data-mov="-1" ${i === 0 ? "disabled" : ""}>↑</button><button class="btn sm ghost" data-mov="1" ${i === m.cadena.length - 1 ? "disabled" : ""}>↓</button>
        <button class="btn sm ghost peligro" data-quitar>Quitar</button></div>
      <div class="campos">
        <label class="campo">Nombre<input type="text" data-k="nombre" value="${esc(x.nombre)}"></label>
        ${x.tipo === "glm_ocr" ? `
        <label class="campo">URL de Ollama<input type="text" data-k="ollama_url" value="${esc(x.ollama_url)}"></label>
        <label class="campo">Modelo OCR <small>${ollama.ok ? "Instalados: " + esc(ollama.modelos.join(", ")) : "Ollama no responde"}</small><input type="text" data-k="modelo" value="${esc(x.modelo)}"></label>
        <label class="campo">Lado máximo de imagen (px) <small>Menos px = más rápido en CPU</small><input type="number" data-k="lado_maximo_px" value="${x.lado_maximo_px}"></label>
        <label class="campo">Estructurador <small>Convierte el texto OCR al JSON</small><select data-k="estructurador">
          <option value="openai" ${x.estructurador === "openai" ? "selected" : ""}>OpenAI (texto, recomendado)</option>
          <option value="glm_ocr_json" ${x.estructurador === "glm_ocr_json" ? "selected" : ""}>GLM-OCR directo (100 % local)</option></select></label>
        <label class="campo">Modelo estructurador<input type="text" data-k="modelo_estructurador" value="${esc(x.modelo_estructurador)}"></label>
        <label class="check"><input type="checkbox" data-k="usar_texto_pdf" ${x.usar_texto_pdf ? "checked" : ""}> Usar el texto del PDF cuando exista</label>` : `
        <label class="campo">Modelo de OpenAI con visión<input type="text" data-k="modelo" value="${esc(x.modelo)}"></label>
        <label class="campo">Detalle de imagen<select data-k="detalle_imagen"><option value="high" ${x.detalle_imagen === "high" ? "selected" : ""}>Alto</option><option value="auto" ${x.detalle_imagen === "auto" ? "selected" : ""}>Automático</option><option value="low" ${x.detalle_imagen === "low" ? "selected" : ""}>Bajo</option></select></label>`}
      </div></div>`).join("");
  };
  p.innerHTML = `<div><h2>Modelos y API keys</h2><p class="intro">La cadena va en orden: el primario intenta primero. Si sus datos no pasan la validación, la factura pasa al siguiente modelo con una pista del error.
    Si ningún modelo responde (caída, sin saldo, clave inválida), el proceso se detiene y la factura queda pendiente.</p></div>${errBox}
    <div id="mLista" style="display:grid;gap:12px"></div>
    <div class="acciones" style="border:0;padding:0"><button class="btn" id="mAddO">Agregar modelo OpenAI</button><button class="btn" id="mAddG">Agregar GLM-OCR</button></div>
    <div class="campos">
      <label class="campo">Intentos de extracción por factura<input type="number" min="1" id="m_int" value="${m.intentos_maximos}"></label>
      <label class="campo">Reintentos por error técnico <small>Por modelo, con espera</small><input type="number" min="0" id="m_ret" value="${m.reintentos_tecnicos}"></label>
      <label class="campo">Tiempo máximo por llamada (s)<input type="number" min="10" id="m_to" value="${m.timeout_segundos}"></label>
    </div>
    ${secreto}
    <div class="acciones"><button class="btn primario" id="bG">Guardar modelos</button></div>`;
  pinta();
  const lista = $("#mLista");
  lista.addEventListener("input", (e) => {
    const card = e.target.closest("[data-i]"), k = e.target.dataset.k; if (!card || !k) return;
    const x = m.cadena[card.dataset.i];
    x[k] = e.target.type === "checkbox" ? e.target.checked : e.target.type === "number" ? Number(e.target.value) : e.target.value;
    if (k === "activo") card.classList.toggle("inactivo", !e.target.checked);
  });
  lista.addEventListener("click", (e) => {
    const card = e.target.closest("[data-i]"); if (!card) return; const i = Number(card.dataset.i);
    if (e.target.dataset.mov) { const j = i + Number(e.target.dataset.mov); [m.cadena[i], m.cadena[j]] = [m.cadena[j], m.cadena[i]]; pinta(); }
    if (e.target.hasAttribute("data-quitar")) { m.cadena.splice(i, 1); pinta(); }
  });
  const nuevoId = (b) => { let n = 1; while (m.cadena.some((x) => x.id === `${b}-${n}`)) n++; return `${b}-${n}`; };
  $("#mAddO").onclick = () => { m.cadena.push({ id: nuevoId("openai"), nombre: "OpenAI visión", tipo: "openai", activo: true, modelo: "gpt-5.4-mini", detalle_imagen: "high" }); pinta(); };
  $("#mAddG").onclick = () => { m.cadena.push({ ...structuredClone(config._defecto.modelos.cadena[0]), id: nuevoId("glm") }); pinta(); };
  $("#bG").onclick = () => guardarSeccion("modelos", { ...m, intentos_maximos: num("m_int"), reintentos_tecnicos: num("m_ret"), timeout_segundos: num("m_to") });
};

/* Esquema: editor por tablas + JSON */
const TIPOS = { string: "Texto", number: "Número", date: "Fecha", integer: "Entero" };
function filasEsquema(props, req) {
  return Object.entries(props).map(([k, v]) => ({ nombre: k, tipo: v.format === "date" ? "date" : v.type, obligatorio: req.includes(k), descripcion: v.description || "", extra: v }));
}
function aPropiedad(f) {
  const base = { ...(f.extra || {}) };
  delete base.format;
  base.type = f.tipo === "date" ? "string" : f.tipo;
  if (f.tipo === "date") base.format = "date";
  if (f.descripcion) base.description = f.descripcion; else delete base.description;
  return base;
}
VISTAS.esquema = (p) => {
  const esq = structuredClone(config.esquema);
  const campoLineas = config.validacion.campos.lineas;
  const lin = esq.properties[campoLineas] || { type: "array", items: { type: "object", properties: {}, required: [] } };
  let cab = filasEsquema(Object.fromEntries(Object.entries(esq.properties).filter(([k]) => k !== campoLineas)), esq.required || []);
  let det = filasEsquema(lin.items.properties, lin.items.required || []);
  const tabla = (filas, id) => `<div class="tabla-wrap"><table class="tabla edit" id="${id}"><thead><tr><th>Campo</th><th>Tipo</th><th>Obligatorio</th><th>Indicación para el modelo</th><th></th></tr></thead><tbody>
    ${filas.map((f, i) => `<tr data-i="${i}"><td><input type="text" data-k="nombre" value="${esc(f.nombre)}"></td>
      <td><select data-k="tipo">${Object.entries(TIPOS).map(([v, t]) => `<option value="${v}" ${f.tipo === v ? "selected" : ""}>${t}</option>`).join("")}</select></td>
      <td style="text-align:center"><input type="checkbox" data-k="obligatorio" ${f.obligatorio ? "checked" : ""}></td>
      <td><input type="text" data-k="descripcion" value="${esc(f.descripcion)}"></td><td><button class="btn sm ghost peligro" data-quitar>Quitar</button></td></tr>`).join("")}
    </tbody></table></div><button class="btn sm" data-agregar="${id}" style="margin-top:8px">Agregar campo</button>`;
  const construir = () => {
    const props = {}; cab.forEach((f) => { if (f.nombre) props[f.nombre] = aPropiedad(f); });
    const lp = {}; det.forEach((f) => { if (f.nombre) lp[f.nombre] = aPropiedad(f); });
    props[campoLineas] = { ...lin, items: { ...lin.items, type: "object", properties: lp, required: det.filter((f) => f.obligatorio && f.nombre).map((f) => f.nombre) } };
    return { ...esq, properties: props, required: [...cab.filter((f) => f.obligatorio && f.nombre).map((f) => f.nombre), campoLineas] };
  };
  const pinta = () => {
    $("#wCab").innerHTML = tabla(cab, "tCab"); $("#wDet").innerHTML = tabla(det, "tDet");
  };
  p.innerHTML = `<div><h2>Esquema de factura</h2><p class="intro">Datos que se extraen de cada factura. El esquema alimenta las instrucciones del modelo, la validación del paso 07 y las columnas de la hoja. Los campos de la hoja Facturas siguen el orden de esta tabla.</p></div>${errBox}
    <div><h3>Campos de la factura</h3><div id="wCab" style="margin-top:8px"><table id="tCab"></table></div></div>
    <div><h3>Campos de cada línea («${esc(campoLineas)}»)</h3><div id="wDet" style="margin-top:8px"></div></div>
    <details><summary>Editar como JSON Schema</summary><textarea class="json-ed" id="eJson" style="margin-top:10px"></textarea>
      <div class="acciones" style="border:0"><button class="btn" id="bJson">Guardar desde el JSON</button></div></details>
    <div class="acciones"><button class="btn primario" id="bG">Guardar esquema</button><button class="btn ghost" id="bDef">Restablecer al esquema inicial</button></div>`;
  pinta();
  $("#eJson").value = JSON.stringify(esq, null, 2);
  const editar = (ev, filas) => { const tr = ev.target.closest("tr[data-i]"), k = ev.target.dataset.k; if (!tr || !k) return;
    filas[tr.dataset.i][k] = ev.target.type === "checkbox" ? ev.target.checked : ev.target.value; $("#eJson").value = JSON.stringify(construir(), null, 2); };
  p.addEventListener("input", (ev) => { if (ev.target.closest("#tCab")) editar(ev, cab); if (ev.target.closest("#tDet")) editar(ev, det); });
  p.addEventListener("click", (ev) => {
    const q = ev.target.closest("[data-quitar]");
    if (q) { const tr = q.closest("tr"); (tr.closest("#tCab") ? cab : det).splice(Number(tr.dataset.i), 1); pinta(); }
    const a = ev.target.closest("[data-agregar]");
    if (a) { (a.dataset.agregar === "tCab" ? cab : det).push({ nombre: "", tipo: "string", obligatorio: false, descripcion: "" }); pinta(); }
  });
  $("#bG").onclick = () => guardarSeccion("esquema", construir(), "Esquema guardado");
  $("#bJson").onclick = () => { let v; try { v = JSON.parse($("#eJson").value); } catch (e) { return toast("El JSON no es válido: " + e.message, true); }
    guardarSeccion("esquema", v, "Esquema guardado").then((ok) => ok && abrirConfig("esquema")); };
  $("#bDef").onclick = async () => { await api("/api/config/esquema/restablecer", { method: "POST" }); await cargarConfig(); toast("Esquema restablecido"); abrirConfig("esquema"); };
};

VISTAS.validacion = (p) => {
  const v = config.validacion;
  p.innerHTML = `<div><h2>Reglas de validación</h2><p class="intro">Una factura solo sigue al catálogo si tiene los campos obligatorios, sus montos cuadran y la confianza del modelo alcanza el mínimo.</p></div>${errBox}
    <div class="campos">
      <label class="campo">Tolerancia por línea <small>cantidad × precio − descuento vs. importe (+0,005 por unidad)</small><input type="number" step="0.01" id="v_tl" value="${v.tolerancia_linea}"></label>
      <label class="campo">Tolerancia en totales <small>suma de líneas vs. subtotal y cálculo del total</small><input type="number" step="0.01" id="v_tt" value="${v.tolerancia_total}"></label>
      <label class="campo">Confianza mínima del modelo <small>0 desactiva esta regla</small><input type="number" step="0.05" min="0" max="1" id="v_cm" value="${v.confianza_minima}"></label>
    </div>
    <label class="check"><input type="checkbox" id="v_pi" ${v.precios_incluyen_impuesto ? "checked" : ""}> Los precios de las líneas ya incluyen el impuesto</label>
    <details><summary>Campos que usa el cuadre</summary><div class="campos" style="margin-top:10px">${Object.entries(v.campos).map(([k, x]) =>
      `<label class="campo">${esc(k)}<input type="text" data-campo="${esc(k)}" value="${esc(x)}"></label>`).join("")}</div></details>
    <div class="acciones"><button class="btn primario" id="bG">Guardar</button></div>`;
  $("#bG").onclick = () => { const campos = {}; $$("[data-campo]").forEach((i) => (campos[i.dataset.campo] = i.value.trim()));
    guardarSeccion("validacion", { tolerancia_linea: num("v_tl"), tolerancia_total: num("v_tt"), confianza_minima: num("v_cm"), precios_incluyen_impuesto: chk("v_pi"), campos }); };
};

VISTAS.catalogo = (p) => {
  const c = structuredClone(config.catalogo);
  const pinta = () => {
    $("#tCat tbody").innerHTML = c.productos.map((x, i) => `<tr data-i="${i}"><td><input type="text" data-k="codigo" value="${esc(x.codigo)}"></td>
      <td><input type="text" data-k="producto" value="${esc(x.producto)}"></td>
      <td><input type="text" data-k="palabras_clave" value="${esc((x.palabras_clave || []).join(", "))}"></td>
      <td style="text-align:center"><input type="checkbox" data-k="activo" ${x.activo !== false ? "checked" : ""}></td>
      <td><button class="btn sm ghost peligro" data-quitar>Quitar</button></td></tr>`).join("") ||
      `<tr><td colspan="5" class="vacio">Sin productos. Agrega uno o importa un CSV.</td></tr>`;
    $("#catN").textContent = `${c.productos.length} producto(s)`;
  };
  p.innerHTML = `<div><h2>Catálogo de productos</h2><p class="intro">Las líneas de la factura que coinciden con un producto activo suman el «total catálogo».
    Busca en orden: código exacto, palabra clave o sinónimo, y parecido de texto (tolera errores de tipeo).</p></div>${errBox}
    <div class="card-h" style="margin:0"><span class="muted" id="catN"></span><div style="display:flex;gap:8px;flex-wrap:wrap">
      <button class="btn sm" id="cAdd">Agregar producto</button><label class="btn sm">Importar CSV<input type="file" id="cCsv" accept=".csv,text/csv" hidden></label></div></div>
    <div class="tabla-wrap"><table class="tabla edit" id="tCat"><thead><tr><th>Código</th><th>Producto</th><th>Palabras clave y sinónimos (separados por coma)</th><th>Activo</th><th></th></tr></thead><tbody></tbody></table></div>
    <div class="campos">
      <label class="campo">Parecido mínimo (50–100) <small>Más alto = más estricto</small><input type="number" min="50" max="100" id="c_um" value="${c.umbral_parecido}"></label>
      <label class="check" style="align-self:end"><input type="checkbox" id="c_imp" ${c.total_con_impuesto ? "checked" : ""}> Sumar el total catálogo con impuesto</label>
    </div>
    <div class="secreto"><label class="campo">Probar una descripción<input type="text" id="cProbar" placeholder="Ej.: Varilla corrugada 3/8 x 6 m"></label><button class="btn" id="bProbar">Probar</button><span id="cRes" class="muted"></span></div>
    <div class="acciones"><button class="btn primario" id="bG">Guardar catálogo</button></div>`;
  pinta();
  $("#tCat").addEventListener("input", (e) => { const tr = e.target.closest("tr[data-i]"), k = e.target.dataset.k; if (!tr || !k) return;
    const x = c.productos[tr.dataset.i]; x[k] = k === "activo" ? e.target.checked : k === "palabras_clave" ? e.target.value.split(",").map((s) => s.trim()).filter(Boolean) : e.target.value; });
  $("#tCat").addEventListener("click", (e) => { if (e.target.hasAttribute("data-quitar")) { c.productos.splice(Number(e.target.closest("tr").dataset.i), 1); pinta(); } });
  $("#cAdd").onclick = () => { c.productos.push({ codigo: "", producto: "", palabras_clave: [], activo: true }); pinta(); $("#tCat tbody tr:last-child input[data-k=producto]")?.focus(); };
  $("#cCsv").onchange = async (e) => {
    const texto = await e.target.files[0].text(); const lineas = texto.split(/\r?\n/).filter((l) => l.trim());
    const sep = lineas[0]?.includes(";") ? ";" : ","; let n = 0;
    for (const [i, l] of lineas.entries()) {
      const [codigo, producto, ...claves] = l.split(sep).map((s) => s.trim().replace(/^"|"$/g, ""));
      if (i === 0 && /producto/i.test(l)) continue;
      if (producto) { c.productos.push({ codigo, producto, palabras_clave: claves.join(",").split(/[,|]/).map((s) => s.trim()).filter(Boolean), activo: true }); n++; }
    }
    pinta(); toast(`${n} producto(s) importados. Revisa y guarda.`);
  };
  $("#bProbar").onclick = async () => { await guardarSeccion("catalogo", { ...c, umbral_parecido: num("c_um"), total_con_impuesto: chk("c_imp") }, "Catálogo guardado");
    const r = await api("/api/probar/catalogo", { method: "POST", body: JSON.stringify({ descripcion: val("cProbar") }) });
    $("#cRes").innerHTML = r.coincide ? `<span class="hit">Coincide con ${esc(r.producto)}</span> (${esc(r.tipo)} ${r.tipo === "parecido" ? r.puntaje : ""})` : "No coincide con ningún producto"; };
  $("#bG").onclick = () => guardarSeccion("catalogo", { ...c, umbral_parecido: num("c_um"), total_con_impuesto: chk("c_imp") }, "Catálogo guardado");
};

VISTAS.probar = (p) => {
  p.innerHTML = `<div><h2>Probar extracción</h2><p class="intro">Sube una factura desde tu equipo para ver qué extrae cada modelo y si pasa la validación. No toca Google Drive ni la hoja.</p></div>
    <div class="campos"><label class="campo">Archivo (PDF o imagen)<input type="file" id="pArch" accept=".pdf,image/*"></label>
      <label class="campo">Modelo<select id="pMod"><option value="">Cadena completa (como en el proceso)</option>${config.modelos.cadena.filter((m) => m.activo).map((m) => `<option value="${esc(m.id)}">${esc(m.nombre)}</option>`).join("")}</select></label></div>
    <div class="acciones"><button class="btn primario" id="bP">Extraer</button><span class="muted" id="pEst"></span></div><div id="pRes" style="display:grid;gap:14px"></div>`;
  $("#bP").onclick = async () => {
    const f = $("#pArch").files[0]; if (!f) return toast("Elige un archivo", true);
    const fd = new FormData(); fd.append("archivo", f);
    $("#pEst").textContent = "Extrayendo… GLM-OCR en CPU puede tardar alrededor de un minuto por página."; $("#bP").disabled = true; $("#pRes").innerHTML = "";
    try {
      const r = await api(`/api/probar/extraccion${val("pMod") ? "?modelo=" + encodeURIComponent(val("pMod")) : ""}`, { method: "POST", body: fd });
      $("#pRes").innerHTML = !r.ok ? `<div class="errores">${esc(r.error)}</div>` : r.resultados.map((x) => !x.ok
        ? `<div class="errores"><b>${esc(x.modelo)}</b>: ${esc(x.error)}</div>`
        : `<div class="card"><div class="card-h"><h3>${esc(x.modelo)} · ${x.segundos} s</h3><span class="pill ${x.evaluacion.valida ? "procesada" : "revision"}">${x.evaluacion.valida ? "Válida" : "No válida"}</span></div>
          ${x.evaluacion.valida ? "" : `<p style="margin:0 0 10px">${esc(x.evaluacion.motivo)}</p>`}
          ${x.catalogo ? `<p style="margin:0 0 10px">Total catálogo: <b class="hit">${dinero(x.catalogo.total_catalogo)}</b> (${x.catalogo.lineas_catalogo} de ${x.catalogo.lineas_total} líneas)</p>` : ""}
          <pre class="bloque">${esc(JSON.stringify(x.datos, null, 2))}</pre>
          ${x.texto_ocr ? `<details style="margin-top:10px"><summary>Texto OCR</summary><pre class="bloque">${esc(x.texto_ocr)}</pre></details>` : ""}</div>`).join("");
    } catch (e) { toast(e.message, true); } finally { $("#pEst").textContent = ""; $("#bP").disabled = false; }
  };
};

/* ── inicio ───────────────────────────────────────────── */
(async () => {
  await cargarConfig();
  let tab = "panel"; try { tab = localStorage.getItem("tab") || "panel"; } catch { /* sin almacenamiento */ }
  abrirTab(tab);
  await refrescarEstado();
  setInterval(() => { refrescarEstado(); if (tabActual === "facturas" && ultimoEstado?.servicio.corriendo) cargarFacturas(); }, 3000);
})();
