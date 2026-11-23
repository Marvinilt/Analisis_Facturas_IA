/**
 * Facturas IA en Cloudflare: Worker + Durable Object + contenedor con la app de Python.
 *
 *   navegador ─HTTPS─► Worker (facturas.marvinlt.cloud) ─► Durable Object «FacturasApp» ─► contenedor :8000
 *
 * - El Durable Object arranca el contenedor cuando hace falta y le reenvía las peticiones.
 * - El disco del contenedor se borra al reiniciar, así que la app sube un respaldo de sus datos a
 *   http://respaldo.interno. Esa dirección no sale a internet: la intercepta la clase «Almacen» y el
 *   respaldo queda en el almacenamiento SQLite del Durable Object.
 * - Un cron cada 5 minutos («pulso») mantiene despierto el contenedor mientras el procesamiento
 *   programado esté activo o haya una corrida en curso; si no, lo deja dormir tras 15 min sin visitas.
 */
import { DurableObject, WorkerEntrypoint } from "cloudflare:workers";

const PUERTO = 8000;
const HOST_RESPALDO = "respaldo.interno";
const INACTIVIDAD_MS = 30 * 60 * 1000; // red de seguridad: sin actividad del Durable Object, se apaga solo
const REPOSO_MS = 15 * 60 * 1000; // sin programación ni visitas en este tiempo, el pulso lo apaga
const PARTE = 512 * 1024; // el respaldo se guarda en trozos para respetar el tamaño máximo por valor
const INSTANCIA = { vcpu: 0.25, memoryMib: 1024, diskMb: 4000 };
const SIGTERM = 15;

