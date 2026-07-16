"""Cliente Gmail de solo lectura, con refresh token (igual patrón probado
en el proyecto base: OAuth de app instalada + token renovable)."""
from __future__ import annotations

import base64
from datetime import date, timedelta

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from .config import Config


def servicio(cfg: Config):
    creds = Credentials(
        token=None,
        refresh_token=cfg.gmail_refresh_token,
        client_id=cfg.gmail_client_id,
        client_secret=cfg.gmail_client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def buscar_mensajes(svc, cfg: Config) -> list[str]:
    """IDs de mensajes según la ventana (o el barrido inicial completo)."""
    if cfg.backfill_desde:
        desde = cfg.backfill_desde.replace("-", "/")
    else:
        desde = (date.today() - timedelta(days=cfg.dias_ventana)).strftime("%Y/%m/%d")
    consulta = f"{cfg.gmail_query} after:{desde}"

    ids, token = [], None
    while True:
        resp = (
            svc.users()
            .messages()
            .list(userId="me", q=consulta, pageToken=token, maxResults=100)
            .execute()
        )
        ids += [m["id"] for m in resp.get("messages", [])]
        token = resp.get("nextPageToken")
        if not token:
            return ids


def leer_mensaje(svc, msg_id: str) -> dict:
    """Devuelve asunto, remitente, fecha, cuerpo en texto y adjuntos [(nombre, bytes)]."""
    msg = svc.users().messages().get(userId="me", id=msg_id, format="full").execute()
    headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}

    cuerpo, adjuntos = [], []

    def recorrer(parte):
        datos = parte.get("body", {})
        nombre = parte.get("filename") or ""
        if nombre and (datos.get("attachmentId") or datos.get("data")):
            if datos.get("attachmentId"):
                adj = (
                    svc.users()
                    .messages()
                    .attachments()
                    .get(userId="me", messageId=msg_id, id=datos["attachmentId"])
                    .execute()
                )
                contenido = base64.urlsafe_b64decode(adj["data"])
            else:
                contenido = base64.urlsafe_b64decode(datos["data"])
            adjuntos.append((nombre, contenido))
        elif parte.get("mimeType", "").startswith("text/") and datos.get("data"):
            cuerpo.append(base64.urlsafe_b64decode(datos["data"]).decode("utf-8", "replace"))
        for sub in parte.get("parts", []):
            recorrer(sub)

    recorrer(msg["payload"])
    return {
        "id": msg_id,
        "asunto": headers.get("subject", ""),
        "remitente": headers.get("from", ""),
        "fecha": headers.get("date", ""),
        "cuerpo": "\n".join(cuerpo),
        "adjuntos": adjuntos,
    }
