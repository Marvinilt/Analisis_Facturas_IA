"""Orquestador del flujo: una corrida revisa la carpeta y procesa las facturas nuevas una por una.

Pasos (numerados como en el diagrama):
 01 vigilar carpeta   02 detectar nuevos   03 cola   04 descargar
 05 extracción IA     06 modelo de respaldo
 07 validar esquema   08 cuadre de montos  09 ¿datos confiables?
 10 cruce catálogo    11 total catálogo    12 registrar en hoja  13 mover a Procesadas  14 cerrar
 R  revisión manual   D  detener proceso (ningún modelo disponible)
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Callable

from . import catalogo, configuracion, db
from .extraction import Documento, ErrorDocumento, ErrorProveedor, Extractor, crear_cadena
from .extraction.preparar import preparar
from .storage import Almacen, AlmacenError, ArchivoDrive, crear_almacen
from .storage.base import HOJA_DETALLE, HOJA_ERRORES, HOJA_FACTURAS
from .validacion import Evaluacion, evaluar

Informar = Callable[[str, str | None], None]

NOMBRE_PASO = {
    "02": "Detectar nuevos", "04": "Descargar", "05": "Extracción IA", "06": "Modelo de respaldo",
    "07": "Validar esquema", "08": "Cuadre de montos", "09": "¿Datos confiables?", "12": "Registrar en la hoja",
}


class ProcesoDetenido(Exception):
    """Ningún modelo está disponible: se detiene la corrida y la factura queda pendiente."""

    def __init__(self, motivos: dict[str, str]):
        self.motivos = motivos
        detalle = "; ".join(f"{k}: {v}" for k, v in motivos.items())
        super().__init__(f"Ningún modelo disponible. {detalle}")


@dataclass
class ResultadoFactura:
    valida: bool
    evaluacion: Evaluacion | None
    historial: list[dict] = field(default_factory=list)
    modelo: str | None = None
    texto_ocr: str | None = None
    paso_fallo: str = "09"


class Procesador:
    def __init__(self, config: dict | None = None, almacen: Almacen | None = None,
                 cadena: list[Extractor] | None = None, informar: Informar | None = None):
        self.config = config or configuracion.cargar()
        self.almacen = almacen
        self.cadena = cadena
        self.informar = informar or (lambda paso, archivo: None)
        self.caidos: dict[str, str] = {}  # modelos no disponibles en esta corrida
        self.cid: int | None = None

    # ── utilidades ────────────────────────────────────────
    def _ev(self, file_id: str | None, paso: str, mensaje: str, nivel: str = "info") -> None:
        db.evento(self.cid, file_id, paso, mensaje, nivel)

    # ── corrida completa ──────────────────────────────────
    def correr(self, origen: str = "manual", detener: threading.Event | None = None) -> dict[str, Any]:
        self.cid = db.nueva_corrida(origen)
        resumen = {"corrida": self.cid, "encontrados": 0, "procesadas": 0, "revision": 0, "ignorados": 0,
                   "estado": "completada", "detalle": ""}
        try:
            self.informar("01 · Vigilar carpeta", None)
            if self.almacen is None:
                self.almacen = crear_almacen(self.config["drive"])
            info = self.almacen.preparar()
            if info.get("creadas"):
                self._ev(None, "01", f"Se crearon dentro de la carpeta: {', '.join(info['creadas'])}")
            db.cerrar_alerta("drive")
            self.informar("02 · Detectar nuevos", None)
            archivos = self.almacen.listar_entrada()
            admitidos = [a for a in archivos if a.admitido]
            ignorados = [a for a in archivos if not a.admitido]
            resumen["encontrados"], resumen["ignorados"] = len(admitidos), len(ignorados)
            db.actualizar_corrida(self.cid, encontrados=len(admitidos), ignorados=len(ignorados))
            for a in ignorados:
                self._ev(a.id, "02", f"«{a.nombre}» se ignora: el tipo {a.mime} no es PDF ni imagen.", "aviso")
            maximo = int(self.config["frecuencia"].get("max_por_corrida", 20))
            cola = admitidos[:maximo]
            self._ev(None, "03", f"{len(admitidos)} factura(s) pendiente(s); se procesan {len(cola)} en esta corrida.")
            if self.cadena is None:
                self.cadena = crear_cadena(self.config["modelos"])
            for i, a in enumerate(cola, 1):
                if detener is not None and detener.is_set():
                    resumen["estado"], resumen["detalle"] = "cancelada", "Detenida por el usuario."
                    break
                self.informar(f"03 · Cola ({i} de {len(cola)})", a.nombre)
                try:
                    destino = self.procesar_archivo(a)
                except ProcesoDetenido as e:
                    resumen["estado"], resumen["detalle"] = "detenida", str(e)
                    db.alerta("modelos", f"Proceso detenido: {e} La factura «{a.nombre}» y el resto de la cola siguen pendientes.")
                    self._ev(a.id, "D", str(e), "error")
                    break
                if destino == "procesada":
                    resumen["procesadas"] += 1
                elif destino == "revision":
                    resumen["revision"] += 1
                if destino in ("procesada", "revision"):
                    self._contar_movimiento("procesadas" if destino == "procesada" else "revision")
        except AlmacenError as e:
            resumen["estado"], resumen["detalle"] = "error", str(e)
            db.alerta("drive", f"Problema con Google Drive: {e}")
            self._ev(None, "01", str(e), "error")
        except Exception as e:  # noqa: BLE001 - la corrida nunca debe morir sin registro
            resumen["estado"], resumen["detalle"] = "error", f"{type(e).__name__}: {e}"
            self._ev(None, "—", f"Error inesperado: {type(e).__name__}: {e}", "error")
        finally:
            self.informar("14 · Contando archivos", None)
            self._actualizar_contadores()
            db.cerrar_corrida(self.cid, resumen["estado"], encontrados=resumen["encontrados"],
                              procesadas=resumen["procesadas"], revision=resumen["revision"],
                              ignorados=resumen["ignorados"], detalle=resumen["detalle"])
            self.informar("", None)
        return resumen

    @staticmethod
    def _contar_movimiento(destino: str) -> None:
        """Ajusta el último conteo sin volver a listar Drive (el conteo exacto se hace al final)."""
        c = db.contadores()
        if "pendientes" in c:
            db.guardar_contadores({"pendientes": max(0, c["pendientes"] - 1), destino: c.get(destino, 0) + 1})

    def _actualizar_contadores(self) -> None:
        if self.almacen is None:
            return
        try:
            archivos = self.almacen.listar_entrada()
            db.guardar_contadores({
                "pendientes": sum(1 for a in archivos if a.admitido),
                "ignorados": sum(1 for a in archivos if not a.admitido),
                "procesadas": self.almacen.contar("procesadas"),
                "revision": self.almacen.contar("revision"),
                "resultados": self.almacen.enlace_resultados(),
                "actualizado": db.ahora(),
            })
        except AlmacenError as e:
            self._ev(None, "14", f"No se pudieron contar los archivos: {e}", "aviso")

    # ── una factura ───────────────────────────────────────
    def procesar_archivo(self, a: ArchivoDrive) -> str:
        """Devuelve 'procesada', 'revision' u 'omitida'. Lanza ProcesoDetenido."""
        fila = db.registrar_archivo(a.dict(), self.cid)
        if fila["estado"] == "escrita":
            self._ev(a.id, "13", "Ya estaba registrada en la hoja; solo falta moverla.")
            return self._mover(a, fila, "procesadas", "procesada")
        if fila["estado"] == "revision_sin_mover":
            return self._mover(a, fila, "revision", "revision")

        self._ev(a.id, "02", f"Nueva: «{a.nombre}» ({a.mime}, {a.tamano or '?'} bytes).")
        dup = db.duplicado_por_md5(a.md5, a.id)
        if dup:
            return self._a_revision(a, "02", f"Duplicado exacto de «{dup['nombre']}», que ya fue procesado.", [])

        db.actualizar_archivo(a.id, estado="en_proceso", paso="04", motivo=None, intentos=0)
        self.informar("04 · Descargar y preparar", a.nombre)
        try:
            datos = self.almacen.descargar(a)
        except AlmacenError as e:
            db.actualizar_archivo(a.id, estado="pendiente", motivo=str(e))
            self._ev(a.id, "04", str(e), "aviso")
            if e.temporal:
                raise
            return "omitida"

        r = self.extraer_y_validar(a, datos)
        if not r.valida:
            motivo = r.evaluacion.motivo if r.evaluacion else (r.historial[-1]["motivo"] if r.historial else "Sin datos")
            db.actualizar_archivo(a.id, datos_json=r.evaluacion.datos if r.evaluacion else None,
                                  resultado_json={"evaluacion": r.evaluacion.dict() if r.evaluacion else None,
                                                  "historial": r.historial, "texto_ocr": r.texto_ocr})
            return self._a_revision(a, r.paso_fallo, motivo, r.historial)

        datos_ok = r.evaluacion.datos
        self.informar("10 · Cruce con catálogo", a.nombre)
        campos = self.config["validacion"]["campos"]
        cat = catalogo.aplicar(datos_ok, self.config["catalogo"], campos)
        self._ev(a.id, "10", f"{cat['lineas_catalogo']} de {cat['lineas_total']} línea(s) coinciden con el catálogo.")
        self._ev(a.id, "11", f"Total catálogo = {cat['total_catalogo']:.2f} ({cat['porcentaje']} % del subtotal).")
        db.actualizar_archivo(a.id, datos_json=datos_ok, modelo=r.modelo, intentos=len(r.historial),
                              numero_factura=str(datos_ok.get(campos["numero"], "")),
                              emisor=str(datos_ok.get(campos["emisor_nombre"], "")),
                              total=datos_ok.get(campos["total"]), total_catalogo=cat["total_catalogo"],
                              resultado_json={"evaluacion": r.evaluacion.dict(), "catalogo": cat,
                                              "historial": r.historial, "texto_ocr": r.texto_ocr})

        self.informar("12 · Registrar en la hoja", a.nombre)
        try:
            duplicada = self._registrar(a, datos_ok, cat, r)
        except AlmacenError as e:
            db.actualizar_archivo(a.id, estado="pendiente", paso="12", motivo=f"No se pudo escribir la hoja: {e}")
            self._ev(a.id, "12", f"No se pudo escribir la hoja; la factura queda pendiente: {e}", "error")
            if e.temporal:
                raise
            return "omitida"
        if duplicada:
            return self._a_revision(a, "12", duplicada, r.historial)
        db.actualizar_archivo(a.id, estado="escrita", paso="12")
        self._ev(a.id, "12", f"Registrada: 1 fila en {HOJA_FACTURAS} y {cat['lineas_total']} en {HOJA_DETALLE}.")
        return self._mover(a, db.archivo(a.id), "procesadas", "procesada", datos_ok)

    # ── pasos 05–09 ───────────────────────────────────────
    def extraer_y_validar(self, a: ArchivoDrive, datos: bytes) -> ResultadoFactura:
        cfg_p = self.config["preparacion"]
        esquema, reglas = self.config["esquema"], self.config["validacion"]
        maximo = int(self.config["modelos"].get("intentos_maximos", 3))
        historial: list[dict] = []
        self.informar("05 · Extracción IA", a.nombre)
        try:
            doc: Documento = preparar(a.nombre, a.mime, datos, int(cfg_p["max_paginas"]), int(cfg_p["dpi_pdf"]),
                                      int(cfg_p["lado_maximo_px"]))
        except ErrorDocumento as e:
            historial.append({"intento": 0, "modelo": "—", "resultado": "documento ilegible", "motivo": str(e)})
            self._ev(a.id, "05", str(e), "aviso")
            ev = Evaluacion(False, {}, motivo=f"Documento dañado o ilegible: {e}")
            return ResultadoFactura(False, ev, historial, paso_fallo="05")

        pista: str | None = None
        ultima: Evaluacion | None = None
        texto_ocr: str | None = None
        intentos_datos = 0
        no_factura: set[str] = set()
        while intentos_datos < maximo:
            disponibles = [x for x in self.cadena if x.id not in self.caidos]
            if not disponibles:
                db.actualizar_archivo(a.id, estado="pendiente", paso="D",
                                      motivo="Proceso detenido: ningún modelo disponible")
                raise ProcesoDetenido({x.nombre: self.caidos[x.id] for x in self.cadena})
            extractor = disponibles[min(intentos_datos, len(disponibles) - 1)]
            paso = "05" if extractor is self.cadena[0] and intentos_datos == 0 else "06"
            self.informar(f"{paso} · {extractor.nombre}", a.nombre)
            inicio = time.time()
            try:
                res = extractor.extraer(doc, esquema, pista)
            except ErrorProveedor as e:
                self.caidos[extractor.id] = str(e)
                historial.append({"intento": len(historial) + 1, "modelo": extractor.nombre,
                                  "resultado": "modelo no disponible", "motivo": str(e),
                                  "segundos": round(time.time() - inicio, 1)})
                self._ev(a.id, paso, f"{extractor.nombre} no disponible: {e}", "aviso")
                continue
            except ErrorDocumento as e:
                intentos_datos += 1
                historial.append({"intento": len(historial) + 1, "modelo": extractor.nombre,
                                  "resultado": "sin datos", "motivo": str(e), "segundos": round(time.time() - inicio, 1)})
                self._ev(a.id, paso, f"{extractor.nombre}: {e}", "aviso")
                ultima = Evaluacion(False, {}, motivo=str(e))
                if not e.reintentable:
                    break
                pista = str(e)
                continue

            texto_ocr = res.texto_ocr or texto_ocr
            intentos_datos += 1
            self.informar("07 · Validar esquema y montos", a.nombre)
            ev = evaluar(res.datos, esquema, reglas, res.confianza, res.es_factura, res.observaciones)
            historial.append({"intento": len(historial) + 1, "modelo": res.modelo,
                              "resultado": "válida" if ev.valida else "no válida", "motivo": ev.motivo,
                              "segundos": res.segundos, "confianza": res.confianza, "detalle": res.detalle})
            self._ev(a.id, "07", "Esquema correcto." if not ev.errores_esquema else "; ".join(ev.errores_esquema[:4]),
                     "info" if not ev.errores_esquema else "aviso")
            if ev.reglas:
                malas = [x for x in ev.reglas if not x.ok]
                self._ev(a.id, "08", "Montos cuadrados." if not malas else "; ".join(x.detalle for x in malas[:3]),
                         "info" if not malas else "aviso")
            self._ev(a.id, "09", f"{'Válida' if ev.valida else 'No válida'} ({res.modelo}, {res.segundos} s)."
                     + ("" if ev.valida else f" {ev.motivo}"), "info" if ev.valida else "aviso")
            ultima = ev
            if ev.valida:
                db.cerrar_alerta("modelos")
                return ResultadoFactura(True, ev, historial, res.modelo, texto_ocr)
            if not res.es_factura:
                no_factura.add(extractor.id)
                if len(no_factura) >= 2:  # dos modelos distintos coinciden: no vale la pena otro intento
                    break
            pista = ev.pista()
        return ResultadoFactura(False, ultima, historial, None, texto_ocr, paso_fallo="09")

    # ── pasos 12–13 y revisión ────────────────────────────
    def _registrar(self, a: ArchivoDrive, datos: dict, cat: dict, r: ResultadoFactura) -> str | None:
        """Escribe las filas. Devuelve un motivo si la factura ya estaba registrada por otro archivo."""
        campos = self.config["validacion"]["campos"]
        props = self.config["esquema"].get("properties", {})
        numero, emisor_id = str(datos.get(campos["numero"], "")), str(datos.get(campos["emisor_id"], ""))
        filas = self.almacen.leer_hoja(HOJA_FACTURAS)
        ya_escrita = False
        if filas:
            enc = [str(x) for x in filas[0]]
            ix_id = enc.index("ID archivo") if "ID archivo" in enc else None
            ix_num = enc.index(campos["numero"]) if campos["numero"] in enc else None
            ix_em = enc.index(campos["emisor_id"]) if campos["emisor_id"] in enc else None
            for f in filas[1:]:
                f = list(f) + [""] * (len(enc) - len(f))
                if ix_id is not None and f[ix_id] == a.id:
                    ya_escrita = True
                elif (ix_num is not None and ix_em is not None and numero and str(f[ix_num]) == numero
                      and str(f[ix_em]) == emisor_id):
                    return f"La factura {numero} de {emisor_id} ya estaba registrada (archivo «{f[enc.index('Archivo')] if 'Archivo' in enc else '?'}»)."
        if not ya_escrita:
            fila = {"ID archivo": a.id, "Procesada": datetime.now().strftime("%Y-%m-%d %H:%M"), "Archivo": a.nombre,
                    "Enlace": a.enlace or ""}
            for k, sub in props.items():
                v = datos.get(k)
                if sub.get("type") == "array" and sub.get("items", {}).get("type") == "object":
                    continue
                fila[k] = ", ".join(map(str, v)) if isinstance(v, list) else v
            fila.update({"Total catálogo": cat["total_catalogo"], "Líneas catálogo": f"{cat['lineas_catalogo']} de {cat['lineas_total']}",
                         "% catálogo": cat["porcentaje"], "Modelo": r.modelo, "Intentos": len(r.historial),
                         "Estado": "Procesada"})
            self.almacen.agregar_filas(HOJA_FACTURAS, [fila])
        detalle = self.almacen.leer_hoja(HOJA_DETALLE)
        if not any(len(f) and f[0] == a.id for f in detalle[1:]):
            lineas = datos.get(campos["lineas"]) or []
            filas_det = []
            for ln, marca in zip(lineas, cat["lineas"]):
                d = {"ID archivo": a.id, "N° factura": numero, "Emisor": datos.get(campos["emisor_nombre"], ""),
                     "Línea": marca["linea"]}
                d.update({k: v for k, v in ln.items() if not isinstance(v, (dict, list))})
                d.update({"Producto catálogo": marca["producto"] or "", "Código catálogo": marca["codigo"] or "",
                          "Coincidencia": marca["coincidencia"] or ""})
                filas_det.append(d)
            self.almacen.agregar_filas(HOJA_DETALLE, filas_det)
        return None

    def _nombre_final(self, a: ArchivoDrive, datos: dict | None) -> str | None:
        if not datos or not self.config["drive"].get("renombrar_al_mover"):
            return None
        c = self.config["validacion"]["campos"]
        partes = [str(datos.get("fecha_emision", "")), str(datos.get(c["emisor_nombre"], "")), str(datos.get(c["numero"], ""))]
        base = "_".join(re.sub(r"[^\w\-]+", "-", p).strip("-") for p in partes if p)
        return f"{base}{PurePosixPath(a.nombre).suffix}" if base else None

    def _mover(self, a: ArchivoDrive, fila: dict, destino: str, estado: str, datos: dict | None = None) -> str:
        paso = "13" if destino == "procesadas" else "R"
        self.informar("13 · Mover a Procesadas" if destino == "procesadas" else "R · Mover a Revisión", a.nombre)
        try:
            self.almacen.mover(a, destino, self._nombre_final(a, datos) if destino == "procesadas" else None)
        except AlmacenError as e:
            pendiente = "escrita" if destino == "procesadas" else "revision_sin_mover"
            db.actualizar_archivo(a.id, estado=pendiente, motivo=f"No se pudo mover: {e}")
            self._ev(a.id, paso, f"No se pudo mover el archivo; se reintenta en la próxima corrida: {e}", "error")
            if e.temporal:
                raise
            return "omitida"
        carpeta = self.config["drive"]["carpeta_procesadas" if destino == "procesadas" else "carpeta_revision"]
        db.actualizar_archivo(a.id, estado=estado, paso=paso)
        self._ev(a.id, paso, f"Movida a {self.config['drive']['carpeta_entrada']}/{carpeta}.")
        return estado

    def _a_revision(self, a: ArchivoDrive, paso: str, motivo: str, historial: list[dict]) -> str:
        self.informar("R · Revisión manual", a.nombre)
        db.actualizar_archivo(a.id, estado="revision_sin_mover", paso=paso, motivo=motivo, intentos=len(historial))
        self._ev(a.id, "R", f"A revisión manual: {motivo}", "aviso")
        modelos = " · ".join(f"{h['modelo']} {'✓' if h['resultado'] == 'válida' else '✗'}" for h in historial) or "ninguno"
        try:
            self.almacen.agregar_filas(HOJA_ERRORES, [{
                "Fecha": datetime.now().strftime("%Y-%m-%d %H:%M"), "ID archivo": a.id, "Archivo": a.nombre,
                "Enlace": a.enlace or "", "Paso": f"{paso} · {NOMBRE_PASO.get(paso, '')}".strip(" ·"),
                "Motivo": motivo, "Modelos intentados": modelos}])
        except AlmacenError as e:
            self._ev(a.id, "R", f"No se pudo escribir en la hoja {HOJA_ERRORES}: {e}", "aviso")
        return self._mover(a, db.archivo(a.id), "revision", "revision")
