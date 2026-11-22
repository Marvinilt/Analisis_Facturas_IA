"""Convierte el archivo descargado en páginas de imagen (y texto si el PDF lo trae).

No se usa para descartar archivos al descargar: si el documento no se puede abrir,
se informa como ErrorDocumento dentro del paso de extracción.
"""
from __future__ import annotations

import io

import pypdfium2 as pdfium
from PIL import Image, ImageOps, UnidentifiedImageError

from .base import Documento, ErrorDocumento

Image.MAX_IMAGE_PIXELS = 80_000_000


def preparar(nombre: str, mime: str, datos: bytes, max_paginas: int = 5, dpi: int = 150,
             lado_maximo: int = 1800) -> Documento:
    doc = Documento(nombre=nombre, mime=mime, datos=datos)
    if mime == "application/pdf":
        try:
            pdf = pdfium.PdfDocument(datos)
        except pdfium.PdfiumError as e:
            texto = str(e).lower()
            if "password" in texto:
                raise ErrorDocumento("El PDF está protegido con contraseña y no se puede leer.", reintentable=False) from e
            raise ErrorDocumento(f"El PDF está dañado o no se puede abrir ({e}).", reintentable=False) from e
        doc.total_paginas = len(pdf)
        if doc.total_paginas == 0:
            raise ErrorDocumento("El PDF no tiene páginas.", reintentable=False)
        textos = []
        for i in range(min(doc.total_paginas, max_paginas)):
            pagina = pdf[i]
            try:
                textos.append(pagina.get_textpage().get_text_bounded().strip())
            except pdfium.PdfiumError:
                textos.append("")
            img = pagina.render(scale=dpi / 72).to_pil().convert("RGB")
            img.thumbnail((lado_maximo, lado_maximo))
            doc.paginas.append(img)
        doc.texto_pdf = "\n\n".join(f"--- Página {i + 1} ---\n{t}" for i, t in enumerate(textos) if t)
        pdf.close()
    else:
        try:
            img = Image.open(io.BytesIO(datos))
            img.load()
        except (UnidentifiedImageError, OSError) as e:
            raise ErrorDocumento("La imagen está dañada o en un formato que no se puede leer.", reintentable=False) from e
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((lado_maximo, lado_maximo))
        doc.paginas = [img]
        doc.total_paginas = 1
    return doc


def a_bytes(img: Image.Image, lado_maximo: int | None = None, formato: str = "JPEG", calidad: int = 88) -> bytes:
    if lado_maximo and max(img.size) > lado_maximo:
        img = img.copy()
        img.thumbnail((lado_maximo, lado_maximo))
    b = io.BytesIO()
    img.save(b, formato, quality=calidad)
    return b.getvalue()
