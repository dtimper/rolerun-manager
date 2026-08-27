from __future__ import annotations

"""Perfil de MT de Pokémon Negro 2 y Blanco 2.

DE DÓNDE SALE QUÉ ENSEÑA CADA MT

Del juego en marcha, no de una tabla guardada. RoleRun está pensado para jugarse
en **randomizers**, y un randomizer cambia qué movimiento enseña cada MT: una
tabla extraída de PKHeX una sola vez describe la quinta generación original y
mentiría en cuanto la partida estuviera randomizada.

La lista vive en `b2w2_live.TM_TABLE_BASE`, demostrada el 27-08-2026: en los
4 MiB de RAM hay un único tramo con esa forma y, indexado por objeto, coincide
101 de 101 con la lista derivada de PKHeX. Un randomizer cambia el contenido de
esa tabla, no su posición.

LO QUE SÍ ES FIJO

Qué objeto es cada MT. MT01 es el objeto 328 y MT21 el 348 en cualquier B2/W2,
randomizada o no. El juego guarda la lista **en orden de objeto**: MT01–MT92
(328–419), MO01–MO06 (420–425) y MT93–MT95 (618–620).

LO QUE NO ENTRA

Las seis MO. La interfaz rotula cada entrada como `MT<número>`, así que una MO
aparecería con un número que no es el suyo; y en quinta generación un movimiento
aprendido por MO no se puede olvidar dentro del juego. Sus posiciones se leen
igual —van en medio de la tabla— pero no se publican como MT.

Y la compatibilidad por especie, que RoleRun ignora a propósito: quién puede
aprender una MT lo decide el **rol** del Pokémon (ver `_build_tm_candidates` en
`app/ui.py`).
"""

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path

from .b2w2_live import TM_TABLE_COUNT

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_REFERENCE_PATH = _DATA_DIR / "b2w2_tm_table.json"
_MOVE_PP_PATH = _DATA_DIR / "b2w2_move_pp.json"

# Los objetos, en el orden en que el juego los guarda. Tres tramos contiguos.
TM_TABLE_ITEM_IDS: tuple[int, ...] = (
    *range(328, 420),     # MT01 - MT92
    *range(420, 426),     # MO01 - MO06
    *range(618, 621),     # MT93 - MT95
)
# Qué es cada posición: ("TM", 1) … ("HM", 1) … ("TM", 93) …
TM_TABLE_SLOTS: tuple[tuple[str, int], ...] = (
    *(("TM", n) for n in range(1, 93)),
    *(("HM", n) for n in range(1, 7)),
    *(("TM", n) for n in range(93, 96)),
)
assert len(TM_TABLE_ITEM_IDS) == len(TM_TABLE_SLOTS) == TM_TABLE_COUNT


class B2W2TMError(RuntimeError):
    """El perfil de MT de B2/W2 no se puede construir con datos demostrados."""


@dataclass(frozen=True, slots=True)
class B2W2TM:
    number: int        # número real de MT: 1-95
    item_id: int
    move_id: int
    label: str         # MT21


