"""Proyección de compromisos: vencimientos vs ingresos previstos, por mes.

Alimenta el panel de Compromisos futuros. Si el bucket de un mes o el
acumulado dejaran de cuadrar, el panel diría que hay caja donde no la hay
(o al revés), que es justo la decisión que debe apoyar.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from lib import db  # noqa: E402

HOY = pd.Timestamp("2026-07-20")


def test_agrupa_por_mes_y_acumula_la_caja():
    egresos = pd.DataFrame({"fecha": ["2026-07-10", "2026-08-15", "2026-09-01"],
                            "valor": [100, 200, 50]})
    ingresos = pd.DataFrame({"fecha": ["2026-07-05", "2026-08-20"], "valor": [300, 100]})
    p = db.proyeccion_compromisos(egresos, ingresos, meses=3, hoy=HOY)
    assert list(p["periodo"]) == ["2026-07", "2026-08", "2026-09"]
    jul = p[p["periodo"] == "2026-07"].iloc[0]
    assert jul["neto"] == 200 and jul["acumulado"] == 200        # 300 - 100
    ago = p[p["periodo"] == "2026-08"].iloc[0]
    assert ago["neto"] == -100 and ago["acumulado"] == 100       # 200 + (100 - 200)
    sep = p[p["periodo"] == "2026-09"].iloc[0]
    assert sep["neto"] == -50 and sep["acumulado"] == 50


def test_lo_vencido_va_a_un_bucket_propio_al_inicio():
    egresos = pd.DataFrame({"fecha": ["2026-05-01"], "valor": [500]})   # antes del mes actual
    p = db.proyeccion_compromisos(egresos, pd.DataFrame(columns=["fecha", "valor"]),
                                  meses=2, hoy=HOY)
    assert p.iloc[0]["periodo"] == "Vencido / atrasado"
    assert p.iloc[0]["egresos_comprometidos"] == 500
    assert p.iloc[0]["acumulado"] == -500


def test_lo_posterior_al_horizonte_se_separa():
    egresos = pd.DataFrame({"fecha": ["2027-01-01"], "valor": [900]})
    p = db.proyeccion_compromisos(egresos, pd.DataFrame(columns=["fecha", "valor"]),
                                  meses=3, hoy=HOY)
    assert "Posterior" in list(p["periodo"])
    assert p[p["periodo"] == "Posterior"].iloc[0]["egresos_comprometidos"] == 900


def test_los_meses_del_horizonte_se_muestran_aunque_esten_en_cero():
    p = db.proyeccion_compromisos(pd.DataFrame(columns=["fecha", "valor"]),
                                  pd.DataFrame(columns=["fecha", "valor"]),
                                  meses=3, hoy=HOY)
    assert list(p["periodo"]) == ["2026-07", "2026-08", "2026-09"]
    assert (p["neto"] == 0).all()


def test_lo_sin_fecha_no_se_pierde():
    egresos = pd.DataFrame({"fecha": [None], "valor": [70]})
    p = db.proyeccion_compromisos(egresos, pd.DataFrame(columns=["fecha", "valor"]),
                                  meses=1, hoy=HOY)
    assert "Sin fecha" in list(p["periodo"])
    assert p[p["periodo"] == "Sin fecha"].iloc[0]["egresos_comprometidos"] == 70


if __name__ == "__main__":
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith("test_"):
            fn()
            print("OK  ", nombre)
