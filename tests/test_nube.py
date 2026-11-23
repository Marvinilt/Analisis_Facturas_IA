"""Respaldo de datos para el contenedor de Cloudflare (app/nube.py), con un servidor de respaldo falso."""
from __future__ import annotations

import io
import sqlite3
import sys
import tarfile
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app import nube  # noqa: E402


def _datos() -> Path:
    d = Path(tempfile.mkdtemp(prefix="facturas_nube_"))
    con = sqlite3.connect(d / "estado.db")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE t (x TEXT)")
    con.execute("INSERT INTO t VALUES ('hola')")
    con.commit()
    con.close()
    (d / "config.json").write_text('{"a": 1}', encoding="utf-8")
    return d


def test_empaquetar_y_restaurar_ida_y_vuelta():
    origen = _datos()
    paquete = nube.empaquetar(origen)
    destino = Path(tempfile.mkdtemp(prefix="facturas_nube_dest_"))
    (destino / "estado.db-wal").write_bytes(b"basura vieja")
    assert sorted(nube.desempaquetar(paquete, destino)) == ["config.json", "estado.db"]
    assert not (destino / "estado.db-wal").exists()
    con = sqlite3.connect(destino / "estado.db")
    assert con.execute("SELECT x FROM t").fetchone()[0] == "hola"
    con.close()
    assert (destino / "config.json").read_text(encoding="utf-8") == '{"a": 1}'


def test_desempaquetar_ignora_nombres_ajenos():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for nombre, datos in (("../fuera.txt", b"x"), ("otro.py", b"y"), ("config.json", b"{}")):
            info = tarfile.TarInfo(nombre)
            info.size = len(datos)
            tar.addfile(info, io.BytesIO(datos))
    destino = Path(tempfile.mkdtemp(prefix="facturas_nube_dest_"))
    assert nube.desempaquetar(buf.getvalue(), destino) == ["config.json"]
    assert not (destino.parent / "fuera.txt").exists() and not (destino / "otro.py").exists()


def test_vigilante_sube_solo_si_hay_cambios(monkeypatch):
    datos = _datos()
    subidos: list[bytes] = []
    monkeypatch.setattr(nube, "subir", subidos.append)
    r = nube.Respaldo(datos)
    r._huella = r.huella()
    assert r.guardar() is False and subidos == []
    con = sqlite3.connect(datos / "estado.db")
    con.execute("INSERT INTO t VALUES ('nuevo')")
    con.commit()
    con.close()
    assert r.guardar() is True and len(subidos) == 1
    assert r.guardar() is False and len(subidos) == 1
    (datos / "secretos.enc").write_bytes(b"cifrado")
    assert r.guardar() is True and len(subidos) == 2
    assert r.ultimo and r.error is None


def test_vigilante_reintenta_si_falla_la_subida(monkeypatch):
    datos = _datos()

    def falla(_contenido):
        raise RuntimeError("sin red")

    monkeypatch.setattr(nube, "subir", falla)
    r = nube.Respaldo(datos)
    r._huella = ()
    assert r.guardar() is False and r.error == "sin red"
    subidos: list[bytes] = []
    monkeypatch.setattr(nube, "subir", subidos.append)
    assert r.guardar() is True and len(subidos) == 1 and r.error is None
