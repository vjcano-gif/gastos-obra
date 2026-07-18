import pandas as pd
import streamlit as st

from lib import db

st.set_page_config(page_title="Todas las facturas", page_icon="🗂️", layout="wide")
sb, uid = db.requiere_sesion()

st.title("🗂️ Todas las facturas")
st.caption(
    "El universo completo de lo procesado, a nivel de artículo (una factura con 5 artículos "
    "aparece en 5 filas, cada una con su propia clasificación). Filtra y haz clic en una fila "
    "para corregirla."
)

fx = db.facturas(sb, uid)
if fx.empty:
    st.info("No hay documentos todavía.")
    st.stop()

items_all = db.todos_los_items(sb, uid)

pr = db.proyectos(sb, uid)
tg = db.tipos_gasto(sb, uid)
cap = db.capitulos(sb, uid)
act = db.actividades(sb, uid)
res = db.residentes(sb, uid)

opciones_pr = {"— sin proyecto —": None} | ({r["nombre"]: r["id"] for _, r in pr.iterrows()} if not pr.empty else {})
opciones_tg = {"— sin tipo —": None} | ({r["nombre"]: r["id"] for _, r in tg.iterrows()} if not tg.empty else {})
opciones_cap = {"— sin capítulo —": None} | ({r["nombre"]: r["id"] for _, r in cap.iterrows()} if not cap.empty else {})
opciones_act = {"— sin actividad —": None} | (
    {
        (f"{r['capitulo_nombre']} › {r['nombre']}" if r.get("capitulo_nombre") else r["nombre"]): r["id"]
        for _, r in act.iterrows()
    }
    if not act.empty
    else {}
)
opciones_res = {"— sin residente —": None} | ({r["nombre"]: r["id"] for _, r in res.iterrows()} if not res.empty else {})

nombre_pr = {v: k for k, v in opciones_pr.items() if v}
nombre_tg = {v: k for k, v in opciones_tg.items() if v}
nombre_cap = {v: k for k, v in opciones_cap.items() if v}
nombre_act = {v: k for k, v in opciones_act.items() if v}
nombre_res = {v: k for k, v in opciones_res.items() if v}

# ---------------------------------------------------------- una fila por articulo
detalle = db.detalle_clasificado(fx, items_all)
total_original = len(detalle)

detalle["_fecha_dt"] = pd.to_datetime(detalle["fecha_emision"], errors="coerce")
detalle["proyecto"] = detalle["proyecto_id"].map(nombre_pr).fillna("—")
detalle["tipo_gasto"] = detalle["tipo_gasto_id"].map(nombre_tg).fillna("—")
detalle["capitulo"] = detalle["capitulo_id"].map(nombre_cap).fillna("—")
detalle["actividad"] = detalle["actividad_id"].map(nombre_act).fillna("—")
detalle["residente"] = detalle["residente_id"].map(nombre_res).fillna("—")

# ------------------------------------------------------------------ filtros
c1, c2, c3, c4 = st.columns(4)
f_proy = c1.multiselect("Proyecto", sorted(detalle["proyecto"].unique()))
f_cap = c2.multiselect("Capítulo", sorted(detalle["capitulo"].unique()))
f_estado = c3.multiselect("Estado", sorted(detalle["estado"].dropna().unique()))
f_proveedor = c4.text_input("Buscar proveedor")

fechas_validas = detalle["_fecha_dt"].dropna()
if not fechas_validas.empty:
    min_f, max_f = fechas_validas.min().date(), fechas_validas.max().date()
    cf1, cf2 = st.columns(2)
    desde = cf1.date_input("Desde", value=min_f, min_value=min_f, max_value=max_f, key="todas_desde")
    hasta = cf2.date_input("Hasta", value=max_f, min_value=min_f, max_value=max_f, key="todas_hasta")
    detalle = detalle[
        detalle["_fecha_dt"].isna() | ((detalle["_fecha_dt"].dt.date >= desde) & (detalle["_fecha_dt"].dt.date <= hasta))
    ]

if f_proy:
    detalle = detalle[detalle["proyecto"].isin(f_proy)]
if f_cap:
    detalle = detalle[detalle["capitulo"].isin(f_cap)]
if f_estado:
    detalle = detalle[detalle["estado"].isin(f_estado)]
if f_proveedor:
    detalle = detalle[detalle["proveedor_nombre"].fillna("").str.contains(f_proveedor, case=False, regex=False)]

