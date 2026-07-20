"""Orquestador: barre el buzón, extrae, deduplica, calcula y guarda.

Capas de deduplicación (en orden):
  1. gmail_message_id  -> un correo nunca se procesa dos veces
  2. CUFE              -> una factura electrónica nunca se duplica
  3. hash del adjunto  -> el mismo archivo reenviado se reconoce
  4. heurística ingresos (monto+fecha) -> se marca posible duplicado, decide el humano

Ejecutar:  python -m worker.sync            (ventana normal)
           BACKFILL_DESDE=2026-01-01 python -m worker.sync   (barrido inicial)
"""
from __future__ import annotations

import hashlib
import sys

from . import clasificador, dian_xml, gmail_client, ocr, pdf_evidencia, retenciones
from .config import Config
from .storage import Store, nombre_renombrado


def procesar_mensaje(cfg: Config, store: Store, msg: dict, contexto: dict) -> str:
    """Devuelve el resultado para correos_procesados."""
    creadas = 0

    # --- adjuntos: ZIP/XML DIAN primero, luego PDF suelto
    for nombre, contenido in msg["adjuntos"]:
        ext = nombre.lower().rsplit(".", 1)[-1] if "." in nombre else ""
        h = hashlib.sha256(contenido).hexdigest()

        xmls = []
        if ext == "zip":
            try:
                xmls = dian_xml.extraer_xml_de_zip(contenido)
            except Exception:
                pass
        elif ext == "xml":
            xmls = [contenido]

        # Dedup por hash del archivo: si ya se proceso, no se re-inserta,
        # pero SI se repara lo que haya quedado incompleto por un fallo
        # parcial (factura sin documento o sin items). Antes se hacia
        # `continue` a ciegas y la factura quedaba mutilada para siempre.
        if store.hash_existe(h):
            _reparar_incompletas(store, h, contenido, xmls, ext, nombre)
            continue

        fids_de_este_zip = []
        for xml in xmls:
            datos = dian_xml.parsear_factura(xml)
            if not datos:
                continue
            f = datos["factura"]
            if f.get("cufe") and store.cufe_existe(f["cufe"]):
                # misma logica de reparacion para la capa CUFE
                _reparar_por_cufe(store, f["cufe"], xml, contenido, ext, nombre)
                continue
            f["gmail_message_id"] = msg["id"]
            f["remitente_correo"] = (msg.get("remitente") or "")[:200] or None
            f["hash_adjunto"] = h
            # El concepto de retención (compras/servicios/honorarios/arriendos)
            # define la tarifa de retefuente. Antes se derivaba del "tipo de
            # gasto"; esa dimensión se quitó de la app, así que ahora se sugiere
            # directo — sin ella, todo caía a "compras" y servicios/honorarios/
            # arriendos recibían tarifa equivocada (regresión que evitamos).
            f["concepto_retencion"] = clasificador.sugerir_concepto_retencion(cfg, f)
            f.update(retenciones.calcular(f, contexto["reglas"], contexto["uvt"]))
            f.pop("concepto_retencion", None)
            fid = store.insertar_factura(f, datos["items"])
            base = nombre_renombrado(f)  # termina en .pdf
            store.subir_documento(fid, nombre, xml, "application/xml", base[:-4] + ".xml")
            fids_de_este_zip.append((fid, base))
            creadas += 1

        # El ZIP DIAN también trae la representación en PDF de la factura —
        # esa es la que un humano quiere ver. Si el zip generó exactamente
        # una factura, sus PDFs le pertenecen sin ambigüedad.
        if ext == "zip" and len(fids_de_este_zip) == 1:
            fid, base = fids_de_este_zip[0]
            try:
                for nombre_pdf, pdf_bytes in dian_xml.extraer_pdfs_de_zip(contenido):
                    store.subir_documento(fid, nombre_pdf, pdf_bytes, "application/pdf", base)
            except Exception:
                pass  # sin PDF no se pierde nada critico: el XML ya quedo guardado

        if ext == "pdf" and not xmls:
            # PDF suelto sin XML: la IA extrae, humano confirma
            contenido = pdf_evidencia.desbloquear_pdf(contenido, cfg.pdf_passwords)
            texto = _texto_de_pdf(contenido)
            if ocr.pdf_es_escaneado(contenido):
                # PDF escaneado: es una imagen dentro de un PDF, no hay texto
                # que leer -> rasterizar y pasar por el modelo de visión.
                datos = clasificador.extraer_de_imagen(cfg, ocr.pdf_a_imagenes(contenido))
                fuente_doc = "ocr"
            else:
                datos = clasificador.extraer_de_texto(
                    cfg, f"{msg['asunto']}\n{texto or msg['cuerpo']}"
                )
                fuente_doc = "pdf"
            if datos and datos.get("total"):
                f = _factura_desde_ia(datos, msg, h, fuente=fuente_doc)
                fid = store.insertar_factura(f, _items_desde_ia(datos))
                store.subir_documento(fid, nombre, contenido, "application/pdf", nombre_renombrado(f))
                creadas += 1

        # --- foto o escaneo suelto (recibo, cuenta de cobro, consignación)
        if ocr.es_imagen(nombre):
            imagen = ocr.comprimir_imagen(contenido)
            datos = clasificador.extraer_de_imagen(cfg, [imagen])
            if datos and datos.get("total"):
                f = _factura_desde_ia(datos, msg, h, fuente="ocr")
                fid = store.insertar_factura(f, _items_desde_ia(datos))
                mime = f"image/{'jpeg' if ext in ('jpg', 'jpeg') else ext}"
                store.subir_documento(fid, nombre, contenido, mime, nombre_renombrado(f))
                creadas += 1

    # --- sin adjuntos: ¿consignación u otro soporte en el cuerpo?
    if not creadas and dian_xml.parece_consignacion(msg["asunto"], msg["cuerpo"]):
        datos = clasificador.extraer_de_texto(cfg, f"{msg['asunto']}\n{msg['cuerpo']}")
        if datos and datos.get("total"):
            datos["sentido"] = "ingreso"
            datos["tipo_documento"] = "consignacion"
            f = _factura_desde_ia(datos, msg, hash_adjunto=None, fuente="correo")
            f["posible_duplicado_de"] = store.buscar_ingreso_parecido(
                f["total"], f.get("fecha_emision") or ""
            )
            fid = store.insertar_factura(f, [])
            pdf = pdf_evidencia.correo_a_pdf(
                msg["asunto"], msg["remitente"], msg["fecha"], msg["cuerpo"]
            )
            if pdf:
                store.subir_documento(fid, "correo.pdf", pdf, "application/pdf", nombre_renombrado(f))
            creadas += 1

    return "factura" if creadas else "ignorado"


