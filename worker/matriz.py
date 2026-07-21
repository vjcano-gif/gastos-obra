"""Lectura y cruce de la matriz de Excel que la constructora lleva hoy.

Su archivo tiene 2.359 movimientos de los cuales 2.186 YA estan
clasificados a mano (proyecto, capitulo, actividad, corte). Casi todos
del mismo periodo que ya trajimos de Gmail. Cruzarlos significa heredar
ese trabajo en vez de pedirle a alguien que vuelva a clasificar 4.052
facturas.

Este modulo es SOLO logica pura (leer, normalizar, emparejar): no toca
la base ni la red, para poder probarlo entero. La carga vive en
`importar_matriz.py`.

Sobre el emparejamiento — por que es por capas y no por una sola llave:
    - El numero viene en 12 formatos distintos ("CCFE-65767", "FE 4256",
      "JH - 9008", "D-381"), asi que hay que normalizarlo antes.
    - El NIT solo esta en el 57% de las filas, asi que no puede ser la
      llave principal.
    - Un numero suelto NO identifica: dos proveedores distintos pueden
      tener la factura "1234".
Por eso cada capa combina el numero con un segundo dato independiente, y
ante CUALQUIER ambiguedad se prefiere no emparejar: un dato heredado mal
es peor que uno vacio, porque nadie lo va a revisar.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

# Columnas de la hoja "MATRIZ GASTOS" (por posicion: sus encabezados
# tienen espacios y tildes inconsistentes).
COL = {
    "proyecto": 1, "id_capitulo": 2, "capitulo": 3, "corte": 4,
    "id_actividad": 5, "actividad": 6, "fecha": 7, "proveedor": 12,
    "nit": 13, "documento": 15, "numero": 16, "descripcion": 17,
    "valor_bruto": 18, "descuento": 19, "iva": 20, "subtotal": 26,
    "retenciones": 27, "total_a_pagar": 29, "forma_pago": 30,
    "estado": 31, "medio_pago": 32, "pagador": 33, "legalizacion": 34,
    "fecha_vencimiento": 36, "concepto": 37,
    "fecha_pago": 41, "valor_pagado": 42, "valor_pagado2": 44,
    "saldo": 46,  # "Saldo Calculado", el que ya trae la resta hecha
    "exento_aiu": 47, "pct_aiu": 48, "comision": 49,
}

ESTADO_PAGO = {
    "pagada": "pagada",
    "pendiente de pago": "pendiente",
    "pendiente reporte pago": "pendiente_reporte",
    "parcialmente pagada": "parcial",
    "anulada": "anulada",
}
# Solo estos cuentan como deuda. Una fila sin estado marcado se toma como
# PAGADA (el usuario confirmo que las que no tienen estado ya estan
# pagadas), no como pendiente: si no, su Saldo Calculado inflaria la deuda.
PENDIENTES = {"pendiente", "pendiente_reporte", "parcial"}

FORMA_PAGO = {
    "contado": "contado",
    "credito": "credito",
    "abono": "abono",
    "legalizacion anticipo": "legalizacion_anticipo",
    "anulada": "anulada",
}

MEDIO_PAGO = {
    "cuentas x pagar": "cuentas_x_pagar",
    "efectivo": "efectivo",
    "cheque": "cheque",
    "tarjeta credito vr": "tarjeta_credito_vr",
    "tarjeta credito": "tarjeta_credito",
    "tarjeta debito": "tarjeta_debito",
    "transferencia": "transferencia",
    "pago directo cliente": "pago_directo_cliente",
    "anulada": "anulada",
}

PAGADOR = {
    "espacios creativos": "empresa",
    "pago directo cliente": "cliente",
    "pago directo cliente ": "cliente",
    "cliente": "cliente",
}

MODO_PAGO_INGRESO = {
    "efectivo": "efectivo",
    "transferencia": "bancos",
    "bancos": "bancos",
    "pago directo": "pago_directo",
    "por identificar": "por_identificar",
}


def norm(texto) -> str:
    """Texto comparable: sin tildes, sin espacios de mas, en minusculas."""
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.lower().split())


def norm_numero(valor) -> str:
    """Numero de documento comparable.

    Quita todo lo que no sea letra o digito, porque el mismo documento
    aparece como "FE-708", "FE 708" y "FE708" segun quien lo digito.
    """
    if valor is None:
        return ""
    texto = str(valor).strip()
    if texto.endswith(".0"):          # Excel convierte los numericos a float
        texto = texto[:-2]
    return re.sub(r"[^0-9A-Za-z]", "", texto).upper()


def norm_corte(valor) -> str | None:
    """Nombre de corte canonico: "Corte1", "corte 1", " CORTE 1 " -> "corte 1".

    Ademas devuelve None para "sin corte", que en su matriz son 818 filas:
    no es un corte llamado asi, es la ausencia de corte. Tratarlo como uno
    mas habria creado un corte fantasma en casi todos los proyectos y
    habria descuadrado cualquier informe por corte.
    """
    t = norm(valor)
    if not t or t in ("sin corte", "sin identificar", "n/a", "na", "-"):
        return None
    m = re.search(r"(\d+)", t)
    return f"corte {int(m.group(1))}" if m else None


def norm_nit(valor) -> str:
    """NIT sin puntos, guiones ni digito de verificacion."""
    if valor is None:
        return ""
    solo = re.sub(r"[^0-9]", "", str(valor).split("-")[0])
    return solo.lstrip("0")


def a_fecha(valor):
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return None


def a_numero(valor) -> float:
    try:
        return round(float(valor), 2)
    except (TypeError, ValueError):
        return 0.0


def _mapear(diccionario: dict, valor, defecto=None):
    return diccionario.get(norm(valor), defecto)


def leer_gastos(hoja) -> list[dict]:
    """Filas de la hoja MATRIZ GASTOS como diccionarios normalizados."""
    filas = []
    it = iter(hoja)
    next(it, None)                      # encabezado
    for n, fila in enumerate(it, start=2):
        if len(fila) <= COL["comision"] or not fila[COL["proyecto"]]:
            continue
        if str(fila[COL["proyecto"]]).strip().lower().startswith("ejemplo"):
            continue                                    # fila de ejemplo de la plantilla
        filas.append(
            {
                "fila_excel": n,
                "proyecto": str(fila[COL["proyecto"]]).strip(),
                "capitulo_codigo": _codigo_entero(fila[COL["id_capitulo"]]),
                "actividad_codigo": _codigo_decimal(fila[COL["id_actividad"]]),
                "corte": norm_corte(fila[COL["corte"]]),
                "fecha": a_fecha(fila[COL["fecha"]]),
                "proveedor": str(fila[COL["proveedor"]] or "").strip() or None,
                "nit": norm_nit(fila[COL["nit"]]) or None,
                "documento": str(fila[COL["documento"]] or "").strip() or None,
                "numero": str(fila[COL["numero"]] or "").strip() or None,
                "numero_norm": norm_numero(fila[COL["numero"]]),
                "descripcion": str(fila[COL["descripcion"]] or "").strip() or None,
                "subtotal": a_numero(fila[COL["subtotal"]]),
                "total_a_pagar": a_numero(fila[COL["total_a_pagar"]]),
                "retenciones": a_numero(fila[COL["retenciones"]]),
                "iva": a_numero(fila[COL["iva"]]),
                "forma_pago": _mapear(FORMA_PAGO, fila[COL["forma_pago"]]),
                # sin estado marcado -> pagada (confirmado por el usuario)
                "estado_pago": _mapear(ESTADO_PAGO, fila[COL["estado"]], "pagada"),
                "metodo_pago": _mapear(MEDIO_PAGO, fila[COL["medio_pago"]]),
                "pagador": _mapear(PAGADOR, fila[COL["pagador"]]),
                "legalizacion": _mapear(
                    {"encima": "encima", "debajo": "debajo"}, fila[COL["legalizacion"]]
                ),
                "exento_aiu": bool(fila[COL["exento_aiu"]]),
                "comision": a_numero(fila[COL["comision"]]),
                "fecha_vencimiento": a_fecha(fila[COL["fecha_vencimiento"]]),
                "concepto_pago": str(fila[COL["concepto"]] or "").strip() or None,
                "fecha_pago": a_fecha(fila[COL["fecha_pago"]]),
                "valor_pagado": a_numero(fila[COL["valor_pagado"]]) + a_numero(fila[COL["valor_pagado2"]]),
                # El saldo solo cuenta si el estado dice que sigue pendiente;
                # una fila pagada tiene saldo 0 aunque su "Saldo Calculado"
                # traiga un valor residual.
                "saldo": (
                    a_numero(fila[COL["saldo"]])
                    if _mapear(ESTADO_PAGO, fila[COL["estado"]], "pagada") in PENDIENTES
                    else 0.0
                ),
            }
        )
    return filas


def _codigo_entero(valor) -> str | None:
    """ID de capitulo: 4 -> "4"."""
    if valor is None or valor == "":
        return None
    try:
        return str(int(float(valor)))
    except (TypeError, ValueError):
        return None


def _codigo_decimal(valor) -> str | None:
    """ID de actividad: 66.01 -> "66.01" (dos decimales siempre)."""
    if valor is None or valor == "":
        return None
    try:
        return f"{float(valor):.2f}"
    except (TypeError, ValueError):
        return None


def leer_ingresos(hoja) -> list[dict]:
    """Hoja MATRIZ INGRESOS: los abonos del cliente."""
    filas = []
    it = iter(hoja)
    next(it, None)
    for n, fila in enumerate(it, start=2):
        if len(fila) < 10 or not fila[4] or not isinstance(fila[7], (int, float)):
            continue
        if str(fila[4]).strip().lower().startswith("ejemplo"):
            continue                                    # fila de ejemplo de la plantilla
        filas.append(
            {
                "fila_excel": n,
                "fecha": a_fecha(fila[0]),
                "proyecto": str(fila[4]).strip(),
                "corte": norm_corte(fila[5]),
                "detalle": str(fila[6] or "").strip() or None,
                "valor": a_numero(fila[7]),
                "modo_pago": _mapear(MODO_PAGO_INGRESO, fila[8], "por_identificar"),
                "legalizacion": _mapear(
                    {"encima": "encima", "debajo": "debajo"}, fila[9]
                ),
            }
        )
    return filas


def leer_proyectos(hoja) -> list[dict]:
    """Hoja LCLIENTES: proyecto, estado y %AIU del contrato."""
    proyectos = []
    it = iter(hoja)
    next(it, None)
    for fila in it:
        if not fila or not fila[0]:
            continue
        proyectos.append(
            {
                "nombre": str(fila[0]).strip(),
                "estado": "cerrado" if norm(fila[1]) == "cerrado" else "activo",
                "pct_aiu": a_numero(fila[2]) if len(fila) > 2 else 0.0,
            }
        )
    return proyectos


# ------------------------------------------------------------------- cruce
def indexar_facturas(facturas: list[dict]) -> dict:
    """Indices de las facturas ya cargadas, para buscarlas por varias vias.

    Se guardan LISTAS y no un unico id a proposito: si una llave apunta a
    mas de una factura es ambigua y no se debe emparejar sola.
    """
    idx = {"num_nit": {}, "num_valor": {}, "num_prov": {}}
    for f in facturas:
        num = norm_numero(f.get("numero"))
        if not num:
            continue
        nit = norm_nit(f.get("proveedor_nit"))
        if nit:
            idx["num_nit"].setdefault((num, nit), []).append(f)
        total = a_numero(f.get("total"))
        if total:
            idx["num_valor"].setdefault((num, total), []).append(f)
        prov = norm(f.get("proveedor_nombre"))
        if prov:
            idx["num_prov"].setdefault((num, prov), []).append(f)
    return idx


def emparejar(fila: dict, idx: dict) -> tuple[dict | None, str]:
    """Busca la factura que corresponde a una fila de la matriz.

    Devuelve (factura, motivo). Las capas van de mas fuerte a mas debil, y
    una llave que apunte a varias facturas se descarta: preferimos dejarlo
    para revision humana antes que heredar una clasificacion equivocada.
    """
    num = fila.get("numero_norm")
    if not num:
        return None, "sin_numero"

    intentos = [
        ("numero+nit", (num, fila.get("nit")), "num_nit"),
        ("numero+valor", (num, fila.get("subtotal")), "num_valor"),
        ("numero+proveedor", (num, norm(fila.get("proveedor"))), "num_prov"),
    ]
    hubo_ambiguo = False
    for motivo, llave, indice in intentos:
        if not llave[1]:
            continue
        candidatos = idx[indice].get(llave, [])
        if len(candidatos) == 1:
            return candidatos[0], motivo
        if len(candidatos) > 1:
            hubo_ambiguo = True
    return None, "ambiguo" if hubo_ambiguo else "sin_coincidencia"


def cambios_heredables(fila: dict, factura: dict, ids: dict) -> dict:
    """Que se le puede copiar a una factura ya cargada, SIN pisar nada.

    Solo se rellenan campos vacios. Si alguien ya clasifico una factura en
    la app, su decision manda sobre el Excel: el Excel es historico y la
    app es lo vivo.
    """
    cambios = {}

    def poner(campo, valor):
        if valor is not None and not factura.get(campo):
            cambios[campo] = valor

    poner("proyecto_id", ids["proyectos"].get(norm(fila["proyecto"])))
    poner("capitulo_id", ids["capitulos"].get(fila.get("capitulo_codigo")))
    poner("actividad_id", ids["actividades"].get(fila.get("actividad_codigo")))
    poner("corte_id", ids["cortes"].get((norm(fila["proyecto"]), fila.get("corte"))))
    poner("forma_pago", fila.get("forma_pago"))
    poner("metodo_pago", fila.get("metodo_pago"))
    poner("pagador", fila.get("pagador"))
    poner("legalizacion", fila.get("legalizacion"))
    poner("concepto", fila.get("descripcion"))

    # estado_pago arranca en 'pendiente' por defecto, asi que "vacio" no
    # sirve como senal: se copia cuando el Excel dice algo mas concreto.
    if fila.get("estado_pago") and fila["estado_pago"] != "pendiente":
        if factura.get("estado_pago") in (None, "", "pendiente"):
            cambios["estado_pago"] = fila["estado_pago"]

    if fila.get("exento_aiu") and not factura.get("exento_aiu"):
        cambios["exento_aiu"] = True

    # Datos de PAGO: se copian aunque el valor sea 0 (0 = pagada, es un dato
    # valido, no "vacio"). Son la verdad de tesoreria de la matriz y en la
    # factura de Gmail no existian; por eso se ponen siempre, no solo si
    # faltan. Sin esto, "cuanto debo" quedaria sin fuente confiable.
    if fila.get("saldo") is not None and factura.get("saldo") is None:
        cambios["saldo"] = fila["saldo"]
    if fila.get("valor_pagado") and not factura.get("valor_pagado"):
        cambios["valor_pagado"] = fila["valor_pagado"]
    if fila.get("fecha_pago") and not factura.get("fecha_pago"):
        cambios["fecha_pago"] = fila["fecha_pago"].isoformat()
    if fila.get("fecha_vencimiento") and not factura.get("fecha_vencimiento"):
        cambios["fecha_vencimiento"] = fila["fecha_vencimiento"].isoformat()
    return cambios


def rangos_de_cortes(filas: list[dict]) -> dict:
    """Deduce las fechas de cada corte a partir de los movimientos.

    Su LCORTE solo trae los nombres ("Corte 1".."Corte 15") sin fechas, y
    sin fechas no se puede asignar el corte automaticamente. Pero cada
    corte SI tiene movimientos fechados, asi que el rango sale de los
    propios datos: del primero al ultimo movimiento del corte.
    """
    rangos: dict[tuple[str, str], dict] = {}
    for f in filas:
        if not f.get("corte") or not f.get("fecha"):
            continue
        llave = (norm(f["proyecto"]), f["corte"])
        r = rangos.setdefault(
            llave, {"fecha_inicio": f["fecha"], "fecha_fin": f["fecha"], "movimientos": 0}
        )
        r["fecha_inicio"] = min(r["fecha_inicio"], f["fecha"])
        r["fecha_fin"] = max(r["fecha_fin"], f["fecha"])
        r["movimientos"] += 1
    return rangos


def numero_de_corte(nombre: str) -> int:
    """"corte 12" -> 12. Sirve para ordenarlos."""
    m = re.search(r"(\d+)", nombre or "")
    return int(m.group(1)) if m else 0
