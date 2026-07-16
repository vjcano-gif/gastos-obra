"""Evidencias en PDF con fpdf2 (puro Python, sin dependencias del sistema).

- correo_a_pdf: cuando el soporte es solo el cuerpo del correo (consignaciones).
- desbloquear_pdf: extractos o facturas protegidas con contraseña.
Nunca lanza excepción: si algo falla devuelve None y la factura sigue su curso.
"""
from __future__ import annotations

import fitz  # PyMuPDF
from fpdf import FPDF


def _latin(t: str) -> str:
    return (t or "").encode("latin-1", "replace").decode("latin-1")


def correo_a_pdf(asunto: str, remitente: str, fecha: str, cuerpo: str) -> bytes | None:
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 12)
        pdf.multi_cell(0, 7, _latin(f"Evidencia de correo: {asunto}"))
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 5, _latin(f"De: {remitente}\nFecha: {fecha}"))
        pdf.ln(3)
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 5, _latin(cuerpo[:8000]))
        return bytes(pdf.output())
    except Exception:
        return None


def desbloquear_pdf(contenido: bytes, contrasenas: tuple[str, ...]) -> bytes:
    """Si el PDF pide contraseña, intenta con la lista y devuelve una copia libre."""
    try:
        doc = fitz.open(stream=contenido, filetype="pdf")
        if not doc.needs_pass:
            return contenido
        for c in contrasenas:
            if doc.authenticate(c):
                return doc.tobytes(encryption=fitz.PDF_ENCRYPT_NONE)
        return contenido
    except Exception:
        return contenido
