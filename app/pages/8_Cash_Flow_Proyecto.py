"""Cash flow y control de costos de UN proyecto.

Es el modulo que ve el cliente de la obra: el equivalente a su archivo
"Cash Flow Casa Vieja 61" (hojas Portada y Cash flow). Independiente del
resto de la app a proposito — un usuario con rol 'cliente' entra aqui,
ve SU obra y nada mas: ni proveedores, ni facturas individuales, ni las
otras obras. Eso lo garantiza el RLS de la migracion 016, no esta
pantalla; aqui solo se evita mostrar lo que ademas no debe pedirse.
"""
from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st

from lib import db, informe_pdf, viz

st.set_page_config(page_title="Cash Flow del proyecto", page_icon="💧", layout="wide")
sb, uid = db.requiere_sesion()

st.title("💧 Cash flow y costos del proyecto")

rol = db.mi_rol(sb, uid)
pr = db.proyectos(sb, uid)

if pr.empty:
    st.info("Todavía no hay proyectos. Créalos en Configuración.")
    st.stop()

# Un cliente tiene un solo proyecto visible: no se le muestra un selector
# con obras que de todas formas no podría abrir.
if rol == "cliente" and len(pr) == 1:
    proyecto = pr.iloc[0]
    st.subheader(f"🏠 {proyecto['nombre']}")
else:
    nombres = {r["nombre"]: r["id"] for _, r in pr.iterrows()}
    elegido = st.selectbox("Proyecto", list(nombres))
    proyecto = pr[pr["id"] == nombres[elegido]].iloc[0]

proyecto_id = proyecto["id"]
pct_aiu = float(proyecto.get("pct_aiu") or 0)
proyecto_exento = bool(proyecto.get("exento_aiu"))

cortes = db.cortes(sb, uid, proyecto_id)
anticipos = db.anticipos(sb, uid, proyecto_id)
movimientos = db.movimientos_caja(sb, uid, proyecto_id)

# El cliente no puede leer `facturas` (el RLS se lo impide), así que su
# costo llega ya sumado desde la función costo_por_capitulo().
if rol == "cliente":
    facturas = pd.DataFrame()
    costos = db.costo_por_capitulo(sb, proyecto_id)
else:
    # El filtro por proyecto va a la base: baja solo las facturas de esta
    # obra, no las miles del workspace para descartarlas en pandas.
    facturas = db.facturas(sb, uid, proyecto_id=proyecto_id)
    costos = None

# ------------------------------------------------------------ encabezado
tabla = db.cash_flow(facturas, anticipos, movimientos, cortes, pct_aiu, proyecto_exento)

total_ingresos = float(tabla.loc["anticipos"].sum())
total_costos = float(tabla.loc["total_egresos"].sum())
caja = float(tabla.loc["caja_final"].iloc[-1]) if not tabla.empty else 0.0
aiu_total = float(tabla.loc["aiu_gastos"].sum() + tabla.loc["aiu_pagos_directos"].sum())

c1, c2, c3, c4 = st.columns(4)
c1.metric("Anticipos del cliente", db.cop(total_ingresos))
c2.metric("Total costos", db.cop(total_costos))
c3.metric(f"Comisión AIU ({pct_aiu:.0%})", db.cop(aiu_total))
c4.metric("Caja del proyecto", db.cop(caja), delta=None if caja >= 0 else "en rojo")

if caja < 0:
    st.warning(
        "La caja del proyecto está en negativo: se ha gastado más de lo que "
        "el cliente ha abonado hasta este corte."
    )

st.divider()

# -------------------------------------------------------------- cash flow
st.subheader("Cash flow por corte")
st.caption(
    "El saldo final de cada corte es el inicial del siguiente. Los pagos "
    "directos del cliente suman al costo de la obra y generan comisión, "
    "pero no salen de la caja de Espacios: por eso están fuera del subtotal."
)

