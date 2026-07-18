"""Pruebas del OCR: deteccion de PDF escaneado, rasterizado y armado de
items. Sin llamadas a la API: solo la logica local, que es donde estan los
errores que si podemos controlar."""
import sys
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from worker import ocr  # noqa: E402


def _pdf_con_texto() -> bytes:
    doc = fitz.open()
    doc.new_page().insert_text(
        (72, 100), "FACTURA DE VENTA No FE-1234 " + "detalle de la compra " * 5
    )
    datos = doc.tobytes()
    doc.close()
    return datos


def _pdf_escaneado() -> bytes:
    """Una imagen dentro de un PDF: lo que produce un escaner o una foto."""
    doc = fitz.open()
    pagina = doc.new_page()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 400, 300))
    pix.set_rect(pix.irect, (255, 255, 255))
    pagina.insert_image(fitz.Rect(0, 0, 400, 300), pixmap=pix)
    datos = doc.tobytes()
    doc.close()
    return datos


def test_pdf_con_texto_no_es_escaneado():
    assert ocr.pdf_es_escaneado(_pdf_con_texto()) is False


def test_pdf_sin_texto_es_escaneado():
    assert ocr.pdf_es_escaneado(_pdf_escaneado()) is True


def test_rasteriza_paginas_a_png():
    imagenes = ocr.pdf_a_imagenes(_pdf_escaneado())
    assert len(imagenes) == 1
    assert imagenes[0].startswith(b"\x89PNG")


def test_contenido_invalido_no_lanza():
    assert ocr.pdf_a_imagenes(b"esto no es un pdf") == []
    assert ocr.texto_de_pdf(b"esto no es un pdf") == ""


def test_reconoce_extensiones_de_imagen():
    assert ocr.es_imagen("recibo.JPG")
    assert ocr.es_imagen("foto.png")
    assert not ocr.es_imagen("factura.xml")
    assert not ocr.es_imagen("sin_extension")


def test_items_de_ia_numera_sin_huecos():
    """Un articulo vacio se descarta, pero los siguientes NO deben quedar
    con hueco en el numero de linea: la reparacion casa items por linea."""
    from worker.sync import _items_desde_ia

    items = _items_desde_ia(
        {
            "items": [
                {"descripcion": "Cemento", "cantidad": 10, "total": 250000},
                {"descripcion": "   ", "total": 999},
                {"descripcion": "Arena", "cantidad": None, "total": None},
            ]
        }
    )
    assert [it["linea"] for it in items] == [1, 2]
    assert len(items) == 2


def test_items_de_ia_sin_items():
    from worker.sync import _items_desde_ia

    assert _items_desde_ia({}) == []


if __name__ == "__main__":
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith("test_"):
            fn()
            print("OK  ", nombre)
