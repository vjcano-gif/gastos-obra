import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib import db

ORDEN_ESTADOS = ["extraida", "asignada", "aprobada", "pagada", "anulada"]
ETIQUETAS_ESTADO = {
    "extraida": "Sin revisar",
    "asignada": "Asignada (falta aprobar)",
    "aprobada": "Aprobada",
    "pagada": "Pagada",
    "anulada": "Anulada",
}

st.set_page_config(page_title="Revisión", page_icon="📋", layout="wide")
sb, uid = db.requiere_sesion()

st.title("📋 Revisión y asignación")

puede_aprobar = db.puede_aprobar(sb, uid)
if not puede_aprobar:
    st.caption("🔒 Tu rol no permite aprobar facturas: puedes clasificar y guardar.")

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

cortes = db.cortes(sb, uid)
nombre_corte = {c["id"]: c["nombre"] for _, c in cortes.iterrows()} if not cortes.empty else {}
# Quién paga se hereda del proyecto; solo el modo 'mixto' obliga a digitarlo.
modo_pagador = (
    {r["id"]: (r.get("pagador_modo") or "espacios") for _, r in pr.iterrows()}
    if not pr.empty
    else {}
)
# El %AIU es del contrato, así que vive en el proyecto y de ahí sale la comisión.
pct_aiu = (
    {r["id"]: (r.get("pct_aiu") or 0) for _, r in pr.iterrows()} if not pr.empty else {}
)

nombre_pr = {v: k for k, v in opciones_pr.items() if v}
nombre_tg = {v: k for k, v in opciones_tg.items() if v}
nombre_cap = {v: k for k, v in opciones_cap.items() if v}
nombre_act = {v: k for k, v in opciones_act.items() if v}

fx = db.facturas(sb, uid)

if fx.empty:
    st.info("No hay documentos todavía.")
else:
    fx["_fecha_dt"] = pd.to_datetime(fx["fecha_emision"], errors="coerce")
    fechas_validas = fx["_fecha_dt"].dropna()
    if not fechas_validas.empty:
        min_fecha, max_fecha = fechas_validas.min().date(), fechas_validas.max().date()
        st.caption(
            f"📅 Filtrar por fecha (datos disponibles desde {min_fecha} hasta {max_fecha}). "
            "Aplica a las métricas, gráficas y la lista de abajo."
        )
        cf1, cf2 = st.columns(2)
        desde = cf1.date_input("Desde", value=min_fecha, min_value=min_fecha, max_value=max_fecha, key="rev_desde")
        hasta = cf2.date_input("Hasta", value=max_fecha, min_value=min_fecha, max_value=max_fecha, key="rev_hasta")
        fx = fx[fx["_fecha_dt"].isna() | ((fx["_fecha_dt"].dt.date >= desde) & (fx["_fecha_dt"].dt.date <= hasta))]

    st.subheader("📊 Estado de la revisión")
    if fx.empty:
        st.info("No hay documentos en ese rango de fechas.")
    resumen = (
        fx.assign(monto_abs=fx["monto_efectivo"].abs())
        .groupby("estado")
        .agg(cantidad=("id", "count"), monto=("monto_abs", "sum"))
        .reindex(ORDEN_ESTADOS)
        .fillna(0)
    )
    total_cant = resumen["cantidad"].sum()

    cols_resumen = st.columns(len(ORDEN_ESTADOS))
    for col, estado in zip(cols_resumen, ORDEN_ESTADOS):
        cant = int(resumen.loc[estado, "cantidad"])
        monto = resumen.loc[estado, "monto"]
        pct = (cant / total_cant * 100) if total_cant else 0
        col.metric(ETIQUETAS_ESTADO[estado], f"{cant} ({pct:.0f}%)", db.cop(monto))

    cg1, cg2 = st.columns(2)
    with cg1:
        fig_cant = go.Figure(
            go.Bar(
                x=[ETIQUETAS_ESTADO[e] for e in ORDEN_ESTADOS],
                y=resumen["cantidad"],
                marker_color="#D85A30",
                text=resumen["cantidad"].astype(int),
                texttemplate="%{text}",
                textposition="outside",
            )
        )
        fig_cant.update_layout(title="Documentos por estado (cantidad)", height=320, margin=dict(t=40))
        st.plotly_chart(fig_cant, use_container_width=True)
    with cg2:
        # Barras con % en la etiqueta, no torta: los estados se comparan
        # mejor en barras (regla de visualización de toda la app).
        total_monto = resumen["monto"].sum() or 1
        fig_monto = go.Figure(
            go.Bar(
                x=[ETIQUETAS_ESTADO[e] for e in ORDEN_ESTADOS],
                y=resumen["monto"],
                marker_color="#1D9E75",
                text=[f"{db.cop(m)}<br>{m / total_monto * 100:.0f}%" for m in resumen["monto"]],
                textposition="outside",
            )
        )
        fig_monto.update_layout(title="Monto por estado", height=320, margin=dict(t=40), yaxis_title="COP")
        st.plotly_chart(fig_monto, use_container_width=True)

    st.divider()