def _completar_factura(store: Store, factura: dict, xml: bytes, zip_bytes: bytes | None,
                       ext: str, nombre_adjunto: str) -> None:
    """Rellena lo que le falte a una factura ya existente: items y/o
    documentos (XML y el PDF visual del ZIP). Idempotente: solo agrega lo
    que no esta."""
    fid = factura["id"]
    base = nombre_renombrado(factura)

    if not store.tiene_items(fid):
        datos = dian_xml.parsear_factura(xml)
        if datos and datos["items"]:
            store.insertar_items(fid, datos["items"])
            print(f"  + reparados {len(datos['items'])} items de la factura {factura.get('numero')}")

    mimes = store.mimes_de_factura(fid)
    if "application/xml" not in mimes:
        store.subir_documento(fid, nombre_adjunto, xml, "application/xml", base[:-4] + ".xml")
        print(f"  + reparado XML de la factura {factura.get('numero')}")
    if "application/pdf" not in mimes and ext == "zip" and zip_bytes:
        try:
            pdfs = dian_xml.extraer_pdfs_de_zip(zip_bytes)
            if pdfs:
                store.subir_documento(fid, pdfs[0][0], pdfs[0][1], "application/pdf", base)
                print(f"  + reparado PDF de la factura {factura.get('numero')}")
        except Exception:
            pass


