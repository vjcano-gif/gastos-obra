"""Cash flow del proyecto, contrastado contra su archivo real.

Los valores esperados son los de la hoja "Cash flow Casa Chipre" del
archivo Cash Flow Casa Vieja 61, cortes 1 y 2. Si el calculo deja de dar
esas cifras, el informe dejo de ser el de ellos — y esa es exactamente la
falla que nadie notaria a tiempo mirando la pantalla.

    Corte 1   subtotal  21.994.759,9   egresos  44.492.880,9   caja  8.005.240,1
    Corte 2   subtotal  92.092.300,9   egresos 176.216.986,9   caja 10.912.939,2
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from lib import db  # noqa: E402

CORTES = pd.DataFrame(
    [
        {"id": "K1", "proyecto_id": "P", "numero": 1, "nombre": "Corte 1"},
        {"id": "K2", "proyecto_id": "P", "numero": 2, "nombre": "Corte 2"},
    ]
)


def _escenario():
    """Reconstruye los cortes 1 y 2 de Casa Vieja 61 con datos de la app.

    Los gastos se parten en dos filas (Espacios / pago directo del
    cliente) porque esa distincion es la que cambia la caja.
    """
    facturas = pd.DataFrame(
        [
            # --- corte 1
            {"corte_id": "K1", "pagador": "empresa", "total": 1684701.7, "exento_aiu": False},
            {"corte_id": "K1", "pagador": "cliente", "total": 530000.0, "exento_aiu": False},
            # --- corte 2
            {"corte_id": "K2", "pagador": "empresa", "total": 70363899.0, "exento_aiu": False},
            {"corte_id": "K2", "pagador": "cliente", "total": 84124686.0, "exento_aiu": False},
        ]
    )
    anticipos = pd.DataFrame(
        [
            {"corte_id": "K1", "valor": 30000000.0, "modo_pago": "efectivo"},
            {"corte_id": "K2", "valor": 70000000.0, "modo_pago": "efectivo"},
            {"corte_id": "K2", "valor": 25000000.0, "modo_pago": "bancos"},
        ]
    )
    movimientos = pd.DataFrame(
        [
            {"corte_id": "K1", "concepto": "otros_gastos", "valor": 20000000.0},
            {"corte_id": "K1", "concepto": "pago_exento", "valor": 21968121.0},
            {"corte_id": "K2", "concepto": "gmf", "valor": 100000.0},
        ]
    )
    return db.cash_flow(facturas, anticipos, movimientos, CORTES, 0.14)


def test_reproduce_el_subtotal_de_los_dos_cortes():
    t = _escenario()
    assert round(t.loc["subtotal", "Corte 1"], 1) == 21994759.9
    assert round(t.loc["subtotal", "Corte 2"], 1) == 92092300.9


def test_reproduce_el_total_de_egresos():
    t = _escenario()
    assert round(t.loc["total_egresos", "Corte 1"], 1) == 44492880.9
    assert round(t.loc["total_egresos", "Corte 2"], 1) == 176216986.9


def test_reproduce_el_saldo_en_caja():
    t = _escenario()
    assert round(t.loc["caja_final", "Corte 1"], 1) == 8005240.1
    assert round(t.loc["caja_final", "Corte 2"], 1) == 10912939.2


def test_el_aiu_se_calcula_aparte_para_gastos_y_pagos_directos():
    t = _escenario()
    assert round(t.loc["aiu_gastos", "Corte 1"], 1) == 235858.2
    assert round(t.loc["aiu_pagos_directos", "Corte 1"], 1) == 74200.0


def test_la_caja_se_encadena_entre_cortes():
    """El saldo final de un corte tiene que ser el inicial del siguiente:
    si no, cada corte arrancaria de cero y la caja no significaria nada."""
    t = _escenario()
    assert t.loc["caja_inicial", "Corte 1"] == 0
    assert t.loc["caja_inicial", "Corte 2"] == t.loc["caja_final", "Corte 1"]


def test_el_pago_directo_no_sale_de_la_caja_pero_si_suma_al_costo():
    """Lo que el cliente le paga directo al proveedor es costo de la obra
    y genera comision, pero no toca la caja de Espacios."""
    t = _escenario()
    assert t.loc["pagos_directos", "Corte 1"] == 530000.0
    assert t.loc["aiu_pagos_directos", "Corte 1"] == 74200.0
    # No esta dentro del subtotal que descuenta la caja:
    assert t.loc["subtotal", "Corte 1"] < t.loc["total_egresos", "Corte 1"]


def test_anticipos_partidos_por_bancos_y_efectivo():
    t = _escenario()
    assert t.loc["anticipos_bancos", "Corte 2"] == 25000000.0
    assert t.loc["anticipos_efectivo", "Corte 2"] == 70000000.0
    assert t.loc["anticipos", "Corte 2"] == 95000000.0


def test_una_factura_exenta_no_genera_comision():
    facturas = pd.DataFrame(
        [
            {"corte_id": "K1", "pagador": "empresa", "total": 1000000.0, "exento_aiu": True},
            {"corte_id": "K1", "pagador": "empresa", "total": 1000000.0, "exento_aiu": False},
        ]
    )
    t = db.cash_flow(facturas, pd.DataFrame(), pd.DataFrame(), CORTES, 0.10)
    assert t.loc["gastos", "Corte 1"] == 2000000.0
    assert t.loc["aiu_gastos", "Corte 1"] == 100000.0     # solo sobre la no exenta


def test_lo_que_no_tiene_corte_no_se_pierde():
    """848 movimientos de su matriz no tienen corte. Si se descartaran, el
    costo del proyecto quedaria incompleto sin que nadie lo note."""
    facturas = pd.DataFrame(
        [{"corte_id": None, "pagador": "empresa", "total": 500000.0, "exento_aiu": False}]
    )
    t = db.cash_flow(facturas, pd.DataFrame(), pd.DataFrame(), CORTES, 0.0)
    assert "Sin corte" in t.columns
    assert t.loc["gastos", "Sin corte"] == 500000.0


def test_proyecto_sin_movimientos_no_revienta():
    t = db.cash_flow(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), CORTES, 0.14)
    assert t.loc["caja_final", "Corte 1"] == 0
    assert t.loc["subtotal", "Corte 2"] == 0


def test_sin_cortes_definidos_sigue_mostrando_algo():
    facturas = pd.DataFrame(
        [{"corte_id": None, "pagador": "empresa", "total": 100.0, "exento_aiu": False}]
    )
    t = db.cash_flow(facturas, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), 0.0)
    assert t.loc["gastos", "Sin corte"] == 100.0


if __name__ == "__main__":
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith("test_"):
            fn()
            print("OK  ", nombre)


# --- exención de AIU a nivel de proyecto (migración 019) ------------------
def test_proyecto_exento_no_genera_comision():
    """Un proyecto exento de AIU no genera comisión aunque tenga %AIU: la
    exención del proyecto manda sobre la tarifa."""
    facturas = pd.DataFrame([
        {"corte_id": "K1", "pagador": "empresa", "total": 1000000.0, "exento_aiu": False},
    ])
    t = db.cash_flow(facturas, pd.DataFrame(), pd.DataFrame(), CORTES, 0.14,
                     proyecto_exento=True)
    assert t.loc["aiu_gastos", "Corte 1"] == 0
    # y sin la exención del proyecto sí cobra
    t2 = db.cash_flow(facturas, pd.DataFrame(), pd.DataFrame(), CORTES, 0.14,
                      proyecto_exento=False)
    assert t2.loc["aiu_gastos", "Corte 1"] == 140000.0
