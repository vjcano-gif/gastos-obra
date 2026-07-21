"""Obligaciones pendientes y bases del negocio.

Reproduce los tableros SEGUI del Excel y responde las preguntas del
usuario:
  - ¿Qué facturas tengo pendientes? ¿A quién le debo? ¿Cuánto? ¿Desde
    cuándo?  -> secciones "por proveedor / por proyecto / antigüedad".
  - ¿Cuál es la base de mi comisión? ¿La base de lo que debo pagar? ¿Qué %
    de retención aplico?  -> sección "Bases del negocio".
"""
from datetime import date

import pandas as pd
import streamlit as st

from lib import db, viz

sb, uid = db.requiere_sesion()

st.title("💳 Obligaciones y bases del negocio")

fx = db.facturas(sb, uid, sentido="gasto")
if fx.empty:
    st.info("Sin facturas registradas.")
    st.stop()

pr = db.proyectos(sb, uid)
nombre_pr = dict(zip(pr["id"], pr["nombre"])) if not pr.empty else {}

# --- filtro por proyecto (lista desplegable, aguanta cientos de obras)
_, pid_filtro = viz.selector_proyecto(pr, key="cpp_proy")
if pid_filtro is not None:
    fx = fx[fx["proyecto_id"] == pid_filtro]

# --- deuda: saldo de la matriz si existe, si no estado_pago (helper probado)
pend = db.con_saldo_pendiente(fx)
# abonos registrados en la app restan del saldo
pagos = db.df(sb.table("pagos").select("*").eq("user_id", uid).execute())
if not pend.empty and not pagos.empty:
    abonado = pagos.groupby("factura_id")["monto"].sum()
    pend["saldo_pend"] = (pend["saldo_pend"] - pend["id"].map(abonado).fillna(0)).clip(lower=0)
    pend = pend[pend["saldo_pend"] > 0]

st.caption(
    "Refleja el estado de pago actual (saldo de la matriz + abonos en la app). "
    "Las facturas de correo aún sin conciliar no aparecen hasta que tengan estado de pago."
)

if pend.empty:
    st.success("No hay saldos pendientes registrados. 🎉")
    st.stop()

hoy = pd.Timestamp(date.today())
venc = pd.to_datetime(pend["fecha_vencimiento"].fillna(pend["fecha_emision"]), errors="coerce")
pend["dias"] = (venc - hoy).dt.days
pend["proyecto"] = pend["proyecto_id"].map(nombre_pr).fillna("Sin asignar")

# ------------------------------------------------------------------ KPIs
total = pend["saldo_pend"].sum()
vencido = pend.loc[pend["dias"] < 0, "saldo_pend"].sum()
c1, c2, c3 = st.columns(3)
c1.metric("Total por pagar", db.cop(total))
c2.metric("Vencido", db.cop(vencido), delta=f"{vencido / total * 100:.0f}% del total" if total else None,
          delta_color="inverse")
c3.metric("Facturas pendientes", len(pend))

st.divider()

# ---------------------------------------- ¿a quién le debo? (SEGUI proveedor)
st.subheader("¿A quién le debo?")
por_prov = (
    pend.assign(proveedor=pend["proveedor_nombre"].map(lambda v: db.texto(v, "Sin proveedor")))
    .groupby("proveedor")
    .agg(saldo=("saldo_pend", "sum"), facturas=("id", "count"),
         desde=("fecha_emision", "min"))
    .sort_values("saldo", ascending=False)
    .reset_index()
)
por_prov["% del total"] = (por_prov["saldo"] / total * 100).map(lambda p: f"{p:.1f}%")
por_prov["Saldo"] = por_prov["saldo"].map(db.cop)
st.dataframe(
    por_prov[["proveedor", "Saldo", "% del total", "facturas", "desde"]].rename(
        columns={"proveedor": "Proveedor", "facturas": "N.° facturas", "desde": "Debo desde"}
    ),
    use_container_width=True, hide_index=True,
)

cA, cB = st.columns(2)
with cA:
    st.subheader("Por proyecto")
    por_proy = pend.groupby("proyecto")["saldo_pend"].sum().sort_values()
    viz.barras(por_proy.index, por_proy.values, key="cpp_proy", porcentaje=True)
with cB:
    st.subheader("Antigüedad de la deuda")
    def rango(d):
        if pd.isna(d):
            return "Sin fecha"
        if d < -60:
            return "Vencida +60 días"
        if d < -30:
            return "Vencida 31-60"
        if d < 0:
            return "Vencida 1-30"
        if d <= 15:
            return "Vence ≤ 15 días"
        return "Al día"
    orden = ["Vencida +60 días", "Vencida 31-60", "Vencida 1-30", "Vence ≤ 15 días", "Al día", "Sin fecha"]
    ant = pend.assign(a=pend["dias"].map(rango)).groupby("a")["saldo_pend"].sum()
    ant = ant.reindex([o for o in orden if o in ant.index])
    viz.barras(ant.index, ant.values, key="cpp_aging", color=viz.COLOR_GASTO, porcentaje=True)

