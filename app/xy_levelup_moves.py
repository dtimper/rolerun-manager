"""Aprendizajes por nivel de X/Y ajustados al rol, vía mod de Azahar.

Mismo mecanismo que ya tiene ORAS (``app/oras_levelup_moves.py``, validado
físicamente el 2026-09-03): un archivo de mod LayeredFS que el emulador relee
sin caché de contenido en cada petición del juego. X/Y comparte el mismo
formato PK6/GARC que ORAS, así que toda la mecánica de fichero
(``mod_learnset_path``, ``ensure_registered``, ``write_blob``) y el parcheo
puro (``compute_species_patch``, ``build_party_patched_blob``,
``parse_levelup_garc``) se reutilizan tal cual — solo cambia la ruta RomFS.

**Ruta confirmada leyendo la ROM real del usuario el 2026-09-05**
(``a/2/1/4``, no ``a/1/9/1`` como ORAS: X/Y numera esa carpeta de datos por
especie de otra forma). Decodificada con ``parse_levelup_garc`` da 799
entradas indexadas 1:1 por ``species_id`` -igual que ORAS, sin indirección
por ``personal_id``- y coincide byte a byte con aprendizajes reales
conocidos: especie 1 (Bulbasaur) aprende Látigo Cepa a nivel 9, especie 25
(Pikachu) aprende Nuzzle -movimiento propio de la generación X/Y- a nivel 7.
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

LEVELUP_MOVES_PATH = "a/2/1/4"

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
