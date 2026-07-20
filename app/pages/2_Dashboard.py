import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib import db, viz

st.set_page_config(page_title="Dashboard", page_icon="📈", layout="wide")
sb, uid = db.requiere_sesion()

st.title("📈 Gastos vs ingresos por proyecto")

pr = db.proyectos(sb, uid)
fx = db.facturas(sb, uid)
fx = fx[fx["estado"] != "anulada"] if not fx.empty else fx

# --- selector de proyecto en lista desplegable (no radio: aguanta cientos)
_, pid = viz.selector_proyecto(pr, key="dash_proy")
if pid is not None and not fx.empty:
    fx = fx[fx["proyecto_id"] == pid]

if fx.empty:
    st.info("Sin datos todavía.")
    st.stop()

# --- detalle por artículo, respetando el reparto multiproyecto
detalle = db.detalle_clasificado(fx, db.todos_los_items(sb, uid))
detalle = db.aplicar_asignaciones(detalle, db.asignaciones(sb, uid))
detalle_gasto = detalle[detalle["sentido"] == "gasto"] if not detalle.empty else detalle

# Los INGRESOS del proyecto son los abonos del cliente (tabla `anticipos`, la
# "matriz de ingresos") MÁS cualquier ingreso registrado como factura. Antes
# solo se contaban las facturas sentido=ingreso, así que una obra con abonos
# —como Arrayanes 40— aparecía en $0 aunque el cliente ya hubiera consignado.
anticipos = db.anticipos(sb, uid, pid)

cap = db.capitulos(sb, uid)
act = db.actividades(sb, uid)

# --- métricas: SIEMPRE a nivel de proyecto (el filtro cruzado no las toca;
# afecta las gráficas de abajo, que es lo que se quiere drill-down).
gasto_total = detalle_gasto["valor"].sum() if not detalle_gasto.empty else 0
ingreso_fac = detalle[detalle["sentido"] == "ingreso"]["valor"].sum() if not detalle.empty else 0
ingreso_ant = (
    float(pd.to_numeric(anticipos["valor"], errors="coerce").fillna(0).sum())
    if not anticipos.empty else 0.0
)
ingreso_total = ingreso_fac + ingreso_ant
m1, m2, m3 = st.columns(3)
m1.metric("Gastos", db.cop(gasto_total))
m2.metric("Ingresos", db.cop(ingreso_total),
          help="Abonos del cliente (matriz de ingresos) más ingresos registrados como factura.")
m3.metric("Saldo", db.cop(ingreso_total - gasto_total))

# --- FILTRO CRUZADO: el capítulo clicado (en la gráfica de abajo) filtra
# las demás gráficas. Se lee al inicio del rerun para filtrar antes de
# dibujar. Los ingresos NO se filtran por capítulo (no se clasifican así).
foco_cap = viz.foco_actual("dash_cap")
detalle_foco = detalle_gasto
if foco_cap and not detalle_gasto.empty and not cap.empty:
    ids_cap = set(cap.loc[cap["nombre"] == foco_cap, "id"])
    detalle_foco = detalle_gasto[detalle_gasto["capitulo_id"].isin(ids_cap)]
    parte = detalle_foco["valor"].sum()
    pct = parte / gasto_total * 100 if gasto_total else 0
    c1, c2 = st.columns([4, 1])
    c1.info(f"🔎 Filtrando por capítulo: **{foco_cap}** — {db.cop(parte)} ({pct:.1f}% del gasto)")
    if c2.button("Quitar filtro"):
        st.session_state.pop("dash_cap", None)
        db.rerun()

# --- serie mensual gastos vs ingresos (área + etiquetas), desde el detalle
# a nivel de artículo: los gastos respetan el filtro cruzado, los ingresos no.
def _por_mes(d: pd.DataFrame, col_fecha: str = "fecha_emision", col_valor: str = "valor") -> pd.Series:
    if d is None or d.empty or col_fecha not in d or col_valor not in d:
        return pd.Series(dtype=float)
    d = d.copy()
    d["_f"] = pd.to_datetime(d[col_fecha], errors="coerce")
    d = d[d["_f"].notna()]
    d["_mes"] = d["_f"].dt.to_period("M").dt.to_timestamp()
    return d.groupby("_mes")[col_valor].sum()

