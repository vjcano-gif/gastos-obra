"""Previsualizacion de documentos: el PDF se convierte a imagen en el
servidor en vez de incrustarlo con un <iframe>.

El iframe dependia del visor de PDF del navegador dentro del sandbox de
Streamlit Cloud y fallaba mostrando un documento roto, con el archivo
intacto. Aqui se prueba que el rasterizado funciona y, sobre todo, que
cuando algo falla NO se cae la pagina: se devuelve lista vacia y la
Revision sigue usable con el enlace de descarga.
"""
import sys
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from lib import db  # noqa: E402


def _pdf(paginas: int = 1) -> bytes:
    doc = fitz.open()
    for n in range(paginas):
        doc.new_page().insert_text((72, 100), f"FACTURA FVE484 - pagina {n + 1}")
    datos = doc.tobytes()
    doc.close()
    return datos


class _Sb:
    """Cliente falso: devuelve el contenido dado, o lanza si es None."""

    def __init__(self, contenido):
        self._contenido = contenido

    def _download(self, path):
        if self._contenido is None:
            raise RuntimeError("storage caido")
        return self._contenido

    @property
    def storage(self):
        sb = self

        class _Bucket:
            def download(self, path):
                return sb._download(path)

        class _Storage:
            def from_(self, nombre):
                return _Bucket()

        return _Storage()


def test_pdf_se_convierte_a_png():
    imgs = db.paginas_pdf(_Sb(_pdf()), "ruta/factura.pdf")
    assert len(imgs) == 1
    assert imgs[0].startswith(b"\x89PNG")


def test_respeta_el_tope_de_paginas():
    """Una factura larga no debe cargar la pantalla con 40 imagenes."""
    imgs = db.paginas_pdf(_Sb(_pdf(8)), "ruta/larga.pdf", max_paginas=3)
    assert len(imgs) == 3


def test_storage_caido_no_lanza():
    assert db.paginas_pdf(_Sb(None), "ruta/inexistente.pdf") == []


def test_contenido_que_no_es_pdf_no_lanza():
    """Un ZIP renombrado, un XML mal etiquetado: se degrada, no se cae."""
    assert db.paginas_pdf(_Sb(b"PK\x03\x04 esto es un zip"), "ruta/malo.pdf") == []


if __name__ == "__main__":
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith("test_"):
            fn()
            print("OK  ", nombre)
