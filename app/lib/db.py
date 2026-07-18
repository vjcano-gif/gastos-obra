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


def hitos_proyecto(sb, uid, proyecto_id: str | None = None) -> pd.DataFrame:
    q = sb.table("hitos_proyecto").select("*").eq("user_id", uid)
    if proyecto_id:
        q = q.eq("proyecto_id", proyecto_id)
    return df(q.order("fecha").execute())


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


def factura_items(sb, factura_id: str) -> pd.DataFrame:
    return df(
        sb.table("factura_items").select("*").eq("factura_id", factura_id).order("linea").execute()
    )


def todos_los_items(sb, uid) -> pd.DataFrame:
    """Todos los items de todas las facturas del workspace, paginado (mismo
    tope de 1000 filas por respuesta que facturas())."""
    tam_pagina = 1000
    inicio = 0
    filas: list[dict] = []
    while True:
        lote = (
            sb.table("factura_items")
            .select("*")
            .eq("user_id", uid)
            .order("id")
            .range(inicio, inicio + tam_pagina - 1)
            .execute()
            .data
            or []
        )
        filas.extend(lote)
        if len(lote) < tam_pagina:
            break
        inicio += tam_pagina
    return pd.DataFrame(filas)


def detalle_clasificado(fx: pd.DataFrame, items_all: pd.DataFrame) -> pd.DataFrame:
    """Una fila por artículo (con su propia clasificación), y una fila de
    respaldo por cada factura SIN detalle de artículos (manuales,
    consignaciones) usando la clasificación de la factura completa. Base
    común para "Todas las facturas" y los reportes por capítulo/tipo."""
    if fx.empty:
        return pd.DataFrame()

    fx_indexed = fx.set_index("id")
    con_items = set(items_all["factura_id"]) if items_all is not None and not items_all.empty else set()

    filas = []
    if items_all is not None and not items_all.empty:
        for _, it in items_all.iterrows():
            fid = it["factura_id"]
            if fid not in fx_indexed.index:
                continue
            fac = fx_indexed.loc[fid]
            filas.append(
                {
                    "factura_id": fid,
                    "item_id": it["id"],
                    "fecha_emision": fac.get("fecha_emision"),
                    "numero": fac.get("numero"),
                    "proveedor_nombre": fac.get("proveedor_nombre"),
                    "descripcion": it.get("descripcion"),
                    "cantidad": it.get("cantidad"),
                    "valor": it.get("total"),
                    "sentido": fac.get("sentido"),
                    "estado": fac.get("estado"),
                    "proyecto_id": fac.get("proyecto_id"),
                    "residente_id": fac.get("residente_id"),
                    "tipo_gasto_id": it.get("tipo_gasto_id"),
                    "capitulo_id": it.get("capitulo_id"),
                    "actividad_id": it.get("actividad_id"),
                }
            )

    for fid, fac in fx_indexed.iterrows():
        if fid not in con_items:
            filas.append(
                {
                    "factura_id": fid,
                    "item_id": None,
                    "fecha_emision": fac.get("fecha_emision"),
                    "numero": fac.get("numero"),
                    "proveedor_nombre": fac.get("proveedor_nombre"),
                    "descripcion": fac.get("descripcion") or "(sin detalle de artículos)",
                    "cantidad": None,
                    "valor": fac.get("total"),
                    "sentido": fac.get("sentido"),
                    "estado": fac.get("estado"),
                    "proyecto_id": fac.get("proyecto_id"),
                    "residente_id": fac.get("residente_id"),
                    "tipo_gasto_id": fac.get("tipo_gasto_id"),
                    "capitulo_id": fac.get("capitulo_id"),
                    "actividad_id": fac.get("actividad_id"),
                }
            )
    return pd.DataFrame(filas)


def facturas(sb, uid, **filtros) -> pd.DataFrame:
    """Supabase/PostgREST limita cada respuesta a 1000 filas por defecto,
    sin importar el .limit() que pidamos — hay que paginar con .range()
    para traer todo (ya pasamos de 4000 facturas)."""

    def consulta():
        q = sb.table("facturas").select("*").eq("user_id", uid)
        for k, v in filtros.items():
            q = q.eq(k, v)
        # "id" como desempate: varias facturas comparten fecha (o la tienen
        # nula), y sin un orden 100% determinista la paginacion con .range()
        # puede saltarse o repetir filas entre paginas.
        return q.order("fecha_emision", desc=True).order("id")

    tam_pagina = 1000
    inicio = 0
    filas: list[dict] = []
    while True:
        lote = consulta().range(inicio, inicio + tam_pagina - 1).execute().data or []
        filas.extend(lote)
        if len(lote) < tam_pagina:
            break
        inicio += tam_pagina

    data = pd.DataFrame(filas)
    if not data.empty:
        # las notas crédito restan
        data["monto_efectivo"] = data.apply(
            lambda r: -abs(r["total"]) if r["tipo_documento"] == "nota_credito" else r["total"],
            axis=1,
        )
    return data


