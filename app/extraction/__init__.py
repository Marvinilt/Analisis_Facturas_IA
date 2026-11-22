from __future__ import annotations

from typing import Any

from .base import Documento, ErrorDocumento, ErrorProveedor, Extractor, ResultadoExtraccion  # noqa: F401


def crear_cadena(cfg_modelos: dict[str, Any]) -> list[Extractor]:
    """Extractores activos en el orden configurado (primario primero)."""
    from .glm_ocr import ExtractorGLMOCR
    from .openai_ext import ExtractorOpenAI

    timeout = float(cfg_modelos.get("timeout_segundos", 240))
    reintentos = int(cfg_modelos.get("reintentos_tecnicos", 2))
    cadena: list[Extractor] = []
    for m in cfg_modelos.get("cadena", []):
        if not m.get("activo", True):
            continue
        if m["tipo"] == "glm_ocr":
            cadena.append(ExtractorGLMOCR(m, timeout, reintentos))
        elif m["tipo"] == "openai":
            cadena.append(ExtractorOpenAI(m, timeout, reintentos))
    return cadena
