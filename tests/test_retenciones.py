"""Prueba del motor de retenciones: vigencias, bases mínimas y no reescritura."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from worker import retenciones

UVT = {2026: 52000.0}

REGLAS = [
    {  # vigente todo 2026 hasta junio 30
        "id": "r1", "tipo": "retefuente", "concepto": "compras", "tarifa": 1.0,
        "base_minima_uvt": 27, "vigencia_desde": "2026-01-01", "vigencia_hasta": "2026-06-30",
    },
    {  # la ley cambió al 2% desde julio 1
        "id": "r2", "tipo": "retefuente", "concepto": "compras", "tarifa": 2.0,
        "base_minima_uvt": 27, "vigencia_desde": "2026-07-01", "vigencia_hasta": None,
    },
    {
        "id": "r3", "tipo": "reteiva", "concepto": "compras", "tarifa": 15.0,
        "base_minima_uvt": 0, "vigencia_desde": "2026-01-01", "vigencia_hasta": None,
    },
]


def factura(fecha, bruto, iva=0.0):
    return {
        "sentido": "gasto", "fecha_emision": fecha, "valor_bruto": bruto,
        "descuentos": 0, "iva": iva, "concepto_retencion": "compras",
    }


def test_vigencia_antigua():
    """Factura de marzo usa la tarifa del 1%, no la del 2%."""
    r = retenciones.calcular(factura("2026-03-10", 10_000_000), REGLAS, UVT)
    assert r["rete_fuente"] == 100_000, r


def test_vigencia_nueva():
    """Factura de agosto usa la tarifa del 2%: la historia no cambia, lo nuevo sí."""
    r = retenciones.calcular(factura("2026-08-10", 10_000_000), REGLAS, UVT)
    assert r["rete_fuente"] == 200_000, r


def test_base_minima():
    """Compra por debajo de 27 UVT no genera retefuente."""
    r = retenciones.calcular(factura("2026-03-10", 1_000_000), REGLAS, UVT)
    assert r["rete_fuente"] == 0, r


def test_reteiva_sobre_iva():
    """ReteIVA se calcula sobre el IVA, no sobre la base."""
    r = retenciones.calcular(factura("2026-03-10", 10_000_000, iva=1_900_000), REGLAS, UVT)
    assert r["rete_iva"] == 285_000, r


def test_ingreso_no_retiene():
    f = factura("2026-03-10", 10_000_000)
    f["sentido"] = "ingreso"
    assert retenciones.calcular(f, REGLAS, UVT) == {}


if __name__ == "__main__":
    fallos = 0
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith("test_"):
            try:
                fn()
                print(f"OK   {nombre}")
            except AssertionError as e:
                fallos += 1
                print(f"FALLO {nombre}: {e}")
    sys.exit(1 if fallos else 0)
