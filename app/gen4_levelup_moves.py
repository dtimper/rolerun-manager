"""Aprendizajes por nivel de cuarta generación ajustados al rol.

Mismo objetivo y misma técnica que ``gen5_levelup_moves``: HeartGold corre
sobre melonDS, que mantiene la imagen entera de la ROM en su propia memoria,
en una región de escritura, así que la tabla se parchea ahí directamente. La
lógica de qué movimiento sustituye a cuál no se reescribe: es
``role_levelup_moves.compute_species_patch``, la misma de todos los juegos.

**Localizado el 06-09-2026 contra la ROM real del usuario, con Project
Pokemon como referencia de la ruta** (``/a/0/3/2`` y ``/a/0/3/3`` documentadas
para HGSS): la tabla vive en ``a/0/3/3``, 508 archivos —el mismo recuento que
Platino, con las formas alternativas incluidas—. Decodifica en aprendizajes
reales conocidos: Bulbasaur ``Placaje@1, Gruñido@3, Drenadoras@7, Látigo
Cepa@9, Polvo Veneno@13``, exactamente el aprendizaje vainilla de cuarta
generación.

**El formato NO es el de quinta.** Ahí cada entrada son dos u16 separados
(movimiento, nivel). Aquí cada entrada es UN SOLO u16 con los dos datos
empaquetados en el mismo campo: nivel en los 7 bits altos, movimiento en los
9 bits bajos (``valor = (nivel << 9) | movimiento``). Confirmado decodificando
cinco especies conocidas contra su aprendizaje real. La lista termina con
``0xFFFF``, no con un par de terminadores.

Esto tiene una consecuencia real para escribir: como movimiento y nivel
comparten los mismos dos bytes, no basta con escribir un movimiento nuevo —
hay que volver a empaquetar el nivel que ya tenía esa entrada, o la
escritura también le cambiaría el nivel de aprendizaje. Por eso
``compute_role_patch`` sigue devolviendo ``{desplazamiento: movimiento}`` sin
empaquetar nada -igual que en quinta-, y quien lo empaqueta con el nivel
correcto es la capa de memoria (``gen4_levelup_memory.py``), que ya tiene la
tabla de niveles esperados por posición.

Si cuarta cachea la tabla como quinta o como ORAS todavía no se ha probado:
eso exige una escritura real de RAM, y solo se prueba una vez que el resto
del mecanismo (localizar la imagen, calcular el parche) esté demostrado
leyendo.
"""

from __future__ import annotations

import struct
from collections.abc import Mapping
from pathlib import Path

from .nds_rom import NdsRomError, open_nds
from .role_levelup_moves import compute_move_substitute, compute_species_patch

#: Contenedor de aprendizajes por nivel de HeartGold/SoulSilver.
LEVELUP_MOVES_PATH = "a/0/3/3"

#: Fin de la lista de una especie: un único centinela, no un par.
TERMINATOR = 0xFFFF

#: Cada entrada es UN SOLO u16 con movimiento y nivel empaquetados.
ENTRY_SIZE = 2

#: Cuántos bits bajos son el movimiento. El resto (7 bits altos) es el nivel.
MOVE_BITS = 9
MOVE_MASK = (1 << MOVE_BITS) - 1

__all__ = [
    "LEVELUP_MOVES_PATH",
    "TERMINATOR",
    "ENTRY_SIZE",
    "MOVE_BITS",
    "MOVE_MASK",
    "pack_entry",
    "unpack_entry",
    "compute_move_substitute",
    "compute_species_patch",
    "parse_levelup_narc",
    "compute_role_patch",
]


def unpack_entry(valor: int) -> tuple[int, int]:
    """``(movimiento, nivel)`` a partir del u16 empaquetado."""
    valor = int(valor) & 0xFFFF
    return valor & MOVE_MASK, valor >> MOVE_BITS


def pack_entry(move_id: int, level: int) -> int:
    """El u16 empaquetado a partir de movimiento y nivel."""
    move_id = int(move_id) & MOVE_MASK
    if not 0 <= int(level) <= 0x7F:
        raise ValueError(f"El nivel {level} no cabe en los 7 bits altos de cuarta.")
    return (int(level) << MOVE_BITS) | move_id


def parse_levelup_narc(rom_path: Path | str) -> dict[int, tuple[tuple[int, int, int], ...]]:
    """``especie -> ((movimiento, nivel, desplazamiento_en_la_rom), ...)``.

    El tercer elemento es la posición ABSOLUTA, dentro del archivo .nds, de
    los dos bytes empaquetados de esa entrada -la «clave» opaca que espera
    ``compute_species_patch``, y lo que permite escribir solo esos dos bytes
    sin tocar ninguna otra entrada-.
    """
    rom = open_nds(rom_path)
    archivos = rom.narc(LEVELUP_MOVES_PATH)
    trozos = rom.narc_absolute_slices(LEVELUP_MOVES_PATH)
    if len(archivos) != len(trozos):
        raise NdsRomError(
            "El contenedor de aprendizajes de cuarta no declara el mismo número "
            "de archivos que de posiciones."
        )
    resultado: dict[int, tuple[tuple[int, int, int], ...]] = {}
    for especie, (crudo, (inicio, tamano)) in enumerate(zip(archivos, trozos)):
        if len(crudo) != tamano:
            raise NdsRomError(
                f"El aprendizaje de la especie {especie} declara {tamano} bytes "
                f"pero mide {len(crudo)}."
            )
        pares: list[tuple[int, int, int]] = []
        for desplazamiento in range(0, len(crudo) - (ENTRY_SIZE - 1), ENTRY_SIZE):
            valor = struct.unpack_from("<H", crudo, desplazamiento)[0]
            if valor == TERMINATOR:
                break
            movimiento, nivel = unpack_entry(valor)
            pares.append((movimiento, nivel, inicio + desplazamiento))
        resultado[especie] = tuple(pares)
    return resultado


def compute_role_patch(
    entries_by_species: Mapping[int, tuple[tuple[int, int, int], ...]],
    roles_by_species: Mapping[int, str],
    *,
    pools: Mapping[str, list[int]],
    damage_classes: Mapping[int, str],
    speed_status_moves: set[int],
    self_healing_damage_moves: set[int],
    usable_move_ids: set[int] | None = None,
) -> dict[int, int]:
    """``{desplazamiento_en_la_rom: nuevo_movimiento}`` para toda la party.

    Devuelve el movimiento SIN empaquetar: quien escribe en memoria conoce el
    nivel de cada desplazamiento (la misma tabla de ``entries_by_species``) y
    es quien vuelve a empaquetar antes de escribir.
    """
    patch: dict[int, int] = {}
    for species_id, role in roles_by_species.items():
        entries = entries_by_species.get(int(species_id))
        if not entries:
            continue
        patch.update(
            compute_species_patch(
                entries, role, species_id=int(species_id),
                pools=pools, damage_classes=damage_classes,
                speed_status_moves=speed_status_moves,
                self_healing_damage_moves=self_healing_damage_moves,
                usable_move_ids=usable_move_ids,
            )
        )
    return patch
