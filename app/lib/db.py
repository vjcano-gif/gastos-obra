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


# Streamlit Community Cloud sirve la app dentro de un iframe con sandbox
# SIN "allow-top-navigation": ningún script (ni el nuestro) puede redirigir
# la página real, así que el truco clásico de "copiar el hash a la query
# string" no funciona ahí (sí funcionaría en Streamlit self-hosted, pero no
# en Cloud). En vez de pelear con eso, este componente resuelve todo del
# lado del navegador sin redirigir nada:
#   1. Lee el fragmento #access_token=...&type=recovery de la URL real
#      (window.top.location.hash) — leer sí está permitido, solo NAVEGAR no.
#   2. Si lo encuentra, agranda su propio iframe (window.frameElement) y
#      dibuja un formulario de "nueva contraseña".
#   3. Al guardar, llama directo al endpoint de Supabase con ese
#      access_token — la misma llamada que haría el SDK, sin pasar por
#      Python ni por Streamlit en ningún momento.
# Si no hay token de recuperación en la URL, el componente no dibuja nada.
_RESTABLECER_JS = """
<div id="reset-box"></div>
<script>
(function () {
  function intentar() {
    var box = document.getElementById("reset-box");
    if (box.innerHTML) { return true; }

    var hash = "";
    try { hash = window.top.location.hash || ""; } catch (e) {}
    if (hash.indexOf("access_token") === -1 || hash.indexOf("type=recovery") === -1) { return false; }
    var params = new URLSearchParams(hash.substring(1));
    var accessToken = params.get("access_token");
    if (!accessToken) { return false; }

    if (window.frameElement) {
      window.frameElement.style.height = "380px";
      window.frameElement.style.width = "100%";
    }

    box.innerHTML =
      '<div style="font-family:-apple-system,Segoe UI,sans-serif;max-width:420px;margin:8px auto;padding:20px;border:1px solid #d0d0d0;border-radius:10px;">' +
      '<h3 style="margin-top:0;">Restablecer contraseña</h3>' +
      '<input id="pw1" type="password" placeholder="Nueva contraseña" style="width:100%;padding:9px;margin-bottom:8px;box-sizing:border-box;font-size:15px;">' +
      '<input id="pw2" type="password" placeholder="Repite la contraseña" style="width:100%;padding:9px;margin-bottom:12px;box-sizing:border-box;font-size:15px;">' +
      '<button id="btn-guardar" style="width:100%;padding:10px;cursor:pointer;font-size:15px;">Guardar nueva contraseña</button>' +
      '<div id="msg" style="margin-top:10px;font-size:14px;"></div>' +
      '</div>';

    document.getElementById("btn-guardar").onclick = async function () {
      var pw1 = document.getElementById("pw1").value;
      var pw2 = document.getElementById("pw2").value;
      var msg = document.getElementById("msg");
      if (pw1.length < 8) { msg.style.color = "crimson"; msg.textContent = "Usa al menos 8 caracteres."; return; }
      if (pw1 !== pw2) { msg.style.color = "crimson"; msg.textContent = "Las contraseñas no coinciden."; return; }
      msg.style.color = "#555";
      msg.textContent = "Guardando...";
      try {
        var resp = await fetch("__SUPABASE_URL__/auth/v1/user", {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
            "apikey": "__ANON_KEY__",
            "Authorization": "Bearer " + accessToken
          },
          body: JSON.stringify({ password: pw1 })
        });
        if (resp.ok) {
          box.innerHTML = '<div style="font-family:-apple-system,Segoe UI,sans-serif;max-width:420px;margin:8px auto;padding:20px;border:1px solid #b7e4c7;border-radius:10px;background:#f0fdf4;color:#166534;">' +
            '<strong>Contraseña actualizada.</strong><br>Cierra esta pestaña y entra de nuevo con tu nueva contraseña.</div>';
        } else {
          msg.style.color = "crimson";
          msg.textContent = "El enlace ya expiró o no es válido. Pide uno nuevo desde \\"Olvidé mi contraseña\\".";
        }
      } catch (e) {
        msg.style.color = "crimson";
        msg.textContent = "Error de conexión. Intenta de nuevo.";
      }
    };
    return true;
  }

  // Al crearse el iframe (via srcdoc) la primera pasada puede correr antes
  // de que el navegador termine de enlazarlo con la página real, y
  // window.top no resuelve todavía. Reintenta unas pocas veces con backoff
  // corto en vez de depender de que la primera pasada funcione.
  [0, 100, 300, 700, 1500].forEach(function (ms) {
    setTimeout(intentar, ms);
  });
})();
</script>
"""


def _puente_restablecer() -> None:
    js = _RESTABLECER_JS.replace("__SUPABASE_URL__", st.secrets["SUPABASE_URL"]).replace(
        "__ANON_KEY__", st.secrets["SUPABASE_ANON_KEY"]
    )
    st.iframe(js, height=1)


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

    st.title("🏗️ Gastos de obra")
    _puente_restablecer()

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

    st.caption(
        "¿Olvidaste tu contraseña? Escríbele a "
        f"**{st.secrets.get('ADMIN_CONTACTO', 'quien administra esta cuenta')}** "
        "para que te la restablezca."
    )

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


def capitulos(sb, uid) -> pd.DataFrame:
    return df(sb.table("capitulos").select("*").eq("user_id", uid).order("orden").order("nombre").execute())


def actividades(sb, uid) -> pd.DataFrame:
    """Trae también el nombre del capítulo al que pertenece cada actividad,
    para poder mostrar "Estructura › Vaciado de placa" en los selectores."""
    data = df(
        sb.table("actividades")
        .select("*, capitulos(nombre)")
        .eq("user_id", uid)
        .order("nombre")
        .execute()
    )
    if not data.empty:
        data["capitulo_nombre"] = data["capitulos"].apply(
            lambda c: c["nombre"] if isinstance(c, dict) else None
        )
    return data


def residentes(sb, uid) -> pd.DataFrame:
    return (
        df(sb.table("residentes").select("*").eq("user_id", uid).order("nombre").execute())
    )


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

CAPITULOS_OBRA = [
    "Preliminares",
    "Cimentación",
    "Estructura",
    "Mampostería",
    "Acabados",
    "Instalaciones eléctricas",
    "Instalaciones hidrosanitarias",
    "Equipos y herramienta",
    "Transporte y acarreos",
    "Mano de obra",
    "Honorarios y diseño",
    "Administración",
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


def sembrar_capitulos_si_vacio(sb, uid) -> None:
    if sb.table("capitulos").select("id").eq("user_id", uid).limit(1).execute().data:
        return
    sb.table("capitulos").insert(
        [{"user_id": uid, "nombre": n, "orden": i} for i, n in enumerate(CAPITULOS_OBRA)]
    ).execute()


def cop(v) -> str:
    try:
        return f"${v:,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return "-"
