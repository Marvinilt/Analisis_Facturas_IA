"""Extracción con modelos de OpenAI (visión directa o estructurado de texto OCR)."""
from __future__ import annotations

import base64
import json
import time
from typing import Any

import openai

from .. import secretos
from .base import Documento, ErrorDocumento, ErrorProveedor, Extractor, ResultadoExtraccion
from .instrucciones import SISTEMA, esquema_estricto, texto_usuario
from .preparar import a_bytes


def _cliente(timeout: float, reintentos: int) -> openai.OpenAI:
    clave = secretos.obtener("openai_api_key")
    if not clave:
        raise ErrorProveedor("Falta la API key de OpenAI (Configuración → Modelos).")
    return openai.OpenAI(api_key=clave, timeout=timeout, max_retries=reintentos)


def _razonamiento(modelo: str) -> dict[str, Any]:
    return {"reasoning_effort": "low"} if modelo.startswith(("gpt-5", "o3", "o4")) else {"temperature": 0}


def llamar_estructurado(modelo: str, contenido: list[dict] | str, esquema: dict, timeout: float = 120,
                        reintentos: int = 2) -> tuple[dict, dict]:
    """Devuelve (respuesta JSON, uso de tokens). Traduce errores de OpenAI a ErrorProveedor / ErrorDocumento."""
    cliente = _cliente(timeout, reintentos)
    try:
        r = cliente.chat.completions.create(
            model=modelo,
            messages=[{"role": "system", "content": SISTEMA}, {"role": "user", "content": contenido}],
            response_format={"type": "json_schema",
                             "json_schema": {"name": "factura", "strict": True, "schema": esquema_estricto(esquema)}},
            **_razonamiento(modelo),
        )
    except openai.AuthenticationError as e:
        raise ErrorProveedor(f"OpenAI rechazó la API key ({modelo}).") from e
    except openai.PermissionDeniedError as e:
        raise ErrorProveedor(f"La cuenta de OpenAI no tiene acceso a {modelo}.") from e
    except openai.NotFoundError as e:
        raise ErrorProveedor(f"El modelo {modelo} no existe en OpenAI.") from e
    except openai.RateLimitError as e:
        codigo = getattr(e, "code", None) or ""
        if "insufficient_quota" in str(e) or codigo == "insufficient_quota":
            raise ErrorProveedor("La cuenta de OpenAI no tiene saldo (insufficient_quota).") from e
        raise ErrorProveedor(f"OpenAI: límite de uso alcanzado tras {reintentos} reintentos.") from e
    except (openai.APIConnectionError, openai.APITimeoutError) as e:
        raise ErrorProveedor(f"No hay conexión con OpenAI ({type(e).__name__}).") from e
    except openai.InternalServerError as e:
        raise ErrorProveedor(f"OpenAI con fallas en su servidor ({e.status_code}).") from e
    except openai.BadRequestError as e:
        msg = str(e)
        if "image" in msg.lower():
            raise ErrorDocumento(f"OpenAI no pudo procesar la imagen: {msg[:200]}", reintentable=False) from e
        raise ErrorProveedor(f"OpenAI rechazó la solicitud: {msg[:300]}") from e
    choice = r.choices[0]
    if getattr(choice.message, "refusal", None):
        raise ErrorDocumento(f"El modelo se negó a responder: {choice.message.refusal}")
    if choice.finish_reason == "length":
        raise ErrorDocumento("La respuesta del modelo quedó incompleta (demasiado larga).")
    try:
        datos = json.loads(choice.message.content or "")
    except json.JSONDecodeError as e:
        raise ErrorDocumento("La respuesta del modelo no es un JSON válido.") from e
    uso = {"entrada": r.usage.prompt_tokens, "salida": r.usage.completion_tokens} if r.usage else {}
    return datos, uso


def a_resultado(respuesta: dict, modelo: str, inicio: float, **extra: Any) -> ResultadoExtraccion:
    return ResultadoExtraccion(
        datos=respuesta.get("factura") or {},
        modelo=modelo,
        segundos=round(time.time() - inicio, 1),
        es_factura=bool(respuesta.get("es_factura", True)),
        confianza=respuesta.get("confianza"),
        observaciones=respuesta.get("observaciones"),
        **extra,
    )


class ExtractorOpenAI(Extractor):
    """Envía las páginas como imágenes (y la capa de texto del PDF, si existe) a un modelo con visión."""

    def __init__(self, cfg: dict[str, Any], timeout: float, reintentos: int):
        self.id = cfg["id"]
        self.nombre = cfg.get("nombre") or cfg["modelo"]
        self.modelo = cfg["modelo"]
        self.detalle = cfg.get("detalle_imagen", "high")
        self.timeout, self.reintentos = timeout, reintentos

    def extraer(self, doc: Documento, esquema: dict, pista: str | None = None) -> ResultadoExtraccion:
        inicio = time.time()
        contenido: list[dict] = [{"type": "text", "text": texto_usuario(pista, texto_pdf=doc.texto_pdf)}]
        for img in doc.paginas:
            b64 = base64.b64encode(a_bytes(img, 2000)).decode()
            contenido.append({"type": "image_url",
                              "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": self.detalle}})
        respuesta, uso = llamar_estructurado(self.modelo, contenido, esquema, self.timeout, self.reintentos)
        return a_resultado(respuesta, f"OpenAI {self.modelo}", inicio, detalle={"tokens": uso})
