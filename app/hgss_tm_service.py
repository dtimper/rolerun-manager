from __future__ import annotations

"""Perfil de MT de HeartGold/SoulSilver.

DE DÓNDE SALE QUÉ ENSEÑA CADA MT

Del juego en marcha, no de una tabla guardada. RoleRun se juega en
**randomizers**, y un randomizer cambia qué movimiento enseña cada MT: una lista
extraída una sola vez describe la cuarta generación original y mentiría en cuanto
la partida estuviera randomizada.

La tabla vive en `gen4_memory.tm_table`, localizada el 28-08-2026. Las 92 MT son
idénticas en toda la cuarta generación, así que su lista se sacó del binario de
las ROM de Perla y Platino del usuario —las dos dan exactamente la misma— y se
buscó esa firma en los 4 MiB de RAM del DS: **aparece una sola vez**.

Y se valida sola: la MO05 que hay en esa dirección es **Torbellino**, no
Despejar. Esa es justo la diferencia conocida entre HeartGold y Platino, así que
lo encontrado no es una copia de la referencia sino la tabla propia del juego.

LO QUE SÍ ES FIJO

Qué objeto es cada MT. MT01 es el objeto 328 y MT51 el 378 en cualquier juego de
cuarta, randomizado o no. El juego guarda la lista en orden de objeto: MT01–MT92
(328–419) y MO01–MO08 (420–427).

LA DIFERENCIA GORDA CON QUINTA

**En cuarta generación las MT se gastan al enseñarlas.** Enseñar una MT no es
solo escribir el movimiento: hay que descontar el objeto de la mochila, y las
dos cosas tienen que ir o no ir juntas.

LO QUE NO ENTRA

Las ocho MO. La interfaz rotula cada entrada como `MT<número>`, así que una MO
aparecería con un número que no es el suyo; y un movimiento aprendido por MO no
se puede olvidar dentro del juego. Sus posiciones se leen igual —van al final de
la tabla— pero no se publican como MT.

Y la compatibilidad por especie, que RoleRun ignora a propósito: quién puede
aprender una MT lo decide el **rol** del Pokémon.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .hgss_live import TM_TABLE_COUNT

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_REFERENCE_PATH = _DATA_DIR / "gen4_tm_table.json"
_MOVE_PP_PATH = _DATA_DIR / "gen4_move_pp.json"

# Los objetos, en el orden en que el juego los guarda. Dos tramos contiguos.
TM_TABLE_ITEM_IDS: tuple[int, ...] = (
    *range(328, 420),     # MT01 - MT92
    *range(420, 428),     # MO01 - MO08
)
TM_TABLE_SLOTS: tuple[tuple[str, int], ...] = (
    *(("TM", n) for n in range(1, 93)),
    *(("HM", n) for n in range(1, 9)),
)
assert len(TM_TABLE_ITEM_IDS) == len(TM_TABLE_SLOTS) == TM_TABLE_COUNT


class HgssTMError(RuntimeError):
    """El perfil de MT no se puede construir con datos demostrados."""


@dataclass(frozen=True, slots=True)
class HgssTM:
    number: int        # número real de MT: 1-92
    item_id: int
    move_id: int
    label: str         # MT51


@dataclass(frozen=True, slots=True)
class HgssTMSource:
    """Procedencia del perfil, con la misma forma que los que sí tienen archivo."""

    name: str

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True, slots=True)
class HgssTMProfile:
    source: HgssTMSource
    tms: dict[int, HgssTM]
    move_base_pp: dict[int, int]
    # Datos de movimiento leídos de la ROM del juego. Cuando están, mandan: un
    # randomizer puede cambiar categoría, potencia, precisión y PP.
    rom: object | None = None
    # En cuarta, enseñar una MT la gasta. Quien escriba tiene que descontarla.
    consumes_item: bool = True

    def tm(self, number: int) -> HgssTM | None:
        return self.tms.get(int(number))

    def tm_for_item(self, item_id: int) -> HgssTM | None:
        item_id = int(item_id)
        return next((tm for tm in self.tms.values() if tm.item_id == item_id), None)

    def base_pp(self, move_id: int) -> int:
        if self.rom is not None:
            desde_rom = int(self.rom.base_pp(move_id))
            if desde_rom > 0:
                return desde_rom
        return int(self.move_base_pp.get(int(move_id), 0))

    def damage_class(self, move_id: int) -> str:
        """Categoría real del movimiento; «unknown» si no se ha demostrado.

        Sin la ROM no se responde: en una partida randomizada el catálogo
        estático podría mentir. La interfaz sabe caer a su propio catálogo.
        """
        if self.rom is None:
            return "unknown"
        return str(self.rom.damage_class(move_id))

    def power(self, move_id: int) -> int:
        return int(self.rom.power(move_id)) if self.rom is not None else 0

    def accuracy(self, move_id: int) -> int:
        return int(self.rom.accuracy(move_id)) if self.rom is not None else 0


@lru_cache(maxsize=1)
def _move_base_pp() -> dict[int, int]:
    try:
        documento = json.loads(_MOVE_PP_PATH.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise HgssTMError("Falta data/gen4_move_pp.json.") from exc
    return {int(clave): int(valor) for clave, valor in documento.get("pp", {}).items()}


@lru_cache(maxsize=1)
def reference_move_ids() -> tuple[int, ...]:
    """La lista sacada de las ROM de Perla y Platino, en orden de objeto.

    No es la fuente de verdad de ninguna partida: sirve para **localizar y
    validar** la tabla viva, que es la que manda.
    """
    try:
        documento = json.loads(_REFERENCE_PATH.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise HgssTMError("Falta data/gen4_tm_table.json.") from exc
    movimientos = tuple(int(valor) for valor in documento.get("moves_dppt", ()))
    if len(movimientos) != TM_TABLE_COUNT:
        raise HgssTMError(
            f"La referencia de MT trae {len(movimientos)} entradas y no {TM_TABLE_COUNT}."
        )
    return movimientos


def build_tm_profile(move_ids, *, source: str, rom=None) -> HgssTMProfile:
    """Construye el perfil con la lista que el juego tiene cargada.

    ``move_ids`` son los 100 movimientos en orden de objeto. Se publican solo
    las 92 MT; las 8 MO se leen pero no entran.
    """
    movimientos = tuple(int(valor) for valor in move_ids)
    if len(movimientos) != TM_TABLE_COUNT:
        raise HgssTMError(
            f"La tabla de MT trae {len(movimientos)} entradas y no {TM_TABLE_COUNT}."
        )
    if any(valor <= 0 for valor in movimientos):
        raise HgssTMError("La tabla de MT declara un movimiento vacío.")

    tms: dict[int, HgssTM] = {}
    for indice, (tipo, numero) in enumerate(TM_TABLE_SLOTS):
        if tipo != "TM":
            continue
        tms[numero] = HgssTM(
            number=numero,
            item_id=TM_TABLE_ITEM_IDS[indice],
            move_id=movimientos[indice],
            label=f"MT{numero:02d}",
        )
    return HgssTMProfile(
        source=HgssTMSource(source),
        tms=tms,
        move_base_pp=_move_base_pp(),
        rom=rom,
    )