detalle = detalle.reset_index(drop=True)
st.caption(f"**{len(detalle)}** de {total_original} artículos/facturas coinciden con los filtros.")

columnas_tabla = [
    "fecha_emision", "numero", "proveedor_nombre", "descripcion", "cantidad", "valor",
    "sentido", "estado", "proyecto", "tipo_gasto", "capitulo", "actividad", "residente",
]
seleccion = st.dataframe(
    detalle[columnas_tabla],
    use_container_width=True,
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    key="tabla_todas_facturas",
)

filas_sel = seleccion.selection.rows if seleccion and seleccion.selection else []
if filas_sel:
    fila = detalle.loc[filas_sel[0]]
    st.divider()
    st.subheader(
        f"✏️ Editar: {fila.get('proveedor_nombre') or 'Sin nombre'} · N.° {fila.get('numero') or 's.n.'} · "
        f"{fila.get('descripcion') or ''} · {db.cop(fila['valor'])}"
    )

    docs = db.df(sb.table("documentos").select("*").eq("factura_id", fila["factura_id"]).execute())
    for _, d in docs.iterrows():
        url = db.url_documento(sb, d["storage_path"])
        if url:
            nombre_doc = d.get("nombre_renombrado") or d.get("nombre_original") or "documento"
            st.markdown(f"📄 [⬇️ Descargar {nombre_doc}]({url})")

    with st.form("editar_detalle"):
        if fila["item_id"] is not None:
            c1, c2, c3 = st.columns(3)
            tipo = c1.selectbox("Tipo de gasto", list(opciones_tg), index=list(opciones_tg).index(nombre_tg.get(fila["tipo_gasto_id"], "— sin tipo —")))
            capitulo = c2.selectbox("Capítulo", list(opciones_cap), index=list(opciones_cap).index(nombre_cap.get(fila["capitulo_id"], "— sin capítulo —")))
            actividad = c3.selectbox("Actividad", list(opciones_act), index=list(opciones_act).index(nombre_act.get(fila["actividad_id"], "— sin actividad —")))
        else:
            st.caption("Esta factura no tiene detalle de artículos: se clasifica completa.")
            c1, c2, c3 = st.columns(3)
            tipo = c1.selectbox("Tipo de gasto", list(opciones_tg), index=list(opciones_tg).index(nombre_tg.get(fila["tipo_gasto_id"], "— sin tipo —")))
            capitulo = c2.selectbox("Capítulo", list(opciones_cap), index=list(opciones_cap).index(nombre_cap.get(fila["capitulo_id"], "— sin capítulo —")))
            actividad = c3.selectbox("Actividad", list(opciones_act), index=list(opciones_act).index(nombre_act.get(fila["actividad_id"], "— sin actividad —")))

        c4, c5, c6 = st.columns(3)
        proy = c4.selectbox("Proyecto", list(opciones_pr), index=list(opciones_pr).index(nombre_pr.get(fila["proyecto_id"], "— sin proyecto —")))
        residente = c5.selectbox("Residente", list(opciones_res), index=list(opciones_res).index(nombre_res.get(fila["residente_id"], "— sin residente —")))
        estado_nuevo = c6.selectbox(
            "Estado",
            ["extraida", "asignada", "aprobada", "pagada", "anulada"],
            index=["extraida", "asignada", "aprobada", "pagada", "anulada"].index(fila["estado"]),
        )
        if st.form_submit_button("💾 Guardar cambios", use_container_width=True):
            if fila["item_id"] is not None:
                sb.table("factura_items").update(
                    {
                        "tipo_gasto_id": opciones_tg[tipo],
                        "capitulo_id": opciones_cap[capitulo],
                        "actividad_id": opciones_act[actividad],
                    }
                ).eq("id", fila["item_id"]).execute()
            sb.table("facturas").update(
                {
                    "proyecto_id": opciones_pr[proy],
                    "residente_id": opciones_res[residente],
                    "estado": estado_nuevo,
                    **(
                        {}
                        if fila["item_id"] is not None
                        else {
                            "tipo_gasto_id": opciones_tg[tipo],
                            "capitulo_id": opciones_cap[capitulo],
                            "actividad_id": opciones_act[actividad],
                        }
                    ),
                }
            ).eq("id", fila["factura_id"]).execute()
            st.success("Actualizado.")
            st.rerun()
