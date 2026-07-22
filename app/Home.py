"""Punto de entrada y navegación de la app.

Usa st.navigation para agrupar los módulos por lo que hace el usuario
(Registro, Reportes, Tesorería, Administración) en vez de una lista plana, y
para esconder lo que un rol no debería ver (Usuarios solo el dueño; el cliente
solo su obra). Cada vista vive en app/vistas/ y NO llama a set_page_config:
esta pantalla lo hace una sola vez para toda la app.
"""
import streamlit as st

from lib import db

st.set_page_config(page_title="Gastos de obra", page_icon="🏗️", layout="wide")

sb, uid = db.requiere_sesion()

rol = db.mi_rol(sb, uid)

# Sembrar (reglas de retención, UVT, catálogo) es una tarea de PUESTA A PUNTO
# del dueño. Solo él tiene permiso de escribir esas tablas: si lo intentara un
# cliente o un editor, `reglas_retencion` está vedada por RLS —el SELECT vuelve
# vacío y el INSERT es rechazado—, lo que tumbaba la app entera al entrar.
# Se corre UNA sola vez por sesión: antes hacía 2 consultas de red en CADA
# navegación entre pantallas, y eso se sentía lento.
if db.es_dueno(uid) and not st.session_state.get("_sembrado"):
    db.sembrar_si_vacio(sb, uid)
    db.sembrar_capitulos_si_vacio(sb, uid)
    st.session_state["_sembrado"] = True


def _p(archivo, titulo, icono, default=False):
    return st.Page(f"vistas/{archivo}", title=titulo, icon=icono, default=default)


inicio = _p("inicio.py", "Inicio", "🏠", default=True)
manual = _p("manual.py", "Manual de usuario", "❓")

if rol == "cliente":
    # El cliente solo ve su obra y la ayuda; el resto lo bloquea RLS de todos modos.
    navegacion = {
        "": [inicio],
        "Mi obra": [_p("cash_flow_proyecto.py", "Cash Flow del proyecto", "💧")],
        "Ayuda": [manual],
    }
else:
    administracion = [_p("configuracion.py", "Configuración", "⚙️")]
    if db.es_dueno(uid):
        administracion.append(_p("usuarios.py", "Usuarios", "👥"))
    navegacion = {
        "": [inicio],
        "Registro": [
            _p("revision.py", "Revisión", "📋"),
            _p("todas_las_facturas.py", "Todas las facturas", "🗂️"),
            _p("ingresos.py", "Ingresos", "💵"),
            _p("importar_matriz.py", "Importar matriz", "📥"),
        ],
        "Reportes": [
            _p("dashboard.py", "Dashboard", "📈"),
            _p("cash_flow_proyecto.py", "Cash Flow del proyecto", "💧"),
            _p("flujo_semanal.py", "Flujo semanal", "🗓️"),
            _p("compromisos.py", "Compromisos futuros", "📆"),
        ],
        "Tesorería": [
            _p("cuentas_por_pagar.py", "Cuentas por pagar", "💳"),
            _p("estado_de_cuenta.py", "Estado de cuenta", "✉️"),
        ],
        "Administración": administracion,
        "Ayuda": [manual],
    }

st.navigation(navegacion).run()
