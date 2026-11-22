"use strict";
/* Facturas IA — frontend sin dependencias: acceso, panel, facturas y configuración. */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const ico = (n, cls = "ico") => `<svg class="${cls}"><use href="#i-${n}"/></svg>`;
const dinero = (v) => (v === null || v === undefined || v === "" ? "—" : Number(v).toLocaleString("es", { minimumFractionDigits: 2, maximumFractionDigits: 2, useGrouping: "always" }));
const compacto = (v) => Number(v || 0).toLocaleString("es", { notation: Math.abs(v) >= 100000 ? "compact" : "standard", maximumFractionDigits: Math.abs(v) >= 100000 ? 1 : 0 });
const entero = (v) => Number(v || 0).toLocaleString("es", { useGrouping: "always" });
const fecha = (iso, o = { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) => (iso ? new Date(iso).toLocaleString("es", o) : "—");
const horaCorta = (iso) => (iso ? new Date(iso).toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "");
const diaCorto = (iso) => new Date(iso + "T12:00:00").toLocaleDateString("es", { day: "numeric", month: "short" });
const ESTADOS = { procesada: "Procesada", revision: "Revisión manual", pendiente: "Pendiente", en_proceso: "En proceso",
  escrita: "Registrada, sin mover", revision_sin_mover: "A revisión, sin mover", completada: "Completada",
  detenida: "Detenida", error: "Error", cancelada: "Cancelada", "en curso": "En curso" };
const pill = (e) => `<span class="pill ${esc(e)}">${esc(ESTADOS[e] || e)}</span>`;
const guardarLocal = (k, v) => { try { localStorage.setItem(k, v); } catch { /* sin almacenamiento */ } };
const leerLocal = (k) => { try { return localStorage.getItem(k); } catch { return null; } };

/* ── API ──────────────────────────────────────────────── */
async function api(ruta, opciones = {}) {
  const cab = opciones.body && !(opciones.body instanceof FormData) ? { "Content-Type": "application/json" } : {};
  const r = await fetch(ruta, { credentials: "same-origin", headers: cab, ...opciones });
  let datos = null;
  try { datos = await r.json(); } catch { /* sin cuerpo */ }
  if (r.status === 401 && !ruta.startsWith("/api/auth/")) {
    // Solo si la app estaba abierta: una consulta tardía no debe reiniciar el formulario de acceso.
    if (!$("#app").hidden) mostrarAcceso();
    throw new Error("Sesión vencida");
  }
  if (!r.ok) {
    const det = datos?.detail;
    const msg = det?.errores ? det.errores.join(" ") : typeof det === "string" ? det : `Error ${r.status}`;
    const e = new Error(msg); e.errores = det?.errores; e.status = r.status; throw e;
  }
  return datos;
}

function toast(msg, err = false) {
  const t = document.createElement("div");
  t.className = "toast " + (err ? "err" : "ok");
  t.innerHTML = `${ico(err ? "error" : "ok")}<span>${esc(msg)}</span>`;
  $("#toasts").appendChild(t);
  setTimeout(() => t.remove(), err ? 6500 : 3200);
}

/* ── Tema ─────────────────────────────────────────────── */
function temaActual() {
  return document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
}
function rotularTema() {
  const t = temaActual();
  $$(".tema").forEach((b) => { b.setAttribute("aria-label", t === "dark" ? "Cambiar a tema claro" : "Cambiar a tema oscuro"); b.title = b.getAttribute("aria-label"); });
}
function alternarTema() {
  const nuevo = temaActual() === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = nuevo; guardarLocal("tema", nuevo); rotularTema();
  if (!$("#app").hidden && ruta === "panel" && stats) pintarGraficos();
}
document.addEventListener("click", (e) => { if (e.target.closest(".tema")) alternarTema(); });
// Botón de tema también en la pantalla de acceso, en la misma esquina superior derecha.
$(".acceso-form").insertAdjacentHTML("afterbegin", `<button class="icono tema tema-flotante" type="button" aria-label="Cambiar tema"><svg class="t-sol"><use href="#i-sol"/></svg><svg class="t-luna"><use href="#i-luna"/></svg></button>`);
rotularTema();

/* ── Acceso ───────────────────────────────────────────── */
let modoAcceso = "login", sesion = null;

async function arrancar() {
  let s;
  try { s = await api("/api/auth/estado"); } catch { s = { autenticado: false }; }
  sesion = s;
  if (s.autenticado) iniciarApp(); else mostrarAcceso(s);
}

async function mostrarAcceso(s) {
  detenerSondeo();
  if (!s) { try { s = await api("/api/auth/estado"); } catch { s = {}; } }
  $("#app").hidden = true; $("#acceso").hidden = false; $("#cajon").hidden = true;
  modoAcceso = s.requiere_configuracion ? (s.configuracion_permitida ? "configurar" : "bloqueado") : "login";
  const aviso = $("#aAviso");
  aviso.hidden = true; aviso.className = "aviso-acceso";
  $("#wConfirmar").hidden = modoAcceso !== "configurar";
  $("#aMedidor").hidden = modoAcceso !== "configurar";
  $("#wRecordar").hidden = modoAcceso !== "login";
  $("#aClave").autocomplete = modoAcceso === "configurar" ? "new-password" : "current-password";
  if (modoAcceso === "configurar") {
    $("#aTitulo").textContent = "Crea tu cuenta";
    $("#aSub").textContent = "Es la primera vez que se abre el sistema. Esta cuenta será la de administrador.";
    $("#aEntrar").textContent = "Crear cuenta y entrar";
  } else if (modoAcceso === "bloqueado") {
    $("#aTitulo").textContent = "Falta crear la cuenta";
    $("#aSub").textContent = "Por seguridad, la primera cuenta solo se crea desde el equipo donde corre el sistema.";
    aviso.hidden = false; aviso.classList.add("info");
    aviso.innerHTML = `${ico("info")}<span>Abre <code>http://localhost:8000</code> en ese equipo, o ejecuta <code>.venv\\Scripts\\python -m app.auth crear-usuario admin</code>.</span>`;
    $("#aEntrar").textContent = "Entrar";
  } else {
    $("#aTitulo").textContent = "Inicia sesión";
    $("#aSub").textContent = "Entra con tu usuario para ver el panel de facturas.";
    $("#aEntrar").textContent = "Entrar";
  }
  $("#aEntrar").disabled = modoAcceso === "bloqueado";
  setTimeout(() => $("#aUsuario").focus(), 50);
}

$("#aVer").addEventListener("click", () => {
  const i = $("#aClave"), ver = i.type === "password";
  i.type = ver ? "text" : "password"; $("#aConfirmar").type = i.type;
  $("#aVer").innerHTML = `<svg><use href="#i-${ver ? "ojo-no" : "ojo"}"/></svg>`;
  $("#aVer").setAttribute("aria-label", ver ? "Ocultar contraseña" : "Mostrar contraseña");
});
$("#aClave").addEventListener("input", () => {
  if (modoAcceso !== "configurar") return;
  const v = $("#aClave").value; let p = 0;
  if (v.length >= 10) p++; if (v.length >= 14) p++; if (/[A-Z]/.test(v) && /[a-z]/.test(v)) p++; if (/\d/.test(v)) p++; if (/[^A-Za-z0-9]/.test(v)) p++;
  const niv = [["Muy débil", "var(--err)"], ["Débil", "var(--err)"], ["Aceptable", "var(--av-marca)"], ["Buena", "var(--av-marca)"], ["Fuerte", "var(--ok-marca)"], ["Muy fuerte", "var(--ok-marca)"]][p];
  const m = $("#aMedidor i"); m.style.setProperty("--v", `${Math.max(8, (p / 5) * 100)}%`); m.style.setProperty("--c", niv[1]);
  $("#aMedidor span").textContent = v ? niv[0] : "Mínimo 10 caracteres";
});
$("#fAcceso").addEventListener("submit", async (e) => {
  e.preventDefault();
  const aviso = $("#aAviso"), b = $("#aEntrar");
  const usuario = $("#aUsuario").value.trim(), clave = $("#aClave").value;
  aviso.hidden = true; aviso.className = "aviso-acceso";
  const fallo = (m) => { aviso.hidden = false; aviso.innerHTML = `${ico("error")}<span>${esc(m)}</span>`; };
  if (!usuario || !clave) return fallo("Escribe tu usuario y tu contraseña.");
  if (modoAcceso === "configurar" && clave !== $("#aConfirmar").value) return fallo("Las contraseñas no coinciden.");
  b.disabled = true; const texto = b.textContent; b.textContent = "Entrando…";
  try {
    const ruta = modoAcceso === "configurar" ? "/api/auth/configurar" : "/api/auth/login";
    const cuerpo = modoAcceso === "configurar" ? { usuario, clave } : { usuario, clave, recordar: $("#aRecordar").checked };
    const r = await api(ruta, { method: "POST", body: JSON.stringify(cuerpo) });
    sesion = { autenticado: true, usuario: r.usuario };
    $("#aClave").value = ""; $("#aConfirmar").value = "";
    iniciarApp();
  } catch (err) { fallo(err.message); $("#aClave").select(); }
  finally { b.disabled = false; b.textContent = texto; }
});
$("#bSalir").addEventListener("click", async () => {
  detenerSondeo();
  try { await api("/api/auth/logout", { method: "POST" }); } catch { /* ya estaba cerrada */ }
  sesion = null; mostrarAcceso();
});

/* ── Estructura: menú, rutas ──────────────────────────── */
const TITULOS = { panel: ["Panel", "Estado del procesamiento de facturas"], facturas: ["Facturas", "Todo lo que ha pasado por la carpeta de Drive"],
  config: ["Configuración", "Conexión, modelos, reglas y catálogo"] };
let ruta = "panel";

function aplicarColapso(c) {
  $("#app").classList.toggle("colapsada", c);
  const b = $("#bColapsar"); b.setAttribute("aria-label", c ? "Expandir el menú" : "Contraer el menú"); b.title = b.getAttribute("aria-label");
}
$("#bColapsar").addEventListener("click", () => { const c = !$("#app").classList.contains("colapsada"); aplicarColapso(c); guardarLocal("menuColapsado", c ? "1" : "0"); setTimeout(() => ruta === "panel" && stats && pintarGraficos(), 240); });
const cerrarMenu = () => { $("#app").classList.remove("menu-abierto"); $("#velo").hidden = true; };
$("#bMenu").addEventListener("click", () => { $("#app").classList.add("menu-abierto"); $("#velo").hidden = false; });
$("#velo").addEventListener("click", cerrarMenu);
$$(".menu a[data-ruta]").forEach((a) => a.addEventListener("click", cerrarMenu));

function irA(hash) {
  const [r, sub] = (hash || "").replace("#", "").split("/");
  ruta = TITULOS[r] ? r : "panel";
  $$(".menu a[data-ruta]").forEach((a) => (a.dataset.ruta === ruta ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
  $$(".vista").forEach((v) => (v.hidden = v.id !== `v-${ruta}`));
  $("#titulo").textContent = TITULOS[ruta][0]; $("#subtitulo").textContent = TITULOS[ruta][1];
  document.title = `${TITULOS[ruta][0]} · Facturas IA`;
  if (ruta === "panel") { cargarStats(); refrescarCorridas(true); }
  if (ruta === "facturas") cargarFacturas();
  if (ruta === "config") abrirConfig(sub && VISTAS[sub] ? sub : cfgActual);
}
addEventListener("hashchange", () => !$("#app").hidden && irA(location.hash));

let iniciada = false;
async function iniciarApp() {
  $("#acceso").hidden = true; $("#app").hidden = false;
  const u = sesion?.usuario || "";
  $("#pUsuario").textContent = u || "—"; $("#avatar").textContent = (u[0] || "?");
  aplicarColapso(leerLocal("menuColapsado") === "1");
  await cargarConfig();
  if (!iniciada) {
    iniciada = true;
    const dias = leerLocal("periodo");
    if (dias !== null) $$("#periodo button").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.dias === dias)));
  }
  await refrescarEstado();
  irA(location.hash || "#panel");
  iniciarSondeo();
}

