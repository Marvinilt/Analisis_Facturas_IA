"""Indicadores del panel: series por día, motivos de revisión, rendimiento por modelo y corridas."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from . import db

MOTIVOS = [
    ("uplicad", "Duplicado"),
    ("dañado o ilegible", "Documento dañado"),
    ("no es una factura", "No es factura o ilegible"),
    ("montos no cuadran", "Montos no cuadran"),
    ("Datos incompletos", "Datos incompletos"),
    ("Confianza baja", "Confianza baja"),
]


def clasificar_motivo(motivo: str | None) -> str:
    texto = motivo or ""
    for clave, nombre in MOTIVOS:
        if clave.lower() in texto.lower():
            return nombre
    return "Otro"


def _dia(iso: str | None) -> str | None:
    return iso[:10] if iso else None


def calcular(dias: int | None = 30) -> dict[str, Any]:
    hoy = date.today()
    desde = (hoy - timedelta(days=dias - 1)).isoformat() if dias else None
    archivos = db._q("SELECT estado, motivo, modelo, total, total_catalogo, datos_json, resultado_json, actualizado "
                     "FROM archivos" + (" WHERE actualizado >= ?" if desde else ""), (desde,) if desde else ())
    corridas = db._q("SELECT * FROM corridas" + (" WHERE inicio >= ?" if desde else "") + " ORDER BY id",
                     (desde,) if desde else ())

    # Serie diaria de resultados.
    serie: dict[str, dict[str, int]] = defaultdict(lambda: {"procesadas": 0, "revision": 0})
    for a in archivos:
        d = _dia(a["actualizado"])
        if not d:
            continue
        if a["estado"] == "procesada":
            serie[d]["procesadas"] += 1
        elif a["estado"] in ("revision", "revision_sin_mover"):
            serie[d]["revision"] += 1
    inicio = date.fromisoformat(desde) if desde else (min((date.fromisoformat(k) for k in serie), default=hoy))
    n_dias = (hoy - inicio).days + 1
    dias_lista = [(inicio + timedelta(days=i)).isoformat() for i in range(max(n_dias, 1))]
    serie_diaria = [{"fecha": d, **serie.get(d, {"procesadas": 0, "revision": 0})} for d in dias_lista]

    procesadas = [a for a in archivos if a["estado"] == "procesada"]
    revision = [a for a in archivos if a["estado"] in ("revision", "revision_sin_mover")]
    monedas = Counter()
    for a in procesadas:
        try:
            monedas[(json.loads(a["datos_json"] or "{}") or {}).get("moneda") or "—"] += 1
        except json.JSONDecodeError:
            pass

    # Rendimiento por modelo, a partir del historial de intentos.
    modelos: dict[str, dict[str, Any]] = defaultdict(lambda: {"intentos": 0, "validas": 0, "segundos": []})
    for a in archivos:
        try:
            hist = (json.loads(a["resultado_json"] or "{}") or {}).get("historial") or []
        except json.JSONDecodeError:
            hist = []
        for h in hist:
            if not h.get("modelo") or h["modelo"] == "—":
                continue
            m = modelos[h["modelo"]]
            m["intentos"] += 1
            m["validas"] += h.get("resultado") == "válida"
            if isinstance(h.get("segundos"), (int, float)):
                m["segundos"].append(h["segundos"])
    por_modelo = sorted(
        ({"modelo": k, "intentos": v["intentos"], "validas": v["validas"],
          "tasa": round(100 * v["validas"] / v["intentos"]) if v["intentos"] else 0,
          "segundos_promedio": round(sum(v["segundos"]) / len(v["segundos"]), 1) if v["segundos"] else None}
         for k, v in modelos.items()), key=lambda x: -x["intentos"])

    motivos = Counter(clasificar_motivo(a["motivo"]) for a in revision)

    duraciones = []
    for c in corridas:
        if c.get("inicio") and c.get("fin"):
            try:
                duraciones.append((datetime.fromisoformat(c["fin"]) - datetime.fromisoformat(c["inicio"])).total_seconds())
            except ValueError:
                pass

    total = len(procesadas) + len(revision)
    return {
        "dias": dias,
        "desde": inicio.isoformat(),
        "serie": serie_diaria,
        "resumen": {
            "procesadas": len(procesadas),
            "revision": len(revision),
            "tasa_exito": round(100 * len(procesadas) / total, 1) if total else None,
            "monto_total": round(sum(a["total"] or 0 for a in procesadas), 2),
            "monto_catalogo": round(sum(a["total_catalogo"] or 0 for a in procesadas), 2),
            "moneda": monedas.most_common(1)[0][0] if monedas else None,
            "corridas": len(corridas),
            "corridas_detenidas": sum(c["estado"] == "detenida" for c in corridas),
            "duracion_promedio_s": round(sum(duraciones) / len(duraciones)) if duraciones else None,
        },
        "motivos": [{"motivo": k, "cantidad": v} for k, v in motivos.most_common()],
        "modelos": por_modelo,
        "corridas_por_origen": dict(Counter(c["origen"] or "—" for c in corridas)),
    }
