"""Genera facturas de prueba (PDF con texto, PDF escaneado, JPG, PNG) y casos de error.

Uso:  .venv/Scripts/python tests/generar_documentos.py
Salida: tests/docs/*  y  tests/docs/esperado.json  (resultado esperado de cada archivo)
"""
from __future__ import annotations

import io
import json
import random
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

OUT = Path(__file__).parent / "docs"
random.seed(7)


@dataclass
class Linea:
    descripcion: str
    cantidad: float
    precio: float
    descuento: float = 0.0

    @property
    def importe(self) -> float:
        return round(self.cantidad * self.precio - self.descuento, 2)


@dataclass
class Factura:
    emisor: str
    id_fiscal: str
    direccion: str
    numero: str
    fecha: str  # dd/mm/aaaa como se imprime
    cliente: str
    cliente_id: str
    moneda: str
    lineas: list[Linea]
    tasa_iva: float = 0.13
    descuento_global: float = 0.0
    envio: float = 0.0
    formato: str = "es"  # es: 1.234,56   us: 1,234.56
    total_impreso: float | None = None  # para forzar un total que no cuadra
    color: tuple = (0.08, 0.28, 0.45)
    extra: dict = field(default_factory=dict)

    @property
    def subtotal(self) -> float:
        return round(sum(l.importe for l in self.lineas), 2)

    @property
    def iva(self) -> float:
        return round((self.subtotal - self.descuento_global) * self.tasa_iva, 2)

    @property
    def total(self) -> float:
        return round(self.subtotal - self.descuento_global + self.iva + self.envio, 2)


def fmt(v: float, f: str) -> str:
    s = f"{v:,.2f}"
    if f == "es":
        s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return s


