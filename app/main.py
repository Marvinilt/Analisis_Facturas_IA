"""API y servidor del frontend.

Iniciar:  .venv/Scripts/python -m uvicorn app.main:app --port 8000
Abrir:    http://localhost:8000
"""
from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import catalogo, configuracion, db, secretos
from .extraction import ErrorDocumento, ErrorProveedor, crear_cadena
from .extraction.preparar import preparar
from .servicio import servicio
from .settings import ROOT, WEB
from .storage import AlmacenError, crear_almacen
from .validacion import evaluar


@asynccontextmanager
async def ciclo(app: FastAPI):
    db.conexion()
    # Una corrida que quedó a medias por un corte vuelve a la cola.
    for a in db.listar_archivos("en_proceso"):
        db.actualizar_archivo(a["file_id"], estado="pendiente", motivo="Se interrumpió la corrida anterior")
    servicio.iniciar_planificador()
    yield
    servicio.apagar()


app = FastAPI(title="Facturas IA", lifespan=ciclo)


# ── estado y ejecución ───────────────────────────────────
@app.get("/api/estado")
def estado() -> dict[str, Any]:
    return {
        "servicio": servicio.estado(),
        "contadores": db.contadores(),
        "por_estado": db.contar_por_estado(),
        "alertas": db.alertas_activas(),
        "ultima_corrida": (db.corridas(1) or [None])[0],
    }


@app.post("/api/procesar")
def procesar() -> dict[str, Any]:
    if not servicio.iniciar("manual"):
        raise HTTPException(409, "Ya hay una corrida en curso.")
    return {"ok": True}


@app.post("/api/detener")
def detener() -> dict[str, Any]:
    servicio.detener()
    return {"ok": True}


@app.get("/api/corridas")
def corridas(limite: int = 20) -> list[dict]:
    return db.corridas(limite)


@app.get("/api/eventos")
def eventos(corrida_id: int | None = None, limite: int = 300) -> list[dict]:
    return db.eventos(corrida_id=corrida_id, limite=limite)


@app.get("/api/archivos")
def archivos(estado: str | None = None, limite: int = 200) -> list[dict]:
    filas = db.listar_archivos(estado, limite)
    for f in filas:
        f.pop("datos_json", None)
        f.pop("resultado_json", None)
    return filas


@app.get("/api/archivos/{file_id:path}")
def archivo(file_id: str) -> dict:
    f = db.archivo(file_id)
    if not f:
        raise HTTPException(404, "Archivo no encontrado")
    for k in ("datos_json", "resultado_json"):
        f[k] = json.loads(f[k]) if f.get(k) else None
    f["eventos"] = db.eventos(file_id=file_id)
    return f


@app.post("/api/alertas/{alerta_id}/cerrar")
def cerrar_alerta(alerta_id: int) -> dict:
    db.cerrar_alerta(alerta_id=alerta_id)
    return {"ok": True}


# ── configuración ────────────────────────────────────────
@app.get("/api/config")
def leer_config() -> dict:
    return {"config": configuracion.cargar(), "defecto": configuracion.DEFAULT}


@app.put("/api/config/{seccion}")
def guardar_config(seccion: str, valor: Any = Body(...)) -> dict:
    errores = configuracion.actualizar_seccion(seccion, valor)
    if errores:
        raise HTTPException(422, {"errores": errores})
    return {"ok": True, "config": configuracion.cargar()}


@app.post("/api/config/{seccion}/restablecer")
def restablecer(seccion: str) -> dict:
    if seccion not in configuracion.DEFAULT:
        raise HTTPException(404, "Sección desconocida")
    configuracion.actualizar_seccion(seccion, configuracion.DEFAULT[seccion])
    return {"ok": True, "config": configuracion.cargar()}


@app.get("/api/secretos")
def leer_secretos() -> dict:
    return secretos.estado()


@app.put("/api/secretos/{nombre}")
def guardar_secreto(nombre: str, valor: str = Body(..., embed=True)) -> dict:
    if nombre not in secretos.NOMBRES:
        raise HTTPException(404, "Secreto desconocido")
    if not valor.strip():
        raise HTTPException(422, {"errores": ["La clave está vacía."]})
    secretos.guardar(nombre, valor)
    return secretos.estado()


