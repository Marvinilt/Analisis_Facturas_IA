"""Pruebas sin red: normalización, validación, catálogo y reglas de la cadena de modelos."""
from __future__ import annotations

import copy
import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("FACTURAS_IA_DATA", tempfile.mkdtemp(prefix="facturas_ia_test_"))

from app import catalogo, configuracion, db  # noqa: E402
from app.extraction.base import ErrorDocumento, ErrorProveedor, Extractor, ResultadoExtraccion  # noqa: E402
from app.extraction.instrucciones import esquema_estricto, parsear_json  # noqa: E402
from app.pipeline import Procesador, ProcesoDetenido  # noqa: E402
from app.storage.local import DriveLocal  # noqa: E402
from app.validacion import a_fecha, a_numero, evaluar  # noqa: E402

CFG = configuracion.DEFAULT
FACTURA = {
    "numero_factura": "F001-000457", "fecha_emision": "18/11/2026", "emisor_nombre": "Ferretería El Tornillo S.A.",
    "emisor_id_fiscal": "0614-250390-102-3", "moneda": "USD",
    "lineas": [
        {"descripcion": "Cemento gris 42.5 kg", "cantidad": "10", "precio_unitario": "9,50", "importe": "95,00"},
        {"descripcion": "Varilla corrugada 3/8\"", "cantidad": 20, "precio_unitario": 12.25, "importe": 245},
        {"descripcion": "Tornillo autorroscante", "cantidad": 4, "precio_unitario": 7.5, "importe": 30},
        {"descripcion": "Pintrua látex blanca", "cantidad": 6, "precio_unitario": 50, "importe": 300},
        {"descripcion": "Brocha 3\"", "cantidad": 10, "precio_unitario": 3, "importe": 30},
        {"descripcion": "Lija de agua #120", "cantidad": 100, "precio_unitario": 3, "importe": 300},
    ],
    "subtotal": "1.000,00", "impuestos": "130,00", "total": "1.130,00", "descuento_total": None,
}


@pytest.mark.parametrize("texto,valor", [
    ("1.130,00", 1130.0), ("1,130.00", 1130.0), ("$ 1,130.00", 1130.0), ("38,90", 38.9), ("1,130", 1130.0),
    ("(25.00)", -25.0), ("-", None), ("", None), (12, 12.0), ("1.234.567", 1234567.0),
])
def test_numeros(texto, valor):
    assert a_numero(texto) == valor


@pytest.mark.parametrize("texto,valor", [("18/11/2026", "2026-11-18"), ("2026-11-18", "2026-11-18"),
                                          ("05-01-26", "2026-01-05")])
def test_fechas(texto, valor):
    assert a_fecha(texto) == valor


def test_factura_valida():
    ev = evaluar(copy.deepcopy(FACTURA), CFG["esquema"], CFG["validacion"], confianza=0.95)
    assert ev.valida, ev.motivo
    assert ev.datos["fecha_emision"] == "2026-11-18"
    assert ev.datos["total"] == 1130.0


def test_total_no_cuadra():
    f = copy.deepcopy(FACTURA)
    f["total"] = "1.180,00"
    ev = evaluar(f, CFG["esquema"], CFG["validacion"])
    assert not ev.valida
    assert "1180.00" in ev.motivo and "1130.00" in ev.motivo
    assert "total leído" in ev.pista()


def test_linea_no_cuadra():
    f = copy.deepcopy(FACTURA)
    f["lineas"][1]["importe"] = 254
    f["subtotal"] = 1009
    f["total"] = 1139
    ev = evaluar(f, CFG["esquema"], CFG["validacion"])
    assert not ev.valida and "Línea" not in ev.motivo or "254.00" in ev.motivo


def test_descuento_impreso_negativo():
    """La factura imprime «Descuento -25,00»: debe restarse igual que «25,00»."""
    f = copy.deepcopy(FACTURA)
    f.update(descuento_total="-25,00", impuestos="126,75", otros_cargos="35,00", total="1.136,75")
    ev = evaluar(f, CFG["esquema"], CFG["validacion"])
    assert ev.valida, ev.motivo
    f["descuento_total"] = "25,00"
    assert evaluar(f, CFG["esquema"], CFG["validacion"]).valida


def test_falta_campo():
    f = copy.deepcopy(FACTURA)
    del f["numero_factura"]
    ev = evaluar(f, CFG["esquema"], CFG["validacion"])
    assert not ev.valida and "numero_factura" in ev.motivo


def test_no_es_factura():
    ev = evaluar({}, CFG["esquema"], CFG["validacion"], es_factura=False, observaciones="Es un acta")
    assert not ev.valida and "no es una factura" in ev.motivo


def test_confianza_baja():
    ev = evaluar(copy.deepcopy(FACTURA), CFG["esquema"], CFG["validacion"], confianza=0.3)
    assert not ev.valida and "Confianza baja" in ev.motivo


def test_catalogo():
    ev = evaluar(copy.deepcopy(FACTURA), CFG["esquema"], CFG["validacion"])
    cat = catalogo.aplicar(ev.datos, CFG["catalogo"], CFG["validacion"]["campos"])
    assert cat["lineas_catalogo"] == 3
    assert cat["total_catalogo"] == 640.0
    tipos = {m["producto"]: m["coincidencia"] for m in cat["lineas"] if m["producto"]}
    assert tipos["Pintura"].startswith("parecido")  # «Pintrua» con error de tipeo
    assert tipos["Cemento"] == "palabra clave"


