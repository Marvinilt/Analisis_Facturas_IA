"""Estado del sistema en SQLite: archivos, corridas, bitácora de eventos y alertas."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from typing import Any

from .settings import DATA

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

ESQUEMA_SQL = """
CREATE TABLE IF NOT EXISTS archivos (
    file_id TEXT PRIMARY KEY,
    nombre TEXT, mime TEXT, md5 TEXT, tamano INTEGER, enlace TEXT,
    estado TEXT NOT NULL DEFAULT 'pendiente',
    paso TEXT, motivo TEXT, intentos INTEGER DEFAULT 0, modelo TEXT,
    numero_factura TEXT, emisor TEXT, total REAL, total_catalogo REAL,
    datos_json TEXT, resultado_json TEXT,
    corrida_id INTEGER, creado TEXT, actualizado TEXT
);
CREATE TABLE IF NOT EXISTS corridas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inicio TEXT, fin TEXT, estado TEXT, origen TEXT,
    encontrados INTEGER DEFAULT 0, procesadas INTEGER DEFAULT 0, revision INTEGER DEFAULT 0,
    ignorados INTEGER DEFAULT 0, detalle TEXT
);
CREATE TABLE IF NOT EXISTS eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    corrida_id INTEGER, file_id TEXT, ts TEXT, nivel TEXT, paso TEXT, mensaje TEXT
);
CREATE TABLE IF NOT EXISTS alertas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT, nivel TEXT, clave TEXT, mensaje TEXT, activa INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS contadores (clave TEXT PRIMARY KEY, valor TEXT);
CREATE INDEX IF NOT EXISTS ix_archivos_md5 ON archivos(md5);
CREATE INDEX IF NOT EXISTS ix_eventos_corrida ON eventos(corrida_id);
"""


def ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def conexion() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            _conn = sqlite3.connect(DATA / "estado.db", check_same_thread=False, isolation_level=None)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.executescript(ESQUEMA_SQL)
        return _conn


def reiniciar_conexion() -> None:
    """Solo para pruebas: cierra la conexión para abrir otra base."""
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn = None


def _q(sql: str, args: tuple = ()) -> list[dict]:
    with _lock:
        return [dict(r) for r in conexion().execute(sql, args).fetchall()]


def _x(sql: str, args: tuple = ()) -> int:
    with _lock:
        cur = conexion().execute(sql, args)
        return cur.lastrowid


# ── archivos ──────────────────────────────────────────────
def archivo(file_id: str) -> dict | None:
    r = _q("SELECT * FROM archivos WHERE file_id=?", (file_id,))
    return r[0] if r else None


def registrar_archivo(a: dict, corrida_id: int) -> dict:
    actual = archivo(a["id"])
    if actual is None:
        _x("""INSERT INTO archivos(file_id,nombre,mime,md5,tamano,enlace,estado,corrida_id,creado,actualizado)
              VALUES(?,?,?,?,?,?,'pendiente',?,?,?)""",
           (a["id"], a["nombre"], a["mime"], a.get("md5"), a.get("tamano"), a.get("enlace"), corrida_id, ahora(), ahora()))
    else:
        _x("UPDATE archivos SET nombre=?, md5=?, tamano=?, enlace=?, corrida_id=?, actualizado=? WHERE file_id=?",
           (a["nombre"], a.get("md5"), a.get("tamano"), a.get("enlace"), corrida_id, ahora(), a["id"]))
    return archivo(a["id"])


def actualizar_archivo(file_id: str, **campos: Any) -> None:
    if not campos:
        return
    for k in ("datos_json", "resultado_json"):
        if k in campos and not isinstance(campos[k], (str, type(None))):
            campos[k] = json.dumps(campos[k], ensure_ascii=False)
    campos["actualizado"] = ahora()
    sets = ", ".join(f"{k}=?" for k in campos)
    _x(f"UPDATE archivos SET {sets} WHERE file_id=?", (*campos.values(), file_id))


def duplicado_por_md5(md5: str | None, file_id: str) -> dict | None:
    if not md5:
        return None
    r = _q("""SELECT * FROM archivos WHERE md5=? AND file_id<>? AND estado IN ('procesada','escrita')
              ORDER BY actualizado LIMIT 1""", (md5, file_id))
    return r[0] if r else None


def listar_archivos(estado: str | None = None, limite: int = 200) -> list[dict]:
    if estado:
        return _q("SELECT * FROM archivos WHERE estado=? ORDER BY actualizado DESC LIMIT ?", (estado, limite))
    return _q("SELECT * FROM archivos ORDER BY actualizado DESC LIMIT ?", (limite,))


def contar_por_estado() -> dict[str, int]:
    return {r["estado"]: r["n"] for r in _q("SELECT estado, COUNT(*) n FROM archivos GROUP BY estado")}


# ── corridas y eventos ────────────────────────────────────
def nueva_corrida(origen: str) -> int:
    return _x("INSERT INTO corridas(inicio,estado,origen) VALUES(?,?,?)", (ahora(), "en curso", origen))


def cerrar_corrida(cid: int, estado: str, **campos: Any) -> None:
    campos.update(fin=ahora(), estado=estado)
    sets = ", ".join(f"{k}=?" for k in campos)
    _x(f"UPDATE corridas SET {sets} WHERE id=?", (*campos.values(), cid))


def actualizar_corrida(cid: int, **campos: Any) -> None:
    sets = ", ".join(f"{k}=?" for k in campos)
    _x(f"UPDATE corridas SET {sets} WHERE id=?", (*campos.values(), cid))


def corridas(limite: int = 20) -> list[dict]:
    return _q("SELECT * FROM corridas ORDER BY id DESC LIMIT ?", (limite,))


def evento(corrida_id: int | None, file_id: str | None, paso: str, mensaje: str, nivel: str = "info") -> None:
    _x("INSERT INTO eventos(corrida_id,file_id,ts,nivel,paso,mensaje) VALUES(?,?,?,?,?,?)",
       (corrida_id, file_id, ahora(), nivel, paso, mensaje))


def eventos(corrida_id: int | None = None, file_id: str | None = None, limite: int = 300) -> list[dict]:
    if file_id:
        return _q("SELECT * FROM eventos WHERE file_id=? ORDER BY id LIMIT ?", (file_id, limite))
    if corrida_id:
        return _q("SELECT * FROM eventos WHERE corrida_id=? ORDER BY id LIMIT ?", (corrida_id, limite))
    return _q("SELECT * FROM eventos ORDER BY id DESC LIMIT ?", (limite,))


# ── alertas ───────────────────────────────────────────────
def alerta(clave: str, mensaje: str, nivel: str = "error") -> None:
    """Una alerta activa por clave: si ya existe, se actualiza el mensaje."""
    existente = _q("SELECT id FROM alertas WHERE clave=? AND activa=1", (clave,))
    if existente:
        _x("UPDATE alertas SET mensaje=?, ts=?, nivel=? WHERE id=?", (mensaje, ahora(), nivel, existente[0]["id"]))
    else:
        _x("INSERT INTO alertas(ts,nivel,clave,mensaje,activa) VALUES(?,?,?,?,1)", (ahora(), nivel, clave, mensaje))


def cerrar_alerta(clave: str | None = None, alerta_id: int | None = None) -> None:
    if alerta_id is not None:
        _x("UPDATE alertas SET activa=0 WHERE id=?", (alerta_id,))
    elif clave:
        _x("UPDATE alertas SET activa=0 WHERE clave=?", (clave,))


def alertas_activas() -> list[dict]:
    return _q("SELECT * FROM alertas WHERE activa=1 ORDER BY id DESC")


# ── contadores (último conteo leído de Drive) ─────────────
def guardar_contadores(valores: dict[str, Any]) -> None:
    for k, v in valores.items():
        _x("INSERT INTO contadores(clave,valor) VALUES(?,?) ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",
           (k, json.dumps(v)))


def contadores() -> dict[str, Any]:
    return {r["clave"]: json.loads(r["valor"]) for r in _q("SELECT * FROM contadores")}