let sondeo = null, contadorStats = 0;
function iniciarSondeo() {
  detenerSondeo();
  sondeo = setInterval(async () => {
    if (document.hidden) return;
    await refrescarEstado();
    if (ruta === "panel" && ++contadorStats % 10 === 0) cargarStats();
    if (ruta === "facturas" && ultimoEstado?.servicio.corriendo) cargarFacturas(false);
  }, 3000);
}
function detenerSondeo() { if (sondeo) clearInterval(sondeo); sondeo = null; }

/* ── Estado del servicio ──────────────────────────────── */
let config = null, ultimoEstado = null, estabaCorriendo = false;

async function refrescarEstado() {
  let e;
  try { e = await api("/api/estado"); } catch (err) {
    if (err.message !== "Sesión vencida") { $("#estadoRun span").textContent = "Servidor sin respuesta"; $("#estadoRun").className = "estado-run detenido"; }
    return;
  }
  ultimoEstado = e;
  const s = e.servicio, detenido = e.alertas.some((a) => a.clave === "modelos");
  const texto = s.corriendo ? `${s.paso || "Procesando"}${s.archivo ? " · " + s.archivo : ""}`
    : detenido ? "Proceso detenido" : s.programado ? `En espera · próxima ${fecha(s.proxima, { hour: "2-digit", minute: "2-digit" })}` : "En espera";
  $("#estadoRun").className = "estado-run" + (s.corriendo ? " activo" : detenido ? " detenido" : "");
  $("#estadoRun span").textContent = texto; $("#estadoRun").title = texto;
  $("#bProcesar").disabled = s.corriendo;
  $("#bDetener").hidden = !s.corriendo; $("#bDetener").disabled = s.deteniendo;
  $("#lEstado").className = "lateral-estado" + (s.corriendo ? " activo" : detenido ? " detenido" : "");
  $("#lEstado").innerHTML = `<b><i></i><span>${s.corriendo ? "Procesando" : detenido ? "Detenido" : "En espera"}</span></b>
    <small>${s.corriendo ? esc(s.archivo || s.paso || "") : s.programado ? `Revisión automática cada ${config?.frecuencia.cada_minutos ?? "?"} min` : "Revisión automática apagada"}</small>`;
  const nRev = (e.por_estado.revision || 0) + (e.por_estado.revision_sin_mover || 0);
  $("#mRevision").hidden = !nRev; $("#mRevision").textContent = nRev; $("#mRevision").title = `${nRev} en revisión manual`;

  $("#alertas").innerHTML = e.alertas.map((a) => `<div class="alerta ${a.nivel === "aviso" ? "aviso" : ""}">${ico(a.nivel === "aviso" ? "aviso" : "error")}
      <div><b>${a.clave === "modelos" ? "Proceso detenido" : a.clave === "drive" ? "Problema con Google Drive" : "Aviso"}</b>${esc(a.mensaje.replace(/^(Proceso detenido|Problema con Google Drive):\s*/i, ""))}
      <small>${fecha(a.ts)}</small></div><button class="btn sm ghost" data-cerrar="${a.id}">Descartar</button></div>`).join("");

  if (ruta === "panel") {
    pintarRecorrido();
    if (estabaCorriendo && !s.corriendo) { cargarStats(); refrescarCorridas(true); }
    else if (s.corriendo) refrescarCorridas(false);
  }
  estabaCorriendo = s.corriendo;
}

$("#alertas").addEventListener("click", async (ev) => {
  const b = ev.target.closest("[data-cerrar]"); if (!b) return;
  await api(`/api/alertas/${b.dataset.cerrar}/cerrar`, { method: "POST" }); refrescarEstado();
});
$("#bProcesar").addEventListener("click", async () => {
  try { await api("/api/procesar", { method: "POST" }); toast("Corrida iniciada"); } catch (e) { toast(e.message, true); }
  refrescarEstado();
});
$("#bDetener").addEventListener("click", async () => { await api("/api/detener", { method: "POST" }); toast("Se detendrá al terminar la factura en curso"); refrescarEstado(); });

/* ── Panel: indicadores y gráficos ────────────────────── */
let stats = null;
const periodo = () => Number($("#periodo [aria-checked=true]").dataset.dias);