def _reparar_incompletas(store: Store, h: str, contenido: bytes, xmls: list[bytes],
                         ext: str, nombre_adjunto: str) -> None:
    """El adjunto ya se habia procesado (mismo hash). Verifica que la
    factura resultante haya quedado completa y repara si no."""
    factura = store.factura_por_hash(h)
    if not factura:
        return
    for xml in xmls:
        datos = dian_xml.parsear_factura(xml)
        if not datos:
            continue
        # con varias facturas en el zip, solo la que corresponde a este hash
        if factura.get("cufe") and datos["factura"].get("cufe") != factura["cufe"]:
            continue
        _completar_factura(store, factura, xml, contenido if ext == "zip" else None, ext, nombre_adjunto)
        return


def _reparar_por_cufe(store: Store, cufe: str, xml: bytes, contenido: bytes,
                      ext: str, nombre_adjunto: str) -> None:
    """Mismo CUFE ya registrado (reenvio del proveedor con otro archivo):
    no se duplica la factura, pero se aprovecha para completarla."""
    factura = store.factura_por_cufe(cufe)
    if factura:
        _completar_factura(store, factura, xml, contenido if ext == "zip" else None, ext, nombre_adjunto)


def _factura_desde_ia(datos: dict, msg: dict, hash_adjunto: str | None, fuente: str) -> dict:
    return {
        "sentido": datos.get("sentido") or "gasto",
        "tipo_documento": datos.get("tipo_documento") or "otro",
        "numero": datos.get("numero"),
        "proveedor_nombre": datos.get("proveedor_nombre") or msg["remitente"][:100],
        "proveedor_nit": datos.get("proveedor_nit"),
        "fecha_emision": datos.get("fecha_emision"),
        "total": float(datos.get("total") or 0),
        "iva": float(datos.get("iva") or 0),
        "descripcion": (datos.get("descripcion") or msg["asunto"])[:2000],
        "confianza": "baja",
        "fuente": fuente,
        "gmail_message_id": msg["id"],
        "remitente_correo": (msg.get("remitente") or "")[:200] or None,
        "hash_adjunto": hash_adjunto,
    }


def _texto_de_pdf(contenido: bytes) -> str:
    return ocr.texto_de_pdf(contenido)[:15000]


def _items_desde_ia(datos: dict) -> list[dict]:
    """Artículos que el modelo de visión alcanzó a leer. Van con los mismos
    campos que los del XML para que Revisión los trate igual; lo que el
    modelo no distinga queda en None y el humano lo completa."""
    items = []
    for it in datos.get("items") or []:
        desc = (it.get("descripcion") or "").strip()
        if not desc:
            continue
        # numerar sobre los artículos REALMENTE agregados: si se enumerara
        # la lista original, descartar uno vacío dejaría huecos (1, 3, 4...)
        # y la reparación por número de línea dejaría de casar.
        items.append(
            {
                "linea": len(items) + 1,
                "descripcion": desc[:500],
                "cantidad": it.get("cantidad"),
                "precio_unitario": it.get("precio_unitario"),
                "total": it.get("total"),
            }
        )
    return items


def main() -> int:
    cfg = Config()
    cfg.validar()
    store = Store(cfg)
    svc = gmail_client.servicio(cfg)

    contexto = {
        "reglas": store.reglas_retencion(),
        "uvt": store.uvt(),
    }

    ids = gmail_client.buscar_mensajes(svc, cfg)
    nuevos, errores = 0, 0
    for msg_id in ids:
        if store.correo_procesado(msg_id):  # capa 1
            continue
        try:
            msg = gmail_client.leer_mensaje(svc, msg_id)
            resultado = procesar_mensaje(cfg, store, msg, contexto)
            store.marcar_correo(msg_id, resultado, msg["asunto"])
            if resultado == "factura":
                nuevos += 1
        except Exception as e:  # un correo malo no tumba el barrido
            errores += 1
            store.marcar_correo(msg_id, "error", str(e))

    print(f"Correos revisados: {len(ids)} | documentos nuevos: {nuevos} | errores: {errores}")
    return 0 if errores == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
