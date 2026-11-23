"""Configuración editable desde el frontend (data/config.json) con valores por defecto."""
from __future__ import annotations

import copy
import json
import threading
from typing import Any

from jsonschema import Draft202012Validator

from .settings import DATA

_ARCHIVO = DATA / "config.json"
_lock = threading.Lock()

ESQUEMA_FACTURA: dict[str, Any] = {
    "type": "object",
    "title": "Factura",
    "required": ["numero_factura", "fecha_emision", "emisor_nombre", "emisor_id_fiscal", "moneda",
                 "lineas", "subtotal", "total"],
    "properties": {
        "numero_factura": {"type": "string", "description": "Número o serie de la factura tal como aparece impreso"},
        "fecha_emision": {"type": "string", "format": "date", "description": "Fecha de emisión"},
        "emisor_nombre": {"type": "string", "description": "Razón social de quien emite la factura"},
        "emisor_id_fiscal": {"type": "string", "description": "NIT, RUC, RFC u otro ID fiscal del emisor"},
        "receptor_nombre": {"type": "string", "description": "Cliente al que se factura"},
        "receptor_id_fiscal": {"type": "string", "description": "ID fiscal del cliente"},
        "moneda": {"type": "string", "description": "Código ISO 4217, por ejemplo USD"},
        "lineas": {
            "type": "array",
            "minItems": 1,
            "description": "Productos o servicios facturados, uno por línea",
            "items": {
                "type": "object",
                "required": ["descripcion", "cantidad", "precio_unitario", "importe"],
                "properties": {
                    "descripcion": {"type": "string", "description": "Descripción completa del producto"},
                    "cantidad": {"type": "number"},
                    "precio_unitario": {"type": "number"},
                    "descuento": {"type": "number", "description": "Descuento de la línea en dinero, 0 si no hay"},
                    "importe": {"type": "number", "description": "Importe final de la línea"},
                },
            },
        },
        "subtotal": {"type": "number", "description": "Suma de los importes de las líneas"},
        "descuento_total": {"type": "number", "description": "Descuento general aplicado al subtotal, 0 si no hay"},
        "impuestos": {"type": "number", "description": "Suma de todos los impuestos (IVA, etc.)"},
        "otros_cargos": {"type": "number", "description": "Envío u otros cargos, 0 si no hay"},
        "total": {"type": "number", "description": "Total a pagar"},
    },
}

DEFAULT: dict[str, Any] = {
    "drive": {
        "proveedor": "composio",  # composio | local
        "carpeta_entrada": "Facturas IA",
        "carpeta_procesadas": "Procesadas",
        "carpeta_revision": "Revisión manual",
        "archivo_resultados": "Facturas Procesadas IA",
        "renombrar_al_mover": False,
        "carpeta_local": "data/drive_local",
    },
    "frecuencia": {
        "activo": False,
        "cada_minutos": 5,
        "hora_inicio": "00:00",
        "hora_fin": "23:59",
        "max_por_corrida": 20,
    },
    "modelos": {
        "intentos_maximos": 3,
        "reintentos_tecnicos": 2,
        "timeout_segundos": 240,
        "cadena": [
            {
                "id": "glm-ocr-local",
                "nombre": "GLM-OCR local + estructurador OpenAI",
                "tipo": "glm_ocr",
                "activo": True,
                "ollama_url": "http://localhost:11434",
                "modelo": "glm-ocr",
                "lado_maximo_px": 1000,
                "usar_texto_pdf": True,
                "estructurador": "openai",
                "modelo_estructurador": "gpt-5.4-nano",
            },
            {
                "id": "openai-vision",
                "nombre": "OpenAI visión",
                "tipo": "openai",
                "activo": True,
                "modelo": "gpt-5.4-mini",
                "detalle_imagen": "high",
            },
        ],
    },
    "preparacion": {"max_paginas": 5, "dpi_pdf": 150, "lado_maximo_px": 1800},
    "esquema": ESQUEMA_FACTURA,
    "validacion": {
        "tolerancia_linea": 0.02,
        "tolerancia_total": 0.05,
        "confianza_minima": 0.6,
        "precios_incluyen_impuesto": False,
        "campos": {
            "lineas": "lineas", "cantidad": "cantidad", "precio_unitario": "precio_unitario",
            "descuento_linea": "descuento", "importe": "importe", "subtotal": "subtotal",
            "descuento_total": "descuento_total", "impuestos": "impuestos", "otros_cargos": "otros_cargos",
            "total": "total", "numero": "numero_factura", "emisor_id": "emisor_id_fiscal",
            "emisor_nombre": "emisor_nombre",
        },
    },
    "catalogo": {
        "umbral_parecido": 85,
        "total_con_impuesto": False,
        "productos": [
            {"codigo": "CEM", "producto": "Cemento", "palabras_clave": ["cemento"], "activo": True},
            {"codigo": "VAR", "producto": "Varilla", "palabras_clave": ["varilla", "hierro corrugado"], "activo": True},
            {"codigo": "PIN", "producto": "Pintura", "palabras_clave": ["pintura"], "activo": True},
            {"codigo": "ARR", "producto": "Arroz", "palabras_clave": ["arroz"], "activo": True},
            {"codigo": "ACE", "producto": "Aceite vegetal", "palabras_clave": ["aceite vegetal", "aceite comestible"], "activo": True},
        ],
    },
}

