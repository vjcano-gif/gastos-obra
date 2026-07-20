"""AIU/comisión, cash flow por corte y comparación plan vs real."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from ._conexion import TTL_LECTURA
from ._lecturas import capitulos, detalle_clasificado, df, items_de_factura_ids


ESTADOS_PENDIENTES = ("pendiente", "parcial", "pendiente_reporte")


def con_saldo_pendiente(fx: pd.DataFrame) -> pd.DataFrame:
    """Agrega la columna `saldo_pend` (lo que queda por pagar) y devuelve
    SOLO las facturas que se deben. Base de "Cuentas por pagar".

    Prioridad del saldo, de más confiable a menos:
      1. `saldo` de la matriz (columna 018): el dato de tesorería real.
      2. Si no hay saldo cargado pero el estado_pago dice pendiente:
         total a pagar (neto de retención) menos lo abonado.
    Ojo: se filtra por estado_PAGO (si se pagó), no por `estado` (el flujo
    interno de revisión). Mezclarlos hacía que las 2.359 importadas —que la
    matriz marca pagadas— aparecieran como deuda solo por estar en
    'asignada'."""
    if fx is None or fx.empty:
        return pd.DataFrame()
    d = fx.copy()
    if "estado" in d:
        d = d[d["estado"] != "anulada"]
    if d.empty:
        return d

    def col_num(nombre, defecto=0.0):
        """Columna numérica como Serie alineada; 0 si la columna no existe
        (d.get devuelve un escalar en ese caso, que rompe las operaciones)."""
        if nombre in d.columns:
            return pd.to_numeric(d[nombre], errors="coerce").fillna(defecto)
        return pd.Series([defecto] * len(d), index=d.index)

    tiene_saldo = "saldo" in d.columns
    ret = col_num("rete_fuente") + col_num("rete_iva") + col_num("rete_ica")
    ret_xml = col_num("retenciones_xml")
    base = col_num("monto_efectivo") if "monto_efectivo" in d.columns else col_num("total")
    total_a_pagar = base - ret.where(ret > 0, ret_xml)

    estado_pago = (
        d["estado_pago"] if "estado_pago" in d.columns
        else pd.Series(["pendiente"] * len(d), index=d.index)
    )
    por_estado = total_a_pagar.where(estado_pago.isin(ESTADOS_PENDIENTES), 0)

    if tiene_saldo:
        saldo = pd.to_numeric(d["saldo"], errors="coerce")
        # donde hay saldo de la matriz mandala; donde es nulo, cae al estado
        d["saldo_pend"] = saldo.where(saldo.notna(), por_estado)
    else:
        d["saldo_pend"] = por_estado

    return d[d["saldo_pend"] > 0].copy()


def base_aiu(factura, exento=None) -> float:
    """Base sobre la que se cobra la comision.

    Es el valor del costo antes de retenciones: la retencion es plata que
    se le retiene al proveedor y se le gira a la DIAN, no un menor costo
    del proyecto, asi que no puede reducir la comision.
    """
    if exento is None:
        exento = bool(factura.get("exento_aiu"))
    if exento:
        return 0.0
    total = factura.get("total")
    try:
        return float(total or 0)
    except (TypeError, ValueError):
        return 0.0


def comision(factura, exento, pct) -> float:
    """Comision de una factura: base x %AIU del proyecto."""
    try:
        pct = float(pct or 0)
    except (TypeError, ValueError):
        return 0.0
    return round(base_aiu(factura, exento) * pct, 2)


def corte_de_fecha(cortes_df, proyecto_id, fecha):
    """Corte al que cae una fecha dentro de un proyecto.

    Evita que alguien digite el corte factura por factura, que era una de
    las columnas que hoy llena Nadia a mano. Si los cortes aun no tienen
    fechas cargadas devuelve None y el corte se elige manualmente.
    """
    if cortes_df is None or getattr(cortes_df, "empty", True) or not proyecto_id or not fecha:
        return None
    fecha = pd.to_datetime(fecha, errors="coerce")
    if pd.isna(fecha):
        return None
    fecha = fecha.date()
    candidatos = cortes_df[cortes_df["proyecto_id"] == proyecto_id]
    for _, c in candidatos.sort_values("numero").iterrows():
        ini = pd.to_datetime(c.get("fecha_inicio"), errors="coerce")
        if pd.isna(ini) or fecha < ini.date():
            continue
        fin = pd.to_datetime(c.get("fecha_fin"), errors="coerce")
        if pd.isna(fin) or fecha <= fin.date():
            return c["id"]
    return None


# ---------------------------------------------------------------- cash flow
# Mecanica tomada de su hoja "Cash flow Casa Chipre" y verificada contra
# los dos primeros cortes de Casa Vieja 61 antes de escribirla:
#
#   subtotal      = gastos + AIU gastos + AIU pagos directos + GMF + otros
#   total egresos = subtotal + pagos directos + pagos exentos
#   caja final    = caja inicial + anticipos - subtotal
#
# Dos sutilezas que hay que respetar o los numeros no les cuadran:
#
#  1. Los PAGOS DIRECTOS (los que el cliente le paga al proveedor) suman
#     al costo del proyecto y generan comision, pero NO salen de la caja
#     de Espacios. Por eso entran en "total egresos" pero no en el
#     subtotal que descuenta la caja.
#  2. La etiqueta de su hoja dice "Subtotal = 1+2+3+4", pero el numero
#     real incluye tambien el 5 (otros gastos): en el corte 1 el subtotal
#     es 21.994.759,9 y 1+2+3+4 da 1.994.759,9. La etiqueta se quedo
#     desactualizada; se sigue el numero, no el rotulo.

CONCEPTOS_CASH_FLOW = [
    ("gastos", "1. Gastos"),
    ("aiu_gastos", "2. AIU gastos"),
    ("aiu_pagos_directos", "3. AIU pagos directos"),
    ("gmf", "4. GMF 4x1000"),
    ("otros_gastos", "5. Otros gastos"),
    ("subtotal", "Subtotal (sale de caja)"),
    ("pagos_directos", "Pagos directos del cliente"),
    ("pagos_exentos", "Otros pagos exentos"),
    ("total_egresos", "Total egresos"),
]


def cash_flow(facturas_pr, anticipos_pr, movimientos_pr, cortes_pr, pct_aiu,
              proyecto_exento: bool = False) -> pd.DataFrame:
    """Cash flow del proyecto, un corte por columna.

    Recibe ya filtrado por proyecto. Devuelve un DataFrame con una fila
    por concepto y una columna por corte, en el mismo orden en que ellos
    lo leen. El saldo de caja se encadena: el final de un corte es el
    inicial del siguiente.

    `proyecto_exento`: si el proyecto es exento de AIU, no genera comisión
    aunque tenga %AIU (la exención del proyecto manda). Ver migración 019.
    """
    try:
        pct = 0.0 if proyecto_exento else float(pct_aiu or 0)
    except (TypeError, ValueError):
        pct = 0.0

    orden = []
    if cortes_pr is not None and not cortes_pr.empty:
        orden = list(cortes_pr.sort_values("numero")["id"])
    # Lo que no tenga corte asignado se muestra aparte en vez de perderse.
    orden.append(None)

    columnas, caja = {}, 0.0
    for corte_id in orden:
        f = _filtrar_corte(facturas_pr, corte_id)
        a = _filtrar_corte(anticipos_pr, corte_id)
        m = _filtrar_corte(movimientos_pr, corte_id)

        gastos = _suma(f[f["pagador"] != "cliente"], "total") if not f.empty else 0.0
        directos = _suma(f[f["pagador"] == "cliente"], "total") if not f.empty else 0.0
        exentos_aiu = _suma(f[f.get("exento_aiu") == True], "total") if not f.empty else 0.0  # noqa: E712

        gmf = _suma(m[m["concepto"] == "gmf"], "valor") if not m.empty else 0.0
        otros = _suma(m[m["concepto"] == "otros_gastos"], "valor") if not m.empty else 0.0
        pagos_exentos = _suma(m[m["concepto"] == "pago_exento"], "valor") if not m.empty else 0.0

        # Lo marcado como exento no entra a la base de la comision.
        aiu_gastos = round(max(gastos - exentos_aiu, 0) * pct, 2)
        aiu_directos = round(directos * pct, 2)

        subtotal = gastos + aiu_gastos + aiu_directos + gmf + otros
        anticipos_corte = _suma(a, "valor") if not a.empty else 0.0
        caja_inicial = caja
        caja = caja_inicial + anticipos_corte - subtotal

        columnas[corte_id] = {
            "caja_inicial": caja_inicial,
            "anticipos": anticipos_corte,
            "anticipos_bancos": _suma(a[a["modo_pago"] == "bancos"], "valor") if not a.empty else 0.0,
            "anticipos_efectivo": _suma(a[a["modo_pago"] == "efectivo"], "valor") if not a.empty else 0.0,
            "gastos": gastos,
            "aiu_gastos": aiu_gastos,
            "aiu_pagos_directos": aiu_directos,
            "gmf": gmf,
            "otros_gastos": otros,
            "subtotal": subtotal,
            "pagos_directos": directos,
            "pagos_exentos": pagos_exentos,
            "total_egresos": subtotal + directos + pagos_exentos,
            "caja_final": caja,
        }

    nombres = {}
    if cortes_pr is not None and not cortes_pr.empty:
        nombres = dict(zip(cortes_pr["id"], cortes_pr["nombre"]))
    nombres[None] = "Sin corte"

    tabla = pd.DataFrame(columnas)
    tabla.columns = [nombres.get(c, "Sin corte") for c in tabla.columns]
    return tabla


def costo_por_capitulo(sb, proyecto_id: str) -> pd.DataFrame:
    """Costo por capítulo y corte, YA sumado, para el usuario cliente.

    El cliente no puede leer `facturas`: el RLS se lo impide, porque esa
    tabla trae proveedores y valores por documento. La suma la hace una
    función SECURITY DEFINER en la base, que ella misma verifica que el
    proyecto consultado sea el suyo.
    """
    try:
        r = sb.rpc("costo_por_capitulo", {"p_proyecto": proyecto_id}).execute()
    except Exception:
        return pd.DataFrame()
    datos = pd.DataFrame(r.data or [])
    if datos.empty:
        return datos
    datos["capitulo"] = datos["capitulo"].fillna("Sin capítulo")
    datos["corte"] = datos["corte"].fillna("Sin corte")
    return datos


def cumplimiento_cronograma(hitos, anticipos) -> dict:
    """Cumplimiento de los abonos del cliente: lo PROGRAMADO (cronograma
    de hitos tipo 'abono') contra lo REALMENTE recibido (anticipos).

    Devuelve totales y % de cumplimiento. Sirve para responder si el
    cliente va al día con los pagos pactados.
    """
    programado = 0.0
    if hitos is not None and not hitos.empty and "tipo" in hitos:
        ab = hitos[hitos["tipo"] == "abono"]
        programado = pd.to_numeric(ab.get("monto", 0), errors="coerce").fillna(0).sum()
    recibido = 0.0
    if anticipos is not None and not anticipos.empty:
        recibido = pd.to_numeric(anticipos["valor"], errors="coerce").fillna(0).sum()
    pct = (recibido / programado * 100) if programado else None
    return {
        "programado": float(programado),
        "recibido": float(recibido),
        "pendiente": float(max(programado - recibido, 0)),
        "cumplimiento_pct": pct,          # None si no hay cronograma cargado
    }


def superavit_por_corte(cash_flow_tabla) -> pd.DataFrame:
    """Superávit (+) o déficit (-) por corte, a partir del cash flow.

    El déficit de un corte es cuando lo recibido no alcanzó a cubrir lo
    gastado en ese periodo (anticipos del corte - subtotal del corte). El
    acumulado es la caja del proyecto."""
    if cash_flow_tabla is None or cash_flow_tabla.empty:
        return pd.DataFrame()
    ant = cash_flow_tabla.loc["anticipos"]
    sub = cash_flow_tabla.loc["subtotal"]
    return pd.DataFrame({
        "corte": list(cash_flow_tabla.columns),
        "resultado": (ant - sub).values,           # + superávit, - déficit
        "caja_acumulada": cash_flow_tabla.loc["caja_final"].values,
    })


def proyeccion_compromisos(egresos, ingresos, meses: int = 3, hoy=None) -> pd.DataFrame:
    """Proyección de caja hacia adelante, un mes por fila.

    Contrasta los EGRESOS comprometidos (vencimientos de cuentas por pagar)
    contra los INGRESOS previstos (abonos programados del cronograma del
    proyecto). Responde: ¿me alcanza lo que voy a cobrar para cubrir lo que
    tengo que pagar en los próximos `meses`?

    `egresos` e `ingresos` son DataFrames con columnas 'fecha' y 'valor'. Lo
    ATRASADO (fecha anterior al mes en curso) y lo POSTERIOR al horizonte van
    a buckets propios para no esconderlos: así el acumulado arranca desde el
    saldo vencido real y los totales reconcilian con lo que se debe y lo que
    falta por cobrar. Devuelve periodo, ingresos_previstos,
    egresos_comprometidos, neto y acumulado (la trayectoria de caja).
    """
    hoy = (pd.Timestamp(hoy) if hoy is not None else pd.Timestamp.today()).normalize()
    mes0 = hoy.to_period("M")
    horizonte = [mes0 + i for i in range(max(int(meses), 1))]
    ult = horizonte[-1]

    ATRASADO, POSTERIOR, SINFECHA = "Vencido / atrasado", "Posterior", "Sin fecha"

    def bucket(fecha):
        f = pd.to_datetime(fecha, errors="coerce")
        if pd.isna(f):
            return SINFECHA
        p = f.to_period("M")
        if p < mes0:
            return ATRASADO
        if p > ult:
            return POSTERIOR
        return str(p)

    def por_bucket(d):
        s: dict = {}
        if d is not None and not d.empty and "fecha" in d and "valor" in d:
            v = pd.to_numeric(d["valor"], errors="coerce").fillna(0)
            for b, val in zip(d["fecha"].map(bucket), v):
                s[b] = s.get(b, 0.0) + float(val)
        return s

    eg, ing = por_bucket(egresos), por_bucket(ingresos)

    # Los meses del horizonte siempre se muestran (aunque estén en cero, para
    # ver la línea de tiempo); los buckets extra solo si tienen algo.
    orden = []
    if eg.get(ATRASADO) or ing.get(ATRASADO):
        orden.append(ATRASADO)
    orden += [str(p) for p in horizonte]
    for extra in (POSTERIOR, SINFECHA):
        if eg.get(extra) or ing.get(extra):
            orden.append(extra)

    filas, acum = [], 0.0
    for b in orden:
        i, e = round(ing.get(b, 0.0), 2), round(eg.get(b, 0.0), 2)
        acum += i - e
        filas.append({
            "periodo": b, "ingresos_previstos": i, "egresos_comprometidos": e,
            "neto": round(i - e, 2), "acumulado": round(acum, 2),
        })
    return pd.DataFrame(
        filas,
        columns=["periodo", "ingresos_previstos", "egresos_comprometidos", "neto", "acumulado"],
    )


def costo_por_capitulo_local(sb, uid, proyecto_id, facturas_pr, cortes_pr) -> pd.DataFrame:
    """Lo mismo, pero para el equipo interno, calculado aquí.

    Se separa del camino del cliente a propósito: aquí sí se puede bajar
    al detalle de artículo, que es donde vive la clasificación real
    (una misma factura reparte cemento a Estructura y pintura a Acabados).
    """
    if facturas_pr is None or facturas_pr.empty:
        return pd.DataFrame()

    # Solo los items de las facturas de ESTE proyecto, no los del workspace.
    items = items_de_factura_ids(sb, uid, facturas_pr["id"].tolist())
    caps = capitulos(sb, uid)
    nombre_cap = dict(zip(caps["id"], caps["nombre"])) if not caps.empty else {}
    nombre_corte = (
        dict(zip(cortes_pr["id"], cortes_pr["nombre"])) if not cortes_pr.empty else {}
    )

    detalle = detalle_clasificado(facturas_pr, items)
    if detalle.empty:
        return pd.DataFrame()

    detalle["capitulo"] = detalle["capitulo_id"].map(nombre_cap).fillna("Sin capítulo")
    detalle["corte"] = detalle["corte_id"].map(nombre_corte).fillna("Sin corte")
    return (
        detalle.groupby(["capitulo", "corte"], as_index=False)["valor"]
        .sum()
        .rename(columns={"valor": "total"})
    )


def _filtrar_corte(datos, corte_id):
    """Filas de un corte; corte_id None son las que no tienen corte."""
    if datos is None or datos.empty:
        return pd.DataFrame()
    if corte_id is None:
        return datos[datos["corte_id"].isna()]
    return datos[datos["corte_id"] == corte_id]


def _suma(datos, columna) -> float:
    if datos is None or datos.empty or columna not in datos:
        return 0.0
    return float(pd.to_numeric(datos[columna], errors="coerce").fillna(0).sum())


# ------------------------------------------------------------ flujo semanal
@st.cache_data(ttl=TTL_LECTURA, show_spinner=False)
def presupuesto(_sb, uid, proyecto_id: str | None = None) -> pd.DataFrame:
    q = _sb.table("presupuesto").select("*").eq("user_id", uid)
    if proyecto_id:
        q = q.eq("proyecto_id", proyecto_id)
    return df(q.order("orden").execute())


@st.cache_data(ttl=TTL_LECTURA, show_spinner=False)
def plan_semanal(_sb, uid, presupuesto_ids: list[str]) -> pd.DataFrame:
    """Reparto semanal de las líneas de presupuesto indicadas."""
    if not presupuesto_ids:
        return pd.DataFrame()
    return df(
        _sb.table("presupuesto_semana").select("*")
        .eq("user_id", uid).in_("presupuesto_id", presupuesto_ids)
        .order("anio").order("semana").execute()
    )


def semana_iso(fecha) -> tuple[int, int] | tuple[None, None]:
    """(año, semana) ISO de una fecha. Su flujo va por semanas."""
    f = pd.to_datetime(fecha, errors="coerce")
    if pd.isna(f):
        return (None, None)
    iso = f.isocalendar()
    return (int(iso[0]), int(iso[1]))


def planeado_vs_real(plan, detalle_real) -> pd.DataFrame:
    """Compara el plan semanal contra lo realmente ejecutado.

    `plan` viene de presupuesto_semana; `detalle_real` es el detalle
    clasificado (una fila por artículo) con su fecha. Se agrupa por semana
    ISO, que es como ellos leen el avance.

    El desfase se muestra en pesos y en %, pero el % se omite cuando no
    había nada planeado: dividir por cero daría "infinito" y una semana
    sin plan no es un incumplimiento del 100%, es una semana sin plan.
    """
    filas = {}
    if plan is not None and not plan.empty:
        for _, p in plan.iterrows():
            llave = (int(p["anio"]), int(p["semana"]))
            filas.setdefault(llave, {"planeado": 0.0, "real": 0.0})
            filas[llave]["planeado"] += float(p.get("valor") or 0)

    if detalle_real is not None and not detalle_real.empty:
        for _, r in detalle_real.iterrows():
            anio, semana = semana_iso(r.get("fecha_emision"))
            if anio is None:
                continue
            filas.setdefault((anio, semana), {"planeado": 0.0, "real": 0.0})
            filas[(anio, semana)]["real"] += float(r.get("valor") or 0)

    if not filas:
        return pd.DataFrame()

    tabla = pd.DataFrame(
        [
            {"anio": a, "semana": s, "periodo": f"{a}-S{s:02d}", **v}
            for (a, s), v in sorted(filas.items())
        ]
    )
    tabla["desfase"] = tabla["real"] - tabla["planeado"]
    tabla["cumplimiento_%"] = [
        round(r / p * 100, 1) if p else None
        for r, p in zip(tabla["real"], tabla["planeado"])
    ]
    tabla["planeado_acum"] = tabla["planeado"].cumsum()
    tabla["real_acum"] = tabla["real"].cumsum()
    return tabla


# -------------------------------------------------------------- vocabularios
# Estas listas tienen que coincidir EXACTAMENTE con los CHECK de la base
# (migracion 013) y con lo que escribe el worker. Antes estaban repetidas
# en cada pantalla y en dian_xml.py, y al ampliarlas se desincronizaban:
# la base rechazaba un valor que la pantalla si ofrecia. Un solo sitio.
#
# Las etiquetas son las que ellos usan en su matriz; el valor guardado es
# el slug, para no depender de tildes ni mayusculas.
