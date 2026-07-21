"""Manual de usuario, consultable dentro de la app. Es solo texto de ayuda:
no lee ni escribe datos, así que cualquier rol puede abrirlo."""
import streamlit as st

from lib import db

db.requiere_sesion()  # solo para exigir sesión; no usa los datos

st.title("❓ Manual de usuario")
st.caption("Guía práctica de cada módulo. Búscala aquí cuando tengas una duda.")

st.markdown(
    """
Esta aplicación lleva el **control de gastos e ingresos de cada obra**: recibe las
facturas electrónicas por correo, las clasifica por proyecto/capítulo/actividad,
calcula retención y comisión (AIU), controla lo que hay que pagar y lo que el
cliente va abonando, y arma el **informe para el cliente** con la misma forma del
Excel de control de costos.
"""
)

# ---------------------------------------------------------------- flujo general
st.header("🔄 Cómo funciona, de principio a fin")
st.markdown(
    """
1. **Llegan los documentos.** Un robot revisa el buzón de correo cada ~6 horas y
   guarda las facturas electrónicas (XML/PDF) que encuentra. También puedes subir
   archivos o registrar movimientos a mano.
2. **Se revisan.** En **Revisión** le asignas a cada documento su proyecto,
   capítulo y actividad, el método de pago y —si aplica— el corte de obra.
3. **Se aprueban.** Un aprobador o el dueño marca la factura como **aprobada**.
   Solo lo aprobado entra en el estado de cuenta del cliente.
4. **Se controla la plata.** En **Cuentas por pagar** registras los pagos (con
   comprobante); en **Ingresos** registras los abonos del cliente.
5. **Se reporta.** El **Dashboard**, el **Cash Flow** y los **Compromisos**
   muestran cómo va la obra; el **Estado de cuenta** arma el informe para el cliente.
"""
)

# ---------------------------------------------------------------- roles
st.header("👤 Roles y permisos")
st.markdown(
    """
| Rol | Qué puede hacer |
|---|---|
| **Dueño** | Todo, incluido invitar/quitar usuarios. |
| **Editor** | Registrar, clasificar, editar y pagar. No administra usuarios. |
| **Aprobador** | Lo de editor **más** aprobar facturas. |
| **Lector** | Solo consultar; no modifica datos. |
| **Cliente** | Solo ve el **Cash Flow** de su propia obra. |

El menú de la izquierda se adapta al rol: por ejemplo, **Usuarios** solo lo ve el
dueño, y el cliente solo ve su obra.
"""
)

# ---------------------------------------------------------------- módulos
st.header("📚 Módulos, uno por uno")

st.subheader("📥 Registro")
with st.expander("📋 Revisión"):
    st.markdown(
        """
El corazón del día a día. Muestra lo que llegó y aún no se ha clasificado.
Por cada documento:
- Asigna **proyecto**, **capítulo** y **actividad** (por artículo si la factura
  trae detalle, o para toda la factura si no).
- Elige el **método de pago** y, si aplica, el **corte de obra** y el **pagador**.
- Usa el **previsualizador** para ver la factura real y el **segmentador de fechas**
  para enfocarte en un período.
- Cuando esté lista, **apruébala**. Solo lo aprobado llega al cliente.

> El sistema sugiere el concepto de retención (compras / servicios / honorarios /
> arriendos) para calcular la retefuente; verifícalo antes de aprobar.
"""
    )
with st.expander("🗂️ Todas las facturas"):
    st.markdown(
        """
La tabla completa, a nivel de artículo, con todos los filtros (proyecto, estado,
capítulo, fechas). Sirve para **buscar, corregir y descargar** cualquier
movimiento, esté aprobado o no. Es el mejor lugar para auditar o exportar a Excel.
"""
    )
with st.expander("💵 Ingresos"):
    st.markdown(
        """
Los **abonos del cliente** (la "matriz de ingresos"). Puedes:
- **Registrar** un abono a mano (fecha, valor, corte, medio, si va por encima o
  por debajo del presupuesto).
- **📥 Importar la matriz de ingresos** desde tu Excel: empareja proyecto y corte
  por nombre e inserta todos los abonos de una, **sin duplicar** los que ya estén.

Estos abonos son los que alimentan la fila de **Ingresos** del Dashboard y del Cash Flow.
"""
    )
with st.expander("📥 Importar matriz"):
    st.markdown(
        """
Cargue masivo desde el Excel de movimientos: cruza lo del archivo contra lo que ya
existe para no duplicar, y te muestra qué entra y qué queda pendiente. Úsalo para
subir el histórico o una actualización grande de una sola vez.
"""
    )

