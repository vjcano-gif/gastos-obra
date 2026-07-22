import pandas as pd
import streamlit as st

from lib import db

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
cap = db.capitulos(sb, uid)
act = db.actividades(sb, uid)
res = db.residentes(sb, uid)
cortes = db.cortes(sb, uid)

# --- opciones compartidas por las dos vistas (clasificación + dimensiones)
opciones_pr = {"— sin proyecto —": None} | ({r["nombre"]: r["id"] for _, r in pr.iterrows()} if not pr.empty else {})
opciones_cap = {"— sin capítulo —": None} | ({r["nombre"]: r["id"] for _, r in cap.iterrows()} if not cap.empty else {})
opciones_act = {"— sin actividad —": None} | (
    {
        (f"{r['capitulo_nombre']} › {r['nombre']}" if r.get("capitulo_nombre") else r["nombre"]): r["id"]
        for _, r in act.iterrows()
    }
    if not act.empty else {}
)
opciones_res = {"— sin residente —": None} | ({r["nombre"]: r["id"] for _, r in res.iterrows()} if not res.empty else {})
opciones_cor = {"— sin corte —": None} | ({r["nombre"]: r["id"] for _, r in cortes.iterrows()} if not cortes.empty else {})
nombre_pr = {v: k for k, v in opciones_pr.items() if v}
nombre_cap = {v: k for k, v in opciones_cap.items() if v}
nombre_act = {v: k for k, v in opciones_act.items() if v}
nombre_res = {v: k for k, v in opciones_res.items() if v}
nombre_cor = {v: k for k, v in opciones_cor.items() if v}
puede = db.puede_editar(sb, uid)
ESTADOS_FACTURA = ["extraida", "asignada", "aprobada", "pagada", "anulada"]

vista = st.radio(
    "Vista",
    ["Por artículo (clasificar)", "Matriz (todas las columnas, por factura)"],
    horizontal=True,
)

