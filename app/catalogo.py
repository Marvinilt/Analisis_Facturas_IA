"""Paso 10 (cruce con catálogo) y paso 11 (total catálogo)."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz

from .validacion import a_numero


def normalizar_texto(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s).lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


@dataclass
class Coincidencia:
    producto: str
    codigo: str
    tipo: str  # código | palabra clave | parecido
    puntaje: float


def _ventanas(palabras: list[str], n: int):
    for i in range(0, max(1, len(palabras) - n + 1)):
        yield " ".join(palabras[i:i + n])


def coincidir(descripcion: str, productos: list[dict], umbral: float = 85) -> Coincidencia | None:
    texto = normalizar_texto(descripcion)
    palabras = texto.split()
    mejor: Coincidencia | None = None
    for p in productos:
        if not p.get("activo", True):
            continue
        nombre = p.get("producto", "")
        codigo = str(p.get("codigo") or "").strip()
        candidatos: list[Coincidencia] = []
        if codigo and normalizar_texto(codigo) in palabras and len(codigo) >= 3:
            candidatos.append(Coincidencia(nombre, codigo, "código", 100))
        claves = [normalizar_texto(k) for k in (p.get("palabras_clave") or []) + [nombre] if str(k).strip()]
        for clave in claves:
            if re.search(rf"\b{re.escape(clave)}\b", texto):
                candidatos.append(Coincidencia(nombre, codigo, "palabra clave", 99))
                continue
            if len(clave) < 4:
                continue
            n = len(clave.split())
            puntaje = max((fuzz.ratio(v, clave) for v in _ventanas(palabras, n)), default=0)
            if puntaje >= umbral:
                candidatos.append(Coincidencia(nombre, codigo, "parecido", round(puntaje, 1)))
        for c in candidatos:
            if mejor is None or c.puntaje > mejor.puntaje:
                mejor = c
    return mejor


def aplicar(datos: dict, cfg_catalogo: dict, campos: dict) -> dict[str, Any]:
    """Marca cada línea y calcula el total catálogo."""
    productos = cfg_catalogo.get("productos", [])
    umbral = float(cfg_catalogo.get("umbral_parecido", 85))
    lineas = datos.get(campos["lineas"]) or []
    marcadas, total, n = [], 0.0, 0
    for i, ln in enumerate(lineas, 1):
        c = coincidir(str(ln.get("descripcion", "")), productos, umbral)
        importe = a_numero(ln.get(campos["importe"])) or 0.0
        if c:
            total += importe
            n += 1
        marcadas.append({"linea": i, "descripcion": ln.get("descripcion"), "importe": importe,
                         "producto": c.producto if c else None, "codigo": c.codigo if c else None,
                         "coincidencia": f"{c.tipo}" + (f" {c.puntaje:.0f}" if c and c.tipo == "parecido" else "") if c else None})
    total = round(total, 2)
    subtotal = a_numero(datos.get(campos["subtotal"])) or round(sum(m["importe"] for m in marcadas), 2)
    if cfg_catalogo.get("total_con_impuesto") and subtotal:
        impuestos = a_numero(datos.get(campos["impuestos"])) or 0.0
        total = round(total * (1 + impuestos / subtotal), 2)
    return {
        "lineas": marcadas,
        "total_catalogo": total,
        "lineas_catalogo": n,
        "lineas_total": len(lineas),
        "porcentaje": round(100 * total / subtotal, 1) if subtotal else 0.0,
    }
