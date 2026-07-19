"""Reprocesa los documentos XML ya guardados en Storage para llenar los
campos que el parser no extraía antes (descuento/IVA/codigo por articulo,
notas, orden de compra, medio de pago).

Ademas rescata el PDF con la representación visual de la factura, que el
ZIP DIAN siempre trajo pero el sistema descartaba:
  - Si el documento guardado aun es el ZIP viejo (bug), extrae de ahi
    tanto el XML correcto como el PDF.
  - Si el ZIP ya fue reemplazado por solo-XML en una corrida anterior
    (el PDF se perdió de Storage), recupera el mensaje original de Gmail
    por gmail_message_id y saca el PDF de su adjunto.

Ejecutar:  python -m worker.reprocesar_items
"""
from __future__ import annotations

from . import dian_xml, gmail_client
from .config import Config
from .paginacion import traer_todo
from .storage import Store, nombre_renombrado


def _pdfs_desde_gmail(svc, factura: dict) -> list[tuple[str, bytes]]:
    """Recupera los PDFs del adjunto ZIP del correo original de esta factura.
    Con varios ZIPs en el correo, elige el que contiene el XML de ESTA
    factura (por CUFE); con uno solo, lo usa directo."""
    msg = gmail_client.leer_mensaje(svc, factura["gmail_message_id"])
    zips = [(n, c) for n, c in msg["adjuntos"] if n.lower().endswith(".zip")]
    if not zips:
        return []
    if len(zips) > 1 and factura.get("cufe"):
        for _, contenido_zip in zips:
            try:
                for xml in dian_xml.extraer_xml_de_zip(contenido_zip):
                    datos = dian_xml.parsear_factura(xml)
                    if datos and datos["factura"].get("cufe") == factura["cufe"]:
                        return dian_xml.extraer_pdfs_de_zip(contenido_zip)
            except Exception:
                continue
        return []
    return dian_xml.extraer_pdfs_de_zip(zips[0][1])


def _elegir_xml(contenido: bytes, factura: dict) -> tuple[bytes, dict] | None:
    """Devuelve (xml_bytes, datos_parseados) que corresponde a ESTA factura,
    ya sea que `contenido` sea el XML de verdad o el ZIP viejo (bug)."""
    candidatos: list[tuple[bytes, dict]] = []

    try:
        datos = dian_xml.parsear_factura(contenido)
        if datos:
            candidatos.append((contenido, datos))
    except Exception:
        pass  # `contenido` no es XML valido (ej. es el ZIP viejo del bug) -> se intenta como zip abajo

    if not candidatos:
        try:
            for xml in dian_xml.extraer_xml_de_zip(contenido):
                datos = dian_xml.parsear_factura(xml)
                if datos:
                    candidatos.append((xml, datos))
        except Exception:
            pass

    if not candidatos:
        return None
    if len(candidatos) == 1:
        return candidatos[0]

    # Zip con varias facturas: elegir la que coincide con esta (por CUFE, o numero si no hay CUFE)
    for xml_bytes, datos in candidatos:
        f2 = datos["factura"]
        if factura.get("cufe") and f2.get("cufe") == factura["cufe"]:
            return xml_bytes, datos
        if not factura.get("cufe") and f2.get("numero") and f2.get("numero") == factura.get("numero"):
            return xml_bytes, datos
    return None


def reprocesar() -> None:
    cfg = Config()
    cfg.validar()
    store = Store(cfg)
    sb = store.sb

    # PostgREST corta en 1000 filas por respuesta; traer_todo pagina los
    # 4000+ documentos (un solo sitio con esa logica en el worker).
    docs = traer_todo(
        sb.table("documentos")
        .select("id, factura_id, storage_path")
        .eq("user_id", cfg.user_id)
        .eq("mime", "application/xml")
        .order("id")
    )

    revisados = actualizados = reempaquetados = errores = 0
    pdfs_zip = pdfs_gmail = 0
    svc_gmail = None  # se crea solo si hace falta recuperar desde Gmail

    for d in docs:
        revisados += 1
        try:
            contenido = sb.storage.from_("documentos").download(d["storage_path"])

            fila = sb.table("facturas").select("*").eq("id", d["factura_id"]).limit(1).execute().data
            if not fila:
                continue
            factura = fila[0]

            elegido = _elegir_xml(contenido, factura)
            if elegido is None:
                errores += 1
                continue
            xml_bytes, datos = elegido
            f2 = datos["factura"]

            # --- PDF visual de la factura (antes de reemplazar el ZIP)
            tiene_pdf = bool(
                sb.table("documentos")
                .select("id")
                .eq("factura_id", factura["id"])
                .eq("mime", "application/pdf")
                .limit(1)
                .execute()
                .data
            )
            if not tiene_pdf:
                pdfs: list[tuple[str, bytes]] = []
                origen = ""
                if xml_bytes != contenido:  # el documento guardado aun es el ZIP
                    try:
                        pdfs, origen = dian_xml.extraer_pdfs_de_zip(contenido), "zip"
                    except Exception:
                        pdfs = []
                elif factura.get("gmail_message_id"):  # ZIP ya descartado: recuperar del correo
                    try:
                        if svc_gmail is None:
                            svc_gmail = gmail_client.servicio(cfg)
                        pdfs, origen = _pdfs_desde_gmail(svc_gmail, factura), "gmail"
                    except Exception:
                        pdfs = []
                if pdfs:
                    nombre_pdf, pdf_bytes = pdfs[0]
                    store.subir_documento(
                        factura["id"], nombre_pdf, pdf_bytes, "application/pdf", nombre_renombrado(factura)
                    )
                    if origen == "zip":
                        pdfs_zip += 1
                    else:
                        pdfs_gmail += 1

            cambios_factura = {
                campo: f2[campo]
                for campo in ("notas", "orden_compra", "moneda", "metodo_pago")
                if not factura.get(campo) and f2.get(campo)
            }
            if cambios_factura:
                sb.table("facturas").update(cambios_factura).eq("id", factura["id"]).execute()

            items_actuales = (
                sb.table("factura_items").select("id, linea").eq("factura_id", factura["id"]).execute().data
                or []
            )
            por_linea = {it["linea"]: it["id"] for it in items_actuales}
            for it2 in datos["items"]:
                item_id = por_linea.get(it2["linea"])
                if not item_id:
                    continue
                sb.table("factura_items").update(
                    {
                        "descuento": it2.get("descuento"),
                        "iva": it2.get("iva"),
                        "tarifa_iva": it2.get("tarifa_iva"),
                        "codigo_articulo": it2.get("codigo_articulo"),
                    }
                ).eq("id", item_id).execute()

            if xml_bytes != contenido:
                sb.storage.from_("documentos").upload(
                    d["storage_path"], xml_bytes, {"content-type": "application/xml", "upsert": "true"}
                )
                reempaquetados += 1

            actualizados += 1
        except Exception as e:
            errores += 1
            print(f"  ! error en documento {d['id']}: {e}")

        if revisados % 200 == 0:
            print(f"  ... {revisados}/{len(docs)} revisados")

    print(
        f"Documentos revisados: {revisados} | actualizados: {actualizados} | "
        f"reempaquetados (zip -> xml correcto): {reempaquetados} | "
        f"PDFs rescatados del zip: {pdfs_zip} | PDFs recuperados de Gmail: {pdfs_gmail} | "
        f"errores: {errores}"
    )


if __name__ == "__main__":
    reprocesar()
