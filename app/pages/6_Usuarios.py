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
    "Todas las personas que agregues aquí ven y editan exactamente los mismos "
    "proyectos, facturas e ingresos que tú — es un solo equipo, un solo workspace."
)

miembros = db.df(
    sb.table("miembros").select("*").eq("owner_user_id", uid).order("created_at").execute()
)
if miembros.empty:
    st.caption("Todavía no has agregado a nadie.")
else:
    for _, m in miembros.iterrows():
        c1, c2, c3 = st.columns([3, 2, 1])
        c1.write(m["email"])
        c2.write(
            {"editor": "Editor", "lector": "Solo lectura", "aprobador": "Aprobador"}.get(
                m["rol"], m["rol"]
            )
        )
        if c3.button("Quitar", key=f"quitar_{m['id']}"):
            sb.table("miembros").delete().eq("id", m["id"]).execute()
            st.rerun()

st.divider()
st.subheader("➕ Agregar a alguien")
st.caption(
    "Antes de agregarlo aquí, crea su cuenta en Supabase → Authentication → "
    "Users → **Add user → Create new user** (correo y contraseña que tú le "
    "entregas directamente — deja marcado \"Auto confirm user\", así no se "
    "envía ningún correo). Después vinculas ese mismo correo aquí abajo."
)
with st.form("agregar"):
    email = st.text_input("Correo de la persona (el mismo que usaste en Supabase)")
    ETIQUETA_ROL = {
        "editor": "Editor — clasifica y edita, no aprueba",
        "lector": "Solo lectura — ve todo, no modifica nada",
        "aprobador": "Aprobador — además puede aprobar y marcar pagadas",
        "cliente": "Cliente de obra — solo SU proyecto, sin ver proveedores",
    }
    rol = st.selectbox("Rol", list(ETIQUETA_ROL), format_func=lambda r: ETIQUETA_ROL[r])

    # El cliente es el único rol que se limita a un proyecto. Sin proyecto
    # no habría nada que lo limite, así que la base lo exige (migración 016)
    # y aquí se pide antes de intentar guardarlo.
    pr = db.proyectos(sb, uid)
    proyecto_id = None
    if rol == "cliente":
        if pr.empty:
            st.warning("Crea primero el proyecto que este cliente va a ver.")
        else:
            ops = {r["nombre"]: r["id"] for _, r in pr.iterrows()}
            proyecto_id = ops[st.selectbox("Proyecto que puede ver", list(ops))]
        st.info(
            "Un cliente entra solo al módulo **Cash Flow del proyecto**: ve sus "
            "anticipos, el costo por capítulo y corte, y la caja de su obra. "
            "No ve proveedores, ni facturas individuales, ni las demás obras."
        )

    if st.form_submit_button("Vincular a mi equipo"):
        email = email.strip().lower()
        if not email:
            st.warning("Escribe un correo.")
        elif rol == "cliente" and not proyecto_id:
            st.warning("Un cliente tiene que quedar asignado a un proyecto.")
        elif not miembros.empty and email in miembros["email"].values:
            st.warning("Esa persona ya está en tu equipo.")
        else:
            usuarios = admin.auth.admin.list_users(page=1, per_page=200)
            encontrado = next((u for u in usuarios if (u.email or "").lower() == email), None)
            if encontrado is None:
                st.error(
                    "No existe ninguna cuenta con ese correo todavía. Créala primero en "
                    "Supabase → Authentication → Users → Add user → Create new user, "
                    "y vuelve a intentarlo."
                )
            else:
                sb.table("miembros").insert(
                    {
                        "owner_user_id": uid,
                        "member_user_id": encontrado.id,
                        "email": email,
                        "rol": rol,
                        "proyecto_id": proyecto_id,
                    }
                ).execute()
                st.success(
                    f"{email} ya puede entrar con su correo y contraseña."
                    if rol == "cliente"
                    else f"{email} ya puede entrar con su correo y contraseña, y ve tus mismos datos."
                )
                st.rerun()
