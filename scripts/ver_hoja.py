"""Muestra el contenido de la hoja de resultados y de las carpetas en Drive (solo lectura)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import configuracion  # noqa: E402
from app.storage import crear_almacen  # noqa: E402

alm = crear_almacen(configuracion.cargar()["drive"])
info = alm.preparar()
print("Hoja:", alm.enlace_resultados())
for hoja in ("Facturas", "Detalle", "Errores"):
    filas = alm.leer_hoja(hoja)
    print(f"\n== {hoja}: {max(len(filas) - 1, 0)} fila(s)")
    for f in filas[:40]:
        print(" | ".join(str(x) for x in f)[:260])
print("\nPendientes:", [a.nombre for a in alm.listar_entrada()])
print("Procesadas:", alm.contar("procesadas"), "· Revisión:", alm.contar("revision"))
