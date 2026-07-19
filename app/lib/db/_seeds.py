"""Semillas iniciales y catálogo real de capítulos/actividades."""
from __future__ import annotations

from ._formato import _norm
from ._lecturas import df

TIPOS_OBRA = [
    ("Preliminares", "preliminares", "servicios"),
    ("Cimentación", "cimentacion", "compras"),
    ("Estructura", "estructura", "compras"),
    ("Mampostería", "mamposteria", "compras"),
    ("Acabados", "acabados", "compras"),
    ("Instalaciones eléctricas", "instalaciones", "compras"),
    ("Instalaciones hidrosanitarias", "instalaciones", "compras"),
    ("Carpintería y metálicas", "acabados", "compras"),
    ("Equipos y herramienta", "equipos", "compras"),
    ("Transporte y acarreos", "logistica", "servicios"),
    ("Mano de obra", "mano_de_obra", "servicios"),
    ("Honorarios y diseño", "honorarios", "honorarios"),
    ("Administración", "administracion", "ninguno"),
]

# Tarifas de ejemplo — VALIDAR con el contador antes de usar en serio.
REGLAS_EJEMPLO = [
    ("retefuente", "compras", 2.5, 27),
    ("retefuente", "servicios", 4.0, 4),
    ("retefuente", "honorarios", 10.0, 0),
    ("retefuente", "arriendos", 3.5, 27),
    ("reteiva", "compras", 15.0, 0),
]

CAPITULOS_OBRA = [
    "Preliminares",
    "Cimentación",
    "Estructura",
    "Mampostería",
    "Acabados",
    "Instalaciones eléctricas",
    "Instalaciones hidrosanitarias",
    "Equipos y herramienta",
    "Transporte y acarreos",
    "Mano de obra",
    "Honorarios y diseño",
    "Administración",
]


def sembrar_si_vacio(sb, uid) -> None:
    if sb.table("tipos_gasto").select("id").eq("user_id", uid).limit(1).execute().data:
        return
    sb.table("tipos_gasto").insert(
        [
            {"user_id": uid, "nombre": n, "capitulo": c, "concepto_retencion": r}
            for n, c, r in TIPOS_OBRA
        ]
    ).execute()
    sb.table("reglas_retencion").insert(
        [
            {
                "user_id": uid,
                "tipo": t,
                "concepto": c,
                "tarifa": tf,
                "base_minima_uvt": b,
                "vigencia_desde": "2026-01-01",
                "notas": "Semilla de ejemplo: validar con el contador.",
            }
            for t, c, tf, b in REGLAS_EJEMPLO
        ]
    ).execute()
    try:
        sb.table("uvt").upsert({"anio": 2025, "valor": 49799}).execute()
    except Exception:
        pass  # la tabla uvt se administra con service_role si RLS lo exige


def sembrar_capitulos_si_vacio(sb, uid) -> None:
    if sb.table("capitulos").select("id").eq("user_id", uid).limit(1).execute().data:
        return
    sb.table("capitulos").insert(
        [{"user_id": uid, "nombre": n, "orden": i} for i, n in enumerate(CAPITULOS_OBRA)]
    ).execute()


def catalogo_obra() -> dict:
    """Capítulos y actividades reales de la constructora.

    Salen de su propio archivo: el catálogo maestro es la hoja LCAPITULOS
    de la matriz, pero 96 de los 154 nombres venían pegados sin espacios
    ("Marcacioneimplantaciondelacasaenterreno"). La hoja Portada del Cash
    Flow trae esos mismos códigos bien escritos, así que el nombre se toma
    de ahí cuando existe. Ningún nombre es inventado: los dos vienen de
    archivos suyos.
    """
    import json
    from pathlib import Path

    ruta = Path(__file__).with_name("capitulos_obra.json")
    return json.loads(ruta.read_text(encoding="utf-8"))


def instalar_catalogo_obra(sb, uid) -> dict:
    """Carga (o actualiza) capítulos y actividades con el catálogo real.

    ACTUALIZA lo que ya existe en vez de duplicarlo, que es lo que pidió
    el usuario: las dimensiones ya estaban creadas desde la migración 005.
    El emparejamiento va por CÓDIGO cuando lo hay ("1.02") y si no por
    nombre, de modo que correrlo dos veces no crea nada repetido.
    """
    cat = catalogo_obra()
    resumen = {"capitulos_nuevos": 0, "capitulos_actualizados": 0,
               "actividades_nuevas": 0, "actividades_actualizadas": 0}

    existentes = df(sb.table("capitulos").select("*").eq("user_id", uid).execute())
    por_codigo = {}
    por_nombre = {}
    if not existentes.empty:
        for _, c in existentes.iterrows():
            if c.get("codigo"):
                por_codigo[str(c["codigo"])] = c["id"]
            por_nombre[_norm(c["nombre"])] = c["id"]

    ids_cap = {}
    for i, cap in enumerate(cat["capitulos"]):
        actual = por_codigo.get(cap["codigo"]) or por_nombre.get(_norm(cap["nombre"]))
        fila = {"nombre": cap["nombre"], "codigo": cap["codigo"], "orden": i}
        if actual:
            sb.table("capitulos").update(fila).eq("id", actual).execute()
            ids_cap[cap["codigo"]] = actual
            resumen["capitulos_actualizados"] += 1
        else:
            r = sb.table("capitulos").insert({"user_id": uid, **fila}).execute()
            ids_cap[cap["codigo"]] = r.data[0]["id"]
            resumen["capitulos_nuevos"] += 1

    act_ex = df(sb.table("actividades").select("*").eq("user_id", uid).execute())
    act_codigo, act_nombre = {}, {}
    if not act_ex.empty:
        for _, a in act_ex.iterrows():
            if a.get("codigo"):
                act_codigo[str(a["codigo"])] = a["id"]
            act_nombre[(a.get("capitulo_id"), _norm(a["nombre"]))] = a["id"]

    for act in cat["actividades"]:
        cap_id = ids_cap.get(act["capitulo"])
        actual = (act["codigo"] and act_codigo.get(act["codigo"])) or act_nombre.get(
            (cap_id, _norm(act["nombre"]))
        )
        fila = {"nombre": act["nombre"], "codigo": act["codigo"], "capitulo_id": cap_id}
        if actual:
            sb.table("actividades").update(fila).eq("id", actual).execute()
            resumen["actividades_actualizadas"] += 1
        else:
            r = sb.table("actividades").insert({"user_id": uid, **fila}).execute()
            # El indice en memoria se actualiza DURANTE el bucle: si el
            # catalogo trajera dos veces el mismo nombre en un capitulo, la
            # segunda pasada debe encontrar la fila recien creada y
            # actualizarla, no chocar contra el unique de la base. Paso con
            # el 12.01 repetido de URBANISMO y dejo la carga a medias.
            act_nombre[(cap_id, _norm(act["nombre"]))] = r.data[0]["id"]
            if act["codigo"]:
                act_codigo[act["codigo"]] = r.data[0]["id"]
            resumen["actividades_nuevas"] += 1
    return resumen


