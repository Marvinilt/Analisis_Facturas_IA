"""GLM-OCR en local (Ollama) + un estructurador que convierte el texto al JSON del esquema.

1. Si el PDF trae capa de texto, se usa directamente (no hace falta OCR).
2. Si no, GLM-OCR lee cada página con el prompt "Text Recognition:".
3. El texto pasa al estructurador:
   - "openai": un modelo de texto económico con salida estructurada estricta (recomendado).
   - "glm_ocr_json": GLM-OCR devuelve directamente el JSON a partir de la imagen (100 % local, menos preciso).
"""
from __future__ import annotations

import base64
import time
from typing import Any

import httpx

from .base import Documento, ErrorDocumento, ErrorProveedor, Extractor, ResultadoExtraccion
from .instrucciones import parsear_json, plantilla_simple, texto_usuario
from .openai_ext import a_resultado, llamar_estructurado
from .preparar import a_bytes

MIN_TEXTO = 60


class ExtractorGLMOCR(Extractor):
    def __init__(self, cfg: dict[str, Any], timeout: float, reintentos: int):
        self.id = cfg["id"]
        self.nombre = cfg.get("nombre") or "GLM-OCR"
        self.url = cfg.get("ollama_url", "http://localhost:11434").rstrip("/")
        self.modelo = cfg.get("modelo", "glm-ocr")
        self.lado = int(cfg.get("lado_maximo_px", 1000))
        self.usar_texto_pdf = cfg.get("usar_texto_pdf", True)
        self.estructurador = cfg.get("estructurador", "openai")
        self.modelo_estructurador = cfg.get("modelo_estructurador", "gpt-5.4-nano")
        self.timeout, self.reintentos = timeout, reintentos

    # ── Ollama ────────────────────────────────────────────
    def _generar(self, prompt: str, imagen: bytes) -> str:
        cuerpo = {"model": self.modelo, "prompt": prompt, "images": [base64.b64encode(imagen).decode()],
                  "stream": False, "options": {"temperature": 0}}
        ultimo: Exception | None = None
        for intento in range(self.reintentos + 1):
            try:
                r = httpx.post(f"{self.url}/api/generate", json=cuerpo, timeout=self.timeout)
            except httpx.ConnectError as e:
                raise ErrorProveedor(f"Ollama no responde en {self.url}. ¿Está abierto?") from e
            except httpx.TimeoutException as e:
                ultimo = ErrorProveedor(f"GLM-OCR tardó más de {self.timeout:.0f} s en responder.")
            else:
                if r.status_code == 404:
                    raise ErrorProveedor(f"El modelo {self.modelo} no está instalado en Ollama (ollama pull {self.modelo}).")
                if r.status_code >= 500:
                    ultimo = ErrorProveedor(f"Ollama devolvió {r.status_code}: {r.text[:200]}")
                elif r.status_code >= 400:
                    raise ErrorDocumento(f"Ollama rechazó la imagen: {r.text[:200]}")
                else:
                    return r.json().get("response", "")
            if intento < self.reintentos:
                time.sleep(2 * (intento + 1))
        raise ultimo  # type: ignore[misc]

    def ocr(self, doc: Documento) -> tuple[str, str]:
        """Devuelve (texto, origen) donde origen es 'pdf' o 'glm-ocr'."""
        if self.usar_texto_pdf and len(doc.texto_pdf.strip()) >= MIN_TEXTO:
            return doc.texto_pdf, "pdf"
        textos = []
        for i, img in enumerate(doc.paginas, 1):
            t = self._generar("Text Recognition:", a_bytes(img, self.lado)).strip()
            textos.append(f"--- Página {i} ---\n{t}" if len(doc.paginas) > 1 else t)
        return "\n\n".join(textos), "glm-ocr"

    # ── Extractor ─────────────────────────────────────────
    def extraer(self, doc: Documento, esquema: dict, pista: str | None = None) -> ResultadoExtraccion:
        inicio = time.time()
        texto, origen = self.ocr(doc)
        letras = sum(ch.isalnum() for ch in texto)
        if letras < MIN_TEXTO:
            raise ErrorDocumento("GLM-OCR no reconoce texto suficiente: la imagen parece ilegible.")
        detalle = {"origen_texto": origen, "segundos_ocr": round(time.time() - inicio, 1)}

        if self.estructurador == "glm_ocr_json":
            prompt = "请按下列JSON格式输出图中信息:\n" + plantilla_simple(esquema)
            crudo = self._generar(prompt, a_bytes(doc.paginas[0], self.lado))
            try:
                datos = parsear_json(crudo)
            except ValueError as e:
                raise ErrorDocumento("GLM-OCR no devolvió un JSON válido.") from e
            return ResultadoExtraccion(datos=datos, modelo=f"GLM-OCR local (JSON directo)",
                                       segundos=round(time.time() - inicio, 1), texto_ocr=texto, detalle=detalle)

        respuesta, uso = llamar_estructurado(self.modelo_estructurador, texto_usuario(pista, texto_ocr=texto),
                                             esquema, self.timeout, self.reintentos)
        detalle["tokens"] = uso
        nombre = "Texto del PDF" if origen == "pdf" else "GLM-OCR local"
        return a_resultado(respuesta, f"{nombre} + {self.modelo_estructurador}", inicio, texto_ocr=texto, detalle=detalle)
