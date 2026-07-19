"""Validacion de las migraciones SQL sin necesitar un servidor.

Las migraciones son lo mas caro de equivocar: se corren a mano contra la
base del cliente y un error a mitad deja el esquema a medias. Aqui se
comprueban dos cosas antes de que eso pase:

1. SINTAXIS, con el parser real de PostgreSQL (pglast = libpg_query, el
   mismo que usa el servidor). No es una aproximacion.

2. COLUMNAS DE LAS POLITICAS RLS. Varias politicas se crean dentro de un
   bucle `foreach t in array array[...]` con format(): son cadenas, asi
   que ningun parser las revisa, pero Postgres SI valida las columnas al
   crear cada politica. Escribiendo la 016 meti `miembros` en una de esas
   listas — es la unica tabla cuyo dueno se llama owner_user_id y no
   user_id — y la migracion habria reventado a la mitad, con las tablas
   anteriores ya modificadas. Esta prueba es la que lo encontro.
"""
import re
import sys
from pathlib import Path

import pglast
import pytest

MIGRACIONES = sorted((Path(__file__).resolve().parents[1] / "supabase" / "migrations").glob("*.sql"))


def _sql(f: Path) -> str:
    return f.read_text(encoding="utf-8")


def _sin_comentarios(sql: str) -> str:
    """Quita los comentarios `--`.

    Hace falta porque los comentarios de estas migraciones EXPLICAN los
    nombres de columna ("...se llama owner_user_id y no user_id...") y el
    analisis de abajo los tomaba por codigo, marcando un fallo donde no lo
    habia. Se analiza lo que Postgres ejecuta, no lo que se le comenta.
    """
    return re.sub(r"--[^\n]*", "", sql)


def columnas_por_tabla() -> dict[str, set[str]]:
    """Columnas de cada tabla segun TODAS las migraciones en orden."""
    cols: dict[str, set[str]] = {}
    for f in MIGRACIONES:
        sql = _sql(f)
        for m in re.finditer(r"create table if not exists public\.(\w+) \((.*?)\n\);", sql, re.S):
            nombre, cuerpo = m.group(1), m.group(2)
            # Solo las lineas que declaran columna (dos espacios + identificador),
            # descartando las restricciones de tabla.
            declaradas = {
                c
                for c in re.findall(r"^ {2}(\w+)\s", cuerpo, re.M)
                if c not in ("check", "unique", "primary", "foreign", "constraint")
            }
            cols.setdefault(nombre, set()).update(declaradas)
        for m in re.finditer(r"alter table public\.(\w+)\s+add column if not exists (\w+)", sql):
            cols.setdefault(m.group(1), set()).add(m.group(2))
    return cols


COLUMNAS = columnas_por_tabla()

# Identificadores que aparecen en las politicas y son COLUMNAS de la tabla
# (no funciones ni palabras clave). Si una politica menciona una de estas,
# la tabla tiene que tenerla.
COLUMNAS_VIGILADAS = {"user_id", "owner_user_id", "member_user_id", "proyecto_id"}


@pytest.mark.parametrize("archivo", MIGRACIONES, ids=lambda f: f.name)
def test_sintaxis_valida(archivo: Path):
    """El parser real de PostgreSQL acepta el archivo completo."""
    assert pglast.parse_sql(_sql(archivo))


def test_esquema_tiene_las_tablas_esperadas():
    """Red de seguridad del propio parseo: si el regex de arriba dejara de
    encontrar las tablas, las demas pruebas pasarian en vacio."""
    for t in ("facturas", "proyectos", "cortes", "anticipos", "miembros"):
        assert t in COLUMNAS, f"no se detecto la tabla {t}"
    assert "user_id" in COLUMNAS["facturas"]
    # La rareza que causo el bug, fijada como hecho comprobado:
    assert "user_id" not in COLUMNAS["miembros"]
    assert "owner_user_id" in COLUMNAS["miembros"]


