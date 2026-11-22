"""Cliente mínimo de Composio Connect (MCP por HTTP, JSON-RPC).

La API key de Composio Connect (prefijo ck_) se envía en la cabecera x-consumer-api-key.
Se usan tres herramientas del servidor MCP:
  - COMPOSIO_PROXY_EXECUTE: llama la API REST de Google Drive / Sheets con la cuenta conectada.
  - COMPOSIO_MULTI_EXECUTE_TOOL: herramientas de Composio (descargar archivo de Drive).
  - COMPOSIO_MANAGE_CONNECTIONS: estado de las cuentas conectadas.
"""
from __future__ import annotations

import itertools
import json
import time
from typing import Any

import httpx

URL = "https://connect.composio.dev/mcp"


class ComposioError(Exception):
    def __init__(self, mensaje: str, temporal: bool = False, estado_http: int | None = None):
        super().__init__(mensaje)
        self.temporal = temporal
        self.estado_http = estado_http


class ComposioMCP:
    def __init__(self, api_key: str, timeout: float = 120, reintentos: int = 3):
        if not api_key:
            raise ComposioError("Falta la API key de Composio. Agrégala en Configuración → Conexión.")
        self._h = {
            "x-consumer-api-key": api_key,
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        self._ids = itertools.count(1)
        self._timeout = timeout
        self._reintentos = reintentos
        self._http = httpx.Client(timeout=timeout)

    # ── JSON-RPC ──────────────────────────────────────────
    def _rpc(self, method: str, params: dict) -> dict:
        cuerpo = {"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params}
        ultimo: Exception | None = None
        for intento in range(self._reintentos + 1):
            try:
                r = self._http.post(URL, json=cuerpo, headers=self._h)
            except httpx.HTTPError as e:
                ultimo = ComposioError(f"No se pudo conectar con Composio: {e}", temporal=True)
            else:
                if r.status_code in (401, 403):
                    raise ComposioError("Composio rechazó la API key. Revísala en Configuración → Conexión.",
                                        estado_http=r.status_code)
                if r.status_code == 429 or r.status_code >= 500:
                    ultimo = ComposioError(f"Composio respondió {r.status_code}", temporal=True, estado_http=r.status_code)
                else:
                    return self._parsear(r)
            if intento < self._reintentos:
                time.sleep(2 * (intento + 1))
        raise ultimo  # type: ignore[misc]

    @staticmethod
    def _parsear(r: httpx.Response) -> dict:
        texto = r.text
        if "application/json" in r.headers.get("content-type", "") and texto.lstrip().startswith("{"):
            return json.loads(texto)
        for linea in texto.splitlines():
            if linea.startswith("data:"):
                return json.loads(linea[5:])
        raise ComposioError(f"Respuesta inesperada de Composio: {texto[:200]}", temporal=True)

    def herramienta(self, nombre: str, argumentos: dict) -> dict:
        """Ejecuta una herramienta MCP y devuelve el JSON de su resultado."""
        resp = self._rpc("tools/call", {"name": nombre, "arguments": argumentos})
        if "error" in resp:
            raise ComposioError(f"Error de Composio: {resp['error'].get('message')}")
        res = resp.get("result", {})
        texto = "".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
        try:
            datos = json.loads(texto)
        except json.JSONDecodeError:
            raise ComposioError(f"Respuesta no JSON de {nombre}: {texto[:200]}", temporal=True)
        if res.get("isError") or not datos.get("successful", True):
            raise ComposioError(f"{nombre} falló: {str(datos.get('error') or texto)[:400]}")
        return datos

    # ── Atajos ────────────────────────────────────────────
    def proxy(self, toolkit: str, endpoint: str, metodo: str = "GET", query: dict | None = None,
              body: Any = None) -> Any:
        args: dict[str, Any] = {"toolkit_slug": toolkit, "endpoint": endpoint, "method": metodo}
        if query:
            args["parameters"] = [{"name": k, "value": str(v), "type": "query"} for k, v in query.items()]
        if body is not None:
            args["body"] = body
        datos = self.herramienta("COMPOSIO_PROXY_EXECUTE", args).get("data", {})
        estado = datos.get("status", 200)
        contenido = datos.get("data")
        if estado >= 400:
            msg = contenido.get("error", {}).get("message") if isinstance(contenido, dict) else str(contenido)[:200]
            raise ComposioError(f"Google respondió {estado}: {msg}", temporal=(estado == 429 or estado >= 500),
                                estado_http=estado)
        return contenido

    def ejecutar(self, slug: str, argumentos: dict) -> dict:
        datos = self.herramienta("COMPOSIO_MULTI_EXECUTE_TOOL", {
            "tools": [{"tool_slug": slug, "arguments": argumentos}],
            "sync_response_to_workbench": False,
            "thought": f"Facturas IA: {slug}",
        })
        resultados = datos.get("data", {}).get("results", [])
        if not resultados:
            raise ComposioError(f"{slug} no devolvió resultado")
        r = resultados[0]
        resp = r.get("response", r)
        if not resp.get("successful", True) or resp.get("error"):
            raise ComposioError(f"{slug} falló: {resp.get('error')}")
        return resp.get("data", resp)

    def conexiones(self, toolkits: list[str]) -> dict:
        datos = self.herramienta("COMPOSIO_MANAGE_CONNECTIONS",
                                 {"toolkits": [{"name": t, "action": "list"} for t in toolkits]})
        return datos.get("data", {}).get("results", {})

    def descargar_url(self, url: str) -> bytes:
        r = self._http.get(url, timeout=self._timeout)
        r.raise_for_status()
        return r.content
