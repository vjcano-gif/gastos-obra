"""Importar la matriz histórica de Excel desde la app.

Se hace desde aquí, subiendo el archivo, y NO metiéndolo al repositorio:
la matriz trae proveedores, montos y 25 proyectos, y un archivo commiteado
queda en el historial de Git para siempre aunque después se borre. Subirlo
por esta pantalla lo mantiene solo en la base, que es donde ya vive el
resto de la información.

La lógica es exactamente la misma del worker (worker/importar_matriz.py):
se importa, no se reescribe, para que las dos vías no se separen con el
tiempo. Aquí corre con la sesión del usuario, así que el RLS sigue
aplicando — un lector no puede importar aunque llegue a esta página.
"""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from lib import db

# El worker vive fuera de app/, que es lo único que Streamlit pone en el path.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from worker.importar_matriz import Importador  # noqa: E402

st.set_page_config(page_title="Importar matriz", page_icon="📥", layout="wide")
sb, uid = db.requiere_sesion()

st.title("📥 Importar la matriz histórica")

if not db.puede_editar(sb, uid):
    st.error("Tu rol no permite importar información.")
    st.stop()

st.caption(
    "Sube el archivo **MATRIZ Movimientos Contables**. Se cruza con las "
    "facturas que ya llegaron por correo para heredar la clasificación que "
    "ya está hecha a mano (proyecto, capítulo, actividad y corte), sin pisar "
    "nada de lo que ya se haya clasificado en la app."
)

# Sin el catálogo cargado no hay con qué emparejar capítulos y actividades:
# se avisa antes de que alguien corra la importación y salga sin clasificar.
caps = db.capitulos(sb, uid)
con_codigo = 0 if caps.empty else int(caps["codigo"].notna().sum()) if "codigo" in caps else 0
if con_codigo == 0:
    st.warning(
        "⚠️ Todavía no hay capítulos con código. Ve primero a **Configuración → "
        "Capítulos, actividades y residentes → Cargar el catálogo de obra**; "
        "si no, la importación no podrá heredar capítulo ni actividad."
    )
else:
    st.success(f"Catálogo listo: {con_codigo} capítulos con código.")

archivo = st.file_uploader("Archivo de la matriz (.xlsx)", type=["xlsx"])

modo = st.radio(
    "¿Qué hago?",
    ["simular", "aplicar"],
    format_func=lambda m: (
        "Simular — solo muestra qué pasaría, no escribe nada"
        if m == "simular"
        else "Aplicar — escribe los cambios en la base"
    ),
    horizontal=True,
)

if modo == "aplicar":
    st.warning(
        "Vas a escribir en la base. Es reejecutable (no duplica), pero "
        "conviene haber mirado antes el resultado de la simulación."
    )

if archivo and st.button("▶️ Ejecutar", type="primary"):
    with st.spinner("Leyendo el Excel y cruzando contra las facturas…"):
        try:
            imp = Importador(sb, uid, archivo, simular=(modo == "simular"))
            imp.correr()
        except Exception as e:                       # noqa: BLE001
            st.error(f"La importación falló y no se completó: {e}")
            st.stop()

    cruzadas, total = imp.cruce()
    st.success(
        f"Listo{' (simulación: no se escribió nada)' if modo == 'simular' else ''}. "
        f"Cruzaron {cruzadas} de {total} movimientos "
        f"({cruzadas * 100 // (total or 1)}%)."
    )

    c1, c2, c3 = st.columns(3)
    c1.metric("Facturas enriquecidas", imp.resumen.get("facturas_enriquecidas", 0))
    c2.metric("Movimientos nuevos", imp.resumen.get("importadas_nuevas", 0))
    c3.metric("Anticipos del cliente", imp.resumen.get("anticipos_nuevos", 0))

    detalle = pd.DataFrame(
        sorted(imp.resumen.items()), columns=["concepto", "cantidad"]
    )
    st.dataframe(detalle, use_container_width=True, hide_index=True)

    st.caption(
        "Las filas que no cruzaron por ser ambiguas se dejan a propósito sin "
        "emparejar: heredar la clasificación de la factura equivocada es peor "
        "que dejarla vacía, porque un dato errado ya no lo revisa nadie."
    )