async function cargarStats() {
  try { stats = await api(`/api/estadisticas?dias=${periodo()}`); } catch { return; }
  const d = periodo();
  $("#periodoInfo").textContent = d ? `Del ${diaCorto(stats.desde)} a hoy` : `Desde ${diaCorto(stats.desde)}, la primera factura registrada`;
  $("#recInfo").textContent = d ? `Lo que pasó con las facturas de los últimos ${d} días` : "Lo que pasó con todas las facturas registradas";
  pintarKpis(); pintarGraficos(); pintarRecorrido();
}
$("#periodo").addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (!b) return;
  $$("#periodo button").forEach((x) => x.setAttribute("aria-checked", String(x === b)));
  guardarLocal("periodo", b.dataset.dias); cargarStats();
});

function pintarKpis() {
  const r = stats.resumen, c = ultimoEstado?.contadores || {};
  const serieP = stats.serie.map((x) => x.procesadas), serieR = stats.serie.map((x) => x.revision);
  const total = r.procesadas + r.revision;
  const pctCat = r.monto_total ? Math.round((100 * r.monto_catalogo) / r.monto_total) : 0;
  $("#kpis").innerHTML = `
    <div class="kpi"><div class="kpi-h"><span class="kpi-ico">${ico("carpeta")}</span>Pendientes en Drive</div>
      <div class="kpi-v num">${c.pendientes ?? "—"}</div>
      <div class="kpi-p">${c.actualizado ? `Conteo del ${fecha(c.actualizado)}` : "Sin conteo todavía"}</div>
      <div class="kpi-p">${c.ignorados ? `<b>${c.ignorados}</b> de otro tipo, ignorado(s)` : "PDF, JPG, PNG o WEBP"}</div></div>
    <div class="kpi ok"><div class="kpi-h"><span class="kpi-ico">${ico("ok")}</span>Procesadas</div>
      <div class="kpi-v num">${entero(r.procesadas)}</div><div class="chispa" id="chP"></div></div>
    <div class="kpi rev"><div class="kpi-h"><span class="kpi-ico">${ico("aviso")}</span>A revisión manual</div>
      <div class="kpi-v num">${entero(r.revision)}</div><div class="chispa" id="chR"></div></div>
    <div class="kpi acento"><div class="kpi-h"><span class="kpi-ico">${ico("escudo")}</span>Tasa de éxito</div>
      <div class="kpi-v num">${r.tasa_exito ?? "—"}<small>${r.tasa_exito !== null ? "%" : ""}</small></div>
      <div class="kpi-p">${total ? `${entero(r.procesadas)} de ${entero(total)} sin intervención` : "Sin facturas en el periodo"}</div>
      <div class="medida" title="Procesadas frente a revisión">${total ? `<i style="width:${(100 * r.procesadas) / total}%"></i><i style="flex:1"></i>` : ""}</div></div>
    <div class="kpi"><div class="kpi-h"><span class="kpi-ico">${ico("hoja")}</span>Monto registrado</div>
      <div class="kpi-v num" title="${dinero(r.monto_total)}">${compacto(r.monto_total)}<small>${esc(r.moneda && r.moneda !== "—" ? r.moneda : "")}</small></div>
      <div class="kpi-p">Catálogo: <b>${compacto(r.monto_catalogo)}</b> (${pctCat} %)</div>
      <div class="kpi-p">${r.corridas} corrida(s)${r.corridas_detenidas ? `, <b>${r.corridas_detenidas}</b> detenida(s)` : ""}</div></div>`;
  Graficos.chispa($("#chP"), serieP, "var(--ok-marca)");
  Graficos.chispa($("#chR"), serieR, "var(--rev-marca)");
}

function pintarGraficos() {
  if (!stats) return;
  Graficos.columnasApiladas($("#gDiario"), stats.serie,
    [{ clave: "procesadas", nombre: "Procesadas", color: "var(--ok-marca)" }, { clave: "revision", nombre: "A revisión", color: "var(--rev-marca)" }],
    { titulo: "Facturas por día", etiquetaX: (d) => diaCorto(d.fecha), titulo_tip: (d) => new Date(d.fecha + "T12:00:00").toLocaleDateString("es", { weekday: "long", day: "numeric", month: "long" }),
      vacio: "Todavía no hay facturas en este periodo.<br>Usa «Procesar ahora» para revisar la carpeta." });
  const total = stats.motivos.reduce((s, m) => s + m.cantidad, 0);
  $("#motivosInfo").textContent = total ? `${total} factura(s) en el periodo` : "Ninguna factura fue a revisión";
  Graficos.barrasH($("#gMotivos"), stats.motivos.map((m) => ({ etiqueta: m.motivo, valor: m.cantidad })),
    { vacio: "Ninguna factura fue a revisión en este periodo." });
  $("#gModelos").innerHTML = stats.modelos.length ? `<div class="modelos">${stats.modelos.map((m) => `
    <div class="modelo-f"><div class="nom"><b title="${esc(m.modelo)}">${esc(m.modelo)}</b><small>${entero(m.intentos)} intento(s)</small></div>
      <div class="tasa"><div class="tasa-t"><span>Datos válidos</span><b>${m.tasa} %</b></div><div class="pista"><i style="width:${m.tasa}%"></i></div></div>
      <div class="seg">${m.segundos_promedio ?? "—"} s<small>promedio</small></div></div>`).join("")}</div>`
    : `<div class="vacio"><b>Sin intentos en el periodo</b>Cuando se procese una factura verás aquí cada modelo.</div>`;
}

/* Recorrido: siete etapas del flujo con el paso en curso o el resumen del periodo. */
const ETAPAS = [
  { n: "Detectar", ico: "carpeta", pasos: ["01", "02", "03"] }, { n: "Descargar", ico: "descargar", pasos: ["04"] },
  { n: "Leer con IA", ico: "chip", pasos: ["05", "06"] }, { n: "Validar", ico: "escudo", pasos: ["07", "08", "09"] },
  { n: "Catálogo", ico: "catalogo", pasos: ["10", "11"] }, { n: "Registrar", ico: "hoja", pasos: ["12"] },
  { n: "Mover", ico: "flecha", pasos: ["13", "R", "14"] }];
const SALIDA_ETAPA = { "Duplicado": 0, "Documento dañado": 2, "No es factura o ilegible": 3, "Montos no cuadran": 3, "Datos incompletos": 3, "Confianza baja": 3, "Otro": 3 };

function pintarRecorrido() {
  const s = ultimoEstado?.servicio, r = stats?.resumen;
  const paso = s?.corriendo ? (s.paso || "").match(/^(\d\d|R)/)?.[1] : null;
  const actual = paso ? ETAPAS.findIndex((e) => e.pasos.includes(paso)) : -1;
  const salidas = Array(7).fill(0);
  (stats?.motivos || []).forEach((m) => (salidas[SALIDA_ETAPA[m.motivo] ?? 3] += m.cantidad));
  const total = r ? r.procesadas + r.revision : 0;
  const intentos = (stats?.modelos || []).reduce((a, m) => a + m.intentos, 0);
  const segProm = intentos ? (stats.modelos.reduce((a, m) => a + (m.segundos_promedio || 0) * m.intentos, 0) / intentos).toFixed(1) : null;
  const validas = total - salidas[0] - salidas[2];
  const datos = r ? [
    `<b>${entero(total)}</b> factura(s) detectadas`, `<b>${entero(total - salidas[0])}</b> descargadas`,
    segProm ? `<b>${segProm} s</b> por lectura, en promedio` : "Sin lecturas",
    validas > 0 ? `<b>${Math.round((100 * r.procesadas) / validas)} %</b> pasan las reglas` : "Sin validaciones",
    r.monto_total ? `<b>${Math.round((100 * r.monto_catalogo) / r.monto_total)} %</b> del monto en catálogo` : "Sin montos",
    `<b>${entero(r.procesadas)}</b> filas en la hoja`, `<b>${entero(r.procesadas)}</b> a Procesadas`] : Array(7).fill("&nbsp;");
  $("#etapas").innerHTML = ETAPAS.map((e, i) => `<li class="etapa ${actual >= 0 ? (i < actual ? "hecha" : i === actual ? "actual" : "") : "hecha"}">
      <span class="nodo">${ico(e.ico)}</span><h3>${e.n}</h3><p class="dato">${datos[i]}</p>
      <span class="salida ${salidas[i] ? "" : "cero"}" title="Facturas que se desviaron a revisión en esta etapa">${salidas[i]} a revisión</span></li>`).join("");
  $("#recRun").innerHTML = s?.corriendo
    ? `<span class="pill en_proceso">Procesando</span><span><b>${esc(s.paso || "")}</b>${s.archivo ? ` · ${esc(s.archivo)}` : ""}</span>`
    : ultimoEstado?.ultima_corrida ? `<span>Última corrida</span>${pill(ultimoEstado.ultima_corrida.estado)}<span>${fecha(ultimoEstado.ultima_corrida.inicio)}</span>` : "";
}

