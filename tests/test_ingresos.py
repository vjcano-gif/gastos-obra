"""Cumplimiento del cronograma y superávit/déficit por corte.

Alimentan el módulo de Ingresos: cuánto abonó el cliente contra lo pactado
y si cada corte cerró con caja o en rojo.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from lib import db  # noqa: E402


def test_cumplimiento_compara_programado_con_recibido():
    hitos = pd.DataFrame([
        {"tipo": "abono", "monto": 100_000_000},
        {"tipo": "abono", "monto": 50_000_000},
        {"tipo": "entregable", "monto": None},      # no cuenta
    ])
    anticipos = pd.DataFrame([{"valor": 90_000_000}, {"valor": 30_000_000}])
    r = db.cumplimiento_cronograma(hitos, anticipos)
    assert r["programado"] == 150_000_000
    assert r["recibido"] == 120_000_000
    assert r["pendiente"] == 30_000_000
    assert round(r["cumplimiento_pct"], 1) == 80.0


def test_sin_cronograma_no_hay_porcentaje():
    """Sin abonos programados no se puede medir cumplimiento: None, no
    dividir por cero ni inventar 100%."""
    r = db.cumplimiento_cronograma(pd.DataFrame(), pd.DataFrame([{"valor": 100}]))
    assert r["cumplimiento_pct"] is None
    assert r["recibido"] == 100


def test_cumplimiento_vacio_no_revienta():
    r = db.cumplimiento_cronograma(None, None)
    assert r["programado"] == 0 and r["recibido"] == 0
    assert r["cumplimiento_pct"] is None


def test_superavit_y_deficit_por_corte():
    """Superávit = anticipos - subtotal del corte; caja acumulada encadena."""
    cf = pd.DataFrame({
        "Corte 1": {"anticipos": 100.0, "subtotal": 60.0, "caja_final": 40.0},
        "Corte 2": {"anticipos": 20.0, "subtotal": 50.0, "caja_final": 10.0},
    })
    sd = db.superavit_por_corte(cf)
    assert list(sd["corte"]) == ["Corte 1", "Corte 2"]
    assert list(sd["resultado"]) == [40.0, -30.0]      # C1 superávit, C2 déficit
    assert list(sd["caja_acumulada"]) == [40.0, 10.0]


def test_superavit_sin_datos_no_revienta():
    assert db.superavit_por_corte(pd.DataFrame()).empty
    assert db.superavit_por_corte(None).empty


if __name__ == "__main__":
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith("test_"):
            fn()
            print("OK  ", nombre)
