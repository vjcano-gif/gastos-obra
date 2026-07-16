"""Conexión, sesión y semillas de la app Streamlit (workspace compartido, RLS)."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from supabase import create_client

try:
    import truststore

    truststore.inject_into_ssl()
except Exception:
    pass


def cliente():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_ANON_KEY"])


def cliente_admin():
    """Cliente con service_role: solo para administrar usuarios (invitar/borrar).
    Nunca usar esto para leer o escribir datos de negocio (se saltaría RLS)."""
    key = st.secrets.get("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        return None
    return create_client(st.secrets["SUPABASE_URL"], key)


# El enlace de recuperación de Supabase redirige con los tokens en el
# fragmento de la URL (#access_token=...&type=recovery), que el navegador
# nunca envía al servidor. Este script, corriendo dentro del iframe del
# componente, lee la ubicación de la página PADRE (mismo origen) y si
# encuentra ese fragmento lo copia a la query string (?access_token=...),
# que Streamlit sí puede leer del lado de Python con st.query_params.
_PUENTE_RECOVERY = """
<script>
(function () {
  try {
    var loc = window.parent.location;
    if (loc.hash && loc.hash.indexOf("access_token") !== -1 && loc.search.indexOf("access_token") === -1) {
      var desdeHash = new URLSearchParams(loc.hash.substring(1));
      var query = new URLSearchParams(loc.search);
      desdeHash.forEach(function (v, k) { query.set(k, v); });
      loc.href = loc.pathname + "?" + query.toString();
    }
  } catch (e) {}
})();
</script>
"""


def _pantalla_restablecer(access_token: str, refresh_token: str) -> None:
    st.title("🏗️ Gastos de obra")
    st.subheader("Restablecer contraseña")
    with st.form("restablecer"):
        nueva = st.text_input("Nueva contraseña", type="password")
        repetir = st.text_input("Repite la nueva contraseña", type="password")
        if st.form_submit_button("Guardar nueva contraseña", use_container_width=True):
            if len(nueva) < 8:
                st.error("Usa al menos 8 caracteres.")
            elif nueva != repetir:
                st.error("Las dos contraseñas no coinciden.")
            else:
                try:
                    sb = cliente()
                    sb.auth.set_session(access_token, refresh_token)
                    sb.auth.update_user({"password": nueva})
                    st.session_state["clave_restablecida"] = True
                    st.query_params.clear()
                    st.rerun()
                except Exception:
                    st.error("El enlace ya expiró o no es válido. Pide uno nuevo desde 'Olvidé mi contraseña'.")
    st.stop()


def requiere_sesion():
    """Login. Devuelve (supabase, workspace_id).

    workspace_id es el id compartido por todo el equipo (mi_empresa() en la
    base de datos): para el dueño de los datos es su propio id; para un
    miembro invitado, es el id del dueño al que pertenece. Todo el resto de
    la app puede seguir usando `uid` tal cual para filtrar/insertar, sin
    saber si quien está logueado es el dueño o un invitado.
    """
    if "sb_session" in st.session_state:
        sb = cliente()
        sb.auth.set_session(
            st.session_state["sb_session"]["access_token"],
            st.session_state["sb_session"]["refresh_token"],
        )
        return sb, st.session_state["sb_workspace_id"]

    st.components.v1.html(_PUENTE_RECOVERY, height=0)
    qp = st.query_params
    if qp.get("type") == "recovery" and qp.get("access_token"):
        _pantalla_restablecer(qp["access_token"], qp.get("refresh_token", ""))

    st.title("🏗️ Gastos de obra")

    if st.session_state.pop("clave_restablecida", False):
        st.success("Contraseña actualizada. Ya puedes iniciar sesión con la nueva.")

    with st.form("login"):
        correo = st.text_input("Correo")
        clave = st.text_input("Contraseña", type="password")
        if st.form_submit_button("Entrar", use_container_width=True):
            try:
                sb = cliente()
                res = sb.auth.sign_in_with_password({"email": correo, "password": clave})
                st.session_state["sb_session"] = {
                    "access_token": res.session.access_token,
                    "refresh_token": res.session.refresh_token,
                }
                st.session_state["sb_user_id"] = res.user.id
                st.session_state["sb_workspace_id"] = sb.rpc("mi_empresa").execute().data
                st.rerun()
            except Exception:
                st.error("Correo o contraseña incorrectos.")

    with st.expander("¿Olvidaste tu contraseña?"):
        correo_recuperar = st.text_input("Tu correo", key="correo_recuperar")
        if st.button("Enviar enlace de recuperación"):
            try:
                cliente().auth.reset_password_for_email(correo_recuperar)
            except Exception:
                pass
            st.info("Si ese correo tiene una cuenta, te llegará un enlace para poner una contraseña nueva.")

    st.stop()


def usuario_actual_id() -> str:
    """El id personal de quien inició sesión (no el workspace compartido)."""
    return st.session_state["sb_user_id"]


def es_dueno(workspace_id: str) -> bool:
    """True si quien está logueado es el dueño del workspace (no un invitado)."""
    return usuario_actual_id() == workspace_id


# ------------------------------------------------------------------ lecturas
def df(res) -> pd.DataFrame:
    return pd.DataFrame(res.data or [])


def proyectos(sb, uid) -> pd.DataFrame:
    return df(sb.table("proyectos").select("*").eq("user_id", uid).order("nombre").execute())


def tipos_gasto(sb, uid) -> pd.DataFrame:
    return df(sb.table("tipos_gasto").select("*").eq("user_id", uid).order("nombre").execute())


def facturas(sb, uid, **filtros) -> pd.DataFrame:
    q = sb.table("facturas").select("*").eq("user_id", uid)
    for k, v in filtros.items():
        q = q.eq(k, v)
    data = df(q.order("fecha_emision", desc=True).limit(5000).execute())
    if not data.empty:
        # las notas crédito restan
        data["monto_efectivo"] = data.apply(
            lambda r: -abs(r["total"]) if r["tipo_documento"] == "nota_credito" else r["total"],
            axis=1,
        )
    return data


def url_documento(sb, storage_path: str, minutos: int = 10) -> str | None:
    try:
        r = sb.storage.from_("documentos").create_signed_url(storage_path, minutos * 60)
        return r.get("signedURL") or r.get("signedUrl")
    except Exception:
        return None


# ------------------------------------------------------------------ semillas
TIPOS_OBRA = [
    ("Preliminares", "preliminares", "servicios"),
    ("Cimentación", "cimentacion", "compras"),
    ("Estructura", "estructura", "compras"),
    ("Mampostería", "mamposteria", "compras"),
    ("Acabados", "acabados", "compras"),
    ("Instalaciones eléctricas", "instalaciones", "compras"),
    ("Instalaciones hidrosanitarias", "instalaciones", "compras"),
    ("Carpintería y metálicas", "acabados", "compras"),
    ("Equipos y herramienta", "equipos", "compras"),
    ("Transporte y acarreos", "logistica", "servicios"),
    ("Mano de obra", "mano_de_obra", "servicios"),
    ("Honorarios y diseño", "honorarios", "honorarios"),
    ("Administración", "administracion", "ninguno"),
]

# Tarifas de ejemplo — VALIDAR con el contador antes de usar en serio.
REGLAS_EJEMPLO = [
    ("retefuente", "compras", 2.5, 27),
    ("retefuente", "servicios", 4.0, 4),
    ("retefuente", "honorarios", 10.0, 0),
    ("retefuente", "arriendos", 3.5, 27),
    ("reteiva", "compras", 15.0, 0),
]


def sembrar_si_vacio(sb, uid) -> None:
    if sb.table("tipos_gasto").select("id").eq("user_id", uid).limit(1).execute().data:
        return
    sb.table("tipos_gasto").insert(
        [
            {"user_id": uid, "nombre": n, "capitulo": c, "concepto_retencion": r}
            for n, c, r in TIPOS_OBRA
        ]
    ).execute()
    sb.table("reglas_retencion").insert(
        [
            {
                "user_id": uid,
                "tipo": t,
                "concepto": c,
                "tarifa": tf,
                "base_minima_uvt": b,
                "vigencia_desde": "2026-01-01",
                "notas": "Semilla de ejemplo: validar con el contador.",
            }
            for t, c, tf, b in REGLAS_EJEMPLO
        ]
    ).execute()
    try:
        sb.table("uvt").upsert({"anio": 2025, "valor": 49799}).execute()
    except Exception:
        pass  # la tabla uvt se administra con service_role si RLS lo exige


def cop(v) -> str:
    try:
        return f"${v:,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return "-"
