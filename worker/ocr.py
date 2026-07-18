"""OCR de documentos sin capa de texto: PDFs escaneados y fotos.

Un PDF "digital" (el que emite la DIAN o cualquier software) lleva el texto
embebido y se lee directo. Un PDF escaneado es una IMAGEN metida en un PDF:
no tiene texto que extraer, y hasta ahora esos documentos se guardaban sin
que nadie leyera su contenido.

Aquí no se usa Tesseract: requiere un binario del sistema y con facturas
fotografiadas (torcidas, con sombras, con sellos encima) su tasa de acierto
es pobre. Se rasteriza la página con PyMuPDF —ya es dependencia— y se manda
a un modelo de visión, que además entiende la ESTRUCTURA de la factura y no
solo los caracteres sueltos.

Nunca lanza excepción: si algo falla, el documento sigue su curso y queda
en revisión humana sin datos sugeridos.
"""
from __future__ import annotations

import fitz  # PyMuPDF

EXTENSIONES_IMAGEN = ("jpg", "jpeg", "png", "webp", "heic", "tif", "tiff")

# Umbral de caracteres para considerar que un PDF SÍ trae capa de texto.
# Un escaneo suele devolver 0; algunos traen basura de una marca de agua o
# del pie de página, por eso no se compara contra cero puro.
MIN_CARACTERES_TEXTO = 80


def texto_de_pdf(contenido: bytes) -> str:
    try:
        with fitz.open(stream=contenido, filetype="pdf") as doc:
            return "\n".join(p.get_text() for p in doc)
    except Exception:
        return ""


def pdf_es_escaneado(contenido: bytes) -> bool:
    """True si el PDF no tiene capa de texto aprovechable."""
    return len(texto_de_pdf(contenido).strip()) < MIN_CARACTERES_TEXTO


def pdf_a_imagenes(contenido: bytes, max_paginas: int = 3, dpi: int = 180) -> list[bytes]:
    """Rasteriza las primeras páginas a PNG. Tres páginas cubren el 99% de
    las facturas; más solo encarece la llamada al modelo."""
    imagenes: list[bytes] = []
    try:
        with fitz.open(stream=contenido, filetype="pdf") as doc:
            for pagina in doc[:max_paginas]:
                imagenes.append(pagina.get_pixmap(dpi=dpi).tobytes("png"))
    except Exception:
        return []
    return imagenes


def es_imagen(nombre_archivo: str) -> bool:
    ext = nombre_archivo.lower().rsplit(".", 1)[-1] if "." in nombre_archivo else ""
    return ext in EXTENSIONES_IMAGEN


def comprimir_imagen(contenido: bytes, lado_max: int = 1600) -> bytes:
    """Reduce fotos de cámara (4000px+) antes de mandarlas al modelo: baja
    el costo y la latencia sin perder legibilidad del texto."""
    try:
        with fitz.open(stream=contenido) as doc:
            pix = doc[0].get_pixmap()
            if max(pix.width, pix.height) <= lado_max:
                return contenido
            escala = lado_max / max(pix.width, pix.height)
            return doc[0].get_pixmap(matrix=fitz.Matrix(escala, escala)).tobytes("png")
    except Exception:
        return contenido
