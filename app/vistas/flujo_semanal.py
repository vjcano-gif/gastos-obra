"""Plan semanal de obra contra lo realmente ejecutado.

Equivale a su hoja "Flujo Semanal Casa 61": el presupuesto por actividad
y subactividad, repartido por semanas, comparado con el gasto real. Sirve
para responder si la obra va al ritmo que se planeó.
"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib import db, importar_presupuesto, plantillas

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
        # Solo las facturas y los items de esta obra, filtrados en la base.
        fx = db.facturas(sb, uid, proyecto_id=proyecto_id)
        real = (
            db.detalle_clasificado(fx, db.items_de_factura_ids(sb, uid, fx["id"].tolist()))
            if not fx.empty
            else pd.DataFrame()
        )

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

            # Etiquetas compactas (12M) para no saturar cuando hay muchas
            # semanas; las que se pisen se ocultan solas (uniformtext).
            def _compacto(v):
                v = float(v or 0)
                return f"{v/1e6:.0f}M" if abs(v) >= 1e6 else (f"{v/1e3:.0f}k" if v else "")

            fig = go.Figure()
            fig.add_bar(x=comparacion["periodo"], y=comparacion["planeado"], name="Planeado",
                        text=[_compacto(v) for v in comparacion["planeado"]], textposition="outside")
            fig.add_bar(x=comparacion["periodo"], y=comparacion["real"], name="Ejecutado",
                        text=[_compacto(v) for v in comparacion["real"]], textposition="outside")
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
                uniformtext_minsize=8, uniformtext_mode="hide",
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
        # ---------------------------------- carga masiva del presupuesto (Excel)
        with st.expander("📥 Cargar presupuesto masivo (Excel)"):
            st.caption(
                "Sube el presupuesto por actividad de este proyecto. Empareja "
                "capítulo y actividad por nombre y no duplica lo ya cargado."
            )
            st.download_button(
                "⬇️ Descargar plantilla", data=plantillas.presupuesto(),
                file_name="plantilla_presupuesto.xlsx", mime=plantillas.MIME_XLSX,
                help="Columnas correctas, ejemplo e instrucciones.",
            )
            archivo_p = st.file_uploader("Archivo .xlsx", type=["xlsx"], key="imp_ppto")
            if archivo_p is not None:
                try:
                    nuevas = importar_presupuesto.parsear_excel(archivo_p.getvalue())
                except Exception as e:
                    st.error(f"No se pudo leer el archivo: {e}")
                    nuevas = None
                if nuevas is not None and nuevas.empty:
                    st.warning("El archivo no tiene líneas de presupuesto válidas.")
                elif nuevas is not None:
                    _n = importar_presupuesto._norm
                    cap_por_nombre = {_n(v): k for k, v in nom_cap.items()}
                    # La actividad se empareja DENTRO de su capítulo: los nombres
                    # solo son únicos por capítulo (unique user_id,capitulo_id,nombre),
                    # así que emparejar por nombre global pegaría el id equivocado.
                    act_por_clave = {}
                    if not act.empty and "capitulo_id" in act.columns:
                        for _, a in act.iterrows():
                            act_por_clave[(a["capitulo_id"], _n(a["nombre"]))] = a["id"]

                    def _clave(cid, aid, sub, cant, total):
                        return (cid, aid, _n(sub), round(float(cant or 0), 2), round(float(total or 0), 2))

                    # Dedup contra lo que YA está en la base (incluye cantidad y
                    # total, para no colapsar dos líneas distintas del mismo rubro).
                    existentes = {
                        _clave(r.get("capitulo_id"), r.get("actividad_id"),
                               r.get("subactividad"), r.get("cantidad"), r.get("costo_total"))
                        for _, r in ppto.iterrows()
                    }
                    a_insertar, sin_cap, sin_act = [], set(), set()
                    for _, r in nuevas.iterrows():
                        cid = cap_por_nombre.get(_n(r["capitulo"])) if r["capitulo"] else None
                        if r["capitulo"] and cid is None:
                            sin_cap.add(r["capitulo"])
                        aid = act_por_clave.get((cid, _n(r["actividad"]))) if (cid and r["actividad"]) else None
                        if r["actividad"] and aid is None:
                            sin_act.add(r["actividad"])
                        clave = _clave(cid, aid, r["subactividad"], r["cantidad"], r["costo_total"])
                        if clave in existentes:
                            continue
                        existentes.add(clave)
                        a_insertar.append({
                            "user_id": uid, "proyecto_id": proyecto_id,
                            "capitulo_id": cid, "actividad_id": aid,
                            "subactividad": r["subactividad"], "unidad": r["unidad"],
                            "cantidad": float(r["cantidad"] or 0),
                            "costo_unitario": float(r["costo_unitario"] or 0),
                            "costo_total": float(r["costo_total"] or 0),
                            "orden": len(ppto) + len(a_insertar),
                        })
                    st.dataframe(
                        nuevas.assign(**{"Costo total": nuevas["costo_total"].map(db.cop)})[
                            ["capitulo", "actividad", "subactividad", "unidad", "cantidad", "Costo total"]
                        ],
                        use_container_width=True, hide_index=True,
                    )
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Líneas nuevas", len(a_insertar))
                    c2.metric("Sin capítulo", len(sin_cap))
                    c3.metric("Sin actividad", len(sin_act))
                    if sin_cap:
                        st.warning(
                            "Capítulos del archivo que no existen en la app (créalos en "
                            "Configuración): " + ", ".join(sorted(sin_cap))
                        )
                    if sin_act:
                        st.warning(
                            "Actividades que no coinciden con ninguna del capítulo "
                            "indicado (la línea entra sin actividad; revisa el nombre): "
                            + ", ".join(sorted(sin_act))
                        )
                    if a_insertar and st.button(f"✅ Cargar {len(a_insertar)} líneas"):
                        for i in range(0, len(a_insertar), 200):
                            sb.table("presupuesto").insert(a_insertar[i:i + 200]).execute()
                        st.success(f"{len(a_insertar)} líneas cargadas.")
                        db.rerun()

        # -------------------------------------- nueva línea individual (cascada)
        st.markdown("**Nueva línea de presupuesto**")
        # El capítulo va FUERA del form para que, al cambiarlo, se filtren SUS
        # actividades (un form no refresca hasta enviar).
        ops_cap = {"— sin capítulo —": None} | {v: k for k, v in nom_cap.items()}
        cap_sel = st.selectbox("Capítulo", list(ops_cap), key="ppto_cap_nueva")
        cap_id_sel = ops_cap[cap_sel]
        if cap_id_sel and not act.empty and "capitulo_id" in act.columns:
            act_cap = act[act["capitulo_id"] == cap_id_sel]
        else:
            act_cap = act.iloc[0:0]           # sin capítulo -> primero elige uno
        ops_act = {"— sin actividad —": None} | (
            {r["nombre"]: r["id"] for _, r in act_cap.iterrows()} if not act_cap.empty else {}
        )
        with st.form("nueva_linea_ppto"):
            act_sel = st.selectbox("Actividad", list(ops_act),
                                   help="Solo las actividades del capítulo elegido arriba.")
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
                        "capitulo_id": cap_id_sel,
                        "actividad_id": ops_act[act_sel],
                        "subactividad": sub or None,
                        "unidad": unidad or None,
                        "cantidad": cantidad,
                        "costo_unitario": unitario,
                        "costo_total": total_manual or round(cantidad * unitario, 2),
                        "orden": len(ppto),
                    }
                ).execute()
                db.rerun()

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
                    db.rerun()