def dibujar_factura(c: canvas.Canvas, fx: Factura, lineas: list[Linea], pagina: int, paginas: int, con_totales: bool):
    w, h = letter
    r, g, b = fx.color
    c.setFillColorRGB(r, g, b)
    c.rect(0, h - 28 * mm, w, 28 * mm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 17)
    c.drawString(18 * mm, h - 14 * mm, fx.emisor)
    c.setFont("Helvetica", 9)
    c.drawString(18 * mm, h - 20 * mm, fx.direccion)
    c.drawString(18 * mm, h - 24.5 * mm, f"NIT: {fx.id_fiscal}")
    c.setFont("Helvetica-Bold", 20)
    c.drawRightString(w - 18 * mm, h - 15 * mm, "FACTURA")
    c.setFont("Helvetica", 9)
    c.drawRightString(w - 18 * mm, h - 21 * mm, f"Página {pagina} de {paginas}")

    c.setFillColor(colors.black)
    y = h - 40 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(18 * mm, y, "Cliente")
    c.drawString(120 * mm, y, "No. de factura")
    c.setFont("Helvetica", 10)
    c.drawString(18 * mm, y - 5 * mm, fx.cliente)
    c.drawString(18 * mm, y - 10 * mm, f"NIT: {fx.cliente_id}")
    c.drawString(120 * mm, y - 5 * mm, fx.numero)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(160 * mm, y, "Fecha")
    c.setFont("Helvetica", 10)
    c.drawString(160 * mm, y - 5 * mm, fx.fecha)
    c.drawString(120 * mm, y - 10 * mm, f"Moneda: {fx.moneda}")

    # tabla
    y = h - 62 * mm
    cols = [18, 36, 128, 152, 170, 197]  # mm: cant, desc, p.unit, desc, importe, fin
    c.setFillColorRGB(0.92, 0.94, 0.96)
    c.rect(18 * mm, y - 2 * mm, (197 - 18) * mm, 7 * mm, stroke=0, fill=1)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(20 * mm, y, "Cant.")
    c.drawString(cols[1] * mm, y, "Descripción")
    c.drawRightString((cols[3] - 2) * mm, y, "P. unitario")
    c.drawRightString((cols[4] - 2) * mm, y, "Desc.")
    c.drawRightString((cols[5] - 2) * mm, y, "Importe")
    c.setFont("Helvetica", 9.5)
    y -= 8 * mm
    for ln in lineas:
        q = int(ln.cantidad) if float(ln.cantidad).is_integer() else ln.cantidad
        c.drawString(20 * mm, y, str(q))
        c.drawString(cols[1] * mm, y, ln.descripcion)
        c.drawRightString((cols[3] - 2) * mm, y, fmt(ln.precio, fx.formato))
        c.drawRightString((cols[4] - 2) * mm, y, fmt(ln.descuento, fx.formato) if ln.descuento else "-")
        c.drawRightString((cols[5] - 2) * mm, y, fmt(ln.importe, fx.formato))
        c.setStrokeColorRGB(0.85, 0.87, 0.9)
        c.line(18 * mm, y - 2.5 * mm, 197 * mm, y - 2.5 * mm)
        y -= 7 * mm

    if not con_totales:
        c.setFont("Helvetica-Oblique", 9)
        c.drawString(20 * mm, y - 4 * mm, "Continúa en la página siguiente...")
        return

    y -= 4 * mm
    filas = [("Subtotal", fx.subtotal)]
    if fx.descuento_global:
        filas.append(("Descuento", -fx.descuento_global))
    filas.append((f"IVA {int(round(fx.tasa_iva * 100))}%", fx.iva))
    if fx.envio:
        filas.append(("Envío", fx.envio))
    total = fx.total_impreso if fx.total_impreso is not None else fx.total
    c.setFont("Helvetica", 10)
    for etiqueta, valor in filas:
        c.drawString(140 * mm, y, etiqueta)
        c.drawRightString(195 * mm, y, fmt(valor, fx.formato))
        y -= 6 * mm
    y -= 2 * mm
    c.setFillColorRGB(r, g, b)
    c.rect(136 * mm, y - 3 * mm, 61 * mm, 8 * mm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(140 * mm, y, f"TOTAL {fx.moneda}")
    c.drawRightString(195 * mm, y, fmt(total, fx.formato))
    c.setFillColor(colors.grey)
    c.setFont("Helvetica", 8)
    c.drawString(18 * mm, 15 * mm, "Documento generado para pruebas del sistema Facturas IA. Sin validez fiscal.")


def pdf_factura(fx: Factura, por_pagina: int = 18, encrypt: str | None = None) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter, encrypt=encrypt)
    c.setTitle(f"Factura {fx.numero}")
    grupos = [fx.lineas[i:i + por_pagina] for i in range(0, len(fx.lineas), por_pagina)]
    for i, grupo in enumerate(grupos, 1):
        dibujar_factura(c, fx, grupo, i, len(grupos), con_totales=(i == len(grupos)))
        c.showPage()
    c.save()
    return buf.getvalue()


def pdf_a_imagenes(data: bytes, dpi: int = 150) -> list[Image.Image]:
    doc = pdfium.PdfDocument(data)
    return [p.render(scale=dpi / 72).to_pil().convert("RGB") for p in doc]


