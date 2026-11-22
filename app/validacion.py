"""Paso 07 (esquema), paso 08 (cuadre de montos) y paso 09 (decisión)."""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

# ── normalización ─────────────────────────────────────────


def a_numero(v: Any) -> float | None:
    """Convierte '1.130,00', '1,130.00', '$ 1130', '(25.00)', '-' a número. None si no es número."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s in ("", "-", "—", "N/A", "n/a", "null"):
        return None
    negativo = s.startswith("(") and s.endswith(")") or s.startswith("-")
    s = re.sub(r"[^\d.,]", "", s)
    if not s:
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", "") if re.fullmatch(r"\d{1,3}(,\d{3})+", s) else s.replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    try:
        n = float(s)
    except ValueError:
        return None
    return -n if negativo else n


FORMATOS_FECHA = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%Y/%m/%d", "%d-%m-%y")


def a_fecha(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, (date, datetime)):
        return v.strftime("%Y-%m-%d")
    s = str(v).strip()
    for f in FORMATOS_FECHA:
        try:
            return datetime.strptime(s, f).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return s


def normalizar(datos: Any, esquema: dict) -> Any:
    """Adapta tipos según el esquema: números, fechas y textos. Quita nulos de campos opcionales."""
    t = esquema.get("type")
    if t == "object" and isinstance(datos, dict):
        props = esquema.get("properties", {})
        salida = {}
        for k, v in datos.items():
            if k in props:
                n = normalizar(v, props[k])
                if n is None or n == "":
                    if k in esquema.get("required", []):
                        salida[k] = n
                    continue
                salida[k] = n
            elif v not in (None, ""):
                salida[k] = v
        return salida
    if t == "array" and isinstance(datos, list):
        items = esquema.get("items", {})
        return [normalizar(x, items) for x in datos if x not in (None, {}, "")]
    if t in ("number", "integer"):
        n = a_numero(datos)
        if n is not None and t == "integer" and float(n).is_integer():
            return int(n)
        return n if n is not None else datos
    if t == "string":
        if datos is None:
            return None
        s = str(datos).strip()
        return a_fecha(s) if esquema.get("format") == "date" else s
    return datos


# ── esquema ───────────────────────────────────────────────


def _ruta(error) -> str:
    partes = []
    for p in error.absolute_path:
        partes.append(f"línea {p + 1}" if isinstance(p, int) else str(p))
    return " › ".join(partes) or "factura"


def validar_esquema(datos: dict, esquema: dict) -> list[str]:
    errores = []
    for e in sorted(Draft202012Validator(esquema, format_checker=FormatChecker()).iter_errors(datos),
                    key=lambda e: list(map(str, e.absolute_path))):
        ruta = _ruta(e)
        if e.validator == "required":
            campo = re.findall(r"'([^']+)'", e.message)
            errores.append(f"Falta el campo obligatorio «{campo[0] if campo else e.message}» en {ruta}")
        elif e.validator == "type":
            esperado = e.validator_value
            if e.instance is None:
                errores.append(f"«{ruta}» está vacío")
            else:
                errores.append(f"«{ruta}» debería ser {esperado} y es «{str(e.instance)[:40]}»")
        elif e.validator == "format":
            errores.append(f"«{ruta}» no tiene un formato de {e.validator_value} válido: «{e.instance}»")
        elif e.validator == "minItems":
            errores.append(f"«{ruta}» no tiene elementos")
        else:
            errores.append(f"«{ruta}»: {e.message}")
    return errores


# ── cuadre de montos ──────────────────────────────────────


@dataclass
class Regla:
    nombre: str
    ok: bool
    calculado: float | None = None
    leido: float | None = None
    detalle: str = ""

    @property
    def diferencia(self) -> float | None:
        if self.calculado is None or self.leido is None:
            return None
        return round(self.leido - self.calculado, 2)

    def dict(self) -> dict:
        return {"regla": self.nombre, "ok": self.ok, "calculado": self.calculado, "leido": self.leido,
                "diferencia": self.diferencia, "detalle": self.detalle}


def _f(v: Any) -> float:
    return a_numero(v) or 0.0


def cuadre(datos: dict, reglas: dict) -> list[Regla]:
    c = reglas["campos"]
    tol_l, tol_t = float(reglas["tolerancia_linea"]), float(reglas["tolerancia_total"])
    resultado: list[Regla] = []
    lineas = datos.get(c["lineas"]) or []

    for i, ln in enumerate(lineas, 1):
        cant, precio, imp = (a_numero(ln.get(c["cantidad"])), a_numero(ln.get(c["precio_unitario"])),
                             a_numero(ln.get(c["importe"])))
        if cant is None or precio is None or imp is None:
            continue
        # Un descuento siempre resta, aunque la factura lo imprima como «-25,00».
        calc = round(cant * precio - abs(_f(ln.get(c["descuento_linea"]))), 2)
        tol = tol_l + 0.005 * abs(cant)  # el precio unitario impreso viene redondeado a centavos
        ok = abs(calc - imp) <= tol
        resultado.append(Regla(f"Línea {i}: cantidad × precio − descuento = importe", ok, calc, imp,
                               "" if ok else f"«{str(ln.get(c['cantidad']))} × {precio:.2f}» da {calc:.2f} y el importe leído es {imp:.2f}"))

    suma = round(sum(_f(ln.get(c["importe"])) for ln in lineas), 2)
    subtotal = a_numero(datos.get(c["subtotal"]))
    total = a_numero(datos.get(c["total"]))
    desc, imp_, otros = abs(_f(datos.get(c["descuento_total"]))), _f(datos.get(c["impuestos"])), _f(datos.get(c["otros_cargos"]))
    tol_suma = tol_t + 0.005 * len(lineas)

    if subtotal is not None:
        ok = abs(suma - subtotal) <= tol_suma
        resultado.append(Regla("Suma de importes = subtotal", ok, suma, subtotal,
                               "" if ok else f"Las líneas suman {suma:.2f} y el subtotal leído es {subtotal:.2f}"))
    base = subtotal if subtotal is not None else suma
    if total is not None:
        if reglas.get("precios_incluyen_impuesto"):
            calc = round(base - desc + otros, 2)
            texto = f"subtotal {base:.2f} − descuento {desc:.2f} + otros {otros:.2f}"
        else:
            calc = round(base - desc + imp_ + otros, 2)
            texto = f"subtotal {base:.2f} − descuento {desc:.2f} + impuestos {imp_:.2f} + otros {otros:.2f}"
        ok = abs(calc - total) <= tol_t
        resultado.append(Regla("Subtotal − descuento + impuestos + otros cargos = total", ok, calc, total,
                               "" if ok else f"{texto} = {calc:.2f}, pero el total leído es {total:.2f}"))
    else:
        resultado.append(Regla("Total presente", False, detalle="No se leyó el total"))
    return resultado


# ── decisión ──────────────────────────────────────────────


@dataclass
class Evaluacion:
    valida: bool
    datos: dict
    errores_esquema: list[str] = field(default_factory=list)
    reglas: list[Regla] = field(default_factory=list)
    motivo: str = ""

    def dict(self) -> dict:
        return {"valida": self.valida, "motivo": self.motivo, "errores_esquema": self.errores_esquema,
                "reglas": [r.dict() for r in self.reglas]}

    def pista(self) -> str:
        """Texto que se envía al siguiente modelo para que relea lo que falló."""
        partes = list(self.errores_esquema[:6])
        partes += [r.detalle for r in self.reglas if not r.ok and r.detalle][:6]
        return "; ".join(partes) or self.motivo


def evaluar(datos_crudos: dict, esquema: dict, reglas: dict, confianza: float | None = None,
            es_factura: bool = True, observaciones: str | None = None) -> Evaluacion:
    if not es_factura:
        return Evaluacion(False, datos_crudos, motivo=f"El modelo indica que no es una factura legible: {observaciones or 'sin detalle'}")
    datos = normalizar(copy.deepcopy(datos_crudos), esquema)
    errores = validar_esquema(datos, esquema)
    reglas_res = cuadre(datos, reglas) if not errores else []
    fallidas = [r for r in reglas_res if not r.ok]
    minima = float(reglas.get("confianza_minima") or 0)
    if errores:
        motivo = "Datos incompletos: " + "; ".join(errores[:3])
    elif fallidas:
        motivo = "Los montos no cuadran: " + "; ".join(r.detalle for r in fallidas[:3])
    elif confianza is not None and confianza < minima:
        motivo = f"Confianza baja del modelo ({confianza:.2f} < {minima:.2f}): {observaciones or ''}".strip()
    else:
        return Evaluacion(True, datos, errores, reglas_res, "Válida")
    return Evaluacion(False, datos, errores, reglas_res, motivo)
