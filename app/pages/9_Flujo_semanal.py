"""Plan semanal de obra contra lo realmente ejecutado.

Equivale a su hoja "Flujo Semanal Casa 61": el presupuesto por actividad
y subactividad, repartido por semanas, comparado con el gasto real. Sirve
para responder si la obra va al ritmo que se planeó.
"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib import db

st.set_page_config(page_title="Flujo semanal", page_icon="📆", layout="wide")
sb, uid = db.requiere_sesion()

st.title("📆 Flujo semanal: planeado vs ejecutado")

pr = db.proyectos(sb, uid)
if pr.empty:
    st.info("Crea un proyecto primero en Configuración.")
    st.stop()

nombres = {r["nombre"]: r["id"] for _, r in pr.iterrows()}
elegido = st.selectbox("Proyecto", list(nombres))
proyecto_id = nombres[elegido]

ppto = db.presupuesto(sb, uid, proyecto_id)
puede_editar = db.puede_editar(sb, uid)

tab_comparar, tab_ppto = st.tabs(["📊 Comparación", "📝 Presupuesto"])

with tab_comparar:
    if ppto.empty:
        st.info(
            "Este proyecto todavía no tiene presupuesto cargado. "
            "Créalo en la pestaña **Presupuesto** para poder comparar."
        )
    else:
        plan = db.plan_semanal(sb, uid, list(ppto["id"]))
        todas = db.facturas(sb, uid)
        fx = todas[todas["proyecto_id"] == proyecto_id] if not todas.empty else pd.DataFrame()
        real = db.detalle_clasificado(fx, db.todos_los_items(sb, uid)) if not fx.empty else pd.DataFrame()

        comparacion = db.planeado_vs_real(plan, real)
        if comparacion.empty:
            st.info("Aún no hay semanas con plan ni con gasto ejecutado.")
        else:
            total_plan = comparacion["planeado"].sum()
            total_real = comparacion["real"].sum()
            c1, c2, c3 = st.columns(3)
            c1.metric("Planeado", db.cop(total_plan))
            c2.metric("Ejecutado", db.cop(total_real))
            c3.metric(
                "Desfase", db.cop(total_real - total_plan),
                delta=f"{(total_real / total_plan - 1) * 100:.1f}%" if total_plan else None,
                delta_color="inverse",
            )

            fig = go.Figure()
            fig.add_bar(x=comparacion["periodo"], y=comparacion["planeado"], name="Planeado")
            fig.add_bar(x=comparacion["periodo"], y=comparacion["real"], name="Ejecutado")
            fig.add_scatter(
                x=comparacion["periodo"], y=comparacion["planeado_acum"],
                name="Planeado acumulado", mode="lines", yaxis="y2",
            )
            fig.add_scatter(
                x=comparacion["periodo"], y=comparacion["real_acum"],
                name="Ejecutado acumulado", mode="lines", yaxis="y2",
            )
            fig.update_layout(
                barmode="group",
                yaxis2=dict(overlaying="y", side="right", title="Acumulado"),
                xaxis_title="Semana", yaxis_title="Pesos de la semana",
            )
            st.plotly_chart(fig, use_container_width=True)

            st.caption(
                "El cumplimiento queda vacío en las semanas sin plan: una semana "
                "sin presupuesto no es un incumplimiento, es una semana sin plan."
            )
            st.dataframe(
                comparacion[
                    ["periodo", "planeado", "real", "desfase", "cumplimiento_%"]
                ].style.format(
                    {
                        "planeado": db.cop, "real": db.cop, "desfase": db.cop,
                        "cumplimiento_%": lambda v: "—" if pd.isna(v) else f"{v:.1f}%",
                    }
                ),
                use_container_width=True, hide_index=True,
            )

with tab_ppto:
    if not puede_editar:
        st.caption("🔒 Tu rol no permite editar el presupuesto.")

    cap = db.capitulos(sb, uid)
    act = db.actividades(sb, uid)
    nom_cap = dict(zip(cap["id"], cap["nombre"])) if not cap.empty else {}
    nom_act = dict(zip(act["id"], act["nombre"])) if not act.empty else {}

    if not ppto.empty:
        vista = ppto.assign(
            capitulo=ppto["capitulo_id"].map(nom_cap),
            actividad=ppto["actividad_id"].map(nom_act),
        )
        st.dataframe(
            vista[["capitulo", "actividad", "subactividad", "unidad",
                   "cantidad", "costo_unitario", "costo_total"]],
            use_container_width=True, hide_index=True,
        )
        st.metric("Presupuesto total del proyecto", db.cop(ppto["costo_total"].sum()))

    if puede_editar:
        with st.form("nueva_linea_ppto"):
            st.markdown("**Nueva línea de presupuesto**")
            ops_cap = {"— sin capítulo —": None} | {v: k for k, v in nom_cap.items()}
            ops_act = {"— sin actividad —": None} | {v: k for k, v in nom_act.items()}
            l1, l2 = st.columns(2)
            cap_sel = l1.selectbox("Capítulo", list(ops_cap))
            act_sel = l2.selectbox("Actividad", list(ops_act))
            sub = st.text_input("Subactividad", help="Ej: Vaciado de loza, Bomba, Casetones")
            m1, m2, m3 = st.columns(3)
            unidad = m1.text_input("Unidad", value="gl", help="mt2, uds, gl…")
            cantidad = m2.number_input("Cantidad", min_value=0.0, step=1.0, value=1.0)
            unitario = m3.number_input("Costo unitario", min_value=0.0, step=10000.0)
            st.caption(
                "Si el total negociado no es cantidad × unitario, escríbelo aparte: "
                "manda el valor negociado, como en su archivo."
            )
            total_manual = st.number_input(
                "Costo total (0 = calcular)", min_value=0.0, step=10000.0
            )
            if st.form_submit_button("Agregar línea"):
                sb.table("presupuesto").insert(
                    {
                        "user_id": uid,
                        "proyecto_id": proyecto_id,
                        "capitulo_id": ops_cap[cap_sel],
                        "actividad_id": ops_act[act_sel],
                        "subactividad": sub or None,
                        "unidad": unidad or None,
                        "cantidad": cantidad,
                        "costo_unitario": unitario,
                        "costo_total": total_manual or round(cantidad * unitario, 2),
                        "orden": len(ppto),
                    }
                ).execute()
                st.rerun()

        if not ppto.empty:
            st.divider()
            st.markdown("**Repartir una línea por semanas**")
            etiquetas = {
                f"{nom_cap.get(r['capitulo_id'], '—')} · {r.get('subactividad') or nom_act.get(r['actividad_id'], '—')} "
                f"({db.cop(r['costo_total'])})": r["id"]
                for _, r in ppto.iterrows()
            }
            linea = st.selectbox("Línea", list(etiquetas))
            with st.form("reparto_semanal"):
                s1, s2, s3 = st.columns(3)
                anio = s1.number_input("Año", min_value=2020, max_value=2100, value=2026, step=1)
                semana = s2.number_input("Semana ISO", min_value=1, max_value=53, value=1, step=1)
                valor = s3.number_input("Valor de esa semana", min_value=0.0, step=100000.0)
                if st.form_submit_button("Guardar semana"):
                    sb.table("presupuesto_semana").upsert(
                        {
                            "user_id": uid,
                            "presupuesto_id": etiquetas[linea],
                            "anio": int(anio),
                            "semana": int(semana),
                            "valor": valor,
                        },
                        on_conflict="presupuesto_id,anio,semana",
                    ).execute()
                    st.rerun()
