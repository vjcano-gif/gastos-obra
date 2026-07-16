import streamlit as st

from lib import db

st.set_page_config(page_title="Revisión", page_icon="📋", layout="wide")
sb, uid = db.requiere_sesion()

st.title("📋 Revisión y asignación")

pr = db.proyectos(sb, uid)
tg = db.tipos_gasto(sb, uid)
opciones_pr = {"— sin proyecto —": None} | ({r["nombre"]: r["id"] for _, r in pr.iterrows()} if not pr.empty else {})
opciones_tg = {"— sin tipo —": None} | ({r["nombre"]: r["id"] for _, r in tg.iterrows()} if not tg.empty else {})

filtro = st.radio(
    "Mostrar", ["Por revisar", "Posibles duplicados", "Todas"], horizontal=True
)

fx = db.facturas(sb, uid)
if fx.empty:
    st.info("No hay documentos todavía.")
else:
    if filtro == "Por revisar":
        fx = fx[fx["estado"].isin(["extraida", "asignada"])]
    elif filtro == "Posibles duplicados":
        fx = fx[fx["posible_duplicado_de"].notna()]

    for _, f in fx.head(100).iterrows():
        icono = "🟢" if f["sentido"] == "ingreso" else "🔴"
        alerta = " ⚠️ posible duplicado" if f.get("posible_duplicado_de") else ""
        baja = " 🔍 confianza baja" if f.get("confianza") == "baja" else ""
        titulo = (
            f"{icono} {f.get('fecha_emision') or 's.f.'} · "
            f"{(f.get('proveedor_nombre') or 'Sin nombre')[:45]} · {db.cop(f['total'])} · "
            f"{f['tipo_documento']} · {f['estado']}{alerta}{baja}"
        )
        with st.expander(titulo):
            c1, c2 = st.columns([3, 2])
            with c1:
                st.caption(f.get("descripcion") or "Sin descripción")
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
                    url = db.url_documento(sb, d["storage_path"])
                    if url:
                        st.markdown(f"📄 [{d.get('nombre_renombrado') or d.get('nombre_original')}]({url})")
                        if str(d.get("mime", "")).endswith("pdf"):
                            with st.popover("👁 Previsualizar"):
                                st.components.v1.iframe(url, height=500)
            with c2:
                with st.form(f"asig_{f['id']}"):
                    proy = st.selectbox("Proyecto", list(opciones_pr), key=f"p{f['id']}")
                    tipo = st.selectbox("Tipo de gasto", list(opciones_tg), key=f"t{f['id']}")
                    metodo = st.selectbox("Método de pago", ["", "TC", "TD", "contado", "transferencia"])
                    pagador = st.selectbox("Quién paga", ["", "empresa", "cliente"])
                    concepto = st.text_input("Concepto", value=f.get("concepto") or "")
                    ca, cb = st.columns(2)
                    guardar = ca.form_submit_button("💾 Guardar", use_container_width=True)
                    aprobar = cb.form_submit_button("✅ Aprobar", use_container_width=True)
                    if guardar or aprobar:
                        cambios = {
                            "proyecto_id": opciones_pr[proy],
                            "tipo_gasto_id": opciones_tg[tipo],
                            "metodo_pago": metodo or None,
                            "pagador": pagador or None,
                            "concepto": concepto or None,
                            "estado": "aprobada" if aprobar else "asignada",
                            "posible_duplicado_de": None,
                        }
                        sb.table("facturas").update(cambios).eq("id", f["id"]).execute()
                        st.rerun()
                if st.button("🚫 Anular / descartar", key=f"an{f['id']}"):
                    sb.table("facturas").update({"estado": "anulada"}).eq("id", f["id"]).execute()
                    st.rerun()

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
        st.rerun()
