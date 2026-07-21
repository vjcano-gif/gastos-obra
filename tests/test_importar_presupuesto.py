"""Parser del presupuesto por actividad (Excel) y su plantilla."""
import sys
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "app"))

from lib import importar_presupuesto, plantillas  # noqa: E402

_ENC = ["Capítulo", "Actividad", "Subactividad", "Unidad", "Cantidad", "Costo unitario", "Costo total"]


def _excel(filas, encabezados=None):
    wb = Workbook()
    ws = wb.active
    ws.title = "PRESUPUESTO"
    ws.append(encabezados or _ENC)
    for f in filas:
        ws.append(f)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parsea_y_calcula_total_si_falta():
    d = importar_presupuesto.parsear_excel(_excel([
        ["MAMPOSTERIA", "Muros", "Bloque", "m2", 300, 38000, 11400000],
        ["ESTRUCTURA", "Columnas", "", "m3", 10, 450000, None],   # total vacío -> 10*450000
    ]))
    assert len(d) == 2
    assert d.iloc[0]["capitulo"] == "MAMPOSTERIA"
    assert d.iloc[0]["costo_total"] == 11400000
    assert d.iloc[1]["costo_total"] == 4500000       # calculado


def test_descarta_filas_sin_identificacion_o_sin_valor():
    d = importar_presupuesto.parsear_excel(_excel([
        ["", "", "", "gl", 0, 0, 0],                  # nada -> fuera
        ["ACABADOS", "", "Pintura", "gl", 0, 0, 5000000],   # válida (subactividad + total)
    ]))
    assert len(d) == 1
    assert d.iloc[0]["subactividad"] == "Pintura"


def test_archivo_sin_columnas_avisa():
    wb = Workbook()
    wb.active.append(["algo", "otra"])
    buf = BytesIO()
    wb.save(buf)
    try:
        importar_presupuesto.parsear_excel(buf.getvalue())
        raise AssertionError("debió lanzar ValueError")
    except ValueError:
        pass


def test_plantilla_presupuesto_la_lee_su_parser():
    """La plantilla debe subirse sin novedad por el mismo parser."""
    d = importar_presupuesto.parsear_excel(plantillas.presupuesto())
    assert len(d) == 2
    assert d.iloc[0]["capitulo"] == "EXCAVACIONES, FUNDACIONES Y CONCRETOS"
    assert d.iloc[0]["costo_total"] == 54000000


if __name__ == "__main__":
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith("test_"):
            fn()
            print("OK  ", nombre)
