"""Acceso a Supabase para el worker (service_role, solo en GitHub Actions)."""
from __future__ import annotations

import hashlib
import re
from datetime import date

from supabase import create_client

from .config import Config


class Store:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.sb = create_client(cfg.supabase_url, cfg.supabase_service_key)
        self.uid = cfg.user_id

    # ------------------------------------------------------------- dedup
    def correo_procesado(self, gmail_id: str) -> bool:
        """True si el correo ya se proceso con exito. Los que fallaron con
        error (ej. cortes de red transitorios) no cuentan como procesados,
        para que la siguiente corrida los reintente."""
        r = (
            self.sb.table("correos_procesados")
            .select("id")
            .eq("user_id", self.uid)
            .eq("gmail_message_id", gmail_id)
            .neq("resultado", "error")
            .limit(1)
            .execute()
        )
        return bool(r.data)

    def marcar_correo(self, gmail_id: str, resultado: str, detalle: str = "") -> None:
        self.sb.table("correos_procesados").upsert(
            {
                "user_id": self.uid,
                "gmail_message_id": gmail_id,
                "resultado": resultado,
                "detalle": detalle[:500],
            },
            on_conflict="user_id,gmail_message_id",
        ).execute()

    def cufe_existe(self, cufe: str) -> bool:
        r = (
            self.sb.table("facturas")
            .select("id")
            .eq("user_id", self.uid)
            .eq("cufe", cufe)
            .limit(1)
            .execute()
        )
        return bool(r.data)

    def hash_existe(self, h: str) -> bool:
        r = (
            self.sb.table("facturas")
            .select("id")
            .eq("user_id", self.uid)
            .eq("hash_adjunto", h)
            .limit(1)
            .execute()
        )
        return bool(r.data)

    def factura_por_hash(self, h: str) -> dict | None:
        r = (
            self.sb.table("facturas")
            .select("*")
            .eq("user_id", self.uid)
            .eq("hash_adjunto", h)
            .limit(1)
            .execute()
        )
        return r.data[0] if r.data else None

    def factura_por_cufe(self, cufe: str) -> dict | None:
        r = (
            self.sb.table("facturas")
            .select("*")
            .eq("user_id", self.uid)
            .eq("cufe", cufe)
            .limit(1)
            .execute()
        )
        return r.data[0] if r.data else None

    def mimes_de_factura(self, factura_id: str) -> set[str]:
        r = (
            self.sb.table("documentos")
            .select("mime")
            .eq("factura_id", factura_id)
            .execute()
        )
        return {d.get("mime") for d in (r.data or [])}

    def tiene_items(self, factura_id: str) -> bool:
        r = (
            self.sb.table("factura_items")
            .select("id")
            .eq("factura_id", factura_id)
            .limit(1)
            .execute()
        )
        return bool(r.data)

    def insertar_items(self, factura_id: str, items: list[dict]) -> None:
        if not items:
            return
        self.sb.table("factura_items").insert(
            [{**it, "user_id": self.uid, "factura_id": factura_id} for it in items]
        ).execute()

    def buscar_ingreso_parecido(self, monto: float, fecha: str) -> str | None:
        """Heurística para consignaciones: mismo monto y fecha ya registrados."""
        r = (
            self.sb.table("facturas")
            .select("id")
            .eq("user_id", self.uid)
            .eq("sentido", "ingreso")
            .eq("total", monto)
            .eq("fecha_emision", fecha)
            .limit(1)
            .execute()
        )
        return r.data[0]["id"] if r.data else None

    # ----------------------------------------------------------- escritura
    def insertar_factura(self, factura: dict, items: list[dict]) -> str:
        factura = {**factura, "user_id": self.uid}
        res = self.sb.table("facturas").insert(factura).execute()
        fid = res.data[0]["id"]
        if items:
            self.sb.table("factura_items").insert(
                [{**it, "user_id": self.uid, "factura_id": fid} for it in items]
            ).execute()
        return fid

    def subir_documento(
        self, factura_id: str, nombre_original: str, contenido: bytes, mime: str, renombrado: str
    ) -> None:
        h = hashlib.sha256(contenido).hexdigest()
        seguro = re.sub(r"[^A-Za-z0-9._-]", "_", renombrado)[:180]
        ruta = f"{self.uid}/{factura_id}/{seguro}"
        self.sb.storage.from_("documentos").upload(
            ruta, contenido, {"content-type": mime, "upsert": "true"}
        )
        self.sb.table("documentos").insert(
            {
                "user_id": self.uid,
                "factura_id": factura_id,
                "storage_path": ruta,
                "nombre_original": nombre_original[:200],
                "nombre_renombrado": renombrado[:200],
                "mime": mime,
                "hash": h,
            }
        ).execute()

    # ------------------------------------------------------------ lectura
    def reglas_retencion(self) -> list[dict]:
        return (
            self.sb.table("reglas_retencion").select("*").eq("user_id", self.uid).execute().data
            or []
        )

    def uvt(self) -> dict[int, float]:
        filas = self.sb.table("uvt").select("*").execute().data or []
        return {f["anio"]: float(f["valor"]) for f in filas}

    def historial_clasificacion(self) -> list[dict]:
        """Proveedor -> tipo de gasto más usado, para que la IA aprenda del pasado."""
        r = (
            self.sb.table("facturas")
            .select("proveedor_nit, tipo_gasto_id, proyecto_id")
            .eq("user_id", self.uid)
            .neq("estado", "extraida")
            .not_.is_("tipo_gasto_id", "null")
            .limit(2000)
            .execute()
        )
        return r.data or []


def nombre_renombrado(factura: dict, codigo_proyecto: str | None = None) -> str:
    """AAAAMMDD-PROVEEDOR-NUMERO-FORMAPAGO-PROYECTO.pdf"""
    fecha = (factura.get("fecha_emision") or str(date.today())).replace("-", "")
    prov = (factura.get("proveedor_nombre") or "SIN-PROVEEDOR")[:40].upper().strip()
    num = factura.get("numero") or "SN"
    pago = (factura.get("metodo_pago") or factura.get("forma_pago") or "NA").upper()
    partes = [fecha, prov, num, pago]
    if codigo_proyecto:
        partes.append(codigo_proyecto.upper())
    return "-".join(re.sub(r"[^A-Za-z0-9 ]", "", p).strip().replace(" ", " ") for p in partes) + ".pdf"
