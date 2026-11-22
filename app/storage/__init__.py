from __future__ import annotations

from typing import Any

from .. import secretos
from .base import Almacen, AlmacenError, ArchivoDrive, TIPOS_ADMITIDOS  # noqa: F401


def crear_almacen(cfg_drive: dict[str, Any]) -> Almacen:
    if cfg_drive.get("proveedor") == "local":
        from .local import DriveLocal
        return DriveLocal(cfg_drive)
    from .drive_composio import DriveComposio
    clave = secretos.obtener("composio_api_key")
    if not clave:
        raise AlmacenError("Falta la API key de Composio. Agrégala en Configuración → Conexión.")
    return DriveComposio(cfg_drive, clave)
