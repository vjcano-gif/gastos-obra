"""Reprocesa los documentos XML ya guardados en Storage para llenar los
campos que el parser no extraía antes (descuento/IVA/codigo por articulo,
notas, orden de compra, medio de pago) — sin volver a tocar Gmail.

De paso corrige el bug donde el documento guardado era el ZIP completo
(mal etiquetado como XML): si detecta eso, sube el XML individual
correcto al mismo storage_path.

Ejecutar:  python -m worker.reprocesar_items
"""
from __future__ import annotations

from . import dian_xml
from .config import Config
from .storage import Store


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

    docs = (
        sb.table("documentos")
        .select("id, factura_id, storage_path")
        .eq("user_id", cfg.user_id)
        .eq("mime", "application/xml")
        .execute()
        .data
        or []
    )

    revisados = actualizados = reempaquetados = errores = 0

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
        f"reempaquetados (zip -> xml correcto): {reempaquetados} | errores: {errores}"
    )


if __name__ == "__main__":
    reprocesar()