st.subheader("📊 Reportes")
with st.expander("📈 Dashboard"):
    st.markdown(
        """
La foto del negocio: **gastos vs ingresos por mes**, saldo, y desglose por
capítulo, con segmentador por proyecto. Los ingresos incluyen los abonos del
cliente (no solo las facturas de ingreso).
"""
    )
with st.expander("💧 Cash Flow del proyecto"):
    st.markdown(
        """
El control de costos e ingresos de **una obra**, con la estructura de tu Excel:
- **Portada / control de costos**: capítulo → actividad × corte, con su % de
  participación.
- **Cash Flow por corte**: saldo inicial, anticipos, gastos, AIU, egresos y saldo.
- Botón **⬇️ Descargar informe PDF** con logo, colores y el detalle de anticipos,
  listo para el cliente.
"""
    )
with st.expander("🗓️ Flujo semanal"):
    st.markdown(
        "Lo **planeado vs lo realmente ejecutado** semana a semana, para ver si la "
        "obra va al ritmo del presupuesto."
    )
with st.expander("📆 Compromisos futuros"):
    st.markdown(
        """
Mira **N meses hacia adelante**: los **vencimientos por pagar** contra los
**ingresos previstos** (los abonos programados en el cronograma). La línea de caja
proyectada avisa en qué mes los pagos superan a los cobros esperados.
"""
    )

st.subheader("💰 Tesorería")
with st.expander("💳 Cuentas por pagar"):
    st.markdown(
        """
Lo que se debe: vencimientos y saldos, con filtro por proyecto. Al registrar un
**pago** anotas el **comprobante**, el **medio** y la **fecha**; la factura pasa a
**parcial** o **pagada** según cubra el saldo, y se acumula el valor pagado.
"""
    )
with st.expander("✉️ Estado de cuenta"):
    st.markdown(
        """
El informe para el **cliente**: incluye solo lo **aprobado**, en el rango de fechas
que elijas. Puedes **descargar el PDF** (mismo formato del Cash Flow) y **enviarlo
por correo** con el PDF adjunto. Avisa si ya mandaste uno hace poco para no
duplicar el envío.
"""
    )

st.subheader("⚙️ Administración")
with st.expander("⚙️ Configuración"):
    st.markdown(
        """
El tablero de ajustes:
- **Proyectos** (con fechas, cliente, % de comisión/AIU y cronograma de abonos).
- **Capítulos, actividades y residentes**.
- **Reglas de retención** y valor de la **UVT**.
- **Dimensiones** editables (cortes, modos de pago, etc.).
"""
    )
with st.expander("👥 Usuarios (solo el dueño)"):
    st.markdown(
        """
Invitar o quitar personas del equipo y asignarles un rol. Para un **cliente**, se
le asigna **un solo proyecto**: solo verá el Cash Flow de esa obra.
"""
    )

# ---------------------------------------------------------------- conceptos
st.header("💡 Conceptos clave")
with st.expander("Capítulo y actividad"):
    st.markdown(
        "El **capítulo** es el gran rubro de obra (Preliminares, Estructura, "
        "Acabados…) y la **actividad** es el detalle dentro de él. Clasificar bien "
        "es lo que hace que el control de costos cuadre."
    )
with st.expander("Corte de obra"):
    st.markdown(
        "Un **corte** es un período de avance/cobro de la obra. Gastos e ingresos se "
        "agrupan por corte para ver el flujo de caja etapa por etapa."
    )
with st.expander("AIU / comisión"):
    st.markdown(
        "El **AIU** (Administración, Imprevistos y Utilidad) es la comisión que se "
        "calcula sobre los gastos según el % pactado en cada proyecto."
    )
with st.expander("Retención en la fuente y UVT"):
    st.markdown(
        "La **retefuente** se calcula según el concepto (compras, servicios, "
        "honorarios, arriendos), su tarifa y la **UVT** del año. La UVT se actualiza "
        "en Configuración cada año."
    )
with st.expander("Anticipos del cliente"):
    st.markdown(
        "Los **anticipos** son los abonos que el cliente va consignando. Son los "
        "**ingresos** reales de la obra y se registran en el módulo de Ingresos."
    )

st.divider()
st.caption(
    "¿Encontraste algo que el manual no explica o que la app podría hacer mejor? "
    "Coméntalo con quien administra la cuenta para incluirlo."
)
