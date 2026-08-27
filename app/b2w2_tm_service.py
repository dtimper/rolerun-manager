from __future__ import annotations

"""Tabla de MT/MO de Pokémon Negro 2 y Blanco 2.

A diferencia de ORAS, X/Y o Perla Reluciente, aquí **no hace falta la ROM del
usuario**: la quinta generación no admite randomización de MT en el flujo que
RoleRun soporta, así que la correspondencia MT → movimiento es la misma en toda
partida de B2/W2 y se puede extraer una sola vez de PKHeX.

Y no se copió a mano de ninguna lista. `tools_extract_gen5_tm` la **deriva** de
la propia lógica de PKHeX: enciende un solo bit de MT en una ficha personal en
blanco y pregunta qué movimiento queda enseñable. Comprobado contra hechos
independientes: MT21 = Frustración (la MT que el usuario tiene en su partida),
MO01–MO06 = Corte, Vuelo, Surf, Fuerza, Cascada y Buceo —Buceo como MO06 es
propio de B2/W2, no de Negro/Blanco—, y los 101 índices dan 101 movimientos
distintos.

Los identificadores de objeto salen de la misma tabla de PKHeX que ya validó
físicamente la mochila real del usuario (MT21 = objeto 348).
"""

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_TM_TABLE_PATH = _DATA_DIR / "b2w2_tm_table.json"
_MOVE_PP_PATH = _DATA_DIR / "b2w2_move_pp.json"


class B2W2TMError(RuntimeError):
    """La tabla de MT de B2/W2 no está disponible o no es coherente."""


@dataclass(frozen=True, slots=True)
class B2W2TM:
    number: int
    item_id: int
    move_id: int
    kind: str          # "TM" o "HM"
    label: str         # MT21, MO03…


@dataclass(frozen=True, slots=True)
class B2W2TMProfile:
    source: Path
    tms: dict[int, B2W2TM]
    move_base_pp: dict[int, int]

    def tm(self, number: int) -> B2W2TM | None:
        return self.tms.get(int(number))

    def tm_for_item(self, item_id: int) -> B2W2TM | None:
        item_id = int(item_id)
        return next((tm for tm in self.tms.values() if tm.item_id == item_id), None)

    def base_pp(self, move_id: int) -> int:
        """PP base de quinta generación; 0 si el movimiento no existe en Gen 5."""
        return int(self.move_base_pp.get(int(move_id), 0))


def _numero_unico(entrada: dict) -> int:
    """Las MO se numeran detrás de las MT para no chocar con ellas.

    La interfaz indexa el perfil por un solo número, así que MO01 pasa a ser 96
    y no un segundo «1». El rótulo visible se conserva en ``label``.
    """
    numero = int(entrada["numero"])
    return numero + 95 if str(entrada["tipo"]) == "HM" else numero


@lru_cache(maxsize=1)
def load_b2w2_tm_profile() -> B2W2TMProfile:
    try:
        documento = json.loads(_TM_TABLE_PATH.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise B2W2TMError("Falta data/b2w2_tm_table.json.") from exc
    entradas = list(documento.get("entradas", ()))
    if not entradas:
        raise B2W2TMError("La tabla de MT de B2/W2 está vacía.")

    tms: dict[int, B2W2TM] = {}
    for entrada in entradas:
        numero = _numero_unico(entrada)
        if numero in tms:
            raise B2W2TMError(f"La MT/MO número {numero} está repetida en B2/W2.")
        tms[numero] = B2W2TM(
            number=numero,
            item_id=int(entrada["item_id"]),
            move_id=int(entrada["move_id"]),
            kind=str(entrada["tipo"]),
            label=str(entrada["etiqueta"]),
        )
    # Dos MT que enseñaran el mismo movimiento, o que compartieran objeto,
    # significarían que la extracción se ha desalineado. Mejor no publicarla.
    if len({tm.move_id for tm in tms.values()}) != len(tms):
        raise B2W2TMError("Dos MT de B2/W2 enseñan el mismo movimiento.")
    if len({tm.item_id for tm in tms.values()}) != len(tms):
        raise B2W2TMError("Dos MT de B2/W2 comparten identificador de objeto.")

    try:
        pp_documento = json.loads(_MOVE_PP_PATH.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise B2W2TMError("Falta data/b2w2_move_pp.json.") from exc
    pp = {int(clave): int(valor) for clave, valor in pp_documento.get("pp", {}).items()}

    sin_pp = sorted(tm.label for tm in tms.values() if pp.get(tm.move_id, 0) <= 0)
    if sin_pp:
        raise B2W2TMError(
            f"Estas MT enseñan un movimiento sin PP en quinta generación: {', '.join(sin_pp)}."
        )

    return B2W2TMProfile(source=_TM_TABLE_PATH, tms=tms, move_base_pp=pp)