export class FacturasApp extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    if (ctx.container?.running) {
      ctx.blockConcurrencyWhile(() => ctx.container.setInactivityTimeout(INACTIVIDAD_MS));
    }
  }

  // ── arranque ───────────────────────────────────────────
  asegurar() {
    this.arranque ??= this.arrancar().finally(() => { this.arranque = undefined; });
    return this.arranque;
  }

  async arrancar() {
    const c = this.ctx.container;
    let ultimo;
    for (let intento = 0; intento < 240; intento++) {
      if (!c.running) await this.iniciarContenedor();
      try {
        const r = await c.getTcpPort(PUERTO).fetch("http://contenedor/_interno/salud", { signal: AbortSignal.timeout(2000) });
        await r.body?.cancel();
        if (r.ok) return;
        ultimo = new Error(`salud respondió ${r.status}`);
      } catch (e) {
        ultimo = e;
      }
      await scheduler.wait(500);
    }
    throw new Error("El contenedor no respondió a tiempo", { cause: ultimo });
  }

  async iniciarContenedor() {
    const c = this.ctx.container;
    const token = crypto.randomUUID() + crypto.randomUUID();
    await this.ctx.storage.put("token", token);
    // Los intercepts duran lo que dura el contenedor: se registran en cada arranque, antes de start().
    await c.interceptOutboundHttp(HOST_RESPALDO, this.ctx.exports.Almacen({ props: {} }));
    const env = {
      FACTURAS_IA_RESPALDO_URL: `http://${HOST_RESPALDO}`,
      FACTURAS_IA_TOKEN_INTERNO: token,
      TZ: this.env.ZONA_HORARIA || "America/Chicago",
    };
    for (const [destino, origen] of [["OPENAI_APIKEY", "OPENAI_APIKEY"], ["COMPOSIO_APIKEY", "COMPOSIO_APIKEY"],
                                      ["FACTURAS_IA_CODIGO_CONFIGURACION", "CODIGO_CONFIGURACION"]]) {
      if (this.env[origen]) env[destino] = this.env[origen];
    }
    c.start({ image: c.images.base, instance: INSTANCIA, enableInternet: true, env });
    await c.setInactivityTimeout(INACTIVIDAD_MS);
    c.monitor().then(
      () => console.log("El contenedor terminó."),
      (e) => console.log(`El contenedor terminó con error: ${e?.message} (código ${e?.exitCode})`),
    );
  }

  // ── tráfico de la app ──────────────────────────────────
  async fetch(request) {
    await this.ctx.storage.put("ultimaVisita", Date.now());
    await this.asegurar();
    const url = new URL(request.url);
    return this.ctx.container.getTcpPort(PUERTO).fetch(new Request(`http://contenedor${url.pathname}${url.search}`, request));
  }

  async interno(ruta) {
    const token = await this.ctx.storage.get("token");
    return this.ctx.container.getTcpPort(PUERTO).fetch(`http://contenedor${ruta}`, {
      headers: { "x-token-interno": token || "" }, signal: AbortSignal.timeout(10000),
    });
  }

  // ── pulso (cron) ───────────────────────────────────────
  async pulso() {
    const c = this.ctx.container;
    if (!c.running && (await this.ctx.storage.get("programado")) === false) {
      return { estado: "dormido" };
    }
    await this.asegurar();
    const r = await this.interno("/_interno/pulso");
    if (!r.ok) throw new Error(`pulso respondió ${r.status}`);
    const d = await r.json();
    await this.ctx.storage.put("programado", !!d.programado);
    const visita = (await this.ctx.storage.get("ultimaVisita")) || 0;
    if (!d.programado && !d.corriendo && Date.now() - visita > REPOSO_MS) {
      c.signal(SIGTERM); // apagado ordenado: la app sube su último respaldo antes de salir
      return { ...d, estado: "a dormir" };
    }
    return { ...d, estado: "despierto" };
  }

  // ── respaldo ───────────────────────────────────────────
  async leerRespaldo() {
    const meta = await this.ctx.storage.get("respaldo:meta");
    if (!meta) return null;
    const claves = Array.from({ length: meta.partes }, (_, i) => `respaldo:${meta.gen}:${i}`);
    const partes = [];
    for (let i = 0; i < claves.length; i += 128) {
      const lote = await this.ctx.storage.get(claves.slice(i, i + 128));
      for (const k of claves.slice(i, i + 128)) partes.push(lote.get(k));
    }
    const salida = new Uint8Array(meta.tamano);
    let pos = 0;
    for (const p of partes) { salida.set(new Uint8Array(p), pos); pos += p.byteLength; }
    return salida.buffer;
  }

  async guardarRespaldo(contenido) {
    const datos = new Uint8Array(contenido);
    const anterior = await this.ctx.storage.get("respaldo:meta");
    const gen = (anterior?.gen || 0) + 1;
    const partes = Math.max(1, Math.ceil(datos.byteLength / PARTE));
    for (let i = 0; i < partes; i += 128) {
      const lote = {};
      for (let j = i; j < Math.min(partes, i + 128); j++) lote[`respaldo:${gen}:${j}`] = datos.slice(j * PARTE, (j + 1) * PARTE);
      await this.ctx.storage.put(lote);
    }
    const meta = { gen, partes, tamano: datos.byteLength, fecha: new Date().toISOString() };
    await this.ctx.storage.put("respaldo:meta", meta);
    if (anterior) {
      const viejas = Array.from({ length: anterior.partes }, (_, i) => `respaldo:${anterior.gen}:${i}`);
      for (let i = 0; i < viejas.length; i += 128) await this.ctx.storage.delete(viejas.slice(i, i + 128));
    }
    return meta;
  }

  /** Sube datos desde el equipo local: reemplaza el respaldo y reinicia el contenedor sin dejarle guardar encima. */
  async reemplazarRespaldo(contenido) {
    const meta = await this.guardarRespaldo(contenido);
    if (this.ctx.container.running) await this.ctx.container.destroy();
    return meta;
  }

  async infoRespaldo() {
    return (await this.ctx.storage.get("respaldo:meta")) || null;
  }
}

/** Atiende las peticiones del contenedor a http://respaldo.interno (nunca llegan a internet). */
export class Almacen extends WorkerEntrypoint {
  async fetch(request) {
    const url = new URL(request.url);
    const app = this.env.FACTURAS.getByName("principal");
    if (url.pathname !== "/respaldo") return new Response("No encontrado", { status: 404 });
    if (request.method === "GET") {
      const datos = await app.leerRespaldo();
      return datos ? new Response(datos, { headers: { "content-type": "application/gzip" } }) : new Response("Sin respaldo", { status: 404 });
    }
    if (request.method === "PUT") {
      const meta = await app.guardarRespaldo(await request.arrayBuffer());
      return Response.json(meta);
    }
    return new Response("Método no permitido", { status: 405 });
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname.startsWith("/_interno")) return new Response("No encontrado", { status: 404 });
    if (url.pathname === "/_admin/respaldo") return administrar(request, env);

