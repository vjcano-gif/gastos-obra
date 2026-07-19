"""Vocabularios de medios/formas de pago y helpers de opciones."""
from __future__ import annotations

import pandas as pd  # noqa: F401  (indice_de tolera NaN)

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