def foto(img: Image.Image, angulo: float = 2.0, ruido: int = 10, blur: float = 0.6, escala: float = 0.8) -> Image.Image:
    """Simula una foto de celular: fondo de mesa, giro, ruido, desenfoque leve."""
    img = img.resize((int(img.width * escala), int(img.height * escala)))
    fondo = Image.new("RGB", (img.width + 140, img.height + 160), (96, 84, 70))
    fondo.paste(img, (70, 80))
    fondo = fondo.rotate(angulo, expand=False, fillcolor=(96, 84, 70))
    px = fondo.load()
    for _ in range(fondo.width * fondo.height // 9):
        x, y = random.randrange(fondo.width), random.randrange(fondo.height)
        r, g, b = px[x, y]
        d = random.randint(-ruido, ruido)
        px[x, y] = (max(0, min(255, r + d)), max(0, min(255, g + d)), max(0, min(255, b + d)))
    # sombra suave en una esquina
    sombra = Image.new("L", fondo.size, 0)
    ImageDraw.Draw(sombra).ellipse((-fondo.width // 2, -fondo.height // 2, fondo.width // 2, fondo.height // 3), fill=40)
    sombra = sombra.filter(ImageFilter.GaussianBlur(80))
    fondo = Image.composite(Image.new("RGB", fondo.size, (0, 0, 0)), fondo, sombra)
    return fondo.filter(ImageFilter.GaussianBlur(blur))


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    esperado: dict[str, dict] = {}

    # 1. PDF con texto, formato 1.234,56, coincide con catálogo
    f1 = Factura("Ferretería El Tornillo S.A.", "0614-250390-102-3", "Calle Los Almendros 25, San Salvador",
                 "F001-000457", "18/11/2026", "Constructora Ríos y Asociados", "0614-110185-101-9", "USD", [
                     Linea("Cemento gris 42.5 kg", 10, 9.50),
                     Linea("Varilla corrugada 3/8\" x 6 m", 20, 12.25),
                     Linea("Tornillo autorroscante caja 100 u", 4, 7.50),
                     Linea("Pintura látex blanca 1 galón", 6, 50.00),
                     Linea("Brocha 3\"", 10, 3.00),
                     Linea("Lija de agua #120", 100, 3.00),
                 ])
    (OUT / "factura_01_ferreteria.pdf").write_bytes(pdf_factura(f1))
    esperado["factura_01_ferreteria.pdf"] = {"resultado": "procesada", "numero_factura": f1.numero, "total": f1.total,
                                              "subtotal": f1.subtotal, "total_catalogo": 640.00, "lineas_catalogo": 3}

    # 2. Foto JPG de distribuidora de alimentos
    f2 = Factura("Distribuidora La Cosecha", "0210-080875-001-4", "Km 12 Carretera al Puerto, Santa Tecla",
                 "A-2026-01893", "19/11/2026", "Comedor Doña Tere", "0511-200990-104-2", "USD", [
                     Linea("Arroz blanco precocido saco 45 kg", 3, 38.90),
                     Linea("Aceite vegetal 3.785 L", 6, 11.25),
                     Linea("Frijol rojo seda 25 lb", 4, 21.40),
                     Linea("Azúcar refinada 50 lb", 2, 24.75),
                     Linea("Sal yodada 1 kg (fardo 24)", 1, 9.60),
                 ], color=(0.12, 0.42, 0.25))
    img2 = foto(pdf_a_imagenes(pdf_factura(f2), dpi=150)[0], angulo=1.8)
    img2.save(OUT / "factura_02_distribuidora.jpg", quality=82)
    esperado["factura_02_distribuidora.jpg"] = {"resultado": "procesada", "numero_factura": f2.numero, "total": f2.total,
                                                 "subtotal": f2.subtotal, "total_catalogo": round(3 * 38.90 + 6 * 11.25, 2),
                                                 "lineas_catalogo": 2}

    # 3. PNG limpio, formato 1,234.56 (EE. UU.), sin coincidencias con el catálogo
    f3 = Factura("Papelería y Oficina Central", "0614-030301-109-7", "Av. Olímpica 3412, San Salvador",
                 "PC-88213", "20/11/2026", "Despacho Contable Méndez", "0614-150772-102-5", "USD", [
                     Linea("Resma papel bond carta 75 g", 25, 4.85),
                     Linea("Bolígrafo azul caja 12 u", 10, 3.20),
                     Linea("Folder manila tamaño carta (100 u)", 3, 8.90),
                     Linea("Tóner compatible HP 85A", 2, 42.00),
                 ], formato="us", color=(0.35, 0.18, 0.45))
    pdf_a_imagenes(pdf_factura(f3), dpi=130)[0].save(OUT / "factura_03_papeleria.png", optimize=True)
    esperado["factura_03_papeleria.png"] = {"resultado": "procesada", "numero_factura": f3.numero, "total": f3.total,
                                             "subtotal": f3.subtotal, "total_catalogo": 0.0, "lineas_catalogo": 0}

    # 4. PDF escaneado (solo imágenes), 2 páginas, con descuento global y envío
    nombres = ["Cemento blanco 25 kg", "Bloque de concreto 15x20x40", "Arena de río m3", "Grava 3/4 m3",
               "Alambre de amarre lb", "Clavo 2 1/2\" lb", "Tubo PVC 1/2\" x 6 m", "Codo PVC 1/2\"",
               "Pegamento PVC 1/4 gal", "Malla electrosoldada 6x6", "Varilla lisa 1/4\" x 6 m",
               "Pintura anticorrosiva gris 1 gal", "Thinner 1 gal", "Rodillo 9\"", "Cinta métrica 8 m",
               "Nivel de aluminio 24\"", "Martillo de uña 16 oz", "Pala cuadrada", "Carretilla 5 pies3",
               "Guantes de cuero par", "Casco de seguridad", "Lentes de protección"]
    lineas4 = [Linea(n, random.choice([1, 2, 3, 5, 8, 10, 12]), round(random.uniform(0.8, 65), 2)) for n in nombres]
    f4 = Factura("Materiales y Construcción El Roble", "0614-221004-103-0", "Bulevar del Ejército Km 4, Soyapango",
                 "MR-004211", "21/11/2026", "Constructora Ríos y Asociados", "0614-110185-101-9", "USD", lineas4,
                 descuento_global=25.00, envio=35.00, color=(0.45, 0.25, 0.10))
    paginas = pdf_a_imagenes(pdf_factura(f4, por_pagina=14), dpi=140)
    paginas = [p.convert("L").filter(ImageFilter.GaussianBlur(0.5)).convert("RGB").rotate(0.6, fillcolor="white") for p in paginas]
    paginas[0].save(OUT / "factura_04_escaneada.pdf", save_all=True, append_images=paginas[1:], resolution=140)
    cat4 = [l for l in lineas4 if l.descripcion.lower().startswith(("cemento", "varilla", "pintura"))]
    esperado["factura_04_escaneada.pdf"] = {"resultado": "procesada", "numero_factura": f4.numero, "total": f4.total,
                                             "subtotal": f4.subtotal, "total_catalogo": round(sum(l.importe for l in cat4), 2),
                                             "lineas_catalogo": len(cat4)}

    # 5. Totales mal impresos: no cuadra (va a revisión aunque se relea)
    f5 = Factura("Taller Eléctrico Volta", "0614-090993-105-1", "Calle Arce 1120, San Salvador",
                 "TV-3381", "15/11/2026", "Condominio Las Palmas", "0614-010101-100-0", "USD", [
                     Linea("Cable THHN calibre 12 (rollo 100 m)", 2, 68.00),
                     Linea("Tomacorriente doble polarizado", 15, 3.40),
                     Linea("Interruptor sencillo", 10, 2.90),
                     Linea("Mano de obra instalación", 1, 250.00),
                 ], color=(0.55, 0.12, 0.12))
    f5.total_impreso = round(f5.total + 80.00, 2)
    (OUT / "factura_05_totales_erroneos.pdf").write_bytes(pdf_factura(f5))
    esperado["factura_05_totales_erroneos.pdf"] = {"resultado": "revision", "motivo": "montos"}

    # 6. Descuentos por línea y formato es, JPG con más ruido
    f6 = Factura("Pinturas Arcoíris", "0614-170386-108-6", "Centro Comercial Metrocentro Local 22",
                 "PA-10477", "21/11/2026", "Hotel Vista al Lago", "0614-300488-103-8", "USD", [
                     Linea("Pintura esmalte azul marino 1 galón", 8, 28.50, descuento=12.00),
                     Linea("Pintura látex blanco hueso cubeta 5 gal", 3, 112.00, descuento=20.00),
                     Linea("Sellador acrílico 1 gal", 4, 19.90),
                     Linea("Rodillo antigota 9\"", 6, 6.75),
                 ], envio=15.00, color=(0.10, 0.35, 0.55))
    foto(pdf_a_imagenes(pdf_factura(f6), dpi=150)[0], angulo=-2.5, ruido=16, blur=0.8).save(
        OUT / "factura_06_descuentos.jpg", quality=78)
    cat6 = [l for l in f6.lineas if l.descripcion.lower().startswith("pintura")]
    esperado["factura_06_descuentos.jpg"] = {"resultado": "procesada", "numero_factura": f6.numero, "total": f6.total,
                                              "subtotal": f6.subtotal, "total_catalogo": round(sum(l.importe for l in cat6), 2),
                                              "lineas_catalogo": len(cat6)}

    # 7. Foto ilegible: muy pequeña y desenfocada
    il = pdf_a_imagenes(pdf_factura(f2), dpi=40)[0].filter(ImageFilter.GaussianBlur(3.5))
    il = il.resize((il.width // 2, il.height // 2))
    foto(il, angulo=7, ruido=30, blur=2.5, escala=1).save(OUT / "foto_borrosa.jpg", quality=35)
    esperado["foto_borrosa.jpg"] = {"resultado": "revision", "motivo": "ilegible"}

    # 8. PDF protegido con contraseña
    (OUT / "documento_protegido.pdf").write_bytes(pdf_factura(f3, encrypt="clave-secreta"))
    esperado["documento_protegido.pdf"] = {"resultado": "revision", "motivo": "dañado"}

    # 9. Imagen que no es una factura
    memo = Image.new("RGB", (1100, 1400), "white")
    d = ImageDraw.Draw(memo)
    try:
        fuente = ImageFont.truetype("arial.ttf", 30)
        fuente_t = ImageFont.truetype("arialbd.ttf", 44)
    except OSError:
        fuente = fuente_t = ImageFont.load_default()
    d.text((80, 90), "ACTA DE REUNIÓN DE EQUIPO", fill="black", font=fuente_t)
    texto = ["Fecha: 18 de noviembre de 2026", "Asistentes: Ana, Luis, Carmen, Jorge", "",
             "1. Se revisó el avance del proyecto de bodega.", "2. Se acordó cambiar el proveedor de pintura.",
             "3. Próxima reunión: martes a las 10:00.", "", "Pendientes:", "- Cotizar techo de lámina",
             "- Revisar planos eléctricos", "- Enviar informe semanal a gerencia"]
    for i, t in enumerate(texto):
        d.text((80, 200 + i * 52), t, fill="black", font=fuente)
    foto(memo, angulo=-1.2, escala=0.7).save(OUT / "no_es_factura.jpg", quality=80)
    esperado["no_es_factura.jpg"] = {"resultado": "revision", "motivo": "no es factura"}

    # 10. Duplicado exacto de la factura 1 con otro nombre
    shutil.copy(OUT / "factura_01_ferreteria.pdf", OUT / "factura_01_copia.pdf")
    esperado["factura_01_copia.pdf"] = {"resultado": "revision", "motivo": "duplicado"}

    # 11. Archivo de un tipo no admitido: se ignora y se queda en la carpeta
    (OUT / "notas.txt").write_text("Recordatorio: subir las facturas de noviembre.", encoding="utf-8")
    esperado["notas.txt"] = {"resultado": "ignorado"}

    (OUT / "esperado.json").write_text(json.dumps(esperado, ensure_ascii=False, indent=2), encoding="utf-8")
    for p in sorted(OUT.iterdir()):
        print(f"{p.name:40s} {p.stat().st_size:>9,d} bytes")


if __name__ == "__main__":
    main()