ETIQUETAS = {
    "caja_inicial": "Saldo inicial de caja",
    "anticipos": "Anticipos del cliente",
    "anticipos_bancos": "   · Bancos",
    "anticipos_efectivo": "   · Efectivo",
    "gastos": "1. Gastos",
    "aiu_gastos": "2. AIU gastos",
    "aiu_pagos_directos": "3. AIU pagos directos",
    "gmf": "4. GMF 4x1000",
    "otros_gastos": "5. Otros gastos",
    "subtotal": "Subtotal (sale de caja)",
    "pagos_directos": "Pagos directos del cliente",
    "pagos_exentos": "Otros pagos exentos",
    "total_egresos": "Total egresos",
    "caja_final": "Saldo en caja",
}

vista = tabla.reindex(list(ETIQUETAS)).rename(index=ETIQUETAS)
st.dataframe(
    vista.style.format(db.cop).apply(
        lambda fila: [
            "font-weight:bold" if fila.name in ("Saldo en caja", "Total egresos") else ""
            for _ in fila
        ],
        axis=1,
    ),
    use_container_width=True,
)

acumulado = pd.DataFrame(
    {
        "Anticipos acumulados": tabla.loc["anticipos"].cumsum(),
        "Costos acumulados": tabla.loc["total_egresos"].cumsum(),
        "Caja": tabla.loc["caja_final"],
    }
)
st.plotly_chart(
    px.line(acumulado, markers=True, labels={"value": "Pesos", "index": "Corte"}),
    use_container_width=True,
)

st.divider()

# ---------------------------------------------------------------- portada
st.subheader("Costo por capítulo y corte")
st.caption("Equivale a la hoja Portada: en qué se ha ido la plata de la obra.")

if rol == "cliente":
    detalle = costos
else:
    detalle = db.costo_por_capitulo_local(sb, uid, proyecto_id, facturas, cortes)

if detalle is None or detalle.empty:
    st.info(
        "Todavía no hay costos clasificados por capítulo en este proyecto. "
        "Se llenan al clasificar las facturas en Revisión."
    )
else:
    matriz = detalle.pivot_table(
        index="capitulo", columns="corte", values="total", aggfunc="sum", fill_value=0
    )
    matriz["Total"] = matriz.sum(axis=1)
    matriz = matriz.sort_values("Total", ascending=False)
    total_general = matriz["Total"].sum() or 1
    matriz["Part. %"] = matriz["Total"] / total_general * 100

    st.dataframe(
        matriz.style.format({**{c: db.cop for c in matriz.columns if c != "Part. %"},
                             "Part. %": "{:.1f}%"}),
        use_container_width=True,
    )
    # Barras con etiqueta de dato (no px sin etiqueta), de menor a mayor
    # para que la más alta quede arriba.
    top = matriz.reset_index().head(15).sort_values("Total")
    st.caption("Capítulos con mayor costo")
    viz.barras(top["capitulo"], top["Total"], key="cf_cap_bar")

st.divider()

# ------------------------------------------------------------ informe PDF
st.subheader("📄 Informe para el cliente")
st.caption(
    "El mismo formato del Excel: portada de control de costos (capítulo × corte) "
    "y cash flow por corte, con el logo. Descárgalo o envíalo desde **Estado de cuenta**."
)
periodo_txt = None
if proyecto.get("fecha_inicio"):
    periodo_txt = f"{db.texto(proyecto.get('fecha_inicio'))} a {date.today().isoformat()}"
try:
    pdf_bytes = informe_pdf.generar_informe(
        proyecto.to_dict(),
        tabla,
        detalle if detalle is not None else pd.DataFrame(),
        periodo=periodo_txt,
    )
    st.download_button(
        "⬇️ Descargar informe PDF", data=pdf_bytes,
        file_name=f"Informe {proyecto['nombre']}.pdf", mime="application/pdf",
        use_container_width=True,
    )
except Exception as e:  # nunca tumbar la página por el PDF
    st.warning(f"No se pudo generar el informe PDF: {e}")
