"""Crea una carpeta de datos de DEMOSTRACIÓN para probar el frontend y tomar capturas.

Genera 45 días de corridas, facturas y bitácora con emisores ficticios. No toca Google Drive
ni la carpeta data/ real: todo va a la carpeta indicada.

Uso:
    .venv/Scripts/python tests/frontend/datos_demo.py <carpeta_destino> [--vacio]

--vacio crea la carpeta sin corridas ni facturas (para probar los estados vacíos).
"""
from __future__ import annotations

import json
import os
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

EMISORES = [
    ("Ferretería El Martillo, S.A.", "4587123-5"), ("Distribuidora La Central", "7781245-K"),
    ("Papelería Continental", "1209876-3"), ("Materiales y Construcción Roca", "9034521-1"),
    ("Abarrotes San José", "5567812-0"), ("Pinturas del Valle", "3321908-7"),
    ("Agroinsumos Los Altos", "6612093-4"), ("Comercial Santa Elena", "2290341-8"),
]
PRODUCTOS = [
    ("Cemento gris 42.5 kg", 82.5, "Cemento"), ("Varilla corrugada 3/8 x 6 m", 41.9, "Varilla"),
    ("Pintura látex blanca galón", 129.0, "Pintura"), ("Arroz blanco 46 kg", 315.0, "Arroz"),
    ("Aceite vegetal 1 L", 21.75, "Aceite vegetal"), ("Tornillo punta broca 1\"", 0.85, None),
    ("Cinta métrica 8 m", 54.0, None), ("Resma papel bond carta", 38.5, None),
    ("Guantes de cuero", 27.0, None), ("Brocha 3\"", 18.9, None),
]
MODELOS = [("GLM-OCR local + gpt-5.4-nano", 0.62, (38, 75)), ("Texto del PDF + gpt-5.4-nano", 0.25, (2, 5)),
           ("OpenAI visión gpt-5.4-mini", 0.13, (3, 8))]
