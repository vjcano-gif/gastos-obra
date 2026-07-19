"""con_saldo_pendiente: qué facturas se deben y cuánto.

Es la base de "Cuentas por pagar" y responde las preguntas del usuario
(qué debo, a quién, cuánto). El error que destapó la importación: filtrar
por `estado` (flujo interno) en vez de `estado_pago` (si se pagó) marcaba
como deuda las 2.359 facturas importadas que la matriz da por pagadas.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from lib import db  # noqa: E402


def test_el_saldo_de_la_matriz_manda():
    """Cuando hay saldo cargado (columna de la matriz), ese es el dato."""
    fx = pd.DataFrame([
        {"estado": "asignada", "estado_pago": "pagada", "saldo": 0, "monto_efectivo": 100},
        {"estado": "asignada", "estado_pago": "pendiente", "saldo": 40, "monto_efectivo": 100},
    ])
    pend = db.con_saldo_pendiente(fx)
    assert len(pend) == 1            # la de saldo 0 no se debe
    assert pend["saldo_pend"].iloc[0] == 40


def test_pagada_no_es_deuda_aunque_estado_sea_asignada():
    """El bug que destapó la importación: estado='asignada' pero de verdad
    pagada (estado_pago='pagada'). No debe contar como cuenta por pagar."""
    fx = pd.DataFrame([
        {"estado": "asignada", "estado_pago": "pagada", "monto_efectivo": 500},
    ])
    assert db.con_saldo_pendiente(fx).empty


def test_sin_saldo_cae_al_estado_pago():
    """Sin la columna saldo, se usa estado_pago + total a pagar."""
    fx = pd.DataFrame([
        {"estado": "asignada", "estado_pago": "pendiente", "monto_efectivo": 200, "rete_fuente": 5},
        {"estado": "asignada", "estado_pago": "pagada", "monto_efectivo": 300},
    ])
    pend = db.con_saldo_pendiente(fx)
    assert len(pend) == 1
    assert pend["saldo_pend"].iloc[0] == 195      # 200 - 5 de retención


def test_saldo_nulo_cae_al_estado_pago():
    """Facturas de Gmail nunca cruzadas: saldo nulo. Se decide por
    estado_pago, no se asume deuda sin dato."""
    fx = pd.DataFrame([
        {"estado": "asignada", "estado_pago": "pagada", "saldo": None, "monto_efectivo": 100},
        {"estado": "asignada", "estado_pago": "pendiente", "saldo": None, "monto_efectivo": 100},
    ])
    pend = db.con_saldo_pendiente(fx)
    assert len(pend) == 1
    assert pend["saldo_pend"].iloc[0] == 100


def test_anulada_nunca_es_deuda():
    fx = pd.DataFrame([
        {"estado": "anulada", "estado_pago": "pendiente", "saldo": 999, "monto_efectivo": 999},
    ])
    assert db.con_saldo_pendiente(fx).empty


def test_vacio_no_revienta():
    assert db.con_saldo_pendiente(pd.DataFrame()).empty
    assert db.con_saldo_pendiente(None).empty


if __name__ == "__main__":
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith("test_"):
            fn()
            print("OK  ", nombre)
