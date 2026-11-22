"""Tipos comunes de la extracción."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from PIL import Image


class ErrorProveedor(Exception):
    """El modelo no está disponible (caída, sin saldo, API key inválida, Ollama apagado).

    No dice nada de la factura: si todos los modelos fallan así, el proceso se detiene
    y la factura queda pendiente.
    """


class ErrorDocumento(Exception):
    """El documento no permite obtener datos (dañado, protegido, ilegible, no es factura, JSON inválido).

    reintentable=False cuando otro modelo tampoco podría (por ejemplo, PDF con contraseña).
    """

    def __init__(self, mensaje: str, reintentable: bool = True):
        super().__init__(mensaje)
        self.reintentable = reintentable


@dataclass
class Documento:
    nombre: str
    mime: str
    datos: bytes
    paginas: list[Image.Image] = field(default_factory=list)
    texto_pdf: str = ""
    total_paginas: int = 0


@dataclass
class ResultadoExtraccion:
    datos: dict[str, Any]
    modelo: str
    segundos: float
    es_factura: bool = True
    confianza: float | None = None
    observaciones: str | None = None
    texto_ocr: str | None = None
    detalle: dict[str, Any] = field(default_factory=dict)


class Extractor:
    id: str = ""
    nombre: str = ""

    def extraer(self, doc: Documento, esquema: dict, pista: str | None = None) -> ResultadoExtraccion:
        raise NotImplementedError
