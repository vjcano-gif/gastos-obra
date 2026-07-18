"""Configuración del worker. Todo llega por variables de entorno (GitHub Secrets)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

try:  # redes corporativas con inspección SSL
    import truststore

    truststore.inject_into_ssl()
except Exception:
    pass


@dataclass(frozen=True)
class Config:
    supabase_url: str = os.environ.get("SUPABASE_URL", "")
    supabase_service_key: str = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    user_id: str = os.environ.get("APP_USER_ID", "")  # UUID del único usuario (auth.users)

    gmail_client_id: str = os.environ.get("GMAIL_CLIENT_ID", "")
    gmail_client_secret: str = os.environ.get("GMAIL_CLIENT_SECRET", "")
    gmail_refresh_token: str = os.environ.get("GMAIL_REFRESH_TOKEN", "")
    gmail_query: str = os.environ.get(
        "GMAIL_QUERY",
        "(filename:zip OR filename:xml OR filename:pdf OR consignacion OR consignación "
        "OR abono OR transferencia OR factura) -category:promotions -category:social",
    )

    openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")
    llm_model: str = os.environ.get("LLM_MODEL", "gpt-4o-mini")
    # Modelo para OCR de imágenes: debe soportar visión (gpt-4o-mini la
    # soporta y es el más barato; gpt-4o acierta más en fotos difíciles).
    llm_model_vision: str = os.environ.get("LLM_MODEL_VISION", "gpt-4o-mini")

    pdf_passwords: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            p.strip() for p in os.environ.get("PDF_PASSWORDS", "").split(",") if p.strip()
        )
    )

    # Barrido: días hacia atrás en ejecución normal; el barrido inicial se
    # lanza con BACKFILL_DESDE=AAAA-MM-DD
    dias_ventana: int = int(os.environ.get("DIAS_VENTANA", "3"))
    backfill_desde: str = os.environ.get("BACKFILL_DESDE", "")

    def validar(self) -> None:
        faltan = [
            n
            for n, v in [
                ("SUPABASE_URL", self.supabase_url),
                ("SUPABASE_SERVICE_ROLE_KEY", self.supabase_service_key),
                ("APP_USER_ID", self.user_id),
                ("GMAIL_CLIENT_ID", self.gmail_client_id),
                ("GMAIL_CLIENT_SECRET", self.gmail_client_secret),
                ("GMAIL_REFRESH_TOKEN", self.gmail_refresh_token),
            ]
            if not v
        ]
        if faltan:
            raise SystemExit(f"Faltan variables de entorno: {', '.join(faltan)}")
