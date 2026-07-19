"""Comparacion del plan semanal contra lo ejecutado."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from lib import db  # noqa: E402

PLAN = pd.DataFrame(
    [
        {"presupuesto_id": "L1", "anio": 2026, "semana": 3, "valor": 50597280.0},
        {"presupuesto_id": "L2", "anio": 2026, "semana": 3, "valor": 5676300.0},
        {"presupuesto_id": "L1", "anio": 2026, "semana": 4, "valor": 6336000.0},
    ]
)


def test_suma_el_plan_de_varias_lineas_en_la_misma_semana():
    t = db.planeado_vs_real(PLAN, pd.DataFrame())
    s3 = t[t["semana"] == 3].iloc[0]
    assert s3["planeado"] == 50597280.0 + 5676300.0


def test_agrupa_el_gasto_real_por_semana_iso():
    real = pd.DataFrame(
        [
            {"fecha_emision": "2026-01-13", "valor": 1000000.0},   # semana 3
            {"fecha_emision": "2026-01-15", "valor": 500000.0},    # semana 3
            {"fecha_emision": "2026-01-20", "valor": 250000.0},    # semana 4
        ]
    )
    t = db.planeado_vs_real(pd.DataFrame(), real)
    assert t[t["semana"] == 3]["real"].iloc[0] == 1500000.0
    assert t[t["semana"] == 4]["real"].iloc[0] == 250000.0


def test_desfase_y_cumplimiento():
    real = pd.DataFrame([{"fecha_emision": "2026-01-19", "valor": 3168000.0}])  # semana 4
    t = db.planeado_vs_real(PLAN, real)
    s4 = t[t["semana"] == 4].iloc[0]
    assert s4["planeado"] == 6336000.0
    assert s4["desfase"] == 3168000.0 - 6336000.0
    assert s4["cumplimiento_%"] == 50.0


def test_semana_sin_plan_no_reporta_cumplimiento():
    """Dividir por cero daria infinito, y una semana sin presupuesto no es
    un incumplimiento: es una semana sin plan.

    Se comprueba MEZCLADO con semanas que si tienen plan, porque es el
    caso real: con una sola fila pandas deja la columna como objeto y el
    vacio se ve como None, pero al mezclar con numeros pasa a float y se
    vuelve NaN. `pd.isna` cubre las dos formas.
    """
    real = pd.DataFrame(
        [
            {"fecha_emision": "2026-01-19", "valor": 6336000.0},   # semana 4: con plan
            {"fecha_emision": "2026-03-02", "valor": 900000.0},    # semana 10: sin plan
        ]
    )
    t = db.planeado_vs_real(PLAN, real)
    sin_plan = t[t["semana"] == 10].iloc[0]
    assert sin_plan["planeado"] == 0
    assert pd.isna(sin_plan["cumplimiento_%"])
    # y la que si tenia plan sigue reportando su cumplimiento
    assert t[t["semana"] == 4].iloc[0]["cumplimiento_%"] == 100.0


def test_acumulados_crecen_en_orden_cronologico():
    real = pd.DataFrame(
        [
            {"fecha_emision": "2026-01-20", "valor": 100.0},
            {"fecha_emision": "2026-01-13", "valor": 200.0},
        ]
    )
    t = db.planeado_vs_real(PLAN, real)
    assert list(t["periodo"]) == sorted(t["periodo"])
    assert t["real_acum"].iloc[-1] == 300.0
    assert t["planeado_acum"].iloc[-1] == t["planeado"].sum()


def test_fechas_invalidas_se_ignoran_sin_romper():
    """Las facturas importadas del Excel pueden venir sin fecha."""
    real = pd.DataFrame(
        [
            {"fecha_emision": None, "valor": 999.0},
            {"fecha_emision": "no es una fecha", "valor": 999.0},
            {"fecha_emision": "2026-01-13", "valor": 100.0},
        ]
    )
    t = db.planeado_vs_real(pd.DataFrame(), real)
    assert len(t) == 1
    assert t["real"].iloc[0] == 100.0


def test_sin_datos_devuelve_vacio():
    assert db.planeado_vs_real(pd.DataFrame(), pd.DataFrame()).empty
    assert db.planeado_vs_real(None, None).empty


def test_semana_iso():
    assert db.semana_iso("2026-01-13") == (2026, 3)
    assert db.semana_iso(None) == (None, None)
    assert db.semana_iso("cualquier cosa") == (None, None)


if __name__ == "__main__":
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith("test_"):
            fn()
            print("OK  ", nombre)