/* Corridas y bitácora */
let corridas = [], corridaSel = null, eventos = [], firmaEventos = "";
async function refrescarCorridas(todo) {
  try { corridas = await api("/api/corridas?limite=80"); } catch { return; }
  if (!corridaSel || (todo && corridas[0] && corridaSel !== corridas[0].id && !corridaElegida)) corridaSel = corridas[0]?.id ?? null;
  pintarCorridas();
  await cargarEventos();
}
let corridaElegida = false;
function pintarCorridas() {
  const f = $("#fCorridas [aria-checked=true]").dataset.f;
  const lista = corridas.filter((c) => !f || c.origen === f || c.estado === f);
  $("#lCorridas").innerHTML = lista.length ? lista.map((c) => {
    const dur = c.fin ? Math.max(1, Math.round((new Date(c.fin) - new Date(c.inicio)) / 1000)) : null;
    const icono = c.estado === "detenida" ? "error" : c.estado === "completada" ? "ok" : "reloj";
    return `<button class="corrida ${esc(c.estado)}" data-id="${c.id}" aria-pressed="${c.id === corridaSel}">
      <span class="ic">${ico(icono)}</span>
      <span class="t"><b>${fecha(c.inicio)}</b><small>${c.origen === "programada" ? "Programada" : c.origen === "manual" ? "Manual" : esc(c.origen)} · ${dur ? (dur >= 60 ? `${Math.floor(dur / 60)} min ${dur % 60} s` : `${dur} s`) : "en curso"}${c.estado === "detenida" ? " · detenida" : ""}</small></span>
      <span class="r"><span class="mini ${c.procesadas ? "ok" : "cero"}" title="Procesadas">${c.procesadas ?? 0}</span><span class="mini ${c.revision ? "rev" : "cero"}" title="A revisión">${c.revision ?? 0}</span></span></button>`;
  }).join("") : `<div class="vacio"><b>No hay corridas con este filtro</b>Cambia el filtro o usa «Procesar ahora».</div>`;
}
$("#fCorridas").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; $$("#fCorridas button").forEach((x) => x.setAttribute("aria-checked", String(x === b))); pintarCorridas(); });
$("#lCorridas").addEventListener("click", (e) => {
  const b = e.target.closest(".corrida"); if (!b) return;
  corridaSel = Number(b.dataset.id); corridaElegida = corridaSel !== corridas[0]?.id;
  $$("#lCorridas .corrida").forEach((x) => x.setAttribute("aria-pressed", String(x === b))); cargarEventos();
});
async function cargarEventos() {
  if (!corridaSel) { eventos = []; pintarBitacora(); return; }
  try { eventos = await api(`/api/eventos?corrida_id=${corridaSel}`); } catch { return; }
  const firma = `${corridaSel}:${eventos.length}`;
  if (firma === firmaEventos) return;
  firmaEventos = firma; pintarBitacora(true);
}
function pintarBitacora(alFinal = false) {
  const c = corridas.find((x) => x.id === corridaSel);
  const nivel = $("#fNivel [aria-checked=true]").dataset.n, q = $("#fBit").value.trim().toLowerCase();
  const lista = eventos.filter((x) => (!nivel || x.nivel === nivel) && (!q || x.mensaje.toLowerCase().includes(q) || (x.paso || "").toLowerCase() === q));
  $("#bitInfo").textContent = c ? `Corrida del ${fecha(c.inicio)} · ${lista.length} de ${eventos.length} evento(s)` : "Sin corridas todavía";
  const resaltar = (t) => { const s = esc(t); if (!q) return s; const i = s.toLowerCase().indexOf(esc(q)); return i < 0 ? s : `${s.slice(0, i)}<mark>${s.slice(i, i + esc(q).length)}</mark>${s.slice(i + esc(q).length)}`; };
  const ul = $("#bitacora");
  ul.innerHTML = lista.length ? lista.map((x) => `<li class="${esc(x.nivel)}"><span class="ts">${horaCorta(x.ts)}</span><span class="ps" title="Paso ${esc(x.paso)}">${esc(x.paso)}</span>
      <span class="nv">${ico(x.nivel === "error" ? "error" : x.nivel === "aviso" ? "aviso" : "info")}</span><span class="msg">${resaltar(x.mensaje)}</span></li>`).join("")
    : `<div class="vacio"><b>${eventos.length ? "Ningún evento coincide" : "La bitácora está vacía"}</b>${eventos.length ? "Prueba con otro nivel o texto." : "Usa «Procesar ahora» o activa la revisión automática en Configuración."}</div>`;
  if (alFinal) ul.scrollTop = ul.scrollHeight;
}
$("#fNivel").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; $$("#fNivel button").forEach((x) => x.setAttribute("aria-checked", String(x === b))); pintarBitacora(); });
$("#fBit").addEventListener("input", () => pintarBitacora());

/* ── Facturas ─────────────────────────────────────────── */
const GRUPOS = [{ f: "", n: "Todas" }, { f: "procesada", n: "Procesadas", e: ["procesada"] },
  { f: "revision", n: "En revisión", e: ["revision", "revision_sin_mover"] }, { f: "pendiente", n: "Pendientes", e: ["pendiente", "en_proceso", "escrita"] }];
let facturas = [], filtroF = "", ordenF = { k: "actualizado", asc: false }, paginaF = 0;
const POR_PAGINA = 15;

async function cargarFacturas(reiniciar = true) {
  if (reiniciar && !facturas.length) $("#tFacturas tbody").innerHTML = Array(6).fill(`<tr>${Array(8).fill('<td><span class="cargando">cargando</span></td>').join("")}</tr>`).join("");
  try { facturas = await api("/api/archivos?limite=5000"); } catch { return; }
  pintarFacturas();
}
function filtradas() {
  const g = GRUPOS.find((x) => x.f === filtroF), q = $("#fBuscar").value.trim().toLowerCase();
  const lista = facturas.filter((f) => (!g?.e || g.e.includes(f.estado)) &&
    (!q || [f.nombre, f.emisor, f.numero_factura, f.motivo].some((v) => (v || "").toLowerCase().includes(q))));
  const { k, asc } = ordenF;
  return lista.sort((a, b) => { const x = a[k] ?? "", y = b[k] ?? ""; const r = typeof x === "number" || typeof y === "number" ? (Number(x) || 0) - (Number(y) || 0) : String(x).localeCompare(String(y), "es"); return asc ? r : -r; });
}
function pintarFacturas() {
  $("#fEstado").innerHTML = GRUPOS.map((g) => `<button role="radio" data-f="${g.f}" aria-checked="${g.f === filtroF}">${g.n}<em>${facturas.filter((f) => !g.e || g.e.includes(f.estado)).length}</em></button>`).join("");
  const lista = filtradas(), paginas = Math.max(1, Math.ceil(lista.length / POR_PAGINA));
  paginaF = Math.min(paginaF, paginas - 1);
  const vista = lista.slice(paginaF * POR_PAGINA, (paginaF + 1) * POR_PAGINA);
  $$("#tFacturas th[data-orden]").forEach((th) => (th.dataset.orden === ordenF.k ? th.setAttribute("aria-sort", ordenF.asc ? "ascending" : "descending") : th.removeAttribute("aria-sort")));
  $("#tFacturas tbody").innerHTML = vista.length ? vista.map((f) => {
    const ext = (f.nombre.split(".").pop() || "").toLowerCase();
    const sec = f.estado === "procesada" ? (f.modelo || "—") : (f.motivo || "—");
    return `<tr class="click" tabindex="0" data-id="${esc(f.file_id)}">
      <td><div class="arch"><span class="tipo ${ext === "pdf" ? "pdf" : "img"}">${esc(ext.toUpperCase().slice(0, 4))}</span><span title="${esc(f.nombre)}">${esc(f.nombre)}</span></div></td>
      <td>${pill(f.estado)}</td><td class="num nw">${esc(f.numero_factura || "—")}</td><td><div class="emisor" title="${esc(f.emisor || "")}">${esc(f.emisor || "—")}</div></td>
      <td class="n">${dinero(f.total)}</td><td class="n">${dinero(f.total_catalogo)}</td>
      <td><div class="sec" title="${esc(sec)}">${esc(sec)}</div></td><td class="num" style="white-space:nowrap">${fecha(f.actualizado)}</td></tr>`;
  }).join("") : `<tr><td colspan="8"><div class="vacio"><b>${facturas.length ? "Ninguna factura coincide" : "Todavía no hay facturas"}</b>${facturas.length ? "Cambia el filtro o la búsqueda." : "Sube facturas a la carpeta de Drive y usa «Procesar ahora»."}</div></td></tr>`;
  const desde = lista.length ? paginaF * POR_PAGINA + 1 : 0, hasta = Math.min(lista.length, (paginaF + 1) * POR_PAGINA);
  $("#paginador").innerHTML = `<span>${desde}–${hasta} de ${entero(lista.length)} factura(s)</span>
    <div class="pags"><button class="btn sm" data-pag="-1" ${paginaF === 0 ? "disabled" : ""}>Anterior</button>
    <span class="btn sm ghost" style="cursor:default">${paginaF + 1} / ${paginas}</span>
    <button class="btn sm" data-pag="1" ${paginaF >= paginas - 1 ? "disabled" : ""}>Siguiente</button></div>`;
}
$("#fEstado").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; filtroF = b.dataset.f; paginaF = 0; pintarFacturas(); });
$("#fBuscar").addEventListener("input", () => { paginaF = 0; pintarFacturas(); });
$("#tFacturas thead").addEventListener("click", (e) => { const th = e.target.closest("th[data-orden]"); if (!th) return;
  ordenF = { k: th.dataset.orden, asc: ordenF.k === th.dataset.orden ? !ordenF.asc : th.dataset.orden !== "actualizado" && !["total", "total_catalogo"].includes(th.dataset.orden) }; pintarFacturas(); });
