"""Motor de retenciones con vigencias.

Regla de oro: se aplica la regla vigente A LA FECHA DE LA FACTURA y el
resultado queda congelado en la factura con el detalle de qué regla se usó.
Un cambio de ley = nueva regla con vigencia_desde; la historia no se toca.
El sistema calcula y SUGIERE; el usuario confirma en Revisión.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal


def _vigente(regla: dict, fecha: date) -> bool:
    desde = date.fromisoformat(str(regla["vigencia_desde"]))
    hasta = regla.get("vigencia_hasta")
    if fecha < desde:
        return False
    return hasta is None or fecha <= date.fromisoformat(str(hasta))


def calcular(factura: dict, reglas: list[dict], uvt_por_anio: dict[int, float]) -> dict:
    """Devuelve {rete_fuente, rete_iva, rete_ica, detalle_retenciones}."""
    if factura.get("sentido") != "gasto" or not factura.get("fecha_emision"):
        return {}
    fecha = date.fromisoformat(str(factura["fecha_emision"]))
    uvt = Decimal(str(uvt_por_anio.get(fecha.year, 0)))
    if uvt == 0:
        return {}

    base = Decimal(str(factura.get("valor_bruto") or 0)) - Decimal(str(factura.get("descuentos") or 0))
    iva = Decimal(str(factura.get("iva") or 0))
    concepto = factura.get("concepto_retencion") or "compras"
    if concepto == "ninguno":
        return {"rete_fuente": 0, "rete_iva": 0, "rete_ica": 0, "detalle_retenciones": []}

    resultado = {"rete_fuente": Decimal("0"), "rete_iva": Decimal("0"), "rete_ica": Decimal("0")}
    detalle = []
    campo_por_tipo = {"retefuente": "rete_fuente", "reteiva": "rete_iva", "reteica": "rete_ica"}

    for regla in reglas:
        if not _vigente(regla, fecha):
            continue
        if regla["tipo"] in ("retefuente", "reteica") and regla["concepto"] != concepto:
            continue
        base_regla = iva if regla["tipo"] == "reteiva" else base
        minimo = Decimal(str(regla.get("base_minima_uvt") or 0)) * uvt
        if base_regla <= 0 or base_regla < minimo:
            continue
        tarifa = Decimal(str(regla["tarifa"]))
        valor = (base_regla * tarifa / Decimal("100")).quantize(Decimal("1"))
        campo = campo_por_tipo[regla["tipo"]]
        # si hay varias reglas del mismo tipo vigentes, gana la más reciente
        previa = next((d for d in detalle if d["tipo"] == regla["tipo"]), None)
        if previa:
            if str(regla["vigencia_desde"]) <= previa["vigencia_desde"]:
                continue
            resultado[campo] -= Decimal(str(previa["valor"]))
            detalle.remove(previa)
        resultado[campo] += valor
        detalle.append(
            {
                "tipo": regla["tipo"],
                "regla_id": regla.get("id"),
                "concepto": regla["concepto"],
                "tarifa": float(tarifa),
                "base": float(base_regla),
                "valor": float(valor),
                "vigencia_desde": str(regla["vigencia_desde"]),
            }
        )

    return {
        "rete_fuente": float(resultado["rete_fuente"]),
        "rete_iva": float(resultado["rete_iva"]),
        "rete_ica": float(resultado["rete_ica"]),
        "detalle_retenciones": detalle,
    }
