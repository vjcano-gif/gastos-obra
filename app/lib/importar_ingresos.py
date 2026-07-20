"""Lee la MATRIZ DE INGRESOS del Excel de la constructora y la normaliza.

Los abonos del cliente se llevan a mano en un Excel con estas columnas:

    Fecha | Proyecto | Corte | Detalle | Total | Modo de Pago | Encima / Debajo

Este módulo SOLO parsea y normaliza el archivo (función pura, sin tocar la
base): devuelve un DataFrame con las columnas que espera la tabla
`anticipos`. La página de Ingresos se encarga de emparejar proyecto/corte por
nombre y de insertar sin duplicar. Se separa así para poder probarlo sin
Streamlit ni Supabase.
"""
from __future__ import annotations

import io
import unicodedata

import pandas as pd

# Cómo se llama cada columna de la tabla `anticipos` según el encabezado del
# Excel (normalizado: sin tildes, en minúscula, sin espacios de más).
_ENCABEZADOS = {
    "fecha": "fecha",
    "proyecto": "proyecto",
    "corte": "corte",
    "detalle": "detalle",
    "total": "valor",
    "valor": "valor",
    "modo de pago": "modo_pago",
    "modo pago": "modo_pago",
    "encima / debajo": "legalizacion",
    "encima/debajo": "legalizacion",
    "encima debajo": "legalizacion",
}

COLUMNAS = ["fecha", "proyecto", "corte", "detalle", "valor", "modo_pago", "legalizacion"]


def _norm(txt) -> str:
    """minúscula, sin tildes y sin espacios de sobra — para emparejar."""
    if txt is None:
        return ""
    s = unicodedata.normalize("NFKD", str(txt))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def _num(v) -> float:
    """Número desde una celda que puede venir como float o como '$ 80.000.000'."""
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return 0.0 if pd.isna(v) else float(v)
    s = str(v).strip().replace("$", "").replace(" ", "")
    if not s:
        return 0.0
    # formato colombiano: '.' separa miles, ',' los decimales
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _txt(v) -> str:
    """Texto de una celda, tratando el NaN de pandas (que es 'truthy' y
    reventaba el `or ""`: una celda vacía llegaba como 'nan')."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


def _fecha(v) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    # Fecha real de Excel (datetime/Timestamp): se usa tal cual.
    if hasattr(v, "isoformat") and not isinstance(v, str):
        try:
            return pd.Timestamp(v).date().isoformat()
        except Exception:
            return None
    s = str(v).strip()
    if not s:
        return None
    # Texto: ISO 'YYYY-MM-DD' (sin dayfirst) vs colombiano '7/05/2024' (con
    # barras, día primero). Forzar dayfirst siempre daña las fechas ISO.
    f = pd.to_datetime(s, errors="coerce", dayfirst=("/" in s))
    return None if pd.isna(f) else f.date().isoformat()


def modo_pago_slug(txt) -> str:
    """Texto libre del Excel -> slug válido para anticipos.modo_pago.

    El CHECK de la base solo acepta bancos/efectivo/pago_directo/
    por_identificar. Una transferencia o consignación es 'bancos'; lo que no
    se reconoce queda 'por_identificar' para revisarlo, no se inventa."""
    n = _norm(txt)
    if not n:
        return "por_identificar"
    if "efectivo" in n:
        return "efectivo"
    if "directo" in n:
        return "pago_directo"
    if any(p in n for p in ("transferencia", "consignacion", "banco", "bancos", "pse", "cheque")):
        return "bancos"
    return "por_identificar"


def legalizacion_slug(txt) -> str | None:
    n = _norm(txt)
    if "encima" in n:
        return "encima"
    if "debajo" in n:
        return "debajo"
    return None


def parsear_excel(contenido: bytes) -> pd.DataFrame:
    """Lee el .xlsx y devuelve un DataFrame normalizado con `COLUMNAS`.

    Descarta filas sin proyecto o sin valor (> 0). No toca la base: el
    emparejamiento de proyecto/corte por nombre y la inserción los hace la
    página, que es la que conoce los ids del workspace.
    """
    xls = pd.ExcelFile(io.BytesIO(contenido))
    # El libro real de la constructora trae ~18 hojas (LCORTE, MATRIZ GASTOS,
    # MATRIZ INGRESOS…). La de ingresos casi nunca es la primera, así que se
    # busca por nombre; si no aparece, se usa la primera hoja.
    hoja = next((s for s in xls.sheet_names if "ingreso" in _norm(s)), xls.sheet_names[0])
    crudo = xls.parse(hoja)
    # Renombrar por encabezado normalizado; ignorar columnas que no conocemos
    # (Día, Mes, Año van en la matriz pero no en la tabla `anticipos`).
    renombre = {}
    for col in crudo.columns:
        destino = _ENCABEZADOS.get(_norm(col))
        if destino:
            renombre[col] = destino
    d = crudo.rename(columns=renombre)

    faltan = [c for c in ("proyecto", "valor") if c not in d.columns]
    if faltan:
        raise ValueError(
            "El archivo no tiene las columnas esperadas de la matriz de ingresos "
            "(Fecha, Proyecto, Corte, Detalle, Total, Modo de Pago, Encima/Debajo). "
            f"No se encontró: {', '.join(faltan)}."
        )

    filas = []
    for _, r in d.iterrows():
        proyecto = _txt(r.get("proyecto"))
        valor = _num(r.get("valor"))
        if not proyecto or valor <= 0:
            continue
        corte = _txt(r.get("corte"))
        detalle = _txt(r.get("detalle"))
        filas.append({
            "fecha": _fecha(r.get("fecha")),
            "proyecto": proyecto,
            "corte": corte or None,
            "detalle": detalle or None,
            "valor": valor,
            "modo_pago": modo_pago_slug(r.get("modo_pago")),
            "legalizacion": legalizacion_slug(r.get("legalizacion")),
        })
    salida = pd.DataFrame(filas, columns=COLUMNAS)
    # Garantiza None (no NaN) en las celdas vacías: un NaN de pandas no es
    # serializable a JSON y reventaba el insert a Supabase ("Out of range
    # float values are not JSON compliant: nan").
    return salida.astype(object).where(pd.notna(salida), None)
