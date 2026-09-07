"""Aprendizajes por nivel de quinta generación ajustados al rol.

Mismo objetivo que ``oras_levelup_moves``/``xy_levelup_moves``, pero por otra
vía: en NDS no existe nada parecido al LayeredFS de 3DS, así que no hay
archivo de mod que el emulador relea. Lo que sí hay —y está medido— es que
**melonDS mantiene la imagen entera de la ROM en su propia memoria, en una
región de escritura**, así que la tabla se parchea ahí directamente. Es la
misma técnica de «parcheo de tablas en vivo» que ya usa BDSP, aplicada a la
imagen de la ROM en vez de a una tabla del juego.

**Todo lo de aquí está demostrado leyendo y probado escribiendo contra la
partida real del usuario, el 06-09-2026:**

- La tabla vive en ``a/0/1/8``: 709 archivos, exactamente las 709 especies
  que declara la tabla personal de B2/W2. Decodifica en aprendizajes reales
  conocidos (Bulbasaur ``Placaje@1, Gruñido@3, Drenadoras@7, Látigo Cepa@9``;
  Pikachu; los tres iniciales de Teselia) y pasa una prueba estructural
  fuerte: 709 de 709 con niveles crecientes dentro de 1..100, cero anomalías.
- El formato es una lista de pares ``(movimiento u16, nivel u16)`` terminada
  por ``FFFF FFFF``.
- **Quinta NO cachea la tabla.** Prueba física: se cambió en memoria el
  aprendizaje de nivel 5 de Lillipup (``Rastreo`` → ``Hidrobomba``, dejando
  el nivel intacto) y el juego, al subirlo de nivel, **anunció y aprendió
  Hidrobomba**, con su tipo AGUA y sus PP correctos. Es el escenario de ORAS:
  una sola capa basta y el cartel del juego dice el nombre real, sin
  necesitar la red de seguridad reactiva ni el parcheo del anuncio que sí
  hacen falta en X/Y, Sol/Luna y UltraSol/UltraLuna.

La lógica de qué movimiento sustituye a cuál no se reescribe: es
``role_levelup_moves.compute_species_patch``, la misma de todos los juegos.
Aquí la ``clave`` de cada entrada es **el desplazamiento absoluto de sus dos
bytes de movimiento dentro del archivo .nds**, que sumado a la base de la ROM
en memoria da la dirección exacta que hay que escribir.
"""

from __future__ import annotations

import struct
from collections.abc import Mapping
from pathlib import Path

from .nds_rom import NdsRomError, open_nds
from .role_levelup_moves import compute_move_substitute, compute_species_patch

#: Contenedor de aprendizajes por nivel, común a B2/W2 y Blanco/Negro.
LEVELUP_MOVES_PATH = "a/0/1/8"

#: Fin de la lista de pares de una especie.
TERMINATOR = 0xFFFF

#: Cada entrada son dos u16: movimiento y nivel.
ENTRY_SIZE = 4

__all__ = [
    "LEVELUP_MOVES_PATH",
    "TERMINATOR",
    "ENTRY_SIZE",
    "compute_move_substitute",
    "compute_species_patch",
    "parse_levelup_narc",
    "compute_role_patch",
]


def parse_levelup_narc(rom_path: Path | str) -> dict[int, tuple[tuple[int, int, int], ...]]:
    """``especie -> ((movimiento, nivel, desplazamiento_en_la_rom), ...)``.

    El tercer elemento es la posición ABSOLUTA, dentro del archivo .nds, de
    los dos bytes del ID de movimiento de esa entrada. Es la «clave» opaca
    que espera ``compute_species_patch``, y a la vez lo que permite escribir
    solo esos dos bytes sin tocar el nivel ni ninguna otra entrada.

    Se leen los archivos y sus posiciones en la misma pasada para que no
    puedan desincronizarse.
    """
    rom = open_nds(rom_path)
    archivos = rom.narc(LEVELUP_MOVES_PATH)
    trozos = rom.narc_absolute_slices(LEVELUP_MOVES_PATH)
    if len(archivos) != len(trozos):
        raise NdsRomError(
            "El contenedor de aprendizajes de quinta no declara el mismo número "
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
            movimiento, nivel = struct.unpack_from("<HH", crudo, desplazamiento)
            if movimiento == TERMINATOR or nivel == TERMINATOR:
                break
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

    No construye ningún blob: en quinta no se reescribe un archivo entero
    sino los dos bytes de cada entrada que no encaja con su rol. Una especie
    ausente de ``roles_by_species`` no aporta ninguna entrada, así que su
    tabla queda exactamente como esté en la ROM —randomizada o no—.
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
