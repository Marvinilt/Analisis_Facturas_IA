"""Inicio de sesión: usuarios con contraseña (scrypt), sesiones por cookie y límite de intentos.

Crear o cambiar un usuario desde la terminal:
    .venv/Scripts/python -m app.auth crear-usuario <usuario>
"""
from __future__ import annotations

import getpass
import hashlib
import hmac
import os
import secrets
import sys
import threading
import time
from datetime import datetime, timedelta

from fastapi import Request

from . import db

COOKIE = "facturas_sesion"
DURACION_HORAS = 12
MAX_FALLOS = 5
VENTANA_FALLOS_S = 300
LONGITUD_MINIMA = 10

_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}
_fallos: dict[str, list[float]] = {}
_lock = threading.Lock()

ESQUEMA_SQL = """
CREATE TABLE IF NOT EXISTS usuarios (
    usuario TEXT PRIMARY KEY, clave TEXT NOT NULL, creado TEXT, ultimo_ingreso TEXT
);
CREATE TABLE IF NOT EXISTS sesiones (
    token TEXT PRIMARY KEY, usuario TEXT NOT NULL, creada TEXT, expira TEXT
);
"""


def _tablas() -> None:
    db.conexion().executescript(ESQUEMA_SQL)


# ── contraseñas ──────────────────────────────────────────
def cifrar_clave(clave: str) -> str:
    sal = secrets.token_bytes(16)
    h = hashlib.scrypt(clave.encode(), salt=sal, **_SCRYPT)
    return f"scrypt${sal.hex()}${h.hex()}"


def verificar_clave(clave: str, guardada: str) -> bool:
    try:
        _, sal, h = guardada.split("$")
        calc = hashlib.scrypt(clave.encode(), salt=bytes.fromhex(sal), **_SCRYPT)
        return hmac.compare_digest(calc.hex(), h)
    except (ValueError, TypeError):
        return False


def validar_nueva(usuario: str, clave: str) -> list[str]:
    errores = []
    if not usuario or len(usuario) < 3 or not all(c.isalnum() or c in "._-@" for c in usuario):
        errores.append("El usuario debe tener al menos 3 caracteres: letras, números, punto, guion o @.")
    if len(clave) < LONGITUD_MINIMA:
        errores.append(f"La contraseña debe tener al menos {LONGITUD_MINIMA} caracteres.")
    return errores


# ── usuarios ─────────────────────────────────────────────
def hay_usuarios() -> bool:
    _tablas()
    return bool(db._q("SELECT 1 FROM usuarios LIMIT 1"))


def guardar_usuario(usuario: str, clave: str) -> None:
    _tablas()
    db._x("""INSERT INTO usuarios(usuario,clave,creado) VALUES(?,?,?)
             ON CONFLICT(usuario) DO UPDATE SET clave=excluded.clave""",
          (usuario.strip().lower(), cifrar_clave(clave), db.ahora()))
    # Cambiar la contraseña cierra las sesiones abiertas de ese usuario.
    db._x("DELETE FROM sesiones WHERE usuario=?", (usuario.strip().lower(),))


def autenticar(usuario: str, clave: str) -> bool:
    _tablas()
    fila = db._q("SELECT clave FROM usuarios WHERE usuario=?", ((usuario or "").strip().lower(),))
    # Se calcula el hash aunque el usuario no exista, para no revelar cuáles existen por el tiempo de respuesta.
    global _FICTICIA
    if _FICTICIA is None:
        _FICTICIA = cifrar_clave(secrets.token_urlsafe(16))
    guardada = fila[0]["clave"] if fila else _FICTICIA
    return verificar_clave(clave or "", guardada) and bool(fila)


_FICTICIA: str | None = None


# ── sesiones ─────────────────────────────────────────────
def abrir_sesion(usuario: str) -> str:
    _tablas()
    token = secrets.token_urlsafe(32)
    expira = (datetime.now() + timedelta(hours=DURACION_HORAS)).isoformat(timespec="seconds")
    db._x("INSERT INTO sesiones(token,usuario,creada,expira) VALUES(?,?,?,?)",
          (_huella(token), usuario.strip().lower(), db.ahora(), expira))
    db._x("UPDATE usuarios SET ultimo_ingreso=? WHERE usuario=?", (db.ahora(), usuario.strip().lower()))
    db._x("DELETE FROM sesiones WHERE expira < ?", (db.ahora(),))
    return token


def usuario_de(token: str | None) -> str | None:
    if not token:
        return None
    _tablas()
    fila = db._q("SELECT usuario, expira FROM sesiones WHERE token=?", (_huella(token),))
    if not fila or fila[0]["expira"] < db.ahora():
        return None
    return fila[0]["usuario"]


def cerrar_sesion(token: str | None) -> None:
    if token:
        _tablas()
        db._x("DELETE FROM sesiones WHERE token=?", (_huella(token),))


def _huella(token: str) -> str:
    """En la base solo se guarda el hash del token: una copia de la base no sirve para entrar."""
    return hashlib.sha256(token.encode()).hexdigest()


# ── peticiones ───────────────────────────────────────────
def ip_cliente(request: Request) -> str:
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")


def es_local(request: Request) -> bool:
    """Petición hecha desde este mismo equipo, sin pasar por el túnel de Cloudflare ni otro proxy."""
    host = request.client.host if request.client else ""
    via_proxy = any(h in request.headers for h in ("cf-connecting-ip", "cf-ray", "x-forwarded-for"))
    return host in ("127.0.0.1", "::1", "localhost", "testclient") and not via_proxy


def codigo_configuracion() -> str | None:
    """Código de un solo uso para crear la primera cuenta desde internet (lo define el Worker en la nube)."""
    return os.environ.get("FACTURAS_IA_CODIGO_CONFIGURACION") or None


def codigo_valido(codigo: str | None) -> bool:
    esperado = codigo_configuracion()
    return bool(esperado and codigo) and hmac.compare_digest(codigo.strip().encode(), esperado.encode())


def es_https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https" \
        or '"https"' in request.headers.get("cf-visitor", "")


def bloqueado(ip: str) -> int:
    """Segundos que faltan para poder intentar de nuevo (0 si no está bloqueado)."""
    with _lock:
        ahora = time.time()
        lista = [t for t in _fallos.get(ip, []) if ahora - t < VENTANA_FALLOS_S]
        _fallos[ip] = lista
        if len(lista) >= MAX_FALLOS:
            return int(VENTANA_FALLOS_S - (ahora - lista[0])) + 1
        return 0


def registrar_fallo(ip: str) -> None:
    with _lock:
        _fallos.setdefault(ip, []).append(time.time())


def limpiar_fallos(ip: str) -> None:
    with _lock:
        _fallos.pop(ip, None)


# ── línea de comandos ────────────────────────────────────
def _cli(args: list[str]) -> int:
    if len(args) != 2 or args[0] != "crear-usuario":
        print("Uso: python -m app.auth crear-usuario <usuario>")
        return 2
    usuario = args[1]
    clave = getpass.getpass("Contraseña: ")
    if clave != getpass.getpass("Repite la contraseña: "):
        print("Las contraseñas no coinciden.")
        return 1
    errores = validar_nueva(usuario, clave)
    if errores:
        print("\n".join(errores))
        return 1
    guardar_usuario(usuario, clave)
    print(f"Usuario «{usuario.lower()}» guardado.")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
