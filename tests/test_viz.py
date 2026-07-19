"""Lógica de los componentes de visualización (la parte sin Streamlit).

Solo se prueba lo que no necesita runtime: por_dimension, que alimenta
TODAS las gráficas del dashboard agrupando el detalle por el nombre de una
dimensión (capítulo, tipo, proyecto). Un error aquí descuadra cada barra.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from lib import viz  # noqa: E402


def test_agrupa_por_nombre_de_dimension():
    detalle = pd.DataFrame([
        {"capitulo_id": "C1", "valor": 100, "sentido": "gasto"},
        {"capitulo_id": "C1", "valor": 50, "sentido": "gasto"},
        {"capitulo_id": "C2", "valor": 30, "sentido": "gasto"},
    ])
    cap = pd.DataFrame([{"id": "C1", "nombre": "Estructura"},
                        {"id": "C2", "nombre": "Acabados"}])
    s = viz.por_dimension(detalle, cap, "capitulo_id")
    assert s["Estructura"] == 150
    assert s["Acabados"] == 30


def test_lo_no_clasificado_cae_al_defecto():
    """Un artículo sin capítulo debe sumarse en 'Sin clasificar', no
    perderse: si desaparece, el total de las barras no cuadra con el real."""
    detalle = pd.DataFrame([
        {"capitulo_id": "C1", "valor": 100},
        {"capitulo_id": None, "valor": 40},
    ])
    cap = pd.DataFrame([{"id": "C1", "nombre": "Estructura"}])
    s = viz.por_dimension(detalle, cap, "capitulo_id")
    assert s["Estructura"] == 100
    assert s["Sin clasificar"] == 40
    assert s.sum() == 140          # nada se pierde


def test_detalle_vacio_no_revienta():
    cap = pd.DataFrame([{"id": "C1", "nombre": "Estructura"}])
    assert viz.por_dimension(pd.DataFrame(), cap, "capitulo_id").empty
    assert viz.por_dimension(None, cap, "capitulo_id").empty


if __name__ == "__main__":
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith("test_"):
            fn()
            print("OK  ", nombre)
