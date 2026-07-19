"""AIU/comision y asignacion automatica de corte.

Las cifras esperadas NO son inventadas: se sacaron de sus propios
archivos antes de escribir el codigo, y son las que tienen que seguir
saliendo. Si alguien cambia la formula, estas pruebas dicen contra que
realidad se esta comparando.

    Arrayanes 40    42.842.500 x 11%  = 4.712.675   (MATRIZ GASTOS)
    Casa Vieja 61    1.684.702 x 14%  =   235.858   (Cash Flow, AIU gastos)
    Casa Vieja 61      530.000 x 14%  =    74.200   (Cash Flow, AIU pagos directos)
"""
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from lib import db  # noqa: E402


# ------------------------------------------------------------------ AIU
def test_comision_reproduce_la_cifra_de_arrayanes_40():
    assert db.comision({"total": 42842500}, False, 0.11) == 4712675


def test_comision_reproduce_el_aiu_de_gastos_de_casa_vieja_61():
    assert db.comision({"total": 1684701.7}, False, 0.14) == round(1684701.7 * 0.14, 2)


def test_comision_reproduce_el_aiu_de_pagos_directos():
    """Los pagos directos generan comision aunque no pasen por la caja de
    Espacios: por eso van por separado, no porque no cuenten."""
    assert db.comision({"total": 530000}, False, 0.14) == 74200


def test_una_factura_exenta_no_genera_comision():
    assert db.comision({"total": 42842500}, True, 0.11) == 0
    assert db.base_aiu({"total": 42842500, "exento_aiu": True}) == 0


def test_proyecto_sin_aiu_no_genera_comision():
    """La mayoria de sus proyectos tiene AIU 0 (obras propias, corporativo)."""
    assert db.comision({"total": 1000000}, False, 0) == 0
    assert db.comision({"total": 1000000}, False, None) == 0


def test_valores_basura_no_revientan():
    """Los datos llegan de Excel y de OCR: hay strings y None donde deberia
    haber numeros. Esto corre dentro del guardado de Revision, asi que una
    excepcion aqui le tumba la pantalla al usuario."""
    assert db.comision({"total": None}, False, 0.11) == 0
    assert db.comision({"total": "no soy un numero"}, False, 0.11) == 0
    assert db.comision({}, False, 0.11) == 0
    assert db.comision({"total": 1000}, False, "ni yo") == 0


def test_la_retencion_no_reduce_la_base():
    """La retencion es plata que se le retiene al proveedor y se le gira a
    la DIAN, no un menor costo del proyecto: no puede bajar la comision."""
    factura = {"total": 1000000, "rete_fuente": 25000, "rete_ica": 5000}
    assert db.comision(factura, False, 0.10) == 100000


# ---------------------------------------------------------------- cortes
CORTES = pd.DataFrame(
    [
        {"id": "K1", "proyecto_id": "P1", "numero": 1,
         "fecha_inicio": "2025-05-29", "fecha_fin": "2025-10-23"},
        {"id": "K2", "proyecto_id": "P1", "numero": 2,
         "fecha_inicio": "2025-10-24", "fecha_fin": "2025-11-30"},
        {"id": "K3", "proyecto_id": "P2", "numero": 1,
         "fecha_inicio": "2025-01-01", "fecha_fin": "2025-12-31"},
    ]
)


def test_asigna_el_corte_por_la_fecha():
    assert db.corte_de_fecha(CORTES, "P1", date(2025, 6, 15)) == "K1"
    assert db.corte_de_fecha(CORTES, "P1", date(2025, 11, 5)) == "K2"


def test_respeta_los_limites_del_corte():
    assert db.corte_de_fecha(CORTES, "P1", date(2025, 5, 29)) == "K1"   # primer dia
    assert db.corte_de_fecha(CORTES, "P1", date(2025, 10, 23)) == "K1"  # ultimo dia
    assert db.corte_de_fecha(CORTES, "P1", date(2025, 10, 24)) == "K2"


