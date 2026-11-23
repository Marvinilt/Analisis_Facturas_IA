"""Respaldo de los datos cuando la app corre en Cloudflare Containers, donde el disco se borra al reiniciar.

Solo se activa si existe la variable FACTURAS_IA_RESPALDO_URL, que pone el Worker al arrancar el contenedor.
Esa dirección no sale a internet: el Worker intercepta las peticiones y guarda el respaldo en el
almacenamiento del Durable Object.

- Antes de arrancar la app:  python -m app.nube restaurar   (si falla, el contenedor no arranca, para
  no empezar vacío y pisar luego el respaldo bueno).
- Con la app en marcha: cada 30 s, si cambió la base o algún archivo de configuración, se sube un respaldo.
- Al apagar (SIGTERM): se sube el último respaldo.
"""
from __future__ import annotations

import io
import os
import sqlite3
import sys
import tarfile
import tempfile
import threading
import time
from pathlib import Path

import httpx

from .settings import DATA

URL = os.environ.get("FACTURAS_IA_RESPALDO_URL", "").rstrip("/")
BASE = "estado.db"
ARCHIVOS = ("config.json", "secretos.enc", ".clave")
INTERVALO_S = 30


def activo() -> bool:
    return bool(URL)


# ── paquete ──────────────────────────────────────────────
def empaquetar(datos: Path = DATA) -> bytes:
    """tar.gz con una copia consistente de la base (API de respaldo de SQLite) y los archivos de configuración."""
    buf = io.BytesIO()
    with tempfile.TemporaryDirectory() as tmp:
        copia = Path(tmp) / BASE
        if (datos / BASE).exists():
            origen, destino = sqlite3.connect(datos / BASE), sqlite3.connect(copia)
            try:
                origen.backup(destino)
            finally:
                origen.close()
                destino.close()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            if copia.exists():
                tar.add(copia, BASE)
            for nombre in ARCHIVOS:
                if (datos / nombre).exists():
                    tar.add(datos / nombre, nombre)
    return buf.getvalue()


def desempaquetar(contenido: bytes, datos: Path = DATA) -> list[str]:
    """Restaura solo los nombres conocidos; ignora cualquier otra entrada del paquete."""
    permitidos = {BASE, *ARCHIVOS}
    restaurados = []
    datos.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(contenido), mode="r:gz") as tar:
        for miembro in tar.getmembers():
            if miembro.name not in permitidos or not miembro.isfile():
                continue
            if miembro.name == BASE:
                for sufijo in ("-wal", "-shm"):
                    (datos / f"{BASE}{sufijo}").unlink(missing_ok=True)
            destino = datos / miembro.name
            destino.write_bytes(tar.extractfile(miembro).read())  # type: ignore[union-attr]
            restaurados.append(miembro.name)
    return restaurados


# ── red ──────────────────────────────────────────────────
def descargar() -> bytes | None:
    """Devuelve el último respaldo, o None si todavía no hay ninguno. Reintenta los fallos de red."""
    ultimo: Exception | None = None
    for intento in range(8):
        try:
            r = httpx.get(f"{URL}/respaldo", timeout=30)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.content
        except httpx.HTTPError as e:
            ultimo = e
            time.sleep(min(2 * (intento + 1), 10))
    raise RuntimeError(f"No se pudo leer el respaldo: {ultimo}")


def subir(contenido: bytes) -> None:
    r = httpx.put(f"{URL}/respaldo", content=contenido, headers={"content-type": "application/gzip"}, timeout=60)
    r.raise_for_status()


# ── vigilante ────────────────────────────────────────────
class Respaldo:
    def __init__(self, datos: Path = DATA) -> None:
        self.datos = datos
        self._lock = threading.Lock()
        self._apagar = threading.Event()
        self._hilo: threading.Thread | None = None
        self._vigia: sqlite3.Connection | None = None
        self._huella: tuple | None = None
        self.ultimo: str | None = None
        self.error: str | None = None

    def _version_base(self) -> int:
        # data_version cambia cada vez que otra conexión confirma cambios en la base.
        if self._vigia is None:
            self._vigia = sqlite3.connect(self.datos / BASE, check_same_thread=False)
        return self._vigia.execute("PRAGMA data_version").fetchone()[0]

    def huella(self) -> tuple:
        archivos = []
        for nombre in ARCHIVOS:
            p = self.datos / nombre
            archivos.append((nombre, p.stat().st_mtime_ns, p.stat().st_size) if p.exists() else (nombre,))
        return (self._version_base(), *archivos)

    def guardar(self, forzar: bool = False) -> bool:
        with self._lock:
            actual = self.huella()
            if not forzar and actual == self._huella:
                return False
            try:
                subir(empaquetar(self.datos))
            except Exception as e:  # noqa: BLE001 — se reintenta en la próxima vuelta
                self.error = str(e)
                return False
            self._huella, self.error = actual, None
            self.ultimo = time.strftime("%Y-%m-%dT%H:%M:%S")
            return True

    def iniciar(self) -> None:
        if not activo() or (self._hilo and self._hilo.is_alive()):
            return
        self._huella = self.huella()
        self._hilo = threading.Thread(target=self._bucle, daemon=True, name="respaldo")
        self._hilo.start()

    def _bucle(self) -> None:
        while not self._apagar.wait(INTERVALO_S):
            self.guardar()

    def apagar(self) -> None:
        """Detiene el vigilante y sube los cambios pendientes."""
        if not activo():
            return
        self._apagar.set()
        if self._hilo:
            self._hilo.join(5)
        self.guardar()


respaldo = Respaldo()


def restaurar() -> int:
    if not activo():
        print("Sin FACTURAS_IA_RESPALDO_URL: no hay nada que restaurar.")
        return 0
    contenido = descargar()
    if contenido is None:
        print("Todavía no hay respaldo: la app arranca con datos nuevos.")
        return 0
    print(f"Respaldo restaurado ({len(contenido)} bytes): {', '.join(desempaquetar(contenido))}")
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["restaurar"]:
        try:
            sys.exit(restaurar())
        except Exception as e:  # noqa: BLE001
            print(f"Error al restaurar el respaldo: {e}", file=sys.stderr)
            sys.exit(1)
    if len(sys.argv) == 3 and sys.argv[1] == "empaquetar":
        Path(sys.argv[2]).write_bytes(empaquetar())
        print(f"Respaldo escrito en {sys.argv[2]}")
        sys.exit(0)
    print("Uso: python -m app.nube restaurar | empaquetar <archivo.tar.gz>")
    sys.exit(2)
