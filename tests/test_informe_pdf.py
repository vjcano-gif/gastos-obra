"""Informe PDF del proyecto (estructura del Excel Casa Vieja 61).

Verifica que el PDF se genere, sea válido y no reviente con datos incompletos.
El formato de cifras (millones estilo colombiano, negativos en pesos) se fija
aquí porque es lo que el cliente lee en el informe.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from lib import db, informe_pdf  # noqa: E402


def _cash_flow():
    facturas = pd.DataFrame([
        {"corte_id": "K1", "pagador": "empresa", "total": 1_000_000, "exento_aiu": False},
        {"corte_id": "K2", "pagador": "cliente", "total": 2_000_000, "exento_aiu": False},
    ])
    anticipos = pd.DataFrame([{"corte_id": "K1", "valor": 3_000_000, "modo_pago": "bancos"}])
    cortes = pd.DataFrame([
        {"id": "K1", "proyecto_id": "P", "numero": 1, "nombre": "Corte 1"},
        {"id": "K2", "proyecto_id": "P", "numero": 2, "nombre": "Corte 2"},
    ])
    return db.cash_flow(facturas, anticipos, pd.DataFrame(), cortes, 0.14)


def test_genera_un_pdf_valido():
    cf = _cash_flow()
    costo = pd.DataFrame([
        {"capitulo": "Estructura", "corte": "Corte 1", "total": 1_000_000},
        {"capitulo": "Acabados", "corte": "Corte 2", "total": 2_000_000},
    ])
    pdf = informe_pdf.generar_informe(
        {"nombre": "Casa Vieja 61", "cliente_nombre": "Bertran"}, cf, costo, periodo="2025"
    )
    assert isinstance(pdf, (bytes, bytearray))
    assert pdf[:4] == b"%PDF"          # es un PDF de verdad
    assert len(pdf) > 2000             # tiene contenido, no una página en blanco


def test_sin_costos_clasificados_no_revienta():
    pdf = informe_pdf.generar_informe({"nombre": "X"}, _cash_flow(), pd.DataFrame())
    assert pdf[:4] == b"%PDF"


def test_sin_nada_no_revienta():
    pdf = informe_pdf.generar_informe({"nombre": "Vacío"}, pd.DataFrame(), pd.DataFrame())
    assert pdf[:4] == b"%PDF"


def test_desglose_por_actividad_genera_pdf():
    cf = _cash_flow()
    costo = pd.DataFrame([
        {"capitulo": "1 Preliminares", "capitulo_orden": 1, "actividad": "1.01 Cerramiento",
         "corte": "Corte 1", "total": 1_245_400},
        {"capitulo": "1 Preliminares", "capitulo_orden": 1, "actividad": "1.05 Campamento",
         "corte": "Corte 2", "total": 9_869_438},
        {"capitulo": "2 Excavaciones", "capitulo_orden": 2, "actividad": "2.02 Fundaciones",
         "corte": "Corte 2", "total": 67_779_351},
    ])
    pdf = informe_pdf.generar_informe({"nombre": "Casa Vieja 61"}, cf, costo, periodo="2025")
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 2000


def test_con_detalle_de_anticipos_y_rangos_de_corte():
    cf = _cash_flow()
    cortes = pd.DataFrame([
        {"id": "K1", "nombre": "Corte 1", "fecha_inicio": "2025-05-29", "fecha_fin": "2025-10-23"},
        {"id": "K2", "nombre": "Corte 2", "fecha_inicio": "2025-10-24", "fecha_fin": "2025-11-30"},
    ])
    anticipos = pd.DataFrame([
        {"corte_id": "K1", "fecha": "2025-08-25", "valor": 30_000_000, "modo_pago": "efectivo", "detalle": "RC 100 (Bertran)"},
        {"corte_id": "K2", "fecha": "2025-10-24", "valor": 55_000_000, "modo_pago": "bancos", "detalle": "RC 112"},
    ])
    pdf = informe_pdf.generar_informe({"nombre": "Casa Vieja 61"}, cf, pd.DataFrame(),
                                      anticipos=anticipos, cortes=cortes)
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 2000


def test_rango_de_fechas_de_corte():
    assert informe_pdf._rango("2025-05-29", "2025-10-23") == "29/05/25-23/10/25"
    assert informe_pdf._rango("2025-05-29", None) == "desde 29/05/25"
    assert informe_pdf._rango(None, None) == ""


def test_formato_pesos_completos():
    assert informe_pdf._pesos(1_639_316_058) == "$1.639.316.058"
    assert informe_pdf._pesos(-47_404_252) == "-$47.404.252"
    assert informe_pdf._pesos(None) == "$0"


def test_celda_pesos_y_cero_vacio():
    assert informe_pdf._celda(350_302) == "350.302"
    assert informe_pdf._celda(-15_183_034) == "-15.183.034"
    assert informe_pdf._celda(0) == ""            # cero -> celda vacía, como su Excel
    assert informe_pdf._celda("100%") == "100%"   # strings pasan tal cual


def test_sin_corte_que_solo_arrastra_caja_se_oculta():
    """En el cash flow, 'Sin corte' hereda el saldo del último corte aunque no
    tenga movimiento propio: no debe ensuciar el informe del cliente."""
    cf = pd.DataFrame({
        "Corte 1": {"anticipos": 100, "total_egresos": 50, "caja_final": 50},
        "Sin corte": {"anticipos": 0, "total_egresos": 0, "caja_final": 50},
    })
    assert informe_pdf._sin_corte_vacio(cf, filas=["anticipos", "total_egresos"]) is True
    cf2 = cf.copy()
    cf2.loc["total_egresos", "Sin corte"] = 500     # ahora sí hay gasto sin corte
    assert informe_pdf._sin_corte_vacio(cf2, filas=["anticipos", "total_egresos"]) is False


if __name__ == "__main__":
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith("test_"):
            fn()
            print("OK  ", nombre)
