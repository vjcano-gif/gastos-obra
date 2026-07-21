"""Lee un Excel de presupuesto por actividad y lo normaliza para la tabla
`presupuesto`. Función pura (no toca la base): la página empareja capítulo y
actividad por nombre e inserta. Contraparte de plantillas.presupuesto()."""
from __future__ import annotations

import io
import re
import unicodedata

import pandas as pd

MARCA_EJEMPLO = "ejemplo"   # fila de ejemplo de la plantilla: no se importa

_ENCABEZADOS = {
    "capitulo": "capitulo",
    "actividad": "actividad",
    "subactividad": "subactividad",
    "unidad": "unidad",
    "cantidad": "cantidad",
    "costo unitario": "costo_unitario", "valor unitario": "costo_unitario", "unitario": "costo_unitario",
    "costo total": "costo_total", "valor total": "costo_total", "total": "costo_total",
}
COLUMNAS = ["capitulo", "actividad", "subactividad", "unidad",
            "cantidad", "costo_unitario", "costo_total"]


def _norm(txt) -> str:
    if txt is None:
        return ""
    s = unicodedata.normalize("NFKD", str(txt))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def _txt(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


def _num(v) -> float:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("$", "").replace(" ", "")
    if not s:
        return 0.0
    if "," in s:                                    # coma decimal: los '.' son miles
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):   # 1.234.567 -> miles
        s = s.replace(".", "")
    # si no, se deja tal cual: un punto decimal ('1234.5') se respeta
    try:
        return float(s)
    except ValueError:
        return 0.0


def parsear_excel(contenido: bytes) -> pd.DataFrame:
    """Devuelve un DataFrame con `COLUMNAS`. Descarta filas sin identificación
    (capítulo/actividad/subactividad) o sin valor. El costo total se calcula
    como cantidad × unitario si no viene explícito."""
    xls = pd.ExcelFile(io.BytesIO(contenido))
    hoja = next((s for s in xls.sheet_names if "presupuesto" in _norm(s)), xls.sheet_names[0])
    crudo = xls.parse(hoja)
    renombre = {c: _ENCABEZADOS[_norm(c)] for c in crudo.columns if _norm(c) in _ENCABEZADOS}
    d = crudo.rename(columns=renombre)
    if not any(col in d.columns for col in ("capitulo", "actividad", "subactividad")):
        raise ValueError(
            "El archivo no tiene columnas de presupuesto (Capítulo, Actividad, "
            "Subactividad, Unidad, Cantidad, Costo unitario, Costo total)."
        )

    filas = []
    for _, r in d.iterrows():
        cap, act, sub = _txt(r.get("capitulo")), _txt(r.get("actividad")), _txt(r.get("subactividad"))
        if _norm(cap).startswith(MARCA_EJEMPLO):     # fila de ejemplo de la plantilla
            continue
        cant, unit = _num(r.get("cantidad")), _num(r.get("costo_unitario"))
        total = _num(r.get("costo_total")) or round(cant * unit, 2)
        if not (cap or act or sub) or total <= 0:
            continue
        filas.append({
            "capitulo": cap or None, "actividad": act or None, "subactividad": sub or None,
            "unidad": _txt(r.get("unidad")) or None,
            "cantidad": cant, "costo_unitario": unit, "costo_total": total,
        })
    salida = pd.DataFrame(filas, columns=COLUMNAS)
    return salida.astype(object).where(pd.notna(salida), None)