filtro = st.radio(
    "Mostrar", ["Por revisar", "Posibles duplicados", "Todas"], horizontal=True
)

if not fx.empty:
    if filtro == "Por revisar":
        fx = fx[fx["estado"].isin(["extraida", "asignada"])]
    elif filtro == "Posibles duplicados":
        fx = fx[fx["posible_duplicado_de"].notna()]

    # Se ordena por cuándo LLEGÓ (created_at), no por la fecha de emisión:
    # así lo recién capturado queda arriba y de un vistazo se ve que el
    # barrido de correo sigue trayendo facturas. Una factura vieja emitida
    # en 2020 pero importada hoy debe verse arriba, no hundida al fondo.
    if "created_at" in fx.columns:
        fx = fx.assign(_llegada=pd.to_datetime(fx["created_at"], errors="coerce")).sort_values(
            "_llegada", ascending=False, na_position="last"
        )

    st.caption("Ordenadas por llegada: las más recientes primero.")
    for _, f in fx.head(100).iterrows():
        icono = "🟢" if f.get("sentido") == "ingreso" else "🔴"
        alerta = " ⚠️ posible duplicado" if f.get("posible_duplicado_de") else ""
        baja = " 🔍 confianza baja" if f.get("confianza") == "baja" else ""
        numero_doc = db.texto(f.get("numero"), "s.n.")
        proveedor = db.texto(f.get("proveedor_nombre"), "Sin nombre")[:45]
        # La fecha de llegada al lado de la de emisión: confirma que entró hoy.
        llegada = f.get("_llegada")
        sello = f" · llegó {llegada.date()}" if pd.notna(llegada) else ""
        titulo = (
            f"{icono} {db.texto(f.get('fecha_emision'), 's.f.')} · "
            f"{proveedor} · N.° {numero_doc} · {db.cop(f['total'])} · "
            f"{db.texto(f.get('estado'))}{alerta}{baja}{sello}"
        )
        with st.expander(titulo):
            items_f = db.factura_items(sb, f["id"])
            c1, c2 = st.columns([3, 2])
            with c1:
                st.markdown(db.render_factura_html(f, items_f), unsafe_allow_html=True)
                if f.get("cufe"):
                    st.caption(f"CUFE: `{str(f['cufe'])[:40]}…`")
                ret = (f.get("rete_fuente") or 0) + (f.get("rete_iva") or 0) + (f.get("rete_ica") or 0)
                if ret:
                    st.caption(
                        f"Retenciones sugeridas: {db.cop(ret)} "
                        f"(fuente {db.cop(f.get('rete_fuente'))}, IVA {db.cop(f.get('rete_iva'))}, "
                        f"ICA {db.cop(f.get('rete_ica'))})"
                    )
                docs = db.df(
                    sb.table("documentos").select("*").eq("factura_id", f["id"]).execute()
                )
                for _, d in docs.iterrows():
                    db.mostrar_documento(sb, d)

                if not items_f.empty:
                    st.markdown("**Clasificación por artículo**")
                    with st.form(f"items_{f['id']}"):
                        seleccion_items = {}
                        for _, it in items_f.iterrows():
                            st.caption(f"{it.get('descripcion') or 'Sin descripción'} · {db.cop(it.get('total'))}")
                            ci1, ci2, ci3 = st.columns(3)
                            tipo_i = ci1.selectbox(
                                "Tipo de gasto", list(opciones_tg), key=f"tg_{it['id']}",
                                index=list(opciones_tg).index(nombre_tg.get(it.get("tipo_gasto_id"), "— sin tipo —")),
                            )
                            cap_i = ci2.selectbox(
                                "Capítulo", list(opciones_cap), key=f"cap_{it['id']}",
                                index=list(opciones_cap).index(nombre_cap.get(it.get("capitulo_id"), "— sin capítulo —")),
                            )
                            act_i = ci3.selectbox(
                                "Actividad", list(opciones_act), key=f"act_{it['id']}",
                                index=list(opciones_act).index(nombre_act.get(it.get("actividad_id"), "— sin actividad —")),
                            )
                            seleccion_items[it["id"]] = (tipo_i, cap_i, act_i)
                        if st.form_submit_button("💾 Guardar clasificación de artículos", use_container_width=True):
                            for item_id, (tipo_i, cap_i, act_i) in seleccion_items.items():
                                sb.table("factura_items").update(
                                    {
                                        "tipo_gasto_id": opciones_tg[tipo_i],
                                        "capitulo_id": opciones_cap[cap_i],
                                        "actividad_id": opciones_act[act_i],
                                    }
                                ).eq("id", item_id).execute()
                            st.success("Artículos clasificados.")
                            db.rerun()
            with c2:
                with st.form(f"asig_{f['id']}"):
                    proy = st.selectbox("Proyecto", list(opciones_pr), key=f"p{f['id']}")
                    residente = st.selectbox("Residente", list(opciones_res), key=f"res{f['id']}")
                    if items_f.empty:
                        st.caption("Sin detalle de artículos: clasifica la factura completa aquí.")
                        tipo = st.selectbox("Tipo de gasto", list(opciones_tg), key=f"t{f['id']}")
                        capitulo = st.selectbox("Capítulo", list(opciones_cap), key=f"cap{f['id']}")
                        actividad = st.selectbox("Actividad", list(opciones_act), key=f"act{f['id']}")
                    # Los vacíos llegan de pandas como NaN (que es "truthy" y no
                    # está en la lista): db.indice_de() lo ataja.
                    m1, m2 = st.columns(2)
                    metodo_ops = db.opciones(db.METODOS_PAGO)
                    metodo = m1.selectbox(
                        "Medio de pago", metodo_ops, key=f"met{f['id']}",
                        index=db.indice_de(metodo_ops, f.get("metodo_pago")),
                        format_func=lambda v: db.etiqueta(db.METODOS_PAGO, v) or "—",
                    )
                    forma_ops = db.opciones(db.FORMAS_PAGO)
                    forma = m2.selectbox(
                        "Forma de pago", forma_ops, key=f"fpa{f['id']}",
                        index=db.indice_de(forma_ops, f.get("forma_pago")),
                        format_func=lambda v: db.etiqueta(db.FORMAS_PAGO, v) or "—",
                    )

                    # El corte se deduce de la fecha de emisión y del proyecto;
                    # solo se muestra para corregirlo cuando haga falta.
                    corte_ops = {"— automático por fecha —": None} | {
                        c["nombre"]: c["id"]
                        for _, c in cortes.iterrows()
                        if c["proyecto_id"] == opciones_pr[proy]
                    }
                    corte_nom = st.selectbox(
                        "Corte de obra", list(corte_ops), key=f"cor{f['id']}",
                        index=db.indice_de(
                            list(corte_ops), nombre_corte.get(f.get("corte_id"))
                        ),
                    )

                    # Quién paga se hereda del proyecto salvo que sea mixto:
                    # así Nadia no digita lo mismo en cada factura de una obra.
                    modo = modo_pagador.get(opciones_pr[proy], "espacios")
                    if modo == "mixto":
                        pagador_ops = db.opciones(db.PAGADOR)
                        pagador = st.selectbox(
                            "Quién paga", pagador_ops, key=f"pag{f['id']}",
                            index=db.indice_de(pagador_ops, f.get("pagador")),
                            format_func=lambda v: db.etiqueta(db.PAGADOR, v) or "—",
                        )
                    else:
                        pagador = "empresa" if modo == "espacios" else "cliente"
                        st.caption(
                            f"Quién paga: **{db.etiqueta(db.PAGADOR, pagador)}** "
                            "(heredado del proyecto)"
                        )

                    e1, e2 = st.columns(2)
                    legal_ops = db.opciones(db.LEGALIZACION)
                    legalizacion = e1.selectbox(
                        "Legalización", legal_ops, key=f"leg{f['id']}",
                        index=db.indice_de(legal_ops, f.get("legalizacion")),
                        format_func=lambda v: db.etiqueta(db.LEGALIZACION, v) or "—",
                    )
                    exento = e2.checkbox(
                        "Exenta de AIU", key=f"aiu{f['id']}",
                        value=bool(f.get("exento_aiu")),
                        help="Se excluye de la base sobre la que se calcula la comisión.",
                    )
                    concepto_actual = f.get("concepto")
                    concepto = st.text_input(
                        "Concepto", value=concepto_actual if isinstance(concepto_actual, str) else ""
                    )
                    ca, cb = st.columns(2)
                    guardar = ca.form_submit_button("💾 Guardar", use_container_width=True)
                    aprobar = cb.form_submit_button(
                        "✅ Aprobar", use_container_width=True, disabled=not puede_aprobar
                    )
                    if guardar or aprobar:
                        proyecto_id = opciones_pr[proy]
                        # Si no lo eligieron a mano, el corte sale de la fecha.
                        corte_id = corte_ops[corte_nom] or db.corte_de_fecha(
                            cortes, proyecto_id, f.get("fecha_emision")
                        )
                        cambios = {
                            "proyecto_id": proyecto_id,
                            "residente_id": opciones_res[residente],
                            "corte_id": corte_id,
                            "metodo_pago": metodo or None,
                            "forma_pago": forma or None,
                            "pagador": pagador or None,
                            "legalizacion": legalizacion or None,
                            "exento_aiu": exento,
                            "comision_aiu": db.comision(
                                f, exento, pct_aiu.get(proyecto_id, 0)
                            ),
                            "concepto": concepto or None,
                            "estado": "aprobada" if aprobar else "asignada",
                            "posible_duplicado_de": None,
                        }
                        if items_f.empty:
                            cambios["tipo_gasto_id"] = opciones_tg[tipo]
                            cambios["capitulo_id"] = opciones_cap[capitulo]
                            cambios["actividad_id"] = opciones_act[actividad]
                        sb.table("facturas").update(cambios).eq("id", f["id"]).execute()
                        db.rerun()
                if st.button("🚫 Anular / descartar", key=f"an{f['id']}"):
                    sb.table("facturas").update({"estado": "anulada"}).eq("id", f["id"]).execute()
                    db.rerun()

                # --- reparto entre varios proyectos (full costing)
                asig_f = db.asignaciones(sb, uid, f["id"])
                with st.expander(
                    f"🏗️ Repartir entre proyectos{' ✅' if not asig_f.empty else ''}"
                ):
                    if not asig_f.empty:
                        st.caption("Reparto actual (manda sobre el proyecto único):")
                        for _, a in asig_f.iterrows():
                            ca1, ca2 = st.columns([4, 1])
                            ca1.write(
                                f"· {nombre_pr.get(a['proyecto_id'], '—')} — {db.cop(a['monto'])}"
                                + (f" ({a['porcentaje']:.1f}%)" if a.get("porcentaje") else "")
                            )
                            if ca2.button("Quitar", key=f"delasig{a['id']}"):
                                sb.table("asignacion_costos").delete().eq("id", a["id"]).execute()
                                db.rerun()
                        asignado = float(asig_f["monto"].abs().sum())
                        st.caption(
                            f"Asignado: {db.cop(asignado)} de {db.cop(abs(f['total']))} "
                            f"({asignado / abs(f['total']) * 100:.0f}%)" if f["total"] else ""
                        )
                    with st.form(f"nueva_asig_{f['id']}"):
                        cr1, cr2 = st.columns(2)
                        proy_rep = cr1.selectbox(
                            "Proyecto", [p for p in opciones_pr if opciones_pr[p]], key=f"pr{f['id']}"
                        )
                        pct = cr2.number_input(
                            "% de la factura", min_value=0.0, max_value=100.0, step=5.0,
                            value=50.0, key=f"pct{f['id']}",
                        )
                        base_txt = st.text_input(
                            "Criterio (opcional)", key=f"base{f['id']}",
                            placeholder="ej. m2 construidos: Torre A=120, Torre B=80",
                        )
                        if st.form_submit_button("➕ Agregar reparto") and pct > 0:
                            sb.table("asignacion_costos").insert(
                                {
                                    "user_id": uid,
                                    "factura_id": f["id"],
                                    "proyecto_id": opciones_pr[proy_rep],
                                    "porcentaje": pct,
                                    "monto": round(abs(float(f["total"] or 0)) * pct / 100, 2),
                                    "metodo": "porcentaje",
                                    "base_asignacion": base_txt or None,
                                    "creado_por": db.usuario_actual_id(),
                                }
                            ).execute()
                            db.rerun()

