import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib import db

st.set_page_config(page_title="Dashboard", page_icon="📈", layout="wide")
sb, uid = db.requiere_sesion()

st.title("📈 Gastos vs ingresos por proyecto")

pr = db.proyectos(sb, uid)
fx = db.facturas(sb, uid)
fx = fx[fx["estado"] != "anulada"] if not fx.empty else fx

nombres = ["Todos los proyectos"] + (pr["nombre"].tolist() if not pr.empty else [])
seleccion = st.radio("Proyecto", nombres, horizontal=True)
st.caption("El segmentador filtra todo lo que hay en esta página.")

if fx.empty:
    st.info("Sin datos todavía.")
    st.stop()

if seleccion != "Todos los proyectos":
    pid = pr.loc[pr["nombre"] == seleccion, "id"].iloc[0]
    fx = fx[fx["proyecto_id"] == pid]

fx = fx[fx["fecha_emision"].notna()].copy()
fx["mes"] = pd.to_datetime(fx["fecha_emision"]).dt.to_period("M").dt.to_timestamp()

serie = (
    fx.groupby(["mes", "sentido"])["monto_efectivo"].sum().unstack(fill_value=0).reset_index()
)
for col in ("gasto", "ingreso"):
    if col not in serie:
        serie[col] = 0

fig = go.Figure()
fig.add_trace(
    go.Scatter(x=serie["mes"], y=serie["gasto"], name="Gastos", mode="lines+markers",
               line=dict(color="#D85A30", width=2.5))
)
fig.add_trace(
    go.Scatter(x=serie["mes"], y=serie["ingreso"], name="Ingresos y abonos", mode="lines+markers",
               line=dict(color="#1D9E75", width=2.5, dash="dash"))
)
fig.update_layout(height=420, hovermode="x unified", yaxis_title="COP",
                  legend=dict(orientation="h", y=1.1))
st.plotly_chart(fig, use_container_width=True)
st.caption(
    "Línea continua: gastos del período (las notas crédito restan). Línea punteada: "
    "consignaciones y abonos del cliente. Si la punteada va por debajo, el proyecto "
    "está consumiendo caja de la empresa."
)

c1, c2, c3 = st.columns(3)
g, i = fx[fx["sentido"] == "gasto"]["monto_efectivo"].sum(), fx[fx["sentido"] == "ingreso"]["monto_efectivo"].sum()
c1.metric("Gastos", db.cop(g))
c2.metric("Ingresos", db.cop(i))
c3.metric("Saldo", db.cop(i - g))

st.divider()
st.subheader("Gastos por proyecto")
if not pr.empty:
    por_p = (
        fx[fx["sentido"] == "gasto"]
        .merge(pr[["id", "nombre"]], left_on="proyecto_id", right_on="id", how="left")
        .fillna({"nombre": "Sin asignar"})
        .groupby("nombre")["monto_efectivo"]
        .sum()
        .sort_values()
    )
    fig2 = go.Figure(go.Bar(x=por_p.values, y=por_p.index, orientation="h", marker_color="#D85A30"))
    fig2.update_layout(height=max(200, 40 * len(por_p)), xaxis_title="COP")
    st.plotly_chart(fig2, use_container_width=True)
    st.caption("Costo acumulado por obra. 'Sin asignar' es lo que espera revisión: idealmente cero.")

st.subheader("Gastos por tipo")
tg = db.tipos_gasto(sb, uid)
if not tg.empty:
    por_t = (
        fx[fx["sentido"] == "gasto"]
        .merge(tg[["id", "nombre"]], left_on="tipo_gasto_id", right_on="id", how="left")
        .fillna({"nombre": "Sin clasificar"})
        .groupby("nombre")["monto_efectivo"]
        .sum()
        .sort_values(ascending=False)
    )
    st.dataframe(por_t.map(db.cop), use_container_width=True)
