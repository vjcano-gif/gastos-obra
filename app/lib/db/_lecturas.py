"""Lecturas de la base (con caché) y armado del detalle clasificado."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from ._conexion import TTL_LECTURA

def df(res) -> pd.DataFrame:
    return pd.DataFrame(res.data or [])


TAM_PAGINA = 1000  # tope duro de PostgREST por respuesta, no se puede subir


def traer_todo(query) -> list[dict]:
    """Trae TODAS las filas de una consulta, saltando el tope de PostgREST.

    PostgREST corta cada respuesta en 1.000 filas SIN avisar, ignorando el
    .limit() que uno pida. Ya nos mordio (Revision mostraba "1000 (100%)"
    sobre 4.052 facturas). Este es el unico sitio con la logica de paginar:
    antes estaba copiada en facturas(), todos_los_items(), el importador y
    el reprocesador, y cada copia era una oportunidad de olvidar el .order()
    que hace el paginado determinista.

    `query` es un PostgREST query builder al que AUN no se le llamo
    .execute(); debe venir ya con su .order() (sin un orden estable, dos
    paginas pueden repetir o saltarse filas).
    """
    filas: list[dict] = []
    inicio = 0
    while True:
        lote = query.range(inicio, inicio + TAM_PAGINA - 1).execute().data or []
        filas.extend(lote)
        if len(lote) < TAM_PAGINA:
            return filas
        inicio += TAM_PAGINA


# El primer parametro va como `_sb`: Streamlit no serializa (ni usa como
# llave de caché) los argumentos que empiezan con guion bajo, y el cliente
# de Supabase no es hasheable. La llave de caché queda en uid + el resto.
@st.cache_data(ttl=TTL_LECTURA, show_spinner=False)
def proyectos(_sb, uid) -> pd.DataFrame:
    return df(_sb.table("proyectos").select("*").eq("user_id", uid).order("nombre").execute())


@st.cache_data(ttl=TTL_LECTURA, show_spinner=False)
def capitulos(_sb, uid) -> pd.DataFrame:
    return df(_sb.table("capitulos").select("*").eq("user_id", uid).order("orden").order("nombre").execute())


@st.cache_data(ttl=TTL_LECTURA, show_spinner=False)
def hitos_proyecto(_sb, uid, proyecto_id: str | None = None) -> pd.DataFrame:
    q = _sb.table("hitos_proyecto").select("*").eq("user_id", uid)
    if proyecto_id:
        q = q.eq("proyecto_id", proyecto_id)
    return df(q.order("fecha").execute())


@st.cache_data(ttl=TTL_LECTURA, show_spinner=False)
def actividades(_sb, uid) -> pd.DataFrame:
    """Trae también el nombre del capítulo al que pertenece cada actividad,
    para poder mostrar "Estructura › Vaciado de placa" en los selectores."""
    data = df(
        _sb.table("actividades")
        .select("*, capitulos(nombre)")
        .eq("user_id", uid)
        .order("nombre")
        .execute()
    )
    if not data.empty:
        data["capitulo_nombre"] = data["capitulos"].apply(
            lambda c: c["nombre"] if isinstance(c, dict) else None
        )
    return data


@st.cache_data(ttl=TTL_LECTURA, show_spinner=False)
def residentes(_sb, uid) -> pd.DataFrame:
    return (
        df(_sb.table("residentes").select("*").eq("user_id", uid).order("nombre").execute())
    )


@st.cache_data(ttl=TTL_LECTURA, show_spinner=False)
def cortes(_sb, uid, proyecto_id: str | None = None) -> pd.DataFrame:
    """Cortes de obra: los periodos de ejecución con los que ellos leen
    toda su información (capítulo × corte, cash flow por corte)."""
    q = _sb.table("cortes").select("*").eq("user_id", uid)
    if proyecto_id:
        q = q.eq("proyecto_id", proyecto_id)
    return df(q.order("proyecto_id").order("numero").execute())


@st.cache_data(ttl=TTL_LECTURA, show_spinner=False)
def anticipos(_sb, uid, proyecto_id: str | None = None) -> pd.DataFrame:
    """Abonos del cliente. Van aparte de las facturas porque el cash flow
    los necesita partidos por bancos/efectivo y con su número de recibo."""
    q = _sb.table("anticipos").select("*").eq("user_id", uid)
    if proyecto_id:
        q = q.eq("proyecto_id", proyecto_id)
    return df(q.order("fecha").execute())


@st.cache_data(ttl=TTL_LECTURA, show_spinner=False)
def movimientos_caja(_sb, uid, proyecto_id: str | None = None) -> pd.DataFrame:
    """Movimientos que no son facturas pero sí afectan la caja del
    proyecto: GMF 4x1000, otros gastos y pagos exentos."""
    q = _sb.table("movimientos_caja").select("*").eq("user_id", uid)
    if proyecto_id:
        q = q.eq("proyecto_id", proyecto_id)
    return df(q.order("fecha").execute())


def factura_items(sb, factura_id: str) -> pd.DataFrame:
    return df(
        sb.table("factura_items").select("*").eq("factura_id", factura_id).order("linea").execute()
    )


@st.cache_data(ttl=TTL_LECTURA, show_spinner=False)
def todos_los_items(_sb, uid) -> pd.DataFrame:
    """Todos los items de todas las facturas del workspace."""
    return pd.DataFrame(
        traer_todo(_sb.table("factura_items").select("*").eq("user_id", uid).order("id"))
    )


def items_de_factura_ids(sb, uid, factura_ids) -> pd.DataFrame:
    """Items de un conjunto conocido de facturas (las de un proyecto).

    Evita bajar los items de todo el workspace cuando una pantalla trabaja
    sobre una sola obra. Recibe los ids de facturas que la pagina ya tiene
    cargados y filtra por ellos, en lotes: `.in_()` mete los ids en la URL
    y una lista larga la desbordaria, asi que se parte de a 150.
    """
    ids = [i for i in factura_ids if i]
    if not ids:
        return pd.DataFrame()
    filas: list[dict] = []
    for i in range(0, len(ids), 150):
        lote = ids[i:i + 150]
        filas.extend(
            traer_todo(
                sb.table("factura_items").select("*")
                .eq("user_id", uid).in_("factura_id", lote).order("id")
            )
        )
    return pd.DataFrame(filas)


def asignaciones(sb, uid, factura_id: str | None = None) -> pd.DataFrame:
    q = sb.table("asignacion_costos").select("*").eq("user_id", uid)
    if factura_id:
        q = q.eq("factura_id", factura_id)
    return df(q.order("id").execute())


def aplicar_asignaciones(detalle: pd.DataFrame, asig: pd.DataFrame) -> pd.DataFrame:
    """Reemplaza las filas que tienen reparto multiproyecto por una fila
    por proyecto asignado. Las que no tienen reparto quedan igual (usan
    proyecto_id de la factura). Devuelve el detalle listo para reportes."""
    if detalle.empty or asig is None or asig.empty:
        return detalle

    # el reparto puede ser por artículo (factura_item_id) o por factura completa
    por_item = {a["factura_item_id"] for _, a in asig.iterrows() if a.get("factura_item_id")}
    por_factura = {
        a["factura_id"] for _, a in asig.iterrows() if not a.get("factura_item_id")
    }

    filas = []
    for _, r in detalle.iterrows():
        item_id, factura_id = r.get("item_id"), r.get("factura_id")
        reemplazada = (item_id in por_item) or (item_id is None and factura_id in por_factura)
        if not reemplazada:
            filas.append(r.to_dict())
            continue
        if item_id in por_item:
            aplican = asig[asig["factura_item_id"] == item_id]
        else:
            aplican = asig[(asig["factura_id"] == factura_id) & (asig["factura_item_id"].isna())]
        signo = -1 if (r.get("valor") or 0) < 0 else 1
        for _, a in aplican.iterrows():
            nueva = r.to_dict()
            nueva["proyecto_id"] = a["proyecto_id"]
            nueva["valor"] = signo * abs(float(a["monto"] or 0))
            nueva["repartida"] = True
            filas.append(nueva)
    return pd.DataFrame(filas)


_COLS_DETALLE = [
    "factura_id", "item_id", "fecha_emision", "numero", "proveedor_nombre",
    "descripcion", "cantidad", "valor", "sentido", "estado", "proyecto_id",
    "residente_id", "corte_id", "capitulo_id", "actividad_id",
]


def detalle_clasificado(fx: pd.DataFrame, items_all: pd.DataFrame) -> pd.DataFrame:
    """Una fila por artículo (con su propia clasificación), y una fila de
    respaldo por cada factura SIN detalle de artículos (manuales,
    consignaciones) usando la clasificación de la factura completa. Base
    común para "Todas las facturas" y los reportes por capítulo.

    Vectorizado: sobre 20.000 items el doble iterrows anterior tardaba y se
    ejecuta en cada rerun. El comportamiento (nota crédito resta, respaldo
    factura->artículo, factura sin items) está fijado en
    tests/test_detalle_clasificado.py — esta versión da lo mismo, peso por
    peso.
    """
    if fx.empty:
        return pd.DataFrame()

    fac = fx.rename(columns={"id": "factura_id"})
    ids_validos = set(fac["factura_id"])
    tiene_items = items_all is not None and not items_all.empty
    con_items: set = set()

    partes = []

    # ---- filas por artículo (item + datos de su factura) -----------------
    if tiene_items:
        it = items_all[items_all["factura_id"].isin(ids_validos)].copy()
        con_items = set(it["factura_id"])
        if not it.empty:
            m = it.merge(
                fac, on="factura_id", how="left", suffixes=("_it", "_fac")
            )

            # El merge renombra las columnas que existen en AMBAS tablas con
            # _it / _fac. Estos tres helpers resuelven de dónde sale cada
            # dato, respetando EXACTAMENTE lo que hacía el código viejo:
            def del_item(base):
                """Valor del artículo (sin caer a la factura). item_id,
                descripción y cantidad son del artículo aunque vengan vacíos:
                rellenarlos con lo de la factura mentiría sobre esa línea."""
                for c in (f"{base}_it", base):
                    if c in m:
                        return m[c]
                return pd.Series([None] * len(m))

            def de_factura(base):
                for c in (f"{base}_fac", base):
                    if c in m:
                        return m[c]
                return pd.Series([None] * len(m))

            def item_o_factura(base):
                """La del artículo manda; si viene vacía, la de la factura
                (respaldo de la migración 007)."""
                vi = del_item(base)
                return vi.where(vi.notna(), de_factura(base))

            es_nc = de_factura("tipo_documento").eq("nota_credito")
            total_it = pd.to_numeric(del_item("total"), errors="coerce").fillna(0).abs()
            a = pd.DataFrame({
                "factura_id": m["factura_id"],
                "item_id": del_item("id"),
                "fecha_emision": de_factura("fecha_emision"),
                "numero": de_factura("numero"),
                "proveedor_nombre": de_factura("proveedor_nombre"),
                "descripcion": del_item("descripcion"),
                "cantidad": del_item("cantidad"),
                "valor": total_it.where(~es_nc, -total_it),
                "sentido": de_factura("sentido"),
                "estado": de_factura("estado"),
                "proyecto_id": de_factura("proyecto_id"),
                "residente_id": de_factura("residente_id"),
                "corte_id": de_factura("corte_id"),
                "capitulo_id": item_o_factura("capitulo_id"),
                "actividad_id": item_o_factura("actividad_id"),
            })
            partes.append(a)

    # ---- fila de respaldo por factura SIN items --------------------------
    sin = fac[~fac["factura_id"].isin(con_items)]
    if not sin.empty:
        def fcol(base, defecto=None):
            return sin[base] if base in sin else pd.Series([defecto] * len(sin), index=sin.index)

        valor = fcol("monto_efectivo")
        if "monto_efectivo" not in sin:      # si no existe la columna, cae al total
            valor = fcol("total")
        else:                                # existe pero puede tener NaN sueltos
            valor = valor.where(valor.notna(), fcol("total"))
        b = pd.DataFrame({
            "factura_id": sin["factura_id"].values,
            "item_id": None,
            "fecha_emision": fcol("fecha_emision").values,
            "numero": fcol("numero").values,
            "proveedor_nombre": fcol("proveedor_nombre").values,
            "descripcion": fcol("descripcion").fillna("(sin detalle de artículos)").values
                if "descripcion" in sin else "(sin detalle de artículos)",
            "cantidad": None,
            "valor": valor.values,
            "sentido": fcol("sentido").values,
            "estado": fcol("estado").values,
            "proyecto_id": fcol("proyecto_id").values,
            "residente_id": fcol("residente_id").values,
            "corte_id": fcol("corte_id").values,
            "capitulo_id": fcol("capitulo_id").values,
            "actividad_id": fcol("actividad_id").values,
        })
        partes.append(b)

    if not partes:
        return pd.DataFrame()
    return pd.concat(partes, ignore_index=True)[_COLS_DETALLE]


@st.cache_data(ttl=TTL_LECTURA, show_spinner=False)
def facturas(_sb, uid, **filtros) -> pd.DataFrame:
    """Facturas del workspace. Acepta filtros por igualdad (proyecto_id=..,
    estado=..) que se empujan a la base para no bajar de mas."""
    q = _sb.table("facturas").select("*").eq("user_id", uid)
    for k, v in filtros.items():
        q = q.eq(k, v)
    # "id" como desempate: varias facturas comparten fecha (o la tienen
    # nula), y sin un orden 100% determinista el paginado puede saltarse o
    # repetir filas entre paginas.
    data = pd.DataFrame(traer_todo(q.order("fecha_emision", desc=True).order("id")))
    if not data.empty:
        # las notas crédito restan
        data["monto_efectivo"] = data.apply(
            lambda r: -abs(r["total"]) if r["tipo_documento"] == "nota_credito" else r["total"],
            axis=1,
        )
    return data


