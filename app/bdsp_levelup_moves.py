"""Aprendizajes por nivel de BDSP ajustados al rol, por sustitución posterior.

BDSP corre en Ryujinx (Switch), no en un emulador 3DS con LayeredFS: no hay
forma demostrada de que el propio juego relea en caliente una tabla de
aprendizajes parcheada, a diferencia de ORAS (``app/oras_levelup_moves.py``).
Por eso este módulo no parchea nada — solo decodifica la tabla VAINILLA
(``WazaOboeTable``, dentro de ``personal_masterdatas``) para saber, cuando un
Pokémon sube de nivel, qué movimiento le tocaría según el juego. La
sustitución de verdad ocurre en ``app/ui.py``: se deja que el juego enseñe
ese movimiento vainilla y, si no encaja con el rol, se reescribe en caliente
en la propia estructura PB8 con ``BDSPLiveWriter`` — el mismo escritor ya
usado para MT y otros cambios de movimiento, reutilizando su camino
transaccional completo (doble lectura, snapshot, verificación, rollback).

Confirmado el 2026-09-03 contra el ``personal_masterdatas`` real del
usuario: ``WazaOboeTable`` existe, indexada directamente por ``personal_id``
(el mismo identificador de forma que ``PersonalTable``, no siempre igual a
``species_id`` — solo coincide para la forma base de cada especie). Cada
fila es ``[personal_id, [nivel, movimiento, nivel, movimiento, ...]]`` — una
lista PLANA de pares intercalados nivel/movimiento, no un entero empaquetado
ni un array de pares anidados.
"""

from __future__ import annotations

from collections.abc import Mapping

from .role_levelup_moves import compute_species_patch

__all__ = ["parse_wazaoboe_table", "compute_species_patch"]


def _personal_id_to_species_form(personal_root: list) -> dict[int, tuple[int, int]]:
    """``personal_id -> (species_id, form_id)``, mismo criterio que
    ``bdsp_tm_service._load_cached`` usa para ``personal_stats``."""
    rows = personal_root[4] if isinstance(personal_root, list) and len(personal_root) > 4 else []
    result: dict[int, tuple[int, int]] = {}
    for row in rows:
        if not isinstance(row, list) or len(row) < 4:
            continue
        valid_flag = int(row[0])
        if not valid_flag:
            continue
        personal_id = int(row[1])
        species_id = int(row[2])
        form_index = int(row[3])
        form_id = 0 if personal_id == species_id else personal_id - form_index + 1
        result[personal_id] = (species_id, form_id)
    return result


def parse_wazaoboe_table(
    objects: Mapping[str, list],
) -> dict[tuple[int, int], tuple[tuple[int, int, int], ...]]:
    """``(species_id, form_id) -> ((movimiento, nivel, índice), ...)``.

    ``objects`` es el resultado de
    ``bdsp_tm_service.load_personal_masterdatas_objects`` — este módulo no
    lee ningún archivo por su cuenta. ``índice`` es la posición de la
    entrada dentro del aprendizaje de esa forma (0, 1, 2…): la clave opaca
    que espera ``compute_species_patch``, aquí sin significado de offset de
    bytes como en ORAS, solo un identificador estable por entrada.
    """
    waza_root = objects.get("WazaOboeTable")
    personal_root = objects.get("PersonalTable")
    if waza_root is None or personal_root is None:
        missing = [name for name, value in (("WazaOboeTable", waza_root), ("PersonalTable", personal_root)) if value is None]
        raise ValueError("personal_masterdatas no contiene las tablas esperadas: " + ", ".join(missing))
    species_form_by_personal_id = _personal_id_to_species_form(personal_root)

    rows = waza_root[4] if len(waza_root) > 4 else []
    result: dict[tuple[int, int], tuple[tuple[int, int, int], ...]] = {}
    for entry in rows:
        if not isinstance(entry, list) or len(entry) < 2:
            continue
        personal_id = int(entry[0])
        species_form = species_form_by_personal_id.get(personal_id)
        if species_form is None:
            continue
        flat = entry[1] if isinstance(entry[1], list) else []
        pairs: list[tuple[int, int, int]] = []
        for index, position in enumerate(range(0, len(flat) - 1, 2)):
            level = int(flat[position])
            move_id = int(flat[position + 1])
            pairs.append((move_id, level, index))
        if pairs:
            result[species_form] = tuple(pairs)
    return result
