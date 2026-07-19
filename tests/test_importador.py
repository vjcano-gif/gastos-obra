"""El importador completo, contra una base simulada.

No basta con probar el cruce por separado: lo que puede salir mal de
verdad es el orquestador — que pise datos, que duplique al reejecutarse,
o que escriba durante una SIMULACION. Eso ultimo seria lo peor: el usuario
pide "solo muestrame que pasaria" y le tocan la base de produccion.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from worker.importar_matriz import Importador  # noqa: E402


class _Tabla:
    def __init__(self, base, nombre):
        self.base, self.nombre = base, nombre
        self._filtros = {}

    def select(self, *a, **k): return self
    def eq(self, col, val): self._filtros[col] = val; return self
    def order(self, *a, **k): return self
    def in_(self, *a, **k): return self

    def range(self, desde, hasta):
        self._rango = (desde, hasta)
        return self

    def execute(self):
        filas = self.base.datos.get(self.nombre, [])
        for col, val in self._filtros.items():
            filas = [f for f in filas if f.get(col) == val]
        d, h = getattr(self, "_rango", (0, 10**9))
        return type("R", (), {"data": filas[d:h + 1]})()

    def insert(self, filas):
        self.base.escrituras.append((self.nombre, "insert"))
        filas = filas if isinstance(filas, list) else [filas]
        creadas = []
        for f in filas:
            f = dict(f)
            f.setdefault("id", f"{self.nombre}-{len(self.base.datos.setdefault(self.nombre, []))}")
            self.base.datos.setdefault(self.nombre, []).append(f)
            creadas.append(f)
        return type("Q", (), {"execute": lambda s=None: type("R", (), {"data": creadas})()})()

    def update(self, cambios):
        self.base.escrituras.append((self.nombre, "update"))
        self._cambios = cambios
        return self

    def _aplicar_update(self):
        for f in self.base.datos.get(self.nombre, []):
            if all(f.get(c) == v for c, v in self._filtros.items()):
                f.update(self._cambios)
                self.base.updates.append((self.nombre, f.get("id"), dict(self._cambios)))
        return type("R", (), {"data": []})()


class _TablaUpdate(_Tabla):
    def execute(self):
        return self._aplicar_update() if hasattr(self, "_cambios") else super().execute()


class _Base:
    """Supabase falso: guarda filas en memoria y anota cada escritura."""

    def __init__(self, datos=None):
        self.datos = datos or {}
        self.escrituras, self.updates = [], []

    def table(self, nombre):
        return _TablaUpdate(self, nombre)


def _excel_falso(gastos, ingresos=(), proyectos=()):
    """Evita depender de un .xlsx real: se inyectan las filas ya leidas."""
    class _Imp(Importador):
        def leer(self):
            self.gastos = list(gastos)
            self.ingresos = list(ingresos)
            self.proyectos_excel = list(proyectos)
    return _Imp


GASTO = {
    "fila_excel": 10, "proyecto": "Casa Vieja 61", "capitulo_codigo": "4",
    "actividad_codigo": "4.01", "corte": "corte 1", "fecha": __import__("datetime").date(2025, 6, 1),
    "proveedor": "Ferreteria Corona", "nit": "901448577", "documento": "Factura electronica",
    "numero": "FE-708", "numero_norm": "FE708", "descripcion": "Cemento",
    "subtotal": 100000.0, "total_a_pagar": 97500.0, "retenciones": 2500.0, "iva": 19000.0,
    "forma_pago": "contado", "estado_pago": "pagada", "metodo_pago": "efectivo",
    "pagador": "empresa", "legalizacion": "debajo", "exento_aiu": False, "comision": 14000.0,
}

PROYECTO = {"nombre": "Casa Vieja 61", "estado": "activo", "pct_aiu": 0.14}


def _correr(datos, gastos, simular):
    base = _Base(datos)
    Imp = _excel_falso(gastos, proyectos=[PROYECTO])
    imp = Imp(base, "U1", "irrelevante.xlsx", simular=simular)
    imp.correr()
    return imp, base


def test_simular_no_escribe_absolutamente_nada():
    """La promesa de "simular" tiene que ser literal."""
    datos = {"proyectos": [], "cortes": [], "capitulos": [], "actividades": [], "facturas": [],
             "anticipos": []}
    imp, base = _correr(datos, [GASTO], simular=True)
    assert base.escrituras == [], f"escribio en simulacion: {base.escrituras}"
    assert base.updates == []


def test_hereda_la_clasificacion_a_la_factura_que_cruza():
    factura = {"id": "F1", "user_id": "U1", "numero": "FE 708",
               "proveedor_nit": "901448577",
               "proveedor_nombre": "Ferreteria Corona", "total": 100000.0}
    datos = {
        "proyectos": [], "cortes": [],
        # user_id en TODAS las filas falsas: _todas() filtra por esa columna
        # igual que PostgREST contra la base real, asi que una fila sin ella
        # queda invisible y la prueba probaria otra cosa.
        "capitulos": [{"id": "C4", "user_id": "U1", "codigo": "4"}],
        "actividades": [{"id": "A401", "user_id": "U1", "codigo": "4.01"}],
        "facturas": [factura], "anticipos": [],
    }
    imp, base = _correr(datos, [GASTO], simular=False)

    assert imp.resumen.get("cruzo_numero+nit") == 1
    assert imp.resumen.get("facturas_enriquecidas") == 1
    cambios = dict(base.updates[-1][2]) if base.updates else {}
    assert cambios.get("capitulo_id") == "C4"
    assert cambios.get("actividad_id") == "A401"
    # No se creo un movimiento nuevo: la factura ya existia
    assert imp.resumen.get("importadas_nuevas", 0) == 0


def test_lo_que_no_cruza_entra_como_movimiento_propio():
    """Las 695 facturas de papel y las cuentas de cobro nunca van a tener
    factura electronica; si no entran, el costo del proyecto queda corto."""
    datos = {"proyectos": [], "cortes": [], "capitulos": [], "actividades": [],
             "facturas": [], "anticipos": []}
    imp, base = _correr(datos, [GASTO], simular=False)

    assert imp.resumen.get("importadas_nuevas") == 1
    creada = [f for f in base.datos["facturas"] if f.get("origen_matriz")][0]
    assert creada["fuente"] == "matriz"
    assert creada["confianza"] == "baja"          # viene de Excel, no de un XML
    assert creada["estado"] == "asignada"         # nunca entra aprobada
    assert creada["origen_matriz"] == "MATRIZ GASTOS!10"
    assert creada["total"] == 100000.0


def test_reejecutar_no_duplica():
    """Es idempotente: la segunda corrida reconoce lo ya importado."""
    datos = {"proyectos": [], "cortes": [], "capitulos": [], "actividades": [],
             "facturas": [], "anticipos": []}
    imp1, base = _correr(datos, [GASTO], simular=False)
    assert imp1.resumen.get("importadas_nuevas") == 1

    Imp = _excel_falso([GASTO], proyectos=[PROYECTO])
    imp2 = Imp(base, "U1", "x.xlsx", simular=False)
    imp2.correr()
    assert imp2.resumen.get("importadas_nuevas", 0) == 0
    # En la segunda corrida el movimiento importado ya ES una factura, asi
    # que la fila del Excel empareja con el (numero + NIT) y no vuelve a
    # crearse. La idempotencia se cumple por el emparejamiento; el indice
    # sobre origen_matriz es la segunda linea de defensa.
    assert imp2.resumen.get("ya_estaba_completa") == 1
    assert len([f for f in base.datos["facturas"] if f.get("origen_matriz")]) == 1


def test_el_corte_se_crea_con_las_fechas_deducidas():
    import datetime
    g2 = GASTO | {"fila_excel": 11, "numero": "FE-709", "numero_norm": "FE709",
                  "fecha": datetime.date(2025, 6, 20)}
    datos = {"proyectos": [], "cortes": [], "capitulos": [], "actividades": [],
             "facturas": [], "anticipos": []}
    imp, base = _correr(datos, [GASTO, g2], simular=False)

    corte = base.datos["cortes"][0]
    assert corte["nombre"] == "Corte 1"
    assert corte["fecha_inicio"] == "2025-06-01"
    assert corte["fecha_fin"] == "2025-06-20"


def test_el_proyecto_se_crea_con_su_aiu():
    datos = {"proyectos": [], "cortes": [], "capitulos": [], "actividades": [],
             "facturas": [], "anticipos": []}
    imp, base = _correr(datos, [GASTO], simular=False)
    p = base.datos["proyectos"][0]
    assert p["nombre"] == "Casa Vieja 61"
    assert p["pct_aiu"] == 0.14
    assert p["codigo"]                       # hace falta para renombrar archivos


def test_sin_proyecto_no_se_inventa_un_movimiento():
    """Una fila cuyo proyecto no esta en LCLIENTES no debe colgarse de
    cualquier proyecto: se descarta y queda contada."""
    datos = {"proyectos": [], "cortes": [], "capitulos": [], "actividades": [],
             "facturas": [], "anticipos": []}
    huerfano = GASTO | {"proyecto": "Obra que no existe", "fila_excel": 99}
    imp, base = _correr(datos, [huerfano], simular=False)
    assert imp.resumen.get("descartadas_sin_proyecto_o_valor") == 1
    assert not [f for f in base.datos["facturas"] if f.get("origen_matriz")]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
