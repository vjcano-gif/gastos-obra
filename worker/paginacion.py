"""Paginacion de PostgREST para el worker.

PostgREST corta cada respuesta en 1.000 filas SIN avisar, ignorando el
.limit() pedido. La app tiene su propio traer_todo() (en app/lib/db.py);
el worker no puede importarlo sin arrastrar Streamlit y sin acoplar el
worker a la capa de la app, asi que comparte esta copia entre sus modulos
(importar_matriz, reprocesar_items). Son dos deployables distintos: una
copia por arbol es lo correcto, no una redundancia que corregir.
"""
from __future__ import annotations

TAM_PAGINA = 1000


def traer_todo(query) -> list[dict]:
    """Todas las filas de una consulta PostgREST ya ordenada (sin .execute()).

    El .order() lo pone quien llama y debe ser estable (por id): sin un
    orden determinista, dos paginas pueden repetir o saltarse filas.
    """
    filas: list[dict] = []
    inicio = 0
    while True:
        lote = query.range(inicio, inicio + TAM_PAGINA - 1).execute().data or []
        filas.extend(lote)
        if len(lote) < TAM_PAGINA:
            return filas
        inicio += TAM_PAGINA
