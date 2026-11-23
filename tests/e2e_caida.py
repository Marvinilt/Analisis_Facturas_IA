"""Escenario real «modelos caídos»: Ollama inaccesible y un modelo de OpenAI inexistente.

Esperado: la corrida se detiene, ninguna factura se mueve (siguen pendientes) y queda una alerta.
Uso: .venv/Scripts/python tests/e2e_caida.py
"""
from __future__ import annotations

import copy
import os
import shutil
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
os.environ["FACTURAS_IA_DATA"] = tempfile.mkdtemp(prefix="facturas_caida_")

from app import configuracion, db  # noqa: E402
from app.pipeline import Procesador  # noqa: E402

cfg = copy.deepcopy(configuracion.DEFAULT)
base = Path(os.environ["FACTURAS_IA_DATA"]) / "drive"
entrada = base / cfg["drive"]["carpeta_entrada"]
entrada.mkdir(parents=True)
for n in ("factura_02_distribuidora.jpg", "factura_03_papeleria.png"):
    shutil.copy(RAIZ / "tests" / "docs" / n, entrada / n)
cfg["drive"].update(proveedor="local", carpeta_local=str(base))
cfg["modelos"]["cadena"][0]["ollama_url"] = "http://localhost:1"
cfg["modelos"]["cadena"][1]["modelo"] = "modelo-que-no-existe"
cfg["modelos"]["reintentos_tecnicos"] = 0

r = Procesador(config=cfg).correr("prueba caída")
pendientes = sorted(p.name for p in entrada.iterdir() if p.is_file() and p.suffix != ".xlsx")
movidas = [p.name for c in (cfg["drive"]["carpeta_procesadas"], cfg["drive"]["carpeta_revision"]) for p in (entrada / c).iterdir()]
alertas = db.alertas_activas()
print("Estado de la corrida:", r["estado"])
print("Detalle:", r["detalle"])
print("Siguen pendientes:", pendientes)
print("Movidas:", movidas)
print("Alerta:", alertas[0]["mensaje"] if alertas else None)
print("Estados en BD:", db.contar_por_estado())
ok = r["estado"] == "detenida" and len(pendientes) == 2 and not movidas and alertas
print("\nRESULTADO:", "✓ correcto" if ok else "✗ incorrecto")
sys.exit(0 if ok else 1)
