/**
 * Facturas IA en Cloudflare: reenvía cada petición a la app local por Workers VPC (túnel «facturas-ia»).
 *
 * Las cabeceras de origen se fijan aquí, pisando lo que mande el cliente, porque la app las usa para
 * saber que la petición viene de internet: con ellas no permite crear la primera cuenta, limita los
 * intentos de acceso por IP real y marca la cookie de sesión como Secure.
 */
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const ip = request.headers.get("cf-connecting-ip") || "";
    const cabeceras = new Headers(request.headers);
    cabeceras.set("CF-Connecting-IP", ip);
    cabeceras.set("X-Forwarded-For", ip);
    cabeceras.set("X-Forwarded-Proto", "https");
    cabeceras.set("X-Forwarded-Host", url.host);

    const destino = new URL(url.pathname + url.search, "http://127.0.0.1:8000");
    try {
      const respuesta = await env.APP.fetch(destino, {
        method: request.method,
        headers: cabeceras,
        body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
        redirect: "manual",
      });
      const r = new Response(respuesta.body, respuesta);
      r.headers.set("Strict-Transport-Security", "max-age=31536000");
      return r;
    } catch (error) {
      return new Response(paginaNoDisponible(), {
        status: 503,
        headers: { "content-type": "text/html; charset=utf-8", "retry-after": "60", "cache-control": "no-store" },
      });
    }
  },
};

function paginaNoDisponible() {
  return `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Facturas IA no está disponible</title><style>
:root{color-scheme:light dark}body{margin:0;min-height:100vh;display:grid;place-items:center;font:16px/1.5 system-ui,"Segoe UI",sans-serif;background:#F3F4F8;color:#171B29}
@media (prefers-color-scheme:dark){body{background:#0E1018;color:#ECEEF5}main p{color:#AEB4C6}}
main{max-width:440px;padding:32px 24px}h1{font-size:24px;margin:16px 0 8px}p{margin:0 0 12px;color:#4B5267}
svg{width:44px;height:44px}</style></head><body><main>
<svg viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="8" fill="#4B3FD1"/><path d="M10 7h12v18l-3-2-3 2-3-2-3 2z" fill="#fff"/></svg>
<h1>Facturas IA no está disponible ahora</h1>
<p>El equipo donde corre el sistema está apagado, o el túnel de Cloudflare no está conectado.</p>
<p>Vuelve a intentarlo en unos minutos.</p></main></body></html>`;
}
