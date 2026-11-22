"""Rutas del proyecto y lectura del archivo .env."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("FACTURAS_IA_DATA", ROOT / "data"))
WEB = ROOT / "web"
DATA.mkdir(parents=True, exist_ok=True)

# Nombres aceptados en .env para cada secreto (el .env actual usa guiones).
ENV_ALIAS = {
    "openai_api_key": ["OPENAI_APIKEY", "OPENAI_API_KEY"],
    "composio_api_key": ["COMPOSIO_APIKEY", "COMPOSIO_API_KEY"],
}


def leer_env() -> dict[str, str]:
    """Lee .env admitiendo claves con guiones (OPENAI-APIKEY) y las normaliza a OPENAI_APIKEY."""
    valores: dict[str, str] = {}
    archivo = ROOT / ".env"
    if archivo.exists():
        for linea in archivo.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            k, v = linea.split("=", 1)
            valores[k.strip().upper().replace("-", "_")] = v.strip().strip('"').strip("'")
    for k, v in os.environ.items():
        if k.upper() in sum(ENV_ALIAS.values(), []):
            valores.setdefault(k.upper(), v)
    return valores


def secreto_env(nombre: str) -> str | None:
    env = leer_env()
    for alias in ENV_ALIAS.get(nombre, []):
        if env.get(alias):
            return env[alias]
    return None
