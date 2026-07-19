from datetime import date

import pandas as pd
import streamlit as st

from lib import db

st.set_page_config(page_title="Cuentas por pagar", page_icon="💳", layout="wide")
sb, uid = db.requiere_sesion()

st.title("💳 Cuentas por pagar")

fx = db.facturas(sb, uid, sentido="gasto")
if fx.empty:
    st.info("Sin facturas registradas.")
    st.stop()

pend = fx[~fx["estado"].isin(["pagada", "anulada"])].copy()
pagos = db.df(sb.table("pagos").select("*").eq("user_id", uid).execute())
abonado = pagos.groupby("factura_id")["monto"].sum() if not pagos.empty else pd.Series(dtype=float)
pend["abonado"] = pend["id"].map(abonado).fillna(0)
pend["saldo"] = pend["monto_efectivo"] - pend["abonado"]
pend = pend[pend["saldo"] > 0]

hoy = pd.Timestamp(date.today())
venc = pd.to_datetime(pend["fecha_vencimiento"].fillna(pend["fecha_emision"]))
pend["dias"] = (venc - hoy).dt.days


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
        return "Vence en 15 días"
    return "Al día"


pend["antiguedad"] = pend["dias"].map(rango)

c1, c2, c3 = st.columns(3)
c1.metric("Total por pagar", db.cop(pend["saldo"].sum()))
c2.metric("Vencido", db.cop(pend.loc[pend["dias"] < 0, "saldo"].sum()))
c3.metric("Facturas pendientes", len(pend))

st.subheader("Antigüedad de saldos")
st.dataframe(
    pend.groupby("antiguedad")["saldo"].agg(["count", "sum"]).rename(
        columns={"count": "facturas", "sum": "saldo"}
    ).assign(saldo=lambda d: d["saldo"].map(db.cop)),
    use_container_width=True,
)

st.subheader("Detalle y registro de pagos")
for _, f in pend.sort_values("dias").head(80).iterrows():
    marca = "🔴" if f["dias"] < 0 else ("🟡" if f["dias"] <= 15 else "🟢")
    with st.expander(
        f"{marca} vence {f.get('fecha_vencimiento') or 's.f.'} · "
        f"{(f.get('proveedor_nombre') or '')[:40]} · saldo {db.cop(f['saldo'])}"
    ):
        st.caption(
            f"Total {db.cop(f['monto_efectivo'])} · abonado {db.cop(f['abonado'])} · "
            f"factura {f.get('numero') or ''}"
        )
        with st.form(f"pago_{f['id']}"):
            c1, c2, c3 = st.columns(3)
            fecha_p = c1.date_input("Fecha del pago", value=date.today())
            monto = c2.number_input(
                "Monto", min_value=0.0, max_value=float(f["saldo"]), value=float(f["saldo"]), step=1000.0
            )
            medio = c3.selectbox("Medio", ["transferencia", "TC", "TD", "efectivo", "cheque"])
            if st.form_submit_button("💾 Registrar pago"):
                sb.table("pagos").insert(
                    {
                        "user_id": uid,
                        "factura_id": f["id"],
                        "fecha": str(fecha_p),
                        "monto": monto,
                        "medio": medio,
                    }
                ).execute()
                if monto >= f["saldo"]:
                    sb.table("facturas").update({"estado": "pagada"}).eq("id", f["id"]).execute()
                db.rerun()