st.divider()

# ------------------------------------------------ Bases del negocio (comisión, retención)
st.subheader("💼 Bases del negocio")
# Reusa `fx` (ya filtrado por proyecto): las bases responden al mismo filtro.
gasto_all = fx
base_com = 0.0
if not gasto_all.empty:
    exento = gasto_all.get("exento_aiu", pd.Series([False] * len(gasto_all)))
    base_com = pd.to_numeric(gasto_all["total"], errors="coerce").fillna(0).where(~exento.astype(bool), 0).sum()
comision = pd.to_numeric(gasto_all.get("comision_aiu", 0), errors="coerce").fillna(0).sum() if not gasto_all.empty else 0
ret_total = (
    pd.to_numeric(gasto_all.get("rete_fuente", 0), errors="coerce").fillna(0)
    + pd.to_numeric(gasto_all.get("rete_iva", 0), errors="coerce").fillna(0)
    + pd.to_numeric(gasto_all.get("rete_ica", 0), errors="coerce").fillna(0)
).sum() if not gasto_all.empty else 0
subtotal = pd.to_numeric(gasto_all["total"], errors="coerce").fillna(0).sum() if not gasto_all.empty else 0

b1, b2, b3, b4 = st.columns(4)
b1.metric("Base de comisión", db.cop(base_com), help="Costo no exento de AIU sobre el que se cobra la comisión.")
b2.metric("Comisión (AIU)", db.cop(comision))
b3.metric("Retenciones aplicadas", db.cop(ret_total),
          delta=f"{ret_total / subtotal * 100:.1f}% del costo" if subtotal else None)
b4.metric("Base a pagar (neto retención)", db.cop(subtotal - ret_total))
st.caption(
    "La retención se le retiene al proveedor y se gira a la DIAN: baja lo que debo pagar, "
    "no el costo del proyecto ni la base de la comisión."
)

st.divider()

# ------------------------------------------- detalle + registro de pagos
st.subheader("Detalle y registro de pagos")
st.caption(
    "Al registrar un pago se anota el comprobante y la fecha, se acumula en "
    "'Valor pagado' y la factura pasa a **parcial** o **pagada** según cubra el saldo."
)
puede = db.puede_editar(sb, uid)
# Lo ya abonado por factura (de la tabla `pagos`), para acumular valor_pagado.
abonado_por_factura = (
    pagos.groupby("factura_id")["monto"].sum() if not pagos.empty else pd.Series(dtype=float)
)
for _, f in pend.sort_values("dias").head(80).iterrows():
    marca = "🔴" if f["dias"] < 0 else ("🟡" if f["dias"] <= 15 else "🟢")
    with st.expander(
        f"{marca} vence {db.texto(f.get('fecha_vencimiento'), 's.f.')} · "
        f"{db.texto(f.get('proveedor_nombre'), 'Sin proveedor')[:40]} · N.° {db.texto(f.get('numero'), 's.n.')} · "
        f"saldo {db.cop(f['saldo_pend'])}"
    ):
        st.caption(f"{f['proyecto']} · total factura {db.cop(f['total'])}")
        ya_abonado = float(abonado_por_factura.get(f["id"], 0) or 0)
        if ya_abonado:
            st.caption(f"Abonado hasta ahora: {db.cop(ya_abonado)}")
        if puede:
            with st.form(f"pago_{f['id']}"):
                cpa, cpb = st.columns(2)
                monto = cpa.number_input("Registrar pago/abono", min_value=0.0,
                                         max_value=float(f["saldo_pend"]), value=float(f["saldo_pend"]), step=1000.0)
                fecha_p = cpb.date_input("Fecha del pago", value=date.today())
                cpc, cpd = st.columns(2)
                comprobante = cpc.text_input("Comprobante / soporte N.º",
                                             placeholder="Ej: transferencia 12345, RC 189")
                medio_ops = db.opciones(db.METODOS_PAGO)
                medio = cpd.selectbox("Medio de pago", medio_ops,
                                      format_func=lambda v: db.etiqueta(db.METODOS_PAGO, v) or "—")
                if st.form_submit_button("💾 Registrar pago") and monto > 0:
                    sb.table("pagos").insert({
                        "user_id": uid, "factura_id": f["id"],
                        "monto": monto, "fecha": str(fecha_p),
                        "medio": medio or None, "notas": comprobante or None,
                    }).execute()
                    # Acumula lo pagado y sella la fecha; marca parcial/pagada.
                    upd = {
                        "valor_pagado": round(ya_abonado + monto, 2),
                        "fecha_pago": str(fecha_p),
                    }
                    if monto >= f["saldo_pend"]:
                        upd["estado_pago"] = "pagada"
                        upd["saldo"] = 0
                    else:
                        upd["estado_pago"] = "parcial"
                    sb.table("facturas").update(upd).eq("id", f["id"]).execute()
                    st.success("Pago registrado.")
                    db.rerun()
