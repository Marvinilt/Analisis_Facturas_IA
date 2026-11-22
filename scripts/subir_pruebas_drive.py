"""Sube los documentos de prueba a la carpeta de entrada en Google Drive (vía Composio).

Uso:  .venv/Scripts/python scripts/subir_pruebas_drive.py [archivo ...]
Sin argumentos sube todos los de tests/docs (excepto esperado.json), la copia duplicada al final.

Composio Connect no acepta archivos locales directamente: cada archivo se envía en base64 al
workbench remoto de Composio, se publica en su almacenamiento temporal y desde ahí
GOOGLEDRIVE_UPLOAD_FILE lo deja dentro de la carpeta de entrada.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app import configuracion, secretos  # noqa: E402
from app.storage.drive_composio import DriveComposio  # noqa: E402

DOCS = RAIZ / "tests" / "docs"

CODIGO = '''
import base64, json
ruta = "/tmp/" + {nombre!r}
open(ruta, "wb").write(base64.b64decode({b64!r}))
sub, err = upload_local_file(ruta)
if err:
    print(json.dumps({{"error": str(err)}}))
else:
    r, e = run_composio_tool("GOOGLEDRIVE_UPLOAD_FILE", {{
        "file_to_upload": {{"name": {nombre!r}, "mimetype": {mime!r}, "s3key": sub["s3key"]}},
        "folder_to_upload_to": {carpeta!r}}})
    datos = (r or {{}}).get("data", r) if isinstance(r, dict) else r
    print("RESULTADO=" + json.dumps({{"error": str(e) if e else None, "id": (datos or {{}}).get("id")}}))
'''


def main() -> None:
    cfg = configuracion.cargar()["drive"]
    alm = DriveComposio(cfg, secretos.obtener("composio_api_key"))
    info = alm.preparar()
    carpeta = info["carpeta_id"]
    nombres = sys.argv[1:] or sorted((p.name for p in DOCS.iterdir() if p.name != "esperado.json"),
                                     key=lambda n: (n == "factura_01_copia.pdf", n))
    print(f"Carpeta «{cfg['carpeta_entrada']}» ({carpeta}). Subiendo {len(nombres)} archivo(s)…")
    for nombre in nombres:
        datos = (DOCS / nombre).read_bytes()
        mime = mimetypes.guess_type(nombre)[0] or "application/octet-stream"
        codigo = CODIGO.format(nombre=nombre, b64=base64.b64encode(datos).decode(), mime=mime, carpeta=carpeta)
        r = alm.c.herramienta("COMPOSIO_REMOTE_WORKBENCH", {"code_to_execute": codigo, "thought": f"Subir {nombre}",
                                                             "current_step": "SUBIR_PRUEBAS"})
        salida = r.get("data", {}).get("stdout", "")
        linea = next((l for l in salida.splitlines() if l.startswith("RESULTADO=")), None)
        res = json.loads(linea.split("=", 1)[1]) if linea else {"error": salida[-300:] or r.get("data", {}).get("error")}
        print(f"  {'✓' if res.get('id') else '✗'} {nombre:34s} {res.get('id') or res.get('error')}")


if __name__ == "__main__":
    main()
