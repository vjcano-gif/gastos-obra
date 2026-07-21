import base64
from datetime import date, timedelta

import pandas as pd
import requests as rq
import streamlit as st

from lib import db, informe_pdf

sb, uid = db.requiere_sesion()

st.title("✉️ Estado de cuenta por proyecto")

pr = db.proyectos(sb, uid)
if pr.empty:
    st.info("Crea primero un proyecto en Configuración.")
    st.stop()

nombre = st.selectbox("Proyecto", pr["nombre"].tolist())
p = pr[pr["nombre"] == nombre].iloc[0]

fx = db.facturas(sb, uid, proyecto_id=p["id"])

# Al cliente solo se le informa lo REVISADO Y APROBADO: antes entraba
# cualquier cosa no anulada, incluyendo documentos recién extraídos que
# aún nadie había verificado.
solo_aprobadas = st.checkbox(
    "Incluir solo facturas aprobadas o pagadas (recomendado)", value=True
)
if not fx.empty:
    fx = fx[fx["estado"].isin(["aprobada", "pagada"])] if solo_aprobadas else fx[fx["estado"] != "anulada"]

if not fx.empty:
    fx["_fecha_dt"] = pd.to_datetime(fx["fecha_emision"], errors="coerce")
    validas = fx["_fecha_dt"].dropna()
    if not validas.empty:
        c_d, c_h = st.columns(2)
        desde = c_d.date_input("Desde", value=validas.min().date(), key="ec_desde")
        hasta = c_h.date_input("Hasta", value=validas.max().date(), key="ec_hasta")
        fx = fx[
            fx["_fecha_dt"].isna()
            | ((fx["_fecha_dt"].dt.date >= desde) & (fx["_fecha_dt"].dt.date <= hasta))
        ]
        periodo = f"{desde} a {hasta}"
    else:
        periodo = "todo el histórico"
else:
    periodo = "todo el histórico"

if fx.empty:
    st.warning("No hay movimientos aprobados en ese rango: no hay nada que enviar.")

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
    f"Período: {periodo}",
    "",
    f"Total invertido en el proyecto a la fecha: {db.cop(tot_g)}",
    f"Abonos recibidos: {db.cop(tot_i)}",
    f"Saldo: {db.cop(tot_g - tot_i)}",
    "",
    "Detalle de los últimos movimientos:",
]
if not fx.empty:
    for _, f in fx.head(30).iterrows():
        signo = "+" if f.get("sentido") == "ingreso" else "-"
        cuerpo.append(
            f"  {db.texto(f.get('fecha_emision'), 's.f.')}  {signo}{db.cop(abs(f['monto_efectivo']))}  "
            f"{(db.texto(f.get('proveedor_nombre')) or db.texto(f.get('descripcion')))[:60]}"
        )
texto = "\n".join(cuerpo)

st.subheader("Vista previa")
st.code(texto, language=None)

# --- informe PDF con la estructura del Excel (portada + cash flow, con logo)
# Se arma con TODO el proyecto (no solo el rango del texto), como el Cash Flow.
st.subheader("📄 Informe PDF para adjuntar")
pdf_informe = None
try:
    fx_proy = db.facturas(sb, uid, proyecto_id=p["id"])
    cortes_p = db.cortes(sb, uid, p["id"])
    anticipos_p = db.anticipos(sb, uid, p["id"])
    cf_tabla = db.cash_flow(
        fx_proy, anticipos_p, db.movimientos_caja(sb, uid, p["id"]),
        cortes_p, float(p.get("pct_aiu") or 0), bool(p.get("exento_aiu")),
    )
    costo_act = db.costo_por_actividad_local(sb, uid, p["id"], fx_proy, cortes_p)
    pdf_informe = informe_pdf.generar_informe(
        p.to_dict(), cf_tabla,
        costo_act if costo_act is not None else pd.DataFrame(), periodo=periodo,
        anticipos=anticipos_p, cortes=cortes_p,
    )
    st.download_button(
        "⬇️ Descargar informe PDF", pdf_informe,
        file_name=f"Informe {p['nombre']}.pdf", mime="application/pdf",
    )
except Exception as e:
    st.warning(f"No se pudo generar el informe PDF: {e}")

adjuntar_pdf = st.checkbox(
    "Adjuntar el informe PDF al correo", value=pdf_informe is not None,
    disabled=pdf_informe is None,
)

destino = st.text_input("Enviar a", value=p.get("cliente_email") or "")

# Aviso de posible envío duplicado: mandar dos estados de cuenta seguidos
# al cliente se ve mal y no hay forma de "des-enviarlo".
recientes = db.df(
    sb.table("envios_estado_cuenta")
    .select("enviado_en, enviado_a")
    .eq("proyecto_id", p["id"])
    .gte("enviado_en", (date.today() - timedelta(days=7)).isoformat())
    .order("enviado_en", desc=True)
    .limit(1)
    .execute()
)
if not recientes.empty:
    ultimo = recientes.iloc[0]
    st.warning(
        f"⚠️ Ya se envió un estado de cuenta de este proyecto el "
        f"{str(ultimo['enviado_en'])[:16]} a {ultimo['enviado_a']}. "
        "Verifica que no sea un envío repetido."
    )

if st.button("📨 Enviar estado de cuenta", type="primary", disabled=not destino or fx.empty):
    api_key = st.secrets.get("RESEND_API_KEY", "")
    remitente = st.secrets.get("EMAIL_FROM", "")
    if not api_key or not remitente:
        st.error(
            "Falta configurar RESEND_API_KEY y EMAIL_FROM en los secretos de la app "
            "para poder enviar correos."
        )
    else:
        cuerpo_email = {
            "from": remitente,
            "to": [destino],
            "subject": f"Estado de cuenta — {p['nombre']}",
            "text": texto,
        }
        if adjuntar_pdf and pdf_informe:
            cuerpo_email["attachments"] = [{
                "filename": f"Informe {p['nombre']}.pdf",
                "content": base64.b64encode(pdf_informe).decode(),
            }]
        r = rq.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}"},
            json=cuerpo_email,
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
