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


def cortes(sb, uid, proyecto_id: str | None = None) -> pd.DataFrame:
    """Cortes de obra: los periodos de ejecución con los que ellos leen
    toda su información (capítulo × corte, cash flow por corte)."""
    q = sb.table("cortes").select("*").eq("user_id", uid)
    if proyecto_id:
        q = q.eq("proyecto_id", proyecto_id)
    return df(q.order("proyecto_id").order("numero").execute())


def anticipos(sb, uid, proyecto_id: str | None = None) -> pd.DataFrame:
    """Abonos del cliente. Van aparte de las facturas porque el cash flow
    los necesita partidos por bancos/efectivo y con su número de recibo."""
    q = sb.table("anticipos").select("*").eq("user_id", uid)
    if proyecto_id:
        q = q.eq("proyecto_id", proyecto_id)
    return df(q.order("fecha").execute())


def movimientos_caja(sb, uid, proyecto_id: str | None = None) -> pd.DataFrame:
    """Movimientos que no son facturas pero sí afectan la caja del
    proyecto: GMF 4x1000, otros gastos y pagos exentos."""
    q = sb.table("movimientos_caja").select("*").eq("user_id", uid)
    if proyecto_id:
        q = q.eq("proyecto_id", proyecto_id)
    return df(q.order("fecha").execute())


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


def asignaciones(sb, uid, factura_id: str | None = None) -> pd.DataFrame:
    q = sb.table("asignacion_costos").select("*").eq("user_id", uid)
    if factura_id:
        q = q.eq("factura_id", factura_id)
    return df(q.order("id").execute())


