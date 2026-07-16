"""Parser del XML de facturación electrónica DIAN (UBL 2.1).

La factura llega como ZIP adjunto con un AttachedDocument que envuelve el
Invoice/CreditNote/DebitNote real. De aquí salen todos los campos exactos:
CUFE, NITs, fechas, totales, impuestos por tipo y el detalle línea a línea.
"""
from __future__ import annotations

import io
import re
import zipfile
from decimal import Decimal, InvalidOperation
from typing import Any

import xmltodict

# Códigos DIAN de TaxScheme
IMPUESTOS = {"01": "iva", "04": "impoconsumo", "05": "reteiva", "06": "retefuente", "07": "reteica"}


def _sin_ns(obj: Any) -> Any:
    """Quita prefijos de namespace de todas las llaves (cbc:ID -> ID)."""
    if isinstance(obj, dict):
        return {k.split(":")[-1]: _sin_ns(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sin_ns(x) for x in obj]
    return obj


def _texto(v: Any) -> str:
    if isinstance(v, dict):
        return str(v.get("#text", "")).strip()
    return str(v or "").strip()


def _num(v: Any) -> Decimal:
    try:
        return Decimal(_texto(v) or "0")
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _lista(v: Any) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def extraer_xml_de_zip(contenido_zip: bytes) -> list[bytes]:
    """Devuelve los XML dentro de un ZIP DIAN."""
    xmls = []
    with zipfile.ZipFile(io.BytesIO(contenido_zip)) as z:
        for nombre in z.namelist():
            if nombre.lower().endswith(".xml"):
                xmls.append(z.read(nombre))
    return xmls


def _desenvolver(xml_bytes: bytes) -> dict | None:
    """AttachedDocument lleva el Invoice real como CDATA en cac:Attachment."""
    doc = _sin_ns(xmltodict.parse(xml_bytes))
    if "AttachedDocument" in doc:
        adj = doc["AttachedDocument"]
        try:
            cdata = adj["Attachment"]["ExternalReference"]["Description"]
            interno = _texto(cdata) if not isinstance(cdata, str) else cdata
            if "<" in interno:
                return _sin_ns(xmltodict.parse(interno))
        except (KeyError, TypeError):
            return doc
    return doc


def parsear_factura(xml_bytes: bytes) -> dict | None:
    """Devuelve un dict listo para la tabla `facturas` + lista de ítems, o None."""
    doc = _desenvolver(xml_bytes)
    if not doc:
        return None

    tipo_doc, raiz = None, None
    for nombre, tipo in [("Invoice", "factura"), ("CreditNote", "nota_credito"), ("DebitNote", "nota_debito")]:
        if nombre in doc:
            raiz, tipo_doc = doc[nombre], tipo
            break
    if raiz is None:
        return None

    proveedor = raiz.get("AccountingSupplierParty", {}).get("Party", {})
    pt = _lista(proveedor.get("PartyTaxScheme"))
    prov_nombre = _texto((pt[0] if pt else {}).get("RegistrationName")) or _texto(
        proveedor.get("PartyName", {}).get("Name")
    )
    prov_nit = _texto((pt[0] if pt else {}).get("CompanyID"))

    cliente = raiz.get("AccountingCustomerParty", {}).get("Party", {})
    ct = _lista(cliente.get("PartyTaxScheme"))
    cli_nit = _texto((ct[0] if ct else {}).get("CompanyID"))

    # Impuestos y retenciones por código de TaxScheme
    montos = {v: Decimal("0") for v in IMPUESTOS.values()}
    for bloque in ("TaxTotal", "WithholdingTaxTotal"):
        for tt in _lista(raiz.get(bloque)):
            for sub in _lista(tt.get("TaxSubtotal")) or [tt]:
                cod = _texto(sub.get("TaxCategory", {}).get("TaxScheme", {}).get("ID"))
                campo = IMPUESTOS.get(cod)
                if campo:
                    montos[campo] += _num(sub.get("TaxAmount") or tt.get("TaxAmount"))

    totales = raiz.get("LegalMonetaryTotal", {})
    cargos = Decimal("0")
    for ac in _lista(raiz.get("AllowanceCharge")):
        if _texto(ac.get("ChargeIndicator")).lower() == "true":
            cargos += _num(ac.get("Amount"))

    pagos = _lista(raiz.get("PaymentMeans"))
    forma = _texto((pagos[0] if pagos else {}).get("ID"))
    vence = _texto((pagos[0] if pagos else {}).get("PaymentDueDate")) or _texto(raiz.get("DueDate"))

    items, descripciones = [], []
    lineas = _lista(raiz.get("InvoiceLine") or raiz.get("CreditNoteLine") or raiz.get("DebitNoteLine"))
    for i, ln in enumerate(lineas, start=1):
        desc = " ".join(_texto(d) for d in _lista(ln.get("Item", {}).get("Description")))
        cant = ln.get("InvoicedQuantity") or ln.get("CreditedQuantity") or ln.get("DebitedQuantity")
        unidad = cant.get("@unitCode", "") if isinstance(cant, dict) else ""
        items.append(
            {
                "linea": i,
                "descripcion": desc[:500],
                "cantidad": float(_num(cant)),
                "unidad": unidad,
                "precio_unitario": float(_num(ln.get("Price", {}).get("PriceAmount"))),
                "total": float(_num(ln.get("LineExtensionAmount"))),
            }
        )
        if desc:
            descripciones.append(desc)

    fecha = _texto(raiz.get("IssueDate"))
    return {
        "factura": {
            "tipo_documento": tipo_doc,
            "sentido": "gasto",
            "fuente": "xml",
            "cufe": _texto(raiz.get("UUID")) or None,
            "numero": _texto(raiz.get("ID")),
            "proveedor_nombre": prov_nombre,
            "proveedor_nit": prov_nit,
            "cliente_nit": cli_nit,
            "fecha_emision": fecha or None,
            "fecha_vencimiento": vence or None,
            "forma_pago": {"1": "contado", "2": "credito"}.get(forma),
            "valor_bruto": float(_num(totales.get("LineExtensionAmount"))),
            "descuentos": float(_num(totales.get("AllowanceTotalAmount"))),
            "iva": float(montos["iva"]),
            "impoconsumo": float(montos["impoconsumo"]),
            "cargos": float(cargos),
            "retenciones_xml": float(montos["retefuente"] + montos["reteiva"] + montos["reteica"]),
            "total": float(_num(totales.get("PayableAmount"))),
            "descripcion": " | ".join(descripciones)[:2000],
        },
        "items": items,
    }


PATRON_CONSIGNACION = re.compile(
    r"(consignaci[oó]n|abono|transferencia\s+recibida|pago\s+recibido)", re.IGNORECASE
)


def parece_consignacion(asunto: str, cuerpo: str) -> bool:
    return bool(PATRON_CONSIGNACION.search(f"{asunto} {cuerpo[:2000]}"))
