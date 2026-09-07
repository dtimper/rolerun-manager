"""Aprendizajes por nivel de SM ajustados al rol, vía mod de Azahar.

Mismo mecanismo que ya tienen ORAS y USUM (``app/oras_levelup_moves.py``,
``app/usum_levelup_moves.py``): un archivo de mod LayeredFS que Azahar relee
sin caché de contenido en cada petición del juego. SM corre en el mismo
emulador y comparte la MISMA generación de motor que USUM, así que toda la
mecánica de fichero (``mod_learnset_path``, ``ensure_registered``,
``write_blob``) y el parcheo puro (``compute_species_patch``,
``build_party_patched_blob``, ``parse_levelup_garc``) se reutilizan tal
cual — solo cambia la ruta RomFS, y esa es la MISMA que USUM (``a/0/1/3``,
confirmada el 2026-09-04 leyendo la ROM real del usuario).

**Igual que USUM**: el GARC de aprendizajes de SM tiene 961 ficheros para
807 especies (``SM_SPECIES_COUNT``) — las de más son formas alternativas,
indexadas por ``personal_id``, el MISMO identificador que ya usa la tabla
Personal (``a/0/1/7``). ``parse_levelup_garc`` asume ``índice de fichero ==
species_id`` — para SM ese índice de fichero es un ``personal_id``, y
``sm_rom_service.sm_personal_id_map`` traduce ``(species_id, form)`` a ese
identificador antes de indexar el GARC. Confirmado con Venusaur/Mega
Venusaur (``personal_id`` 3 y 843): ambas entradas decodifican listas de
aprendizajes completas, con los mismos niveles.
"""

from __future__ import annotations

from pathlib import Path

from .oras_levelup_moves import (
    build_party_patched_blob,
    compute_species_patch,
    ensure_registered as _generic_ensure_registered,
    mod_learnset_path as _generic_mod_learnset_path,
    parse_levelup_garc,
    write_blob as _generic_write_blob,
)

LEVELUP_MOVES_PATH = "a/0/1/3"

__all__ = [
    "LEVELUP_MOVES_PATH",
    "parse_levelup_garc",
    "compute_species_patch",
    "build_party_patched_blob",
    "mod_learnset_path",
    "ensure_registered",
    "write_blob",
]


def mod_learnset_path(azahar_root: Path, title_id: int) -> Path:
    return _generic_mod_learnset_path(azahar_root, title_id, LEVELUP_MOVES_PATH)


def ensure_registered(azahar_root: Path, title_id: int, vanilla_blob: bytes) -> str:
    return _generic_ensure_registered(azahar_root, title_id, vanilla_blob, romfs_path=LEVELUP_MOVES_PATH)


def write_blob(azahar_root: Path, title_id: int, blob: bytes, *, expected_size: int) -> None:
    _generic_write_blob(
        azahar_root, title_id, blob, expected_size=expected_size, romfs_path=LEVELUP_MOVES_PATH,
    )
