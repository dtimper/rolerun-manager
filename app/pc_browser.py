from __future__ import annotations

import unicodedata
from collections.abc import Iterable


def normalize_pc_search_text(value: object) -> str:
    """Normaliza texto para búsquedas del PC tolerantes a tildes/mayúsculas."""
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    return " ".join(
        "".join(ch for ch in text if not unicodedata.combining(ch)).split()
    )


def pokemon_matches_pc_query(pokemon, query: str) -> bool:
    """Busca por especie, mote, habilidad o movimientos.

    Cada palabra escrita por el usuario debe aparecer en alguno de los campos,
    permitiendo consultas como ``gardevoir rastro psiquico`` sin exigir que los
    términos pertenezcan al mismo atributo.
    """
    normalized_query = normalize_pc_search_text(query)
    if not normalized_query:
        return True
    haystack = normalize_pc_search_text(" ".join([
        str(getattr(pokemon, "species", "") or ""),
        str(getattr(pokemon, "nickname", "") or ""),
        str(getattr(pokemon, "ability", "") or ""),
        *[str(move or "") for move in (getattr(pokemon, "moves", None) or [])],
    ]))
    return all(token in haystack for token in normalized_query.split())


def filter_pc_pokemon(pokemon: Iterable, query: str) -> list:
    """Devuelve coincidencias conservando el objeto original (caja/slot incluidos)."""
    return [entry for entry in pokemon if pokemon_matches_pc_query(entry, query)]


def reset_scrollable_to_top(scrollable) -> bool:
    """Resetea un CTkScrollableFrame (o doble de pruebas) al principio.

    CustomTkinter conserva el ``yview`` del canvas al destruir y recrear las
    tarjetas. Si la caja anterior era más alta, una caja corta puede aparecer
    completamente fuera del viewport. Soportamos ambos nombres internos que han
    usado las distintas versiones de CTk.
    """
    for attribute in ("_parent_canvas", "_canvas"):
        canvas = getattr(scrollable, attribute, None)
        if canvas is None:
            continue
        try:
            canvas.yview_moveto(0.0)
            return True
        except Exception:
            continue
    return False
