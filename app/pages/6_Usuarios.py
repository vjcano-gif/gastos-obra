import streamlit as st

from lib import db

st.set_page_config(page_title="Usuarios", page_icon="👥", layout="wide")
sb, uid = db.requiere_sesion()

st.title("👥 Usuarios")

if not db.es_dueno(uid):
    st.info(
        "Estás usando una cuenta invitada. Solo el dueño de esta constructora "
        "puede invitar o quitar personas."
    )
    st.stop()

admin = db.cliente_admin()
if admin is None:
    st.error(
        "Falta configurar el secreto **SUPABASE_SERVICE_ROLE_KEY** en Streamlit "
        "Cloud para poder invitar usuarios (Manage app → Secrets)."
    )
    st.stop()

st.caption(
    "Todas las personas que invites aquí ven y editan exactamente los mismos "
    "proyectos, facturas e ingresos que tú — es un solo equipo, un solo workspace."
)

miembros = db.df(
    sb.table("miembros").select("*").eq("owner_user_id", uid).order("created_at").execute()
)
if miembros.empty:
    st.caption("Todavía no has invitado a nadie.")
else:
    for _, m in miembros.iterrows():
        c1, c2, c3 = st.columns([3, 2, 1])
        c1.write(m["email"])
        c2.write("Editor" if m["rol"] == "editor" else "Solo lectura")
        if c3.button("Quitar", key=f"quitar_{m['id']}"):
            sb.table("miembros").delete().eq("id", m["id"]).execute()
            st.rerun()

st.divider()
st.subheader("➕ Invitar a alguien")
with st.form("invitar"):
    email = st.text_input("Correo de la persona a invitar")
    rol = st.selectbox("Rol", ["editor", "lector"], format_func=lambda r: "Editor" if r == "editor" else "Solo lectura")
    if st.form_submit_button("Enviar invitación"):
        email = email.strip().lower()
        if not email:
            st.warning("Escribe un correo.")
        elif not miembros.empty and email in miembros["email"].values:
            st.warning("Esa persona ya está invitada.")
        else:
            try:
                res = admin.auth.admin.invite_user_by_email(email)
                nuevo_id = res.user.id
                sb.table("miembros").insert(
                    {
                        "owner_user_id": uid,
                        "member_user_id": nuevo_id,
                        "email": email,
                        "rol": rol,
                    }
                ).execute()
                st.success(f"Invitación enviada a {email}. Debe revisar su correo para poner su contraseña.")
                st.rerun()
            except Exception as e:
                mensaje = str(e)
                if "already been registered" in mensaje.lower():
                    st.error(
                        "Ese correo ya tiene una cuenta en el sistema. Si ya existe, "
                        "pide que te confirme su correo exacto e inténtalo de nuevo — "
                        "si el problema persiste, contáctame para vincularlo manualmente."
                    )
                else:
                    st.error(f"No se pudo invitar: {mensaje[:200]}")