def aplicar_asignaciones(detalle: pd.DataFrame, asig: pd.DataFrame) -> pd.DataFrame:
    """Reemplaza las filas que tienen reparto multiproyecto por una fila
    por proyecto asignado. Las que no tienen reparto quedan igual (usan
    proyecto_id de la factura). Devuelve el detalle listo para reportes."""
    if detalle.empty or asig is None or asig.empty:
        return detalle

    # el reparto puede ser por artículo (factura_item_id) o por factura completa
    por_item = {a["factura_item_id"] for _, a in asig.iterrows() if a.get("factura_item_id")}
    por_factura = {
        a["factura_id"] for _, a in asig.iterrows() if not a.get("factura_item_id")
    }

    filas = []
    for _, r in detalle.iterrows():
        item_id, factura_id = r.get("item_id"), r.get("factura_id")
        reemplazada = (item_id in por_item) or (item_id is None and factura_id in por_factura)
        if not reemplazada:
            filas.append(r.to_dict())
            continue
        if item_id in por_item:
            aplican = asig[asig["factura_item_id"] == item_id]
        else:
            aplican = asig[(asig["factura_id"] == factura_id) & (asig["factura_item_id"].isna())]
        signo = -1 if (r.get("valor") or 0) < 0 else 1
        for _, a in aplican.iterrows():
            nueva = r.to_dict()
            nueva["proyecto_id"] = a["proyecto_id"]
            nueva["valor"] = signo * abs(float(a["monto"] or 0))
            nueva["repartida"] = True
            filas.append(nueva)
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
            # las notas crédito RESTAN también a nivel de artículo — si no,
            # los reportes por tipo/capítulo las suman como gasto positivo
            signo = -1 if fac.get("tipo_documento") == "nota_credito" else 1
            filas.append(
                {
                    "factura_id": fid,
                    "item_id": it["id"],
                    "fecha_emision": fac.get("fecha_emision"),
                    "numero": fac.get("numero"),
                    "proveedor_nombre": fac.get("proveedor_nombre"),
                    "descripcion": it.get("descripcion"),
                    "cantidad": it.get("cantidad"),
                    "valor": signo * abs(it.get("total") or 0),
                    "sentido": fac.get("sentido"),
                    "estado": fac.get("estado"),
                    "proyecto_id": fac.get("proyecto_id"),
                    "residente_id": fac.get("residente_id"),
                    "corte_id": fac.get("corte_id"),
                    # La clasificación del artículo manda, pero si ese
                    # artículo quedó sin clasificar se usa la de la factura
                    # completa — que es justo para lo que existe, según dejó
                    # dicho la migración 007. Sin este respaldo, una factura
                    # bien clasificada aparecía como "Sin capítulo" solo
                    # porque el detalle venía en blanco, y el costo por
                    # capítulo quedaba corto sin que nadie lo notara.
                    "tipo_gasto_id": it.get("tipo_gasto_id") or fac.get("tipo_gasto_id"),
                    "capitulo_id": it.get("capitulo_id") or fac.get("capitulo_id"),
                    "actividad_id": it.get("actividad_id") or fac.get("actividad_id"),
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
                    "valor": fac.get("monto_efectivo", fac.get("total")),
                    "sentido": fac.get("sentido"),
                    "estado": fac.get("estado"),
                    "proyecto_id": fac.get("proyecto_id"),
                    "residente_id": fac.get("residente_id"),
                    "corte_id": fac.get("corte_id"),
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


@st.cache_data(ttl=900, show_spinner=False, max_entries=40)
def paginas_pdf(_sb, storage_path: str, max_paginas: int = 5) -> list[bytes]:
    """Convierte el PDF a imágenes PNG en el servidor.

    Mostrar el PDF con un <iframe> obliga a que el visor de PDF del
    navegador funcione dentro del sandbox de Streamlit Cloud, y eso NO se
    cumple siempre: depende del navegador, de su versión y de si el
    usuario tiene el visor desactivado — en móvil falla casi siempre.
    Se veía el ícono de documento roto aunque el archivo estuviera
    perfecto (verificado: 43 KB, cabecera %PDF-1.4, sin cabeceras que
    bloqueen el encuadre).

    Rasterizar aquí elimina esa dependencia: al navegador le llega una
    imagen, y una imagen la pinta cualquiera. El enlace de descarga del
    PDF original se mantiene aparte para quien necesite el archivo.

    El `_sb` va con guion bajo para que Streamlit no intente serializar
    el cliente al calcular la clave del caché.
    """
    try:
        contenido = _sb.storage.from_("documentos").download(storage_path)
    except Exception:
        return []

    import fitz

    imagenes = []
    try:
        with fitz.open(stream=contenido, filetype="pdf") as doc:
            for pagina in doc[:max_paginas]:
                # 144 dpi: se lee bien un número de factura sin inflar la
                # página con imágenes de varios MB.
                imagenes.append(pagina.get_pixmap(dpi=144).tobytes("png"))
    except Exception:
        return []
    return imagenes


def mostrar_documento(sb, d) -> None:
    """Enlace de descarga + previsualización del documento, en la misma
    pantalla (sin abrir otra pestaña). Lo usan Revisión y Todas las
    facturas: una sola implementación, mismo comportamiento en ambas."""
    url = url_documento(sb, d["storage_path"])
    nombre_doc = d.get("nombre_renombrado") or d.get("nombre_original") or "documento"
    mime_doc = str(d.get("mime", ""))

    if url:
        st.markdown(f"📄 [⬇️ Descargar original: {nombre_doc}]({url})")

    if mime_doc.endswith("pdf"):
        paginas = paginas_pdf(sb, d["storage_path"])
        if paginas:
            for n, png in enumerate(paginas, 1):
                st.image(
                    png,
                    use_container_width=True,
                    caption=f"Página {n} de {len(paginas)}" if len(paginas) > 1 else None,
                )
        elif url:
            st.caption("No se pudo previsualizar el PDF; el enlace de descarga sí funciona.")
    elif mime_doc.startswith("image/"):
        # una foto de recibo NO es un XML: se muestra tal cual
        if url:
            st.image(url, use_container_width=True)
    else:
        st.caption(
            "El archivo original es el XML técnico de la DIAN — la vista de arriba "
            "ya muestra sus datos de forma legible. Descárgalo solo si necesitas el XML crudo."
        )


# ------------------------------------------------------------- AIU y cortes
# La comision de Espacios es un % del costo (AIU del contrato). Las formulas
# se verificaron contra sus cifras reales antes de escribirlas:
#
#   Arrayanes 40   42.842.500 x 11%  = 4.712.675   (Total Comision)
#   Casa Vieja 61   1.684.702 x 14%  =   235.858   (AIU gastos, corte 1)
#   Casa Vieja 61     530.000 x 14%  =    74.200   (AIU pagos directos)
#
# El AIU de los pagos directos se calcula por separado del de los gastos:
# el pago directo del cliente NO pasa por la caja de Espacios, pero si
# genera comision. Mezclarlos daria una caja equivocada.


def base_aiu(factura, exento=None) -> float:
    """Base sobre la que se cobra la comision.

    Es el valor del costo antes de retenciones: la retencion es plata que
    se le retiene al proveedor y se le gira a la DIAN, no un menor costo
    del proyecto, asi que no puede reducir la comision.
    """
    if exento is None:
        exento = bool(factura.get("exento_aiu"))
    if exento:
        return 0.0
    total = factura.get("total")
    try:
        return float(total or 0)
    except (TypeError, ValueError):
        return 0.0


def comision(factura, exento, pct) -> float:
    """Comision de una factura: base x %AIU del proyecto."""
    try:
        pct = float(pct or 0)
    except (TypeError, ValueError):
        return 0.0
    return round(base_aiu(factura, exento) * pct, 2)


def corte_de_fecha(cortes_df, proyecto_id, fecha):
    """Corte al que cae una fecha dentro de un proyecto.

    Evita que alguien digite el corte factura por factura, que era una de
    las columnas que hoy llena Nadia a mano. Si los cortes aun no tienen
    fechas cargadas devuelve None y el corte se elige manualmente.
    """
    if cortes_df is None or getattr(cortes_df, "empty", True) or not proyecto_id or not fecha:
        return None
    fecha = pd.to_datetime(fecha, errors="coerce")
    if pd.isna(fecha):
        return None
    fecha = fecha.date()
    candidatos = cortes_df[cortes_df["proyecto_id"] == proyecto_id]
    for _, c in candidatos.sort_values("numero").iterrows():
        ini = pd.to_datetime(c.get("fecha_inicio"), errors="coerce")
        if pd.isna(ini) or fecha < ini.date():
            continue
        fin = pd.to_datetime(c.get("fecha_fin"), errors="coerce")
        if pd.isna(fin) or fecha <= fin.date():
            return c["id"]
    return None


# ---------------------------------------------------------------- cash flow
# Mecanica tomada de su hoja "Cash flow Casa Chipre" y verificada contra
# los dos primeros cortes de Casa Vieja 61 antes de escribirla:
#
#   subtotal      = gastos + AIU gastos + AIU pagos directos + GMF + otros
#   total egresos = subtotal + pagos directos + pagos exentos
#   caja final    = caja inicial + anticipos - subtotal
#
# Dos sutilezas que hay que respetar o los numeros no les cuadran:
#
#  1. Los PAGOS DIRECTOS (los que el cliente le paga al proveedor) suman
#     al costo del proyecto y generan comision, pero NO salen de la caja
#     de Espacios. Por eso entran en "total egresos" pero no en el
#     subtotal que descuenta la caja.
#  2. La etiqueta de su hoja dice "Subtotal = 1+2+3+4", pero el numero
#     real incluye tambien el 5 (otros gastos): en el corte 1 el subtotal
#     es 21.994.759,9 y 1+2+3+4 da 1.994.759,9. La etiqueta se quedo
#     desactualizada; se sigue el numero, no el rotulo.

CONCEPTOS_CASH_FLOW = [
    ("gastos", "1. Gastos"),
    ("aiu_gastos", "2. AIU gastos"),
    ("aiu_pagos_directos", "3. AIU pagos directos"),
    ("gmf", "4. GMF 4x1000"),
    ("otros_gastos", "5. Otros gastos"),
    ("subtotal", "Subtotal (sale de caja)"),
    ("pagos_directos", "Pagos directos del cliente"),
    ("pagos_exentos", "Otros pagos exentos"),
    ("total_egresos", "Total egresos"),
]


def cash_flow(facturas_pr, anticipos_pr, movimientos_pr, cortes_pr, pct_aiu) -> pd.DataFrame:
    """Cash flow del proyecto, un corte por columna.

    Recibe ya filtrado por proyecto. Devuelve un DataFrame con una fila
    por concepto y una columna por corte, en el mismo orden en que ellos
    lo leen. El saldo de caja se encadena: el final de un corte es el
    inicial del siguiente.
    """
    try:
        pct = float(pct_aiu or 0)
    except (TypeError, ValueError):
        pct = 0.0

    orden = []
    if cortes_pr is not None and not cortes_pr.empty:
        orden = list(cortes_pr.sort_values("numero")["id"])
    # Lo que no tenga corte asignado se muestra aparte en vez de perderse.
    orden.append(None)

    columnas, caja = {}, 0.0
    for corte_id in orden:
        f = _filtrar_corte(facturas_pr, corte_id)
        a = _filtrar_corte(anticipos_pr, corte_id)
        m = _filtrar_corte(movimientos_pr, corte_id)

        gastos = _suma(f[f["pagador"] != "cliente"], "total") if not f.empty else 0.0
        directos = _suma(f[f["pagador"] == "cliente"], "total") if not f.empty else 0.0
        exentos_aiu = _suma(f[f.get("exento_aiu") == True], "total") if not f.empty else 0.0  # noqa: E712

        gmf = _suma(m[m["concepto"] == "gmf"], "valor") if not m.empty else 0.0
        otros = _suma(m[m["concepto"] == "otros_gastos"], "valor") if not m.empty else 0.0
        pagos_exentos = _suma(m[m["concepto"] == "pago_exento"], "valor") if not m.empty else 0.0

        # Lo marcado como exento no entra a la base de la comision.
        aiu_gastos = round(max(gastos - exentos_aiu, 0) * pct, 2)
        aiu_directos = round(directos * pct, 2)

        subtotal = gastos + aiu_gastos + aiu_directos + gmf + otros
        anticipos_corte = _suma(a, "valor") if not a.empty else 0.0
        caja_inicial = caja
        caja = caja_inicial + anticipos_corte - subtotal

        columnas[corte_id] = {
            "caja_inicial": caja_inicial,
            "anticipos": anticipos_corte,
            "anticipos_bancos": _suma(a[a["modo_pago"] == "bancos"], "valor") if not a.empty else 0.0,
            "anticipos_efectivo": _suma(a[a["modo_pago"] == "efectivo"], "valor") if not a.empty else 0.0,
            "gastos": gastos,
            "aiu_gastos": aiu_gastos,
            "aiu_pagos_directos": aiu_directos,
            "gmf": gmf,
            "otros_gastos": otros,
            "subtotal": subtotal,
            "pagos_directos": directos,
            "pagos_exentos": pagos_exentos,
            "total_egresos": subtotal + directos + pagos_exentos,
            "caja_final": caja,
        }

    nombres = {}
    if cortes_pr is not None and not cortes_pr.empty:
        nombres = dict(zip(cortes_pr["id"], cortes_pr["nombre"]))
    nombres[None] = "Sin corte"

    tabla = pd.DataFrame(columnas)
    tabla.columns = [nombres.get(c, "Sin corte") for c in tabla.columns]
    return tabla


def costo_por_capitulo(sb, proyecto_id: str) -> pd.DataFrame:
    """Costo por capítulo y corte, YA sumado, para el usuario cliente.

    El cliente no puede leer `facturas`: el RLS se lo impide, porque esa
    tabla trae proveedores y valores por documento. La suma la hace una
    función SECURITY DEFINER en la base, que ella misma verifica que el
    proyecto consultado sea el suyo.
    """
    try:
        r = sb.rpc("costo_por_capitulo", {"p_proyecto": proyecto_id}).execute()
    except Exception:
        return pd.DataFrame()
    datos = pd.DataFrame(r.data or [])
    if datos.empty:
        return datos
    datos["capitulo"] = datos["capitulo"].fillna("Sin capítulo")
    datos["corte"] = datos["corte"].fillna("Sin corte")
    return datos


def costo_por_capitulo_local(sb, uid, proyecto_id, facturas_pr, cortes_pr) -> pd.DataFrame:
    """Lo mismo, pero para el equipo interno, calculado aquí.

    Se separa del camino del cliente a propósito: aquí sí se puede bajar
    al detalle de artículo, que es donde vive la clasificación real
    (una misma factura reparte cemento a Estructura y pintura a Acabados).
    """
    if facturas_pr is None or facturas_pr.empty:
        return pd.DataFrame()

    items = todos_los_items(sb, uid)
    caps = capitulos(sb, uid)
    nombre_cap = dict(zip(caps["id"], caps["nombre"])) if not caps.empty else {}
    nombre_corte = (
        dict(zip(cortes_pr["id"], cortes_pr["nombre"])) if not cortes_pr.empty else {}
    )

    detalle = detalle_clasificado(facturas_pr, items)
    if detalle.empty:
        return pd.DataFrame()

    detalle["capitulo"] = detalle["capitulo_id"].map(nombre_cap).fillna("Sin capítulo")
    detalle["corte"] = detalle["corte_id"].map(nombre_corte).fillna("Sin corte")
    return (
        detalle.groupby(["capitulo", "corte"], as_index=False)["valor"]
        .sum()
        .rename(columns={"valor": "total"})
    )


def _filtrar_corte(datos, corte_id):
    """Filas de un corte; corte_id None son las que no tienen corte."""
    if datos is None or datos.empty:
        return pd.DataFrame()
    if corte_id is None:
        return datos[datos["corte_id"].isna()]
    return datos[datos["corte_id"] == corte_id]


def _suma(datos, columna) -> float:
    if datos is None or datos.empty or columna not in datos:
        return 0.0
    return float(pd.to_numeric(datos[columna], errors="coerce").fillna(0).sum())


# ------------------------------------------------------------ flujo semanal
def presupuesto(sb, uid, proyecto_id: str | None = None) -> pd.DataFrame:
    q = sb.table("presupuesto").select("*").eq("user_id", uid)
    if proyecto_id:
        q = q.eq("proyecto_id", proyecto_id)
    return df(q.order("orden").execute())


def plan_semanal(sb, uid, presupuesto_ids: list[str]) -> pd.DataFrame:
    """Reparto semanal de las líneas de presupuesto indicadas."""
    if not presupuesto_ids:
        return pd.DataFrame()
    return df(
        sb.table("presupuesto_semana").select("*")
        .eq("user_id", uid).in_("presupuesto_id", presupuesto_ids)
        .order("anio").order("semana").execute()
    )


def semana_iso(fecha) -> tuple[int, int] | tuple[None, None]:
    """(año, semana) ISO de una fecha. Su flujo va por semanas."""
    f = pd.to_datetime(fecha, errors="coerce")
    if pd.isna(f):
        return (None, None)
    iso = f.isocalendar()
    return (int(iso[0]), int(iso[1]))


def planeado_vs_real(plan, detalle_real) -> pd.DataFrame:
    """Compara el plan semanal contra lo realmente ejecutado.

    `plan` viene de presupuesto_semana; `detalle_real` es el detalle
    clasificado (una fila por artículo) con su fecha. Se agrupa por semana
    ISO, que es como ellos leen el avance.

    El desfase se muestra en pesos y en %, pero el % se omite cuando no
    había nada planeado: dividir por cero daría "infinito" y una semana
    sin plan no es un incumplimiento del 100%, es una semana sin plan.
    """
    filas = {}
    if plan is not None and not plan.empty:
        for _, p in plan.iterrows():
            llave = (int(p["anio"]), int(p["semana"]))
            filas.setdefault(llave, {"planeado": 0.0, "real": 0.0})
            filas[llave]["planeado"] += float(p.get("valor") or 0)

    if detalle_real is not None and not detalle_real.empty:
        for _, r in detalle_real.iterrows():
            anio, semana = semana_iso(r.get("fecha_emision"))
            if anio is None:
                continue
            filas.setdefault((anio, semana), {"planeado": 0.0, "real": 0.0})
            filas[(anio, semana)]["real"] += float(r.get("valor") or 0)

    if not filas:
        return pd.DataFrame()

    tabla = pd.DataFrame(
        [
            {"anio": a, "semana": s, "periodo": f"{a}-S{s:02d}", **v}
            for (a, s), v in sorted(filas.items())
        ]
    )
    tabla["desfase"] = tabla["real"] - tabla["planeado"]
    tabla["cumplimiento_%"] = [
        round(r / p * 100, 1) if p else None
        for r, p in zip(tabla["real"], tabla["planeado"])
    ]
    tabla["planeado_acum"] = tabla["planeado"].cumsum()
    tabla["real_acum"] = tabla["real"].cumsum()
    return tabla


# -------------------------------------------------------------- vocabularios
# Estas listas tienen que coincidir EXACTAMENTE con los CHECK de la base
# (migracion 013) y con lo que escribe el worker. Antes estaban repetidas
# en cada pantalla y en dian_xml.py, y al ampliarlas se desincronizaban:
# la base rechazaba un valor que la pantalla si ofrecia. Un solo sitio.
#
# Las etiquetas son las que ellos usan en su matriz; el valor guardado es
# el slug, para no depender de tildes ni mayusculas.
METODOS_PAGO = {
    "efectivo": "Efectivo",
    "transferencia": "Transferencia",
    "cheque": "Cheque",
    "tarjeta_credito": "Tarjeta Crédito",
    "tarjeta_credito_vr": "Tarjeta Crédito VR",
    "tarjeta_debito": "Tarjeta Débito",
    "cuentas_x_pagar": "Cuentas x Pagar",
    "pago_directo_cliente": "Pago Directo Cliente",
    "anulada": "Anulada",
}

FORMAS_PAGO = {
    "contado": "Contado",
    "credito": "Crédito",
    "abono": "Abono",
    "legalizacion_anticipo": "Legalización anticipo",
    "anulada": "Anulada",
}

ESTADOS_PAGO = {
    "pendiente": "Pendiente de pago",
    "parcial": "Parcialmente pagada",
    "pagada": "Pagada",
    "pendiente_reporte": "Pendiente reporte de pago",
    "anulada": "Anulada",
}

LEGALIZACION = {"encima": "Encima", "debajo": "Debajo"}

PAGADOR = {"empresa": "Espacios Creativos", "cliente": "Pago Directo Cliente", "mixto": "Mixto"}

PAGADOR_MODO = {
    "espacios": "Espacios Creativos paga todo",
    "cliente": "El cliente paga directo",
    "mixto": "Mixto (se define factura por factura)",
}

MODOS_PAGO_INGRESO = {
    "bancos": "Bancos",
    "efectivo": "Efectivo",
    "pago_directo": "Pago Directo",
    "por_identificar": "Por identificar",
}


def opciones(vocabulario: dict, incluir_vacio: bool = True) -> list[str]:
    """Claves de un vocabulario para un selectbox."""
    return (["", *vocabulario] if incluir_vacio else list(vocabulario))


def etiqueta(vocabulario: dict, clave) -> str:
    """Nombre legible de un valor guardado; si no esta en el vocabulario se
    muestra tal cual en vez de romper (datos viejos o importados)."""
    if not clave:
        return ""
    return vocabulario.get(str(clave), str(clave))


def indice_de(opciones_lista: list[str], valor) -> int:
    """Posicion de `valor` en la lista, o 0 si no esta.

    Existe porque `list.index()` revienta con ValueError cuando el dato
    guardado no esta entre las opciones — paso de verdad, con un NaN de
    pandas que ademas es "truthy", asi que un `or ""` no lo atajaba.
    """
    if valor is None:
        return 0
    try:
        if valor != valor:            # NaN de pandas
            return 0
    except TypeError:
        pass
    valor = str(valor)
    return opciones_lista.index(valor) if valor in opciones_lista else 0


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


def catalogo_obra() -> dict:
    """Capítulos y actividades reales de la constructora.

    Salen de su propio archivo: el catálogo maestro es la hoja LCAPITULOS
    de la matriz, pero 96 de los 154 nombres venían pegados sin espacios
    ("Marcacioneimplantaciondelacasaenterreno"). La hoja Portada del Cash
    Flow trae esos mismos códigos bien escritos, así que el nombre se toma
    de ahí cuando existe. Ningún nombre es inventado: los dos vienen de
    archivos suyos.
    """
    import json
    from pathlib import Path

    ruta = Path(__file__).with_name("capitulos_obra.json")
    return json.loads(ruta.read_text(encoding="utf-8"))


def instalar_catalogo_obra(sb, uid) -> dict:
    """Carga (o actualiza) capítulos y actividades con el catálogo real.

    ACTUALIZA lo que ya existe en vez de duplicarlo, que es lo que pidió
    el usuario: las dimensiones ya estaban creadas desde la migración 005.
    El emparejamiento va por CÓDIGO cuando lo hay ("1.02") y si no por
    nombre, de modo que correrlo dos veces no crea nada repetido.
    """
    cat = catalogo_obra()
    resumen = {"capitulos_nuevos": 0, "capitulos_actualizados": 0,
               "actividades_nuevas": 0, "actividades_actualizadas": 0}

    existentes = df(sb.table("capitulos").select("*").eq("user_id", uid).execute())
    por_codigo = {}
    por_nombre = {}
    if not existentes.empty:
        for _, c in existentes.iterrows():
            if c.get("codigo"):
                por_codigo[str(c["codigo"])] = c["id"]
            por_nombre[_norm(c["nombre"])] = c["id"]

    ids_cap = {}
    for i, cap in enumerate(cat["capitulos"]):
        actual = por_codigo.get(cap["codigo"]) or por_nombre.get(_norm(cap["nombre"]))
        fila = {"nombre": cap["nombre"], "codigo": cap["codigo"], "orden": i}
        if actual:
            sb.table("capitulos").update(fila).eq("id", actual).execute()
            ids_cap[cap["codigo"]] = actual
            resumen["capitulos_actualizados"] += 1
        else:
            r = sb.table("capitulos").insert({"user_id": uid, **fila}).execute()
            ids_cap[cap["codigo"]] = r.data[0]["id"]
            resumen["capitulos_nuevos"] += 1

    act_ex = df(sb.table("actividades").select("*").eq("user_id", uid).execute())
    act_codigo, act_nombre = {}, {}
    if not act_ex.empty:
        for _, a in act_ex.iterrows():
            if a.get("codigo"):
                act_codigo[str(a["codigo"])] = a["id"]
            act_nombre[(a.get("capitulo_id"), _norm(a["nombre"]))] = a["id"]

    for act in cat["actividades"]:
        cap_id = ids_cap.get(act["capitulo"])
        actual = (act["codigo"] and act_codigo.get(act["codigo"])) or act_nombre.get(
            (cap_id, _norm(act["nombre"]))
        )
        fila = {"nombre": act["nombre"], "codigo": act["codigo"], "capitulo_id": cap_id}
        if actual:
            sb.table("actividades").update(fila).eq("id", actual).execute()
            resumen["actividades_actualizadas"] += 1
        else:
            r = sb.table("actividades").insert({"user_id": uid, **fila}).execute()
            # El indice en memoria se actualiza DURANTE el bucle: si el
            # catalogo trajera dos veces el mismo nombre en un capitulo, la
            # segunda pasada debe encontrar la fila recien creada y
            # actualizarla, no chocar contra el unique de la base. Paso con
            # el 12.01 repetido de URBANISMO y dejo la carga a medias.
            act_nombre[(cap_id, _norm(act["nombre"]))] = r.data[0]["id"]
            if act["codigo"]:
                act_codigo[act["codigo"]] = r.data[0]["id"]
            resumen["actividades_nuevas"] += 1
    return resumen


def _norm(texto) -> str:
    """Nombre comparable: sin tildes, sin dobles espacios, en minúsculas.
    Sus archivos escriben el mismo capítulo de varias formas."""
    import unicodedata

    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.lower().split())


def cop(v) -> str:
    try:
        return f"${v:,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return "-"
