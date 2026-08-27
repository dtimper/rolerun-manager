from __future__ import annotations

"""Nombres y orden canónico de características visibles.

El orden binario de PB8 no coincide con el orden que se presenta al usuario.
Este módulo mantiene esa traducción fuera de la UI y no contiene escrituras.
"""

from dataclasses import dataclass


STAT_KEYS = ("hp", "attack", "defense", "sp_attack", "sp_defense", "speed")
STAT_LABELS = {
    "hp": "PS",
    "attack": "ATAQUE",
    "defense": "DEFENSA",
    "sp_attack": "AT. ESP.",
    "sp_defense": "DEF. ESP.",
    "speed": "VELOCIDAD",
}

# PKHeX.Core 26.7.7, GameInfo.Strings.natures para español.
SPANISH_NATURES = (
    "Fuerte", "Huraña", "Audaz", "Firme", "Pícara",
    "Osada", "Dócil", "Plácida", "Agitada", "Floja",
    "Miedosa", "Activa", "Seria", "Alegre", "Ingenua",
    "Modesta", "Afable", "Mansa", "Tímida", "Alocada",
    "Serena", "Amable", "Grosera", "Cauta", "Rara",
)

# NatureAmp usa esta matriz 5×5: fila = stat que sube, columna = stat que baja.
_NATURE_STAT_ORDER = ("attack", "defense", "speed", "sp_attack", "sp_defense")


@dataclass(frozen=True, slots=True)
class NaturePresentation:
    nature_id: int
    name: str
    increased: str | None
    decreased: str | None


def nature_presentation(nature_id: int | None) -> NaturePresentation | None:
    if nature_id is None:
        return None
    value = int(nature_id)
    if not 0 <= value < len(SPANISH_NATURES):
        return None
    up_index, down_index = divmod(value, 5)
    neutral = up_index == down_index
    return NaturePresentation(
        nature_id=value,
        name=SPANISH_NATURES[value],
        increased=None if neutral else _NATURE_STAT_ORDER[up_index],
        decreased=None if neutral else _NATURE_STAT_ORDER[down_index],
    )


def stat_dict(values: tuple[int, ...] | list[int] | None) -> dict[str, int]:
    if values is None or len(values) != len(STAT_KEYS):
        return {}
    return {key: int(value) for key, value in zip(STAT_KEYS, values)}
