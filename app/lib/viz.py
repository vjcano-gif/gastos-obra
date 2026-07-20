"""Componentes de visualización estándar para toda la app.

Reglas que el usuario pidió que fueran transversales, no de una pantalla:

  - Selector de proyecto en LISTA desplegable, no botones: con cientos de
    obras una grilla de radios es inservible.
  - Toda gráfica lleva ETIQUETA DE DATO (el valor sobre la barra).
  - Las tablas que muestran "una parte de un todo" llevan el % del total.
  - Filtro cruzado: al hacer clic en una barra (p.ej. un capítulo), las
    demás visuales de la página se filtran por ese valor.
  - Nada de tortas (pie): barras, área o cascada, que se comparan mejor.

Están aquí, en un solo sitio, para que las cuatro reglas se apliquen
igual en Dashboard, Cash Flow, Flujo semanal y Revisión sin repetirlas.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib import db

COLOR_GASTO = "#D85A30"
COLOR_INGRESO = "#1D9E75"
COLOR_NEUTRO = "#5B8DEF"
_RESALTE = "#B03A1A"  # barra seleccionada en el filtro cruzado


def selector_proyecto(pr: pd.DataFrame, key: str, incluir_todos: bool = True):
    """Lista desplegable de proyectos. Devuelve (nombre, proyecto_id|None).

    Reemplaza al radio: aguanta cientos de proyectos sin llenar la pantalla.
    """
    opciones = (["Todos los proyectos"] if incluir_todos else [])
    if not pr.empty:
        opciones += pr["nombre"].tolist()
    if not opciones:
        return (None, None)
    nombre = st.selectbox("Proyecto", opciones, key=key)
    if nombre == "Todos los proyectos" or pr.empty:
        return (nombre, None)
    pid = pr.loc[pr["nombre"] == nombre, "id"].iloc[0]
    return (nombre, pid)


def _puntos_seleccionados(evento) -> list:
    """Puntos de una selección de Plotly, tolerando las dos formas en que
    Streamlit la devuelve (dict o atributo)."""
    if evento is None:
        return []
    sel = evento.get("selection", {}) if hasattr(evento, "get") else getattr(evento, "selection", {})
    if sel is None:
        return []
    return sel.get("points", []) if hasattr(sel, "get") else getattr(sel, "points", []) or []


def barras(
    nombres,
    valores,
    key: str,
    color: str = COLOR_GASTO,
    seleccionable: bool = False,
    resaltado: str | None = None,
    titulo_x: str = "COP",
    porcentaje: bool = False,
) -> str | None:
    """Barras horizontales con etiqueta de dato (el valor en $).

    Si `seleccionable`, se puede hacer clic en una barra para filtrar el
    resto de la página; devuelve el nombre de la barra elegida (o None).
    `resaltado` pinta distinto la barra activa del filtro cruzado.
    `porcentaje=True` agrega el % del total a la etiqueta: para cuando la
    barra es una PROPORCIÓN (cada obra/capítulo es parte del gasto total).
    """
    nombres = list(nombres)
    valores = [float(v or 0) for v in valores]
    colores = [_RESALTE if (resaltado and n == resaltado) else color for n in nombres]
    total = sum(valores) or 1
    if porcentaje:
        etiquetas = [f"{db.cop(v)} · {v / total * 100:.1f}%" for v in valores]
    else:
        etiquetas = [db.cop(v) for v in valores]

    fig = go.Figure(
        go.Bar(
            x=valores,
            y=nombres,
            orientation="h",
            marker_color=colores,
            text=etiquetas,
            textposition="auto",
            cliponaxis=False,
        )
    )
    fig.update_layout(
        height=max(220, 38 * len(nombres) + 70),
        xaxis_title=titulo_x,
        margin=dict(t=30, l=10, r=40, b=10),
        uniformtext_minsize=8,
        uniformtext_mode="hide",
        showlegend=False,
    )
    if seleccionable:
        ev = st.plotly_chart(fig, use_container_width=True, on_select="rerun", key=key)
        pts = _puntos_seleccionados(ev)
        return pts[0].get("y") if pts else None
    st.plotly_chart(fig, use_container_width=True, key=key)
    return None


def foco_actual(key: str) -> str | None:
    """Valor del filtro cruzado activo (la barra clicada), leído del estado
    de sesión al inicio del rerun para poder filtrar ANTES de dibujar."""
    estado = st.session_state.get(key)
    pts = _puntos_seleccionados(estado)
    return pts[0].get("y") if pts else None


def tabla_parte_del_todo(nombres, valores, col_nombre: str = "Concepto") -> None:
    """Tabla de magnitudes que son parte de un todo: agrega el % del total,
    ordenada de mayor a menor. El % es lo que pidió el usuario para leer
    cuánto pesa cada rubro dentro del conjunto."""
    d = pd.DataFrame({col_nombre: list(nombres), "_v": [float(v or 0) for v in valores]})
    d = d.sort_values("_v", ascending=False)
    total = d["_v"].sum() or 1
    d["% del total"] = (d["_v"] / total * 100).map(lambda p: f"{p:.1f}%")
    d["Valor"] = d["_v"].map(db.cop)
    st.dataframe(
        d[[col_nombre, "Valor", "% del total"]],
        use_container_width=True,
        hide_index=True,
    )


def por_dimension(detalle: pd.DataFrame, dim_df: pd.DataFrame, id_col: str,
                  defecto: str = "Sin clasificar") -> pd.Series:
    """Suma `valor` del detalle agrupado por el NOMBRE de una dimensión
    (capítulo, actividad, proyecto). Devuelve una serie nombre -> total."""
    if detalle is None or detalle.empty:
        return pd.Series(dtype=float)
    d = detalle.merge(
        dim_df[["id", "nombre"]], left_on=id_col, right_on="id", how="left"
    )
    d["nombre"] = d["nombre"].where(d["nombre"].notna(), defecto)
    return d.groupby("nombre")["valor"].sum()
