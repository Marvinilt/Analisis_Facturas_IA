"""Almacenamiento local que imita Drive: útil para pruebas sin conexión.

<carpeta_local>/<carpeta_entrada>/            facturas por procesar
<carpeta_local>/<carpeta_entrada>/Procesadas/
<carpeta_local>/<carpeta_entrada>/Revisión manual/
<carpeta_local>/<carpeta_entrada>/<archivo_resultados>.xlsx
"""
from __future__ import annotations

import hashlib
import mimetypes
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook

from ..settings import ROOT
from .base import Almacen, AlmacenError, ArchivoDrive, alinear

mimetypes.add_type("image/webp", ".webp")


class DriveLocal(Almacen):
    def __init__(self, cfg_drive: dict[str, Any]):
        self.cfg = cfg_drive
        base = Path(cfg_drive.get("carpeta_local") or "data/drive_local")
        self.base = base if base.is_absolute() else ROOT / base
        self.entrada = self.base / cfg_drive["carpeta_entrada"]
        self.carpetas = {"procesadas": self.entrada / cfg_drive["carpeta_procesadas"],
                         "revision": self.entrada / cfg_drive["carpeta_revision"]}
        self.xlsx = self.entrada / f"{cfg_drive['archivo_resultados']}.xlsx"
        self._lock = threading.Lock()

    def preparar(self) -> dict[str, Any]:
        if not self.entrada.exists():
            raise AlmacenError(f"No existe la carpeta local «{self.entrada}».")
        for c in self.carpetas.values():
            c.mkdir(exist_ok=True)
        if not self.xlsx.exists():
            wb = Workbook()
            wb.active.title = "Facturas"
            wb.save(self.xlsx)
        return {"carpeta_id": str(self.entrada), "resultados": str(self.xlsx), "creadas": []}

    def _info(self, p: Path) -> ArchivoDrive:
        datos = p.read_bytes()
        mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        return ArchivoDrive(id=f"local:{p.name}:{hashlib.md5(datos).hexdigest()[:8]}", nombre=p.name, mime=mime,
                            tamano=len(datos), md5=hashlib.md5(datos).hexdigest(),
                            creado=datetime.fromtimestamp(p.stat().st_mtime).isoformat(), enlace=p.as_uri())

    def listar_entrada(self) -> list[ArchivoDrive]:
        archivos = [self._info(p) for p in sorted(self.entrada.iterdir())
                    if p.is_file() and p.resolve() != self.xlsx.resolve() and not p.name.startswith("~$")]
        return sorted(archivos, key=lambda a: (a.creado or "", a.nombre))

    def contar(self, destino: str) -> int:
        return sum(1 for p in self.carpetas[destino].iterdir() if p.is_file())

    def _ruta(self, archivo: ArchivoDrive) -> Path:
        p = self.entrada / archivo.nombre
        if not p.exists():
            raise AlmacenError(f"«{archivo.nombre}» ya no está en la carpeta de entrada.")
        return p

    def descargar(self, archivo: ArchivoDrive) -> bytes:
        return self._ruta(archivo).read_bytes()

    def mover(self, archivo: ArchivoDrive, destino: str, nuevo_nombre: str | None = None) -> None:
        origen = self._ruta(archivo)
        final = self.carpetas[destino] / (nuevo_nombre or archivo.nombre)
        if final.exists():
            final = final.with_name(f"{final.stem}_{datetime.now():%H%M%S}{final.suffix}")
        shutil.move(origen, final)

    def leer_hoja(self, hoja: str) -> list[list[Any]]:
        with self._lock:
            wb = load_workbook(self.xlsx)
            if hoja not in wb.sheetnames:
                return []
            filas = [list(r) for r in wb[hoja].iter_rows(values_only=True)]
            return [f for f in filas if any(c not in (None, "") for c in f)]

    def agregar_filas(self, hoja: str, filas: list[dict[str, Any]]) -> None:
        if not filas:
            return
        with self._lock:
            wb = load_workbook(self.xlsx)
            ws = wb[hoja] if hoja in wb.sheetnames else wb.create_sheet(hoja)
            actuales = [list(r) for r in ws.iter_rows(values_only=True) if any(c not in (None, "") for c in r)]
            encabezado = [str(x) for x in actuales[0]] if actuales else []
            nuevo, valores = alinear(encabezado, filas)
            for i, nombre in enumerate(nuevo, 1):
                ws.cell(row=1, column=i, value=nombre)
            fila = max(len(actuales), 1) + 1
            for v in valores:
                for i, celda in enumerate(v, 1):
                    ws.cell(row=fila, column=i, value=celda)
                fila += 1
            wb.save(self.xlsx)

    def enlace_resultados(self) -> str | None:
        return str(self.xlsx)

    def describir(self) -> dict[str, Any]:
        return {"proveedor": "Carpeta local", "carpeta": str(self.entrada), "resultados": str(self.xlsx)}
