"""API keys guardadas cifradas en el servidor (data/secretos.enc).

Las claves escritas desde el frontend tienen prioridad; si no hay, se usa el .env.
El navegador nunca recibe una clave completa: solo si existe, su origen y los últimos 4 caracteres.
"""
from __future__ import annotations

import json
import threading

from cryptography.fernet import Fernet, InvalidToken

from .settings import DATA, secreto_env

_ARCHIVO = DATA / "secretos.enc"
_CLAVE = DATA / ".clave"
_lock = threading.Lock()

NOMBRES = {
    "openai_api_key": "API key de OpenAI",
    "composio_api_key": "API key de Composio Connect",
}


def _fernet() -> Fernet:
    if not _CLAVE.exists():
        _CLAVE.write_bytes(Fernet.generate_key())
    return Fernet(_CLAVE.read_bytes())


def _leer() -> dict[str, str]:
    if not _ARCHIVO.exists():
        return {}
    try:
        return json.loads(_fernet().decrypt(_ARCHIVO.read_bytes()))
    except (InvalidToken, ValueError):
        return {}


def _escribir(datos: dict[str, str]) -> None:
    _ARCHIVO.write_bytes(_fernet().encrypt(json.dumps(datos).encode()))


def obtener(nombre: str) -> str | None:
    with _lock:
        guardado = _leer().get(nombre)
    return guardado or secreto_env(nombre)


def guardar(nombre: str, valor: str) -> None:
    if nombre not in NOMBRES:
        raise KeyError(nombre)
    with _lock:
        datos = _leer()
        datos[nombre] = valor.strip()
        _escribir(datos)


def borrar(nombre: str) -> None:
    with _lock:
        datos = _leer()
        datos.pop(nombre, None)
        _escribir(datos)


def estado() -> dict[str, dict]:
    with _lock:
        guardados = _leer()
    salida = {}
    for nombre, etiqueta in NOMBRES.items():
        valor = guardados.get(nombre)
        origen = "app" if valor else None
        if not valor:
            valor = secreto_env(nombre)
            origen = ".env" if valor else None
        salida[nombre] = {
            "etiqueta": etiqueta,
            "configurada": bool(valor),
            "origen": origen,
            "final": valor[-4:] if valor else None,
        }
    return salida
