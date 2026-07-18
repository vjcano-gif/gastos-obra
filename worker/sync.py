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

from . import clasificador, dian_xml, gmail_client, pdf_evidencia, retenciones
from .config import Config
from .storage import Store, nombre_renombrado


def procesar_mensaje(cfg: Config, store: Store, msg: dict, contexto: dict) -> str:
    """Devuelve el resultado para correos_procesados."""
    creadas = 0

    # --- adjuntos: ZIP/XML DIAN primero, luego PDF suelto
    for nombre, contenido in msg["adjuntos"]:
        ext = nombre.lower().rsplit(".", 1)[-1] if "." in nombre else ""
        h = hashlib.sha256(contenido).hexdigest()
        if store.hash_existe(h):
            continue

        xmls = []
        if ext == "zip":
            try:
                xmls = dian_xml.extraer_xml_de_zip(contenido)
            except Exception:
                pass
        elif ext == "xml":
            xmls = [contenido]

        fids_de_este_zip = []
        for xml in xmls:
            datos = dian_xml.parsear_factura(xml)
            if not datos:
                continue
            f = datos["factura"]
            if f.get("cufe") and store.cufe_existe(f["cufe"]):
                continue  # capa CUFE
            f["gmail_message_id"] = msg["id"]
            f["hash_adjunto"] = h
            # Clasificar PRIMERO y derivar el concepto de retención del tipo
            # de gasto sugerido — antes se calculaba todo como "compras", así
            # que servicios/honorarios/arriendos recibían tarifa equivocada.
            f["tipo_gasto_id"] = clasificador.sugerir_tipo_gasto(
                cfg, f, contexto["tipos"], contexto["historial"]
            )
            concepto = next(
                (
                    t.get("concepto_retencion")
                    for t in contexto["tipos"]
                    if t.get("id") == f["tipo_gasto_id"]
                ),
                None,
            )
            f["concepto_retencion"] = concepto or "compras"
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
            texto = _texto_de_pdf(contenido) or msg["cuerpo"]
            datos = clasificador.extraer_de_texto(cfg, f"{msg['asunto']}\n{texto}")
            if datos and datos.get("total"):
                f = _factura_desde_ia(datos, msg, h, fuente="pdf")
                fid = store.insertar_factura(f, [])
                store.subir_documento(fid, nombre, contenido, "application/pdf", nombre_renombrado(f))
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
        "hash_adjunto": hash_adjunto,
    }


def _texto_de_pdf(contenido: bytes) -> str:
    try:
        import fitz

        with fitz.open(stream=contenido, filetype="pdf") as doc:
            return "\n".join(p.get_text() for p in doc)[:15000]
    except Exception:
        return ""


def main() -> int:
    cfg = Config()
    cfg.validar()
    store = Store(cfg)
    svc = gmail_client.servicio(cfg)

    contexto = {
        "reglas": store.reglas_retencion(),
        "uvt": store.uvt(),
        "tipos": store.sb.table("tipos_gasto").select("*").eq("user_id", store.uid).execute().data
        or [],
        "historial": store.historial_clasificacion(),
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