@dataclass(frozen=True, slots=True)
class B2W2TMSource:
    """Procedencia del perfil, con la misma forma que los perfiles con archivo.

    Los demás backends leen la tabla de un archivo y la interfaz muestra
    ``profile.source.name``. Aquí no hay archivo —la tabla vive en la RAM del
    juego— pero se expone igual para que la pantalla no tenga que distinguir.
    """

    name: str

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True, slots=True)
class B2W2TMProfile:
    source: B2W2TMSource
    tms: dict[int, B2W2TM]
    move_base_pp: dict[int, int]
    # Datos de movimiento leídos de la ROM del juego. Cuando están, mandan:
    # un randomizer puede cambiar categoría, potencia, precisión y PP, y solo
    # la ROM dice cuáles son en esta partida.
    rom: object | None = None

    def tm(self, number: int) -> B2W2TM | None:
        return self.tms.get(int(number))

    def tm_for_item(self, item_id: int) -> B2W2TM | None:
        item_id = int(item_id)
        return next((tm for tm in self.tms.values() if tm.item_id == item_id), None)

    def base_pp(self, move_id: int) -> int:
        """PP base del movimiento en **esta** partida."""
        if self.rom is not None:
            desde_rom = int(self.rom.base_pp(move_id))
            if desde_rom > 0:
                return desde_rom
        return int(self.move_base_pp.get(int(move_id), 0))

    def damage_class(self, move_id: int) -> str:
        """Categoría real del movimiento; «unknown» si no se ha demostrado.

        Sin la ROM no se responde: el catálogo estático describe la quinta
        generación original y en una partida randomizada podría mentir. La
        interfaz ya sabe caer a su propio catálogo cuando recibe «unknown».
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
        raise B2W2TMError("Falta data/b2w2_move_pp.json.") from exc
    return {int(clave): int(valor) for clave, valor in documento.get("pp", {}).items()}


@lru_cache(maxsize=1)
def reference_move_ids() -> tuple[int, ...]:
    """La lista derivada de PKHeX, reordenada al orden de objeto del juego.

    No es la fuente de verdad de ninguna partida: sirve para **localizar y
    validar** la tabla viva, que es la que manda. Ver
    `tools_b2w2_tm_table_capture.py`.
    """
    try:
        documento = json.loads(_REFERENCE_PATH.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise B2W2TMError("Falta data/b2w2_tm_table.json.") from exc
    por_objeto = {
        int(entrada["item_id"]): int(entrada["move_id"])
        for entrada in documento.get("entradas", ())
    }
    faltan = [item for item in TM_TABLE_ITEM_IDS if item not in por_objeto]
    if faltan:
        raise B2W2TMError(
            f"La referencia de MT no cubre el objeto #{faltan[0]}."
        )
    return tuple(por_objeto[item] for item in TM_TABLE_ITEM_IDS)


def build_tm_profile(move_ids, *, source: str, rom=None) -> B2W2TMProfile:
    """Construye el perfil a partir de la lista que el juego tiene cargada.

    ``move_ids`` son los 101 movimientos en orden de objeto. Se publican solo
    las 95 MT; las 6 MO se leen pero no entran (ver el encabezado del módulo).
    """
    movimientos = tuple(int(valor) for valor in move_ids)
    if len(movimientos) != TM_TABLE_COUNT:
        raise B2W2TMError(
            f"La tabla de MT de B2/W2 tiene {len(movimientos)} entradas y no {TM_TABLE_COUNT}."
        )

    pp = _move_base_pp()
    if rom is not None:
        # Con la ROM delante, los PP de esta partida sustituyen a los de la
        # quinta generación original para todo lo que venga después.
        pp = {
            move_id: int(rom.base_pp(move_id)) or valor
            for move_id, valor in pp.items()
        }
    tms: dict[int, B2W2TM] = {}
    for item_id, (tipo, numero), move_id in zip(
        TM_TABLE_ITEM_IDS, TM_TABLE_SLOTS, movimientos,
    ):
        if tipo != "TM":
            continue
        tms[numero] = B2W2TM(
            number=numero, item_id=item_id, move_id=move_id,
            label=f"MT{numero:02d}",
        )

    # Dos MT que enseñaran lo mismo significarían que la lectura se ha
    # desalineado. Antes de publicar medio perfil, se falla.
    if len({tm.move_id for tm in tms.values()}) != len(tms):
        raise B2W2TMError("Dos MT de B2/W2 enseñan el mismo movimiento.")
    sin_pp = sorted(tm.label for tm in tms.values() if pp.get(tm.move_id, 0) <= 0)
    if sin_pp:
        raise B2W2TMError(
            f"Estas MT enseñan un movimiento sin PP en quinta: {', '.join(sin_pp)}."
        )
    return B2W2TMProfile(
        source=B2W2TMSource(str(source)), tms=tms, move_base_pp=pp, rom=rom,
    )