def _bucles_de_politicas(sql: str) -> list[tuple[list[str], str]]:
    """(tablas, plantilla) de cada `foreach t in array array[...]` que crea
    politicas con format()."""
    bucles = []
    for m in re.finditer(
        r"foreach t in array array\[(.*?)\]\s*(.*?)end loop", sql, re.S
    ):
        tablas = re.findall(r"'(\w+)'", m.group(1))
        bucles.append((tablas, m.group(2)))
    return bucles


@pytest.mark.parametrize("archivo", MIGRACIONES, ids=lambda f: f.name)
def test_politicas_en_bucle_solo_usan_columnas_existentes(archivo: Path):
    """Cada tabla de un bucle debe tener las columnas que la plantilla usa.

    Postgres valida las columnas al CREATE POLICY, aunque la sentencia
    venga de un format(); un descuadre revienta la migracion a media
    ejecucion.
    """
    for tablas, plantilla in _bucles_de_politicas(_sin_comentarios(_sql(archivo))):
        usadas = COLUMNAS_VIGILADAS & set(re.findall(r"\b(\w+)\b", plantilla))
        for tabla in tablas:
            faltantes = usadas - COLUMNAS.get(tabla, set())
            assert not faltantes, (
                f"{archivo.name}: la politica del bucle usa {sorted(faltantes)} "
                f"pero la tabla '{tabla}' no tiene esa columna "
                f"(tiene: {sorted(COLUMNAS.get(tabla, set()))[:6]}...)"
            )


@pytest.mark.parametrize("archivo", MIGRACIONES, ids=lambda f: f.name)
def test_politicas_sueltas_solo_usan_columnas_existentes(archivo: Path):
    """Lo mismo para las politicas escritas directamente, no en bucle."""
    sql = _sin_comentarios(_sql(archivo))
    for m in re.finditer(
        r"create policy \w+ on public\.(\w+)\s+for [\w ]+?\s*using \((.*?)\)\s*(?:with check|;)",
        sql,
        re.S,
    ):
        tabla, cuerpo = m.group(1), m.group(2)
        usadas = COLUMNAS_VIGILADAS & set(re.findall(r"\b(\w+)\b", cuerpo))
        faltantes = usadas - COLUMNAS.get(tabla, set())
        assert not faltantes, (
            f"{archivo.name}: politica sobre '{tabla}' usa {sorted(faltantes)}, "
            "columna que esa tabla no tiene"
        )


def test_el_cliente_no_puede_leer_las_tablas_sensibles():
    """La 016 debe excluir al cliente de TODA tabla con datos de
    proveedor, factura o evidencia. Si alguien agrega una tabla sensible
    y olvida el `not es_cliente()`, el cliente la veria completa."""
    sql = _sql(next(f for f in MIGRACIONES if f.name.startswith("016")))
    # Se recorta sobre el SQL crudo (los marcadores son comentarios) y solo
    # despues se limpian los comentarios de ese trozo.
    bloque = _sin_comentarios(sql.split("tablas VEDADAS")[1].split("tablas VISIBLES")[0])
    vedadas = {t for tablas, _ in _bucles_de_politicas(bloque) for t in tablas}
    for t in ("facturas", "factura_items", "documentos", "pagos", "asignacion_costos"):
        assert t in vedadas, f"'{t}' tiene datos sensibles y no quedo vedada al cliente"
    assert "not public.es_cliente()" in bloque


def test_el_cliente_queda_amarrado_a_un_proyecto():
    """Un cliente sin proyecto no estaria limitado por nada."""
    sql = _sql(next(f for f in MIGRACIONES if f.name.startswith("016")))
    assert "miembros_cliente_con_proyecto" in sql
    assert "rol <> 'cliente' or proyecto_id is not null" in sql


def test_el_cliente_no_puede_editar_ni_aprobar():
    sql = _sql(next(f for f in MIGRACIONES if f.name.startswith("016")))
    editar = sql.split("function public.puede_editar()")[1].split("$$;")[0]
    aprobar = sql.split("function public.puede_aprobar()")[1].split("$$;")[0]
    assert "es_cliente()" in editar
    assert "es_cliente()" in aprobar


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
