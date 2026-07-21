"""Manual de usuario, consultable dentro de la app. Es solo texto de ayuda:
no lee ni escribe datos, así que cualquier rol puede abrirlo."""
import streamlit as st

from lib import db

db.requiere_sesion()  # solo exige sesión; no usa los datos

st.title("❓ Manual de usuario")
st.caption("Guía paso a paso de cada módulo: de dónde sale la información, qué haces y qué se arma con eso.")

st.markdown(
    """
Esta aplicación lleva el **control de gastos e ingresos de cada obra**. Recibe las
facturas electrónicas por correo, las clasifica por proyecto/capítulo/actividad,
calcula retención y comisión (AIU), controla lo que hay que pagar y lo que el
cliente abona, y arma el **informe para el cliente** con la misma forma del Excel
de control de costos.
"""
)

# ---------------------------------------------------------- puesta a punto
st.header("🚀 Puesta a punto (la primera vez)")
st.markdown(
    """
Si el workspace es nuevo, este es el orden recomendado (lo hace el **dueño** o un **editor**):

1. **Configuración → Proyectos**: crea cada obra con su cliente, su **% de comisión (AIU)**
   y, si la tienes, las fechas y el **cronograma de abonos**.
2. **Configuración → Capítulos, actividades y residentes → Cargar el catálogo de obra**:
   instala los capítulos y actividades estándar (sin esto no se puede clasificar ni
   heredar clasificación).
3. **Configuración → Reglas de retención y UVT**: revisa las tarifas y el valor de la UVT del año.
4. **Importar matriz** (opcional): sube tu Excel histórico para heredar de una vez la
   clasificación ya hecha a mano.
5. **Ingresos → Importar matriz de ingresos** (opcional): sube el histórico de abonos del cliente.
6. **Usuarios** (solo el dueño): invita al equipo y, si aplica, a los **clientes** (uno por obra).

De ahí en adelante el día a día es solo **Revisión** (clasificar lo que llega) y consultar reportes.
"""
)

# ---------------------------------------------------------- flujo general
st.header("🔄 Cómo circula la información")
st.markdown(
    """
```
Correo (facturas DIAN)  ─┐
Carga manual / soporte  ─┼─►  REVISIÓN  ─►  (aprobación)  ─►  Reportes y Cash Flow
Matriz histórica (Excel)─┘        │                              (Dashboard, Cash Flow,
                                  │                               Cuentas por pagar, PyG…)
Abonos del cliente ─► INGRESOS ───┘
```
- Un **robot revisa el buzón cada ~6 horas** y guarda las facturas electrónicas (XML/PDF).
- En **Revisión** cada documento recibe su clasificación y se **aprueba**.
- Todo lo demás (Dashboard, Cash Flow, Cuentas por pagar, informes) **se construye solo** a
  partir de esa clasificación y de los abonos del cliente. No hay que recapturar nada.
"""
)

# ---------------------------------------------------------- roles
st.header("👤 Roles y permisos")
st.markdown(
    """
| Rol | Qué puede hacer |
|---|---|
| **Dueño** | Todo, incluido invitar/quitar usuarios. |
| **Editor** | Registrar, clasificar, editar, pagar e importar. No administra usuarios. |
| **Aprobador** | Lo de editor **más** aprobar facturas. |
| **Lector** | Solo consultar; no modifica datos. |
| **Cliente** | Solo ve el **Cash Flow** de su propia obra. |

El menú de la izquierda se adapta al rol: **Usuarios** solo lo ve el dueño, y el cliente
solo ve su obra.
"""
)


def _modulo(titulo, sale, pasos, arma):
    with st.expander(titulo):
        st.markdown(f"**De dónde sale la información:** {sale}")
        st.markdown("**Paso a paso:**")
        st.markdown("\n".join(f"{i}. {p}" for i, p in enumerate(pasos, 1)))
        st.markdown(f"**Qué se arma con esto:** {arma}")


# ---------------------------------------------------------- módulos
st.header("📚 Módulos, paso a paso")

