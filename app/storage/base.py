"""Interfaz común de almacenamiento: carpeta de facturas + archivo de resultados."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Any

TIPOS_ADMITIDOS = {
    "application/pdf": "PDF",
    "image/jpeg": "JPG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}

HOJA_FACTURAS = "Facturas"
HOJA_DETALLE = "Detalle"
HOJA_ERRORES = "Errores"


class AlmacenError(Exception):
    """Error del almacenamiento. temporal=True si conviene reintentar más tarde (red, cuota)."""

    def __init__(self, mensaje: str, temporal: bool = False):
        super().__init__(mensaje)
        self.temporal = temporal


@dataclass
class ArchivoDrive:
    id: str
    nombre: str
    mime: str
    tamano: int | None = None
    md5: str | None = None
    creado: str | None = None
    enlace: str | None = None

    @property
    def admitido(self) -> bool:
        return self.mime in TIPOS_ADMITIDOS

    def dict(self) -> dict[str, Any]:
        return asdict(self)


class Almacen(ABC):
    """Todas las operaciones se limitan a la carpeta de entrada y sus subcarpetas."""

    @abstractmethod
    def preparar(self) -> dict[str, Any]:
        """Ubica la carpeta de entrada, crea subcarpetas y archivo de resultados si faltan."""

    @abstractmethod
    def listar_entrada(self) -> list[ArchivoDrive]:
        """Archivos (no carpetas) que están directamente en la carpeta de entrada."""

    @abstractmethod
    def contar(self, destino: str) -> int:
        """Cantidad de archivos en 'procesadas' o 'revision'."""

    @abstractmethod
    def descargar(self, archivo: ArchivoDrive) -> bytes: ...

    @abstractmethod
    def mover(self, archivo: ArchivoDrive, destino: str, nuevo_nombre: str | None = None) -> None:
        """destino: 'procesadas' | 'revision'."""

    @abstractmethod
    def leer_hoja(self, hoja: str) -> list[list[Any]]:
        """Filas de la hoja incluyendo encabezado. Lista vacía si la hoja no existe o está vacía."""

    @abstractmethod
    def agregar_filas(self, hoja: str, filas: list[dict[str, Any]]) -> None:
        """Agrega filas alineadas por nombre de columna; agrega columnas nuevas al final del encabezado."""

    @abstractmethod
    def enlace_resultados(self) -> str | None: ...

    def describir(self) -> dict[str, Any]:
        return {}


def alinear(encabezado: list[str], filas: list[dict[str, Any]]) -> tuple[list[str], list[list[Any]]]:
    """Devuelve el encabezado ampliado con columnas nuevas y las filas ordenadas según él."""
    nuevo = list(encabezado)
    for f in filas:
        for k in f:
            if k not in nuevo:
                nuevo.append(k)
    return nuevo, [[f.get(c, "") for c in nuevo] for f in filas]