$("#paginador").addEventListener("click", (e) => { const b = e.target.closest("[data-pag]"); if (!b) return; paginaF += Number(b.dataset.pag); pintarFacturas(); });
$("#tFacturas").addEventListener("click", (ev) => { const tr = ev.target.closest("tr[data-id]"); if (tr) abrirFactura(tr.dataset.id); });
$("#tFacturas").addEventListener("keydown", (ev) => { const tr = ev.target.closest("tr[data-id]"); if (tr && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); abrirFactura(tr.dataset.id); } });
$("#bCsv").addEventListener("click", () => {
  const cols = ["nombre", "estado", "numero_factura", "emisor", "total", "total_catalogo", "modelo", "motivo", "actualizado"];
  const csv = [cols.join(","), ...filtradas().map((f) => cols.map((c) => `"${String(f[c] ?? "").replace(/"/g, '""')}"`).join(","))].join("\r\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }));
  a.download = `facturas_${new Date().toISOString().slice(0, 10)}.csv`; a.click(); URL.revokeObjectURL(a.href);
  toast("CSV exportado");
});

/* Detalle */
let focoPrevio = null;
async function abrirFactura(id) {
  let f;
  try { f = await api(`/api/archivos/${encodeURIComponent(id)}`); } catch (e) { return toast(e.message, true); }
  const d = f.datos_json || {}, r = f.resultado_json || {}, ev = r.evaluacion || {}, cat = r.catalogo;
  $("#dTitulo").textContent = f.nombre;
  $("#dSub").innerHTML = `${pill(f.estado)}`;
  const escalares = Object.entries(d).filter(([, v]) => typeof v !== "object" || v === null);
  const lineas = Array.isArray(d.lineas) ? d.lineas : [];
  const marcas = cat?.lineas || [];
  const bit = (f.eventos || []).map((x) => `<li class="${esc(x.nivel)}"><span class="ts">${horaCorta(x.ts)}</span><span class="ps">${esc(x.paso)}</span>
      <span class="nv">${ico(x.nivel === "error" ? "error" : x.nivel === "aviso" ? "aviso" : "info")}</span><span class="msg">${esc(x.mensaje)}</span></li>`).join("");
  $("#dCuerpo").innerHTML = `
    ${f.motivo && f.estado !== "procesada" ? `<div class="motivo-f">${ico("aviso")}<span>${esc(f.motivo)}</span></div>` : ""}
    <div class="resumen-f">
      <div><span>Total</span><b>${dinero(f.total ?? d.total)}</b></div>
      <div><span>Total catálogo</span><b class="${cat ? "hit" : ""}">${cat ? dinero(cat.total_catalogo) : "—"}</b></div>
      <div><span>${f.modelo ? "Leída con" : "Intentos"}</span><b title="${esc(f.modelo || "")}" style="font-size:15px">${f.modelo ? esc(f.modelo) : f.intentos || 0}</b></div>
    </div>
    ${f.enlace?.startsWith("http") ? `<a class="btn" href="${esc(f.enlace)}" target="_blank" rel="noopener" style="width:fit-content">${ico("externo")}Abrir el archivo en Drive</a>` : ""}
    ${escalares.length ? `<div class="tarjeta"><h3>Datos extraídos</h3><div class="kv" style="margin-top:12px">${escalares.map(([k, v]) =>
      `<div><span>${esc(k.replace(/_/g, " "))}</span>${typeof v === "number" ? dinero(v) : esc(v ?? "—")}</div>`).join("")}</div></div>` : ""}
    ${lineas.length ? `<div class="tarjeta"><div class="tarjeta-h" style="margin-bottom:10px"><h3>Líneas</h3>${cat ? `<span class="muted">${cat.lineas_catalogo} de ${cat.lineas_total} en el catálogo</span>` : ""}</div>
      <div class="tabla-wrap"><table class="tabla"><thead><tr><th>#</th><th>Descripción</th><th class="n">Cant.</th><th class="n">P. unit.</th><th class="n">Importe</th><th>Catálogo</th></tr></thead><tbody>
      ${lineas.map((l, i) => { const m = marcas[i]; return `<tr><td>${i + 1}</td><td>${esc(l.descripcion)}</td><td class="n">${esc(l.cantidad)}</td>
        <td class="n">${dinero(l.precio_unitario)}</td><td class="n">${dinero(l.importe)}</td>
        <td>${m?.producto ? `<span class="hit">${esc(m.producto)}</span>` : '<span class="muted">—</span>'}</td></tr>`; }).join("")}
      </tbody></table></div></div>` : ""}
    ${ev.reglas?.length || ev.errores_esquema?.length ? `<div class="tarjeta"><h3>Validación</h3><div style="display:grid;gap:8px;margin-top:12px">
      ${(ev.errores_esquema || []).map((x) => `<div class="regla"><span class="no">${ico("error")}</span>${esc(x)}</div>`).join("")}
      ${(ev.reglas || []).map((x) => `<div class="regla"><span class="${x.ok ? "si" : "no"}">${ico(x.ok ? "ok" : "error")}</span><span>${esc(x.regla)}${x.ok ? "" : ` <span class="muted">— ${esc(x.detalle)}</span>`}</span></div>`).join("")}
      </div></div>` : ""}
    ${r.historial?.length ? `<div class="tarjeta"><h3>Intentos de lectura</h3><div class="tabla-wrap" style="margin-top:8px"><table class="tabla"><thead><tr><th>#</th><th>Modelo</th><th>Resultado</th><th class="n">Seg.</th></tr></thead><tbody>
      ${r.historial.map((h) => `<tr><td>${h.intento}</td><td>${esc(h.modelo)}${h.resultado === "válida" ? "" : `<div class="muted" style="font-size:12.5px">${esc(h.motivo || "")}</div>`}</td><td>${h.resultado === "válida" ? pill("procesada").replace("Procesada", "Válida") : `<span class="pill revision">${esc(h.resultado)}</span>`}</td><td class="n">${h.segundos ?? "—"}</td></tr>`).join("")}
      </tbody></table></div></div>` : ""}
    ${r.texto_ocr ? `<div class="tarjeta"><details><summary>Texto reconocido (OCR)</summary><pre class="bloque" style="margin-top:12px">${esc(r.texto_ocr)}</pre></details></div>` : ""}
    ${bit ? `<div class="tarjeta"><h3>Bitácora del archivo</h3><ol class="bitacora" style="margin-top:8px">${bit}</ol></div>` : ""}`;
  focoPrevio = document.activeElement;
  $("#cajon").hidden = false; $("#dCerrar").focus();
}
const cerrarCajon = () => { $("#cajon").hidden = true; focoPrevio?.focus?.(); };
$("#dCerrar").addEventListener("click", cerrarCajon);
$("#cajon").addEventListener("click", (e) => { if (e.target.id === "cajon") cerrarCajon(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { if (!$("#cajon").hidden) cerrarCajon(); else cerrarMenu(); } });

/* ── Configuración ────────────────────────────────────── */
let cfgActual = "conexion";
$("#cnav").addEventListener("click", (e) => { const b = e.target.closest("button[data-c]"); if (b) history.replaceState(null, "", `#config/${b.dataset.c}`) || abrirConfig(b.dataset.c); });

async function cargarConfig() {
  const r = await api("/api/config");
  config = r.config; config._defecto = r.defecto;
}

async function guardarSeccion(seccion, valor, mensaje = "Cambios guardados") {
  const caja = $("#cErrores");
  try {
    const r = await api(`/api/config/${seccion}`, { method: "PUT", body: JSON.stringify(valor) });
    const def = config._defecto; config = r.config; config._defecto = def;
    if (caja) caja.hidden = true;
    toast(mensaje); await cargarConfig(); refrescarEstado(); return true;
  } catch (e) {
    if (caja) { caja.hidden = false; caja.innerHTML = `<b>No se guardó:</b><ul>${(e.errores || [e.message]).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`; caja.scrollIntoView({ block: "nearest", behavior: "smooth" }); }
    else toast(e.message, true);
    return false;
  }
}

const VISTAS = {};
function abrirConfig(c) {
  cfgActual = c;
  $$("#cnav button").forEach((b) => b.classList.toggle("on", b.dataset.c === c));
  $(`#cnav button[data-c="${c}"]`)?.scrollIntoView({ block: "nearest", inline: "nearest" });
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
const cab = (t, intro) => `<div><h2>${t}</h2><p class="intro">${intro}</p></div>`;

async function bloqueSecreto(nombre, etiqueta, ayuda) {
  const s = (await api("/api/secretos"))[nombre];
  return `<div class="secreto">
    <label class="campo">${esc(etiqueta)} <small>${ayuda}</small>
      <input type="password" id="s_${nombre}" placeholder="${s.configurada ? "••••••••" + esc(s.final) + " (déjala vacía para mantenerla)" : "Pega la clave aquí"}" autocomplete="off"></label>
    <button class="btn" data-guardar-secreto="${nombre}" type="button">${ico("candado")}Guardar clave</button>
    <span class="estado-clave ${s.configurada ? "si" : ""}">${s.configurada ? `Configurada desde ${s.origen === "app" ? "esta app (cifrada)" : "el archivo .env"}, termina en ${esc(s.final)}` : "Sin configurar"}</span>
  </div>`;
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-guardar-secreto]"); if (!b) return;
  const n = b.dataset.guardarSecreto, v = $("#s_" + n).value.trim();
  if (!v) return toast("Escribe la clave primero", true);
  try { await api(`/api/secretos/${n}`, { method: "PUT", body: JSON.stringify({ valor: v }) }); toast("Clave guardada cifrada en el servidor"); abrirConfig(cfgActual); }
  catch (err) { toast(err.message, true); }
});

VISTAS.conexion = async (p) => {
  const d = config.drive;
  p.innerHTML = `<div class="cargando" style="height:220px"></div>`;
  const secreto = await bloqueSecreto("composio_api_key", "API key de Composio Connect", "Empieza con ck_. Las cuentas de Google se conectan en composio.dev.");
  if (!p.isConnected) return; // el usuario ya cambió de sección
  p.innerHTML = `${cab("Conexión con Google Drive", `El sistema usa Composio Connect para leer y mover archivos y escribir la hoja con tu cuenta de Google. Solo trabaja dentro de la carpeta «${esc(d.carpeta_entrada)}» y sus subcarpetas.`)}${errBox}
    <div class="campos"><label class="campo">Origen de las facturas
      <select id="d_prov"><option value="composio">Google Drive (Composio)</option><option value="local">Carpeta local (pruebas)</option></select></label>
      <label class="campo" id="w_local">Carpeta local <small>Solo en modo local. La carpeta «${esc(d.carpeta_entrada)}» va dentro.</small><input type="text" id="d_local" value="${esc(d.carpeta_local)}"></label></div>
    ${secreto}
    <div class="acciones"><button class="btn primario" id="bGuardarCx">Guardar</button><button class="btn" id="bProbarCx">${ico("refrescar")}Probar conexión</button><span class="muted" id="cxEstado"></span></div>
    <div id="cxRes"></div>`;
  $("#d_prov").value = d.proveedor;
  const vis = () => ($("#w_local").hidden = $("#d_prov").value !== "local"); vis(); $("#d_prov").onchange = vis;
  $("#bGuardarCx").onclick = () => guardarSeccion("drive", { ...config.drive, proveedor: $("#d_prov").value, carpeta_local: val("d_local") });
  $("#bProbarCx").onclick = async () => {
    $("#cxEstado").textContent = "Probando la conexión…"; $("#cxRes").innerHTML = ""; $("#bProbarCx").disabled = true;
    try {
      const r = await api("/api/probar/drive", { method: "POST" });
      $("#cxRes").innerHTML = r.ok ? `<div class="ok-box"><b>Conexión correcta</b>
          ${r.cuentas ? Object.entries(r.cuentas).map(([k, v]) => `<span>${k === "googledrive" ? "Google Drive" : "Google Sheets"}: ${esc(v.estado)} ${esc(v.cuenta || "")}</span>`).join("") : ""}
          <span>Carpeta «${esc(r.carpeta)}»: ${r.conteo.pendientes} pendiente(s), ${r.conteo.procesadas} procesada(s), ${r.conteo.revision} en revisión.</span>
          ${r.info.creadas?.length ? `<span>Se crearon: ${esc(r.info.creadas.join(", "))}</span>` : ""}
          <span>Resultados: ${r.resultados?.startsWith("http") ? `<a href="${esc(r.resultados)}" target="_blank" rel="noopener">${esc(config.drive.archivo_resultados)}</a>` : esc(r.resultados)}</span></div>`
        : `<div class="errores"><b>No se pudo conectar:</b> ${esc(r.error)}</div>`;
    } catch (e) { $("#cxRes").innerHTML = `<div class="errores">${esc(e.message)}</div>`; }
    finally { $("#cxEstado").textContent = ""; $("#bProbarCx").disabled = false; refrescarEstado(); }
  };
};

VISTAS.carpetas = (p) => {
  const d = config.drive;
  p.innerHTML = `${cab("Carpetas y hoja de resultados", "Nombres dentro de tu Google Drive. Las subcarpetas y la hoja se crean dentro de la carpeta de entrada si no existen.")}${errBox}
    <div class="campos">
      <label class="campo">Carpeta de entrada <small>Donde subes las facturas</small><input type="text" id="c_ent" value="${esc(d.carpeta_entrada)}"></label>
      <label class="campo">Subcarpeta de procesadas <small>Facturas registradas en la hoja</small><input type="text" id="c_proc" value="${esc(d.carpeta_procesadas)}"></label>
      <label class="campo">Subcarpeta de revisión manual <small>Facturas con datos no confiables</small><input type="text" id="c_rev" value="${esc(d.carpeta_revision)}"></label>
      <label class="campo">Hoja de resultados <small>Google Sheets dentro de la carpeta de entrada</small><input type="text" id="c_res" value="${esc(d.archivo_resultados)}"></label>
    </div>
    <label class="check"><input type="checkbox" id="c_ren" ${d.renombrar_al_mover ? "checked" : ""}> Renombrar al mover a Procesadas (AAAA-MM-DD_Emisor_Número)</label>
    <div class="acciones"><button class="btn primario" id="bG">Guardar</button></div>`;
  $("#bG").onclick = () => guardarSeccion("drive", { ...config.drive, carpeta_entrada: val("c_ent"), carpeta_procesadas: val("c_proc"),
    carpeta_revision: val("c_rev"), archivo_resultados: val("c_res"), renombrar_al_mover: chk("c_ren") });
};

VISTAS.frecuencia = (p) => {
  const f = config.frecuencia;
  p.innerHTML = `${cab("Frecuencia", "Cada cuánto se revisa la carpeta. «Procesar ahora» funciona aunque la revisión automática esté apagada.")}${errBox}
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
  p.innerHTML = `<div class="cargando" style="height:320px"></div>`;
  const ollama = await api("/api/modelos/ollama").catch(() => ({ ok: false }));
  const secreto = await bloqueSecreto("openai_api_key", "API key de OpenAI", "Se usa para el estructurador y el modelo de respaldo.");
  if (!p.isConnected) return; // el usuario ya cambió de sección
  const pinta = () => {
    $("#mLista").innerHTML = m.cadena.map((x, i) => `<div class="modelo ${x.activo ? "" : "inactivo"}" data-i="${i}">
      <div class="modelo-h"><span class="orden">${i === 0 ? "Primario" : "Respaldo " + i}</span><b>${esc(x.nombre)}</b>
        <label class="check"><input type="checkbox" data-k="activo" ${x.activo ? "checked" : ""}> Activo</label>
        <button class="btn sm ghost" data-mov="-1" ${i === 0 ? "disabled" : ""} aria-label="Subir">↑</button><button class="btn sm ghost" data-mov="1" ${i === m.cadena.length - 1 ? "disabled" : ""} aria-label="Bajar">↓</button>
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
        <label class="check" style="align-self:end;min-height:40px"><input type="checkbox" data-k="usar_texto_pdf" ${x.usar_texto_pdf ? "checked" : ""}> Usar el texto del PDF cuando exista</label>` : `
        <label class="campo">Modelo de OpenAI con visión<input type="text" data-k="modelo" value="${esc(x.modelo)}"></label>
        <label class="campo">Detalle de imagen<select data-k="detalle_imagen"><option value="high" ${x.detalle_imagen === "high" ? "selected" : ""}>Alto</option><option value="auto" ${x.detalle_imagen === "auto" ? "selected" : ""}>Automático</option><option value="low" ${x.detalle_imagen === "low" ? "selected" : ""}>Bajo</option></select></label>`}
      </div></div>`).join("");
  };
  p.innerHTML = `${cab("Modelos y API keys", "La cadena va en orden: el primario intenta primero. Si sus datos no pasan la validación, la factura pasa al siguiente modelo con una pista del error. Si ningún modelo responde (caída, sin saldo, clave inválida), el proceso se detiene y la factura queda pendiente.")}${errBox}
    <div id="mLista" style="display:grid;gap:14px"></div>
    <div class="herramientas"><button class="btn sm" id="mAddO">Agregar modelo OpenAI</button><button class="btn sm" id="mAddG">Agregar GLM-OCR</button></div>
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
    const mov = e.target.closest("[data-mov]");
    if (mov) { const j = i + Number(mov.dataset.mov); [m.cadena[i], m.cadena[j]] = [m.cadena[j], m.cadena[i]]; pinta(); }
    if (e.target.closest("[data-quitar]")) { m.cadena.splice(i, 1); pinta(); }
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
  const cabF = filasEsquema(Object.fromEntries(Object.entries(esq.properties).filter(([k]) => k !== campoLineas)), esq.required || []);
  const det = filasEsquema(lin.items.properties, lin.items.required || []);
  const tabla = (filas, id) => `<div class="tabla-wrap"><table class="tabla edit" id="${id}"><thead><tr><th>Campo</th><th>Tipo</th><th>Obligatorio</th><th>Indicación para el modelo</th><th></th></tr></thead><tbody>
    ${filas.map((f, i) => `<tr data-i="${i}"><td style="min-width:150px"><input type="text" data-k="nombre" value="${esc(f.nombre)}" aria-label="Nombre del campo"></td>
      <td style="min-width:120px"><select data-k="tipo" aria-label="Tipo">${Object.entries(TIPOS).map(([v, t]) => `<option value="${v}" ${f.tipo === v ? "selected" : ""}>${t}</option>`).join("")}</select></td>
      <td style="text-align:center"><input type="checkbox" data-k="obligatorio" ${f.obligatorio ? "checked" : ""} aria-label="Obligatorio"></td>
      <td style="min-width:240px"><input type="text" data-k="descripcion" value="${esc(f.descripcion)}" aria-label="Indicación"></td><td><button class="btn sm ghost peligro" data-quitar>Quitar</button></td></tr>`).join("")}
    </tbody></table></div><button class="btn sm" data-agregar="${id}" style="margin-top:10px">Agregar campo</button>`;
  const construir = () => {
    const props = {}; cabF.forEach((f) => { if (f.nombre) props[f.nombre] = aPropiedad(f); });
    const lp = {}; det.forEach((f) => { if (f.nombre) lp[f.nombre] = aPropiedad(f); });
    props[campoLineas] = { ...lin, items: { ...lin.items, type: "object", properties: lp, required: det.filter((f) => f.obligatorio && f.nombre).map((f) => f.nombre) } };
    return { ...esq, properties: props, required: [...cabF.filter((f) => f.obligatorio && f.nombre).map((f) => f.nombre), campoLineas] };
  };
  const pinta = () => { $("#wCab").innerHTML = tabla(cabF, "tCab"); $("#wDet").innerHTML = tabla(det, "tDet"); };
  p.innerHTML = `${cab("Esquema de factura", "Datos que se extraen de cada factura. El esquema alimenta las instrucciones del modelo, la validación del paso 07 y las columnas de la hoja. Los campos de la hoja Facturas siguen el orden de esta tabla.")}${errBox}
    <div><h3>Campos de la factura</h3><div id="wCab" style="margin-top:10px"></div></div>
    <div><h3>Campos de cada línea («${esc(campoLineas)}»)</h3><div id="wDet" style="margin-top:10px"></div></div>
    <details><summary>Editar como JSON Schema</summary><textarea class="json-ed" id="eJson" style="margin-top:12px" aria-label="Esquema JSON"></textarea>
      <div class="herramientas" style="margin-top:10px"><button class="btn" id="bJson">Guardar desde el JSON</button></div></details>
    <div class="acciones"><button class="btn primario" id="bG">Guardar esquema</button><button class="btn ghost" id="bDef">Restablecer al esquema inicial</button></div>`;
  pinta();
  $("#eJson").value = JSON.stringify(esq, null, 2);
  const editar = (ev, filas) => { const tr = ev.target.closest("tr[data-i]"), k = ev.target.dataset.k; if (!tr || !k) return;
    filas[tr.dataset.i][k] = ev.target.type === "checkbox" ? ev.target.checked : ev.target.value; $("#eJson").value = JSON.stringify(construir(), null, 2); };
  p.addEventListener("input", (ev) => { if (ev.target.closest("#tCab")) editar(ev, cabF); if (ev.target.closest("#tDet")) editar(ev, det); });
  p.addEventListener("click", (ev) => {
    const q = ev.target.closest("[data-quitar]");
    if (q) { const tr = q.closest("tr"); (tr.closest("#tCab") ? cabF : det).splice(Number(tr.dataset.i), 1); pinta(); }
    const a = ev.target.closest("[data-agregar]");
    if (a) { (a.dataset.agregar === "tCab" ? cabF : det).push({ nombre: "", tipo: "string", obligatorio: false, descripcion: "" }); pinta(); }
  });
  $("#bG").onclick = () => guardarSeccion("esquema", construir(), "Esquema guardado");
  $("#bJson").onclick = () => { let v; try { v = JSON.parse($("#eJson").value); } catch (e) { return toast("El JSON no es válido: " + e.message, true); }
    guardarSeccion("esquema", v, "Esquema guardado").then((ok) => ok && abrirConfig("esquema")); };
  $("#bDef").onclick = async () => { await api("/api/config/esquema/restablecer", { method: "POST" }); await cargarConfig(); toast("Esquema restablecido"); abrirConfig("esquema"); };
};

VISTAS.validacion = (p) => {
  const v = config.validacion;
  p.innerHTML = `${cab("Reglas de validación", "Una factura solo sigue al catálogo si tiene los campos obligatorios, sus montos cuadran y la confianza del modelo alcanza el mínimo.")}${errBox}
    <div class="campos">
      <label class="campo">Tolerancia por línea <small>cantidad × precio − descuento frente al importe (+0,005 por unidad)</small><input type="number" step="0.01" id="v_tl" value="${v.tolerancia_linea}"></label>
      <label class="campo">Tolerancia en totales <small>Suma de líneas frente al subtotal y cálculo del total</small><input type="number" step="0.01" id="v_tt" value="${v.tolerancia_total}"></label>
      <label class="campo">Confianza mínima del modelo <small>0 desactiva esta regla</small><input type="number" step="0.05" min="0" max="1" id="v_cm" value="${v.confianza_minima}"></label>
    </div>
    <label class="check"><input type="checkbox" id="v_pi" ${v.precios_incluyen_impuesto ? "checked" : ""}> Los precios de las líneas ya incluyen el impuesto</label>
    <details><summary>Campos que usa el cuadre</summary><div class="campos" style="margin-top:12px">${Object.entries(v.campos).map(([k, x]) =>
      `<label class="campo">${esc(k.replace(/_/g, " "))}<input type="text" data-campo="${esc(k)}" value="${esc(x)}"></label>`).join("")}</div></details>
    <div class="acciones"><button class="btn primario" id="bG">Guardar</button></div>`;
  $("#bG").onclick = () => { const campos = {}; $$("[data-campo]").forEach((i) => (campos[i.dataset.campo] = i.value.trim()));
    guardarSeccion("validacion", { tolerancia_linea: num("v_tl"), tolerancia_total: num("v_tt"), confianza_minima: num("v_cm"), precios_incluyen_impuesto: chk("v_pi"), campos }); };
};

VISTAS.catalogo = (p) => {
  const c = structuredClone(config.catalogo);
  const pinta = () => {
    $("#tCat tbody").innerHTML = c.productos.map((x, i) => `<tr data-i="${i}"><td style="min-width:90px"><input type="text" data-k="codigo" value="${esc(x.codigo)}" aria-label="Código"></td>
      <td style="min-width:160px"><input type="text" data-k="producto" value="${esc(x.producto)}" aria-label="Producto"></td>
      <td style="min-width:240px"><input type="text" data-k="palabras_clave" value="${esc((x.palabras_clave || []).join(", "))}" aria-label="Palabras clave"></td>
      <td style="text-align:center"><input type="checkbox" data-k="activo" ${x.activo !== false ? "checked" : ""} aria-label="Activo"></td>
      <td><button class="btn sm ghost peligro" data-quitar>Quitar</button></td></tr>`).join("") ||
      `<tr><td colspan="5"><div class="vacio"><b>Sin productos</b>Agrega uno o importa un CSV.</div></td></tr>`;
    $("#catN").textContent = `${c.productos.length} producto(s)`;
  };
  p.innerHTML = `${cab("Catálogo de productos", "Las líneas de la factura que coinciden con un producto activo suman el «total catálogo». Busca en orden: código exacto, palabra clave o sinónimo, y parecido de texto (tolera errores de tipeo).")}${errBox}
    <div class="tarjeta-h" style="margin:0;align-items:center"><span class="muted" id="catN"></span><div class="herramientas">
      <button class="btn sm" id="cAdd">Agregar producto</button><label class="btn sm">${ico("descargar")}Importar CSV<input type="file" id="cCsv" accept=".csv,text/csv" hidden></label></div></div>
    <div class="tabla-wrap"><table class="tabla edit" id="tCat"><thead><tr><th>Código</th><th>Producto</th><th>Palabras clave y sinónimos (separados por coma)</th><th>Activo</th><th></th></tr></thead><tbody></tbody></table></div>
    <div class="campos">
      <label class="campo">Parecido mínimo (50–100) <small>Más alto = más estricto</small><input type="number" min="50" max="100" id="c_um" value="${c.umbral_parecido}"></label>
      <label class="check" style="align-self:end;min-height:40px"><input type="checkbox" id="c_imp" ${c.total_con_impuesto ? "checked" : ""}> Sumar el total catálogo con impuesto</label>
    </div>
    <div class="secreto"><label class="campo">Probar una descripción<input type="text" id="cProbar" placeholder="Ej.: Varilla corrugada 3/8 x 6 m"></label><button class="btn" id="bProbar">Probar</button><span id="cRes" class="estado-clave" style="display:block"></span></div>
    <div class="acciones"><button class="btn primario" id="bG">Guardar catálogo</button></div>`;
  pinta();
  $("#tCat").addEventListener("input", (e) => { const tr = e.target.closest("tr[data-i]"), k = e.target.dataset.k; if (!tr || !k) return;
    const x = c.productos[tr.dataset.i]; x[k] = k === "activo" ? e.target.checked : k === "palabras_clave" ? e.target.value.split(",").map((s) => s.trim()).filter(Boolean) : e.target.value; });
  $("#tCat").addEventListener("click", (e) => { if (e.target.closest("[data-quitar]")) { c.productos.splice(Number(e.target.closest("tr").dataset.i), 1); pinta(); } });
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
  $("#bProbar").onclick = async () => {
    if (!val("cProbar")) return toast("Escribe una descripción para probar", true);
    await guardarSeccion("catalogo", { ...c, umbral_parecido: num("c_um"), total_con_impuesto: chk("c_imp") }, "Catálogo guardado");
    const r = await api("/api/probar/catalogo", { method: "POST", body: JSON.stringify({ descripcion: val("cProbar") }) });
    $("#cRes").innerHTML = r.coincide ? `<span class="hit">Coincide con ${esc(r.producto)}</span> <span class="muted">(${esc(r.tipo)}${r.tipo === "parecido" ? " " + r.puntaje : ""})</span>` : "No coincide con ningún producto"; };
  $("#bG").onclick = () => guardarSeccion("catalogo", { ...c, umbral_parecido: num("c_um"), total_con_impuesto: chk("c_imp") }, "Catálogo guardado");
};

VISTAS.probar = (p) => {
  p.innerHTML = `${cab("Probar extracción", "Sube una factura desde tu equipo para ver qué extrae cada modelo y si pasa la validación. No toca Google Drive ni la hoja.")}
    <div class="campos"><label class="campo">Archivo (PDF o imagen)<input type="file" id="pArch" accept=".pdf,image/*"></label>
      <label class="campo">Modelo<select id="pMod"><option value="">Cadena completa (como en el proceso)</option>${config.modelos.cadena.filter((m) => m.activo).map((m) => `<option value="${esc(m.id)}">${esc(m.nombre)}</option>`).join("")}</select></label></div>
    <div class="acciones"><button class="btn primario" id="bP">${ico("prueba")}Extraer</button><span class="muted" id="pEst"></span></div><div id="pRes" style="display:grid;gap:14px"></div>`;
  $("#bP").onclick = async () => {
    const f = $("#pArch").files[0]; if (!f) return toast("Elige un archivo", true);
    const fd = new FormData(); fd.append("archivo", f);
    $("#pEst").textContent = "Extrayendo… GLM-OCR en CPU puede tardar alrededor de un minuto por página."; $("#bP").disabled = true; $("#pRes").innerHTML = "";
    try {
      const r = await api(`/api/probar/extraccion${val("pMod") ? "?modelo=" + encodeURIComponent(val("pMod")) : ""}`, { method: "POST", body: fd });
      $("#pRes").innerHTML = !r.ok ? `<div class="errores">${esc(r.error)}</div>` : r.resultados.map((x) => !x.ok
        ? `<div class="errores"><b>${esc(x.modelo)}</b>: ${esc(x.error)}</div>`
        : `<div class="tarjeta"><div class="tarjeta-h"><h3>${esc(x.modelo)} · ${x.segundos} s</h3>${x.evaluacion.valida ? pill("procesada").replace("Procesada", "Válida") : '<span class="pill revision">No válida</span>'}</div>
          ${x.evaluacion.valida ? "" : `<p style="margin:0 0 10px">${esc(x.evaluacion.motivo)}</p>`}
          ${x.catalogo ? `<p style="margin:0 0 10px">Total catálogo: <b class="hit">${dinero(x.catalogo.total_catalogo)}</b> (${x.catalogo.lineas_catalogo} de ${x.catalogo.lineas_total} líneas)</p>` : ""}
          <pre class="bloque">${esc(JSON.stringify(x.datos, null, 2))}</pre>
          ${x.texto_ocr ? `<details style="margin-top:10px"><summary>Texto OCR</summary><pre class="bloque">${esc(x.texto_ocr)}</pre></details>` : ""}</div>`).join("");
    } catch (e) { toast(e.message, true); } finally { $("#pEst").textContent = ""; $("#bP").disabled = false; }
  };
};

/* ── Inicio ───────────────────────────────────────────── */
arrancar();