# ============================ VISTA MATRIZ: una fila por factura, todas las
# columnas de la MATRIZ GASTOS del Excel. Con filtros (proyecto, fechas,
# estado de datos) y, para quien puede editar, un formulario para completar
# los campos que quedaron incompletos.
if vista.startswith("Matriz"):
    n_pr = dict(zip(pr["id"], pr["nombre"])) if not pr.empty else {}
    n_cap = dict(zip(cap["id"], cap["nombre"])) if not cap.empty else {}
    n_capcod = dict(zip(cap["id"], cap.get("codigo", cap["id"]))) if not cap.empty else {}
    n_act = dict(zip(act["id"], act["nombre"])) if not act.empty else {}
    n_cor = dict(zip(cortes["id"], cortes["nombre"])) if not cortes.empty else {}
    n_aiu = dict(zip(pr["id"], pr.get("pct_aiu", pd.Series(dtype=float)))) if not pr.empty else {}

    f = fx.copy()
    f["_fecha_dt"] = pd.to_datetime(f["fecha_emision"], errors="coerce")
    f["_proy_nom"] = f["proyecto_id"].map(n_pr).fillna("— sin proyecto —")

    # -------- filtros
    fc1, fc2, fc3 = st.columns([2, 2, 2])
    mf_proy = fc1.multiselect("Proyecto", sorted(f["_proy_nom"].unique()), key="mtz_proy")
    mf_ed = fc2.multiselect("Estado de datos", ["Pendiente por datos", "Completa"], key="mtz_ed")
    mf_prov = fc3.text_input("Buscar proveedor", key="mtz_prov")
    validas = f["_fecha_dt"].dropna()
    if not validas.empty:
        a, b = validas.min().date(), validas.max().date()
        d1, d2 = st.columns(2)
        md = d1.date_input("Desde", value=a, min_value=a, max_value=b, key="mtz_desde")
        mh = d2.date_input("Hasta", value=b, min_value=a, max_value=b, key="mtz_hasta")
        f = f[f["_fecha_dt"].isna() | ((f["_fecha_dt"].dt.date >= md) & (f["_fecha_dt"].dt.date <= mh))]
    if mf_proy:
        f = f[f["_proy_nom"].isin(mf_proy)]
    if mf_prov:
        f = f[f["proveedor_nombre"].fillna("").str.contains(mf_prov, case=False, regex=False)]
    f = f.reset_index(drop=True)
    if f.empty:
        st.info("Ninguna factura coincide con los filtros.")
        st.stop()

    def num(nombre):
        """Columna numérica como Serie; 0 si aún no existe."""
        if nombre in f.columns:
            return pd.to_numeric(f[nombre], errors="coerce").fillna(0)
        return pd.Series([0.0] * len(f), index=f.index)

    def fecha(nombre):
        if nombre in f.columns:
            return pd.to_datetime(f[nombre], errors="coerce").dt.date
        return pd.Series([None] * len(f), index=f.index)

    def vacio(col):
        s = f[col] if col in f.columns else pd.Series([None] * len(f), index=f.index)
        return s.isna() | s.astype(str).str.strip().isin(["", "None"])

    fe = f["_fecha_dt"]
    ret_calc = num("rete_fuente") + num("rete_iva") + num("rete_ica")
    total = num("total")
    total_pagar = total - ret_calc
    pagado = num("valor_pagado")

    # --- Saldo REAL: lo que FALTA por pagar. Una factura a crédito pendiente
    # = total a pagar − lo ya abonado (antes salía en 0 porque la columna
    # `saldo` no venía cargada). Pagada/anulada = 0.
    estp = (f["estado_pago"].fillna("") if "estado_pago" in f.columns else pd.Series("", index=f.index)).astype(str)
    est = (f["estado"].fillna("") if "estado" in f.columns else pd.Series("", index=f.index)).astype(str)
    liquidada = estp.eq("pagada") | est.isin(["pagada", "anulada"])
    saldo = (total_pagar - pagado).clip(lower=0).where(~liquidada, 0)

    # --- Estado de datos: qué campos clave faltan (solo aplica a gastos)
    es_gasto = f["sentido"].eq("gasto") if "sentido" in f.columns else pd.Series(True, index=f.index)
    es_credito = f["forma_pago"].eq("credito") if "forma_pago" in f.columns else pd.Series(False, index=f.index)
    faltan = pd.DataFrame({
        "proyecto": f["proyecto_id"].isna(),
        "capítulo": f["capitulo_id"].isna(),
        "forma de pago": vacio("forma_pago"),
        "vencimiento": es_credito & vacio("fecha_vencimiento"),
    })
    falta_txt = faltan.apply(lambda r: ", ".join(c for c in faltan.columns if r[c]), axis=1).where(es_gasto, "")
    estado_datos = pd.Series("Completa", index=f.index).mask(es_gasto & faltan.any(axis=1), "Pendiente por datos")

    cap_cod_s = f["capitulo_id"].map(n_capcod)
    capitulo_col = (cap_cod_s.astype(str).where(cap_cod_s.notna(), "") + " "
                    + f["capitulo_id"].map(n_cap).fillna("")).str.strip()

    m = pd.DataFrame({
        "Estado datos": estado_datos,
        "Faltan": falta_txt,
        "Proyecto": f["proyecto_id"].map(n_pr),
        "Capítulo": capitulo_col,
        "Corte": f["corte_id"].map(n_cor),
        "Actividad": f["actividad_id"].map(n_act),
        "Fecha": fe.dt.date, "Año": fe.dt.year, "Mes": fe.dt.month,
        "Proveedor": f["proveedor_nombre"], "NIT": f.get("proveedor_nit"),
        "Documento": f.get("tipo_documento"), "N.°": f["numero"], "Descripción": f.get("descripcion"),
        "Valor bruto": num("valor_bruto"), "Descuento": num("descuentos"), "IVA": num("iva"),
        "Excluido": num("excluidos"), "Impoconsumo": num("impoconsumo"), "Ajuste": num("ajuste"),
        "Fletes/otros": num("cargos"), "SUBTOTAL": total, "Retenciones": ret_calc,
        "TOTAL A PAGAR": total_pagar,
        "Forma pago": f.get("forma_pago"), "Estado pago": f.get("estado_pago"),
        "Medio pago": f.get("metodo_pago"), "Pagador": f.get("pagador"),
        "Encima/Debajo": f.get("legalizacion"), "Plazo": num("plazo_dias"),
        "Vencimiento": fecha("fecha_vencimiento"), "Concepto": f.get("concepto"),
        "% Rete": (ret_calc / total.where(total != 0, 1) * 100).round(2),
        "Fecha pago": fecha("fecha_pago"), "Valor pagado": pagado, "Saldo": saldo,
        "Exento AIU": f.get("exento_aiu"),
        "% AIU": (f["proyecto_id"].map(n_aiu).astype(float) * 100).round(1),
        "Comisión": pd.to_numeric(f.get("comision_aiu", 0), errors="coerce"),
    })

    if mf_ed:
        keep = estado_datos.isin(mf_ed)
        m, f = m[keep].reset_index(drop=True), f[keep].reset_index(drop=True)

    pend = int((m["Estado datos"] == "Pendiente por datos").sum())
    st.caption(
        f"{len(m)} facturas · **{pend} pendientes por datos** · todas las columnas de la MATRIZ GASTOS. "
        "Haz clic en una fila para completarla; descarga con el ícono de la esquina."
    )
    sel = st.dataframe(
        m, use_container_width=True, hide_index=True, height=520,
        on_select="rerun", selection_mode="single-row", key="mtz_tabla",
    )

    rows = sel.selection.rows if sel and sel.selection else []
    if rows:
        factura = f.iloc[rows[0]]
        _tot = pd.to_numeric(factura.get("total"), errors="coerce")
        st.divider()
        st.subheader(
            f"✏️ Completar: {factura.get('proveedor_nombre') or 'Sin nombre'} · "
            f"N.° {factura.get('numero') or 's.n.'} · {db.cop(0 if pd.isna(_tot) else _tot)}"
        )
        if not puede:
            st.caption("🔒 Tu rol no permite editar.")
        else:
            docs = db.df(sb.table("documentos").select("*").eq("factura_id", factura["id"]).execute())
            db.mostrar_documentos(sb, docs)
            venc0 = pd.to_datetime(factura.get("fecha_vencimiento"), errors="coerce")
            with st.form("editar_matriz"):
                e1, e2, e3 = st.columns(3)
                m_proy = e1.selectbox("Proyecto", list(opciones_pr),
                                      index=list(opciones_pr).index(nombre_pr.get(factura["proyecto_id"], "— sin proyecto —")))
                m_cap = e2.selectbox("Capítulo", list(opciones_cap),
                                     index=list(opciones_cap).index(nombre_cap.get(factura["capitulo_id"], "— sin capítulo —")))
                m_act = e3.selectbox("Actividad", list(opciones_act),
                                     index=list(opciones_act).index(nombre_act.get(factura["actividad_id"], "— sin actividad —")))
                g1, g2, g3 = st.columns(3)
                m_cor = g1.selectbox("Corte", list(opciones_cor),
                                     index=list(opciones_cor).index(nombre_cor.get(factura["corte_id"], "— sin corte —")))
                m_res = g2.selectbox("Residente", list(opciones_res),
                                     index=list(opciones_res).index(nombre_res.get(factura["residente_id"], "— sin residente —")))
                m_est = g3.selectbox("Estado", ESTADOS_FACTURA,
                                     index=db.indice_de(ESTADOS_FACTURA, factura.get("estado")))
                h1, h2, h3 = st.columns(3)
                m_forma = h1.selectbox("Forma de pago", db.opciones(db.FORMAS_PAGO),
                                       format_func=lambda v: db.etiqueta(db.FORMAS_PAGO, v) or "— sin dato —",
                                       index=db.indice_de(db.opciones(db.FORMAS_PAGO), factura.get("forma_pago")))
                m_epago = h2.selectbox("Estado de pago", db.opciones(db.ESTADOS_PAGO),
                                       format_func=lambda v: db.etiqueta(db.ESTADOS_PAGO, v) or "— sin dato —",
                                       index=db.indice_de(db.opciones(db.ESTADOS_PAGO), factura.get("estado_pago")))
                m_venc = h3.date_input("Vencimiento", value=(None if pd.isna(venc0) else venc0.date()), key="mtz_venc")
                if st.form_submit_button("💾 Guardar", use_container_width=True):
                    sb.table("facturas").update({
                        "proyecto_id": opciones_pr[m_proy], "capitulo_id": opciones_cap[m_cap],
                        "actividad_id": opciones_act[m_act], "corte_id": opciones_cor[m_cor],
                        "residente_id": opciones_res[m_res], "estado": m_est,
                        "forma_pago": m_forma or None, "estado_pago": m_epago or None,
                        "fecha_vencimiento": str(m_venc) if m_venc else None,
                    }).eq("id", factura["id"]).execute()
                    st.success("Actualizado.")
                    db.rerun()
    st.stop()

