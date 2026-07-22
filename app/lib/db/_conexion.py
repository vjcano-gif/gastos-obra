"""Conexión a Supabase, sesión/login, roles y caché."""
from __future__ import annotations

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


# ------------------------------------------------------------------- caché
# Streamlit re-ejecuta el script COMPLETO en cada interaccion (un clic, un
# filtro, abrir un desplegable). Sin caché, cada rerun vuelve a bajar las
# ~5.000 facturas y todas las dimensiones de Supabase. Las lecturas se
# cachean con @st.cache_data; el problema es la frescura tras un cambio.
#
# La regla es simple y uniforme: toda accion que cambia datos termina en un
# rerun para mostrar el resultado, asi que `rerun()` limpia el caché antes
# de re-ejecutar. Un rerun que no escribio nada tambien lo limpia, pero eso
# solo cuesta una recarga: es preferible a cazar los ~37 sitios de
# escritura y arriesgarse a olvidar uno (el bug de "datos viejos" que ya
# aparecio dos veces). El TTL es una red por si algo se leyera sin rerun.
TTL_LECTURA = 300  # segundos


def limpiar_cache() -> None:
    """Invalida las lecturas cacheadas. Se llama tras escribir en la base."""
    st.cache_data.clear()


def rerun() -> None:
    """Como st.rerun(), pero refrescando primero los datos cacheados.

    Toda pantalla que guarda algo debe usar esto en vez de st.rerun(): es
    lo que garantiza que despues de clasificar o pagar se vea el dato nuevo
    y no el viejo del caché."""
    limpiar_cache()
    st.rerun()


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
# string" no funciona ahí. Tampoco sirve agrandar ESTE iframe para mostrar
# el formulario adentro: Streamlit reserva el espacio en el layout de la
# página según la altura que se le pasa en Python, no según lo que el
# iframe mida después, así que un resize por JS deja el contenido flotando
# ENCIMA de lo que venga después en vez de empujarlo — confirmado en
# producción: un usuario term inó enviando sin querer el botón "Entrar" del
# login (tapado debajo) en vez de "Guardar nueva contraseña".
#
# Por eso este componente se queda invisible (1px) SIEMPRE, y en vez de
# dibujar el formulario adentro de sí mismo, lo INSERTA directo en la
# página real (window.top.document): al ser un elemento más del DOM de esa
# página, el navegador lo acomoda solo y empuja el resto hacia abajo, sin
# necesidad de coordinar ninguna altura con Streamlit.
#   1. Lee el fragmento #access_token=...&type=recovery de la URL real
#      (window.top.location.hash) — leer sí está permitido, solo NAVEGAR no.
#   2. Si lo encuentra, inserta el formulario al inicio de <body>.
#   3. Al guardar, llama directo al endpoint de Supabase con ese
#      access_token — la misma llamada que haría el SDK, sin pasar por
#      Python ni por Streamlit en ningún momento.
# Si no hay token de recuperación en la URL, no se toca la página.
_RESTABLECER_JS = """
<script>
(function () {
  function intentar() {
    var doc = window.top.document;
    if (doc.getElementById("gastos-obra-reset")) { return true; }

    var hash = "";
    try { hash = window.top.location.hash || ""; } catch (e) {}
    if (hash.indexOf("access_token") === -1 || hash.indexOf("type=recovery") === -1) { return false; }
    var params = new URLSearchParams(hash.substring(1));
    var accessToken = params.get("access_token");
    if (!accessToken) { return false; }

    var banner = doc.createElement("div");
    banner.id = "gastos-obra-reset";
    banner.innerHTML =
      '<div style="font-family:-apple-system,Segoe UI,sans-serif;max-width:420px;margin:16px auto;padding:20px;border:1px solid #d0d0d0;border-radius:10px;position:relative;z-index:9999;background:white;">' +
      '<h3 style="margin-top:0;">Restablecer contraseña</h3>' +
      '<input id="go-pw1" type="password" placeholder="Nueva contraseña" style="width:100%;padding:9px;margin-bottom:8px;box-sizing:border-box;font-size:15px;">' +
      '<input id="go-pw2" type="password" placeholder="Repite la contraseña" style="width:100%;padding:9px;margin-bottom:12px;box-sizing:border-box;font-size:15px;">' +
      '<button id="go-btn-guardar" style="width:100%;padding:10px;cursor:pointer;font-size:15px;">Guardar nueva contraseña</button>' +
      '<div id="go-msg" style="margin-top:10px;font-size:14px;"></div>' +
      '</div>';
    doc.body.insertBefore(banner, doc.body.firstChild);

    doc.getElementById("go-btn-guardar").onclick = async function () {
      var pw1 = doc.getElementById("go-pw1").value;
      var pw2 = doc.getElementById("go-pw2").value;
      var msg = doc.getElementById("go-msg");
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
          banner.innerHTML = '<div style="font-family:-apple-system,Segoe UI,sans-serif;max-width:420px;margin:16px auto;padding:20px;border:1px solid #b7e4c7;border-radius:10px;background:#f0fdf4;color:#166534;">' +
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
        try:
            sb.auth.set_session(
                st.session_state["sb_session"]["access_token"],
                st.session_state["sb_session"]["refresh_token"],
            )
            return sb, st.session_state["sb_workspace_id"]
        except Exception:
            # Sesión vencida o token inválido (el refresh_token caducó): en vez
            # de tumbar la app con un AuthApiError, se limpia la sesión y se cae
            # al formulario de login para volver a entrar.
            for k in ("sb_session", "sb_user_id", "sb_workspace_id", "sb_rol"):
                st.session_state.pop(k, None)
            _sesion_expiro = True
    else:
        _sesion_expiro = False

    st.title("🏗️ Gastos de obra")
    if _sesion_expiro:
        st.info("Tu sesión expiró por seguridad. Vuelve a entrar.")
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


def mi_rol(sb, workspace_id: str) -> str:
    """'dueno' | 'editor' | 'lector' | 'aprobador'. Se cachea en la sesión.

    Si la consulta falla (red, permisos), NO tumba la página: devuelve
    'lector', que es el rol más restrictivo. Ante la duda es preferible
    que alguien no pueda aprobar a que la pantalla entera se caiga — o
    peor, que se le conceda un permiso que no tiene. La base de datos
    tiene su propio trigger de aprobación, así que esto es solo la capa
    de interfaz."""
    if es_dueno(workspace_id):
        return "dueno"
    if "sb_rol" not in st.session_state:
        try:
            r = (
                sb.table("miembros")
                .select("rol")
                .eq("member_user_id", usuario_actual_id())
                .limit(1)
                .execute()
            )
            st.session_state["sb_rol"] = (r.data[0]["rol"] if r.data else "editor")
        except Exception:
            return "lector"  # sin cachear: se reintenta en la próxima carga
    return st.session_state["sb_rol"]


def puede_editar(sb, workspace_id: str) -> bool:
    return mi_rol(sb, workspace_id) in ("dueno", "editor")


def puede_aprobar(sb, workspace_id: str) -> bool:
    return mi_rol(sb, workspace_id) in ("dueno", "aprobador")


# ------------------------------------------------------------------ lecturas
