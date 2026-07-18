import pandas as pd
import streamlit as st

from lib import db

st.set_page_config(page_title="Todas las facturas", page_icon="🗂️", layout="wide")
sb, uid = db.requiere_sesion()

st.title("🗂️ Todas las facturas")
st.caption(
    "El universo completo de lo que se ha procesado — filtra por lo que necesites y haz "
    "clic en una fila para corregirla (proyecto, tipo, capítulo, actividad, residente, estado)."
)

fx = db.facturas(sb, uid)
if fx.empty:
    st.info("No hay documentos todavía.")
    st.stop()

total_original = len(fx)

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

fx["_fecha_dt"] = pd.to_datetime(fx["fecha_emision"], errors="coerce")
fx["proyecto"] = fx["proyecto_id"].map(nombre_pr).fillna("—")
fx["tipo_gasto"] = fx["tipo_gasto_id"].map(nombre_tg).fillna("—")
fx["capitulo"] = fx["capitulo_id"].map(nombre_cap).fillna("—")
fx["residente"] = fx["residente_id"].map(nombre_res).fillna("—")

# ------------------------------------------------------------------ filtros
c1, c2, c3, c4 = st.columns(4)
f_proy = c1.multiselect("Proyecto", sorted(fx["proyecto"].unique()))
f_estado = c2.multiselect("Estado", sorted(fx["estado"].dropna().unique()))
f_sentido = c3.multiselect("Gasto / ingreso", sorted(fx["sentido"].dropna().unique()))
f_proveedor = c4.text_input("Buscar proveedor")

fechas_validas = fx["_fecha_dt"].dropna()
if not fechas_validas.empty:
    min_f, max_f = fechas_validas.min().date(), fechas_validas.max().date()
    cf1, cf2 = st.columns(2)
    desde = cf1.date_input("Desde", value=min_f, min_value=min_f, max_value=max_f, key="todas_desde")
    hasta = cf2.date_input("Hasta", value=max_f, min_value=min_f, max_value=max_f, key="todas_hasta")
    fx = fx[fx["_fecha_dt"].isna() | ((fx["_fecha_dt"].dt.date >= desde) & (fx["_fecha_dt"].dt.date <= hasta))]

if f_proy:
    fx = fx[fx["proyecto"].isin(f_proy)]
if f_estado:
    fx = fx[fx["estado"].isin(f_estado)]
if f_sentido:
    fx = fx[fx["sentido"].isin(f_sentido)]
if f_proveedor:
    fx = fx[fx["proveedor_nombre"].fillna("").str.contains(f_proveedor, case=False, regex=False)]

fx = fx.reset_index(drop=True)
st.caption(f"**{len(fx)}** de {total_original} facturas coinciden con los filtros.")

columnas_tabla = [
    "fecha_emision", "proveedor_nombre", "total", "sentido", "tipo_documento",
    "estado", "proyecto", "tipo_gasto", "capitulo", "residente",
]
seleccion = st.dataframe(
    fx[columnas_tabla],
    use_container_width=True,
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    key="tabla_todas_facturas",
)

filas_sel = seleccion.selection.rows if seleccion and seleccion.selection else []
if filas_sel:
    f = fx.loc[filas_sel[0]]
    st.divider()
    st.subheader(f"✏️ Editar: {f.get('proveedor_nombre') or 'Sin nombre'} · {db.cop(f['total'])} · {f.get('fecha_emision') or 's.f.'}")
    with st.form("editar_factura_todas"):
        c1, c2, c3 = st.columns(3)
        proy = c1.selectbox("Proyecto", list(opciones_pr), index=list(opciones_pr).index(nombre_pr.get(f["proyecto_id"], "— sin proyecto —")))
        tipo = c2.selectbox("Tipo de gasto", list(opciones_tg), index=list(opciones_tg).index(nombre_tg.get(f["tipo_gasto_id"], "— sin tipo —")))
        estado_nuevo = c3.selectbox(
            "Estado",
            ["extraida", "asignada", "aprobada", "pagada", "anulada"],
            index=["extraida", "asignada", "aprobada", "pagada", "anulada"].index(f["estado"]),
        )
        c4, c5, c6 = st.columns(3)
        capitulo = c4.selectbox("Capítulo", list(opciones_cap), index=list(opciones_cap).index(nombre_cap.get(f["capitulo_id"], "— sin capítulo —")))
        actividad = c5.selectbox("Actividad", list(opciones_act), index=list(opciones_act).index(nombre_act.get(f["actividad_id"], "— sin actividad —")))
        residente = c6.selectbox("Residente", list(opciones_res), index=list(opciones_res).index(nombre_res.get(f["residente_id"], "— sin residente —")))
        c7, c8 = st.columns(2)
        metodo_opciones = ["", "TC", "TD", "contado", "transferencia"]
        metodo = c7.selectbox("Método de pago", metodo_opciones, index=metodo_opciones.index(f.get("metodo_pago") or ""))
        pagador_opciones = ["", "empresa", "cliente"]
        pagador = c8.selectbox("Quién paga", pagador_opciones, index=pagador_opciones.index(f.get("pagador") or ""))
        concepto = st.text_input("Concepto", value=f.get("concepto") or "")
        if st.form_submit_button("💾 Guardar cambios", use_container_width=True):
            sb.table("facturas").update(
                {
                    "proyecto_id": opciones_pr[proy],
                    "tipo_gasto_id": opciones_tg[tipo],
                    "capitulo_id": opciones_cap[capitulo],
                    "actividad_id": opciones_act[actividad],
                    "residente_id": opciones_res[residente],
                    "metodo_pago": metodo or None,
                    "pagador": pagador or None,
                    "concepto": concepto or None,
                    "estado": estado_nuevo,
                }
            ).eq("id", f["id"]).execute()
            st.success("Actualizado.")
            st.rerun()