# ---------------------------------------------------------- una fila por articulo
# (las opciones opciones_pr/cap/act/res y nombre_* se construyen arriba, compartidas)
detalle = db.detalle_clasificado(fx, items_all)
total_original = len(detalle)

detalle["_fecha_dt"] = pd.to_datetime(detalle["fecha_emision"], errors="coerce")
detalle["proyecto"] = detalle["proyecto_id"].map(nombre_pr).fillna("—")
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
    "sentido", "estado", "proyecto", "capitulo", "actividad", "residente",
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
    db.mostrar_documentos(sb, docs)

    with st.form("editar_detalle"):
        if fila["item_id"] is None:
            st.caption("Esta factura no tiene detalle de artículos: se clasifica completa.")
        c1, c2 = st.columns(2)
        capitulo = c1.selectbox("Capítulo", list(opciones_cap), index=list(opciones_cap).index(nombre_cap.get(fila["capitulo_id"], "— sin capítulo —")))
        actividad = c2.selectbox("Actividad", list(opciones_act), index=list(opciones_act).index(nombre_act.get(fila["actividad_id"], "— sin actividad —")))

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
                            "capitulo_id": opciones_cap[capitulo],
                            "actividad_id": opciones_act[actividad],
                        }
                    ),
                }
            ).eq("id", fila["factura_id"]).execute()
            st.success("Actualizado.")
            db.rerun()