SECCIONES = list(DEFAULT.keys())


def _fusionar(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k != "esquema":
            out[k] = _fusionar(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def cargar() -> dict[str, Any]:
    with _lock:
        if _ARCHIVO.exists():
            try:
                return _fusionar(DEFAULT, json.loads(_ARCHIVO.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                pass
        return copy.deepcopy(DEFAULT)


def guardar(config: dict[str, Any]) -> None:
    with _lock:
        tmp = _ARCHIVO.with_suffix(".tmp")
        tmp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_ARCHIVO)


def validar_seccion(seccion: str, valor: Any) -> list[str]:
    """Errores legibles si la sección no es usable. Lista vacía = correcta."""
    errores: list[str] = []
    if seccion not in DEFAULT:
        return [f"Sección desconocida: {seccion}"]
    if seccion == "esquema":
        try:
            Draft202012Validator.check_schema(valor)
        except Exception as e:  # noqa: BLE001
            return [f"El esquema JSON no es válido: {getattr(e, 'message', e)}"]
        if valor.get("type") != "object" or "properties" not in valor:
            errores.append("El esquema debe ser un objeto con 'properties'.")
        campos = cargar()["validacion"]["campos"]
        props = valor.get("properties", {})
        for clave in ("lineas", "total"):
            if campos[clave] not in props:
                errores.append(f"El esquema necesita el campo «{campos[clave]}» para el cuadre de montos.")
    elif seccion == "drive":
        for k in ("carpeta_entrada", "carpeta_procesadas", "carpeta_revision", "archivo_resultados"):
            if not str(valor.get(k, "")).strip():
                errores.append(f"«{k}» no puede quedar vacío.")
        if valor.get("carpeta_procesadas") == valor.get("carpeta_revision"):
            errores.append("Procesadas y Revisión deben ser carpetas distintas.")
        if valor.get("proveedor") not in ("composio", "local"):
            errores.append("Proveedor de Drive desconocido.")
    elif seccion == "modelos":
        cadena = valor.get("cadena", [])
        if not any(m.get("activo") for m in cadena):
            errores.append("Debe haber al menos un modelo activo.")
        ids = [m.get("id") for m in cadena]
        if len(ids) != len(set(ids)):
            errores.append("Cada modelo de la cadena necesita un id distinto.")
        for m in cadena:
            if m.get("tipo") not in ("glm_ocr", "openai"):
                errores.append(f"Tipo de modelo desconocido: {m.get('tipo')}")
        if int(valor.get("intentos_maximos", 0)) < 1:
            errores.append("Los intentos por factura deben ser al menos 1.")
    elif seccion == "frecuencia":
        if int(valor.get("cada_minutos", 0)) < 1:
            errores.append("La frecuencia mínima es 1 minuto.")
    elif seccion == "catalogo":
        for i, p in enumerate(valor.get("productos", []), 1):
            if not str(p.get("producto", "")).strip():
                errores.append(f"El producto de la fila {i} no tiene nombre.")
        u = valor.get("umbral_parecido", 85)
        if not (50 <= float(u) <= 100):
            errores.append("El umbral de parecido debe estar entre 50 y 100.")
    return errores


def actualizar_seccion(seccion: str, valor: Any) -> list[str]:
    errores = validar_seccion(seccion, valor)
    if errores:
        return errores
    config = cargar()
    config[seccion] = valor
    guardar(config)
    return []
