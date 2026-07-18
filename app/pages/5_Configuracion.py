from datetime import date

import streamlit as st

from lib import db

st.set_page_config(page_title="Configuración", page_icon="⚙️", layout="wide")
sb, uid = db.requiere_sesion()

st.title("⚙️ Configuración")

tab_p, tab_t, tab_c, tab_r, tab_u = st.tabs(
    ["🏗️ Proyectos", "🏷️ Tipos de gasto", "📐 Capítulos, actividades y residentes", "🧾 Reglas de retención", "📏 UVT"]
)

with tab_p:
    pr = db.proyectos(sb, uid)
    if not pr.empty:
        cols_mostrar = [
            c
            for c in ["nombre", "codigo", "cliente_nombre", "cliente_email", "fecha_inicio", "fecha_fin", "estado"]
            if c in pr.columns
        ]
        st.dataframe(pr[cols_mostrar], use_container_width=True)
    with st.form("nuevo_proyecto"):
        st.subheader("Nuevo proyecto")
        c1, c2 = st.columns(2)
        nombre = c1.text_input("Nombre (ej. Torre 1)")
        codigo = c2.text_input("Código corto para archivos (ej. TORRE1)")
        c3, c4, c5 = st.columns(3)
        cli = c3.text_input("Cliente")
        nit = c4.text_input("NIT del cliente")
        email = c5.text_input("Correo del cliente")
        c6, c7 = st.columns(2)
        fecha_inicio = c6.date_input("Fecha de inicio", value=None)
        fecha_fin = c7.date_input("Fecha de fin (estimada)", value=None)
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
                    "fecha_inicio": str(fecha_inicio) if fecha_inicio else None,
                    "fecha_fin": str(fecha_fin) if fecha_fin else None,
                    "presupuesto_total": presupuesto or None,
                }
            ).execute()
            st.rerun()

    st.divider()
    st.subheader("📅 Cronograma: abonos y entregables")
    st.caption(
        "Programa las fechas en que el cliente debe abonar y las fechas de entrega comprometidas. "
        "Sirve como referencia al revisar consignaciones y avance del proyecto."
    )
    if pr.empty:
        st.caption("Crea un proyecto primero.")
    else:
        opciones_pr_hitos = {r["nombre"]: r["id"] for _, r in pr.iterrows()}
        proy_sel_nombre = st.selectbox("Proyecto", list(opciones_pr_hitos), key="hitos_proy_sel")
        proy_sel_id = opciones_pr_hitos[proy_sel_nombre]

        hitos = db.hitos_proyecto(sb, uid, proy_sel_id)
        if not hitos.empty:
            etiqueta_tipo = {"abono": "💰 Abono", "entregable": "📦 Entregable"}
            tabla_hitos = hitos.assign(tipo=hitos["tipo"].map(etiqueta_tipo))
            st.dataframe(
                tabla_hitos[["tipo", "fecha", "descripcion", "monto", "cumplido"]],
                use_container_width=True,
            )
            pendientes = hitos[~hitos["cumplido"]]
            if not pendientes.empty:
                etiqueta_hito = {
                    f"{etiqueta_tipo[r['tipo']]} · {r['fecha']} · {r['descripcion']}": r["id"]
                    for _, r in pendientes.iterrows()
                }
                marcar = st.selectbox("Marcar como cumplido", list(etiqueta_hito), key="marcar_hito")
                if st.button("✅ Marcar cumplido"):
                    sb.table("hitos_proyecto").update({"cumplido": True}).eq("id", etiqueta_hito[marcar]).execute()
                    st.rerun()
        with st.form("nuevo_hito"):
            c1, c2, c3 = st.columns(3)
            tipo_hito = c1.selectbox("Tipo", ["abono", "entregable"], format_func=lambda t: "💰 Abono" if t == "abono" else "📦 Entregable")
            fecha_hito = c2.date_input("Fecha programada", value=date.today())
            monto_hito = c3.number_input("Monto (solo abonos)", min_value=0.0, step=100000.0)
            desc_hito = st.text_input("Descripción (ej. 'Segundo abono' o 'Entrega de cimentación')")
            if st.form_submit_button("Agregar al cronograma") and desc_hito:
                sb.table("hitos_proyecto").insert(
                    {
                        "user_id": uid,
                        "proyecto_id": proy_sel_id,
                        "tipo": tipo_hito,
                        "descripcion": desc_hito,
                        "fecha": str(fecha_hito),
                        "monto": monto_hito if tipo_hito == "abono" and monto_hito else None,
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

with tab_c:
    st.caption(
        "Capítulo = categoría grande del presupuesto de obra (Estructura, Acabados...). "
        "Actividad = tarea específica dentro de un capítulo. Residente = persona responsable "
        "en obra. Los tres se asignan a cada factura desde Revisión."
    )

    st.subheader("Capítulos")
    cap = db.capitulos(sb, uid)
    if not cap.empty:
        st.dataframe(cap[["nombre", "orden"]], use_container_width=True)
    with st.form("nuevo_capitulo"):
        c1, c2 = st.columns([3, 1])
        n_cap = c1.text_input("Nuevo capítulo")
        orden_cap = c2.number_input("Orden", min_value=0, step=1, value=len(cap))
        if st.form_submit_button("Agregar capítulo") and n_cap:
            sb.table("capitulos").insert({"user_id": uid, "nombre": n_cap, "orden": int(orden_cap)}).execute()
            st.rerun()

    st.divider()
    st.subheader("Actividades")
    act = db.actividades(sb, uid)
    if not act.empty:
        st.dataframe(
            act.assign(capitulo=act["capitulo_nombre"].fillna("— sin capítulo —"))[["capitulo", "nombre"]],
            use_container_width=True,
        )
    opciones_cap_form = {"— sin capítulo —": None} | (
        {r["nombre"]: r["id"] for _, r in cap.iterrows()} if not cap.empty else {}
    )
    with st.form("nueva_actividad"):
        c1, c2 = st.columns(2)
        cap_sel = c1.selectbox("Capítulo", list(opciones_cap_form))
        n_act = c2.text_input("Nueva actividad")
        if st.form_submit_button("Agregar actividad") and n_act:
            sb.table("actividades").insert(
                {"user_id": uid, "capitulo_id": opciones_cap_form[cap_sel], "nombre": n_act}
            ).execute()
            st.rerun()

    st.divider()
    st.subheader("Residentes")
    res = db.residentes(sb, uid)
    if not res.empty:
        st.dataframe(res[["nombre", "activo"]], use_container_width=True)
    with st.form("nuevo_residente"):
        n_res = st.text_input("Nombre del residente")
        if st.form_submit_button("Agregar residente") and n_res:
            sb.table("residentes").insert({"user_id": uid, "nombre": n_res}).execute()
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