def render_factura_html(f: dict, items: pd.DataFrame) -> str:
    """Representación visual de la factura a partir de los datos YA
    extraídos (no del XML crudo, que no es legible para un humano)."""
    import html as _html

    def esc(v) -> str:
        return _html.escape(str(v)) if v is not None else ""

    filas_items = ""
    if items is not None and not items.empty:
        for _, it in items.iterrows():
            cod = it.get("codigo_articulo")
            desc_item = esc(it.get("descripcion") or "")
            if cod:
                desc_item += f" <span style='color:#999;'>[{esc(cod)}]</span>"
            tarifa = it.get("tarifa_iva")
            iva_txt = f"{cop(it.get('iva'))}" + (f" ({tarifa:.0f}%)" if tarifa else "")
            filas_items += (
                "<tr>"
                f"<td style='padding:4px 6px;'>{desc_item}</td>"
                f"<td style='padding:4px 6px;text-align:right;'>{esc(it.get('cantidad') or '')}</td>"
                f"<td style='padding:4px 6px;'>{esc(it.get('unidad') or '')}</td>"
                f"<td style='padding:4px 6px;text-align:right;'>{cop(it.get('precio_unitario'))}</td>"
                f"<td style='padding:4px 6px;text-align:right;'>{cop(it.get('descuento'))}</td>"
                f"<td style='padding:4px 6px;text-align:right;'>{iva_txt}</td>"
                f"<td style='padding:4px 6px;text-align:right;'>{cop(it.get('total'))}</td>"
                "</tr>"
            )
    tabla_items = (
        "<table style='width:100%;border-collapse:collapse;font-size:13px;margin-top:10px;'>"
        "<tr style='border-bottom:1px solid #ccc;text-align:left;'>"
        "<th style='padding:4px 6px;'>Descripción</th><th style='padding:4px 6px;'>Cant.</th>"
        "<th style='padding:4px 6px;'>Unidad</th><th style='padding:4px 6px;'>V. unitario</th>"
        "<th style='padding:4px 6px;'>Descuento</th><th style='padding:4px 6px;'>IVA</th>"
        "<th style='padding:4px 6px;'>V. total</th></tr>"
        f"{filas_items}</table>"
    ) if filas_items else "<p style='color:#888;font-size:13px;'>Sin detalle de artículos.</p>"

    extras = []
    if f.get("orden_compra"):
        extras.append(f"<strong>Orden de compra:</strong> {esc(f['orden_compra'])}")
    if f.get("metodo_pago"):
        extras.append(f"<strong>Medio de pago:</strong> {esc(f['metodo_pago'])}")
    if f.get("moneda") and f.get("moneda") != "COP":
        extras.append(f"<strong>Moneda:</strong> {esc(f['moneda'])}")
    linea_extras = (
        f"<div style='font-size:13px;color:#444;margin-top:8px;'>{' · '.join(extras)}</div>" if extras else ""
    )
    linea_notas = (
        f"<div style='font-size:13px;color:#444;margin-top:6px;'><strong>Notas:</strong> {esc(f['notas'])}</div>"
        if f.get("notas") else ""
    )

    return f"""
    <div style='font-family:-apple-system,Segoe UI,sans-serif;border:1px solid #d0d0d0;
                border-radius:10px;padding:16px;margin-bottom:8px;'>
      <div style='display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;'>
        <div>
          <strong>{esc(f.get('proveedor_nombre') or 'Sin nombre')}</strong><br>
          <span style='color:#666;'>NIT {esc(f.get('proveedor_nit') or 's.d.')}</span>
        </div>
        <div style='text-align:right;'>
          <strong>{esc(f.get('tipo_documento') or 'Documento').capitalize()} {esc(f.get('numero') or '')}</strong><br>
          <span style='color:#666;'>{esc(f.get('fecha_emision') or 's.f.')}</span>
        </div>
      </div>
      {linea_extras}
      {linea_notas}
      {tabla_items}
      <div style='text-align:right;margin-top:10px;font-size:15px;'>
        <strong>Total: {cop(f.get('total'))}</strong>
      </div>
    </div>
    """


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
