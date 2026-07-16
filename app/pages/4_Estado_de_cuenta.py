import requests as rq
import streamlit as st

from lib import db

st.set_page_config(page_title="Estado de cuenta", page_icon="✉️", layout="wide")
sb, uid = db.requiere_sesion()

st.title("✉️ Estado de cuenta por proyecto")

pr = db.proyectos(sb, uid)
if pr.empty:
    st.info("Crea primero un proyecto en Configuración.")
    st.stop()

nombre = st.selectbox("Proyecto", pr["nombre"].tolist())
p = pr[pr["nombre"] == nombre].iloc[0]

fx = db.facturas(sb, uid, proyecto_id=p["id"])
fx = fx[fx["estado"] != "anulada"] if not fx.empty else fx

gastos = fx[fx["sentido"] == "gasto"] if not fx.empty else fx
ingresos = fx[fx["sentido"] == "ingreso"] if not fx.empty else fx
tot_g = gastos["monto_efectivo"].sum() if not fx.empty else 0
tot_i = ingresos["monto_efectivo"].sum() if not fx.empty else 0

c1, c2, c3 = st.columns(3)
c1.metric("Gastado en el proyecto", db.cop(tot_g))
c2.metric("Abonos del cliente", db.cop(tot_i))
c3.metric("Saldo por cobrar", db.cop(tot_g - tot_i))

cuerpo = [
    f"Estado de cuenta — {p['nombre']}",
    f"Cliente: {p.get('cliente_nombre') or ''}",
    "",
    f"Total invertido en el proyecto a la fecha: {db.cop(tot_g)}",
    f"Abonos recibidos: {db.cop(tot_i)}",
    f"Saldo: {db.cop(tot_g - tot_i)}",
    "",
    "Detalle de los últimos movimientos:",
]
if not fx.empty:
    for _, f in fx.head(30).iterrows():
        signo = "+" if f["sentido"] == "ingreso" else "-"
        cuerpo.append(
            f"  {f.get('fecha_emision') or 's.f.'}  {signo}{db.cop(abs(f['monto_efectivo']))}  "
            f"{(f.get('proveedor_nombre') or f.get('descripcion') or '')[:60]}"
        )
texto = "\n".join(cuerpo)

st.subheader("Vista previa")
st.code(texto, language=None)

destino = st.text_input("Enviar a", value=p.get("cliente_email") or "")
if st.button("📨 Enviar estado de cuenta", type="primary", disabled=not destino):
    api_key = st.secrets.get("RESEND_API_KEY", "")
    remitente = st.secrets.get("EMAIL_FROM", "")
    if not api_key or not remitente:
        st.error(
            "Falta configurar RESEND_API_KEY y EMAIL_FROM en los secretos de la app "
            "para poder enviar correos."
        )
    else:
        r = rq.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "from": remitente,
                "to": [destino],
                "subject": f"Estado de cuenta — {p['nombre']}",
                "text": texto,
            },
            timeout=30,
        )
        if r.ok:
            sb.table("envios_estado_cuenta").insert(
                {
                    "user_id": uid,
                    "proyecto_id": p["id"],
                    "enviado_a": destino,
                    "asunto": f"Estado de cuenta — {p['nombre']}",
                    "resumen": {"gastos": float(tot_g), "abonos": float(tot_i)},
                }
            ).execute()
            st.success(f"Enviado a {destino}.")
        else:
            st.error(f"El servicio de correo respondió un error: {r.text[:300]}")

hist = db.df(
    sb.table("envios_estado_cuenta").select("*").eq("proyecto_id", p["id"])
    .order("enviado_en", desc=True).limit(10).execute()
)
if not hist.empty:
    st.subheader("Envíos anteriores")
    st.dataframe(hist[["enviado_en", "enviado_a", "asunto"]], use_container_width=True)
