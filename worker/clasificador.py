"""IA de apoyo (OpenAI): extraer datos de documentos sin XML y sugerir
tipo de gasto. Todo lo que salga de aquí queda con confianza='baja' y
pasa obligatoriamente por revisión humana. Si no hay API key, se degrada
con elegancia: el documento queda en revisión sin datos sugeridos.
"""
from __future__ import annotations

import base64
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


INSTRUCCION_VISION = """Eres un extractor de datos de documentos financieros
colombianos. Te dan la IMAGEN de una factura, cuenta de cobro, recibo o
comprobante de consignación (puede estar fotografiada, torcida o escaneada).

Devuelve SOLO un JSON:
{"sentido": "gasto"|"ingreso", "tipo_documento": "factura"|"cuenta_cobro"|"consignacion"|"otro",
 "proveedor_nombre": str|null, "proveedor_nit": str|null, "numero": str|null,
 "fecha_emision": "AAAA-MM-DD"|null, "total": number|null, "iva": number|null,
 "descripcion": str|null,
 "items": [{"descripcion": str, "cantidad": number|null, "precio_unitario": number|null, "total": number|null}]}

Reglas:
- Una consignación, abono o transferencia RECIBIDA es sentido "ingreso".
- Montos en COP, sin puntos de miles ni símbolo (1250000, no $1.250.000).
- "items" es el detalle de artículos si la imagen lo muestra; si no se
  distingue, devuelve [].
- Si un dato NO se lee con seguridad, usa null. NO inventes valores: un
  humano va a revisar esto y un dato inventado es peor que uno vacío."""


def extraer_de_imagen(cfg: Config, imagenes: list[bytes]) -> dict | None:
    """OCR estructurado con modelo de visión. `imagenes` son PNG/JPG en
    bytes (páginas de un PDF escaneado o la foto de un recibo)."""
    cli = _cliente(cfg)
    if cli is None or not imagenes:
        return None
    try:
        contenido = [{"type": "text", "text": "Extrae los datos de este documento."}]
        for img in imagenes[:3]:
            b64 = base64.b64encode(img).decode()
            contenido.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"},
                }
            )
        resp = cli.chat.completions.create(
            model=cfg.llm_model_vision,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": INSTRUCCION_VISION},
                {"role": "user", "content": contenido},
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