@pytest.mark.parametrize("desc,producto", [
    ("Pegamento PVC 1/4 gal", None), ("Thinner 1 gal", None), ("Carretilla 5 pies3", None),
    ("ACEITE VEGETAL 3.785 L", "Aceite vegetal"), ("Arroz blanco precocido", "Arroz"),
    ("Hierro corrugado 1/2", "Varilla"),
])
def test_catalogo_sin_falsos_positivos(desc, producto):
    c = catalogo.coincidir(desc, CFG["catalogo"]["productos"], 85)
    assert (c.producto if c else None) == producto


def test_esquema_estricto():
    e = esquema_estricto(CFG["esquema"])
    factura = e["properties"]["factura"]
    assert set(factura["required"]) == set(factura["properties"])
    assert factura["properties"]["receptor_nombre"]["type"] == ["string", "null"]
    assert factura["properties"]["total"]["type"] == "number"
    assert factura["additionalProperties"] is False


def test_parsear_json():
    assert parsear_json('```json\n{"a": 1,}\n```') == {"a": 1}


# ── cadena de modelos con extractores simulados ───────────────────────────────
class Falso(Extractor):
    def __init__(self, id_, comportamiento):
        self.id, self.nombre = id_, id_
        self.comportamiento = list(comportamiento)
        self.llamadas = 0

    def extraer(self, doc, esquema, pista=None):
        self.llamadas += 1
        c = self.comportamiento.pop(0) if len(self.comportamiento) > 1 else self.comportamiento[0]
        if c == "caido":
            raise ErrorProveedor(f"{self.id} sin servicio")
        if c == "ilegible":
            raise ErrorDocumento("ilegible")
        datos = copy.deepcopy(FACTURA)
        if c == "malo":
            datos["total"] = "1.180,00"
        return ResultadoExtraccion(datos=datos, modelo=self.id, segundos=0.1, confianza=0.9)


@pytest.fixture()
def drive(tmp_path: Path):
    cfg = copy.deepcopy(CFG)
    cfg["drive"]["proveedor"] = "local"
    cfg["drive"]["carpeta_local"] = str(tmp_path)
    entrada = tmp_path / cfg["drive"]["carpeta_entrada"]
    entrada.mkdir()
    origen = Path(__file__).parent / "docs" / "factura_01_ferreteria.pdf"
    if not origen.exists():
        pytest.skip("Faltan documentos de prueba: ejecuta tests/generar_documentos.py")
    (entrada / "f1.pdf").write_bytes(origen.read_bytes())
    return cfg, DriveLocal(cfg["drive"]), entrada


def _correr(cfg, alm, cadena):
    db.reiniciar_conexion()
    p = Procesador(config=cfg, almacen=alm, cadena=cadena)
    return p.correr("prueba"), cadena


def test_todos_los_modelos_caidos_detiene_y_deja_pendiente(drive):
    cfg, alm, entrada = drive
    res, cad = _correr(cfg, alm, [Falso("a", ["caido"]), Falso("b", ["caido"])])
    assert res["estado"] == "detenida"
    assert (entrada / "f1.pdf").exists(), "la factura debe quedar pendiente en la carpeta de entrada"
    assert not any((entrada / cfg["drive"]["carpeta_revision"]).iterdir())


def test_primario_caido_usa_respaldo(drive):
    cfg, alm, entrada = drive
    res, cad = _correr(cfg, alm, [Falso("a", ["caido"]), Falso("b", ["ok"])])
    assert res["procesadas"] == 1
    assert (entrada / cfg["drive"]["carpeta_procesadas"] / "f1.pdf").exists()


def test_datos_malos_reintenta_y_luego_valida(drive):
    cfg, alm, entrada = drive
    a, b = Falso("a", ["malo"]), Falso("b", ["ok"])
    res, _ = _correr(cfg, alm, [a, b])
    assert res["procesadas"] == 1 and a.llamadas == 1 and b.llamadas == 1


def test_datos_siempre_malos_va_a_revision(drive):
    cfg, alm, entrada = drive
    a, b = Falso("a", ["malo"]), Falso("b", ["malo"])
    res, _ = _correr(cfg, alm, [a, b])
    assert res["revision"] == 1
    assert a.llamadas + b.llamadas == cfg["modelos"]["intentos_maximos"]
    assert (entrada / cfg["drive"]["carpeta_revision"] / "f1.pdf").exists()
    filas = alm.leer_hoja("Errores")
    assert filas and "no cuadran" in str(filas[1])


def test_respaldo_cae_tras_datos_malos_detiene(drive):
    """Primario da datos malos y luego el respaldo no responde: sin modelos → detener, no revisión."""
    cfg, alm, entrada = drive
    a, b = Falso("a", ["malo", "caido"]), Falso("b", ["caido"])
    res, _ = _correr(cfg, alm, [a, b])
    assert res["estado"] == "detenida"
    assert (entrada / "f1.pdf").exists()