REVISION = [
    ("Los montos no cuadran: Σ importes 1,240.00 ≠ subtotal 1,420.00", "08"),
    ("El modelo indica que no es una factura legible: la imagen está borrosa", "09"),
    ("Documento dañado o ilegible: El PDF está protegido con contraseña y no se puede leer.", "05"),
    ("Duplicado exacto de «factura_proveedor.pdf», que ya fue procesado.", "02"),
    ("Datos incompletos: falta emisor_id_fiscal", "07"),
    ("Confianza baja del modelo (0.42 < 0.60): sello sobre los importes", "09"),
]


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    destino = Path(sys.argv[1]).resolve()
    vacio = "--vacio" in sys.argv
    destino.mkdir(parents=True, exist_ok=True)
    for f in ("estado.db", "estado.db-wal", "estado.db-shm", "config.json"):
        (destino / f).unlink(missing_ok=True)
    os.environ["FACTURAS_IA_DATA"] = str(destino)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from app import configuracion, db  # noqa: E402

    cfg = json.loads(json.dumps(configuracion.DEFAULT))
    cfg["drive"]["proveedor"] = "local"
    cfg["drive"]["carpeta_local"] = str(destino / "drive_local")
    cfg["frecuencia"]["activo"] = False  # la demo nunca procesa sola
    (destino / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    db.conexion()
    if vacio:
        print(f"Carpeta vacía lista en {destino}")
        return

    rnd = random.Random(2026)
    hoy = datetime.now().replace(second=0, microsecond=0)
    n_archivo = 0
    for d in range(44, -1, -1):
        dia = hoy - timedelta(days=d)
        horas = sorted(rnd.sample([7, 9, 11, 13, 15, 17], k=rnd.choice([1, 2, 2, 3])))
        for hora in horas:
            inicio = dia.replace(hour=hora, minute=rnd.randint(0, 50))
            if inicio > hoy:
                continue
            origen = rnd.choices(["programada", "manual"], [0.75, 0.25])[0]
            cid = db._x("INSERT INTO corridas(inicio,estado,origen) VALUES(?,?,?)", (inicio.isoformat(), "en curso", origen))
            t = inicio
            ev = lambda fid, paso, msg, nivel="info": db._x(  # noqa: E731
                "INSERT INTO eventos(corrida_id,file_id,ts,nivel,paso,mensaje) VALUES(?,?,?,?,?,?)",
                (cid, fid, t.isoformat(), nivel, paso, msg))
            cantidad = rnd.choices([0, 1, 2, 3, 4, 5, 6, 8], [3, 4, 5, 5, 4, 3, 2, 1])[0]
            ev(None, "01", "Carpeta «Facturas IA» encontrada con sus subcarpetas.")
            ev(None, "03", f"{cantidad} factura(s) pendiente(s); se procesan {cantidad} en esta corrida.")
            proc = rev = 0
            detenida = d in (12, 27) and hora == horas[0] and cantidad > 0
            for _ in range(cantidad):
                n_archivo += 1
                emisor, nit = rnd.choice(EMISORES)
                ext = rnd.choices(["pdf", "jpg", "png"], [0.55, 0.35, 0.10])[0]
                nombre = f"{emisor.split()[0].lower().strip(',')}_{n_archivo:04d}.{ext}"
                fid = f"demo-{n_archivo:05d}"
                modelo, _, rango = rnd.choices(MODELOS, [m[1] for m in MODELOS])[0]
                if ext == "pdf" and rnd.random() < 0.5:
                    modelo, rango = MODELOS[1][0], MODELOS[1][2]
                lineas = []
                for prod, precio, _cat in rnd.sample(PRODUCTOS, k=rnd.randint(2, 6)):
                    cant = rnd.choice([1, 2, 3, 5, 10, 12, 20, 40])
                    lineas.append({"descripcion": prod, "cantidad": cant, "precio_unitario": precio,
                                   "descuento": 0, "importe": round(cant * precio, 2)})
                subtotal = round(sum(x["importe"] for x in lineas), 2)
                impuestos = round(subtotal * 0.12, 2)
                total = round(subtotal + impuestos, 2)
                marcas = [{"producto": next((c for p, _, c in PRODUCTOS if p == x["descripcion"]), None),
                           "coincidencia": "palabra clave"} for x in lineas]
                cat_total = round(sum(x["importe"] for x, m in zip(lineas, marcas) if m["producto"]), 2)
                datos = {"numero_factura": f"{emisor[:2].upper()}-{rnd.randint(1000, 99999)}",
                         "fecha_emision": (inicio - timedelta(days=rnd.randint(0, 6))).date().isoformat(),
                         "emisor_nombre": emisor, "emisor_id_fiscal": nit, "receptor_nombre": "Constructora Demo",
                         "receptor_id_fiscal": "1234567-8", "moneda": "GTQ", "lineas": lineas,
                         "subtotal": subtotal, "descuento_total": 0, "impuestos": impuestos, "otros_cargos": 0, "total": total}
                seg = round(rnd.uniform(*rango), 1)
                es_rev = rnd.random() < 0.16
                if detenida:
                    estado, motivo, paso = "pendiente", "Proceso detenido: ningún modelo disponible", "05"
                elif es_rev:
                    motivo, paso_fallo = rnd.choices(REVISION, [5, 3, 1, 2, 2, 1])[0]
                    estado, paso = "revision", "R"
                else:
                    estado, motivo, paso = "procesada", None, "13"
                historial = [{"intento": 1, "modelo": modelo, "resultado": "no válida" if es_rev else "válida",
                              "motivo": motivo or "Válida", "segundos": seg, "confianza": 0.9}]
                if es_rev and rnd.random() < 0.6:
                    historial.append({"intento": 2, "modelo": MODELOS[2][0], "resultado": "no válida",
                                      "motivo": motivo, "segundos": round(rnd.uniform(3, 8), 1), "confianza": 0.7})
                reglas = [{"regla": "Σ importes = subtotal", "ok": not (es_rev and "montos" in (motivo or "")),
                           "detalle": "Σ importes 1,240.00 ≠ subtotal 1,420.00"},
                          {"regla": "subtotal − descuento + impuestos + otros = total", "ok": True, "detalle": ""},
                          {"regla": "Confianza ≥ 0.60", "ok": not (es_rev and "Confianza" in (motivo or "")), "detalle": "0.42"}]
                resultado = {"evaluacion": {"valida": not es_rev, "motivo": motivo or "Válida", "errores_esquema": [], "reglas": reglas},
                             "catalogo": None if es_rev else {"lineas": marcas, "lineas_catalogo": sum(bool(m["producto"]) for m in marcas),
                                                              "lineas_total": len(marcas), "total_catalogo": cat_total,
                                                              "porcentaje": round(100 * cat_total / subtotal)},
                             "historial": historial, "texto_ocr": f"FACTURA\n{emisor}\nNIT {nit}\n..." if "GLM" in modelo else None}
                t = t + timedelta(seconds=seg + rnd.uniform(4, 12))
                db._x("""INSERT INTO archivos(file_id,nombre,mime,md5,tamano,enlace,estado,paso,motivo,intentos,modelo,
                         numero_factura,emisor,total,total_catalogo,datos_json,resultado_json,corrida_id,creado,actualizado)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (fid, nombre, "application/pdf" if ext == "pdf" else f"image/{'jpeg' if ext == 'jpg' else ext}",
                       f"{n_archivo:032x}", rnd.randint(40_000, 900_000), None, estado, paso, motivo, len(historial),
                       None if estado != "procesada" else modelo, datos["numero_factura"], emisor,
                       total if estado == "procesada" else None, cat_total if estado == "procesada" else None,
                       json.dumps(datos, ensure_ascii=False), json.dumps(resultado, ensure_ascii=False),
                       cid, inicio.isoformat(), t.isoformat()))
                ev(fid, "02", f"Nueva: «{nombre}».")
                ev(fid, "05", f"Extracción con {modelo}: {seg} s.")
                if detenida:
                    ev(fid, "D", "Ningún modelo disponible: Ollama no responde y OpenAI devolvió 503. La factura queda pendiente.", "error")
                    break
                if es_rev:
                    ev(fid, "09", f"No válida: {motivo}", "aviso")
                    ev(fid, "R", "Movida a «Revisión manual».", "aviso")
                    rev += 1
                else:
                    ev(fid, "08", "Montos cuadrados.")
                    ev(fid, "12", f"Registrada: 1 fila en Facturas y {len(lineas)} en Detalle.")
                    ev(fid, "13", "Movida a «Procesadas».")
                    proc += 1
            fin = t + timedelta(seconds=rnd.uniform(3, 9))
            ev(None, "14", "Conteo actualizado.")
            db._x("UPDATE corridas SET fin=?, estado=?, encontrados=?, procesadas=?, revision=?, detalle=? WHERE id=?",
                  (fin.isoformat(), "detenida" if detenida else "completada", cantidad, proc, rev,
                   "Ningún modelo disponible" if detenida else None, cid))

    pend = sum(1 for r in db._q("SELECT 1 FROM archivos WHERE estado='pendiente'"))
    db.guardar_contadores({"pendientes": pend + 3, "ignorados": 1,
                           "procesadas": db._q("SELECT COUNT(*) n FROM archivos WHERE estado='procesada'")[0]["n"],
                           "revision": db._q("SELECT COUNT(*) n FROM archivos WHERE estado='revision'")[0]["n"],
                           "resultados": "https://docs.google.com/spreadsheets/d/demo", "actualizado": db.ahora()})
    print(f"Demo lista en {destino}: {n_archivo} facturas.")


if __name__ == "__main__":
    main()
