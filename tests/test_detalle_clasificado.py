"""detalle_clasificado: una fila por articulo (mas una de respaldo por
factura sin articulos). Es la base de TODOS los reportes por capitulo,
tipo y proyecto, asi que un error aqui descuadra la plata en silencio.

Estas pruebas fijan el comportamiento (nota credito resta, respaldo
factura->articulo, factura sin items) para poder vectorizar la funcion
sin cambiar ni un peso del resultado.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from lib import db  # noqa: E402


def _fx(filas):
    return pd.DataFrame(filas)


def test_una_fila_por_articulo():
    fx = _fx([{"id": "F1", "tipo_documento": "factura", "numero": "FE1",
               "proyecto_id": "P", "capitulo_id": "CF", "total": 300}])
    items = pd.DataFrame([
        {"id": "I1", "factura_id": "F1", "descripcion": "Cemento", "total": 100,
         "capitulo_id": "C1"},
        {"id": "I2", "factura_id": "F1", "descripcion": "Arena", "total": 200,
         "capitulo_id": "C2"},
    ])
    d = db.detalle_clasificado(fx, items)
    assert len(d) == 2
    assert set(d["capitulo_id"]) == {"C1", "C2"}
    assert d["valor"].sum() == 300


def test_nota_credito_resta_a_nivel_de_articulo():
    fx = _fx([{"id": "F1", "tipo_documento": "nota_credito", "numero": "NC1",
               "proyecto_id": "P"}])
    items = pd.DataFrame([{"id": "I1", "factura_id": "F1", "total": 50, "capitulo_id": "C1"}])
    d = db.detalle_clasificado(fx, items)
    assert d["valor"].iloc[0] == -50


def test_articulo_sin_clasificar_hereda_la_de_la_factura():
    """Migracion 007: la clasificacion de la factura es el respaldo del
    articulo. Sin esto, una factura bien clasificada aparecia en 'Sin
    capitulo' solo porque el detalle venia en blanco."""
    fx = _fx([{"id": "F1", "tipo_documento": "factura", "proyecto_id": "P",
               "capitulo_id": "CF", "actividad_id": "AF"}])
    items = pd.DataFrame([{"id": "I1", "factura_id": "F1", "total": 100,
                           "capitulo_id": None, "actividad_id": None}])
    d = db.detalle_clasificado(fx, items).iloc[0]
    assert d["capitulo_id"] == "CF"
    assert d["actividad_id"] == "AF"


def test_descripcion_del_articulo_no_hereda_la_de_la_factura():
    """Solo la CLASIFICACION (capitulo/actividad) cae a la factura si
    el articulo la trae vacia. La descripcion del articulo es del articulo:
    si viene vacia, vacia — no se rellena con el consolidado de la factura,
    que diria algo distinto de lo que es esa linea."""
    fx = _fx([{"id": "F1", "tipo_documento": "factura", "descripcion": "CONSOLIDADO FACTURA",
               "capitulo_id": "CF", "total": 100}])
    items = pd.DataFrame([{"id": "I1", "factura_id": "F1", "descripcion": None,
                           "total": 100, "capitulo_id": "C1"}])
    d = db.detalle_clasificado(fx, items).iloc[0]
    assert d["descripcion"] != "CONSOLIDADO FACTURA"
    assert d["capitulo_id"] == "C1"


def test_factura_sin_items_da_una_fila_de_respaldo():
    fx = _fx([{"id": "F1", "tipo_documento": "factura", "numero": "FE1",
               "proyecto_id": "P", "capitulo_id": "CF", "total": 500,
               "monto_efectivo": 500}])
    d = db.detalle_clasificado(fx, pd.DataFrame())
    assert len(d) == 1
    assert d["item_id"].iloc[0] is None
    assert d["valor"].iloc[0] == 500
    assert d["capitulo_id"].iloc[0] == "CF"


def test_factura_sin_items_usa_monto_efectivo():
    """monto_efectivo ya trae el signo de las notas credito (lo calcula
    facturas()); la fila de respaldo lo respeta en vez de recalcular."""
    fx = _fx([{"id": "F1", "tipo_documento": "nota_credito", "proyecto_id": "P",
               "total": 80, "monto_efectivo": -80}])
    d = db.detalle_clasificado(fx, pd.DataFrame())
    assert d["valor"].iloc[0] == -80


def test_mezcla_facturas_con_y_sin_items():
    fx = _fx([
        {"id": "F1", "tipo_documento": "factura", "proyecto_id": "P",
         "capitulo_id": "CF", "total": 100, "monto_efectivo": 100},
        {"id": "F2", "tipo_documento": "factura", "proyecto_id": "P",
         "capitulo_id": "CG", "total": 200, "monto_efectivo": 200},
    ])
    items = pd.DataFrame([{"id": "I1", "factura_id": "F1", "total": 100, "capitulo_id": "C1"}])
    d = db.detalle_clasificado(fx, items)
    # F1 aporta 1 fila (por su articulo), F2 aporta 1 fila de respaldo
    assert len(d) == 2
    assert set(d["factura_id"]) == {"F1", "F2"}
    porf = d.set_index("factura_id")
    assert porf.loc["F1", "capitulo_id"] == "C1"     # del articulo
    assert porf.loc["F2", "capitulo_id"] == "CG"     # de la factura (respaldo)


def test_item_huerfano_se_ignora():
    """Un item cuya factura no esta en fx no debe aparecer."""
    fx = _fx([{"id": "F1", "tipo_documento": "factura", "total": 100}])
    items = pd.DataFrame([
        {"id": "I1", "factura_id": "F1", "total": 100, "capitulo_id": "C1"},
        {"id": "I9", "factura_id": "FANTASMA", "total": 999, "capitulo_id": "CX"},
    ])
    d = db.detalle_clasificado(fx, items)
    assert len(d) == 1
    assert 999 not in d["valor"].values


def test_vacio_no_revienta():
    assert db.detalle_clasificado(pd.DataFrame(), pd.DataFrame()).empty


if __name__ == "__main__":
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith("test_"):
            fn()
            print("OK  ", nombre)
