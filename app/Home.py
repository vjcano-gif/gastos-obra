import streamlit as st

from lib import db

st.set_page_config(page_title="Gastos de obra", page_icon="🏗️", layout="wide")

sb, uid = db.requiere_sesion()
db.sembrar_si_vacio(sb, uid)
db.sembrar_capitulos_si_vacio(sb, uid)

st.title("🏗️ Control de gastos e ingresos por proyecto")

fx = db.facturas(sb, uid)
pr = db.proyectos(sb, uid)

c1, c2, c3, c4 = st.columns(4)
if fx.empty:
    st.info(
        "Aún no hay documentos. El barrido del buzón corre cada 6 horas; "
        "también puedes registrar movimientos manuales en **Revisión**."
    )
else:
    gastos = fx[fx["sentido"] == "gasto"]["monto_efectivo"].sum()
    ingresos = fx[fx["sentido"] == "ingreso"]["monto_efectivo"].sum()
    pendientes = fx[(fx["sentido"] == "gasto") & (~fx["estado"].isin(["pagada", "anulada"]))]
    c1.metric("Gastos acumulados", db.cop(gastos))
    c2.metric("Ingresos acumulados", db.cop(ingresos))
    c3.metric("Por pagar", db.cop(pendientes["monto_efectivo"].sum()))
    c4.metric("Proyectos activos", int((pr["estado"] == "activo").sum()) if not pr.empty else 0)

    sin_revisar = int((fx["estado"] == "extraida").sum())
    if sin_revisar:
        st.warning(f"📋 Hay **{sin_revisar}** documentos esperando revisión y asignación de proyecto.")

st.markdown(
    """
**Rutas rápidas**
- 📋 **Revisión** — asignar proyecto, tipo de gasto y método de pago a lo que llegó.
- 🗂️ **Todas las facturas** — ver y corregir el universo completo, con filtros y segmentador de fechas.
- 📈 **Dashboard** — gastos vs ingresos por mes, con segmentador por proyecto.
- 💳 **Cuentas por pagar** — vencimientos, saldos y registro de abonos.
- ✉️ **Estado de cuenta** — informe del proyecto listo para enviar al cliente.
- ⚙️ **Configuración** — proyectos, tipos de gasto, reglas de retención y UVT.
- 👥 **Usuarios** — invitar o quitar personas del equipo (solo el dueño la ve).
"""
)
