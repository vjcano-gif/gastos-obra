"""Compromisos futuros: vencimientos por pagar vs ingresos previstos.

Mira N meses hacia adelante y responde si lo que se va a cobrar (los abonos
programados del cronograma) alcanza para cubrir lo que hay que pagar (los
vencimientos de las cuentas por pagar). Lo vencido y lo posterior al horizonte
se muestran aparte para no esconder nada.
"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib import db, viz

st.set_page_config(page_title="Compromisos futuros", page_icon="📆", layout="wide")
sb, uid = db.requiere_sesion()

st.title("📆 Compromisos futuros")
st.caption(
    "Lo que hay que pagar (vencimientos de cuentas por pagar) contra lo que se "
    "debería cobrar (abonos programados en el cronograma), mes a mes."
)

pr = db.proyectos(sb, uid)

c1, c2 = st.columns([3, 1])
with c1:
    _, pid = viz.selector_proyecto(pr, key="comp_proy")
with c2:
    meses = st.slider("Meses hacia adelante", 1, 12, 3)

# --- EGRESOS comprometidos: saldo pendiente por su fecha de vencimiento
fx = db.facturas(sb, uid, sentido="gasto")
if pid is not None and not fx.empty:
    fx = fx[fx["proyecto_id"] == pid]
pend = db.con_saldo_pendiente(fx)
if not pend.empty:
    egresos = pd.DataFrame({
        "fecha": pd.to_datetime(pend["fecha_vencimiento"].fillna(pend["fecha_emision"]), errors="coerce"),
        "valor": pend["saldo_pend"],
    })
else:
    egresos = pd.DataFrame(columns=["fecha", "valor"])

# --- INGRESOS previstos: abonos del cronograma aún no cumplidos
hitos = db.hitos_proyecto(sb, uid, pid)
if not hitos.empty:
    abonos = hitos[(hitos["tipo"] == "abono") & (~hitos["cumplido"].fillna(False))]
    ingresos = pd.DataFrame({
        "fecha": pd.to_datetime(abonos["fecha"], errors="coerce"),
        "valor": pd.to_numeric(abonos["monto"], errors="coerce").fillna(0),
    })
    ingresos = ingresos[ingresos["valor"] > 0]
else:
    ingresos = pd.DataFrame(columns=["fecha", "valor"])

proy = db.proyeccion_compromisos(egresos, ingresos, meses=meses)

if proy.empty:
    st.info("No hay compromisos ni ingresos previstos que proyectar en este proyecto.")
    st.stop()

# --- KPIs (todo lo proyectado que se muestra abajo)
tot_ing = float(proy["ingresos_previstos"].sum())
tot_eg = float(proy["egresos_comprometidos"].sum())
brecha = tot_ing - tot_eg
k1, k2, k3 = st.columns(3)
k1.metric("Ingresos previstos", db.cop(tot_ing))
k2.metric("Egresos comprometidos", db.cop(tot_eg))
k3.metric("Brecha", db.cop(brecha), delta="con holgura" if brecha >= 0 else "faltante",
          delta_color="normal" if brecha >= 0 else "inverse")

if ingresos.empty:
    st.warning(
        "Este proyecto no tiene abonos programados en el cronograma, así que los "
        "ingresos previstos salen en cero. Cárgalos en **Configuración → Cronograma** "
        "para poder compararlos contra los vencimientos."
    )

# --- gráfica: barras agrupadas por mes + línea de caja proyectada acumulada
st.subheader("Ingresos previstos vs egresos comprometidos")


def _lbl(v):
    v = float(v or 0)
    return f"{v / 1e6:.1f}M" if abs(v) >= 1e6 else (f"{v / 1e3:.0f}k" if v else "")


fig = go.Figure()
fig.add_bar(x=proy["periodo"], y=proy["ingresos_previstos"], name="Ingresos previstos",
            marker_color=viz.COLOR_INGRESO, text=[_lbl(v) for v in proy["ingresos_previstos"]],
            textposition="outside")
fig.add_bar(x=proy["periodo"], y=proy["egresos_comprometidos"], name="Egresos comprometidos",
            marker_color=viz.COLOR_GASTO, text=[_lbl(v) for v in proy["egresos_comprometidos"]],
            textposition="outside")
fig.add_scatter(x=proy["periodo"], y=proy["acumulado"], name="Caja proyectada (acumulada)",
                mode="lines+markers", line=dict(color=viz.COLOR_NEUTRO, width=2))
fig.update_layout(barmode="group", height=430, yaxis_title="COP",
                  legend=dict(orientation="h", y=1.12), margin=dict(t=30),
                  hovermode="x unified", uniformtext_minsize=8, uniformtext_mode="hide")
st.plotly_chart(fig, use_container_width=True)
st.caption(
    "La línea es la caja proyectada acumulada: si cae por debajo de cero en algún "
    "mes, ahí es donde los pagos superan a los cobros previstos."
)

# --- tabla
st.subheader("Detalle por periodo")
tabla = proy.rename(columns={
    "periodo": "Periodo", "ingresos_previstos": "Ingresos previstos",
    "egresos_comprometidos": "Egresos comprometidos", "neto": "Neto",
    "acumulado": "Caja acumulada",
})
cols_cop = ["Ingresos previstos", "Egresos comprometidos", "Neto", "Caja acumulada"]
st.dataframe(
    tabla.style.format({c: db.cop for c in cols_cop}),
    use_container_width=True, hide_index=True,
)
