"""ORAS: copias en RAM de la tabla de aprendizajes que decide el anuncio.

Evidencia (2026-09-26, partida real del usuario: Alfa Zafiro randomizado,
título 000400000011C500, AzaharPlus 2126.0-A en Windows):

* El diálogo "X quiere aprender Y" de ORAS no sale del archivo del mod
  (``a/1/9/1``, que ``oras_levelup_moves.py`` ya reescribe al cambiar de rol):
  sale de copias de la tabla de la especie que el juego guarda en su memoria.
  Con el archivo en la tabla de Mago, Houndoom seguía anunciando Afilagarras,
  la entrada de la tabla de Asesino que tenía un momento antes.
* Una lectura de SOLO LECTURA de la memoria del proceso encontró DOS copias
  por especie, como una lista plana de pares ``(movimiento, nivel)`` en el
  orden del GARC (el mismo formato que ya se conocía en USUM/X-Y), dentro de
  la región de ~256 MiB del proceso. Están lejos del equipo: la búsqueda de
  USUM/X-Y (una ventana de la RAM huésped centrada en la party) no las ve.
* Abrir la ficha del Pokémon en el juego NO rehace esas copias (en USUM sí).
* Validado físicamente: reescribir los movimientos de las dos copias de
  Houndoom a la tabla de Mago hizo que el juego ofreciera Aligerar (Mago) en
  lugar de Afilagarras (Asesino) al llegar al nivel 16.

Seguridad, más estricta que la de USUM/X-Y porque aquí no hay una lectura por
RPC que confirme la copia: una copia solo se reescribe si su contenido
COMPLETO -movimientos y niveles de todas sus entradas- es exactamente una
tabla conocida de esa especie (la vainilla o la de algún rol). Nunca basta el
ancla de niveles. Se relee justo antes de escribir y se comprueba después.
Solo cambian los movimientos: los niveles se escriben con el mismo valor.
"""

from __future__ import annotations

import re
import struct
from collections.abc import Iterable, Mapping, Sequence

from .usum_levelup_announcement_cache import _level_anchor_pattern

#: Las copias aparecieron siempre en la región de ~256 MiB. Barrer solo las
#: regiones de ese orden evita leer ~500 MiB en cada cambio de rol.
MIN_REGION_SIZE = 200 * 1024 * 1024
_CHUNK = 16 * 1024 * 1024


def table_payload(move_ids: Sequence[int], levels: Sequence[int]) -> bytes:
    """Los bytes de una tabla tal como el juego la guarda: ``(mov, nivel)`` u16 LE."""
    return b"".join(struct.pack("<HH", int(move) & 0xFFFF, int(level) & 0xFFFF)
                    for move, level in zip(move_ids, levels))


def find_copies(
    wpm, handle, levels_by_species: Mapping[int, Sequence[int]],
    *, min_region_size: int = MIN_REGION_SIZE,
) -> dict[int, list[int]]:
    """Direcciones de Windows que empiezan con la secuencia de niveles de cada especie.

    Una sola pasada por la memoria para todas las especies. Es solo el ancla:
    quien escriba debe comprobar el contenido completo (``patch_copies``).
    """
    anchors = {
        int(species): re.compile(_level_anchor_pattern(list(levels)), re.DOTALL)
        for species, levels in levels_by_species.items() if levels
    }
    found: dict[int, list[int]] = {species: [] for species in anchors}
    margin = 4 * max((len(levels) for levels in levels_by_species.values()), default=0)
    for base, size in wpm.iter_writable_regions(handle):
        if size < min_region_size:
            continue
        for start in range(base, base + size, _CHUNK):
            data = wpm.read(handle, start, min(_CHUNK + margin, base + size - start))
            for species, anchor in anchors.items():
                for hit in anchor.finditer(data):
                    if hit.start() < _CHUNK:
                        found[species].append(start + hit.start())
    return found


def patch_copies(
    wpm, handle, addresses: Iterable[int], *, known_payloads: Iterable[bytes], target: bytes,
) -> int:
    """Reescribe con ``target`` cada copia que sea exactamente una tabla conocida.

    Devuelve cuántas quedaron con ``target`` (incluidas las que ya lo tenían).
    Una copia con cualquier otro contenido no se toca.
    """
    known = {bytes(payload) for payload in known_payloads if len(payload) == len(target)}
    done = 0
    for address in addresses:
        current = wpm.read(handle, int(address), len(target))
        if current == target:
            done += 1
            continue
        if current not in known:
            continue
        wpm.write(handle, int(address), target)
        if wpm.read(handle, int(address), len(target)) == target:
            done += 1
        else:
            # No quedó como debía: se devuelve lo que había, nunca a medias.
            wpm.write(handle, int(address), current)
    return done
