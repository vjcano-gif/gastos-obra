import io

import pandas as pd
import streamlit as st

from lib import db, plantillas


@st.cache_data(show_spinner=False)
def _a_excel(df: pd.DataFrame) -> bytes:
    """La matriz filtrada como .xlsx (cacheado por contenido: no se regenera
    en cada interacción, solo cuando cambian los filtros)."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Facturas")
    return buf.getvalue()


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

# `items_all` (todos los artículos) solo lo usa la vista "Por artículo"; se carga
# allá abajo para no traerlo cuando se está en la Matriz (que va por factura).

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
    # Vectorizado (antes era un apply fila por fila, lento con miles de facturas):
    # por cada fila, une los nombres de columna cuyo booleano es True.
    _labels = faltan.columns.to_numpy()
    falta_txt = pd.Series([", ".join(_labels[fila]) for fila in faltan.to_numpy()],
                          index=f.index).where(es_gasto, "")
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
    st.caption(f"{len(m)} facturas · **{pend} pendientes por datos** · con los filtros aplicados.")
    st.download_button(
        "⬇️ Descargar Excel (todas las columnas, con los filtros aplicados)",
        data=_a_excel(m), file_name="todas_las_facturas.xlsx", mime=plantillas.MIME_XLSX,
    )

    # Sin permiso de edición: solo lectura de todas las columnas.
    if not puede:
        st.dataframe(m, use_container_width=True, hide_index=True, height=520)
        st.stop()

    # ------------------------------ edición en lote (rol administrador/editor)
    st.divider()
    st.subheader("✏️ Editar y guardar (administrador)")
    st.caption(
        "Cambia **proyecto** (escoge de la lista), capítulo, actividad, corte, residente, "
        "estado y forma/estado de pago **directo en la tabla**; luego pulsa Guardar. Las "
        "columnas grises no se editan. Filtra arriba (p. ej. «Pendiente por datos» + un "
        "proyecto) para acotar antes de editar."
    )

    LIMITE = 800
    if len(f) > LIMITE:
        st.warning(f"Se editan las primeras {LIMITE} de {len(f)}. Afina los filtros para llegar al resto.")
    fed = f.head(LIMITE).reset_index(drop=True)
    med = m.head(LIMITE).reset_index(drop=True)

    forma_rev = {v: k for k, v in db.FORMAS_PAGO.items()}
    estp_rev = {v: k for k, v in db.ESTADOS_PAGO.items()}
    estado_opts = ESTADOS_FACTURA + sorted(set(fed["estado"].dropna().astype(str)) - set(ESTADOS_FACTURA))

    ed = pd.DataFrame({
        "Estado datos": med["Estado datos"], "Faltan": med["Faltan"],
        "Proveedor": fed["proveedor_nombre"], "N.°": fed["numero"],
        "Fecha": pd.to_datetime(fed["fecha_emision"], errors="coerce").dt.date,
        "Total": med["SUBTOTAL"], "Saldo": med["Saldo"],
        "Proyecto": fed["proyecto_id"].map(lambda i: nombre_pr.get(i, "— sin proyecto —")),
        "Capítulo": fed["capitulo_id"].map(lambda i: nombre_cap.get(i, "— sin capítulo —")),
        "Actividad": fed["actividad_id"].map(lambda i: nombre_act.get(i, "— sin actividad —")),
        "Corte": fed["corte_id"].map(lambda i: nombre_cor.get(i, "— sin corte —")),
        "Residente": fed["residente_id"].map(lambda i: nombre_res.get(i, "— sin residente —")),
        "Estado": fed["estado"].fillna("").astype(str),
        "Forma pago": (fed["forma_pago"].map(lambda s: db.FORMAS_PAGO.get(str(s), "")) if "forma_pago" in fed else ""),
        "Estado pago": (fed["estado_pago"].map(lambda s: db.ESTADOS_PAGO.get(str(s), "")) if "estado_pago" in fed else ""),
        "Vencimiento": (pd.to_datetime(fed["fecha_vencimiento"], errors="coerce").dt.date if "fecha_vencimiento" in fed else None),
    })
    ed.index = fed["id"].values

    cfg = {
        "Proyecto": st.column_config.SelectboxColumn(options=list(opciones_pr), required=True),
        "Capítulo": st.column_config.SelectboxColumn(options=list(opciones_cap), required=True),
        "Actividad": st.column_config.SelectboxColumn(options=list(opciones_act), required=True),
        "Corte": st.column_config.SelectboxColumn(options=list(opciones_cor), required=True),
        "Residente": st.column_config.SelectboxColumn(options=list(opciones_res), required=True),
        "Estado": st.column_config.SelectboxColumn(options=estado_opts, required=True),
        "Forma pago": st.column_config.SelectboxColumn(options=[""] + list(db.FORMAS_PAGO.values())),
        "Estado pago": st.column_config.SelectboxColumn(options=[""] + list(db.ESTADOS_PAGO.values())),
        "Vencimiento": st.column_config.DateColumn(format="YYYY-MM-DD"),
        "Total": st.column_config.NumberColumn(format="$ %d"),
        "Saldo": st.column_config.NumberColumn(format="$ %d"),
    }
    editado = st.data_editor(
        ed, column_config=cfg,
        disabled=["Estado datos", "Faltan", "Proveedor", "N.°", "Fecha", "Total", "Saldo"],
        hide_index=True, use_container_width=True, height=520, key="mtz_editor",
    )

    if st.button("💾 Guardar cambios", type="primary", use_container_width=True):
        n = 0
        for fid in editado.index:
            a, b = ed.loc[fid], editado.loc[fid]
            upd = {}
            if b["Proyecto"] != a["Proyecto"]:
                upd["proyecto_id"] = opciones_pr[b["Proyecto"]]
            if b["Capítulo"] != a["Capítulo"]:
                upd["capitulo_id"] = opciones_cap[b["Capítulo"]]
            if b["Actividad"] != a["Actividad"]:
                upd["actividad_id"] = opciones_act[b["Actividad"]]
            if b["Corte"] != a["Corte"]:
                upd["corte_id"] = opciones_cor[b["Corte"]]
            if b["Residente"] != a["Residente"]:
                upd["residente_id"] = opciones_res[b["Residente"]]
            if b["Estado"] != a["Estado"]:
                upd["estado"] = b["Estado"]
            if b["Forma pago"] != a["Forma pago"]:
                upd["forma_pago"] = forma_rev.get(b["Forma pago"])
            if b["Estado pago"] != a["Estado pago"]:
                upd["estado_pago"] = estp_rev.get(b["Estado pago"])
            va, vb = b["Vencimiento"], a["Vencimiento"]
            if not (pd.isna(va) and pd.isna(vb)) and va != vb:
                upd["fecha_vencimiento"] = None if pd.isna(va) else str(va)
            if upd:
                sb.table("facturas").update(upd).eq("id", fid).execute()
                n += 1
        db.limpiar_cache()
        st.success(f"{n} facturas actualizadas." if n else "No hubo cambios que guardar.")
        if n:
            db.rerun()
    st.stop()

# ---------------------------------------------------------- una fila por articulo
# (las opciones opciones_pr/cap/act/res y nombre_* se construyen arriba, compartidas)
items_all = db.todos_los_items(sb, uid)
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
st.download_button(
    "⬇️ Descargar Excel (artículos filtrados)",
    data=_a_excel(detalle[columnas_tabla]), file_name="facturas_por_articulo.xlsx",
    mime=plantillas.MIME_XLSX,
)
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
