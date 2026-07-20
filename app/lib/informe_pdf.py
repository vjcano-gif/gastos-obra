"""Informe del proyecto para el cliente, calcado del Excel "Cash Flow Casa
Vieja 61": una Portada de CONTROL DE COSTOS (capítulo → actividad × corte, con
% de participación) y un CASH FLOW por corte con la misma colorimetría de la
hoja (capítulos en verde, Total Egresos en rojo, acumulados en azul, saldos
negativos en rojo), con el logo de Espacios Creativos.

Función pura: recibe lo que ya calcula la app (`db.cash_flow` y el costo por
actividad/capítulo) y devuelve los bytes de un PDF. El mismo PDF sirve para
descargarlo, adjuntarlo al correo del cliente y verlo dentro de la app.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from fpdf import FPDF
from fpdf.enums import XPos, YPos

# Paleta de su hoja de Excel.
NARANJA = (216, 90, 48)
VERDE = (29, 158, 117)
AZUL = (91, 141, 239)
GRIS_TX = (55, 55, 55)
BLANCO = (255, 255, 255)
ROJO_TX = (192, 0, 0)              # saldos/valores negativos
VERDE_BG = (217, 234, 211)         # filas de capítulo (Portada)
ROSA_BG = (244, 204, 204)          # Total Egresos (Cash Flow)
AZUL_BG = (207, 226, 243)          # acumulados
GRIS_BG = (236, 236, 236)          # subtotales / totales

_LOGO = Path(__file__).with_name("assets") / "logo_espacios.png"

# Filas del cash flow, en el orden de su hoja.
_CONCEPTOS = [
    ("caja_inicial", "Saldo inicial de caja", "caja"),
    ("anticipos", "Anticipos del cliente", "ingreso"),
    ("anticipos_bancos", "   Bancos", "sub"),
    ("anticipos_efectivo", "   Efectivo", "sub"),
    ("gastos", "1. Gastos", "flujo"),
    ("aiu_gastos", "2. AIU gastos", "flujo"),
    ("aiu_pagos_directos", "3. AIU pagos directos", "flujo"),
    ("gmf", "4. GMF 4x1000", "flujo"),
    ("otros_gastos", "5. Otros gastos", "flujo"),
    ("subtotal", "Subtotal (sale de caja)", "subtotal"),
    ("pagos_directos", "Pagos directos del cliente", "flujo"),
    ("pagos_exentos", "Otros pagos exentos", "flujo"),
    ("total_egresos", "Total egresos", "egresos"),
    ("caja_final", "Saldo en caja", "caja"),
]


def _pesos(v) -> str:
    """Pesos completos con signo: '$1.639.316.058', '-$47.404.252'."""
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        v = 0.0
    s = f"{abs(v):,.0f}".replace(",", ".")
    return f"-${s}" if v < 0 else f"${s}"


def _celda(v) -> str:
    """Número de celda en pesos completos, colombiano, sin '$' (la columna ya
    es de plata). Cero -> vacío, como las celdas en blanco de su Excel."""
    if isinstance(v, str):
        return v
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        v = 0.0
    if round(v) == 0:
        return ""
    s = f"{abs(v):,.0f}".replace(",", ".")
    return f"-{s}" if v < 0 else s


def _clip(pdf: FPDF, texto: str, ancho: float) -> str:
    # "..." en ASCII, no el carácter "…" (U+2026): las fuentes core de fpdf
    # (Helvetica) son latin-1 y ese carácter las hace reventar.
    texto = str(texto)
    if pdf.get_string_width(texto) <= ancho - 2:
        return texto
    while texto and pdf.get_string_width(texto + "...") > ancho - 2:
        texto = texto[:-1]
    return texto + "..."


def _ordenar_cortes(cols) -> list:
    def clave(c):
        s = str(c)
        if s == "Sin corte":
            return (2, 0)
        digs = "".join(ch for ch in s if ch.isdigit())
        return (1, int(digs)) if digs else (0, 0)
    return sorted(cols, key=clave)


def _sin_corte_vacio(tabla, columna="Sin corte", filas=None) -> bool:
    if columna not in tabla.columns:
        return False
    col = pd.to_numeric(tabla[columna], errors="coerce").fillna(0)
    if filas is not None:
        idx = [f for f in filas if f in tabla.index]
        col = col.loc[idx] if idx else col.iloc[0:0]
    return float(col.abs().sum()) == 0


class _Informe(FPDF):
    def __init__(self, proyecto: dict, periodo: str | None):
        super().__init__(orientation="L", unit="mm", format="A4")
        self.proyecto = proyecto
        self.periodo = periodo
        self.set_auto_page_break(True, margin=12)
        self.set_margins(8, 8, 8)

    def header(self):
        if _LOGO.exists():
            try:
                self.image(str(_LOGO), x=self.w - 46, y=6, w=36)
            except Exception:
                pass
        self.set_xy(8, 8)
        self.set_text_color(*NARANJA)
        self.set_font("Helvetica", "B", 14)
        self.cell(0, 6, "ESPACIOS CREATIVOS S.A.S.", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(*GRIS_TX)
        self.set_font("Helvetica", "B", 10)
        self.cell(0, 5, _clip(self, f"PROYECTO: {self.proyecto.get('nombre', '')}", 210),
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font("Helvetica", "", 8.5)
        sub = []
        if self.proyecto.get("cliente_nombre"):
            sub.append(f"Cliente: {self.proyecto['cliente_nombre']}")
        if self.periodo:
            sub.append(f"Período: {self.periodo}")
        if sub:
            self.cell(0, 4.5, "   ·   ".join(sub), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1)

    def footer(self):
        self.set_y(-9)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(150, 150, 150)
        self.cell(0, 5, f"Espacios Creativos · Control de costos e ingresos · página {self.page_no()}",
                  align="C")

    def titulo(self, texto: str):
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(*NARANJA)
        self.cell(0, 7, texto, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(*GRIS_TX)

    def _fila(self, label, valores, extras, label_w, val_w, fs, h,
              fill=None, bold=False, indent=0):
        """Una fila: etiqueta + valores por corte (negativos en rojo) + columnas
        extra (Total, Part.%). `extras` = lista de (texto, ancho, bold)."""
        usar = fill is not None
        if usar:
            self.set_fill_color(*fill)
        self.set_font("Helvetica", "B" if bold else "", fs)
        self.set_text_color(*GRIS_TX)
        etiqueta = ("  " * indent) + " " + _clip(self, label, label_w - 2.2 * indent - 2)
        self.cell(label_w, h, etiqueta, border=1, align="L", fill=usar)
        for v in valores:
            neg = isinstance(v, (int, float)) and v < 0
            self.set_text_color(*(ROJO_TX if neg else GRIS_TX))
            self.cell(val_w, h, _celda(v), border=1, align="R", fill=usar)
        for texto, ancho, eb in extras:
            neg = isinstance(texto, str) and texto.startswith("-$")
            self.set_text_color(*(ROJO_TX if neg else GRIS_TX))
            self.set_font("Helvetica", "B" if (bold or eb) else "", fs)
            self.cell(ancho, h, texto, border=1, align="R", fill=usar)
        self.set_text_color(*GRIS_TX)
        self.ln(h)

    def _encabezado_tabla(self, titulos, anchos, fs, h):
        self.set_font("Helvetica", "B", fs)
        self.set_fill_color(*NARANJA)
        self.set_text_color(*BLANCO)
        for t, w, al in zip(titulos, anchos, ["L"] + ["C"] * (len(titulos) - 1)):
            self.cell(w, h, _clip(self, t, w), border=1, align=al, fill=True)
        self.ln(h)
        self.set_text_color(*GRIS_TX)


def _resumen(cf: pd.DataFrame) -> dict:
    def fila(n):
        return cf.loc[n] if n in cf.index else pd.Series(dtype=float)
    return {
        "ingresos": float(fila("anticipos").sum()),
        "gastos": float(fila("gastos").sum()),
        "gastos_directos": float(fila("pagos_directos").sum()),
        "aiu": float(fila("aiu_gastos").sum() + fila("aiu_pagos_directos").sum()),
        "total_costos": float(fila("total_egresos").sum()),
        "caja": float(fila("caja_final").iloc[-1]) if "caja_final" in cf.index and cf.shape[1] else 0.0,
    }


def _portada(pdf: _Informe, costo: pd.DataFrame):
    pdf.titulo("CONTROL DE COSTOS")
    pdf.set_font("Helvetica", "I", 7.5)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 4.5, "Cifras en pesos colombianos (COP). Capítulos en verde con su % de participación.",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*GRIS_TX)

    if costo is None or costo.empty:
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 8, "Todavía no hay costos clasificados en este proyecto.",
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        return

    tiene_act = "actividad" in costo.columns
    if not tiene_act:
        costo = costo.assign(actividad="", capitulo_orden=0)

    piv = costo.pivot_table(index=["capitulo_orden", "capitulo", "actividad"],
                            columns="corte", values="total", aggfunc="sum", fill_value=0)
    cortes = _ordenar_cortes([c for c in piv.columns
                              if not (c == "Sin corte" and float(piv[c].abs().sum()) == 0)])
    piv = piv[cortes]
    gran_total = float(piv.values.sum()) or 1

    usable = pdf.w - pdf.l_margin - pdf.r_margin
    part_w, total_w, label_w = 15, 22, 64
    val_w = (usable - label_w - total_w - part_w) / max(len(cortes), 1)
    fs = 7 if val_w >= 16 else (6 if val_w >= 12 else 5.2)
    h = 5.0
    pdf._encabezado_tabla(
        ["Capítulo"] + [str(c) for c in cortes] + ["Total", "Part. %"],
        [label_w] + [val_w] * len(cortes) + [total_w, part_w], fs, h,
    )

    for (_orden, cap), sub in piv.groupby(level=[0, 1]):
        cap_por_corte = [float(sub[c].sum()) for c in cortes]
        cap_total = sum(cap_por_corte)
        pct = cap_total / gran_total * 100
        pdf._fila(cap, cap_por_corte,
                  [(_pesos(cap_total), total_w, True), (f"{pct:.2f}%", part_w, True)],
                  label_w, val_w, fs, h, fill=VERDE_BG, bold=True)
        for (_o, _c, act), fila_act in sub.groupby(level=[0, 1, 2]):
            vals = [float(fila_act[c].iloc[0]) for c in cortes]
            if sum(abs(v) for v in vals) == 0:
                continue
            pdf._fila(act, vals, [(_pesos(sum(vals)), total_w, False), ("", part_w, False)],
                      label_w, val_w, fs, h, indent=1)

    total_cortes = [float(piv[c].sum()) for c in cortes]
    pdf._fila("TOTAL", total_cortes,
              [(_pesos(sum(total_cortes)), total_w, True), ("100%", part_w, True)],
              label_w, val_w, fs, h, fill=GRIS_BG, bold=True)


def _cashflow(pdf: _Informe, cf: pd.DataFrame):
    r = _resumen(cf)
    pdf.titulo("CASH FLOW")
    # tira de totales, con los colores de su hoja
    tarjetas = [
        ("Ingresos", r["ingresos"], VERDE), ("Gastos", r["gastos"], NARANJA),
        ("Gastos directos", r["gastos_directos"], NARANJA), ("AIU", r["aiu"], AZUL),
        ("Total costos", r["total_costos"], NARANJA),
        ("Caja", r["caja"], VERDE if r["caja"] >= 0 else ROJO_TX),
    ]
    ancho = (pdf.w - pdf.l_margin - pdf.r_margin) / len(tarjetas)
    y0 = pdf.get_y()
    for i, (tit, val, col) in enumerate(tarjetas):
        pdf.set_xy(pdf.l_margin + i * ancho, y0)
        pdf.set_fill_color(*col)
        pdf.set_text_color(*BLANCO)
        pdf.set_font("Helvetica", "", 7.5)
        pdf.cell(ancho - 2, 5, " " + tit, border=0, new_x=XPos.LEFT, new_y=YPos.NEXT, fill=True, align="L")
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.cell(ancho - 2, 6.5, " " + _pesos(val), border=0, fill=True, align="L")
    pdf.set_xy(pdf.l_margin, y0 + 13)
    pdf.set_text_color(*GRIS_TX)
    pdf.set_font("Helvetica", "I", 7.5)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 4.5, "Cifras en pesos (COP). El saldo final de cada corte es el inicial del siguiente.",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*GRIS_TX)

    if cf is None or cf.empty:
        return
    if _sin_corte_vacio(cf, filas=["anticipos", "total_egresos", "gastos", "pagos_directos"]):
        cf = cf.drop(columns="Sin corte")
    cortes = _ordenar_cortes(cf.columns)

    usable = pdf.w - pdf.l_margin - pdf.r_margin
    total_w, label_w = 24, 50
    val_w = (usable - label_w - total_w) / max(len(cortes), 1)
    fs = 7 if val_w >= 16 else (6 if val_w >= 12 else 5.2)
    h = 5.0
    pdf._encabezado_tabla(
        ["Concepto"] + [str(c) for c in cortes] + ["TOTAL"],
        [label_w] + [val_w] * len(cortes) + [total_w], fs, h,
    )

    fill_por_tipo = {"ingreso": VERDE_BG, "subtotal": GRIS_BG, "egresos": ROSA_BG, "caja": GRIS_BG}
    for clave, etiqueta, tipo in _CONCEPTOS:
        if clave not in cf.index:
            continue
        vals = [float(cf.loc[clave, c]) for c in cortes]
        total = vals[-1] if tipo == "caja" else sum(vals)   # caja no se suma: es saldo
        pdf._fila(etiqueta, vals, [(_pesos(total), total_w, True)],
                  label_w, val_w, fs, h,
                  fill=fill_por_tipo.get(tipo), bold=tipo in ("ingreso", "subtotal", "egresos", "caja"),
                  indent=1 if tipo == "sub" else 0)

    # acumulados (como las dos filas azules al pie de su hoja)
    if "anticipos" in cf.index and "total_egresos" in cf.index:
        ant_ac, gas_ac = [], []
        a = g = 0.0
        for c in cortes:
            a += float(cf.loc["anticipos", c]); ant_ac.append(a)
            g += float(cf.loc["total_egresos", c]); gas_ac.append(g)
        pdf._fila("Anticipos acumulado", ant_ac, [(_pesos(ant_ac[-1]), total_w, True)],
                  label_w, val_w, fs, h, fill=AZUL_BG, bold=True)
        pdf._fila("Gastos acumulado", gas_ac, [(_pesos(gas_ac[-1]), total_w, True)],
                  label_w, val_w, fs, h, fill=AZUL_BG, bold=True)


def generar_informe(proyecto: dict, cash_flow_tabla: pd.DataFrame,
                    costo: pd.DataFrame, periodo: str | None = None) -> bytes:
    """PDF del informe: Portada (control de costos) + Cash Flow, estilo Excel.

    `costo`: DataFrame largo con columnas capitulo, corte, total y —si se tiene—
    actividad y capitulo_orden (para el desglose por actividad de la Portada).
    """
    pdf = _Informe(dict(proyecto) if proyecto is not None else {}, periodo)
    pdf.add_page()
    _portada(pdf, costo)
    pdf.add_page()
    _cashflow(pdf, cash_flow_tabla)
    return bytes(pdf.output())
