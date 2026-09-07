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


def project_stats(
    base_stats: dict[str, int] | None,
    ivs: dict[str, int] | None,
    evs: dict[str, int] | None,
    level: int,
    nature_id: int | None,
) -> dict[str, int]:
    """Estimación de solo lectura de las stats resultantes de ``evs``.

    2026-09-04: pedida por el usuario tras medir en vídeo que un cambio de
    rol tarda ~2s en reflejarse en las stats numéricas, aunque el ROL/icono
    ya cambia al instante -``_projected_party`` en ``app/ui.py`` ya proyecta
    el rol, pero deja las stats tal cual venían del último guardado leído
    hasta que la escritura en vivo confirma-. Misma fórmula entera que ya
    usa cada escritor en vivo (p. ej. ``sm_live.py::_calculate_party_stats``,
    ``oras_live.py``) para verificar bytes, pero aquí opera sobre los
    ``dict[str,int]`` por nombre de ``STAT_KEYS`` que ya trae ``SavePokemon``
    -sin tuplas ni órdenes internos por juego que reordenar-, y nunca se usa
    para escribir nada: es puramente una vista previa mientras la escritura
    real todavía no ha confirmado.

    Devuelve ``{}`` -nada que proyectar, quien llama debe conservar lo que
    ya tenía- si falta cualquier base/IV de las seis o el nivel no es
    válido, en vez de lanzar como sí hacen los escritores.
    """
    if not base_stats or not ivs or not 1 <= int(level or 0) <= 100:
        return {}
    nature = nature_presentation(nature_id)
    level = int(level)
    result: dict[str, int] = {}
    for key in STAT_KEYS:
        base = base_stats.get(key)
        iv = ivs.get(key)
        if base is None or iv is None:
            return {}
        ev = int((evs or {}).get(key, 0) or 0)
        if key == "hp":
            value = 1 if int(base) == 1 else (
                (2 * int(base) + int(iv) + ev // 4) * level // 100 + level + 10
            )
        else:
            value = (2 * int(base) + int(iv) + ev // 4) * level // 100 + 5
            if nature is not None:
                if key == nature.increased:
                    value = value * 110 // 100
                elif key == nature.decreased:
                    value = value * 90 // 100
        result[key] = value
    return result


def project_current_hp(old_current: int, old_max: int, new_max: int) -> int:
    """PS actual proyectado tras un ``new_max`` distinto, sin curar de más.

    Mismo criterio que ya usa cada escritor en vivo al recalcular PS
    (p. ej. ``sm_live.py``): conserva el daño ya sufrido en vez de rellenar
    la barra entera. ``0`` se mantiene en ``0`` (debilitado sigue debilitado).
    """
    old_current = int(old_current or 0)
    if old_current <= 0:
        return 0
    missing = max(0, int(old_max or 0) - old_current)
    return max(1, int(new_max or 0) - missing)
