import streamlit as st

from lib import db

sb, uid = db.requiere_sesion()

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
    # Ingresos = abonos del cliente (anticipos) + ingresos registrados como factura.
    anticipos_all = db.anticipos(sb, uid)
    ingresos = fx[fx["sentido"] == "ingreso"]["monto_efectivo"].sum() + (
        float(anticipos_all["valor"].sum()) if not anticipos_all.empty else 0.0
    )
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
El menú de la izquierda está organizado por lo que vas a hacer:

- **📥 Registro** — clasificar lo que llega, ver todas las facturas, registrar ingresos e importar matrices.
- **📊 Reportes** — Dashboard, Cash Flow del proyecto, Flujo semanal y Compromisos futuros.
- **💰 Tesorería** — Cuentas por pagar y el Estado de cuenta para el cliente.
- **⚙️ Administración** — Configuración (proyectos, capítulos, retención, UVT) y Usuarios.

¿Primera vez o alguna duda? Abre **❓ Manual de usuario** al final del menú: explica cada módulo paso a paso.
"""
)
