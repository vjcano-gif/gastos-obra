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

# Códigos UN/EDIFACT 4461 (PaymentMeansCode) más comunes en facturación
# electrónica colombiana -> nuestras categorías de metodo_pago. Lo que no
# está en este mapa se deja sin auto-llenar (mejor vacío que adivinar mal).
MEDIOS_PAGO_DIAN = {
    "10": "contado",       # efectivo
    "42": "transferencia", # consignación / transferencia bancaria
    "47": "transferencia", # débito a cuenta
    "48": "TC",            # tarjeta de crédito
    "49": "TD",            # tarjeta débito
}


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


def _descuento_linea(ln: dict) -> Decimal:
    """Suma los AllowanceCharge de la línea que son descuento (no recargo)."""
    total = Decimal("0")
    for ac in _lista(ln.get("AllowanceCharge")):
        if _texto(ac.get("ChargeIndicator")).lower() != "true":
            total += _num(ac.get("Amount"))
    return total


def _iva_linea(ln: dict) -> tuple[Decimal, Decimal]:
    """(monto de IVA, tarifa %) de la línea, leyendo su TaxTotal propio."""
    monto = Decimal("0")
    tarifa = Decimal("0")
    for tt in _lista(ln.get("TaxTotal")):
        for sub in _lista(tt.get("TaxSubtotal")) or [tt]:
            cod = _texto(sub.get("TaxCategory", {}).get("TaxScheme", {}).get("ID"))
            if cod == "01":  # IVA
                monto += _num(sub.get("TaxAmount"))
                pct = _num(sub.get("TaxCategory", {}).get("Percent"))
                if pct:
                    tarifa = pct
    return monto, tarifa


def _codigo_articulo(item: dict) -> str:
    ident = item.get("StandardItemIdentification") or item.get("SellersItemIdentification") or {}
    return _texto(ident.get("ID"))


def extraer_xml_de_zip(contenido_zip: bytes) -> list[bytes]:
    """Devuelve los XML dentro de un ZIP DIAN."""
    xmls = []
    with zipfile.ZipFile(io.BytesIO(contenido_zip)) as z:
        for nombre in z.namelist():
            if nombre.lower().endswith(".xml"):
                xmls.append(z.read(nombre))
    return xmls


def extraer_pdfs_de_zip(contenido_zip: bytes) -> list[tuple[str, bytes]]:
    """El ZIP DIAN normalmente trae, junto al XML, la representación
    gráfica de la factura en PDF (la que un humano quiere VER).
    Devuelve [(nombre_archivo, bytes)]."""
    pdfs = []
    with zipfile.ZipFile(io.BytesIO(contenido_zip)) as z:
        for nombre in z.namelist():
            if nombre.lower().endswith(".pdf"):
                pdfs.append((nombre.rsplit("/", 1)[-1], z.read(nombre)))
    return pdfs


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
    cli_nombre = _texto((ct[0] if ct else {}).get("RegistrationName")) or _texto(
        cliente.get("PartyName", {}).get("Name")
    )

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
    # Cargos separados por su razón declarada: flete y propina son costos de
    # naturaleza distinta a un recargo genérico y se piden discriminados.
    cargos = flete = propina = Decimal("0")
    for ac in _lista(raiz.get("AllowanceCharge")):
        if _texto(ac.get("ChargeIndicator")).lower() != "true":
            continue
        monto_ac = _num(ac.get("Amount"))
        razon = _texto(ac.get("AllowanceChargeReason")).lower()
        if re.search(r"flete|transporte|acarreo|env[ií]o", razon):
            flete += monto_ac
        elif "propina" in razon:
            propina += monto_ac
        else:
            cargos += monto_ac

    pagos = _lista(raiz.get("PaymentMeans"))
    primer_pago = pagos[0] if pagos else {}
    forma = _texto(primer_pago.get("ID"))
    medio_codigo = _texto(primer_pago.get("PaymentMeansCode"))
    vence = _texto(primer_pago.get("PaymentDueDate")) or _texto(raiz.get("DueDate"))

    notas = " | ".join(t for t in (_texto(n) for n in _lista(raiz.get("Note"))) if t)
    orden_compra = _texto(raiz.get("OrderReference", {}).get("ID"))
    moneda = _texto(raiz.get("DocumentCurrencyCode")) or "COP"

    items, descripciones = [], []
    lineas = _lista(raiz.get("InvoiceLine") or raiz.get("CreditNoteLine") or raiz.get("DebitNoteLine"))
    for i, ln in enumerate(lineas, start=1):
        item_xml = ln.get("Item", {})
        desc = " ".join(_texto(d) for d in _lista(item_xml.get("Description")))
        cant = ln.get("InvoicedQuantity") or ln.get("CreditedQuantity") or ln.get("DebitedQuantity")
        unidad = cant.get("@unitCode", "") if isinstance(cant, dict) else ""
        iva_monto, iva_tarifa = _iva_linea(ln)
        items.append(
            {
                "linea": i,
                "descripcion": desc[:500],
                "codigo_articulo": _codigo_articulo(item_xml) or None,
                "cantidad": float(_num(cant)),
                "unidad": unidad,
                "precio_unitario": float(_num(ln.get("Price", {}).get("PriceAmount"))),
                "descuento": float(_descuento_linea(ln)),
                "iva": float(iva_monto),
                "tarifa_iva": float(iva_tarifa) if iva_tarifa else None,
                "total": float(_num(ln.get("LineExtensionAmount"))),
                "total_con_iva": float(_num(ln.get("LineExtensionAmount")) + iva_monto),
            }
        )
        if desc:
            descripciones.append(desc)

    fecha = _texto(raiz.get("IssueDate"))
    plazo_dias = None
    if fecha and vence:
        try:
            from datetime import date as _date

            plazo_dias = (_date.fromisoformat(vence) - _date.fromisoformat(fecha)).days
        except ValueError:
            plazo_dias = None

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
            "cliente_nombre": cli_nombre or None,
            "fecha_emision": fecha or None,
            "fecha_vencimiento": vence or None,
            "plazo_dias": plazo_dias,
            "forma_pago": {"1": "contado", "2": "credito"}.get(forma),
            "metodo_pago": MEDIOS_PAGO_DIAN.get(medio_codigo),
            "orden_compra": orden_compra or None,
            "moneda": moneda,
            "notas": notas or None,
            "valor_bruto": float(_num(totales.get("LineExtensionAmount"))),
            "descuentos": float(_num(totales.get("AllowanceTotalAmount"))),
            "iva": float(montos["iva"]),
            "impoconsumo": float(montos["impoconsumo"]),
            "cargos": float(cargos),
            "flete": float(flete),
            "propina": float(propina),
            "ajuste": float(_num(totales.get("PayableRoundingAmount"))),
            "retenciones_xml": float(montos["retefuente"] + montos["reteiva"] + montos["reteica"]),
            "rete_fuente_xml": float(montos["retefuente"]),
            "rete_iva_xml": float(montos["reteiva"]),
            "rete_ica_xml": float(montos["reteica"]),
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
