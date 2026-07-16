from datetime import date

import streamlit as st

from lib import db

st.set_page_config(page_title="Configuración", page_icon="⚙️", layout="wide")
sb, uid = db.requiere_sesion()

st.title("⚙️ Configuración")

tab_p, tab_t, tab_r, tab_u = st.tabs(
    ["🏗️ Proyectos", "🏷️ Tipos de gasto", "🧾 Reglas de retención", "📏 UVT"]
)

with tab_p:
    pr = db.proyectos(sb, uid)
    if not pr.empty:
        st.dataframe(
            pr[["nombre", "codigo", "cliente_nombre", "cliente_email", "estado"]],
            use_container_width=True,
        )
    with st.form("nuevo_proyecto"):
        st.subheader("Nuevo proyecto")
        c1, c2 = st.columns(2)
        nombre = c1.text_input("Nombre (ej. Torre 1)")
        codigo = c2.text_input("Código corto para archivos (ej. TORRE1)")
        c3, c4, c5 = st.columns(3)
        cli = c3.text_input("Cliente")
        nit = c4.text_input("NIT del cliente")
        email = c5.text_input("Correo del cliente")
        presupuesto = st.number_input("Presupuesto total (opcional)", min_value=0.0, step=1000000.0)
        if st.form_submit_button("Crear proyecto") and nombre and codigo:
            sb.table("proyectos").insert(
                {
                    "user_id": uid,
                    "nombre": nombre,
                    "codigo": codigo.upper().replace(" ", ""),
                    "cliente_nombre": cli or None,
                    "cliente_nit": nit or None,
                    "cliente_email": email or None,
                    "presupuesto_total": presupuesto or None,
                }
            ).execute()
            st.rerun()

with tab_t:
    tg = db.tipos_gasto(sb, uid)
    if not tg.empty:
        st.dataframe(tg[["nombre", "capitulo", "concepto_retencion", "activo"]], use_container_width=True)
    with st.form("nuevo_tipo"):
        c1, c2, c3 = st.columns(3)
        n = c1.text_input("Nombre")
        cap = c2.text_input("Capítulo de obra")
        conc = c3.selectbox("Concepto de retención", ["compras", "servicios", "honorarios", "arriendos", "ninguno"])
        if st.form_submit_button("Agregar tipo") and n:
            sb.table("tipos_gasto").insert(
                {"user_id": uid, "nombre": n, "capitulo": cap or None, "concepto_retencion": conc}
            ).execute()
            st.rerun()

with tab_r:
    st.caption(
        "Las reglas NUNCA se editan: si la ley cambia, cierra la vigencia de la regla "
        "actual y crea una nueva desde la fecha del cambio. Así la historia no se altera."
    )
    reglas = db.df(
        sb.table("reglas_retencion").select("*").eq("user_id", uid)
        .order("tipo").order("vigencia_desde", desc=True).execute()
    )
    if not reglas.empty:
        vig = reglas["vigencia_hasta"].isna()
        st.dataframe(
            reglas.assign(estado=["✅ vigente" if v else "cerrada" for v in vig])[
                ["tipo", "concepto", "tarifa", "base_minima_uvt", "vigencia_desde", "vigencia_hasta", "estado"]
            ],
            use_container_width=True,
        )
        abiertas = reglas[vig]
        if not abiertas.empty:
            etiqueta = {
                f"{r['tipo']} · {r['concepto']} · {r['tarifa']}%": r["id"] for _, r in abiertas.iterrows()
            }
            with st.form("cerrar_regla"):
                st.subheader("Cerrar vigencia de una regla")
                sel = st.selectbox("Regla", list(etiqueta))
                hasta = st.date_input("Vigente hasta", value=date.today())
                if st.form_submit_button("Cerrar vigencia"):
                    sb.table("reglas_retencion").update({"vigencia_hasta": str(hasta)}).eq(
                        "id", etiqueta[sel]
                    ).execute()
                    st.rerun()
    with st.form("nueva_regla"):
        st.subheader("Nueva regla")
        c1, c2, c3, c4 = st.columns(4)
        tipo = c1.selectbox("Tipo", ["retefuente", "reteiva", "reteica"])
        conc = c2.selectbox("Concepto", ["compras", "servicios", "honorarios", "arriendos"])
        tarifa = c3.number_input("Tarifa %", min_value=0.0, step=0.1, format="%.2f")
        base = c4.number_input("Base mínima (UVT)", min_value=0.0, step=1.0)
        c5, c6 = st.columns(2)
        desde = c5.date_input("Vigente desde", value=date.today())
        muni = c6.text_input("Municipio (solo ReteICA)")
        if st.form_submit_button("Crear regla"):
            sb.table("reglas_retencion").insert(
                {
                    "user_id": uid,
                    "tipo": tipo,
                    "concepto": conc,
                    "tarifa": tarifa,
                    "base_minima_uvt": base,
                    "vigencia_desde": str(desde),
                    "municipio": muni or None,
                }
            ).execute()
            st.rerun()

with tab_u:
    st.caption("Valor de la UVT por año. Actualízalo cada enero (lo fija la DIAN).")
    uvt = db.df(sb.table("uvt").select("*").order("anio", desc=True).execute())
    if not uvt.empty:
        st.dataframe(uvt, use_container_width=True)
    anio_actual = date.today().year
    if uvt.empty or anio_actual not in uvt.get("anio", []).tolist():
        st.warning(f"No hay valor de UVT para {anio_actual}: las retenciones de este año no se calcularán.")
    with st.form("uvt_form"):
        c1, c2 = st.columns(2)
        anio = c1.number_input("Año", min_value=2020, max_value=2040, value=anio_actual)
        valor = c2.number_input("Valor (COP)", min_value=0.0, step=1.0)
        if st.form_submit_button("Guardar UVT") and valor:
            try:
                sb.table("uvt").upsert({"anio": int(anio), "valor": valor}).execute()
                st.rerun()
            except Exception:
                st.error(
                    "La tabla UVT solo permite lectura con este usuario. "
                    "Pídele al administrador registrar el valor (o ajusta la política RLS de la tabla uvt)."
                )
