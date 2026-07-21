"""Las plantillas descargables deben poder subirse SIN NOVEDAD: se prueba que
cada una la lea su propio importador y que sigan en sync con él."""
import io
import sys
from pathlib import Path

from openpyxl import load_workbook

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "app"))
sys.path.insert(0, str(RAIZ))

from lib import importar_ingresos, plantillas  # noqa: E402


def test_plantillas_son_xlsx_validos():
    for b in (plantillas.matriz_ingresos(), plantillas.matriz_gastos()):
        assert isinstance(b, bytes)
        assert b[:2] == b"PK"          # firma zip de un .xlsx
        assert len(b) > 500


def test_plantilla_ingresos_la_lee_su_propio_importador():
    """La fila de ejemplo tiene que pasar por el mismo parser de la app."""
    d = importar_ingresos.parsear_excel(plantillas.matriz_ingresos())
    assert len(d) == 2
    assert d.iloc[0]["proyecto"] == "Arrayanes 40"
    assert d.iloc[0]["valor"] == 80000000
    assert d.iloc[0]["modo_pago"] == "bancos"
    assert d.iloc[0]["legalizacion"] == "encima"
    assert d.iloc[1]["modo_pago"] == "bancos"          # "Consignación" -> bancos


def test_encabezados_ingresos_los_reconoce_el_parser():
    for h in plantillas.ENCABEZADOS_INGRESOS:
        assert importar_ingresos._norm(h) in importar_ingresos._ENCABEZADOS


def test_plantilla_gastos_en_sync_con_las_posiciones_del_importador():
    from worker.matriz import COL
    posiciones = set(COL.values())
    for pos, nombre in plantillas._COLS_GASTOS.items():
        assert pos in posiciones, f"la columna {pos} ({nombre}) no la lee el importador"


def test_plantilla_gastos_respeta_el_orden_por_posicion():
    ws = load_workbook(io.BytesIO(plantillas.matriz_gastos()))["MATRIZ GASTOS"]
    assert ws.cell(row=1, column=1).value == "Proyecto"
    assert ws.cell(row=1, column=31).value == "Estado"
    assert ws.cell(row=1, column=49).value == "Comisión"


if __name__ == "__main__":
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith("test_"):
            fn()
            print("OK  ", nombre)