st.divider()
st.subheader("➕ Registro manual (gasto o ingreso)")
with st.form("manual"):
    c1, c2, c3 = st.columns(3)
    sentido = c1.selectbox("Tipo", ["gasto", "ingreso"])
    fecha = c2.date_input("Fecha")
    total = c3.number_input("Valor (COP)", min_value=0.0, step=1000.0)
    proveedor = st.text_input("Proveedor / quien consigna")
    descripcion = st.text_input("Descripción")
    proy_m = st.selectbox("Proyecto", list(opciones_pr))
    archivo = st.file_uploader("Soporte (PDF o imagen, opcional)", type=["pdf", "png", "jpg", "jpeg"])
    if st.form_submit_button("Guardar movimiento"):
        res = (
            sb.table("facturas")
            .insert(
                {
                    "user_id": uid,
                    "sentido": sentido,
                    "tipo_documento": "manual",
                    "fuente": "manual",
                    "fecha_emision": str(fecha),
                    "total": total,
                    "proveedor_nombre": proveedor or None,
                    "descripcion": descripcion or None,
                    "proyecto_id": opciones_pr[proy_m],
                    "estado": "asignada",
                }
            )
            .execute()
        )
        fid = res.data[0]["id"]
        if archivo is not None:
            ruta = f"{uid}/{fid}/{archivo.name}"
            sb.storage.from_("documentos").upload(
                ruta, archivo.getvalue(), {"content-type": archivo.type or "application/octet-stream"}
            )
            sb.table("documentos").insert(
                {
                    "user_id": uid,
                    "factura_id": fid,
                    "storage_path": ruta,
                    "nombre_original": archivo.name,
                    "mime": archivo.type,
                }
            ).execute()
        st.success("Movimiento guardado.")
        db.rerun()
