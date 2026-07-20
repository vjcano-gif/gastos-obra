"""Formato de pesos, normalización de texto y vista de documentos."""
from __future__ import annotations

import pandas as pd
import streamlit as st

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


def texto(valor, defecto: str = "") -> str:
    """Texto seguro para títulos y etiquetas.

    `valor or defecto` NO sirve cuando el dato viene de pandas: el NaN es
    "truthy", así que pasa el `or` y luego revienta al cortarlo ([:45]) o
    formatearlo. Pasó en Revisión con facturas importadas de la matriz sin
    nombre de proveedor. `pd.isna` cubre None y NaN por igual."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return defecto
    return str(valor)


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


@st.cache_data(ttl=900, show_spinner=False, max_entries=60)
def paginas_de_documento(_sb, storage_path: str, mime: str, max_paginas: int = 5) -> list[bytes]:
    """Páginas PNG a mostrar de un documento, sea lo que sea.

    - PDF -> se rasteriza.
    - ZIP (o XML mal etiquetado que en realidad es el ZIP de la DIAN) -> se
      SACA el PDF de adentro y se rasteriza. Es lo que pidió el usuario:
      "del xml se saca el pdf". Un ZIP DIAN trae el fv*.pdf junto al XML.
    - Otra cosa (XML crudo de verdad) -> no hay imagen, devuelve [].
    """
    try:
        contenido = _sb.storage.from_("documentos").download(storage_path)
    except Exception:
        return []

    # Un ZIP empieza con "PK". Aunque el mime diga xml, si el archivo es un
    # ZIP se le saca el PDF (datos viejos guardados antes del arreglo).
    if contenido[:2] == b"PK" or "zip" in (mime or ""):
        import io
        import zipfile

        try:
            with zipfile.ZipFile(io.BytesIO(contenido)) as z:
                pdf = next((n for n in z.namelist() if n.lower().endswith(".pdf")), None)
                if pdf:
                    contenido = z.read(pdf)
                else:
                    return []
        except Exception:
            return []
    elif not (mime.endswith("pdf") or contenido[:4] == b"%PDF"):
        return []

    return _rasterizar(contenido, max_paginas)


def _rasterizar(pdf_bytes: bytes, max_paginas: int) -> list[bytes]:
    import fitz

    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            return [doc[i].get_pixmap(dpi=144).tobytes("png") for i in range(min(len(doc), max_paginas))]
    except Exception:
        return []


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


def _nombre(d) -> str:
    return d.get("nombre_renombrado") or d.get("nombre_original") or "documento"


def mostrar_documentos(sb, docs) -> None:
    """Previsualiza la factura y ofrece descargar TODOS sus archivos.

    Recibe el conjunto de documentos de UNA factura (no uno solo) y elige
    el mejor para mostrar: primero un PDF o imagen; si solo hay XML, le
    saca el PDF de adentro (el ZIP de la DIAN lo trae). Los enlaces de
    descarga se muestran para todos los archivos que haya.
    """
    if docs is None or (hasattr(docs, "empty") and docs.empty):
        st.caption("📭 Este movimiento no tiene documento digital (viene de la matriz de Excel).")
        return

    filas = [d for _, d in docs.iterrows()] if hasattr(docs, "iterrows") else list(docs)

    # --- enlaces de descarga de todo lo que haya
    for d in filas:
        url = url_documento(sb, d["storage_path"])
        if url:
            st.markdown(f"📄 [⬇️ Descargar: {_nombre(d)}]({url})")

    # --- una sola previsualización: el mejor documento
    def rango(d):  # prioridad: imagen y pdf antes que xml
        m = str(d.get("mime", ""))
        return 0 if m.startswith("image/") else (1 if m.endswith("pdf") else 2)

    mejor = sorted(filas, key=rango)[0]
    mime = str(mejor.get("mime", ""))

    if mime.startswith("image/"):
        u = url_documento(sb, mejor["storage_path"])
        if u:
            st.image(u, use_container_width=True)
        return

    # pdf, o xml/zip del que se saca el pdf
    paginas = paginas_de_documento(sb, mejor["storage_path"], mime)
    if paginas:
        for n, png in enumerate(paginas, 1):
            st.image(png, use_container_width=True,
                     caption=f"Página {n} de {len(paginas)}" if len(paginas) > 1 else None)
    else:
        st.caption(
            "No hay imagen para previsualizar (el documento es el XML técnico de la "
            "DIAN, sin PDF adjunto). Los datos ya se ven arriba; descarga el XML si lo necesitas."
        )


def mostrar_documento(sb, d) -> None:
    """Compatibilidad: un solo documento. Nuevas pantallas usan
    mostrar_documentos (plural), que elige el mejor de todos."""
    mostrar_documentos(sb, [d])


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


