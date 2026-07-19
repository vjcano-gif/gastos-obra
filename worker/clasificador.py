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
- "items" es el detalle de artículos si la imagen lo muestra; si no se
  distingue, devuelve [].
- Si un dato NO se lee con seguridad, usa null. NO inventes valores: un
  humano va a revisar esto y un dato inventado es peor que uno vacío.

FORMATO DE NÚMEROS (CRÍTICO — en Colombia el punto separa MILES, no decimales):
    "2.903.600"  ->  2903600     NUNCA 2903.6
    "560.000"    ->  560000      NUNCA 560.0
    "1.120.000"  ->  1120000     NUNCA 1120.0
    "28.000"     ->  28000       NUNCA 28.0
Los decimales van con COMA ("1.234,56" -> 1234.56), y en facturas de
construcción casi nunca aparecen: si dudas, el valor es entero.
Un total de una factura de materiales en pesos colombianos rara vez baja
de 10.000; si te da menos de eso, releelo: te comiste los miles."""


def _corregir_miles(datos: dict) -> dict:
    """Red de seguridad contra el error de miles del OCR.

    En Colombia el punto separa miles ("2.903.600"), pero los modelos de
    visión a veces lo leen como decimal y devuelven 2903.6 — un total mil
    veces menor. Detectado en pruebas con una factura real de materiales.
    El prompt ya lo advierte, pero un prompt no es garantía: aquí se
    verifica contra la SUMA DE LOS ARTÍCULOS, que es un dato independiente.

    Solo corrige cuando la evidencia es contundente (desfase cercano a
    x1000); si no cuadra por otra razón, se deja como está y lo resuelve
    la revisión humana.
    """
    items = datos.get("items") or []
    suma = sum(float(it["total"]) for it in items if isinstance(it.get("total"), (int, float)))
    total = datos.get("total")
    if not suma or not isinstance(total, (int, float)) or total <= 0:
        return datos

    def coherente(t: float) -> bool:
        """¿Ese total cuadra con la suma de artículos? Los artículos suman
        el SUBTOTAL, así que el total va de ahí hacia arriba: + IVA (hasta
        19%), fletes y otros cargos. Se deja un 2% de holgura por abajo
        para redondeos y hasta 40% por arriba."""
        return suma <= t * 1.02 and t <= suma * 1.40

    # Solo se toca si el valor actual NO cuadra y el x1000 SÍ: eso descarta
    # descuadres normales (un flete, un redondeo) y actúa únicamente ante
    # la firma inconfundible del error de miles.
    if not coherente(total) and coherente(total * 1000):
        datos["total"] = round(total * 1000)
        if isinstance(datos.get("iva"), (int, float)):
            datos["iva"] = round(datos["iva"] * 1000)
        datos["_correccion_miles"] = True
    return datos


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
        return _corregir_miles(json.loads(resp.choices[0].message.content))
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
