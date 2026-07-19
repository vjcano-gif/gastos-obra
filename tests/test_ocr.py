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


# --- red de seguridad contra el error de miles del OCR -----------------
# Caso real detectado en pruebas: el modelo leyo "2.903.600" (punto de
# miles colombiano) como 2903.6, un total MIL VECES menor. El prompt ya
# lo advierte, pero esto es la defensa que no depende del modelo.


def test_corrige_total_mil_veces_menor():
    from worker.clasificador import _corregir_miles

    datos = _corregir_miles(
        {
            "total": 2903.6,  # deberia ser 2903600
            "iva": 463.6,
            "items": [
                {"descripcion": "Cemento", "total": 560000},
                {"descripcion": "Varilla", "total": 1120000},
                {"descripcion": "Arena", "total": 760000},
            ],
        }
    )
    assert datos["total"] == 2903600
    assert datos["iva"] == 463600
    assert datos["_correccion_miles"] is True


def test_no_toca_un_total_correcto():
    from worker.clasificador import _corregir_miles

    datos = _corregir_miles(
        {
            "total": 2903600,
            "iva": 463600,
            "items": [{"descripcion": "Cemento", "total": 2440000}],
        }
    )
    assert datos["total"] == 2903600
    assert "_correccion_miles" not in datos


def test_no_corrige_si_no_hay_evidencia():
    """Sin articulos no hay con que contrastar: se deja como esta y lo
    resuelve la revision humana, que es mejor que adivinar."""
    from worker.clasificador import _corregir_miles

    datos = _corregir_miles({"total": 2903.6, "iva": 463.6, "items": []})
    assert datos["total"] == 2903.6
    assert "_correccion_miles" not in datos


def test_no_corrige_descuadre_pequeno():
    """Un descuadre normal (propina, flete, redondeo) NO debe disparar la
    correccion: solo el desfase de ~1000x."""
    from worker.clasificador import _corregir_miles

    datos = _corregir_miles(
        {"total": 100000, "items": [{"descripcion": "algo", "total": 95000}]}
    )
    assert datos["total"] == 100000
    assert "_correccion_miles" not in datos


if __name__ == "__main__":
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith("test_"):
            fn()
            print("OK  ", nombre)