@app.delete("/api/secretos/{nombre}")
def borrar_secreto(nombre: str) -> dict:
    secretos.borrar(nombre)
    return secretos.estado()


# ── pruebas de conexión ──────────────────────────────────
@app.post("/api/probar/drive")
def probar_drive() -> dict:
    cfg = configuracion.cargar()["drive"]
    try:
        alm = crear_almacen(cfg)
        info = alm.preparar()
        archivos = alm.listar_entrada()
        conteo = {"pendientes": sum(a.admitido for a in archivos), "ignorados": sum(not a.admitido for a in archivos),
                  "procesadas": alm.contar("procesadas"), "revision": alm.contar("revision"),
                  "resultados": alm.enlace_resultados(), "actualizado": db.ahora()}
        db.guardar_contadores(conteo)
        db.cerrar_alerta("drive")
        cuentas = None
        if cfg.get("proveedor") == "composio":
            res = alm.c.conexiones(["googledrive", "googlesheets"])  # type: ignore[attr-defined]
            cuentas = {k: {"estado": v.get("status"),
                           "cuenta": next((x.get("user_info", {}).get("user", {}).get("emailAddress")
                                           or x.get("user_info", {}).get("email") for x in v.get("accounts", [])), None)}
                       for k, v in res.items()}
        return {"ok": True, "info": info, "conteo": conteo, "cuentas": cuentas, **alm.describir()}
    except AlmacenError as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/modelos/ollama")
def modelos_ollama(url: str = "http://localhost:11434") -> dict:
    try:
        r = httpx.get(f"{url.rstrip('/')}/api/tags", timeout=5)
        return {"ok": True, "modelos": [m["name"] for m in r.json().get("models", [])]}
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"Ollama no responde en {url}: {e}"}


@app.post("/api/probar/extraccion")
async def probar_extraccion(archivo: UploadFile = File(...), modelo: str | None = None) -> dict:
    """Prueba la cadena de modelos con un archivo subido desde el navegador (no toca Drive)."""
    cfg = configuracion.cargar()
    datos = await archivo.read()
    mime = archivo.content_type or "application/octet-stream"
    try:
        doc = preparar(archivo.filename or "prueba", mime, datos, int(cfg["preparacion"]["max_paginas"]),
                       int(cfg["preparacion"]["dpi_pdf"]), int(cfg["preparacion"]["lado_maximo_px"]))
    except ErrorDocumento as e:
        return {"ok": False, "error": str(e)}
    cadena = crear_cadena(cfg["modelos"])
    if modelo:
        cadena = [e for e in cadena if e.id == modelo] or cadena
    resultados = []
    for ext in cadena:
        inicio = time.time()
        try:
            r = ext.extraer(doc, cfg["esquema"])
        except (ErrorProveedor, ErrorDocumento) as e:
            resultados.append({"modelo": ext.nombre, "ok": False, "error": str(e), "segundos": round(time.time() - inicio, 1)})
            continue
        ev = evaluar(r.datos, cfg["esquema"], cfg["validacion"], r.confianza, r.es_factura, r.observaciones)
        cat = catalogo.aplicar(ev.datos, cfg["catalogo"], cfg["validacion"]["campos"]) if ev.valida else None
        resultados.append({"modelo": r.modelo, "ok": True, "segundos": r.segundos, "confianza": r.confianza,
                           "datos": ev.datos, "evaluacion": ev.dict(), "catalogo": cat, "texto_ocr": r.texto_ocr})
        if modelo is None:
            break
    return {"ok": True, "resultados": resultados}


@app.post("/api/probar/catalogo")
def probar_catalogo(descripcion: str = Body(..., embed=True)) -> dict:
    cfg = configuracion.cargar()["catalogo"]
    c = catalogo.coincidir(descripcion, cfg.get("productos", []), float(cfg.get("umbral_parecido", 85)))
    return {"coincide": bool(c), "producto": c.producto if c else None, "tipo": c.tipo if c else None,
            "puntaje": c.puntaje if c else None}


# ── frontend ─────────────────────────────────────────────
app.mount("/web", StaticFiles(directory=WEB), name="web")
app.mount("/diseno", StaticFiles(directory=ROOT / "diseno"), name="diseno")


@app.get("/")
def inicio() -> FileResponse:
    return FileResponse(WEB / "index.html")
