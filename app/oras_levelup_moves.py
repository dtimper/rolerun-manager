"""Aprendizajes por nivel de ORAS ajustados al rol, vía mod de Azahar.

RoleRun no modifica la ROM ni la RAM invitada para esta capacidad: escribe
(y mantiene) un archivo de mod LayeredFS que Azahar ya soporta de forma
nativa, en ``load/mods/<título>/romfs/a/1/9/1``. Validado físicamente el
2026-09-03 contra una partida real en Azahar/AzaharPlus (Alfa Zafiro): tanto
el registro inicial del mod como una reescritura de su contenido en caliente,
sin reiniciar el título, se reflejan en el próximo movimiento que el juego
ofrece al subir de nivel.

Piezas:

* :func:`compute_species_patch` decide, para una especie y un rol, qué
  entradas (nivel, movimiento) de su tabla de aprendizajes vainilla hay que
  sustituir y por qué movimiento, reutilizando exactamente las mismas reglas
  de rol que ya limitan las MT y el drafteo (``role_rules.py``).
* :func:`build_party_patched_blob` aplica esas sustituciones sobre una copia
  del bloque GARC vainilla, sin cambiar su tamaño ni tocar ninguna otra
  especie.
* :func:`ensure_registered`, :func:`write_blob` y :func:`mod_learnset_path`
  gestionan el archivo de mod en disco.

Restricción real de LayeredFS (confirmada leyendo el código fuente de
Azahar, ``layered_fs.cpp``): el **tamaño** del archivo de mod se fija una
sola vez al arrancar el título; el **contenido** se relee del disco en cada
petición del juego, sin caché. Por eso el archivo debe existir (aunque sea
con el contenido vainilla) antes de que el título arranque, y por eso
``write_blob`` exige que el tamaño nunca cambie.
"""

from __future__ import annotations

import struct
from collections.abc import Mapping
from pathlib import Path

from . import oras_rom_service as _rom
from .role_levelup_moves import compute_species_patch

LEVELUP_MOVES_PATH = "a/1/9/1"

__all__ = [
    "LEVELUP_MOVES_PATH",
    "parse_levelup_garc",
    "compute_species_patch",
    "build_party_patched_blob",
    "mod_learnset_path",
    "ensure_registered",
    "write_blob",
]


def parse_levelup_garc(blob: bytes) -> dict[int, tuple[tuple[int, int, int], ...]]:
    """Decodifica el GARC de aprendizajes: ``especie -> ((movimiento, nivel, offset), ...)``.

    ``offset`` es el desplazamiento absoluto (en ``blob``) de los dos bytes
    del ID de movimiento de esa entrada; es lo que necesita
    :func:`build_party_patched_blob` para sustituir solo esos dos bytes sin
    tocar nada más del contenedor.
    """
    entries = _rom._read_garc_entries(blob)
    result: dict[int, tuple[tuple[int, int, int], ...]] = {}
    for species_id, (start, length, _sub) in enumerate(entries):
        pairs: list[tuple[int, int, int]] = []
        for offset in range(start, start + length - 3, 4):
            move_id, level = struct.unpack_from("<hh", blob, offset)
            if move_id == -1 and level == -1:
                break
            pairs.append((move_id, level, offset))
        result[species_id] = tuple(pairs)
    return result


def build_party_patched_blob(
    vanilla_blob: bytes,
    roles_by_species: Mapping[int, str],
    *,
    pools: Mapping[str, list[int]],
    damage_classes: Mapping[int, str],
    speed_status_moves: set[int],
    self_healing_damage_moves: set[int],
    usable_move_ids: set[int] | None = None,
    entries_by_species: Mapping[int, tuple[tuple[int, int, int], ...]] | None = None,
) -> bytes:
    """Copia ``vanilla_blob`` y sustituye solo las especies de ``roles_by_species``.

    Cualquier especie ausente de ``roles_by_species`` queda exactamente como
    en la ROM/masterdata activa, randomizada o no.

    ``entries_by_species`` evita volver a decodificar las 826 especies del
    GARC en cada llamada — este cálculo se repite en cada sondeo en vivo
    (hasta cada 250ms), así que RoleRun lo decodifica una sola vez y lo
    reutiliza en vez de volver a analizar el bloque entero cada vez.
    """
    if entries_by_species is None:
        entries_by_species = parse_levelup_garc(vanilla_blob)
    patched = bytearray(vanilla_blob)
    for species_id, role in roles_by_species.items():
        entries = entries_by_species.get(int(species_id))
        if not entries:
            continue
        patch = compute_species_patch(
            entries, role, species_id=int(species_id),
            pools=pools, damage_classes=damage_classes,
            speed_status_moves=speed_status_moves,
            self_healing_damage_moves=self_healing_damage_moves,
            usable_move_ids=usable_move_ids,
        )
        for offset, new_move_id in patch.items():
            struct.pack_into("<h", patched, offset, int(new_move_id))
    return bytes(patched)


def mod_learnset_path(azahar_root: Path, title_id: int, romfs_path: str = LEVELUP_MOVES_PATH) -> Path:
    """``romfs_path`` es genérico ("a/1/9/1" para ORAS, "a/0/1/3" para USUM,
    etc.) — el valor por defecto mantiene el comportamiento exacto de ORAS
    para no romper la única llamada histórica sin parámetro; toda llamada
    nueva (incluida la propia de ORAS, y cualquier otro juego que reutilice
    estas funciones) debe pasarlo explícitamente."""
    return Path(azahar_root) / "load" / "mods" / f"{int(title_id):016X}" / "romfs" / Path(*romfs_path.split("/"))


def _atomic_write(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".rolerun-tmp")
    tmp.write_bytes(data)
    tmp.replace(target)


def ensure_registered(
    azahar_root: Path, title_id: int, vanilla_blob: bytes, *, romfs_path: str = LEVELUP_MOVES_PATH,
) -> str:
    """Garantiza que el archivo de mod existe con el tamaño vainilla correcto.

    Devuelve ``"created"``, ``"kept"`` (ya existía con el tamaño correcto) o
    ``"size_mismatch"`` (existía con otro tamaño: no se toca, porque
    LayeredFS ya fijó ese tamaño la última vez que el título arrancó y
    sobrescribirlo ahora no cambiaría lo que Azahar sirve hasta el próximo
    reinicio).
    """
    target = mod_learnset_path(azahar_root, title_id, romfs_path)
    if target.is_file():
        if target.stat().st_size != len(vanilla_blob):
            return "size_mismatch"
        return "kept"
    _atomic_write(target, vanilla_blob)
    return "created"


def write_blob(
    azahar_root: Path, title_id: int, blob: bytes, *,
    expected_size: int, romfs_path: str = LEVELUP_MOVES_PATH,
) -> None:
    """Reescribe el contenido del mod ya registrado. Nunca cambia su tamaño."""
    if len(blob) != expected_size:
        raise ValueError(
            "El bloque de aprendizajes no tiene el tamaño que Azahar ya registró para este mod."
        )
    _atomic_write(mod_learnset_path(azahar_root, title_id, romfs_path), blob)
