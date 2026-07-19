"""Pruebas del lector y el cruce de la matriz historica.

Aqui esta el riesgo mas serio de todo el cambio: heredar la clasificacion
de la factura EQUIVOCADA. Un dato heredado mal no lo revisa nadie (parece
correcto), a diferencia de uno vacio, que salta a la vista. Por eso el
emparejador prefiere no emparejar antes que arriesgarse, y eso es
justamente lo que se prueba abajo.
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from worker import matriz  # noqa: E402


# ---------------------------------------------------------- normalizacion
def test_numero_ignora_separadores():
    """El mismo documento se digita de varias formas segun quien lo hizo."""
    assert matriz.norm_numero("FE-708") == "FE708"
    assert matriz.norm_numero("FE 708") == "FE708"
    assert matriz.norm_numero("fe708") == "FE708"
    assert matriz.norm_numero("JH - 9008") == "JH9008"
    assert matriz.norm_numero("CCFE-65767") == "CCFE65767"


def test_numero_desde_excel_numerico():
    """Excel convierte los numeros a float: 4256 llega como "4256.0"."""
    assert matriz.norm_numero("4256.0") == "4256"
    assert matriz.norm_numero(4256) == "4256"


def test_nit_sin_digito_de_verificacion():
    assert matriz.norm_nit("901.448.577-1") == "901448577"
    assert matriz.norm_nit("901448577") == "901448577"
    assert matriz.norm_nit(None) == ""


def test_corte_canonico():
    assert matriz.norm_corte("Corte 1") == "corte 1"
    assert matriz.norm_corte("corte1") == "corte 1"
    assert matriz.norm_corte("  CORTE  12 ") == "corte 12"


def test_sin_corte_no_es_un_corte():
    """818 filas dicen "Sin corte": es la AUSENCIA de corte, no un corte
    llamado asi. Tomarlo literal creaba un corte fantasma por proyecto."""
    assert matriz.norm_corte("Sin corte") is None
    assert matriz.norm_corte("") is None
    assert matriz.norm_corte(None) is None


# ---------------------------------------------------------------- cruce
def _factura(**kw):
    base = {
        "id": "f1", "numero": "FE-708", "proveedor_nit": "901448577",
        "proveedor_nombre": "Ferreteria Corona", "total": 100098.2,
    }
    return base | kw


def test_cruza_por_numero_y_nit():
    idx = matriz.indexar_facturas([_factura()])
    f, motivo = matriz.emparejar(
        {"numero_norm": "FE708", "nit": "901448577", "subtotal": 0, "proveedor": None}, idx
    )
    assert f["id"] == "f1"
    assert motivo == "numero+nit"


def test_cruza_por_numero_y_valor_cuando_no_hay_nit():
    """El NIT solo esta en el 57% de las filas: el valor es el respaldo."""
    idx = matriz.indexar_facturas([_factura()])
    f, motivo = matriz.emparejar(
        {"numero_norm": "FE708", "nit": None, "subtotal": 100098.2, "proveedor": None}, idx
    )
    assert f["id"] == "f1"
    assert motivo == "numero+valor"


def test_cruza_por_numero_y_proveedor():
    idx = matriz.indexar_facturas([_factura()])
    f, motivo = matriz.emparejar(
        {"numero_norm": "FE708", "nit": None, "subtotal": 0,
         "proveedor": "FERRETERIA  CORONA"}, idx
    )
    assert f["id"] == "f1"
    assert motivo == "numero+proveedor"


def test_no_cruza_solo_por_numero():
    """Dos proveedores distintos pueden tener la factura "1234". Un numero
    suelto NO identifica nada."""
    idx = matriz.indexar_facturas([_factura(numero="1234", proveedor_nit="900111222")])
    f, motivo = matriz.emparejar(
        {"numero_norm": "1234", "nit": None, "subtotal": 0, "proveedor": None}, idx
    )
    assert f is None
    assert motivo == "sin_coincidencia"


def test_numero_ambiguo_no_se_empareja():
    """Si la llave apunta a DOS facturas, no se elige ninguna: heredar la
    clasificacion equivocada es peor que dejarla vacia."""
    idx = matriz.indexar_facturas(
        [
            _factura(id="a", numero="FE-708", proveedor_nit=None, total=50000),
            _factura(id="b", numero="FE 708", proveedor_nit=None, total=50000),
        ]
    )
    f, motivo = matriz.emparejar(
        {"numero_norm": "FE708", "nit": None, "subtotal": 50000, "proveedor": None}, idx
    )
    assert f is None
    assert motivo == "ambiguo"


def test_fila_sin_numero_no_cruza():
    idx = matriz.indexar_facturas([_factura()])
    f, motivo = matriz.emparejar({"numero_norm": "", "nit": "901448577"}, idx)
    assert f is None
    assert motivo == "sin_numero"


# --------------------------------------------------------- herencia
IDS = {
    "proyectos": {"casa vieja 61": "P1"},
    "capitulos": {"4": "C4"},
    "actividades": {"4.01": "A401"},
    "cortes": {("casa vieja 61", "corte 3"): "K3"},
}

FILA = {
    "proyecto": "Casa Vieja 61", "capitulo_codigo": "4", "actividad_codigo": "4.01",
    "corte": "corte 3", "forma_pago": "contado", "metodo_pago": "efectivo",
    "pagador": "empresa", "legalizacion": "debajo", "descripcion": "Cemento",
    "estado_pago": "pagada", "exento_aiu": False,
}


def test_hereda_la_clasificacion_a_una_factura_vacia():
    c = matriz.cambios_heredables(FILA, {}, IDS)
    assert c["proyecto_id"] == "P1"
    assert c["capitulo_id"] == "C4"
    assert c["actividad_id"] == "A401"
    assert c["corte_id"] == "K3"
    assert c["estado_pago"] == "pagada"


def test_no_pisa_lo_que_ya_estaba_clasificado():
    """Si alguien ya clasifico en la app, su decision manda sobre el Excel:
    el Excel es historico y la app es lo vivo."""
    factura = {"proyecto_id": "OTRO", "capitulo_id": "OTRO_CAP", "concepto": "ya escrito"}
    c = matriz.cambios_heredables(FILA, factura, IDS)
    assert "proyecto_id" not in c
    assert "capitulo_id" not in c
    assert "concepto" not in c
    assert c["actividad_id"] == "A401"      # esto si estaba vacio


def test_estado_pago_pendiente_no_sobreescribe():
    """'pendiente' es el valor por defecto de la columna, asi que no
    distingue "sin dato" de "de verdad pendiente": no debe pisar nada."""
    fila = FILA | {"estado_pago": "pendiente"}
    c = matriz.cambios_heredables(fila, {"estado_pago": "pagada"}, IDS)
    assert "estado_pago" not in c


def test_codigos_desconocidos_no_inventan_relacion():
    fila = FILA | {"capitulo_codigo": "99", "actividad_codigo": "99.99"}
    c = matriz.cambios_heredables(fila, {}, IDS)
    assert "capitulo_id" not in c
    assert "actividad_id" not in c


# ------------------------------------------------------------- cortes
def test_rango_de_corte_sale_de_los_movimientos():
    """Su LCORTE no trae fechas; el rango se deduce del primero al ultimo
    movimiento de cada corte, y eso es lo que permite asignarlo solo."""
    filas = [
        {"proyecto": "Casa Vieja 61", "corte": "corte 1", "fecha": date(2025, 5, 3)},
        {"proyecto": "Casa Vieja 61", "corte": "corte 1", "fecha": date(2025, 5, 28)},
        {"proyecto": "Casa Vieja 61", "corte": "corte 1", "fecha": date(2025, 5, 10)},
        {"proyecto": "Casa Vieja 61", "corte": "corte 2", "fecha": date(2025, 6, 4)},
        {"proyecto": "Casa Vieja 61", "corte": None, "fecha": date(2025, 7, 1)},
    ]
    r = matriz.rangos_de_cortes(filas)
    c1 = r[("casa vieja 61", "corte 1")]
    assert (c1["fecha_inicio"], c1["fecha_fin"]) == (date(2025, 5, 3), date(2025, 5, 28))
    assert c1["movimientos"] == 3
    assert len(r) == 2                       # la fila sin corte no crea uno


def test_numero_de_corte():
    assert matriz.numero_de_corte("corte 12") == 12
    assert matriz.numero_de_corte("corte 1") == 1
    assert matriz.numero_de_corte("") == 0


if __name__ == "__main__":
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith("test_"):
            fn()
            print("OK  ", nombre)
