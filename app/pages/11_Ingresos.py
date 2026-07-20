"""Ingresos del cliente y cumplimiento por proyecto.

Es la "MATRIZ INGRESOS" del Excel: los abonos del cliente se registran a
MANO (no llegan por correo). Aquí se ingresan, se ven por obra, se compara
lo recibido contra el cronograma pactado y se muestra el superávit/déficit
por corte — para saber si el cliente va al día y si la obra tiene caja.
"""
from datetime import date

import pandas as pd
import streamlit as st

from lib import db, viz

st.set_page_config(page_title="Ingresos", page_icon="💵", layout="wide")
sb, uid = db.requiere_sesion()

st.title("💵 Ingresos y cumplimiento del cliente")

pr = db.proyectos(sb, uid)
if pr.empty:
    st.info("Crea un proyecto primero en Configuración.")
    st.stop()

nombres = {r["nombre"]: r["id"] for _, r in pr.iterrows()}
elegido = st.selectbox("Proyecto", list(nombres))
proyecto = pr[pr["id"] == nombres[elegido]].iloc[0]
pid = proyecto["id"]
puede = db.puede_editar(sb, uid)

anticipos = db.anticipos(sb, uid, pid)
cortes = db.cortes(sb, uid, pid)
hitos = db.hitos_proyecto(sb, uid, pid)
fx = db.facturas(sb, uid, proyecto_id=pid)
mov = db.movimientos_caja(sb, uid, pid)
pct_aiu = float(proyecto.get("pct_aiu") or 0)
proyecto_exento = bool(proyecto.get("exento_aiu"))

tabla_cf = db.cash_flow(fx, anticipos, mov, cortes, pct_aiu, proyecto_exento)
total_ing = anticipos["valor"].sum() if not anticipos.empty else 0.0
total_costo = float(tabla_cf.loc["total_egresos"].sum()) if not tabla_cf.empty else 0.0
caja = float(tabla_cf.loc["caja_final"].iloc[-1]) if not tabla_cf.empty else 0.0
cumpl = db.cumplimiento_cronograma(hitos, anticipos)

# ------------------------------------------------------------------ KPIs
c1, c2, c3, c4 = st.columns(4)
c1.metric("Ingresos recibidos", db.cop(total_ing))
c2.metric("Costo del proyecto", db.cop(total_costo))
c3.metric(
    "Superávit / Déficit", db.cop(caja),
    delta="con caja" if caja >= 0 else "en rojo", delta_color="normal" if caja >= 0 else "inverse",
)
if cumpl["cumplimiento_pct"] is not None:
    c4.metric("Cumplimiento del cronograma", f"{cumpl['cumplimiento_pct']:.0f}%",
              delta=f"faltan {db.cop(cumpl['pendiente'])}" if cumpl["pendiente"] else "al día")
else:
    c4.metric("Cumplimiento del cronograma", "—", help="Carga los abonos programados en Configuración → Cronograma.")

if caja < 0:
    st.warning("La obra está en **déficit**: lo abonado no cubre lo gastado hasta el último corte.")

st.divider()

# ------------------------------------------------ registrar ingreso (manual)
if puede:
    with st.expander("➕ Registrar un ingreso / abono del cliente", expanded=anticipos.empty):
        with st.form("nuevo_ingreso"):
            g1, g2, g3 = st.columns(3)
            fecha_i = g1.date_input("Fecha", value=date.today())
            corte_ops = {"— sin corte —": None} | {
                c["nombre"]: c["id"] for _, c in cortes.iterrows()
            } if not cortes.empty else {"— sin corte —": None}
            corte_i = g2.selectbox("Corte", list(corte_ops))
            modo_i = g3.selectbox("Modo de pago", list(db.MODOS_PAGO_INGRESO),
                                  format_func=lambda v: db.MODOS_PAGO_INGRESO[v])
            g4, g5 = st.columns([3, 1])
            detalle_i = g4.text_input("Detalle", placeholder="Ej: Transferencia RC 189")
            valor_i = g5.number_input("Total", min_value=0.0, step=100000.0)
            legal_i = st.selectbox("Encima / Debajo", db.opciones(db.LEGALIZACION),
                                   format_func=lambda v: db.etiqueta(db.LEGALIZACION, v) or "—")
            if st.form_submit_button("💾 Registrar ingreso") and valor_i > 0:
                sb.table("anticipos").insert({
                    "user_id": uid, "proyecto_id": pid,
                    "corte_id": corte_ops[corte_i], "fecha": str(fecha_i),
                    "valor": valor_i, "modo_pago": modo_i,
                    "detalle": detalle_i or None, "legalizacion": legal_i or None,
                }).execute()
                st.success("Ingreso registrado.")
                db.rerun()

