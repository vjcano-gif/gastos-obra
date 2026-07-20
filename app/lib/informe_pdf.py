"""Informe del proyecto para el cliente, con la MISMA estructura del Excel
"Cash Flow Casa Vieja 61": una Portada de control de costos (capítulo × corte)
y un Cash Flow (totales + tabla por corte), con el logo de Espacios Creativos.

Es una función pura: recibe lo que ya calcula la app (`db.cash_flow` y el
costo por capítulo) y devuelve los bytes de un PDF. El mismo PDF sirve para
los tres canales que pidió el usuario: descargarlo, adjuntarlo al correo del
cliente y verlo dentro de la app.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from fpdf import FPDF
from fpdf.enums import XPos, YPos

NARANJA = (216, 90, 48)
VERDE = (29, 158, 117)
AZUL = (91, 141, 239)
GRIS_TX = (55, 55, 55)
GRIS_BG = (235, 235, 235)
BLANCO = (255, 255, 255)

_LOGO = Path(__file__).with_name("assets") / "logo_espacios.png"

# Orden y etiqueta de las filas del cash flow, igual que en su hoja.
_CONCEPTOS = [
    ("caja_inicial", "Saldo inicial de caja"),
    ("anticipos", "Anticipos del cliente"),
    ("anticipos_bancos", "   Bancos"),
    ("anticipos_efectivo", "   Efectivo"),
    ("gastos", "Gastos"),
    ("aiu_gastos", "AIU gastos"),
    ("aiu_pagos_directos", "AIU pagos directos"),
    ("gmf", "GMF 4x1000"),
    ("otros_gastos", "Otros gastos"),
    ("subtotal", "Subtotal (sale de caja)"),
    ("pagos_directos", "Pagos directos del cliente"),
    ("pagos_exentos", "Otros pagos exentos"),
    ("total_egresos", "Total egresos"),
    ("caja_final", "Saldo en caja"),
]
_FUERTES = {"Anticipos del cliente", "Subtotal (sale de caja)", "Total egresos", "Saldo en caja"}


def _cop(v) -> str:
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        v = 0.0
    s = f"{abs(v):,.0f}".replace(",", ".")
    return f"-${s}" if v < 0 else f"${s}"


def _mm(v) -> str:
    """Compacto en millones (1.639.316.058 -> '1.639,3'), formato colombiano."""
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        v = 0.0
    if v == 0:
        return "-"
    s = f"{v / 1e6:,.1f}"                        # '1,639.3'
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _clip(pdf: FPDF, texto: str, ancho: float) -> str:
    """Recorta `texto` para que quepa en `ancho` mm (con un margen)."""
    texto = str(texto)
    if pdf.get_string_width(texto) <= ancho - 2:
        return texto
    while texto and pdf.get_string_width(texto + "…") > ancho - 2:
        texto = texto[:-1]
    return texto + "…"


def _ordenar_cortes(cols) -> list:
    """Corte 1, Corte 2, …, y 'Sin corte' de último."""
    def clave(c):
        s = str(c)
        if s == "Sin corte":
            return (2, 0)
        digs = "".join(ch for ch in s if ch.isdigit())
        return (1, int(digs)) if digs else (0, 0)
    return sorted(cols, key=clave)


def _sin_corte_vacio(tabla, columna="Sin corte", filas=None) -> bool:
    """True si la columna 'Sin corte' no aporta nada: para no ensuciar el
    informe del cliente con una columna en blanco.

    En el cash flow la caja se ENCADENA, así que 'Sin corte' hereda el saldo
    del último corte aunque no tenga movimiento propio. Por eso se puede
    limitar la revisión a las filas de actividad real (anticipos, egresos…):
    si esas están en cero, la columna solo arrastra caja y se oculta.
    """
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
        self.set_margins(10, 10, 10)

    def header(self):
        if _LOGO.exists():
            try:
                self.image(str(_LOGO), x=self.w - 48, y=7, w=38)
            except Exception:
                pass
        self.set_xy(10, 9)
        self.set_text_color(*NARANJA)
        self.set_font("Helvetica", "B", 15)
        self.cell(0, 7, "ESPACIOS CREATIVOS S.A.S.", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(*GRIS_TX)
        self.set_font("Helvetica", "B", 11)
        self.cell(0, 6, _clip(self, f"Proyecto: {self.proyecto.get('nombre', '')}", 200), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font("Helvetica", "", 9)
        sub = []
        if self.proyecto.get("cliente_nombre"):
            sub.append(f"Cliente: {self.proyecto['cliente_nombre']}")
        if self.periodo:
            sub.append(f"Período: {self.periodo}")
        if sub:
            self.cell(0, 5, "   ·   ".join(sub), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1)

    def footer(self):
        self.set_y(-10)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(150, 150, 150)
        self.cell(0, 5, f"Espacios Creativos · Control de costos e ingresos · página {self.page_no()}",
                  align="C")

    # ---------------------------------------------------------------- tablas
    def titulo_seccion(self, texto: str):
        self.set_font("Helvetica", "B", 12)
        self.set_text_color(*NARANJA)
        self.cell(0, 8, texto, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(*GRIS_TX)

    def tabla(self, encabezados, filas, label_w, fmt=_mm):
        usable = self.w - self.l_margin - self.r_margin
        n_val = max(len(encabezados) - 1, 1)
        val_w = (usable - label_w) / n_val
        fs = 8 if val_w >= 20 else (7 if val_w >= 15 else 6)
        h = 5.6
        # encabezado
        self.set_font("Helvetica", "B", fs)
        self.set_fill_color(*NARANJA)
        self.set_text_color(*BLANCO)
        self.cell(label_w, h, " " + str(encabezados[0]), border=1, align="L", fill=True)
        for t in encabezados[1:]:
            self.cell(val_w, h, _clip(self, t, val_w), border=1, align="C", fill=True)
        self.ln(h)
        # filas
        self.set_text_color(*GRIS_TX)
        for label, vals in filas:
            fuerte = str(label).strip() in _FUERTES or str(label).strip().upper() == "TOTAL"
            self.set_font("Helvetica", "B" if fuerte else "", fs)
            self.set_fill_color(*(GRIS_BG if fuerte else BLANCO))
            self.cell(label_w, h, " " + _clip(self, label, label_w), border=1, align="L", fill=True)
            for v in vals:
                txt = v if isinstance(v, str) else fmt(v)
                self.cell(val_w, h, txt, border=1, align="R", fill=True)
            self.ln(h)


def _resumen(cash_flow_tabla: pd.DataFrame) -> dict:
    def fila(nombre):
        return cash_flow_tabla.loc[nombre] if nombre in cash_flow_tabla.index else pd.Series(dtype=float)
    return {
        "ingresos": float(fila("anticipos").sum()),
        "gastos": float(fila("gastos").sum()),
        "gastos_directos": float(fila("pagos_directos").sum()),
        "aiu": float(fila("aiu_gastos").sum() + fila("aiu_pagos_directos").sum()),
        "total_costos": float(fila("total_egresos").sum()),
        "caja": float(fila("caja_final").iloc[-1]) if "caja_final" in cash_flow_tabla.index and cash_flow_tabla.shape[1] else 0.0,
    }


def generar_informe(proyecto: dict, cash_flow_tabla: pd.DataFrame,
                    costo_capitulo: pd.DataFrame, periodo: str | None = None) -> bytes:
    """PDF del informe del proyecto: Portada (control de costos) + Cash Flow.

    `proyecto`: dict con al menos 'nombre' (y opcional 'cliente_nombre').
    `cash_flow_tabla`: salida de db.cash_flow (índice=conceptos, columnas=cortes).
    `costo_capitulo`: DataFrame largo con columnas capitulo, corte, total.
    """
    proyecto = dict(proyecto) if proyecto is not None else {}
    pdf = _Informe(proyecto, periodo)

    # ------------------------------------------------ Página 1: control de costos
    pdf.add_page()
    pdf.titulo_seccion("CONTROL DE COSTOS por capítulo y corte")
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 5, "Cifras en millones de pesos (COP).", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*GRIS_TX)

    if costo_capitulo is not None and not costo_capitulo.empty:
        matriz = costo_capitulo.pivot_table(
            index="capitulo", columns="corte", values="total", aggfunc="sum", fill_value=0
        )
        if _sin_corte_vacio(matriz):
            matriz = matriz.drop(columns="Sin corte")
        cortes = _ordenar_cortes(matriz.columns)
        matriz = matriz[cortes]
        matriz["Total"] = matriz.sum(axis=1)
        matriz = matriz.sort_values("Total", ascending=False)
        encabezados = ["Capítulo"] + [str(c) for c in cortes] + ["Total"]
        filas = [(cap, list(matriz.loc[cap, cortes]) + [matriz.loc[cap, "Total"]])
                 for cap in matriz.index]
        total_row = [float(matriz[c].sum()) for c in cortes] + [float(matriz["Total"].sum())]
        filas.append(("TOTAL", total_row))
        pdf.tabla(encabezados, filas, label_w=78)
    else:
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 8, "Todavía no hay costos clasificados por capítulo en este proyecto.", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # ------------------------------------------------ Página 2: cash flow
    pdf.add_page()
    r = _resumen(cash_flow_tabla)
    pdf.titulo_seccion("CASH FLOW del proyecto")

    # tira de totales (como el bloque superior de su hoja)
    tarjetas = [
        ("Ingresos (abonos)", r["ingresos"], VERDE),
        ("Gastos", r["gastos"], NARANJA),
        ("Gastos directos", r["gastos_directos"], NARANJA),
        ("AIU (comisión)", r["aiu"], AZUL),
        ("Total costos", r["total_costos"], NARANJA),
        ("Caja del proyecto", r["caja"], VERDE if r["caja"] >= 0 else NARANJA),
    ]
    ancho = (pdf.w - pdf.l_margin - pdf.r_margin) / len(tarjetas)
    y0 = pdf.get_y()
    for i, (tit, val, col) in enumerate(tarjetas):
        x = pdf.l_margin + i * ancho
        pdf.set_xy(x, y0)
        pdf.set_fill_color(*col)
        pdf.set_text_color(*BLANCO)
        pdf.set_font("Helvetica", "", 7.5)
        pdf.cell(ancho - 2, 5, " " + tit, border=0, new_x=XPos.LEFT, new_y=YPos.NEXT, fill=True, align="L")
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(ancho - 2, 7, " " + _cop(val), border=0, fill=True, align="L")
    pdf.set_xy(pdf.l_margin, y0 + 14)
    pdf.set_text_color(*GRIS_TX)
    pdf.ln(2)

    if cash_flow_tabla is not None and not cash_flow_tabla.empty:
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(120, 120, 120)
        pdf.cell(0, 5, "Cifras en millones de pesos (COP). El saldo final de cada corte es el inicial del siguiente.", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(*GRIS_TX)
        _cf_vacio = _sin_corte_vacio(
            cash_flow_tabla, filas=["anticipos", "total_egresos", "gastos", "pagos_directos"]
        )
        cf = cash_flow_tabla.drop(columns="Sin corte") if _cf_vacio else cash_flow_tabla
        cortes = _ordenar_cortes(cf.columns)
        encabezados = ["Concepto"] + [str(c) for c in cortes]
        filas = []
        for clave, etiqueta in _CONCEPTOS:
            if clave in cash_flow_tabla.index:
                filas.append((etiqueta, [cash_flow_tabla.loc[clave, c] for c in cortes]))
        pdf.tabla(encabezados, filas, label_w=58)

    return bytes(pdf.output())