def test_no_mezcla_cortes_de_otro_proyecto():
    """Cada obra tiene sus propios cortes; una fecha de un proyecto no
    puede caer en el corte de otro."""
    assert db.corte_de_fecha(CORTES, "P2", date(2025, 6, 15)) == "K3"
    assert db.corte_de_fecha(CORTES, "P3", date(2025, 6, 15)) is None


def test_fecha_fuera_de_todo_corte():
    assert db.corte_de_fecha(CORTES, "P1", date(2024, 1, 1)) is None
    assert db.corte_de_fecha(CORTES, "P1", date(2030, 1, 1)) is None


def test_entradas_vacias_no_revientan():
    assert db.corte_de_fecha(CORTES, "P1", None) is None
    assert db.corte_de_fecha(CORTES, None, date(2025, 6, 1)) is None
    assert db.corte_de_fecha(pd.DataFrame(), "P1", date(2025, 6, 1)) is None
    assert db.corte_de_fecha(None, "P1", date(2025, 6, 1)) is None
    assert db.corte_de_fecha(CORTES, "P1", "no soy fecha") is None


def test_corte_sin_fecha_fin_queda_abierto():
    """El corte en curso todavia no tiene cierre."""
    abierto = pd.DataFrame(
        [{"id": "KA", "proyecto_id": "P1", "numero": 9,
          "fecha_inicio": "2026-01-01", "fecha_fin": None}]
    )
    assert db.corte_de_fecha(abierto, "P1", date(2026, 7, 19)) == "KA"


# ---------------------------------------------------- indices de opciones
def test_indice_de_tolera_nan_de_pandas():
    """El NaN de pandas es "truthy", asi que un `or ""` no lo atajaba y
    list.index() reventaba con ValueError en pleno formulario."""
    ops = db.opciones(db.METODOS_PAGO)
    assert db.indice_de(ops, float("nan")) == 0
    assert db.indice_de(ops, None) == 0
    assert db.indice_de(ops, "valor_que_no_existe") == 0
    assert db.indice_de(ops, "efectivo") == ops.index("efectivo")


def test_vocabularios_coinciden_con_los_check_de_la_base():
    """Si la pantalla ofrece un valor que el CHECK rechaza, el guardado
    falla en produccion y no en las pruebas. Se contrasta contra el SQL."""
    sql = (Path(__file__).resolve().parents[1] / "supabase" / "migrations"
           / "013_cortes_aiu_dimensiones.sql").read_text(encoding="utf-8")
    for valor in db.METODOS_PAGO:
        assert f"'{valor}'" in sql, f"metodo_pago '{valor}' no esta en el CHECK"
    for valor in db.FORMAS_PAGO:
        assert f"'{valor}'" in sql, f"forma_pago '{valor}' no esta en el CHECK"
    for valor in db.ESTADOS_PAGO:
        assert f"'{valor}'" in sql, f"estado_pago '{valor}' no esta en el CHECK"


def test_etiqueta_muestra_datos_viejos_sin_romper():
    assert db.etiqueta(db.METODOS_PAGO, "efectivo") == "Efectivo"
    assert db.etiqueta(db.METODOS_PAGO, "algo_raro") == "algo_raro"
    assert db.etiqueta(db.METODOS_PAGO, None) == ""


if __name__ == "__main__":
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith("test_"):
            fn()
            print("OK  ", nombre)


# --- texto seguro contra el NaN de pandas (bug real en Revision) ----------
def test_texto_seguro_maneja_nan_y_none():
    """`valor or defecto` fallaba con el NaN de pandas (es "truthy") y
    reventaba al cortar el string. db.texto lo cubre."""
    import math
    assert db.texto(None, "Sin nombre") == "Sin nombre"
    assert db.texto(float("nan"), "Sin nombre") == "Sin nombre"
    assert db.texto(math.nan, "s.n.") == "s.n."
    assert db.texto("Ferreteria Corona") == "Ferreteria Corona"
    assert db.texto(123) == "123"
    # lo que rompia en produccion: cortar el resultado
    assert db.texto(float("nan"), "Sin nombre")[:45] == "Sin nombre"
