"""Prueba de punta a punta con modelos reales y compara contra tests/docs/esperado.json.

  Local (carpeta simulada, no toca Drive):   .venv/Scripts/python tests/e2e.py local
  Drive (usa la configuración guardada):     .venv/Scripts/python tests/e2e.py drive

En modo drive los documentos ya deben estar subidos a «Facturas IA» (scripts/subir_pruebas_drive.py).
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
MODO = sys.argv[1] if len(sys.argv) > 1 else "local"
if MODO == "local":
    os.environ["FACTURAS_IA_DATA"] = tempfile.mkdtemp(prefix="facturas_e2e_")

from app import configuracion, db  # noqa: E402
from app.pipeline import Procesador  # noqa: E402

DOCS = Path(__file__).parent / "docs"
ESPERADO = json.loads((DOCS / "esperado.json").read_text(encoding="utf-8"))


def preparar_local(cfg: dict) -> None:
    base = Path(os.environ["FACTURAS_IA_DATA"]) / "drive"
    entrada = base / cfg["drive"]["carpeta_entrada"]
    entrada.mkdir(parents=True)
    t = time.time() - 3600
    for i, nombre in enumerate(sorted(ESPERADO, key=lambda n: (n == "factura_01_copia.pdf", n))):
        destino = entrada / nombre
        shutil.copy(DOCS / nombre, destino)
        os.utime(destino, (t + i, t + i))  # la copia llega al final
    cfg["drive"].update(proveedor="local", carpeta_local=str(base))


def main() -> int:
    cfg = configuracion.cargar() if MODO == "drive" else copy.deepcopy(configuracion.DEFAULT)
    if MODO == "local":
        preparar_local(cfg)
    inicio = time.time()

    def informar(paso, archivo):
        if paso:
            print(f"  [{time.time() - inicio:6.1f}s] {paso} {archivo or ''}", flush=True)

    resumen = Procesador(config=cfg, informar=informar).correr("prueba e2e")
    print("\nResumen:", json.dumps(resumen, ensure_ascii=False))

    archivos = {a["nombre"]: a for a in db.listar_archivos(limite=500)}
    fallas = 0
    print(f"\n{'Archivo':34s} {'Esperado':10s} {'Obtenido':10s} {'Total':>9s} {'Catálogo':>9s}  Modelo / motivo")
    for nombre, esp in ESPERADO.items():
        a = archivos.get(nombre)
        if esp["resultado"] == "ignorado":
            ok = a is None
            print(f"{nombre:34s} {'ignorado':10s} {'ignorado' if ok else a['estado']:10s}")
            fallas += not ok
            continue
        if a is None:
            print(f"{nombre:34s} {esp['resultado']:10s} {'—':10s}  no se procesó")
            fallas += 1
            continue
        obtenido = "procesada" if a["estado"] == "procesada" else ("revision" if a["estado"] == "revision" else a["estado"])
        ok = obtenido == esp["resultado"]
        if ok and obtenido == "procesada":
            ok = (abs((a["total"] or 0) - esp["total"]) < 0.01 and abs((a["total_catalogo"] or 0) - esp["total_catalogo"]) < 0.01
                  and a["numero_factura"] == esp["numero_factura"])
        detalle = a["modelo"] if obtenido == "procesada" else (a["motivo"] or "")[:90]
        print(f"{'✓' if ok else '✗'} {nombre:32s} {esp['resultado']:10s} {obtenido:10s} {a['total'] or 0:9.2f} "
              f"{a['total_catalogo'] or 0:9.2f}  {detalle}")
        if not ok:
            fallas += 1
            if obtenido == "procesada":
                print(f"     esperado total {esp['total']} catálogo {esp['total_catalogo']} número {esp['numero_factura']};"
                      f" obtenido número {a['numero_factura']}")
    print(f"\n{len(ESPERADO) - fallas} de {len(ESPERADO)} casos correctos en {time.time() - inicio:.0f} s")
    if MODO == "local":
        print("Hoja de resultados:", db.contadores().get("resultados"))
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())