if not detalle.empty:
    gasto_mes = _por_mes(detalle_foco)
    # Ingresos por mes = facturas-ingreso (fecha de emisión) + abonos del
    # cliente (su propia fecha de consignación). `add` alinea los meses.
    ing_mes = _por_mes(detalle[detalle["sentido"] == "ingreso"]).add(
        _por_mes(anticipos, col_fecha="fecha"), fill_value=0
    )
    meses = sorted(set(gasto_mes.index) | set(ing_mes.index))
    serie = pd.DataFrame({
        "mes": meses,
        "gasto": [gasto_mes.get(m, 0) for m in meses],
        "ingreso": [ing_mes.get(m, 0) for m in meses],
    })

    def _compacto(v):
        v = float(v or 0)
        return f"{v/1e6:.0f}M" if abs(v) >= 1e6 else (f"{v/1e3:.0f}k" if v else "")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=serie["mes"], y=serie["gasto"], name="Gastos", mode="lines+markers+text",
        text=[_compacto(v) for v in serie["gasto"]], textposition="top center",
        fill="tozeroy", line=dict(color=viz.COLOR_GASTO, width=2.5),
    ))
    fig.add_trace(go.Scatter(
        x=serie["mes"], y=serie["ingreso"], name="Ingresos y abonos", mode="lines+markers",
        line=dict(color=viz.COLOR_INGRESO, width=2.5, dash="dash"),
    ))
    fig.update_layout(height=420, hovermode="x unified", yaxis_title="COP",
                      legend=dict(orientation="h", y=1.12), margin=dict(t=30))
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "Área: gastos del período (las notas crédito restan). Línea punteada: "
        "consignaciones y abonos del cliente. Si la punteada va por debajo, el "
        "proyecto está consumiendo caja de la empresa."
    )

st.divider()

# La clasificación del negocio es por PROYECTO, CAPÍTULO y ACTIVIDAD. Cada
# barra es una proporción del gasto total, así que lleva su % (regla de la
# app). Todas reaccionan al filtro cruzado por capítulo.

# --- gastos por proyecto (solo cuando se ven todos)
if pid is None:
    st.subheader("Gastos por proyecto")
    por_p = viz.por_dimension(detalle_foco, pr, "proyecto_id", "Sin asignar").sort_values(ascending=False)
    if not por_p.empty:
        viz.barras(por_p.index, por_p.values, key="dash_proy_bar", porcentaje=True)
        st.caption(
            "Costo por obra a nivel de artículo, respetando el reparto multiproyecto. "
            "'Sin asignar' espera revisión: idealmente cero."
        )

c_cap, c_act = st.columns(2)
with c_cap:
    st.subheader("Gastos por capítulo")
    st.caption("Haz clic en un capítulo para filtrar la página; clic de nuevo para quitarlo.")
    # DRIVER del filtro cruzado: siempre muestra TODOS los capítulos (sin
    # el foco) para poder elegir/cambiar. Con % del total.
    por_c = viz.por_dimension(detalle_gasto, cap, "capitulo_id").sort_values(ascending=True)
    if not por_c.empty:
        viz.barras(por_c.index, por_c.values, key="dash_cap",
                   seleccionable=True, resaltado=foco_cap, porcentaje=True)

with c_act:
    st.subheader("Gastos por actividad")
    por_a = viz.por_dimension(detalle_foco, act, "actividad_id").sort_values(ascending=False)
    if not por_a.empty:
        # Tabla con %: suelen ser muchas actividades y una tabla ordenada
        # se lee mejor que 50 barras.
        viz.tabla_parte_del_todo(por_a.index, por_a.values, "Actividad")
    else:
        st.caption("Sin gasto clasificado por actividad en este filtro.")

st.caption(
    "La clasificación por capítulo y actividad se calcula por artículo, no por "
    "factura completa — más preciso cuando una compra mezcla varios rubros."
)