st.subheader("📥 Registro")
_modulo(
    "📋 Revisión",
    "Las facturas electrónicas que el **robot baja del correo** cada ~6 horas, más lo que "
    "**subas a mano** (un PDF/imagen de soporte o un movimiento manual).",
    [
        "Usa el **segmentador de fechas** y los filtros para enfocarte en lo que llegó.",
        "Abre un documento: revisa el **previsualizador** de la factura real.",
        "Asígnale **proyecto**, **capítulo** y **actividad** (por artículo si trae detalle; "
        "para toda la factura si no).",
        "Elige el **método de pago** y, si aplica, el **corte de obra** y el **pagador**.",
        "Verifica el **concepto de retención** sugerido (compras/servicios/honorarios/arriendos).",
        "**Aprueba** la factura. Si algo está mal, puedes anularla.",
    ],
    "La **clasificación** que alimenta TODO lo demás: Dashboard, Cash Flow, control de "
    "costos, retención y el estado de cuenta del cliente. Solo lo **aprobado** llega al cliente.",
)
_modulo(
    "🗂️ Todas las facturas",
    "Todo lo que ya está registrado, a nivel de **artículo** (aprobado o no).",
    [
        "Filtra por proyecto, estado, capítulo o fechas.",
        "Corrige cualquier campo directamente.",
        "Descarga la tabla a Excel para auditar o cruzar por fuera.",
    ],
    "Es tu vista de **auditoría y exportación**: el universo completo en una sola tabla.",
)
_modulo(
    "💵 Ingresos",
    "Los **abonos del cliente** (la 'matriz de ingresos'). No llegan por correo: se "
    "registran a mano o se importan del Excel.",
    [
        "Registra un abono: fecha, valor, corte, medio y si va por encima/por debajo del presupuesto.",
        "O usa **📥 Importar matriz de ingresos**: descarga la **plantilla**, llénala y súbela; "
        "empareja proyecto y corte por nombre y **no duplica**.",
        "Revisa el **cumplimiento**: lo recibido contra el cronograma pactado.",
    ],
    "La fila de **Ingresos** del Dashboard y del Cash Flow, y los ingresos previstos de "
    "**Compromisos futuros**.",
)
_modulo(
    "📥 Importar matriz",
    "Tu Excel **MATRIZ Movimientos Contables** (histórico de gastos).",
    [
        "Descarga la **plantilla** para ver el formato exacto (se lee por posición de columna).",
        "Sube el archivo y corre primero en **Simular** para ver qué pasaría.",
        "Si el cruce se ve bien, corre en **Aplicar** para escribir en la base.",
    ],
    "Hereda la clasificación ya hecha a mano y la cruza con las facturas del correo, sin "
    "recapturar. **Basta hacerlo una vez** (no duplica); repítelo solo si hay movimientos nuevos.",
)

st.subheader("📊 Reportes")
_modulo(
    "📈 Dashboard",
    "Las facturas ya **clasificadas** más los **abonos** del cliente.",
    [
        "Elige un proyecto (o todos) con el segmentador.",
        "Lee gastos vs ingresos por mes, el saldo y el desglose por capítulo.",
    ],
    "La **foto del negocio**: cómo va la plata mes a mes y en qué capítulos se concentra el gasto.",
)
_modulo(
    "💧 Cash Flow del proyecto",
    "Las facturas del proyecto, los **abonos**, los **cortes** y el **% de AIU** de la obra.",
    [
        "Elige el proyecto.",
        "Lee el **control de costos** (capítulo → actividad × corte) y el **cash flow por corte** "
        "(saldo inicial, anticipos, gastos, AIU, egresos y saldo).",
        "Descarga el **informe PDF** con logo, colores y el detalle de anticipos, listo para el cliente.",
    ],
    "El equivalente exacto de tu Excel de control de costos, y el **informe que ve o recibe el cliente**.",
)
_modulo(
    "🗓️ Flujo semanal",
    "El **presupuesto por actividad** que cargas (a mano o por Excel) y el **gasto real** "
    "(las facturas clasificadas).",
    [
        "En la pestaña **Presupuesto**, carga las líneas: una por una (al elegir capítulo salen "
        "solo SUS actividades) o **masivo** con la plantilla.",
        "Reparte cada línea por semanas.",
        "En **Comparación**, mira planeado vs ejecutado y el desfase.",
    ],
    "Saber si la obra **va al ritmo** que se presupuestó, semana a semana.",
)
_modulo(
    "📆 Compromisos futuros",
    "Los **vencimientos** de las cuentas por pagar y los **abonos programados** en el cronograma del proyecto.",
    [
        "Elige el proyecto y cuántos meses mirar hacia adelante.",
        "Compara, mes a mes, lo que hay que pagar contra lo que se debería cobrar.",
    ],
    "Una **proyección de caja**: la línea avisa en qué mes los pagos superan a los cobros previstos.",
)