# ------------------------------------------------------- ingresos por corte
if anticipos.empty:
    st.info("Aún no hay ingresos registrados para este proyecto.")
    st.stop()

nombre_corte = dict(zip(cortes["id"], cortes["nombre"])) if not cortes.empty else {}
ant = anticipos.assign(
    Corte=anticipos["corte_id"].map(nombre_corte).fillna("Sin corte"),
    Modo=anticipos["modo_pago"].map(lambda v: db.MODOS_PAGO_INGRESO.get(v, v)),
)

cL, cR = st.columns(2)
with cL:
    st.subheader("Ingresos por corte")
    por_corte = ant.groupby("Corte")["valor"].sum().sort_values()
    viz.barras(por_corte.index, por_corte.values, key="ing_corte", color=viz.COLOR_INGRESO,
               porcentaje=True)
with cR:
    st.subheader("Por modo de pago")
    por_modo = ant.groupby("Modo")["valor"].sum()
    viz.tabla_parte_del_todo(por_modo.index, por_modo.values, "Modo de pago")

# ------------------------------------------------ superávit / déficit por corte
st.subheader("Superávit / déficit por corte")
st.caption("Verde: en ese corte el cliente abonó más de lo gastado. Rojo: faltó. La línea es la caja acumulada.")
sd = db.superavit_por_corte(tabla_cf)
if not sd.empty:
    import plotly.graph_objects as go
    fig = go.Figure()
    fig.add_bar(
        x=sd["corte"], y=sd["resultado"],
        marker_color=[viz.COLOR_INGRESO if v >= 0 else viz.COLOR_GASTO for v in sd["resultado"]],
        text=[db.cop(v) for v in sd["resultado"]], textposition="outside", name="Resultado del corte",
    )
    fig.add_scatter(x=sd["corte"], y=sd["caja_acumulada"], mode="lines+markers",
                    name="Caja acumulada", line=dict(color=viz.COLOR_NEUTRO, width=2))
    fig.update_layout(height=380, yaxis_title="COP", margin=dict(t=30),
                      legend=dict(orientation="h", y=1.1), uniformtext_minsize=8, uniformtext_mode="hide")
    st.plotly_chart(fig, use_container_width=True)

# ------------------------------------------------ cumplimiento del cronograma
if cumpl["cumplimiento_pct"] is not None:
    st.subheader("Cumplimiento del cronograma de abonos")
    d1, d2, d3 = st.columns(3)
    d1.metric("Programado", db.cop(cumpl["programado"]))
    d2.metric("Recibido", db.cop(cumpl["recibido"]))
    d3.metric("Pendiente", db.cop(cumpl["pendiente"]))
    st.caption("Programado = abonos del cronograma (Configuración). Recibido = ingresos registrados aquí.")

st.divider()

# ------------------------------------------------------------- detalle editable
st.subheader("Ingresos registrados")
vista = ant[["fecha", "Corte", "detalle", "valor", "Modo", "legalizacion"]].rename(
    columns={"fecha": "Fecha", "detalle": "Detalle", "valor": "Total", "legalizacion": "Encima/Debajo"}
).sort_values("Fecha", ascending=False)
st.dataframe(vista.assign(Total=vista["Total"].map(db.cop)), use_container_width=True, hide_index=True)

if puede:
    with st.expander("🗑️ Eliminar un ingreso"):
        etiquetas = {
            f"{r['fecha']} · {db.cop(r['valor'])} · {db.texto(r.get('detalle'))[:30]}": r["id"]
            for _, r in anticipos.iterrows()
        }
        a_borrar = st.selectbox("Ingreso a eliminar", list(etiquetas))
        if st.button("Eliminar", type="secondary"):
            sb.table("anticipos").delete().eq("id", etiquetas[a_borrar]).execute()
            st.success("Eliminado.")
            db.rerun()