    // Las cabeceras de origen se fijan aquí, pisando lo que mande el cliente: con ellas la app sabe que la
    // petición viene de internet (limita intentos por IP real, marca la cookie como Secure, etc.).
    const ip = request.headers.get("cf-connecting-ip") || "";
    const cabeceras = new Headers(request.headers);
    cabeceras.set("CF-Connecting-IP", ip);
    cabeceras.set("X-Forwarded-For", ip);
    cabeceras.set("X-Forwarded-Proto", "https");
    cabeceras.set("X-Forwarded-Host", url.host);
    try {
      const respuesta = await env.FACTURAS.getByName("principal").fetch(new Request(request, { headers: cabeceras, redirect: "manual" }));
      const r = new Response(respuesta.body, respuesta);
      r.headers.set("Strict-Transport-Security", "max-age=31536000");
      return r;
    } catch (error) {
      console.log(`Sin respuesta del contenedor: ${error?.message}`);
      return new Response(paginaNoDisponible(), {
        status: 503,
        headers: { "content-type": "text/html; charset=utf-8", "retry-after": "30", "cache-control": "no-store" },
      });
    }
  },

  async scheduled(controller, env, ctx) {
    ctx.waitUntil(env.FACTURAS.getByName("principal").pulso().then(
      (r) => console.log(`Pulso: ${JSON.stringify(r)}`),
      (e) => console.log(`Pulso con error: ${e?.message}`),
    ));
  },
};

/** GET descarga el respaldo y PUT lo reemplaza. Exige el token de administración (secreto TOKEN_ADMIN). */
async function administrar(request, env) {
  const enviado = (request.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
  if (!env.TOKEN_ADMIN || !iguales(enviado, env.TOKEN_ADMIN)) return new Response("No autorizado", { status: 401 });
  const app = env.FACTURAS.getByName("principal");
  if (request.method === "GET") {
    const datos = await app.leerRespaldo();
    if (!datos) return new Response("Sin respaldo", { status: 404 });
    return new Response(datos, { headers: { "content-type": "application/gzip", "cache-control": "no-store",
      "content-disposition": 'attachment; filename="facturas-ia-respaldo.tar.gz"' } });
  }
  if (request.method === "PUT") return Response.json(await app.reemplazarRespaldo(await request.arrayBuffer()));
  if (request.method === "HEAD") return new Response(null, { status: (await app.infoRespaldo()) ? 200 : 404 });
  return new Response("Método no permitido", { status: 405 });
}

function iguales(a, b) {
  const x = new TextEncoder().encode(a), y = new TextEncoder().encode(b);
  return x.byteLength === y.byteLength && crypto.subtle.timingSafeEqual(x, y);
}

function paginaNoDisponible() {
  return `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Facturas IA no está disponible</title><style>
:root{color-scheme:light dark}body{margin:0;min-height:100vh;display:grid;place-items:center;font:16px/1.5 system-ui,"Segoe UI",sans-serif;background:#F3F4F8;color:#171B29}
@media (prefers-color-scheme:dark){body{background:#0E1018;color:#ECEEF5}main p{color:#AEB4C6}}
main{max-width:440px;padding:32px 24px}h1{font-size:24px;margin:16px 0 8px}p{margin:0 0 12px;color:#4B5267}
svg{width:44px;height:44px}</style></head><body><main>
<svg viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="8" fill="#4B3FD1"/><path d="M10 7h12v18l-3-2-3 2-3-2-3 2z" fill="#fff"/></svg>
<h1>Facturas IA no está disponible ahora</h1>
<p>El sistema se está iniciando o no respondió a tiempo.</p>
<p>Vuelve a intentarlo en un minuto.</p></main></body></html>`;
}
