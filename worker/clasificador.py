"""IA de apoyo (OpenAI): extraer datos de documentos sin XML y sugerir
tipo de gasto. Todo lo que salga de aquí queda con confianza='baja' y
pasa obligatoriamente por revisión humana. Si no hay API key, se degrada
con elegancia: el documento queda en revisión sin datos sugeridos.
"""
from __future__ import annotations

import json

from .config import Config

INSTRUCCION_EXTRACCION = """Eres un extractor de datos financieros colombiano.
Del texto (correo, factura en PDF o cuenta de cobro) devuelve SOLO un JSON:
{"sentido": "gasto"|"ingreso", "tipo_documento": "factura"|"cuenta_cobro"|"consignacion"|"otro",
 "proveedor_nombre": str|null, "proveedor_nit": str|null, "numero": str|null,
 "fecha_emision": "AAAA-MM-DD"|null, "total": number|null, "iva": number|null,
 "descripcion": str|null}
Una consignación, abono o transferencia RECIBIDA es sentido "ingreso".
Montos en COP sin puntos de miles. Si un dato no está, usa null."""


def _cliente(cfg: Config):
    if not cfg.openai_api_key:
        return None
    from openai import OpenAI

    return OpenAI(api_key=cfg.openai_api_key)


def extraer_de_texto(cfg: Config, texto: str) -> dict | None:
    cli = _cliente(cfg)
    if cli is None or not texto.strip():
        return None
    try:
        resp = cli.chat.completions.create(
            model=cfg.llm_model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": INSTRUCCION_EXTRACCION},
                {"role": "user", "content": texto[:12000]},
            ],
            temperature=0,
        )
        return json.loads(resp.choices[0].message.content)
    except Exception:
        return None


def sugerir_tipo_gasto(
    cfg: Config, factura: dict, tipos: list[dict], historial: list[dict]
) -> str | None:
    """Primero el historial (mismo proveedor -> mismo tipo); si no, la IA."""
    nit = factura.get("proveedor_nit")
    if nit:
        usados = [h["tipo_gasto_id"] for h in historial if h.get("proveedor_nit") == nit]
        if usados:
            return max(set(usados), key=usados.count)

    cli = _cliente(cfg)
    if cli is None or not tipos:
        return None
    nombres = {t["nombre"]: t["id"] for t in tipos}
    try:
        resp = cli.chat.completions.create(
            model=cfg.llm_model,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Clasifica este gasto de una constructora en UNA de estas categorías "
                        f"(responde solo el nombre exacto): {list(nombres)}\n\n"
                        f"Proveedor: {factura.get('proveedor_nombre')}\n"
                        f"Descripción: {(factura.get('descripcion') or '')[:800]}"
                    ),
                }
            ],
            temperature=0,
        )
        return nombres.get(resp.choices[0].message.content.strip())
    except Exception:
        return None