st.subheader("💰 Tesorería")
_modulo(
    "💳 Cuentas por pagar",
    "Las **facturas de gasto** con saldo pendiente.",
    [
        "Filtra por proyecto.",
        "Abre una factura y registra el **pago** con **comprobante**, **medio** y **fecha**.",
        "La factura pasa a **parcial** o **pagada** según cubra el saldo.",
    ],
    "El control de la **deuda** y el registro de **pagos** con su soporte.",
)
_modulo(
    "✉️ Estado de cuenta",
    "Las facturas **aprobadas** del proyecto, en el rango de fechas que elijas.",
    [
        "Elige el proyecto y el período.",
        "Descarga el **PDF** (mismo formato del Cash Flow) o **adjúntalo** al correo.",
        "Envíaselo al cliente; la app avisa si ya mandaste uno hace poco.",
    ],
    "El **informe formal para el cliente**, enviado por correo con su PDF adjunto.",
)

st.subheader("⚙️ Administración")
_modulo(
    "⚙️ Configuración",
    "Lo que **defines tú** una vez: la base sobre la que corre todo lo demás.",
    [
        "**Proyectos**: cliente, % de comisión (AIU), fechas y **cronograma de abonos**.",
        "**Capítulos, actividades y residentes**, incluido **cargar el catálogo de obra**.",
        "**Reglas de retención** y valor de la **UVT** del año.",
        "**Dimensiones** editables (cortes, modos de pago, etc.).",
    ],
    "El **catálogo y los parámetros** con los que se clasifica, se calcula retención/AIU y se arman los cortes.",
)
_modulo(
    "👥 Usuarios (solo el dueño)",
    "El equipo y los clientes que defina el dueño.",
    [
        "Invita a una persona con su **rol** (editor, aprobador, lector).",
        "Para un **cliente**, asígnale **un solo proyecto**: solo verá el Cash Flow de esa obra.",
        "Quita a quien ya no deba tener acceso.",
    ],
    "El **control de acceso** del equipo y la vista restringida del cliente.",
)

# ---------------------------------------------------------- conceptos
st.header("💡 Conceptos clave")
with st.expander("Capítulo y actividad"):
    st.markdown(
        "El **capítulo** es el gran rubro de obra (Preliminares, Estructura, Acabados…) y la "
        "**actividad** es el detalle dentro de él. Clasificar bien es lo que hace que el control "
        "de costos cuadre. El **catálogo** se carga en Configuración."
    )
with st.expander("Corte de obra"):
    st.markdown(
        "Un **corte** es un período de avance/cobro de la obra. Gastos e ingresos se agrupan por "
        "corte para ver el flujo de caja etapa por etapa (como las columnas de tu Excel)."
    )
with st.expander("AIU / comisión"):
    st.markdown(
        "El **AIU** (Administración, Imprevistos y Utilidad) es la comisión que se calcula sobre "
        "los gastos según el % pactado en cada proyecto. Los **pagos directos del cliente** también "
        "generan comisión pero no salen de la caja de la empresa."
    )
with st.expander("Retención en la fuente y UVT"):
    st.markdown(
        "La **retefuente** se calcula según el concepto (compras, servicios, honorarios, arriendos), "
        "su tarifa y la **UVT** del año. La UVT se actualiza en Configuración cada año."
    )
with st.expander("Anticipos del cliente"):
    st.markdown(
        "Los **anticipos** son los abonos que el cliente va consignando. Son los **ingresos** reales "
        "de la obra y se registran en el módulo de Ingresos (a mano o importados)."
    )
with st.expander("Estados de una factura"):
    st.markdown(
        "- **Extraída**: recién bajada del correo, sin revisar.\n"
        "- **Aprobada**: ya revisada y clasificada; entra al estado de cuenta del cliente.\n"
        "- **Pagada / Parcial**: según lo registrado en Cuentas por pagar.\n"
        "- **Anulada**: no cuenta para nada."
    )

st.divider()
st.caption(
    "¿Algo que el manual no explique o que la app podría hacer mejor? Coméntalo con quien "
    "administra la cuenta para incluirlo."
)
