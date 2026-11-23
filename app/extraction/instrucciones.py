"""Instrucciones para los modelos y esquema de salida estricto generado desde el esquema configurable."""
from __future__ import annotations

import copy
import json
import re
from typing import Any

PERMITIDAS = {"type", "properties", "items", "required", "description", "enum", "title"}

SISTEMA = """Eres un sistema de extracción de datos de facturas comerciales.
Reglas:
- Copia los datos exactamente como aparecen en el documento. No inventes, no calcules valores que no estén impresos.
- Números: usa punto decimal y sin separador de miles (1.130,00 → 1130.00; 1,130.00 → 1130.00).
- Fechas en formato AAAA-MM-DD. Si la fecha impresa es dd/mm/aaaa, el primer número es el día.
- Copia cada línea de producto completa, en el mismo orden, sin resumir ni unir líneas.
- La descripción de cada línea es solo el texto del producto: sin la cantidad, precios ni importes de las otras columnas.
- Si un campo opcional no aparece, usa null. Si un descuento u otro cargo no aparece, usa 0.
- Los descuentos van como número positivo aunque la factura los imprima con signo menos (-25,00 → 25.00).
- Si el documento no es una factura o es ilegible, marca es_factura=false y explica el motivo en observaciones.
- confianza: tu certeza de 0 a 1 de que todas las cifras quedaron bien leídas."""


def esquema_estricto(esquema: dict[str, Any]) -> dict[str, Any]:
    """Convierte el esquema configurable al subconjunto que exige la salida estructurada estricta.

    Todos los campos pasan a ser obligatorios; los opcionales aceptan null.
    """

    def convertir(nodo: dict[str, Any], requerido: bool) -> dict[str, Any]:
        n = {k: copy.deepcopy(v) for k, v in nodo.items() if k in PERMITIDAS}
        tipo = n.get("type")
        if tipo == "object":
            props = nodo.get("properties", {})
            req = set(nodo.get("required", []))
            n["properties"] = {k: convertir(v, k in req) for k, v in props.items()}
            n["required"] = list(props.keys())
            n["additionalProperties"] = False
        elif tipo == "array":
            n["items"] = convertir(nodo.get("items", {"type": "string"}), True)
        if "format" in nodo and "description" not in n:
            n["description"] = f"Formato {nodo['format']}"
        elif "format" in nodo:
            n["description"] = f"{n['description']} (formato {nodo['format']})"
        if not requerido and isinstance(tipo, str):
            n["type"] = [tipo, "null"]
        return n

    factura = convertir(esquema, True)
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["es_factura", "confianza", "observaciones", "factura"],
        "properties": {
            "es_factura": {"type": "boolean", "description": "true si el documento es una factura legible"},
            "confianza": {"type": "number", "description": "Certeza de 0 a 1 de que las cifras están bien leídas"},
            "observaciones": {"type": ["string", "null"], "description": "Problemas encontrados al leer, o null"},
            "factura": factura,
        },
    }


def texto_usuario(pista: str | None, texto_pdf: str = "", texto_ocr: str = "") -> str:
    partes = ["Extrae los datos de esta factura según el esquema."]
    if texto_pdf:
        partes.append("El PDF incluye esta capa de texto; úsala para verificar las cifras:\n" + texto_pdf[:12000])
    if texto_ocr:
        partes.append("Texto reconocido por OCR del documento (respeta las cifras tal cual):\n" + texto_ocr[:16000])
    if pista:
        partes.append("ATENCIÓN, un intento anterior falló la validación: " + pista +
                      "\nVuelve a leer con cuidado las cifras señaladas. Si el documento realmente imprime esos valores, "
                      "cópialos tal cual aunque no cuadren.")
    return "\n\n".join(partes)


def plantilla_simple(esquema: dict[str, Any]) -> str:
    """Plantilla JSON vacía (para modelos sin salida estructurada, como GLM-OCR)."""

    def vacio(nodo: dict[str, Any]) -> Any:
        t = nodo.get("type")
        if t == "object":
            return {k: vacio(v) for k, v in nodo.get("properties", {}).items()}
        if t == "array":
            return [vacio(nodo.get("items", {}))]
        return ""

    return json.dumps(vacio(esquema), ensure_ascii=False)


def parsear_json(texto: str) -> dict[str, Any]:
    """Extrae el primer objeto JSON de una respuesta (admite bloques ```json)."""
    texto = texto.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", texto, re.S)
    if m:
        texto = m.group(1).strip()
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        inicio, fin = texto.find("{"), texto.rfind("}")
        if inicio >= 0 and fin > inicio:
            fragmento = texto[inicio:fin + 1]
            fragmento = re.sub(r",\s*([}\]])", r"\1", fragmento)
            return json.loads(fragmento)
        raise
