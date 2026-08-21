from __future__ import annotations

import json
import struct
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .role_rules import ROLE_TO_MARKING, MARKING_ROLE_ORDER, ROLE_SYMBOLS, canonical_role
from .azahar_rpc import AzaharProcess, AzaharRPCClient, AzaharRPCError
from .models import (
    PendingChange,
    PendingInventoryChange,
    PendingPCRoleChange,
    PendingRoleChange,
    PendingTeamChange,
    PendingTMTeach,
)
from .oras_tm_service import ORASPersonalStats, oras_tm_item_id
from .boxed_metadata import ability_name, boxed_level, item_name
from .save_engine_client import SaveGameData, SavePokemon
from .realtime_memory import LiveBlockResolver, MemoryCandidateHint


# Direcciones de la revisión 1.4 de Omega Rubí / Zafiro Alfa. Ambos juegos
# comparten el diseño; ``sango-1`` es OR y ``sango-2`` es AS.
#
# Importante: el PK6 del equipo no está almacenado como un bloque contiguo de
# 0x104 bytes en la RAM de ORAS. Los 0xE8 bytes cifrados se encuentran al
# principio de cada slot y las estadísticas de combate están a +0x158. Al
# recomponerlos se obtiene el formato PK6 de equipo que valida PKHeX.
ORAS_PARTY_ADDRESS = 0x08CF727C
ORAS_PARTY_STRIDE = 0x1E4
PK6_PARTY_SIZE = 0x104
PK6_STORED_SIZE = 0xE8
ORAS_PARTY_STATS_OFFSET = 0x158
ORAS_PARTY_STATS_SIZE = 0x16
ORAS_PROCESS_NAMES = {"sango-1", "sango-2"}
ORAS_TITLE_IDS = {0x000400000011C400, 0x000400000011C500}

# Estructuras auxiliares de la revisión 1.4. A diferencia de la party, las
# cajas son una matriz contigua de PK6 almacenados (sin los 28 bytes de combate)
# y las bolsas son registros ``u16 item_id, u16 cantidad``. Nunca se usan estas
# direcciones sin validar primero el PK6 o el registro que se va a tocar.
# Las direcciones de las cajas conocidas públicamente varían entre revisiones
# del juego y también pueden cambiar si la ROM carga un ``code.bin`` modificado.
# Se prueban como atajo, pero el escritor no confía en ellas: antes de editar
# localiza el bloque real con dos identidades PK6 de la misma caja.
ORAS_PC_ADDRESS = 0x08CA2124
ORAS_PC_ADDRESS_V10 = 0x08C9E134
ORAS_PC_KNOWN_ADDRESSES = (ORAS_PC_ADDRESS, ORAS_PC_ADDRESS_V10)
ORAS_PC_BOX_COUNT = 31
ORAS_PC_BOX_SLOT_COUNT = 30
ORAS_PC_SIZE = ORAS_PC_BOX_COUNT * ORAS_PC_BOX_SLOT_COUNT * PK6_STORED_SIZE

# La party validada se encuentra al final de la zona de datos de ORAS. Cuando
# los atajos no coinciden, se explora únicamente el MiB inmediatamente anterior
# (no toda la RAM) y solo se acepta una coincidencia si varios PK6 de la caja
# casan con el guardado de RoleRun.
ORAS_PC_SCAN_START = ORAS_PARTY_ADDRESS - 0x00100000
ORAS_PC_SCAN_END = ORAS_PARTY_ADDRESS - 0x00001000
ORAS_PC_SCAN_BLOCK_SIZE = 0x00010000
# La mochila vive en la misma zona de datos que el PC. Se explora únicamente
# dentro de este MiB y nunca se acepta una coincidencia aislada de un objeto.
ORAS_INVENTORY_SCAN_START = ORAS_PC_SCAN_START
ORAS_INVENTORY_SCAN_END = ORAS_PC_SCAN_END
ORAS_INVENTORY_SCAN_BLOCK_SIZE = ORAS_PC_SCAN_BLOCK_SIZE

ORAS_ITEMS_POUCH_ADDRESS = 0x08C6EC70
ORAS_ITEMS_POUCH_SIZE = 0x640
ORAS_MEDICINE_POUCH_ADDRESS = 0x08C6F5E0
ORAS_MEDICINE_POUCH_SIZE = 0x100
ORAS_TM_POUCH_ADDRESS = 0x08C6F430
ORAS_TM_POUCH_SIZE = 0x1B0
ORAS_MONEY_ADDRESS = 0x08C71DC0
ORAS_BADGES_ADDRESS = ORAS_MONEY_ADDRESS + 0x4

# Layout del bloque ``Misc`` de ORAS dentro de ``main`` (PKHeX: bloque 11).
# A diferencia de la mochila y el PC, no asumimos que este bloque conserve en
# RAM el mismo delta global que otros bloques. Alpha.34 hacía esa suposición y
# podía terminar leyendo una copia secundaria con 0 medallas. Alpha.35 usa el
# propio bloque guardado como huella para localizar ``Misc`` de forma
# independiente y, si todavía no puede calibrarlo, cae al valor de ``main``.
ORAS_SAVE_MISC_OFFSET = 0x04200
ORAS_SAVE_MISC_SIZE = 0x130
ORAS_MISC_MONEY_OFFSET = 0x08
ORAS_MISC_BADGES_OFFSET = 0x0C
ORAS_MISC_BP_OFFSET = 0x30
ORAS_MISC_VIVILLON_OFFSET = 0x44
ORAS_MISC_SCAN_START = ORAS_INVENTORY_SCAN_START
ORAS_MISC_SCAN_END = ORAS_INVENTORY_SCAN_END
ORAS_MISC_SCAN_BLOCK_SIZE = ORAS_INVENTORY_SCAN_BLOCK_SIZE

# EventWork guarda el progreso de historia y los flags persistentes. PKHeX
# define 0x178 ``ushort`` de Event Work seguidos de 0xD00 flags. Alpha.37
# intentaba inferir las medallas a partir de una familia de flags ``TRAINER
# BATTLE``; eran flags distintos de los que ORAS usa para recordar que la
# medalla fue entregada y por eso una copia viva perfectamente localizada podía
# devolver 0. Alpha.38 usa los ocho flags ``Received ... Badge`` de ORAS.
ORAS_SAVE_EVENTWORK_OFFSET = 0x14A00
ORAS_SAVE_EVENTWORK_SIZE = 0x504
ORAS_EVENTWORK_COUNT = 0x178
ORAS_EVENTWORK_FLAG_OFFSET = ORAS_EVENTWORK_COUNT * 2  # 0x2F0
ORAS_EVENTWORK_FLAG_COUNT = 0xD00
ORAS_EVENTWORK_SCAN_START = ORAS_INVENTORY_SCAN_START
ORAS_EVENTWORK_SCAN_END = ORAS_INVENTORY_SCAN_END
ORAS_EVENTWORK_SCAN_BLOCK_SIZE = ORAS_INVENTORY_SCAN_BLOCK_SIZE
# ORAS / EventWork: Received Stone, Knuckle, Dynamo, Heat, Balance, Feather,
# Mind y Rain Badge. Son consecutivos, lo que además permite validar el bloque
# vivo con un patrón de progresión muy fuerte (0x807..0x80E).
ORAS_BADGE_RECEIVED_FLAGS = tuple(range(0x807, 0x80F))
# Alias conservado para no romper imports de utilidades/tests de builds previas.
ORAS_GYM_LEADER_FLAGS = ORAS_BADGE_RECEIVED_FLAGS

# Tercera fuente, independiente de Misc/EventWork: el bloque SUBE (SubEventLog)
# conserva el equipo con el que se ganó cada gimnasio. PKHeX expone esta zona
# como ``IGymTeamInfo``: 8 medallas x 6 species IDs (u16), a partir de +0x60
# dentro del bloque 42 de ORAS. En el ``main`` ese bloque vive en 0x1E800.
#
# Esta señal es especialmente útil para Azahar: no depende de que el byte
# ``Misc.Badges`` esté espejado en la estructura runtime ni de localizar la
# copia viva de EventWork. Si un registro de victoria contiene al menos una
# especie válida, esa medalla necesariamente fue obtenida.
ORAS_SAVE_SUBEVENT_OFFSET = 0x1E800
ORAS_SAVE_SUBEVENT_SIZE = 0x400
ORAS_SUBEVENT_BADGE_VICTORY_OFFSET = 0x60
ORAS_SUBEVENT_BADGE_COUNT = 8
ORAS_SUBEVENT_BADGE_SLOT_COUNT = 6
ORAS_SUBEVENT_BADGE_RECORD_SIZE = ORAS_SUBEVENT_BADGE_SLOT_COUNT * 2
ORAS_SUBEVENT_BADGE_VICTORY_SIZE = ORAS_SUBEVENT_BADGE_COUNT * ORAS_SUBEVENT_BADGE_RECORD_SIZE
ORAS_MAX_SPECIES_ID = 721

# El propio formato SUBE intercala cinco cabeceras u32 "SUBE" en offsets
# conocidos. Cuando el ``main`` contiene esas firmas, sirven como un ancla muy
# fuerte para encontrar el bloque vivo sin depender de datos de historia.
ORAS_SUBEVENT_MAGIC = b"SUBE"
ORAS_SUBEVENT_MAGIC_OFFSETS = (0x5C, 0xC0, 0x1AC, 0x298, 0x2F4)

# Primera pasada: la misma zona de heap donde ya viven mochila/PC. Si una build
# de Azahar coloca SUBE fuera de ese MiB, hacemos dos pasadas auxiliares. Esto
# solo ocurre al calibrar; una vez encontrada la base se cachea y cada tick lee
# únicamente el bloque SUBE de 0x400 bytes. Los fallos de calibración llevan
# backoff para no repetir varios MiB de RPC cada segundo.
ORAS_SUBEVENT_SCAN_RANGES = (
    (ORAS_INVENTORY_SCAN_START, ORAS_INVENTORY_SCAN_END),
    (0x08A00000, ORAS_INVENTORY_SCAN_START),
    (ORAS_INVENTORY_SCAN_END, 0x09000000),
)
ORAS_SUBEVENT_SCAN_BLOCK_SIZE = 0x00010000

# Alpha.40: detector de medallas por los premios físicos de cada líder.
# En ORAS, Roxanne/Brawly/Wattson/Flannery/Norman/Winona/Tate+Liza entregan
# respectivamente TM39/TM08/TM72/TM50/TM67/TM19/TM04, y Wallace entrega
# HM05. Las MT/MO no se consumen en Gen 6, por lo que su presencia forma una
# cadena de hitos irreversible y, sobre todo, vive en la misma mochila que
# RoleRun ya lee/escribe correctamente para el flujo de MT. Un randomizer que
# cambie el MOVIMIENTO contenido en una TM conserva el ID del objeto TMxx.
ORAS_GYM_REWARD_TM_NUMBERS = (39, 8, 72, 50, 67, 19, 4)
# IDs reales de MO en ORAS. IMPORTANTE: no son una serie 420..426.
# PKHeX define 420..424 para MO01..MO05, 425 como adición OR/AS y 737 como
# la otra máquina añadida por OR/AS (Buceo). Alpha.40 asumía erróneamente
# 420..426; al no admitir 737 rechazaba precisamente la mochila viva de una
# partida avanzada que ya tuviera Buceo y podía terminar eligiendo una copia
# antigua de RAM con solo 7 premios de gimnasio.
ORAS_HM01_ITEM_ID = 420
ORAS_HM05_ITEM_ID = 424
ORAS_HM06_ITEM_ID = 425
ORAS_HM07_ITEM_ID = 737
ORAS_HM_ITEM_IDS = frozenset((420, 421, 422, 423, ORAS_HM05_ITEM_ID, ORAS_HM06_ITEM_ID, ORAS_HM07_ITEM_ID))
ORAS_GYM_REWARD_ITEM_IDS = tuple(
    int(oras_tm_item_id(number)) for number in ORAS_GYM_REWARD_TM_NUMBERS
) + (ORAS_HM05_ITEM_ID,)
ORAS_TM_HM_ITEM_IDS = frozenset(
    int(item_id)
    for number in range(1, 101)
    if (item_id := oras_tm_item_id(number)) is not None
) | ORAS_HM_ITEM_IDS

# Si la dirección nominal de la bolsa no coincide con la copia viva de una
# build concreta, alpha.41 puede localizar una copia válida dentro del mismo
# MiB que ya se usa para calibrar mochila/PC. Se cachea tras encontrarla.
ORAS_TM_BADGE_SCAN_START = ORAS_INVENTORY_SCAN_START
ORAS_TM_BADGE_SCAN_END = ORAS_INVENTORY_SCAN_END
ORAS_TM_BADGE_SCAN_BLOCK_SIZE = ORAS_INVENTORY_SCAN_BLOCK_SIZE

# Señales de combate de ORAS 1.4 usadas únicamente en lectura. Son las mismas
# regiones de opponent/PP utilizadas por trackers de Gen 6 basados en Citra.
# IMPORTANTE (alpha.33): estas regiones NO se incluyen ya en la doble captura
# estable del monitor principal. La batalla cambia demasiado rápido y mezclarla
# con la party overworld podía invalidar un tick entero. Se consultan mediante
# una sonda independiente que nunca puede tumbar la sincronización principal.
ORAS_BATTLE_WILD_PLAYER_ADDRESS = 0x08804A94
ORAS_BATTLE_TRAINER_PLAYER_ADDRESS = 0x08803F50
ORAS_BATTLE_WILD_OPPONENT_ADDRESS = 0x08805638
ORAS_BATTLE_TRAINER_OPPONENT_ADDRESS = 0x08804AF4
ORAS_BATTLE_WILD_PP_ADDRESS = 0x0820430C
ORAS_BATTLE_TRAINER_PP_ADDRESS = 0x08205E1C
ORAS_BATTLE_MON_STRIDE = 580
ORAS_BATTLE_DYNAMIC_HP_OFFSET = -266  # u16 max HP, seguido de u16 HP actual
ORAS_BATTLE_DYNAMIC_HP_PAIR_SIZE = 4
# La party de batalla conserva el mismo stride sparse (0x1E4) y la misma
# separación PK6/estadísticas que la party normal de ORAS. Leer hasta las
# estadísticas del sexto slot basta para recuperar PS y nivel sin tocar RAM.
ORAS_BATTLE_PARTY_SPAN = (5 * ORAS_PARTY_STRIDE) + ORAS_PARTY_STATS_OFFSET + ORAS_PARTY_STATS_SIZE
ORAS_ITEM_RECORD_SIZE = 4
ORAS_MAX_BAG_QUANTITY = 999
ORAS_MAX_MONEY = 9_999_999

ORAS_INVENTORY_TARGETS = {
    "rare-candy": (50, "medicine"),
    "max-repel": (77, "items"),
}
_POUCH_LAYOUT = {
    "items": (ORAS_ITEMS_POUCH_ADDRESS, ORAS_ITEMS_POUCH_SIZE),
    "medicine": (ORAS_MEDICINE_POUCH_ADDRESS, ORAS_MEDICINE_POUCH_SIZE),
    "tms": (ORAS_TM_POUCH_ADDRESS, ORAS_TM_POUCH_SIZE),
}


def _pouch_address(label: str, inventory_delta: int = 0) -> int:
    """Devuelve la dirección del bolsillo dentro del layout vivo calibrado."""
    try:
        base_address, _size = _POUCH_LAYOUT[str(label)]
    except KeyError as exc:
        raise ORASLiveError(f"El bolsillo ORAS '{label}' no existe.") from exc
    return int(base_address) + int(inventory_delta)


def parse_oras_badges(raw: bytes) -> int | None:
    """Interpreta el contador de medallas vivo; valores imposibles se ignoran."""
    if len(raw) != 1:
        return None
    value = int(raw[0])
    return value if 0 <= value <= 8 else None


def read_oras_saved_misc(save_path: Path | str) -> bytes | None:
    """Lee el bloque Misc directamente de ``main`` sin pasar por PKHeX.

    ORAS guarda el bloque Misc en 0x4200 y su tamaño es 0x130 bytes. Este
    lector es deliberadamente de solo lectura: sirve como testigo para localizar
    la copia viva y como fallback automático si Azahar todavía no está calibrado.
    """
    try:
        path = Path(save_path)
        with path.open("rb") as handle:
            handle.seek(ORAS_SAVE_MISC_OFFSET)
            raw = handle.read(ORAS_SAVE_MISC_SIZE)
    except (OSError, TypeError, ValueError):
        return None
    return raw if len(raw) == ORAS_SAVE_MISC_SIZE else None


def parse_oras_saved_badges(save_path: Path | str) -> int | None:
    raw = read_oras_saved_misc(save_path)
    if raw is None:
        return None
    return parse_oras_badges(raw[ORAS_MISC_BADGES_OFFSET:ORAS_MISC_BADGES_OFFSET + 1])


def read_oras_saved_eventwork(save_path: Path | str) -> bytes | None:
    """Lee el bloque EventWork de un ``main`` ORAS de forma directa."""
    try:
        path = Path(save_path)
        with path.open("rb") as handle:
            handle.seek(ORAS_SAVE_EVENTWORK_OFFSET)
            raw = handle.read(ORAS_SAVE_EVENTWORK_SIZE)
    except (OSError, TypeError, ValueError):
        return None
    return raw if len(raw) == ORAS_SAVE_EVENTWORK_SIZE else None


def parse_oras_event_flag(eventwork: bytes, flag_number: int) -> bool | None:
    """Devuelve un flag de EventWork usando el layout Gen 6 de PKHeX."""
    if len(eventwork) != ORAS_SAVE_EVENTWORK_SIZE:
        return None
    flag = int(flag_number)
    if not 0 <= flag < ORAS_EVENTWORK_FLAG_COUNT:
        return None
    byte_offset = ORAS_EVENTWORK_FLAG_OFFSET + (flag >> 3)
    return bool(eventwork[byte_offset] & (1 << (flag & 7)))


def count_oras_received_badges(eventwork: bytes) -> int | None:
    """Cuenta las medallas realmente recibidas según EventWork de ORAS."""
    values = [parse_oras_event_flag(eventwork, flag) for flag in ORAS_BADGE_RECEIVED_FLAGS]
    if any(value is None for value in values):
        return None
    return sum(bool(value) for value in values)


def count_oras_gym_leader_flags(eventwork: bytes) -> int | None:
    """Compatibilidad con alpha.37: ahora cuenta flags ``Received Badge``."""
    return count_oras_received_badges(eventwork)


def parse_oras_saved_gym_badges(save_path: Path | str) -> int | None:
    raw = read_oras_saved_eventwork(save_path)
    return count_oras_received_badges(raw) if raw is not None else None


def read_oras_saved_subevent(save_path: Path | str) -> bytes | None:
    """Lee el bloque SUBE/SubEventLog de un ``main`` ORAS de forma directa."""
    try:
        path = Path(save_path)
        with path.open("rb") as handle:
            handle.seek(ORAS_SAVE_SUBEVENT_OFFSET)
            raw = handle.read(ORAS_SAVE_SUBEVENT_SIZE)
    except (OSError, TypeError, ValueError):
        return None
    return raw if len(raw) == ORAS_SAVE_SUBEVENT_SIZE else None


def parse_oras_badge_victory_records(subevent: bytes) -> tuple[tuple[int, ...], ...] | None:
    """Devuelve las 8 plantillas de equipo registradas al ganar gimnasios.

    Cada registro contiene seis ``u16`` de especie. Un hueco de equipo se guarda
    como 0; cualquier valor fuera de la Pokédex de Gen 6 invalida la estructura.
    """
    if len(subevent) != ORAS_SAVE_SUBEVENT_SIZE:
        return None
    start = ORAS_SUBEVENT_BADGE_VICTORY_OFFSET
    end = start + ORAS_SUBEVENT_BADGE_VICTORY_SIZE
    payload = subevent[start:end]
    if len(payload) != ORAS_SUBEVENT_BADGE_VICTORY_SIZE:
        return None
    values = struct.unpack(f"<{ORAS_SUBEVENT_BADGE_COUNT * ORAS_SUBEVENT_BADGE_SLOT_COUNT}H", payload)
    result: list[tuple[int, ...]] = []
    for badge in range(ORAS_SUBEVENT_BADGE_COUNT):
        offset = badge * ORAS_SUBEVENT_BADGE_SLOT_COUNT
        record = tuple(int(value) for value in values[offset:offset + ORAS_SUBEVENT_BADGE_SLOT_COUNT])
        if any(value < 0 or value > ORAS_MAX_SPECIES_ID for value in record):
            return None
        result.append(record)
    return tuple(result)


def count_oras_badge_victories(subevent: bytes, *, require_prefix: bool = True) -> int | None:
    """Cuenta gimnasios ganados mediante los equipos históricos de SUBE.

    Una medalla ganada tiene al menos una especie no cero. En la aventura normal
    las ocho medallas son secuenciales; exigir prefijo evita confundir otra tabla
    de ``u16`` con el historial de gimnasios durante un escaneo de RAM.
    """
    records = parse_oras_badge_victory_records(subevent)
    if records is None:
        return None
    present = [any(value != 0 for value in record) for record in records]
    if require_prefix:
        seen_empty = False
        for value in present:
            if not value:
                seen_empty = True
            elif seen_empty:
                return None
    return sum(present)


def parse_oras_saved_badge_victories(save_path: Path | str) -> int | None:
    raw = read_oras_saved_subevent(save_path)
    return count_oras_badge_victories(raw) if raw is not None else None


_BLOCK_SIZE = 56
_BLOCK_POSITIONS = (
    (0, 1, 2, 3), (0, 1, 3, 2), (0, 2, 1, 3), (0, 3, 1, 2),
    (0, 2, 3, 1), (0, 3, 2, 1), (1, 0, 2, 3), (1, 0, 3, 2),
    (2, 0, 1, 3), (3, 0, 1, 2), (2, 0, 3, 1), (3, 0, 2, 1),
    (1, 2, 0, 3), (1, 3, 0, 2), (2, 1, 0, 3), (3, 1, 0, 2),
    (2, 3, 0, 1), (3, 2, 0, 1), (1, 2, 3, 0), (1, 3, 2, 0),
    (2, 1, 3, 0), (3, 1, 2, 0), (2, 3, 1, 0), (3, 2, 1, 0),
    (0, 1, 2, 3), (0, 1, 3, 2), (0, 2, 1, 3), (0, 3, 1, 2),
    (0, 2, 3, 1), (0, 3, 2, 1), (1, 0, 2, 3), (1, 0, 3, 2),
)

# Inversa de ``_BLOCK_POSITIONS``. PK6 cifra los cuatro bloques en el orden
# indicado por la constante de cifrado; para volver a cifrar un bloque plano hay
# que aplicar la permutación inversa antes del XOR de cada palabra.
_BLOCK_POSITION_INVERT = (
    0, 1, 2, 4, 3, 5, 6, 7, 12, 18, 13, 19,
    8, 10, 14, 20, 16, 22, 9, 11, 15, 21, 17, 23,
    0, 1, 2, 4, 3, 5, 6, 7,
)

_ROLE_TO_MARKING = dict(ROLE_TO_MARKING)
_MOVE_OFFSETS = (0x5A, 0x5C, 0x5E, 0x60)
_MOVE_PP_OFFSETS = (0x62, 0x63, 0x64, 0x65)
_MOVE_PP_UPS_OFFSETS = (0x66, 0x67, 0x68, 0x69)


class ORASLiveError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ORASLiveMemoryBlock:
    """Bloque adicional de RAM leído dentro de una misma captura estable."""

    address: int
    data: bytes


@dataclass(frozen=True, slots=True)
class ORASLiveMemoryWatch:
    """Escritura auxiliar que debe seguir viva hasta un Reset o state-load."""

    address: int
    expected: bytes
    kind: str
    pokemon_identity: str = ""
    box: int | None = None
    box_slot: int | None = None


@dataclass(frozen=True, slots=True)
class ORASLiveSnapshot:
    game: SaveGameData
    process: AzaharProcess
    attempts: int
    memory_blocks: tuple[ORASLiveMemoryBlock, ...] = ()


@dataclass(frozen=True, slots=True)
class ORASBattleProbe:
    """Muestra independiente del motor de batalla; nunca bloquea el monitor normal."""

    state: str  # ``wild``, ``trainer`` o ``none``
    health_game: SaveGameData | None = None
    hp_pairs: tuple[tuple[int, int], ...] = ()  # (current_hp, max_hp) por slot leído


@dataclass(frozen=True, slots=True)
class ORASLiveWriteResult:
    """Resultado de una aplicación confirmada dentro de la RAM de ORAS."""

    game: SaveGameData
    process: AzaharProcess
    attempts: int
    applied_count: int
    memory_watches: tuple[ORASLiveMemoryWatch, ...] = ()
    # La petición puede llegar cuando la RAM ya contiene exactamente el
    # resultado deseado (por ejemplo, tras un doble clic o una repetición de
    # la cola). Sigue siendo una sincronización correcta, pero no se escribió
    # ningún byte.
    already_applied: bool = False



def parse_oras_battle_state(blocks: Sequence[ORASLiveMemoryBlock]) -> str:
    """Devuelve ``wild``, ``trainer`` o ``none`` desde una captura estable.

    Se exige a la vez un PK6 rival estructuralmente válido y el byte auxiliar de
    PP dentro del rango usado por ORAS. Una lectura parcial/extraña se trata como
    ``none``; esta función nunca decide escrituras ni altera la partida.
    """
    values = {int(block.address): bytes(block.data) for block in blocks}

    def opponent_valid(address: int) -> bool:
        raw = values.get(int(address))
        if raw is None or len(raw) != PK6_STORED_SIZE:
            return False
        try:
            pokemon = parse_pk6_boxed(raw, 1, 1, {})
        except Exception:
            return False
        return bool(pokemon is not None and 1 <= int(pokemon.species_id) <= 807)

    wild_pp = values.get(ORAS_BATTLE_WILD_PP_ADDRESS, b"")
    if (
        opponent_valid(ORAS_BATTLE_WILD_OPPONENT_ADDRESS)
        and len(wild_pp) == 1 and int(wild_pp[0]) < 65
    ):
        return "wild"

    trainer_pp = values.get(ORAS_BATTLE_TRAINER_PP_ADDRESS, b"")
    if (
        opponent_valid(ORAS_BATTLE_TRAINER_OPPONENT_ADDRESS)
        and len(trainer_pp) == 1 and int(trainer_pp[0]) < 65
    ):
        return "trainer"
    return "none"

def _crypt_array(data: bytearray, start: int, end: int, seed: int) -> None:
    for offset in range(start, end, 2):
        seed = (0x41C64E6D * seed + 0x6073) & 0xFFFFFFFF
        value = struct.unpack_from("<H", data, offset)[0] ^ (seed >> 16)
        struct.pack_into("<H", data, offset, value)


def _shuffle67(data: bytearray, shuffle_value: int) -> None:
    desired_layout = _BLOCK_POSITIONS[shuffle_value & 31]
    blocks = [bytes(data[8 + i * _BLOCK_SIZE:8 + (i + 1) * _BLOCK_SIZE]) for i in range(4)]
    current_layout = [0, 1, 2, 3]
    for index in range(3):
        desired = desired_layout[index]
        other = current_layout.index(desired)
        if other == index:
            continue
        blocks[index], blocks[other] = blocks[other], blocks[index]
        current_layout[index], current_layout[other] = current_layout[other], current_layout[index]
    data[8:PK6_STORED_SIZE] = b"".join(blocks)


def decrypt_pk6(raw: bytes) -> bytes:
    if len(raw) != PK6_PARTY_SIZE:
        raise ORASLiveError(f"Un slot PK6 debe medir {PK6_PARTY_SIZE} bytes.")
    data = bytearray(raw)
    encryption_constant = struct.unpack_from("<I", data)[0]
    _crypt_array(data, 8, PK6_STORED_SIZE, encryption_constant)
    # Los 28 bytes de estadísticas del equipo usan la misma semilla reiniciada.
    _crypt_array(data, PK6_STORED_SIZE, PK6_PARTY_SIZE, encryption_constant)
    _shuffle67(data, (encryption_constant >> 13) & 31)
    return bytes(data)


def encrypt_pk6(data: bytes) -> bytes:
    """Cifra de nuevo un PK6 plano conservando su constante de cifrado.

    Esta función solo prepara el bloque PK6. Quien la use debe haber actualizado
    antes el checksum. En ORAS el bloque de estadísticas de combate vive en otra
    zona de RAM; RoleRun solo escribe los ``0xE8`` bytes almacenados, donde se
    encuentran movimientos, marcas y checksum.
    """
    if len(data) != PK6_PARTY_SIZE:
        raise ORASLiveError(f"Un slot PK6 debe medir {PK6_PARTY_SIZE} bytes.")
    result = bytearray(data)
    encryption_constant = struct.unpack_from("<I", result)[0]
    _shuffle67(result, _BLOCK_POSITION_INVERT[(encryption_constant >> 13) & 31])
    _crypt_array(result, 8, PK6_STORED_SIZE, encryption_constant)
    _crypt_array(result, PK6_STORED_SIZE, PK6_PARTY_SIZE, encryption_constant)
    return bytes(result)


def decrypt_pk6_stored(raw: bytes) -> bytes:
    """Descifra la parte almacenada de un PK6 de caja (exactamente 0xE8)."""
    if len(raw) != PK6_STORED_SIZE:
        raise ORASLiveError(f"Un PK6 almacenado debe medir {PK6_STORED_SIZE} bytes.")
    data = bytearray(raw)
    encryption_constant = struct.unpack_from("<I", data)[0]
    _crypt_array(data, 8, PK6_STORED_SIZE, encryption_constant)
    _shuffle67(data, (encryption_constant >> 13) & 31)
    return bytes(data)


def encrypt_pk6_stored(data: bytes) -> bytes:
    """Cifra un PK6 de caja plano sin inventar estadísticas de combate."""
    if len(data) != PK6_STORED_SIZE:
        raise ORASLiveError(f"Un PK6 almacenado debe medir {PK6_STORED_SIZE} bytes.")
    result = bytearray(data)
    encryption_constant = struct.unpack_from("<I", result)[0]
    _shuffle67(result, _BLOCK_POSITION_INVERT[(encryption_constant >> 13) & 31])
    _crypt_array(result, 8, PK6_STORED_SIZE, encryption_constant)
    return bytes(result)


def _checksum(data: bytes) -> int:
    return sum(struct.unpack_from("<112H", data, 8)) & 0xFFFF


def _valid_party_pk6(data: bytes) -> bool:
    """Comprueba el mínimo estructural que hace seguro editar un PK6 de party."""
    if len(data) != PK6_PARTY_SIZE:
        return False
    expected_checksum = struct.unpack_from("<H", data, 6)[0]
    species = struct.unpack_from("<H", data, 8)[0]
    level = data[0xEC]
    return (
        struct.unpack_from("<H", data, 4)[0] == 0
        and expected_checksum == _checksum(data)
        and 1 <= species <= 721
        and 1 <= level <= 100
    )


def _valid_stored_pk6(data: bytes) -> bool:
    """Valida un PK6 de caja plano; el hueco vacío es un caso válido."""
    if len(data) != PK6_STORED_SIZE:
        return False
    expected_checksum = struct.unpack_from("<H", data, 6)[0]
    species = struct.unpack_from("<H", data, 8)[0]
    return (
        struct.unpack_from("<H", data, 4)[0] == 0
        and expected_checksum == _checksum(data)
        and 0 <= species <= 721
    )


def _plain_pk6(raw: bytes) -> tuple[bytes, bool]:
    """Devuelve un PK6 válido descifrado y si la entrada venía cifrada."""
    if len(raw) != PK6_PARTY_SIZE:
        raise ORASLiveError(f"Un slot PK6 debe medir {PK6_PARTY_SIZE} bytes.")
    if _valid_party_pk6(raw):
        return raw, False
    decrypted = decrypt_pk6(raw)
    if _valid_party_pk6(decrypted):
        return decrypted, True
    raise ORASLiveError("El PK6 no superó la validación de checksum/especie/nivel.")


def _plain_stored_pk6(raw: bytes) -> tuple[bytes, bool]:
    """Devuelve un PK6 almacenado plano y si estaba cifrado en la RAM."""
    if len(raw) != PK6_STORED_SIZE:
        raise ORASLiveError(f"Un PK6 almacenado debe medir {PK6_STORED_SIZE} bytes.")
    if _valid_stored_pk6(raw):
        return raw, False
    decrypted = decrypt_pk6_stored(raw)
    if _valid_stored_pk6(decrypted):
        return decrypted, True
    raise ORASLiveError("El PK6 de caja no superó la validación de checksum/especie.")


def load_oras_move_pp(path: Path) -> dict[int, int]:
    """Carga la tabla de PP base específica de ORAS/Generación 6.

    El dato se mantiene separado del catálogo visual para no depender de un
    motor de guardados ni de una conexión externa mientras se escribe en RAM.
    Si la tabla no está completa, el escritor aborta antes de enviar un byte.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        values = raw.get("pp", {})
        result = {int(move_id): int(pp) for move_id, pp in values.items()}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}
    return {
        move_id: pp for move_id, pp in result.items()
        if 1 <= move_id <= 621 and 1 <= pp <= 255
    }


def _decode_gen6_string(data: bytes) -> str:
    chars: list[str] = []
    for offset in range(0, len(data) - 1, 2):
        value = struct.unpack_from("<H", data, offset)[0]
        if value in {0, 0xFFFF}:
            break
        chars.append(chr(value))
    return "".join(chars).strip()


def _role_from_markings(markings: list[bool]) -> tuple[str, str]:
    selected = [index for index, marked in enumerate(markings) if marked]
    if len(selected) != 1:
        return "SIN ROL", ""
    role = MARKING_ROLE_ORDER[selected[0]]
    return role, ROLE_SYMBOLS[role]


def parse_pk6_party(raw: bytes, slot: int, move_names: dict[int, str]) -> SavePokemon | None:
    if len(raw) != PK6_PARTY_SIZE:
        raise ORASLiveError(f"El slot {slot} tiene un tamaño inesperado.")
    if not any(raw):
        return None

    # En memoria normalmente está cifrado. Admitir también datos ya descifrados
    # facilita el diagnóstico y evita aplicar el cifrado dos veces si Azahar cambia.
    candidates = (raw, decrypt_pk6(raw))
    data: bytes | None = None
    for candidate in candidates:
        expected_checksum = struct.unpack_from("<H", candidate, 6)[0]
        species = struct.unpack_from("<H", candidate, 8)[0]
        level = candidate[0xEC]
        structurally_valid = (
            struct.unpack_from("<H", candidate, 4)[0] == 0
            and expected_checksum == _checksum(candidate)
        )
        if structurally_valid and species == 0:
            # Los huecos libres pueden ser cero puro o un PK6 vacío cifrado con
            # una constante distinta de cero. Ambos son un slot vacío válido.
            return None
        if structurally_valid and 1 <= species <= 721 and 1 <= level <= 100:
            data = candidate
            break
    if data is None:
        raise ORASLiveError(
            f"El Pokémon del slot {slot} no superó checksum/especie/nivel. "
            "La dirección puede no corresponder a esta revisión de ORAS."
        )

    species_id = struct.unpack_from("<H", data, 8)[0]
    held_item_id = struct.unpack_from("<H", data, 0x0A)[0]
    tid = struct.unpack_from("<H", data, 0x0C)[0]
    sid = struct.unpack_from("<H", data, 0x0E)[0]
    ability_id = data[0x14]
    pid = struct.unpack_from("<I", data, 0x18)[0]
    form = data[0x1D] >> 3
    markings = [bool(data[0x2A] & (1 << index)) for index in range(6)]
    role, symbol = _role_from_markings(markings)
    nickname = _decode_gen6_string(data[0x40:0x58])
    species_name = nickname or f"Especie #{species_id}"
    move_ids = [struct.unpack_from("<H", data, offset)[0] for offset in (0x5A, 0x5C, 0x5E, 0x60)]
    moves = ["—" if move_id == 0 else move_names.get(move_id, f"Movimiento #{move_id}") for move_id in move_ids]
    iv32 = struct.unpack_from("<I", data, 0x74)[0]

    return SavePokemon(
        slot=slot,
        species_id=species_id,
        species=species_name,
        nickname=nickname or species_name,
        level=data[0xEC],
        held_item=item_name(held_item_id),
        ability=ability_name(ability_id),
        moves=moves,
        move_ids=move_ids,
        is_egg=bool(iv32 & 0x40000000),
        markings=markings,
        role=role,
        role_symbol=symbol,
        pid=pid,
        tid=tid,
        sid=sid,
        form=form,
        current_hp=struct.unpack_from("<H", data, 0xF0)[0],
        max_hp=struct.unpack_from("<H", data, 0xF2)[0],
    )


def parse_pk6_boxed(
    raw: bytes,
    box: int,
    box_slot: int,
    move_names: dict[int, str],
    *,
    family: str = "oras",
) -> SavePokemon | None:
    """Interpreta un PK6 almacenado y deriva su nivel desde EXP.

    El formato stored no contiene la extensión de party, pero sí conserva EXP.
    Igual que PKHeX ``CurrentLevel``, RoleRun resuelve la curva de crecimiento de
    la especie/forma y calcula el nivel real. ``family='xy'`` selecciona la tabla
    personal de X/Y; ORAS sigue siendo el valor por defecto para compatibilidad.
    """
    if len(raw) != PK6_STORED_SIZE:
        raise ORASLiveError(
            f"El hueco {box}:{box_slot} del PC tiene un tamaño inesperado."
        )
    if not any(raw):
        return None

    candidates = (raw, decrypt_pk6_stored(raw))
    data: bytes | None = None
    for candidate in candidates:
        if not _valid_stored_pk6(candidate):
            continue
        species = struct.unpack_from("<H", candidate, 8)[0]
        if species == 0:
            return None
        data = candidate
        break
    if data is None:
        raise ORASLiveError(
            f"El Pokémon del PC {box}:{box_slot} no superó checksum/especie. "
            "La dirección de cajas puede no corresponder a esta revisión de ORAS."
        )

    species_id = struct.unpack_from("<H", data, 8)[0]
    held_item_id = struct.unpack_from("<H", data, 0x0A)[0]
    tid = struct.unpack_from("<H", data, 0x0C)[0]
    sid = struct.unpack_from("<H", data, 0x0E)[0]
    ability_id = data[0x14]
    pid = struct.unpack_from("<I", data, 0x18)[0]
    form = data[0x1D] >> 3
    experience = struct.unpack_from("<I", data, 0x10)[0]
    level = boxed_level(family, species_id, form, experience)
    markings = [bool(data[0x2A] & (1 << index)) for index in range(6)]
    role, symbol = _role_from_markings(markings)
    nickname = _decode_gen6_string(data[0x40:0x58])
    species_name = nickname or f"Especie #{species_id}"
    move_ids = [struct.unpack_from("<H", data, offset)[0] for offset in _MOVE_OFFSETS]
    moves = [
        "—" if move_id == 0 else move_names.get(move_id, f"Movimiento #{move_id}")
        for move_id in move_ids
    ]
    iv32 = struct.unpack_from("<I", data, 0x74)[0]

    return SavePokemon(
        slot=box_slot,
        species_id=species_id,
        species=species_name,
        nickname=nickname or species_name,
        level=level,
        held_item=item_name(held_item_id),
        ability=ability_name(ability_id),
        moves=moves,
        move_ids=move_ids,
        is_egg=bool(iv32 & 0x40000000),
        markings=markings,
        role=role,
        role_symbol=symbol,
        box=box,
        box_slot=box_slot,
        pid=pid,
        tid=tid,
        sid=sid,
        form=form,
    )


def parse_oras_item_pocket(raw: bytes, *, label: str) -> dict[int, int]:
    """Lee un bolsillo ORAS y rechaza formatos que no parecen registros reales."""
    if len(raw) == 0 or len(raw) % ORAS_ITEM_RECORD_SIZE:
        raise ORASLiveError(f"El bolsillo {label} de ORAS tiene un tamaño inesperado.")
    result: dict[int, int] = {}
    for offset in range(0, len(raw), ORAS_ITEM_RECORD_SIZE):
        item_id, quantity = struct.unpack_from("<HH", raw, offset)
        if item_id == 0:
            if quantity != 0:
                raise ORASLiveError(
                    f"El bolsillo {label} contiene un hueco vacío con cantidad no nula."
                )
            continue
        if not 1 <= item_id <= 1500 or not 1 <= quantity <= ORAS_MAX_BAG_QUANTITY:
            raise ORASLiveError(
                f"El bolsillo {label} no parece contener registros válidos de ORAS."
            )
        if item_id in result:
            raise ORASLiveError(
                f"El bolsillo {label} contiene el objeto #{item_id} dos veces; no se escribió nada."
            )
        result[item_id] = quantity
    return result


def count_oras_gym_reward_items(items: dict[int, int]) -> int | None:
    """Infiere medallas por las MT/MO que solo entregan los líderes de ORAS.

    La progresión válida es un prefijo: TM39, TM08, TM72, TM50, TM67, TM19,
    TM04 y finalmente HM05. Si no está siquiera el primer premio devolvemos
    ``None`` en vez de 0: una región de RAM a cero o una dirección incorrecta
    nunca debe convertirse en un falso "0 medallas". Una cadena con huecos
    también se rechaza, porque suele indicar que hemos encontrado otra copia o
    una partida con randomización de objetos incompatible con este detector.
    """
    present = tuple(int(item_id) in items for item_id in ORAS_GYM_REWARD_ITEM_IDS)
    if not present or not present[0]:
        return None
    first_missing = next((i for i, value in enumerate(present) if not value), len(present))
    if any(present[first_missing:]):
        return None
    return int(first_missing)


def parse_oras_tm_hm_pocket(raw: bytes) -> dict[int, int]:
    """Valida que un bloque sea realmente el bolsillo de MT/MO de ORAS."""
    items = parse_oras_item_pocket(raw, label="MT/MO")
    if any(int(item_id) not in ORAS_TM_HM_ITEM_IDS for item_id in items):
        raise ORASLiveError("La región candidata contiene objetos que no son MT/MO de ORAS.")
    return items


def live_party_fingerprint(game: SaveGameData) -> tuple[tuple[int, int, int, int, int, str, tuple[int, ...]], ...]:
    """Resume los campos que RoleRun puede modificar en la RAM de ORAS.

    No incluye nivel, PS ni otros datos que cambian mientras se juega. Sirve para
    distinguir una partida recargada (o un cambio externo de rol/movimientos) de
    la evolución normal de un combate, sin convertir la reconciliación en un
    refresco continuo de toda la interfaz.
    """
    return tuple(
        (
            int(pokemon.slot),
            int(pokemon.species_id),
            int(pokemon.pid or 0),
            int(pokemon.tid or 0),
            int(pokemon.sid or 0),
            str(pokemon.role or "SIN ROL"),
            tuple(int(move_id or 0) for move_id in pokemon.move_ids),
        )
        for pokemon in sorted(game.party, key=lambda item: int(item.slot))
    )


class ORASLiveReader:
    def __init__(
        self,
        move_catalog_path: Path,
        client_factory: Callable[[], AzaharRPCClient] = AzaharRPCClient,
        stable_delay: float = 0.045,
        snapshot_attempts: int = 4,
    ) -> None:
        self.client_factory = client_factory
        self.stable_delay = max(0.0, float(stable_delay))
        self.snapshot_attempts = max(1, int(snapshot_attempts))
        self.move_names = self._load_move_names(move_catalog_path)
        # Cache de solo lectura para localizar la matriz viva del PC. Se mantiene
        # separada del escritor: leer cajas nunca habilita una escritura.
        self._pc_bases_by_process: dict[tuple[int, str], int] = {}

    @staticmethod
    def _load_move_names(path: Path) -> dict[int, str]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
            return {
                int(item["id"]): str(item.get("name_es") or item.get("name_en") or f"Movimiento #{item['id']}")
                for item in raw.get("moves", [])
            }
        except (OSError, ValueError, TypeError, KeyError):
            return {}

    @staticmethod
    def _find_oras_process(processes: list[AzaharProcess]) -> AzaharProcess:
        """Selecciona ORAS usando primero el Title ID que expone el RPC.

        Azahar publica tanto ``program_id`` como el nombre interno del codeset.
        Históricamente RoleRun dependía exclusivamente de ``sango-1/sango-2``.
        Eso es innecesariamente frágil ante builds/mods que conservan el Title ID
        oficial pero alteran el nombre interno. El Title ID es la identidad
        primaria; el nombre queda como fallback para compatibilidad histórica.
        """
        title_matches = [process for process in processes if int(process.title_id) in ORAS_TITLE_IDS]
        if len(title_matches) == 1:
            return title_matches[0]
        if len(title_matches) > 1:
            details = ", ".join(
                f"{process.name or '?'}[{int(process.title_id):016X}]"
                for process in title_matches
            )
            raise ORASLiveError(
                "Azahar expone más de un proceso con Title ID de ORAS y no se puede elegir "
                f"con seguridad ({details})."
            )

        name_matches = [process for process in processes if process.name.casefold() in ORAS_PROCESS_NAMES]
        if len(name_matches) == 1:
            return name_matches[0]
        if len(name_matches) > 1:
            details = ", ".join(
                f"{process.name or '?'}[{int(process.title_id):016X}]"
                for process in name_matches
            )
            raise ORASLiveError(
                "Azahar expone más de un proceso ORAS por nombre interno y no se puede elegir "
                f"con seguridad ({details})."
            )

        running = ", ".join(
            f"{process.name or '?'}[{int(process.title_id):016X}]"
            for process in processes
        ) or "ninguno"
        raise ORASLiveError(
            "Azahar responde por RPC, pero no aparece Omega Rubí/Zafiro Alfa "
            f"(procesos visibles: {running})."
        )

    @staticmethod
    def _read_party(client: AzaharRPCClient) -> tuple[bytes, ...]:
        slots: list[bytes] = []
        tail_padding = PK6_PARTY_SIZE - PK6_STORED_SIZE - ORAS_PARTY_STATS_SIZE
        for index in range(6):
            slot_address = ORAS_PARTY_ADDRESS + index * ORAS_PARTY_STRIDE
            stored = client.read_memory(slot_address, PK6_STORED_SIZE)
            stats = client.read_memory(
                slot_address + ORAS_PARTY_STATS_OFFSET,
                ORAS_PARTY_STATS_SIZE,
            )
            # Los seis bytes finales no contienen campos que RoleRun necesite;
            # conservar una longitud PK6 estándar permite reutilizar la
            # validación de checksum y el descifrado sin escribir en Azahar.
            slots.append(stored + stats + (b"\0" * tail_padding))
        return tuple(slots)

    @staticmethod
    def _read_party_compact(client: AzaharRPCClient) -> tuple[bytes, ...]:
        """Lee el Equipo con un bloque contiguo para el sondeo permanente.

        El RPC de Azahar fragmenta internamente peticiones mayores de 1 KiB.
        Aun así, leer ~2,8 KiB contiguos reduce mucho las rondas UDP frente a
        solicitar por separado PK6 + estadísticas de cada uno de los seis slots.
        La escritura segura sigue usando las capturas históricas sin cambios.
        """
        span = (5 * ORAS_PARTY_STRIDE) + ORAS_PARTY_STATS_OFFSET + ORAS_PARTY_STATS_SIZE
        region = client.read_memory(ORAS_PARTY_ADDRESS, span)
        if len(region) != span:
            raise ORASLiveError("Azahar devolvió un bloque de Equipo incompleto.")
        tail_padding = PK6_PARTY_SIZE - PK6_STORED_SIZE - ORAS_PARTY_STATS_SIZE
        slots: list[bytes] = []
        for index in range(6):
            base = index * ORAS_PARTY_STRIDE
            stored = region[base:base + PK6_STORED_SIZE]
            stats_start = base + ORAS_PARTY_STATS_OFFSET
            stats = region[stats_start:stats_start + ORAS_PARTY_STATS_SIZE]
            if len(stored) != PK6_STORED_SIZE or len(stats) != ORAS_PARTY_STATS_SIZE:
                raise ORASLiveError("La captura compacta del Equipo quedó truncada.")
            slots.append(stored + stats + (b"\0" * tail_padding))
        return tuple(slots)

    @staticmethod
    def _parse_compact_party_region(
        region: bytes, *, move_names: dict[int, str], label: str = "Equipo",
    ) -> tuple[SavePokemon, ...]:
        """Interpreta una región sparse de seis slots con layout de party ORAS."""
        if len(region) != ORAS_BATTLE_PARTY_SPAN:
            raise ORASLiveError(f"La captura compacta de {label} tiene un tamaño inesperado.")
        tail_padding = PK6_PARTY_SIZE - PK6_STORED_SIZE - ORAS_PARTY_STATS_SIZE
        party: list[SavePokemon] = []
        for index in range(6):
            base = index * ORAS_PARTY_STRIDE
            stored = region[base:base + PK6_STORED_SIZE]
            stats_start = base + ORAS_PARTY_STATS_OFFSET
            stats = region[stats_start:stats_start + ORAS_PARTY_STATS_SIZE]
            if len(stored) != PK6_STORED_SIZE or len(stats) != ORAS_PARTY_STATS_SIZE:
                raise ORASLiveError(f"La captura compacta de {label} quedó truncada.")
            raw = stored + stats + (b"\0" * tail_padding)
            pokemon = parse_pk6_party(raw, index + 1, move_names)
            if pokemon is not None:
                party.append(pokemon)
        return tuple(party)

    def battle_health_game(
        self, snapshot: ORASLiveSnapshot, current: SaveGameData, state: str | None = None,
    ) -> SaveGameData | None:
        """Devuelve la party del jugador dentro de batalla para detectar PS=0.

        Esta vista se usa únicamente como carril de salud. La UI continúa
        publicando la party normal para evitar formas/estados temporales de batalla.
        """
        battle_state = state or parse_oras_battle_state(snapshot.memory_blocks)
        if battle_state == "wild":
            address = ORAS_BATTLE_WILD_PLAYER_ADDRESS
        elif battle_state == "trainer":
            address = ORAS_BATTLE_TRAINER_PLAYER_ADDRESS
        else:
            return None
        region = next((
            bytes(block.data) for block in snapshot.memory_blocks
            if int(block.address) == int(address)
        ), None)
        if region is None:
            return None
        try:
            parsed = self._parse_compact_party_region(
                region, move_names=self.move_names, label="party de batalla",
            )
        except ORASLiveError:
            return None
        if not parsed:
            return None
        party = [self._preserve_known_labels(pokemon, current) for pokemon in parsed]
        return SaveGameData(
            game=current.game, save_type=f"{current.save_type} + batalla Azahar RPC",
            generation=current.generation, trainer=current.trainer, party=party,
            raw={**current.raw, "liveBattleHealth": True, "liveBattleState": battle_state},
        )

    @staticmethod
    def _normalize_memory_requests(
        memory_blocks: Sequence[tuple[int, int]],
    ) -> tuple[tuple[int, int], ...]:
        """Normaliza bloques auxiliares y evita leer/escribir dos veces la RAM."""
        result: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        for address, size in memory_blocks:
            key = (int(address), int(size))
            if key[0] <= 0 or key[1] <= 0:
                raise ORASLiveError("Se solicitó un bloque auxiliar de RAM inválido.")
            if key in seen:
                continue
            seen.add(key)
            result.append(key)
        return tuple(result)

    @staticmethod
    def _read_memory_blocks(
        client: AzaharRPCClient,
        memory_blocks: Sequence[tuple[int, int]],
    ) -> tuple[ORASLiveMemoryBlock, ...]:
        return tuple(
            ORASLiveMemoryBlock(address, client.read_memory(address, size))
            for address, size in memory_blocks
        )

    @staticmethod
    def _preserve_known_labels(pokemon: SavePokemon, current: SaveGameData) -> SavePokemon:
        previous = next((
            item for item in current.party
            if item.species_id == pokemon.species_id
            and item.pid == pokemon.pid
            and item.tid == pokemon.tid
            and item.sid == pokemon.sid
        ), None)
        if previous is None:
            return pokemon
        # PK6 guarda el nombre de especie en el campo nickname incluso cuando no
        # es un mote. PKHeX sí conoce además objeto y habilidad; conservamos esas
        # etiquetas localizadas mientras el Pokémon sea exactamente el mismo.
        pokemon.species = previous.species
        pokemon.nickname = previous.nickname
        pokemon.held_item = previous.held_item
        pokemon.ability = previous.ability
        return pokemon


    @staticmethod
    def _stable_pc_identity(pokemon: SavePokemon | None) -> tuple[int, int, int, int] | None:
        if pokemon is None:
            return None
        return (
            int(pokemon.species_id), int(pokemon.pid or 0),
            int(pokemon.tid or 0), int(pokemon.sid or 0),
        )

    @staticmethod
    def _pc_slot_address(box: int, box_slot: int, *, base_address: int) -> int:
        if not 1 <= int(box) <= ORAS_PC_BOX_COUNT or not 1 <= int(box_slot) <= ORAS_PC_BOX_SLOT_COUNT:
            raise ORASLiveError("Caja/slot de PC fuera de rango.")
        index = (int(box) - 1) * ORAS_PC_BOX_SLOT_COUNT + (int(box_slot) - 1)
        return int(base_address) + index * PK6_STORED_SIZE

    def _pc_anchor_matches(
        self,
        client: AzaharRPCClient,
        base_address: int,
        anchors: Sequence[SavePokemon],
    ) -> bool:
        """Valida una base de cajas usando varias identidades conocidas.

        Los movimientos hechos desde el propio PC pueden cambiar uno o dos de los
        anchors justo antes de esta lectura, por eso no exigimos que coincidan
        todos. Dos identidades completas (especie/PID/TID/SID) son una huella muy
        fuerte y evitan confundir una copia temporal con la matriz real.
        """
        usable = [
            p for p in anchors
            if p.box is not None and p.box_slot is not None and int(p.species_id) > 0
        ][:16]
        if not usable:
            return False
        matched = 0
        required = 1 if len(usable) == 1 else 2
        for pokemon in usable:
            try:
                raw = client.read_memory(
                    self._pc_slot_address(int(pokemon.box), int(pokemon.box_slot), base_address=base_address),
                    PK6_STORED_SIZE,
                )
                live = parse_pk6_boxed(raw, int(pokemon.box), int(pokemon.box_slot), self.move_names)
            except (ORASLiveError, AzaharRPCError, OSError, ValueError):
                continue
            if self._stable_pc_identity(live) == self._stable_pc_identity(pokemon):
                matched += 1
                if matched >= required:
                    return True
        return False

    def _locate_pc_base_for_read(
        self,
        client: AzaharRPCClient,
        process: AzaharProcess,
        anchors: Sequence[SavePokemon],
    ) -> int:
        """Localiza la matriz viva del PC sin escribir ningún byte."""
        process_key = (int(process.title_id), str(process.name))
        candidates: list[int] = []
        cached = self._pc_bases_by_process.get(process_key)
        if cached is not None:
            candidates.append(int(cached))
        candidates.extend(int(address) for address in ORAS_PC_KNOWN_ADDRESSES if int(address) not in candidates)
        for base_address in candidates:
            if self._pc_anchor_matches(client, base_address, anchors):
                self._pc_bases_by_process[process_key] = base_address
                return base_address

        # Fallback dinámico: buscamos uno de los anchors dentro de la misma zona
        # acotada que usa el escritor y derivamos el inicio de la matriz a partir
        # de su caja/slot. El candidato solo se acepta si otro anchor lo confirma.
        usable = [
            p for p in anchors
            if p.box is not None and p.box_slot is not None and int(p.species_id) > 0
        ]
        if len(usable) >= 2:
            target = usable[0]
            target_identity = self._stable_pc_identity(target)
            target_index = (
                (int(target.box) - 1) * ORAS_PC_BOX_SLOT_COUNT
                + (int(target.box_slot) - 1)
            )
            scan_start = (ORAS_PC_SCAN_START + 3) & ~3
            for block_address in range(scan_start, ORAS_PC_SCAN_END, ORAS_PC_SCAN_BLOCK_SIZE):
                candidate_size = min(ORAS_PC_SCAN_BLOCK_SIZE, ORAS_PC_SCAN_END - block_address)
                raw_block = client.read_memory(block_address, candidate_size + PK6_STORED_SIZE)
                for offset in range(0, candidate_size, 4):
                    if not (raw_block[offset] | raw_block[offset + 1] | raw_block[offset + 2] | raw_block[offset + 3]):
                        continue
                    if raw_block[offset + 4] or raw_block[offset + 5]:
                        continue
                    raw = raw_block[offset:offset + PK6_STORED_SIZE]
                    try:
                        live = parse_pk6_boxed(
                            raw, int(target.box), int(target.box_slot), self.move_names,
                        )
                    except ORASLiveError:
                        continue
                    if self._stable_pc_identity(live) != target_identity:
                        continue
                    base_address = block_address + offset - target_index * PK6_STORED_SIZE
                    if self._pc_anchor_matches(client, base_address, usable[1:]):
                        self._pc_bases_by_process[process_key] = int(base_address)
                        return int(base_address)

        raise ORASLiveError(
            "No se pudo localizar de forma segura la matriz viva del PC de ORAS para leerla."
        )

    def read_pc(
        self,
        anchors: Sequence[SavePokemon],
    ) -> tuple[AzaharProcess, int, dict[tuple[int, int], SavePokemon | None]]:
        """Lee las 31 cajas vivas de ORAS tras una operación del PC.

        Es una lectura excepcional, ejecutada solo cuando cambia la composición
        del equipo. Permite reflejar correctamente los tres flujos del PC del
        juego: Mover Pokémon, Dejar Pokémon y Sacar Pokémon. Nunca escribe RAM.
        """
        try:
            with self.client_factory() as client:
                process = self._find_oras_process(client.process_list())
                client.set_process(process.process_id)
                base_address = self._locate_pc_base_for_read(client, process, anchors)
                stable: bytes | None = None
                for _attempt in range(1, self.snapshot_attempts + 1):
                    first = client.read_memory(base_address, ORAS_PC_SIZE)
                    if self.stable_delay:
                        time.sleep(self.stable_delay)
                    second = client.read_memory(base_address, ORAS_PC_SIZE)
                    if first == second:
                        stable = second
                        break
                if stable is None:
                    raise ORASLiveError("Las cajas cambiaron durante todas las lecturas; se reintentará después.")

                slots: dict[tuple[int, int], SavePokemon | None] = {}
                for index in range(ORAS_PC_BOX_COUNT * ORAS_PC_BOX_SLOT_COUNT):
                    start = index * PK6_STORED_SIZE
                    raw = stable[start:start + PK6_STORED_SIZE]
                    box, slot_index = divmod(index, ORAS_PC_BOX_SLOT_COUNT)
                    box += 1
                    box_slot = slot_index + 1
                    try:
                        pokemon = parse_pk6_boxed(raw, box, box_slot, self.move_names)
                    except ORASLiveError as exc:
                        raise ORASLiveError(
                            f"La lectura viva del PC falló en Caja {box}, hueco {box_slot}: {exc}"
                        ) from exc
                    slots[(box, box_slot)] = pokemon
                return process, int(base_address), slots
        except AzaharRPCError as exc:
            raise ORASLiveError(str(exc)) from exc

    def read(
        self,
        current: SaveGameData,
        memory_blocks: Sequence[tuple[int, int]] = (),
    ) -> ORASLiveSnapshot:
        requests = self._normalize_memory_requests(memory_blocks)
        try:
            with self.client_factory() as client:
                process = self._find_oras_process(client.process_list())
                client.set_process(process.process_id)
                for attempt in range(1, self.snapshot_attempts + 1):
                    first_party = self._read_party(client)
                    first_blocks = self._read_memory_blocks(client, requests)
                    if self.stable_delay:
                        time.sleep(self.stable_delay)
                    second_party = self._read_party(client)
                    second_blocks = self._read_memory_blocks(client, requests)
                    if first_party != second_party or first_blocks != second_blocks:
                        continue
                    party: list[SavePokemon] = []
                    for index, raw in enumerate(second_party, start=1):
                        pokemon = parse_pk6_party(raw, index, self.move_names)
                        if pokemon is not None:
                            party.append(self._preserve_known_labels(pokemon, current))
                    if not party:
                        raise ORASLiveError("La captura estable de ORAS no contiene ningún Pokémon en el equipo.")
                    game = SaveGameData(
                        game=current.game,
                        save_type=f"{current.save_type} + Azahar RPC",
                        generation=current.generation,
                        trainer=current.trainer,
                        party=party,
                        raw={
                            **current.raw,
                            "liveSync": True,
                            # Una lectura nunca es la prueba de que RoleRun
                            # haya escrito memoria. Si la lectura sucede tras
                            # recargar Azahar, evita arrastrar ese marcador de
                            # la instantánea anterior.
                            "liveWrite": False,
                            "liveProcess": process.name,
                            "liveTitleId": f"{process.title_id:016X}",
                            "liveProfile": "ORAS-1.4",
                        },
                    )
                    return ORASLiveSnapshot(
                        game=game,
                        process=process,
                        attempts=attempt,
                        memory_blocks=second_blocks,
                    )
        except AzaharRPCError as exc:
            raise ORASLiveError(str(exc)) from exc

        raise ORASLiveError(
            "El equipo cambió durante todas las lecturas. Sal de la animación o combate y vuelve a pulsar F5."
        )

    def read_monitor(
        self,
        current: SaveGameData,
        memory_blocks: Sequence[tuple[int, int]] = (),
    ) -> ORASLiveSnapshot:
        """Captura estable y ligera para el monitor juego → RoleRun.

        Mantiene la misma doble lectura y las mismas validaciones estructurales
        que ``read``, pero obtiene la party desde una región contigua. No escribe
        memoria y no incluye HP/EXP/nivel en la decisión de refresco de la UI.
        """
        requests = self._normalize_memory_requests(memory_blocks)
        try:
            with self.client_factory() as client:
                process = self._find_oras_process(client.process_list())
                client.set_process(process.process_id)
                for attempt in range(1, self.snapshot_attempts + 1):
                    first_party = self._read_party_compact(client)
                    first_blocks = self._read_memory_blocks(client, requests)
                    if self.stable_delay:
                        time.sleep(self.stable_delay)
                    second_party = self._read_party_compact(client)
                    second_blocks = self._read_memory_blocks(client, requests)
                    if first_party != second_party or first_blocks != second_blocks:
                        continue
                    party: list[SavePokemon] = []
                    for index, raw in enumerate(second_party, start=1):
                        pokemon = parse_pk6_party(raw, index, self.move_names)
                        if pokemon is not None:
                            party.append(self._preserve_known_labels(pokemon, current))
                    if not party:
                        raise ORASLiveError("La captura estable de ORAS no contiene ningún Pokémon en el equipo.")
                    game = SaveGameData(
                        game=current.game,
                        save_type=f"{current.save_type} + Azahar RPC",
                        generation=current.generation,
                        trainer=current.trainer,
                        party=party,
                        raw={
                            **current.raw,
                            "liveSync": True,
                            "liveWrite": False,
                            "liveProcess": process.name,
                            "liveTitleId": f"{process.title_id:016X}",
                            "liveProfile": "ORAS-1.4",
                        },
                    )
                    return ORASLiveSnapshot(
                        game=game, process=process, attempts=attempt,
                        memory_blocks=second_blocks,
                    )
        except AzaharRPCError as exc:
            raise ORASLiveError(str(exc)) from exc
        raise ORASLiveError(
            "El equipo cambió durante todas las lecturas del monitor; se reintentará automáticamente."
        )

    def read_battle_probe(self, current: SaveGameData) -> ORASBattleProbe | None:
        """Lee estado/PS de batalla sin exigir estabilidad entre dos muestras.

        La party normal y esta sonda están deliberadamente desacopladas. Un fallo
        de RPC, una animación o un valor transitorio aquí devuelve ``None`` y el
        monitor principal continúa intacto. Esto garantiza el fallback de muerte
        al salir del combate.
        """
        try:
            with self.client_factory() as client:
                process = self._find_oras_process(client.process_list())
                client.set_process(process.process_id)

                wild_opp = client.read_memory(ORAS_BATTLE_WILD_OPPONENT_ADDRESS, PK6_STORED_SIZE)
                trainer_opp = client.read_memory(ORAS_BATTLE_TRAINER_OPPONENT_ADDRESS, PK6_STORED_SIZE)
                wild_pp_byte = client.read_memory(ORAS_BATTLE_WILD_PP_ADDRESS, 1)
                trainer_pp_byte = client.read_memory(ORAS_BATTLE_TRAINER_PP_ADDRESS, 1)
                blocks = (
                    ORASLiveMemoryBlock(ORAS_BATTLE_WILD_OPPONENT_ADDRESS, bytes(wild_opp)),
                    ORASLiveMemoryBlock(ORAS_BATTLE_TRAINER_OPPONENT_ADDRESS, bytes(trainer_opp)),
                    ORASLiveMemoryBlock(ORAS_BATTLE_WILD_PP_ADDRESS, bytes(wild_pp_byte)),
                    ORASLiveMemoryBlock(ORAS_BATTLE_TRAINER_PP_ADDRESS, bytes(trainer_pp_byte)),
                )
                state = parse_oras_battle_state(blocks)
                if state not in {"wild", "trainer"}:
                    return ORASBattleProbe(state="none")

                pp_address = (
                    ORAS_BATTLE_WILD_PP_ADDRESS if state == "wild"
                    else ORAS_BATTLE_TRAINER_PP_ADDRESS
                )
                count = min(6, len(current.party))
                if count <= 0:
                    return ORASBattleProbe(state=state)
                start = int(pp_address) + ORAS_BATTLE_DYNAMIC_HP_OFFSET
                size = ((count - 1) * ORAS_BATTLE_MON_STRIDE) + ORAS_BATTLE_DYNAMIC_HP_PAIR_SIZE
                raw = client.read_memory(start, size)
        except Exception:
            return None

        party: list[SavePokemon] = []
        pairs: list[tuple[int, int]] = []
        valid = 0
        for index, pokemon in enumerate(current.party):
            clone = replace(
                pokemon,
                moves=list(pokemon.moves),
                move_ids=list(pokemon.move_ids),
                markings=list(pokemon.markings),
            )
            if index < count:
                offset = index * ORAS_BATTLE_MON_STRIDE
                if offset + 4 <= len(raw):
                    max_hp, current_hp = struct.unpack_from("<HH", raw, offset)
                    # El motor de batalla puede publicar valores transitorios al
                    # entrar/salir. No exigimos igualdad con max_hp overworld (mods
                    # pueden alterar stats), pero sí una estructura físicamente válida.
                    if 1 <= int(max_hp) <= 9999 and 0 <= int(current_hp) <= int(max_hp):
                        clone.max_hp = int(max_hp)
                        clone.current_hp = int(current_hp)
                        pairs.append((int(current_hp), int(max_hp)))
                        valid += 1
                    else:
                        pairs.append((-1, -1))
            party.append(clone)

        health = None
        if valid:
            health = SaveGameData(
                game=current.game,
                save_type=f"{current.save_type} + PS batalla Azahar RPC",
                generation=current.generation,
                trainer=current.trainer,
                party=party,
                raw={**current.raw, "liveBattleHealth": True, "liveBattleState": state},
            )
        return ORASBattleProbe(state=state, health_game=health, hp_pairs=tuple(pairs))


    def read_tm_inventory(self) -> tuple[dict[int, int], AzaharProcess, int]:
        """Devuelve las MT/HM que están disponibles ahora mismo en la RAM de ORAS."""
        try:
            with self.client_factory() as client:
                process = self._find_oras_process(client.process_list())
                client.set_process(process.process_id)
                for attempt in range(1, self.snapshot_attempts + 1):
                    first = client.read_memory(ORAS_TM_POUCH_ADDRESS, ORAS_TM_POUCH_SIZE)
                    if self.stable_delay:
                        time.sleep(self.stable_delay)
                    second = client.read_memory(ORAS_TM_POUCH_ADDRESS, ORAS_TM_POUCH_SIZE)
                    if first != second:
                        continue
                    return parse_oras_item_pocket(second, label="MT/MO"), process, attempt
        except AzaharRPCError as exc:
            raise ORASLiveError(str(exc)) from exc
        raise ORASLiveError(
            "Las MT/MO cambiaron durante todas las lecturas. Cierra la mochila del juego y vuelve a intentarlo."
        )


class _ORASLiveWriterExtendedMixin:

    @staticmethod
    def _captured_subblock(
        captured: dict[str, bytes],
        requests: Sequence[tuple[str, int, int]],
        address: int,
        size: int,
    ) -> bytes:
        """Obtiene un subbloque de una captura auxiliar ya confirmada."""
        end = address + size
        for key, base, block_size in requests:
            if base <= address and end <= base + block_size:
                raw = captured[key]
                offset = address - base
                return raw[offset:offset + size]
        raise ORASLiveError("La verificación no encontró el bloque auxiliar esperado.")

    def _extended_requests(
        self,
        changes: Sequence[object],
        *,
        pc_base: int = ORAS_PC_ADDRESS,
        inventory_delta: int = 0,
        inventory_witness_labels: Sequence[str] = (),
    ) -> tuple[tuple[str, int, int], ...]:
        requests: dict[str, tuple[int, int]] = {}

        def add(key: str, address: int, size: int) -> None:
            current = requests.get(key)
            value = (address, size)
            if current is not None and current != value:
                raise ORASLiveError("La cola de Azahar contiene bloques auxiliares incompatibles.")
            requests[key] = value

        for change in changes:
            if isinstance(change, (PendingPCRoleChange, PendingTeamChange)):
                box = int(change.box)
                box_slot = int(change.box_slot)
                add(
                    f"pc:{box}:{box_slot}",
                    self._box_slot_address(box, box_slot, base_address=pc_base),
                    PK6_STORED_SIZE,
                )
                if isinstance(change, PendingTeamChange) and change.operation == "replace-fainted":
                    if change.graveyard_box is None or change.graveyard_box_slot is None:
                        raise ORASLiveError("La sustitución de un debilitado no tiene destino de cementerio.")
                    graveyard_box = int(change.graveyard_box)
                    graveyard_slot = int(change.graveyard_box_slot)
                    add(
                        f"pc:{graveyard_box}:{graveyard_slot}",
                        self._box_slot_address(graveyard_box, graveyard_slot, base_address=pc_base),
                        PK6_STORED_SIZE,
                    )
            elif isinstance(change, PendingInventoryChange):
                if change.item_key == "money-max":
                    add("money", ORAS_MONEY_ADDRESS + int(inventory_delta), 4)
                else:
                    target = ORAS_INVENTORY_TARGETS.get(change.item_key)
                    if target is None:
                        raise ORASLiveError(
                            f"La utilidad '{change.item_name}' no tiene una dirección ORAS validada."
                        )
                    _item_id, label = target
                    _address, size = _POUCH_LAYOUT[label]
                    add(f"pocket:{label}", _pouch_address(label, inventory_delta), size)
            elif isinstance(change, PendingTMTeach):
                # MTs reutilizables: el cambio vive exclusivamente en el PK6.
                # No capturamos la mochila para no acoplar una escritura de
                # movimientos a una calibración de inventario innecesaria.
                pass
        # Los bolsillos que sirven de testigo también se capturan dentro de la
        # doble lectura. Así una calibración nunca se reutiliza si la mochila
        # cambió entre el barrido y el momento de escribir.
        for label in inventory_witness_labels:
            if label not in _POUCH_LAYOUT:
                continue
            _address, size = _POUCH_LAYOUT[label]
            add(f"pocket:{label}", _pouch_address(label, inventory_delta), size)
        return tuple((key, address, size) for key, (address, size) in requests.items())

    def _apply_extended(
        self,
        current: SaveGameData,
        changes: Sequence[object],
    ) -> ORASLiveWriteResult:
        """Aplica el conjunto ampliado de operaciones que no altera el save.

        Cajas e inventario se editan en bloques pequeños, ya existentes y
        verificados. Las MT de ORAS son reutilizables: se comprueba que la
        máquina está presente, pero no se descuenta ninguna unidad de la mochila.
        """
        unsupported = self._unsupported_changes(changes)
        if unsupported:
            raise ORASLiveError(
                "Esta operación contiene cambios sin escritura viva validada: "
                + ", ".join(unsupported)
                + ". No se escribió nada."
            )
        supported = [
            change for change in changes
            if isinstance(
                change,
                (PendingChange, PendingRoleChange, PendingPCRoleChange, PendingInventoryChange, PendingTMTeach, PendingTeamChange),
            )
        ]
        if not supported:
            raise ORASLiveError("No hay cambios compatibles con Azahar en esta cola.")

        party_changes = [
            change for change in supported
            if isinstance(change, (PendingChange, PendingRoleChange, PendingTMTeach))
        ]
        pc_changes = [change for change in supported if isinstance(change, PendingPCRoleChange)]
        team_swaps = [
            change for change in supported
            if isinstance(change, PendingTeamChange) and change.operation in {"swap-party-box", "replace-fainted"}
        ]
        faint_replacements = [
            change for change in team_swaps if change.operation == "replace-fainted"
        ]
        if len(team_swaps) > 1:
            raise ORASLiveError(
                "Solo se puede confirmar una sustitución Equipo ↔ PC por captura. "
                "No se escribió ningún byte; pulsa F5 y repite las sustituciones de una en una."
            )
        inventory_changes = [change for change in supported if isinstance(change, PendingInventoryChange)]
        tm_changes = [change for change in supported if isinstance(change, PendingTMTeach)]
        # ORAS tiene MT reutilizables. Enseñar una MT solo modifica el PK6 del
        # equipo: no escribe ni necesita localizar la mochila. La disponibilidad
        # se usa para construir el selector, pero la escritura viva no debe
        # depender de que el ``main`` coincida byte a byte con la bolsa actual.
        inventory_sources = list(inventory_changes)

        try:
            with self.reader.client_factory() as client:
                process = self.reader._find_oras_process(client.process_list())
                client.set_process(process.process_id)
                pc_locator_changes = [*pc_changes, *team_swaps]
                pc_base = (
                    self._locate_pc_base(client, process, pc_locator_changes)
                    if pc_locator_changes else ORAS_PC_ADDRESS
                )
                inventory_witnesses = (
                    self._inventory_witness_map(inventory_sources)
                    if inventory_sources else {}
                )
                inventory_delta = (
                    self._locate_inventory_delta(client, process, inventory_witnesses)
                    if inventory_sources else 0
                )
                requests = self._extended_requests(
                    supported,
                    pc_base=pc_base,
                    inventory_delta=inventory_delta,
                    inventory_witness_labels=tuple(inventory_witnesses),
                )
                original_capture, original_extra, capture_attempt = self._capture_stable_state(client, requests)
                live_party = self._read_party_members(original_capture, current)
                if not live_party:
                    raise ORASLiveError("La captura estable de ORAS no contiene ningún Pokémon en el equipo.")
                if inventory_witnesses:
                    self._validate_inventory_witness_capture(original_extra, inventory_witnesses)

                # --- Objetivos de party y MT ---------------------------------
                party_targets = {
                    id(change): self._resolve_target(change, live_party)
                    for change in party_changes
                }
                swap_party_targets = {
                    id(change): self._resolve_team_swap_party_target(change, live_party)
                    for change in team_swaps
                }
                if tm_changes:
                    for change in tm_changes:
                        tm_number = int(change.tm_number)
                        expected_item = oras_tm_item_id(tm_number)
                        if expected_item is None or int(change.item_id) != expected_item:
                            raise ORASLiveError(
                                "La MT preparada no corresponde a la tabla original de ORAS. "
                                "No se escribió ningún movimiento."
                            )

                original_slots: dict[int, bytes] = {}
                plain_slots: dict[int, bytearray] = {}
                was_encrypted: dict[int, bool] = {}
                all_party_targets = {*party_targets.values(), *swap_party_targets.values()}
                for slot in sorted(all_party_targets):
                    original = original_capture[slot - 1]
                    plain, encrypted = _plain_pk6(original)
                    original_slots[slot] = original
                    plain_slots[slot] = bytearray(plain)
                    was_encrypted[slot] = encrypted

                # --- Objetivos de PC ------------------------------------------
                pc_plain: dict[tuple[int, int], bytearray] = {}
                pc_encrypted: dict[tuple[int, int], bool] = {}
                pc_original: dict[tuple[int, int], bytes] = {}
                pc_identity: dict[tuple[int, int], str] = {}
                pc_target_changes = [*pc_changes, *team_swaps]
                pc_kind: dict[tuple[int, int], str] = {}
                for change in pc_target_changes:
                    key = (int(change.box), int(change.box_slot))
                    raw = original_extra[f"pc:{key[0]}:{key[1]}"]
                    pokemon = self._resolve_pc_target(change, raw)
                    if key not in pc_plain:
                        plain, encrypted = _plain_stored_pk6(raw)
                        pc_plain[key] = bytearray(plain)
                        pc_encrypted[key] = encrypted
                        pc_original[key] = raw
                    target_identity = self._pc_target_identity(change)
                    pc_identity[key] = str(target_identity or self._pokemon_identity(pokemon))
                    pc_kind[key] = "pc-role" if isinstance(change, PendingPCRoleChange) else "pc-team"

                # Una baja usa dos posiciones de PC: el Pokémon sustituto sale de
                # su hueco y el debilitado entra en el hueco de Cementerio elegido.
                # La posición de cementerio se valida aquí, dentro
                # de la misma doble captura estable, antes de preparar un solo byte.
                for change in faint_replacements:
                    source_key = (int(change.box), int(change.box_slot))
                    graveyard_key = (int(change.graveyard_box), int(change.graveyard_box_slot))
                    if graveyard_key == source_key:
                        raise ORASLiveError(
                            "El sustituto no puede proceder del mismo hueco reservado para el cementerio."
                        )
                    graveyard_raw = original_extra[
                        f"pc:{graveyard_key[0]}:{graveyard_key[1]}"
                    ]
                    graveyard_current = parse_pk6_boxed(
                        graveyard_raw, graveyard_key[0], graveyard_key[1], self.reader.move_names,
                    )
                    if graveyard_current is not None:
                        raise ORASLiveError(
                            f"El hueco {graveyard_key[0]}:{graveyard_key[1]} del Cementerio ya no está libre. "
                            "No se escribió ningún byte; vuelve a elegir el sustituto."
                        )
                    pc_plain[graveyard_key] = bytearray(PK6_STORED_SIZE)
                    pc_encrypted[graveyard_key] = False
                    pc_original[graveyard_key] = graveyard_raw
                    pc_identity[graveyard_key] = ""
                    pc_kind[graveyard_key] = "pc-graveyard"

                # Las operaciones se aplican siempre en el orden de la cola.
                # Así un cambio de rol seguido de una MT conserva la misma
                # semántica que el flujo de guardado tradicional.
                for change in supported:
                    if isinstance(change, PendingRoleChange):
                        self._replace_role(plain_slots[party_targets[id(change)]], change)
                    elif isinstance(change, (PendingChange, PendingTMTeach)):
                        self._replace_move(plain_slots[party_targets[id(change)]], change)
                    elif isinstance(change, PendingPCRoleChange):
                        self._set_role(pc_plain[(int(change.box), int(change.box_slot))], change.new_role)

                # --- Sustitución Equipo ↔ PC --------------------------------
                # Un PK6 almacenado no incluye nivel/PS/estadísticas de combate.
                # Se reconstruye ese bloque con los datos personales de la ROM
                # efectiva y después se intercambian ambos PK6 en memoria.
                swap_slots: set[int] = set()
                for change in team_swaps:
                    slot = swap_party_targets[id(change)]
                    key = (int(change.box), int(change.box_slot))
                    incoming = bytearray(pc_plain[key])
                    self._set_role(incoming, change.incoming_role or "SIN ROL")
                    self._remove_move_slots(incoming, change.remove_move_slots)
                    self._refresh_checksum(incoming)
                    species_id = struct.unpack_from("<H", incoming, 8)[0]
                    form = incoming[0x1D] >> 3
                    personal = self.personal_for(species_id, form) if self.personal_for else None
                    if personal is None:
                        raise ORASLiveError(
                            f"La ROM activa no aportó estadísticas personales para la especie #{species_id}, forma {form}. "
                            "No se escribió ningún byte."
                        )
                    extension = self._party_extension(incoming, personal)

                    outgoing = bytearray(plain_slots[slot][:PK6_STORED_SIZE])
                    self._refresh_checksum(outgoing)
                    plain_slots[slot] = bytearray(bytes(incoming) + extension)

                    if change.operation == "replace-fainted":
                        # El hueco del sustituto queda vacío y el debilitado se
                        # deposita en la caja de Cementerio. Nunca reducimos el tamaño de
                        # la party ni dejamos un slot vacío durante un combate.
                        graveyard_key = (int(change.graveyard_box), int(change.graveyard_box_slot))
                        pc_plain[key] = bytearray(PK6_STORED_SIZE)
                        pc_encrypted[key] = False
                        pc_identity[key] = ""
                        pc_kind[key] = "pc-empty"

                        pc_plain[graveyard_key] = outgoing
                        pc_encrypted[graveyard_key] = True
                        pc_identity[graveyard_key] = str(
                            change.outgoing_identity or self._pokemon_identity(live_party[slot])
                        )
                        pc_kind[graveyard_key] = "pc-graveyard"
                    else:
                        pc_plain[key] = outgoing
                        pc_identity[key] = str(
                            change.outgoing_identity or self._pokemon_identity(live_party[slot])
                        )
                        pc_kind[key] = "pc-team"
                    swap_slots.add(slot)

                # --- Inventario y dinero --------------------------------------
                pouch_original: dict[str, bytes] = {}
                pouch_modified: dict[str, bytearray] = {}
                pouch_offsets: dict[str, set[int]] = {}
                money_original: bytes | None = None
                money_modified: bytes | None = None
                for change in inventory_changes:
                    if change.item_key == "money-max":
                        if money_original is None:
                            money_original = original_extra["money"]
                            self._validate_money(money_original)
                        money_modified = struct.pack("<I", ORAS_MAX_MONEY)
                        continue
                    target = ORAS_INVENTORY_TARGETS.get(change.item_key)
                    if target is None:
                        raise ORASLiveError(
                            f"La utilidad '{change.item_name}' no tiene un objetivo validado en ORAS."
                        )
                    item_id, label = target
                    if label not in pouch_modified:
                        raw = original_extra[f"pocket:{label}"]
                        parse_oras_item_pocket(raw, label=label)
                        pouch_original[label] = raw
                        pouch_modified[label] = bytearray(raw)
                        pouch_offsets[label] = set()
                    pouch_offsets[label].update(self._prepare_inventory_value(
                        pouch_modified[label], item_id, int(change.quantity), label=change.item_name,
                    ))

                # --- Prepara todos los bytes antes de escribir el primero -----
                planned: dict[int, tuple[bytes, bytes, str, str]] = {}

                def plan(address: int, original: bytes, replacement: bytes, kind: str, identity: str = "") -> None:
                    if original == replacement:
                        return
                    previous = planned.get(address)
                    if previous is not None and previous[1] != original:
                        raise ORASLiveError("Dos operaciones intentan modificar el mismo bloque auxiliar de forma incompatible.")
                    planned[address] = (replacement, original, kind, identity)

                expected_party: dict[int, SavePokemon] = {}
                for slot, plain in plain_slots.items():
                    self._refresh_checksum(plain)
                    encoded = encrypt_pk6(bytes(plain)) if was_encrypted[slot] else bytes(plain)
                    expected = parse_pk6_party(encoded, slot, self.reader.move_names)
                    if expected is None:
                        raise ORASLiveError(f"El slot {slot} quedó vacío durante la preparación; no se escribió nada.")
                    expected_party[slot] = expected
                    plan(self._slot_address(slot), original_slots[slot][:PK6_STORED_SIZE], encoded[:PK6_STORED_SIZE], "party")
                    if slot in swap_slots:
                        plan(
                            self._slot_address(slot) + ORAS_PARTY_STATS_OFFSET,
                            original_slots[slot][PK6_STORED_SIZE:PK6_STORED_SIZE + ORAS_PARTY_STATS_SIZE],
                            encoded[PK6_STORED_SIZE:PK6_STORED_SIZE + ORAS_PARTY_STATS_SIZE],
                            "party-stats",
                        )

                expected_pc: dict[tuple[int, int], bytes] = {}
                for key, plain in pc_plain.items():
                    # Un hueco que debe quedar vacío no es un PK6 y no necesita
                    # checksum. Para el resto conservamos la validación habitual.
                    kind = pc_kind.get(key, "pc-role")
                    if kind != "pc-empty":
                        self._refresh_checksum(plain)
                    encoded = encrypt_pk6_stored(bytes(plain)) if pc_encrypted[key] else bytes(plain)
                    expected = parse_pk6_boxed(encoded, key[0], key[1], self.reader.move_names)
                    if expected is None and kind != "pc-empty":
                        raise ORASLiveError(f"El hueco PC {key[0]}:{key[1]} quedó vacío durante la preparación.")
                    if expected is not None and kind == "pc-empty":
                        raise ORASLiveError(f"El hueco PC {key[0]}:{key[1]} no quedó vacío durante la preparación.")
                    expected_pc[key] = encoded
                    plan(
                        self._box_slot_address(*key, base_address=pc_base), pc_original[key], encoded,
                        pc_kind.get(key, "pc-role"), pc_identity.get(key, ""),
                    )

                for label, offsets in pouch_offsets.items():
                    original = pouch_original[label]
                    modified = pouch_modified[label]
                    base = _pouch_address(label, inventory_delta)
                    for offset in sorted(offsets):
                        plan(
                            base + offset,
                            original[offset:offset + ORAS_ITEM_RECORD_SIZE],
                            bytes(modified[offset:offset + ORAS_ITEM_RECORD_SIZE]),
                            "inventory",
                        )
                if money_original is not None and money_modified is not None:
                    plan(ORAS_MONEY_ADDRESS + int(inventory_delta), money_original, money_modified, "money")

                if not planned:
                    # La captura doble ya demostró que estos bytes son estables.
                    # Si todos coinciden con el objetivo, no es un fallo: no
                    # volver a escribir evita tocar RAM innecesariamente y
                    # permite retirar la cola pendiente con seguridad.
                    watch_specs: list[tuple[int, bytes, str, str]] = []
                    for key, expected in expected_pc.items():
                        watch_specs.append((
                            self._box_slot_address(*key, base_address=pc_base),
                            expected,
                            pc_kind.get(key, "pc-role"),
                            pc_identity.get(key, ""),
                        ))
                    for label, offsets in pouch_offsets.items():
                        base = _pouch_address(label, inventory_delta)
                        modified = pouch_modified[label]
                        for offset in sorted(offsets):
                            watch_specs.append((
                                base + offset,
                                bytes(modified[offset:offset + ORAS_ITEM_RECORD_SIZE]),
                                "inventory",
                                "",
                            ))
                    if money_modified is not None:
                        watch_specs.append((ORAS_MONEY_ADDRESS + int(inventory_delta), money_modified, "money", ""))

                    pc_addresses = {
                        self._box_slot_address(*key, base_address=pc_base): key
                        for key in expected_pc
                    }
                    watches = tuple(
                        ORASLiveMemoryWatch(
                            address, expected, kind, identity,
                            *(pc_addresses.get(address, (None, None)) if kind.startswith("pc-") else (None, None)),
                        )
                        for address, expected, kind, identity in sorted(watch_specs)
                    )
                    return ORASLiveWriteResult(
                        game=self._build_game(original_capture, current, process, live_write=True),
                        process=process,
                        attempts=capture_attempt,
                        applied_count=len(supported),
                        memory_watches=watches,
                        already_applied=True,
                    )

                attempted: list[tuple[int, bytes]] = []
                try:
                    for address in sorted(planned):
                        replacement, original, _kind, _identity = planned[address]
                        attempted.append((address, original))
                        client.write_memory(address, replacement)

                    def validate_verified_state(capture, extra) -> None:
                        verified_party = self._read_party_members(capture, current)
                        for slot, expected in expected_party.items():
                            actual = verified_party.get(slot)
                            if actual is None or self._pokemon_identity(actual) != self._pokemon_identity(expected):
                                raise ORASLiveError(
                                    f"Azahar devolvió un Pokémon distinto en el slot {slot} tras la escritura."
                                )
                            if actual.role != expected.role or actual.move_ids != expected.move_ids:
                                raise ORASLiveError(
                                    f"Azahar no confirmó los cambios del slot {slot}; se restaurará el contenido original."
                                )
                            if slot in swap_slots:
                                expected_raw = (
                                    encrypt_pk6(bytes(plain_slots[slot]))
                                    if was_encrypted[slot] else bytes(plain_slots[slot])
                                )
                                actual_raw = capture[slot - 1]
                                if (
                                    actual_raw[:PK6_STORED_SIZE] != expected_raw[:PK6_STORED_SIZE]
                                    or actual_raw[PK6_STORED_SIZE:PK6_STORED_SIZE + ORAS_PARTY_STATS_SIZE]
                                    != expected_raw[PK6_STORED_SIZE:PK6_STORED_SIZE + ORAS_PARTY_STATS_SIZE]
                                ):
                                    raise ORASLiveError(
                                        f"Azahar no confirmó el bloque completo del nuevo Pokémon en el slot {slot}."
                                    )
                        for key, expected_raw in expected_pc.items():
                            actual_raw = extra[f"pc:{key[0]}:{key[1]}"]
                            actual = parse_pk6_boxed(actual_raw, key[0], key[1], self.reader.move_names)
                            expected = parse_pk6_boxed(expected_raw, key[0], key[1], self.reader.move_names)
                            if actual_raw != expected_raw:
                                raise ORASLiveError(
                                    f"Azahar no confirmó la caja {key[0]}, hueco {key[1]}."
                                )
                            if expected is None:
                                if actual is not None:
                                    raise ORASLiveError(
                                        f"Azahar no confirmó que la caja {key[0]}, hueco {key[1]} quedase vacía."
                                    )
                                continue
                            if actual is None:
                                raise ORASLiveError(
                                    f"Azahar vació inesperadamente la caja {key[0]}, hueco {key[1]}."
                                )
                            if self._pokemon_identity(actual) != self._pokemon_identity(expected) or actual.role != expected.role:
                                raise ORASLiveError(
                                    f"El Pokémon de la caja {key[0]}, hueco {key[1]} cambió durante la escritura."
                                )
                        for address, (replacement, _original, kind, _identity) in planned.items():
                            if kind.startswith("party"):
                                continue
                            actual = self._captured_subblock(extra, requests, address, len(replacement))
                            if actual != replacement:
                                raise ORASLiveError(
                                    f"Azahar no confirmó la escritura auxiliar en 0x{address:08X}."
                                )

                    verified_capture, verified_extra, verified_attempt = self._capture_stable_state(client, requests)
                    validate_verified_state(verified_capture, verified_extra)

                    # Una sustitución por muerte modifica simultáneamente party + dos
                    # huecos de PC. ORAS puede aceptar la escritura y acto seguido
                    # reconstruir la party desde su propio estado interno. La alpha.26
                    # podía publicar entonces Golem en RoleRun aunque el juego hubiese
                    # vuelto a Granbull. Para este caso hacemos una SEGUNDA verificación
                    # diferida; solo publicamos éxito si el estado sobrevive al ciclo
                    # de actualización del juego. Si no, el rollback existente restaura
                    # los bytes originales y RoleRun nunca adelanta visualmente al juego.
                    if faint_replacements:
                        time.sleep(max(0.60, float(getattr(self.reader, "stable_delay", 0.06)) * 5.0))
                        late_capture, late_extra, late_attempt = self._capture_stable_state(client, requests)
                        validate_verified_state(late_capture, late_extra)
                        verified_capture, verified_extra = late_capture, late_extra
                        verified_attempt = max(verified_attempt, late_attempt)

                    game = self._build_game(verified_capture, current, process, live_write=True)
                    pc_addresses = {
                        self._box_slot_address(*key, base_address=pc_base): key
                        for key in expected_pc
                    }
                    watches = tuple(
                        ORASLiveMemoryWatch(
                            address, replacement, kind, identity,
                            *(pc_addresses.get(address, (None, None)) if kind.startswith("pc-") else (None, None)),
                        )
                        for address, (replacement, _original, kind, identity) in sorted(planned.items())
                        if not kind.startswith("party")
                    )
                    return ORASLiveWriteResult(
                        game=game,
                        process=process,
                        attempts=max(capture_attempt, verified_attempt),
                        applied_count=len(supported),
                        memory_watches=watches,
                    )
                except Exception as exc:
                    rollback_errors = self._rollback(client, attempted)
                    if rollback_errors:
                        raise ORASLiveError(
                            f"La sincronización en vivo falló: {exc}. "
                            "No se pudo confirmar la restauración de todos los bloques: "
                            + "; ".join(rollback_errors)
                        ) from exc
                    if attempted:
                        raise ORASLiveError(
                            f"La sincronización en vivo falló: {exc}. "
                            "RoleRun restauró los bytes originales en RAM y no tocó el archivo main."
                        ) from exc
                    raise
        except AzaharRPCError as exc:
            raise ORASLiveError(str(exc)) from exc
class ORASLiveWriter(_ORASLiveWriterExtendedMixin):
    """Aplica una porción acotada y verificable de RoleRun directamente en ORAS.

    El escritor no toca ``main``, estados de Azahar ni datos de historia. Puede
    actualizar campos PK6 de equipo/caja, utilidades de mochila y dinero solo
    después de una doble captura idéntica. Toda escritura se relee y valida;
    si no coincide, se restauran los bytes originales en RAM.
    """

    def __init__(
        self,
        reader: ORASLiveReader,
        move_pp_for: Callable[[int], int],
        personal_for: Callable[[int, int], ORASPersonalStats | None] | None = None,
    ) -> None:
        self.reader = reader
        self.move_pp_for = move_pp_for
        self.personal_for = personal_for
        self._pc_bases_by_process: dict[tuple[int, str], int] = {}
        self._inventory_deltas_by_process: dict[tuple[int, str], int] = {}
        self._misc_bases_by_process: dict[tuple[int, str], int] = {}
        self._eventwork_bases_by_process: dict[tuple[int, str], int] = {}
        self._subevent_bases_by_process: dict[tuple[int, str], int] = {}
        self._subevent_failed_scan_at: dict[tuple[int, str], float] = {}
        self._tm_badge_bases_by_process: dict[tuple[int, str], int] = {}
        # Alpha.45: el selector de MT comparte la misma copia viva de la mochila
        # que el detector de medallas. Azahar puede conservar una copia antigua
        # en la dirección nominal, así que no debemos volver a leerla a ciegas.
        self._tm_inventory_bases_by_process: dict[tuple[int, str], int] = {}
        self._tm_badge_failed_scan_at: dict[tuple[int, str], float] = {}
        # 0.2.1-alpha.2: caché/localización común del Real-Time Core. Se usa ya
        # para la mochila MT/MO y queda como patrón para XY/SM/USUM. Los dicts
        # legacy se conservan como espejo para compatibilidad con tests y código
        # de escritura anterior; nunca se aceptan sin volver a validar bytes.
        self.block_resolver = LiveBlockResolver(default_failure_cooldown=8.0)
        self._last_badge_source: str | None = None

    @property
    def last_badge_source(self) -> str | None:
        """Fuente usada por la última lectura de medallas (diagnóstico UI)."""
        return self._last_badge_source

    @staticmethod
    def _inventory_witness_map(changes: Sequence[object]) -> dict[str, dict[int, tuple[int, int]]]:
        """Normaliza la huella del guardado que identifica la mochila viva.

        Las cantidades cero son válidas: representan que el objeto no existía
        en el último guardado. Ese dato evita tomar una copia secundaria que
        conserve el resto de la bolsa pero haya recibido una escritura antigua.
        """
        result: dict[str, dict[int, tuple[int, int]]] = {}
        for change in changes:
            for entry in tuple(getattr(change, "inventory_witnesses", ()) or ()):
                try:
                    label, slot, item_id, quantity = entry
                    label = str(label or "").casefold()
                    slot = int(slot)
                    item_id = int(item_id)
                    quantity = int(quantity)
                except (TypeError, ValueError):
                    continue
                if label not in _POUCH_LAYOUT or not 1 <= item_id <= 1500:
                    continue
                slot_count = _POUCH_LAYOUT[label][1] // ORAS_ITEM_RECORD_SIZE
                if slot >= 0:
                    if slot >= slot_count or not 1 <= quantity <= ORAS_MAX_BAG_QUANTITY:
                        continue
                elif slot == -item_id:
                    if quantity != 0:
                        continue
                else:
                    continue
                entries = result.setdefault(label, {})
                value = (item_id, quantity)
                previous = entries.get(slot)
                if previous is not None and previous != value:
                    raise ORASLiveError(
                        "La mochila cambió entre operaciones pendientes. Pulsa F5 y vuelve a preparar la utilidad."
                    )
                entries[slot] = value

        positives_by_label = {
            label: sum(1 for slot, (_item_id, quantity) in entries.items() if slot >= 0 and quantity > 0)
            for label, entries in result.items()
        }
        positive_total = sum(positives_by_label.values())
        if positive_total < 2 or max(positives_by_label.values(), default=0) < 2:
            raise ORASLiveError(
                "No hay suficientes objetos del último guardado para localizar la mochila viva de ORAS. "
                "Guarda normalmente dentro del juego, pulsa F5 y vuelve a intentarlo. No se escribió ningún byte."
            )
        return result

    @staticmethod
    def _eventwork_badge_byte_offsets() -> frozenset[int]:
        return frozenset(
            ORAS_EVENTWORK_FLAG_OFFSET + (int(flag) >> 3)
            for flag in ORAS_BADGE_RECEIVED_FLAGS
        )

    @classmethod
    def _eventwork_fingerprint_positions(cls, saved_eventwork: bytes) -> tuple[int, ...]:
        """Testigos de EventWork sin los dos bytes de ``Received Badge``.

        El guardado puede estar varias medallas por detrás de la sesión viva, así
        que jamás comparamos los bytes que contienen esos flags. EventWork es un
        bloque mucho más rico que Misc: mezcla variables y cientos de flags de
        historia, por lo que una muestra repartida por el bloque funciona bien
        como huella sin necesitar que ``main`` esté recién guardado.
        """
        if len(saved_eventwork) != ORAS_SAVE_EVENTWORK_SIZE:
            return ()
        excluded = cls._eventwork_badge_byte_offsets()
        nonzero = [
            i for i, value in enumerate(saved_eventwork)
            if i not in excluded and value != 0
        ]
        if len(nonzero) <= 64:
            return tuple(nonzero)
        step = max(1, len(nonzero) // 64)
        return tuple(nonzero[::step][:64])

    @classmethod
    def _eventwork_candidate_score(
        cls, raw: bytes, saved_eventwork: bytes, *, relaxed: bool = False,
    ) -> tuple[int, int] | None:
        if len(raw) != ORAS_SAVE_EVENTWORK_SIZE or len(saved_eventwork) != ORAS_SAVE_EVENTWORK_SIZE:
            return None
        badge_count = count_oras_received_badges(raw)
        if badge_count is None or not cls._badge_flags_form_prefix(raw):
            return None
        positions = cls._eventwork_fingerprint_positions(saved_eventwork)
        if not positions:
            return None
        matches = sum(raw[pos] == saved_eventwork[pos] for pos in positions)
        # La sesión puede llevar horas por delante del último guardado. Para la
        # búsqueda por anchor pedimos una coincidencia fuerte; el fallback por
        # patrón de medallas admite más deriva pero todavía exige una huella real.
        ratio = 0.35 if relaxed else 0.58
        required = max(8 if relaxed else 12, int(len(positions) * ratio))
        if matches < required:
            return None
        # En la primera calibración, si quedan copias antiguas equivalentes en
        # RAM, la que tiene más medallas recibidas es la más reciente. Una vez
        # cacheada la base ya no usamos este desempate, por lo que un state-load
        # hacia atrás puede reducir el contador normalmente.
        return matches, int(badge_count)

    @classmethod
    def _eventwork_anchors(cls, saved_eventwork: bytes) -> tuple[tuple[int, bytes], ...]:
        """Devuelve varias ventanas con entropía para localizar EventWork rápido."""
        if len(saved_eventwork) != ORAS_SAVE_EVENTWORK_SIZE:
            return ()
        excluded = cls._eventwork_badge_byte_offsets()
        width = 12
        ranked: list[tuple[int, int, bytes]] = []
        for offset in range(0, len(saved_eventwork) - width + 1):
            if any(index in excluded for index in range(offset, offset + width)):
                continue
            window = bytes(saved_eventwork[offset:offset + width])
            nonzero = sum(value != 0 for value in window)
            distinct = len(set(window))
            if nonzero < 5:
                continue
            ranked.append((nonzero * 4 + distinct, offset, window))
        ranked.sort(reverse=True)
        chosen: list[tuple[int, bytes]] = []
        for _score, offset, window in ranked:
            if any(abs(offset - previous) < width for previous, _ in chosen):
                continue
            chosen.append((offset, window))
            if len(chosen) >= 5:
                break
        return tuple(chosen)

    @staticmethod
    def _badge_flags_form_prefix(eventwork: bytes) -> bool:
        """En la historia normal las medallas se obtienen en orden 1..8."""
        values = [parse_oras_event_flag(eventwork, flag) for flag in ORAS_BADGE_RECEIVED_FLAGS]
        if any(value is None for value in values):
            return False
        seen_false = False
        for value in values:
            if not value:
                seen_false = True
            elif seen_false:
                return False
        return True

    def _locate_eventwork_base(
        self,
        client: AzaharRPCClient,
        process: AzaharProcess,
        saved_eventwork: bytes,
    ) -> int | None:
        """Localiza la copia viva de EventWork sin depender de Misc/mochila."""
        process_key = (int(process.title_id), str(process.name))
        cached = self._eventwork_bases_by_process.get(process_key)
        if cached is not None:
            try:
                raw = bytes(client.read_memory(cached, ORAS_SAVE_EVENTWORK_SIZE))
            except (AzaharRPCError, OSError, ValueError):
                raw = b""
            # La base cacheada se valida con huella relajada para tolerar que la
            # historia avance; no se desempata por número de medallas.
            if self._eventwork_candidate_score(raw, saved_eventwork, relaxed=True) is not None:
                return cached
            self._eventwork_bases_by_process.pop(process_key, None)

        candidates: dict[int, bytes] = {}
        scan_start = (ORAS_EVENTWORK_SCAN_START + 3) & ~3
        overlap = ORAS_SAVE_EVENTWORK_SIZE + 16

        # Ruta principal: buscar varias ventanas del EventWork guardado. Aunque
        # ``main`` esté atrasado, la mayor parte del progreso previo permanece.
        anchors = self._eventwork_anchors(saved_eventwork)
        for block_address in range(scan_start, ORAS_EVENTWORK_SCAN_END, ORAS_EVENTWORK_SCAN_BLOCK_SIZE):
            block_size = min(ORAS_EVENTWORK_SCAN_BLOCK_SIZE, ORAS_EVENTWORK_SCAN_END - block_address)
            try:
                raw_block = bytes(client.read_memory(block_address, block_size + overlap))
            except (AzaharRPCError, OSError, ValueError):
                continue
            for anchor_offset, pattern in anchors:
                position = raw_block.find(pattern)
                while position >= 0:
                    if position < block_size:
                        candidate_base = block_address + position - anchor_offset
                        if 0x08000000 <= candidate_base < 0x0A000000 and candidate_base % 4 == 0:
                            start = candidate_base - block_address
                            if 0 <= start and start + ORAS_SAVE_EVENTWORK_SIZE <= len(raw_block):
                                candidate = bytes(raw_block[start:start + ORAS_SAVE_EVENTWORK_SIZE])
                            else:
                                try:
                                    candidate = bytes(client.read_memory(candidate_base, ORAS_SAVE_EVENTWORK_SIZE))
                                except (AzaharRPCError, OSError, ValueError):
                                    candidate = b""
                            if self._eventwork_candidate_score(candidate, saved_eventwork) is not None:
                                candidates[candidate_base] = candidate
                    position = raw_block.find(pattern, position + 1)

            # Fallback específico para partidas muy por delante de ``main``:
            # los ocho flags Received Badge forman dos bytes consecutivos. El
            # primero solo usa el bit 7 (Stone) y el segundo los bits 0..6
            # (Knuckle..Rain). Buscamos ese patrón 1..N y después exigimos la
            # huella EventWork relajada para descartar coincidencias fortuitas.
            cluster_offset = ORAS_EVENTWORK_FLAG_OFFSET + (ORAS_BADGE_RECEIVED_FLAGS[0] >> 3)  # 0x3F0
            cluster_width = 2
            limit = min(block_size, max(0, len(raw_block) - cluster_width + 1))
            for position in range(0, limit):
                candidate_base = block_address + position - cluster_offset
                if candidate_base % 4 or not (0x08000000 <= candidate_base < 0x0A000000):
                    continue
                b0, b1 = raw_block[position:position + cluster_width]
                badge_bits = (
                    bool(b0 & 0x80),       # 0x807 Stone
                    bool(b1 & 0x01),       # 0x808 Knuckle
                    bool(b1 & 0x02),       # 0x809 Dynamo
                    bool(b1 & 0x04),       # 0x80A Heat
                    bool(b1 & 0x08),       # 0x80B Balance
                    bool(b1 & 0x10),       # 0x80C Feather
                    bool(b1 & 0x20),       # 0x80D Mind
                    bool(b1 & 0x40),       # 0x80E Rain
                )
                if not badge_bits[0]:
                    continue
                first_false = next((i for i, value in enumerate(badge_bits) if not value), len(badge_bits))
                if any(badge_bits[first_false:]):
                    continue
                start = candidate_base - block_address
                if 0 <= start and start + ORAS_SAVE_EVENTWORK_SIZE <= len(raw_block):
                    candidate = bytes(raw_block[start:start + ORAS_SAVE_EVENTWORK_SIZE])
                else:
                    try:
                        candidate = bytes(client.read_memory(candidate_base, ORAS_SAVE_EVENTWORK_SIZE))
                    except (AzaharRPCError, OSError, ValueError):
                        continue
                if not self._badge_flags_form_prefix(candidate):
                    continue
                if self._eventwork_candidate_score(candidate, saved_eventwork, relaxed=True) is not None:
                    candidates.setdefault(candidate_base, candidate)

        ranked: list[tuple[tuple[int, int], int]] = []
        for base, raw in candidates.items():
            score = self._eventwork_candidate_score(raw, saved_eventwork, relaxed=True)
            if score is not None:
                matches, badge_count = score
                # Alpha.37 devolvía ``(matches, badge_count)`` directamente al
                # sort. Eso elegía antes una copia vieja idéntica a ``main``
                # que la copia activa con más progreso. En la calibración
                # inicial la progresión de medallas es la señal temporal fuerte;
                # la similitud con main solo desempata entre copias equivalentes.
                ranked.append(((badge_count, matches), base))
        if not ranked:
            return None
        ranked.sort(reverse=True)
        _score, best_base = ranked[0]
        self._eventwork_bases_by_process[process_key] = best_base
        return best_base

    def _read_badges_from_eventwork(
        self,
        client: AzaharRPCClient,
        process: AzaharProcess,
        saved_eventwork: bytes,
    ) -> int | None:
        base = self._locate_eventwork_base(client, process, saved_eventwork)
        if base is None:
            return None
        try:
            first = bytes(client.read_memory(base, ORAS_SAVE_EVENTWORK_SIZE))
            if self.reader.stable_delay:
                time.sleep(self.reader.stable_delay)
            second = bytes(client.read_memory(base, ORAS_SAVE_EVENTWORK_SIZE))
        except (AzaharRPCError, OSError, ValueError):
            return None
        if first != second:
            return None
        return count_oras_received_badges(second)

    @staticmethod
    def _subevent_magic(saved_subevent: bytes | None) -> bytes:
        """Obtiene la firma repetida del bloque SUBE sin depender del ``main``.

        Si el guardado contiene cinco cabeceras coherentes, reutilizamos esos
        bytes. Si el ``main`` está viejo/truncado o esa zona no es utilizable,
        la estructura de ORAS tiene una firma estable ``SUBE`` y el localizador
        puede trabajar igualmente solo contra RAM.
        """
        if saved_subevent is not None and len(saved_subevent) == ORAS_SAVE_SUBEVENT_SIZE:
            markers = tuple(
                bytes(saved_subevent[offset:offset + 4])
                for offset in ORAS_SUBEVENT_MAGIC_OFFSETS
            )
            if markers and all(marker == ORAS_SUBEVENT_MAGIC for marker in markers):
                return ORAS_SUBEVENT_MAGIC
        return ORAS_SUBEVENT_MAGIC

    @staticmethod
    def _subevent_fingerprint_positions(saved_subevent: bytes | None) -> tuple[int, ...]:
        """Testigos secundarios para desempatar copias SUBE antiguas/activas.

        La validación fuerte son las cinco firmas estructurales; esta huella no
        puede rechazar un candidato porque una sesión viva puede ir muy por
        delante del último guardado. Solo ayuda a ordenar copias equivalentes.
        """
        if saved_subevent is None or len(saved_subevent) != ORAS_SAVE_SUBEVENT_SIZE:
            return ()
        dynamic = set(range(0x00, 0xC0))  # rematches + historial de gimnasios
        dynamic.update(range(0x29C, 0x2A0))  # récord de Cycling Road
        dynamic.update(range(0x2F8, ORAS_SAVE_SUBEVENT_SIZE))  # ending scroll
        for offset in ORAS_SUBEVENT_MAGIC_OFFSETS:
            dynamic.update(range(offset, offset + 4))
        candidates = [
            index for index, value in enumerate(saved_subevent)
            if index not in dynamic and value != 0
        ]
        if len(candidates) <= 48:
            return tuple(candidates)
        step = max(1, len(candidates) // 48)
        return tuple(candidates[::step][:48])

    @classmethod
    def _subevent_candidate_score(
        cls,
        raw: bytes,
        saved_subevent: bytes | None,
        marker: bytes,
    ) -> tuple[int, int] | None:
        if len(raw) != ORAS_SAVE_SUBEVENT_SIZE:
            return None
        if len(marker) != 4:
            return None
        if any(bytes(raw[offset:offset + 4]) != marker for offset in ORAS_SUBEVENT_MAGIC_OFFSETS):
            return None
        badge_count = count_oras_badge_victories(raw)
        if badge_count is None:
            return None
        positions = cls._subevent_fingerprint_positions(saved_subevent)
        matches = sum(raw[pos] == saved_subevent[pos] for pos in positions)
        # La progresión es la señal temporal: una copia de 8 debe ganar frente a
        # una copia stale de 0 aunque esta última sea idéntica al main.
        return int(badge_count), int(matches)

    def _locate_subevent_base(
        self,
        client: AzaharRPCClient,
        process: AzaharProcess,
        saved_subevent: bytes | None,
    ) -> int | None:
        """Localiza el historial vivo de gimnasios mediante firmas SUBE.

        A diferencia de alpha.35-38, no busca ni el byte de medallas ni EventWork.
        El formato SUBE contiene cinco cabeceras repetidas a distancias fijas y
        un historial de 8x6 especies, una combinación suficientemente específica
        para localizar el bloque de forma independiente en el heap de ORAS.
        """
        marker = self._subevent_magic(saved_subevent)
        process_key = (int(process.title_id), str(process.name))
        cached = self._subevent_bases_by_process.get(process_key)
        if cached is not None:
            try:
                raw = bytes(client.read_memory(cached, ORAS_SAVE_SUBEVENT_SIZE))
            except (AzaharRPCError, OSError, ValueError):
                raw = b""
            # La base cacheada se conserva incluso si el número baja tras cargar
            # un state; solo exigimos que siga siendo el mismo tipo de bloque.
            if self._subevent_candidate_score(raw, saved_subevent, marker) is not None:
                return cached
            self._subevent_bases_by_process.pop(process_key, None)

        # Si una pasada completa no encontró el bloque, no repetimos varios MiB
        # de RPC cada ~1 s. SUBE existe durante toda la partida, así que esperar
        # unos segundos no compromete la detección en tiempo real y evita stutter.
        last_failed = self._subevent_failed_scan_at.get(process_key)
        if last_failed is not None and (time.monotonic() - last_failed) < 8.0:
            return None

        first_magic_offset = ORAS_SUBEVENT_MAGIC_OFFSETS[0]
        candidates: dict[int, tuple[tuple[int, int], bytes]] = {}

        for range_index, (range_start, range_end) in enumerate(ORAS_SUBEVENT_SCAN_RANGES):
            if range_end <= range_start:
                continue
            overlap = ORAS_SAVE_SUBEVENT_SIZE + 8
            for block_address in range(range_start, range_end, ORAS_SUBEVENT_SCAN_BLOCK_SIZE):
                block_size = min(ORAS_SUBEVENT_SCAN_BLOCK_SIZE, range_end - block_address)
                try:
                    raw_block = bytes(client.read_memory(block_address, block_size + overlap))
                except (AzaharRPCError, OSError, ValueError):
                    continue
                position = raw_block.find(marker)
                while position >= 0:
                    if position < block_size:
                        candidate_base = block_address + position - first_magic_offset
                        if candidate_base % 4 == 0 and 0x08000000 <= candidate_base < 0x0A000000:
                            start = candidate_base - block_address
                            if 0 <= start and start + ORAS_SAVE_SUBEVENT_SIZE <= len(raw_block):
                                candidate = bytes(raw_block[start:start + ORAS_SAVE_SUBEVENT_SIZE])
                            else:
                                try:
                                    candidate = bytes(client.read_memory(candidate_base, ORAS_SAVE_SUBEVENT_SIZE))
                                except (AzaharRPCError, OSError, ValueError):
                                    candidate = b""
                            score = self._subevent_candidate_score(candidate, saved_subevent, marker)
                            if score is not None:
                                candidates[candidate_base] = (score, candidate)
                    position = raw_block.find(marker, position + 1)

            # La zona primaria ya es la que contiene las estructuras runtime
            # conocidas de ORAS. Si encontramos SUBE ahí, no castigamos cada tick
            # inicial con varios MiB adicionales de RPC.
            if candidates and range_index == 0:
                break

        if not candidates:
            self._subevent_failed_scan_at[process_key] = time.monotonic()
            return None
        ranked = sorted(
            ((score, base) for base, (score, _raw) in candidates.items()),
            reverse=True,
        )
        _best_score, best_base = ranked[0]
        self._subevent_bases_by_process[process_key] = best_base
        self._subevent_failed_scan_at.pop(process_key, None)
        return best_base

    def _read_badges_from_subevent(
        self,
        client: AzaharRPCClient,
        process: AzaharProcess,
        saved_subevent: bytes | None,
    ) -> int | None:
        base = self._locate_subevent_base(client, process, saved_subevent)
        if base is None:
            return None
        try:
            first = bytes(client.read_memory(base, ORAS_SAVE_SUBEVENT_SIZE))
            if self.reader.stable_delay:
                time.sleep(self.reader.stable_delay)
            second = bytes(client.read_memory(base, ORAS_SAVE_SUBEVENT_SIZE))
        except (AzaharRPCError, OSError, ValueError):
            return None
        if first != second:
            return None
        return count_oras_badge_victories(second)

    @staticmethod
    def _misc_fingerprint_positions(saved_misc: bytes) -> tuple[int, ...]:
        """Selecciona bytes estables/no triviales para validar un bloque Misc.

        Se excluyen Money, Badges y BP porque pueden cambiar durante la sesión.
        Vivillon sí es un buen testigo. Priorizamos bytes no nulos para no
        aceptar por accidente una gran zona de RAM a cero.
        """
        dynamic = set(range(ORAS_MISC_MONEY_OFFSET, ORAS_MISC_BADGES_OFFSET + 1))
        dynamic.update(range(ORAS_MISC_BP_OFFSET, ORAS_MISC_BP_OFFSET + 2))
        candidates = [
            i for i, value in enumerate(saved_misc)
            if i not in dynamic and value != 0
        ]
        # Reparte los testigos por todo el bloque; 24 bytes bastan y evitan
        # convertir cada tick en una comparación grande.
        if len(candidates) <= 24:
            return tuple(candidates)
        step = max(1, len(candidates) // 24)
        result = tuple(candidates[::step][:24])
        return result

    @classmethod
    def _misc_candidate_matches(cls, raw: bytes, saved_misc: bytes, *, initial: bool = False) -> bool:
        """Valida que una región se parece al bloque Misc de esta partida.

        ``Badges`` NO participa en la huella. Una copia de ``main`` puede estar
        varias medallas por detrás del juego vivo; exigir igualdad fue el motivo
        por el que alpha.35 podía seleccionar/rechazar precisamente la copia que
        queríamos encontrar.
        """
        if len(raw) != ORAS_SAVE_MISC_SIZE or len(saved_misc) != ORAS_SAVE_MISC_SIZE:
            return False
        if parse_oras_badges(raw[ORAS_MISC_BADGES_OFFSET:ORAS_MISC_BADGES_OFFSET + 1]) is None:
            return False
        positions = cls._misc_fingerprint_positions(saved_misc)
        if not positions:
            return False
        matches = sum(raw[pos] == saved_misc[pos] for pos in positions)
        required = max(4, (len(positions) * 3 + 3) // 4)
        return matches >= required

    @classmethod
    def _misc_candidate_score(
        cls,
        raw: bytes,
        saved_misc: bytes,
        *,
        live_money: int | None,
        live_bp: int | None,
    ) -> tuple[int, int, int] | None:
        """Puntúa copias Misc candidatas sin depender de un ``main`` al día.

        Money/BP tienen direcciones runtime conocidas en ORAS 1.4 y sirven como
        testigos de qué copia está activa. El número de medallas se usa solo como
        desempate final: en una partida normal es monotónico y permite distinguir
        una copia vieja de 0 frente a la activa de 8 cuando el resto del bloque es
        idéntico. Una vez calibrada una base, se conserva y el contador puede
        bajar también tras un state-load porque ya no se vuelve a elegir por ese
        desempate.
        """
        if not cls._misc_candidate_matches(raw, saved_misc):
            return None
        positions = cls._misc_fingerprint_positions(saved_misc)
        matches = sum(raw[pos] == saved_misc[pos] for pos in positions)
        badge = parse_oras_badges(raw[ORAS_MISC_BADGES_OFFSET:ORAS_MISC_BADGES_OFFSET + 1])
        assert badge is not None
        score = matches * 10
        reference_hits = 0
        try:
            candidate_money = struct.unpack_from("<I", raw, ORAS_MISC_MONEY_OFFSET)[0]
            candidate_bp = struct.unpack_from("<H", raw, ORAS_MISC_BP_OFFSET)[0]
        except struct.error:
            return None
        if live_money is not None and candidate_money == live_money:
            score += 1000
            reference_hits += 1
        if live_bp is not None and candidate_bp == live_bp:
            score += 300
            reference_hits += 1
        # tuple lexicográfica: referencias runtime > huella > progresión.
        return reference_hits, score, int(badge)

    @staticmethod
    def _misc_anchor(saved_misc: bytes) -> tuple[int, bytes] | None:
        """Devuelve una ventana estable y con entropía para barrer RAM rápido."""
        dynamic = set(range(ORAS_MISC_MONEY_OFFSET, ORAS_MISC_BADGES_OFFSET + 1))
        dynamic.update(range(ORAS_MISC_BP_OFFSET, ORAS_MISC_BP_OFFSET + 2))
        best: tuple[int, int, bytes] | None = None
        width = 12
        for offset in range(0, len(saved_misc) - width + 1):
            if any(index in dynamic for index in range(offset, offset + width)):
                continue
            window = bytes(saved_misc[offset:offset + width])
            nonzero = sum(value != 0 for value in window)
            distinct = len(set(window))
            score = nonzero * 4 + distinct
            if nonzero < 5:
                continue
            if best is None or score > best[0]:
                best = (score, offset, window)
        if best is None:
            return None
        return best[1], best[2]

    @staticmethod
    def _live_misc_references(client: AzaharRPCClient) -> tuple[int | None, int | None]:
        """Lee Money/BP runtime como testigos; nunca falla la lectura de medallas."""
        money: int | None = None
        bp: int | None = None
        try:
            raw = client.read_memory(ORAS_MONEY_ADDRESS, 4)
            value = struct.unpack("<I", bytes(raw))[0]
            if 0 <= value <= ORAS_MAX_MONEY:
                money = int(value)
        except (AzaharRPCError, OSError, ValueError, struct.error):
            pass
        # PKHeX sitúa BP a +0x28 respecto a Money dentro de Misc, y los códigos
        # runtime de ORAS 1.4 usan exactamente 0x08C71DE8 para este valor.
        try:
            raw = client.read_memory(ORAS_MONEY_ADDRESS + (ORAS_MISC_BP_OFFSET - ORAS_MISC_MONEY_OFFSET), 2)
            value = struct.unpack("<H", bytes(raw))[0]
            if 0 <= value <= 65535:
                bp = int(value)
        except (AzaharRPCError, OSError, ValueError, struct.error):
            pass
        return money, bp

    def _locate_misc_base(
        self,
        client: AzaharRPCClient,
        process: AzaharProcess,
        saved_misc: bytes,
    ) -> int | None:
        process_key = (int(process.title_id), str(process.name))
        cached = self._misc_bases_by_process.get(process_key)
        if cached is not None:
            try:
                raw = client.read_memory(cached, ORAS_SAVE_MISC_SIZE)
            except (AzaharRPCError, OSError, ValueError):
                raw = b""
            if self._misc_candidate_matches(bytes(raw), saved_misc):
                return cached
            self._misc_bases_by_process.pop(process_key, None)

        live_money, live_bp = self._live_misc_references(client)
        candidates: dict[int, bytes] = {}

        # La dirección histórica sigue siendo un candidato, nunca una verdad.
        static_base = ORAS_MONEY_ADDRESS - ORAS_MISC_MONEY_OFFSET
        try:
            raw = bytes(client.read_memory(static_base, ORAS_SAVE_MISC_SIZE))
        except (AzaharRPCError, OSError, ValueError):
            raw = b""
        if self._misc_candidate_matches(raw, saved_misc):
            candidates[static_base] = raw

        anchor = self._misc_anchor(saved_misc)
        if anchor is not None:
            anchor_offset, pattern = anchor
            scan_start = (ORAS_MISC_SCAN_START + 3) & ~3
            overlap = ORAS_SAVE_MISC_SIZE + len(pattern)
            for block_address in range(scan_start, ORAS_MISC_SCAN_END, ORAS_MISC_SCAN_BLOCK_SIZE):
                block_size = min(ORAS_MISC_SCAN_BLOCK_SIZE, ORAS_MISC_SCAN_END - block_address)
                try:
                    raw_block = client.read_memory(block_address, block_size + overlap)
                except (AzaharRPCError, OSError, ValueError):
                    continue
                position = raw_block.find(pattern)
                while position >= 0:
                    if position < block_size:
                        candidate_base = block_address + position - anchor_offset
                        if 0x08000000 <= candidate_base < 0x0A000000:
                            start = candidate_base - block_address
                            if 0 <= start and start + ORAS_SAVE_MISC_SIZE <= len(raw_block):
                                candidate = bytes(raw_block[start:start + ORAS_SAVE_MISC_SIZE])
                            else:
                                try:
                                    candidate = bytes(client.read_memory(candidate_base, ORAS_SAVE_MISC_SIZE))
                                except (AzaharRPCError, OSError, ValueError):
                                    candidate = b""
                            if self._misc_candidate_matches(candidate, saved_misc):
                                candidates[candidate_base] = candidate
                    position = raw_block.find(pattern, position + 1)

        # Fallback de calibración: si la huella del ``main`` está demasiado
        # desfasada para encontrar la copia viva, usamos el dinero runtime como
        # ancla. Buscamos regiones con ese mismo Money en +0x08 y BP en +0x30;
        # luego exigimos un contador de medallas válido. Esto sigue siendo solo
        # lectura y evita depender de haber guardado recientemente.
        if live_money is not None and len(candidates) <= 1:
            money_pattern = struct.pack("<I", int(live_money))
            scan_start = (ORAS_MISC_SCAN_START + 3) & ~3
            overlap = ORAS_SAVE_MISC_SIZE + 4
            for block_address in range(scan_start, ORAS_MISC_SCAN_END, ORAS_MISC_SCAN_BLOCK_SIZE):
                block_size = min(ORAS_MISC_SCAN_BLOCK_SIZE, ORAS_MISC_SCAN_END - block_address)
                try:
                    raw_block = client.read_memory(block_address, block_size + overlap)
                except (AzaharRPCError, OSError, ValueError):
                    continue
                position = raw_block.find(money_pattern)
                while position >= 0:
                    if position < block_size:
                        candidate_base = block_address + position - ORAS_MISC_MONEY_OFFSET
                        start = candidate_base - block_address
                        if 0x08000000 <= candidate_base < 0x0A000000:
                            if 0 <= start and start + ORAS_SAVE_MISC_SIZE <= len(raw_block):
                                candidate = bytes(raw_block[start:start + ORAS_SAVE_MISC_SIZE])
                            else:
                                try:
                                    candidate = bytes(client.read_memory(candidate_base, ORAS_SAVE_MISC_SIZE))
                                except (AzaharRPCError, OSError, ValueError):
                                    candidate = b""
                            badge = (
                                parse_oras_badges(candidate[ORAS_MISC_BADGES_OFFSET:ORAS_MISC_BADGES_OFFSET + 1])
                                if len(candidate) == ORAS_SAVE_MISC_SIZE else None
                            )
                            if badge is not None:
                                try:
                                    candidate_bp = struct.unpack_from("<H", candidate, ORAS_MISC_BP_OFFSET)[0]
                                except struct.error:
                                    candidate_bp = -1
                                if live_bp is None or candidate_bp == live_bp:
                                    # Si la huella clásica ya casa, se puntúa
                                    # normalmente. Si no, guardamos igualmente el
                                    # candidato con Money/BP confirmados y lo
                                    # puntuaremos mediante una huella relajada.
                                    candidates.setdefault(candidate_base, candidate)
                    position = raw_block.find(money_pattern, position + 1)

        ranked: list[tuple[tuple[int, int, int], int]] = []
        for base, raw in candidates.items():
            score = self._misc_candidate_score(
                raw, saved_misc, live_money=live_money, live_bp=live_bp,
            )
            if score is None and len(raw) == ORAS_SAVE_MISC_SIZE:
                # Candidato de fallback anclado por Money/BP runtime. No exigimos
                # 75 % de la huella del main, pero sí contamos coincidencias para
                # desempatar entre copias de la misma estructura.
                badge = parse_oras_badges(raw[ORAS_MISC_BADGES_OFFSET:ORAS_MISC_BADGES_OFFSET + 1])
                try:
                    candidate_money = struct.unpack_from("<I", raw, ORAS_MISC_MONEY_OFFSET)[0]
                    candidate_bp = struct.unpack_from("<H", raw, ORAS_MISC_BP_OFFSET)[0]
                except struct.error:
                    continue
                money_hit = live_money is not None and candidate_money == live_money
                bp_hit = live_bp is not None and candidate_bp == live_bp
                if badge is not None and money_hit and (live_bp is None or bp_hit):
                    positions = self._misc_fingerprint_positions(saved_misc)
                    matches = sum(raw[pos] == saved_misc[pos] for pos in positions)
                    # Money/BP solos pueden aparecer en estructuras auxiliares.
                    # Exigimos al menos una porción de la huella Misc para que el
                    # fallback no convierta una región casi vacía en candidato.
                    minimum_relaxed = max(2, len(positions) // 12)
                    if matches < minimum_relaxed:
                        continue
                    score = (1 + int(bp_hit), 900 + matches * 10, int(badge))
            if score is not None:
                ranked.append((score, base))
        if not ranked:
            return None
        ranked.sort(reverse=True)
        best_score, best_base = ranked[0]
        self._misc_bases_by_process[process_key] = best_base
        return best_base

    @staticmethod
    def _read_stable_tm_pouch_at(client: AzaharRPCClient, address: int, delay: float) -> bytes | None:
        try:
            first = bytes(client.read_memory(int(address), ORAS_TM_POUCH_SIZE))
            if delay:
                time.sleep(delay)
            second = bytes(client.read_memory(int(address), ORAS_TM_POUCH_SIZE))
        except (AzaharRPCError, OSError, ValueError):
            return None
        return second if first == second else None

    @staticmethod
    def _tm_pouch_badge_score(raw: bytes) -> tuple[int, int] | None:
        try:
            items = parse_oras_tm_hm_pocket(raw)
        except ORASLiveError:
            return None
        badge_count = count_oras_gym_reward_items(items)
        if badge_count is None:
            return None
        # Más medallas gana; para dos copias con el mismo progreso, la que
        # contiene más MT/MO adquiridas suele ser la estructura viva completa.
        return int(badge_count), int(len(items))

    def _locate_tm_badge_pouch_base(
        self,
        client: AzaharRPCClient,
        process: AzaharProcess,
    ) -> int | None:
        """Localiza la mochila TM/MO mediante el resolver común del Core.

        0.2.1-alpha.2 conserva el algoritmo probado de ORAS, pero extrae las
        reglas universales (validar caché -> probar candidatos -> barrer ->
        puntuar -> cachear -> cooldown) a ``LiveBlockResolver``. Los siguientes
        juegos solo tendrán que aportar sus firmas/validadores.
        """
        process_key = (int(process.title_id), str(process.name))
        block_key = "inventory.tm_hm"

        # Importa cachés legacy para que actualizar desde alpha.45/alpha.1 no
        # cambie de dirección innecesariamente. Resolver vuelve a validarla.
        legacy = self._tm_badge_bases_by_process.get(process_key)
        if legacy is not None and self.block_resolver.cached_address(process_key, block_key) is None:
            self.block_resolver.prime(process_key, block_key, int(legacy))

        preferred: list[MemoryCandidateHint] = []
        cached_delta = self._inventory_deltas_by_process.get(process_key)
        if cached_delta is not None:
            preferred.append(MemoryCandidateHint(
                _pouch_address("tms", int(cached_delta)), "inventory-layout", 300,
            ))
        preferred.append(MemoryCandidateHint(ORAS_TM_POUCH_ADDRESS, "nominal", 100))

        def read_at(address: int) -> bytes | None:
            return self._read_stable_tm_pouch_at(client, int(address), self.reader.stable_delay)

        def discover():
            anchor_item = ORAS_GYM_REWARD_ITEM_IDS[0]
            anchor_pattern = struct.pack("<H", anchor_item)
            overlap = ORAS_TM_POUCH_SIZE + ORAS_ITEM_RECORD_SIZE
            found: set[int] = set()
            for block_address in range(
                ORAS_TM_BADGE_SCAN_START, ORAS_TM_BADGE_SCAN_END, ORAS_TM_BADGE_SCAN_BLOCK_SIZE
            ):
                block_size = min(ORAS_TM_BADGE_SCAN_BLOCK_SIZE, ORAS_TM_BADGE_SCAN_END - block_address)
                try:
                    raw_block = bytes(client.read_memory(block_address, block_size + overlap))
                except (AzaharRPCError, OSError, ValueError):
                    continue
                position = raw_block.find(anchor_pattern)
                while position >= 0:
                    if position < block_size:
                        for slot in range(ORAS_TM_POUCH_SIZE // ORAS_ITEM_RECORD_SIZE):
                            start = position - slot * ORAS_ITEM_RECORD_SIZE
                            if start < 0 or start + ORAS_TM_POUCH_SIZE > len(raw_block):
                                continue
                            candidate_base = block_address + start
                            if candidate_base & 3 or candidate_base in found:
                                continue
                            candidate = bytes(raw_block[start:start + ORAS_TM_POUCH_SIZE])
                            if self._tm_pouch_badge_score(candidate) is not None:
                                found.add(candidate_base)
                                yield MemoryCandidateHint(candidate_base, "scan:TM39", 0)
                    position = raw_block.find(anchor_pattern, position + 1)

        resolution = self.block_resolver.resolve(
            block_key, process_key,
            read_at=read_at, validate=self._tm_pouch_badge_score,
            preferred=tuple(preferred), discover=discover, failure_cooldown=8.0,
        )
        if not resolution.success or resolution.address is None:
            # Espejo legacy del cooldown para no romper herramientas/tests que
            # todavía observan este dato directamente.
            if resolution.source in {"scan", "scan-error", "cooldown"}:
                self._tm_badge_failed_scan_at[process_key] = time.monotonic()
            return None

        base = int(resolution.address)
        self._tm_badge_bases_by_process[process_key] = base
        self._tm_badge_failed_scan_at.pop(process_key, None)
        return base

    def _read_badges_from_gym_rewards(
        self,
        client: AzaharRPCClient,
        process: AzaharProcess,
    ) -> int | None:
        base = self._locate_tm_badge_pouch_base(client, process)
        if base is None:
            return None
        process_key = (int(process.title_id), str(process.name))
        # La copia que demuestra las medallas es también la mejor prueba de qué
        # bolsillo MT/MO está vivo. El selector de MT reutiliza esta dirección.
        self._tm_inventory_bases_by_process[process_key] = int(base)
        raw = self._read_stable_tm_pouch_at(client, base, self.reader.stable_delay)
        if raw is None:
            return None
        try:
            items = parse_oras_tm_hm_pocket(raw)
        except ORASLiveError:
            return None
        return count_oras_gym_reward_items(items)

    @staticmethod
    def _tm_inventory_candidate_score(
        raw: bytes,
        saved_items: Mapping[int, int] | None = None,
    ) -> tuple[int, int, int] | None:
        """Puntúa una copia candidata del bolsillo MT/MO.

        Las MT/MO de Gen 6 no se consumen, así que una copia viva normal nunca
        debería contener menos progreso persistente que una copia antigua salvo
        que el jugador haya cargado un state anterior. Por eso la dirección ya
        cacheada tiene prioridad; este score se usa para validar y desempatar.
        """
        try:
            items = parse_oras_tm_hm_pocket(raw)
        except ORASLiveError:
            return None
        saved = {
            int(item_id): int(quantity)
            for item_id, quantity in dict(saved_items or {}).items()
            if int(item_id) in ORAS_TM_HM_ITEM_IDS and int(quantity) > 0
        }
        overlap = sum(1 for item_id in saved if int(item_id) in items)
        badge_count = count_oras_gym_reward_items(items)
        return overlap, int(badge_count if badge_count is not None else -1), len(items)

    def _locate_tm_inventory_pouch_base(
        self,
        client: AzaharRPCClient,
        process: AzaharProcess,
        saved_items: Mapping[int, int] | None = None,
    ) -> int:
        """Resuelve la mochila MT/MO viva usando la misma caché común.

        Una dirección ya cacheada se conserva mientras siga parseando como una
        mochila válida, incluso después de cargar un state anterior. En una
        calibración inicial, la huella del ``main`` ayuda a desempatar copias.
        """
        process_key = (int(process.title_id), str(process.name))
        block_key = "inventory.tm_hm"

        # Cualquier caché previa de alpha.45 se importa una sola vez. La caché
        # de medallas tiene prioridad porque ya demostró que la estructura es
        # viva; ambas rutas terminan compartiendo el mismo bloque.
        for legacy in (
            self._tm_inventory_bases_by_process.get(process_key),
            self._tm_badge_bases_by_process.get(process_key),
        ):
            if legacy is not None and self.block_resolver.cached_address(process_key, block_key) is None:
                self.block_resolver.prime(process_key, block_key, int(legacy))
                break

        saved_count = sum(
            1 for item_id, quantity in dict(saved_items or {}).items()
            if int(item_id) in ORAS_TM_HM_ITEM_IDS and int(quantity) > 0
        )

        def validate(raw: bytes) -> tuple[int, int, int] | None:
            score = self._tm_inventory_candidate_score(raw, saved_items)
            if score is None:
                return None
            overlap, badges, item_count = score
            # En la calibración inicial una copia sin ninguna coincidencia con
            # un main que ya contiene MTs es sospechosa. La ruta cacheada del
            # resolver se valida con esta misma función, pero al cargar states
            # las MT de Gen 6 persisten y normalmente sigue habiendo overlap.
            if saved_count and overlap <= 0:
                return None
            return int(overlap), int(badges), int(item_count)

        def read_at(address: int) -> bytes | None:
            return self._read_stable_tm_pouch_at(client, int(address), self.reader.stable_delay)

        preferred: list[MemoryCandidateHint] = []
        badge_legacy = self._tm_badge_bases_by_process.get(process_key)
        if badge_legacy is not None:
            preferred.append(MemoryCandidateHint(int(badge_legacy), "badges-cache", 350))
        cached_delta = self._inventory_deltas_by_process.get(process_key)
        if cached_delta is not None:
            preferred.append(MemoryCandidateHint(_pouch_address("tms", int(cached_delta)), "inventory-layout", 300))
        preferred.append(MemoryCandidateHint(ORAS_TM_POUCH_ADDRESS, "nominal", 100))

        resolution = self.block_resolver.resolve(
            block_key, process_key, read_at=read_at, validate=validate,
            preferred=tuple(preferred), discover=None, failure_cooldown=0.0,
        )
        if resolution.success and resolution.address is not None:
            base = int(resolution.address)
            self._tm_inventory_bases_by_process[process_key] = base
            self._tm_badge_bases_by_process.setdefault(process_key, base)
            return base

        # Si todavía no existe caché válida, el localizador de premios aporta el
        # barrido caro y comparte su resultado con este mismo block_key.
        badge_base = self._locate_tm_badge_pouch_base(client, process)
        if badge_base is not None:
            self._tm_inventory_bases_by_process[process_key] = int(badge_base)
            return int(badge_base)

        raise ORASLiveError(
            "No se pudo localizar la mochila MT/MO viva de ORAS. RoleRun no usará una copia vacía o antigua de RAM."
        )

    def read_tm_inventory(
        self,
        saved_items: Mapping[int, int] | None = None,
    ) -> tuple[dict[int, int], AzaharProcess, int]:
        """Lee las MT/MO de la misma mochila viva validada por alpha.41+."""
        try:
            with self.reader.client_factory() as client:
                process = self.reader._find_oras_process(client.process_list())
                client.set_process(process.process_id)
                base = self._locate_tm_inventory_pouch_base(
                    client, process, saved_items=saved_items,
                )
                for attempt in range(1, self.reader.snapshot_attempts + 1):
                    raw = self._read_stable_tm_pouch_at(
                        client, base, self.reader.stable_delay,
                    )
                    if raw is None:
                        continue
                    return parse_oras_tm_hm_pocket(raw), process, attempt
        except AzaharRPCError as exc:
            raise ORASLiveError(str(exc)) from exc
        raise ORASLiveError(
            "Las MT/MO cambiaron durante todas las lecturas. Cierra la mochila del juego y vuelve a intentarlo."
        )

    def read_badges(
        self,
        save_path: Path | str | None,
        inventory_witnesses: Sequence[tuple[str, int, int, int]] = (),
    ) -> int | None:
        """Lee medallas priorizando los premios persistentes de cada gimnasio.

        Alpha.41 usa como primera señal la mochila MT/MO viva, una estructura que
        RoleRun ya necesita para enseñar movimientos. Cada líder entrega un
        objeto TM/HM específico junto con su medalla y esos objetos no se
        consumen en ORAS, por lo que forman un historial independiente de los
        bloques Misc/EventWork/SUBE que han resultado problemáticos en Azahar.

        SUBE, EventWork y Misc se mantienen como fallbacks.
        """
        if save_path is None:
            self._last_badge_source = None
            return None

        saved_subevent = read_oras_saved_subevent(save_path)
        saved_subevent_badges = (
            count_oras_badge_victories(saved_subevent)
            if saved_subevent is not None else None
        )
        saved_eventwork = read_oras_saved_eventwork(save_path)
        saved_event_badges = (
            count_oras_received_badges(saved_eventwork)
            if saved_eventwork is not None else None
        )
        saved_misc = read_oras_saved_misc(save_path)
        saved_misc_badges = None
        if saved_misc is not None:
            saved_misc_badges = parse_oras_badges(
                saved_misc[ORAS_MISC_BADGES_OFFSET:ORAS_MISC_BADGES_OFFSET + 1]
            )

        # Si las fuentes guardadas difieren, conservar el mayor progreso evita
        # que una representación obsoleta fuerce el contador a cero. BadgeVictory
        # es semánticamente la más fuerte, pero el max también protege saves de
        # revisiones/editores que no hayan poblado esa tabla.
        saved_candidates = [
            value for value in (saved_subevent_badges, saved_event_badges, saved_misc_badges)
            if value is not None
        ]
        saved_fallback = max(saved_candidates) if saved_candidates else None

        try:
            with self.reader.client_factory() as client:
                process = self.reader._find_oras_process(client.process_list())
                client.set_process(process.process_id)

                # Ruta alpha.41: premios físicos de los líderes en la mochila
                # TM/MO viva. Es independiente de Misc/EventWork/SUBE y reutiliza
                # una estructura que ya conocemos por el sistema de MT en vivo.
                live_reward_badges = self._read_badges_from_gym_rewards(client, process)
                if live_reward_badges is not None:
                    self._last_badge_source = "Premios líderes · MT/MO"
                    return live_reward_badges

                # Ruta alpha.39 queda como segundo detector: historial SUBE.
                live_subevent_badges = self._read_badges_from_subevent(
                    client, process, saved_subevent,
                )
                if live_subevent_badges is not None:
                    self._last_badge_source = "SUBE vivo · equipos de gimnasio"
                    return live_subevent_badges

                if saved_eventwork is not None:
                    live_event_badges = self._read_badges_from_eventwork(
                        client, process, saved_eventwork,
                    )
                    if live_event_badges is not None:
                        self._last_badge_source = "EventWork vivo · Received Badge"
                        return live_event_badges

                # Respaldo histórico: mantener el lector Misc por si una build
                # concreta no conserva EventWork de forma localizable en RAM.
                if saved_misc is not None:
                    base = self._locate_misc_base(client, process, saved_misc)
                    if base is not None:
                        address = int(base) + ORAS_MISC_BADGES_OFFSET
                        first = client.read_memory(address, 1)
                        if self.reader.stable_delay:
                            time.sleep(self.reader.stable_delay)
                        second = client.read_memory(address, 1)
                        if first == second:
                            live = parse_oras_badges(bytes(second))
                            if live is not None:
                                self._last_badge_source = "Misc vivo · contador"
                                return live
                if saved_fallback is not None:
                    if saved_subevent_badges == saved_fallback:
                        self._last_badge_source = "main · equipos de gimnasio"
                    elif saved_event_badges == saved_fallback:
                        self._last_badge_source = "main · Received Badge"
                    else:
                        self._last_badge_source = "main · contador"
                return saved_fallback
        except (ORASLiveError, AzaharRPCError, OSError, ValueError):
            if saved_fallback is not None:
                if saved_subevent_badges == saved_fallback:
                    self._last_badge_source = "main · equipos de gimnasio"
                elif saved_event_badges == saved_fallback:
                    self._last_badge_source = "main · Received Badge"
                else:
                    self._last_badge_source = "main · contador"
            return saved_fallback

    @staticmethod
    def _pocket_matches_inventory_witnesses(
        raw: bytes,
        label: str,
        witnesses: dict[int, tuple[int, int]],
    ) -> bool:
        try:
            parsed = parse_oras_item_pocket(raw, label=label)
        except ORASLiveError:
            return False
        for slot, (item_id, quantity) in witnesses.items():
            if slot >= 0:
                actual_item_id, actual_quantity = struct.unpack_from(
                    "<HH", raw, slot * ORAS_ITEM_RECORD_SIZE,
                )
                if actual_item_id != item_id or actual_quantity != quantity:
                    return False
            elif int(parsed.get(item_id, 0)) != 0:
                return False
        return True

    def _validate_inventory_witness_capture(
        self,
        captured: dict[str, bytes],
        witnesses: dict[str, dict[int, tuple[int, int]]],
    ) -> None:
        for label, entries in witnesses.items():
            raw = captured.get(f"pocket:{label}")
            if raw is None or not self._pocket_matches_inventory_witnesses(raw, label, entries):
                raise ORASLiveError(
                    "La mochila de ORAS cambió durante la calibración. Cierra la mochila del juego, pulsa F5 y vuelve a probar."
                )

    def _inventory_delta_matches(
        self,
        client: AzaharRPCClient,
        inventory_delta: int,
        witnesses: dict[str, dict[int, tuple[int, int]]],
    ) -> bool:
        """Comprueba todos los testigos en un layout candidato antes de usarlo."""
        for label, entries in witnesses.items():
            address = _pouch_address(label, inventory_delta)
            _base, size = _POUCH_LAYOUT[label]
            if not 0x08000000 <= address < 0x0A000000:
                return False
            try:
                raw = client.read_memory(address, size)
            except (AzaharRPCError, OSError, ValueError):
                return False
            if not self._pocket_matches_inventory_witnesses(raw, label, entries):
                return False
        return True

    def _scan_inventory_deltas(
        self,
        client: AzaharRPCClient,
        witnesses: dict[str, dict[int, tuple[int, int]]],
    ) -> set[int]:
        """Encuentra layouts candidatos usando varios registros de la mochila.

        Solo el primer registro se busca como bytes para acelerar el barrido;
        cada posible inicio se vuelve a parsear por completo y se contrasta con
        todos los registros del mismo bolsillo. La validación de los otros
        bolsillos sucede después, antes de aceptar cualquier dirección.
        """
        anchors = [
            (
                label,
                [
                    (slot, item_id, quantity)
                    for slot, (item_id, quantity) in entries.items()
                    if slot >= 0 and quantity > 0
                ],
            )
            for label, entries in witnesses.items()
        ]
        anchor_label, anchor_values = max(anchors, key=lambda entry: len(entry[1]))
        if len(anchor_values) < 2:
            return set()
        anchor_slot, anchor_item_id, anchor_quantity = anchor_values[0]
        anchor_pattern = struct.pack("<HH", anchor_item_id, anchor_quantity)
        static_base, pocket_size = _POUCH_LAYOUT[anchor_label]
        candidates: set[int] = set()
        scan_start = (ORAS_INVENTORY_SCAN_START + 3) & ~3

        for block_address in range(scan_start, ORAS_INVENTORY_SCAN_END, ORAS_INVENTORY_SCAN_BLOCK_SIZE):
            block_size = min(ORAS_INVENTORY_SCAN_BLOCK_SIZE, ORAS_INVENTORY_SCAN_END - block_address)
            raw_block = client.read_memory(block_address, block_size + pocket_size)
            position = raw_block.find(anchor_pattern)
            while position >= 0:
                # El patrón puede aparecer en el solape que pertenece al
                # siguiente bloque; se revisará allí con su inicio real.
                if position < block_size:
                    start = position - anchor_slot * ORAS_ITEM_RECORD_SIZE
                    if start < 0 or start >= block_size or start + pocket_size > len(raw_block):
                        position = raw_block.find(anchor_pattern, position + 1)
                        continue
                    address = block_address + start
                    if address & 3:
                        position = raw_block.find(anchor_pattern, position + 1)
                        continue
                    candidate = raw_block[start:start + pocket_size]
                    if self._pocket_matches_inventory_witnesses(
                        candidate, anchor_label, witnesses[anchor_label],
                    ):
                        delta = address - static_base
                        if all(0x08000000 <= _pouch_address(label, delta) < 0x0A000000 for label in witnesses):
                            candidates.add(delta)
                position = raw_block.find(anchor_pattern, position + 1)
        return candidates

    def _locate_inventory_delta(
        self,
        client: AzaharRPCClient,
        process: AzaharProcess,
        witnesses: dict[str, dict[int, tuple[int, int]]],
    ) -> int:
        """Localiza una única mochila activa, o se detiene sin escribir."""
        process_key = (int(process.title_id), str(process.name))
        cached = self._inventory_deltas_by_process.get(process_key)
        if cached is not None and self._inventory_delta_matches(client, cached, witnesses):
            return cached

        candidates = self._scan_inventory_deltas(client, witnesses)
        verified = [
            delta for delta in sorted(candidates)
            if self._inventory_delta_matches(client, delta, witnesses)
        ]
        if len(verified) == 1:
            selected = verified[0]
            self._inventory_deltas_by_process[process_key] = selected
            return selected
        if not verified:
            raise ORASLiveError(
                "No se pudo localizar una mochila viva de ORAS que coincida con el último guardado. "
                "Guarda normalmente dentro del juego, pulsa F5 y vuelve a probar. No se escribió ningún byte."
            )
        raise ORASLiveError(
            "Se encontraron varias copias posibles de la mochila de ORAS. RoleRun no puede elegir una de forma segura; "
            "guarda normalmente dentro del juego, pulsa F5 y vuelve a probar. No se escribió ningún byte."
        )

    @staticmethod
    def _pc_target_identity(change: PendingPCRoleChange | PendingTeamChange) -> str:
        if isinstance(change, PendingTeamChange):
            return str(change.incoming_identity or "")
        return str(change.pokemon_identity or "")

    @classmethod
    def _pc_witnesses(
        cls, change: PendingPCRoleChange | PendingTeamChange,
    ) -> tuple[tuple[int, str], ...]:
        """Normaliza los testigos de una caja sin confiar en datos ambiguos."""
        target_slot = int(change.box_slot)
        target_identity = cls._pc_target_identity(change)
        if not target_identity:
            return ()
        result: list[tuple[int, str]] = [(target_slot, target_identity)]
        seen_slots = {target_slot}
        for entry in tuple(getattr(change, "box_witnesses", ()) or ()):
            try:
                slot, identity = entry
                slot = int(slot)
                identity = str(identity or "")
            except (TypeError, ValueError):
                continue
            if not 1 <= slot <= ORAS_PC_BOX_SLOT_COUNT or not identity or slot in seen_slots:
                continue
            seen_slots.add(slot)
            result.append((slot, identity))
        return tuple(result)

    def _pc_base_matches(
        self,
        client: AzaharRPCClient,
        base_address: int,
        changes: Sequence[PendingPCRoleChange | PendingTeamChange],
        *,
        require_companion: bool,
    ) -> bool:
        """Comprueba que una base contiene exactamente los PK6 esperados.

        Una coincidencia del Pokémon objetivo por sí sola no es suficiente: una
        copia temporal de party podría contenerlo. Por eso la búsqueda dinámica
        exige una segunda identidad de la misma caja y sus offsets reales.
        """
        base_address = int(base_address)
        if not 0x08000000 <= base_address < 0x0A000000:
            return False
        for change in changes:
            witnesses = self._pc_witnesses(change)
            if not witnesses or (require_companion and len(witnesses) < 2):
                return False
            for box_slot, expected_identity in witnesses:
                try:
                    raw = client.read_memory(
                        self._box_slot_address(int(change.box), box_slot, base_address=base_address),
                        PK6_STORED_SIZE,
                    )
                    pokemon = parse_pk6_boxed(
                        raw, int(change.box), box_slot, self.reader.move_names,
                    )
                except ORASLiveError:
                    return False
                if pokemon is None or self._pokemon_identity(pokemon) != expected_identity:
                    return False
        return True

    def _scan_pc_base(
        self,
        client: AzaharRPCClient,
        changes: Sequence[PendingPCRoleChange | PendingTeamChange],
    ) -> int | None:
        """Busca una base de PC únicamente si los perfiles conocidos fallan.

        La exploración se reduce al MiB anterior a la party, donde vive el bloque
        de datos de ORAS. Antes de descifrar se exige una cabecera PK6 plausible,
        de modo que las zonas vacías no convierten esta calibración en un barrido
        costoso de RAM ni se acepta nunca una coincidencia aislada.
        """
        change = next((item for item in changes if len(self._pc_witnesses(item)) >= 2), None)
        if change is None:
            return None
        target_identity = self._pc_target_identity(change)
        target_index = (
            (int(change.box) - 1) * ORAS_PC_BOX_SLOT_COUNT
            + (int(change.box_slot) - 1)
        )
        scan_start = (ORAS_PC_SCAN_START + 3) & ~3
        for block_address in range(scan_start, ORAS_PC_SCAN_END, ORAS_PC_SCAN_BLOCK_SIZE):
            candidate_size = min(ORAS_PC_SCAN_BLOCK_SIZE, ORAS_PC_SCAN_END - block_address)
            raw_block = client.read_memory(block_address, candidate_size + PK6_STORED_SIZE)
            for offset in range(0, candidate_size, 4):
                # Constante de cifrado y sanity. Los huecos vacíos (cero puro)
                # se descartan sin descifrar ni crear objetos Python.
                if not (raw_block[offset] | raw_block[offset + 1] | raw_block[offset + 2] | raw_block[offset + 3]):
                    continue
                if raw_block[offset + 4] or raw_block[offset + 5]:
                    continue
                candidate = raw_block[offset:offset + PK6_STORED_SIZE]
                try:
                    pokemon = parse_pk6_boxed(
                        candidate, int(change.box), int(change.box_slot), self.reader.move_names,
                    )
                except ORASLiveError:
                    continue
                if pokemon is None or self._pokemon_identity(pokemon) != target_identity:
                    continue
                base_address = block_address + offset - target_index * PK6_STORED_SIZE
                if self._pc_base_matches(
                    client, base_address, changes, require_companion=True,
                ):
                    return base_address
        return None

    def _locate_pc_base(
        self,
        client: AzaharRPCClient,
        process: AzaharProcess,
        changes: Sequence[PendingPCRoleChange | PendingTeamChange],
    ) -> int:
        """Resuelve la matriz viva de cajas sin arriesgar una escritura ciega."""
        if not changes:
            return ORAS_PC_ADDRESS
        process_key = (int(process.title_id), str(process.name))
        candidates: list[int] = []
        cached = self._pc_bases_by_process.get(process_key)
        if cached is not None:
            candidates.append(cached)
        candidates.extend(address for address in ORAS_PC_KNOWN_ADDRESSES if address not in candidates)
        for base_address in candidates:
            if self._pc_base_matches(client, base_address, changes, require_companion=False):
                self._pc_bases_by_process[process_key] = base_address
                return base_address

        discovered = self._scan_pc_base(client, changes)
        if discovered is not None:
            self._pc_bases_by_process[process_key] = discovered
            return discovered
        raise ORASLiveError(
            "No se pudo localizar y validar la caja viva de ORAS con los Pokémon de esa caja. "
            "No se escribió ningún byte. Pulsa F5 fuera de combate o del PC y vuelve a probar."
        )

    def _capture_stable_party(self, client: AzaharRPCClient) -> tuple[tuple[bytes, ...], int]:
        for attempt in range(1, self.reader.snapshot_attempts + 1):
            first = self.reader._read_party(client)
            if self.reader.stable_delay:
                time.sleep(self.reader.stable_delay)
            second = self.reader._read_party(client)
            if first == second:
                return second, attempt
        raise ORASLiveError(
            "El equipo cambió durante todas las lecturas. Sal de la animación o combate y vuelve a intentarlo."
        )

    def _capture_stable_state(
        self,
        client: AzaharRPCClient,
        extras: Sequence[tuple[str, int, int]],
    ) -> tuple[tuple[bytes, ...], dict[str, bytes], int]:
        """Captura party y bloques auxiliares exactamente en el mismo instante estable."""
        for attempt in range(1, self.reader.snapshot_attempts + 1):
            first_party = self.reader._read_party(client)
            first_extra = {
                key: client.read_memory(address, size)
                for key, address, size in extras
            }
            if self.reader.stable_delay:
                time.sleep(self.reader.stable_delay)
            second_party = self.reader._read_party(client)
            second_extra = {
                key: client.read_memory(address, size)
                for key, address, size in extras
            }
            if first_party == second_party and first_extra == second_extra:
                return second_party, second_extra, attempt
        raise ORASLiveError(
            "ORAS cambió durante todas las lecturas. Sal de combates, mochila o cajas y vuelve a intentarlo."
        )

    @staticmethod
    def _pokemon_identity(pokemon: SavePokemon) -> str:
        if int(pokemon.pid or 0) or int(pokemon.tid or 0) or int(pokemon.sid or 0):
            return f"{int(pokemon.species_id)}:{int(pokemon.pid or 0)}:{int(pokemon.tid or 0)}:{int(pokemon.sid or 0)}"
        return f"fallback:{int(pokemon.species_id)}:{(pokemon.nickname or pokemon.species).strip().casefold()}"

    def _read_party_members(
        self,
        slots: Sequence[bytes],
        current: SaveGameData,
    ) -> dict[int, SavePokemon]:
        party: dict[int, SavePokemon] = {}
        for index, raw in enumerate(slots, start=1):
            pokemon = parse_pk6_party(raw, index, self.reader.move_names)
            if pokemon is not None:
                party[index] = self.reader._preserve_known_labels(pokemon, current)
        return party

    def _build_game(
        self,
        slots: Sequence[bytes],
        current: SaveGameData,
        process: AzaharProcess,
        *,
        live_write: bool,
    ) -> SaveGameData:
        by_slot = self._read_party_members(slots, current)
        party = [by_slot[index] for index in sorted(by_slot)]
        if not party:
            raise ORASLiveError("La captura posterior de ORAS no contiene ningún Pokémon en el equipo.")
        return SaveGameData(
            game=current.game,
            save_type=f"{current.save_type} + Azahar RPC",
            generation=current.generation,
            trainer=current.trainer,
            party=party,
            raw={
                **current.raw,
                "liveSync": True,
                "liveWrite": live_write,
                "liveProcess": process.name,
                "liveTitleId": f"{process.title_id:016X}",
                "liveProfile": "ORAS-1.4",
            },
        )

    @staticmethod
    def _unsupported_changes(changes: Sequence[object]) -> list[str]:
        labels: list[str] = []
        for change in changes:
            if isinstance(
                change,
                (PendingChange, PendingRoleChange, PendingPCRoleChange, PendingInventoryChange, PendingTMTeach),
            ):
                continue
            if isinstance(change, PendingTeamChange) and change.operation in {"swap-party-box", "replace-fainted"}:
                continue
            if isinstance(change, PendingTeamChange):
                label = "traslados que cambian el tamaño del equipo"
                if label not in labels:
                    labels.append(label)
                continue
            if type(change).__name__ not in labels:
                labels.append(type(change).__name__)
        return labels

    def _resolve_target(
        self,
        change: PendingChange | PendingRoleChange | PendingTMTeach,
        live_party: dict[int, SavePokemon],
    ) -> int:
        identity = str(getattr(change, "pokemon_identity", "") or "")
        if identity:
            matches = [
                slot for slot, pokemon in live_party.items()
                if self._pokemon_identity(pokemon) == identity
            ]
            if len(matches) == 1:
                return matches[0]
            if not matches:
                raise ORASLiveError(
                    f"{change.pokemon} ya no está en el mismo equipo vivo. Pulsa F5, revisa y vuelve a preparar el cambio."
                )
            raise ORASLiveError(
                f"La identidad de {change.pokemon} aparece más de una vez en el equipo vivo. No se escribió nada."
            )

        slot = int(change.pokemon_slot)
        pokemon = live_party.get(slot)
        if pokemon is None:
            raise ORASLiveError(
                f"El slot {slot} ya no contiene el Pokémon previsto. Pulsa F5 antes de guardar."
            )
        declared = {str(change.pokemon or "").strip().casefold(), str(change.species or "").strip().casefold()}
        declared.discard("")
        actual = {pokemon.nickname.strip().casefold(), pokemon.species.strip().casefold()}
        if declared and not declared.intersection(actual):
            raise ORASLiveError(
                f"El slot {slot} ya no corresponde a {change.pokemon}. Pulsa F5 antes de guardar."
            )
        return slot

    @staticmethod
    def _box_slot_address(
        box: int,
        box_slot: int,
        *,
        base_address: int = ORAS_PC_ADDRESS,
    ) -> int:
        if not 1 <= int(box) <= ORAS_PC_BOX_COUNT or not 1 <= int(box_slot) <= ORAS_PC_BOX_SLOT_COUNT:
            raise ORASLiveError("La posición de PC indicada no existe en ORAS.")
        index = (int(box) - 1) * ORAS_PC_BOX_SLOT_COUNT + (int(box_slot) - 1)
        return int(base_address) + index * PK6_STORED_SIZE

    def _resolve_pc_target(
        self,
        change: PendingPCRoleChange | PendingTeamChange,
        raw: bytes,
    ) -> SavePokemon:
        pokemon = parse_pk6_boxed(raw, int(change.box), int(change.box_slot), self.reader.move_names)
        if pokemon is None:
            raise ORASLiveError(
                f"El hueco PC {change.box}:{change.box_slot} está vacío. Pulsa F5 y revisa antes de cambiar el rol."
            )
        identity = self._pc_target_identity(change)
        pokemon_name = (
            change.incoming_pokemon if isinstance(change, PendingTeamChange)
            else change.pokemon
        )
        species_name = (
            change.incoming_species if isinstance(change, PendingTeamChange)
            else change.species
        )
        if identity and self._pokemon_identity(pokemon) != identity:
            raise ORASLiveError(
                f"{pokemon_name} ya no está en la caja {change.box}:{change.box_slot}. "
                "No se escribió ningún byte."
            )
        if not identity:
            declared = {
                str(pokemon_name or "").strip().casefold(),
                str(species_name or "").strip().casefold(),
            }
            declared.discard("")
            actual = {pokemon.nickname.strip().casefold(), pokemon.species.strip().casefold()}
            if declared and not declared.intersection(actual):
                raise ORASLiveError(
                    f"El hueco PC {change.box}:{change.box_slot} ya no corresponde a {pokemon_name}."
                )
        return pokemon

    def _resolve_team_swap_party_target(
        self,
        change: PendingTeamChange,
        live_party: dict[int, SavePokemon],
    ) -> int:
        identity = str(change.outgoing_identity or "")
        if identity:
            matches = [
                slot for slot, pokemon in live_party.items()
                if self._pokemon_identity(pokemon) == identity
            ]
            if len(matches) == 1:
                return matches[0]
            if not matches:
                raise ORASLiveError(
                    f"{change.outgoing_pokemon or 'El Pokémon elegido'} ya no está en el equipo vivo. "
                    "Pulsa F5 y vuelve a preparar la sustitución."
                )
            raise ORASLiveError(
                "La identidad del Pokémon saliente aparece más de una vez; no se escribió nada."
            )

        slot = int(change.party_slot)
        pokemon = live_party.get(slot)
        if pokemon is None:
            raise ORASLiveError(
                f"El slot {slot} del equipo ya no contiene el Pokémon que iba a salir."
            )
        declared = {
            str(change.outgoing_pokemon or "").strip().casefold(),
            str(change.outgoing_species or "").strip().casefold(),
        }
        declared.discard("")
        actual = {pokemon.nickname.strip().casefold(), pokemon.species.strip().casefold()}
        if declared and not declared.intersection(actual):
            raise ORASLiveError(
                f"El slot {slot} ya no corresponde a {change.outgoing_pokemon}. Pulsa F5 antes de sustituirlo."
            )
        return slot

    @staticmethod
    def _current_role(data: bytes | bytearray) -> str:
        markings = [bool(data[0x2A] & (1 << index)) for index in range(6)]
        return _role_from_markings(markings)[0]

    @staticmethod
    def _set_role(data: bytearray, role: str) -> None:
        role = canonical_role(role)
        try:
            selected = _ROLE_TO_MARKING[role]
        except KeyError as exc:
            raise ORASLiveError(f"El rol '{role}' no es válido para ORAS en vivo.") from exc
        markings = data[0x2A] & ~0x3F
        if selected >= 0:
            markings |= 1 << selected
        data[0x2A] = markings

    def _replace_role(self, data: bytearray, change: PendingRoleChange) -> None:
        """Cambia un rol solo si el juego conserva el estado que se iba a editar.

        Es la barrera que permite mantener REVISAR CAMBIOS aun cuando el monitor
        juego → RoleRun detecte actividad posterior: si el usuario cambió esa
        marca desde ORAS, una reversión vieja se rechaza en vez de sobrescribirla.
        """
        actual = self._current_role(data)
        expected = canonical_role(str(change.old_role or "SIN ROL"))
        if actual != expected:
            name = str(getattr(change, "pokemon", "") or "El Pokémon")
            raise ORASLiveError(
                f"{name} cambió de rol dentro del juego ({actual}). RoleRun esperaba {expected}; "
                "se ha cancelado la escritura para no sobrescribir ese cambio."
            )
        self._set_role(data, change.new_role)

    @staticmethod
    def _remove_move_slots(data: bytearray, slots: Sequence[int]) -> None:
        """Elimina huecos originales en orden descendente y compacta move/PP."""
        for one_based in sorted({int(value) for value in slots}, reverse=True):
            index = one_based - 1
            if not 0 <= index < 4:
                raise ORASLiveError(f"El hueco de movimiento {one_based} no es válido.")
            for move_index in range(index, 3):
                next_index = move_index + 1
                struct.pack_into(
                    "<H", data, _MOVE_OFFSETS[move_index],
                    struct.unpack_from("<H", data, _MOVE_OFFSETS[next_index])[0],
                )
                data[_MOVE_PP_OFFSETS[move_index]] = data[_MOVE_PP_OFFSETS[next_index]]
                data[_MOVE_PP_UPS_OFFSETS[move_index]] = data[_MOVE_PP_UPS_OFFSETS[next_index]]
            struct.pack_into("<H", data, _MOVE_OFFSETS[3], 0)
            data[_MOVE_PP_OFFSETS[3]] = 0
            data[_MOVE_PP_UPS_OFFSETS[3]] = 0

    @staticmethod
    def _experience_for_level(level: int, growth: int) -> int:
        """Experiencia acumulada mínima de Gen 6 para una curva y nivel."""
        level = max(1, min(100, int(level)))
        growth = int(growth)
        cube = level ** 3
        if growth == 0:  # Medium Fast
            return cube
        if growth == 1:  # Erratic
            if level <= 50:
                return cube * (100 - level) // 50
            if level <= 68:
                return cube * (150 - level) // 100
            if level <= 98:
                return cube * ((1911 - 10 * level) // 3) // 500
            return cube * (160 - level) // 100
        if growth == 2:  # Fluctuating
            if level <= 15:
                return cube * (((level + 1) // 3) + 24) // 50
            if level <= 35:
                return cube * (level + 14) // 50
            return cube * ((level // 2) + 32) // 50
        if growth == 3:  # Medium Slow
            return max(0, 6 * cube // 5 - 15 * level * level + 100 * level - 140)
        if growth == 4:  # Fast
            return 4 * cube // 5
        if growth == 5:  # Slow
            return 5 * cube // 4
        raise ORASLiveError("La ROM activa declara una curva de experiencia no compatible.")

    @classmethod
    def _level_for_experience(cls, experience: int, growth: int) -> int:
        experience = max(0, int(experience))
        level = 1
        while level < 100 and experience >= cls._experience_for_level(level + 1, growth):
            level += 1
        return level

    @classmethod
    def _party_extension(
        cls,
        stored: bytes | bytearray,
        personal: ORASPersonalStats,
    ) -> bytes:
        """Construye los 28 bytes de party como hace ORAS al retirar del PC."""
        if len(stored) != PK6_STORED_SIZE:
            raise ORASLiveError("El PK6 de caja no tiene el tamaño necesario para entrar al equipo.")
        experience = struct.unpack_from("<I", stored, 0x10)[0]
        level = cls._level_for_experience(experience, personal.exp_growth)
        nature = int(stored[0x1C])
        if not 0 <= nature <= 24:
            raise ORASLiveError("El Pokémon del PC contiene una naturaleza no válida.")
        evs = [int(stored[0x1E + index]) for index in range(6)]
        if any(not 0 <= ev <= 252 for ev in evs) or sum(evs) > 510:
            raise ORASLiveError("El Pokémon del PC contiene EV no válidos.")
        iv32 = struct.unpack_from("<I", stored, 0x74)[0]
        ivs = [(iv32 >> (5 * index)) & 0x1F for index in range(6)]
        base = tuple(int(value) for value in personal.base_stats)
        if len(base) != 6 or any(not 1 <= value <= 255 for value in base):
            raise ORASLiveError("La ROM activa devolvió estadísticas base no válidas.")

        hp = 1 if base[0] == 1 else ((ivs[0] + 2 * base[0] + evs[0] // 4 + 100) * level // 100) + 10
        stats = [
            ((ivs[index] + 2 * base[index] + evs[index] // 4) * level // 100) + 5
            for index in range(1, 6)
        ]
        raised = nature // 5
        lowered = nature % 5
        if raised != lowered:
            stats[raised] = stats[raised] * 11 // 10
            stats[lowered] = stats[lowered] * 9 // 10
        values = [hp, hp, *stats]
        if any(not 1 <= value <= 0xFFFF for value in values):
            raise ORASLiveError("Las estadísticas calculadas no caben en el bloque de equipo de ORAS.")

        extension = bytearray(PK6_PARTY_SIZE - PK6_STORED_SIZE)
        struct.pack_into("<I", extension, 0, 0)  # Estado curado al retirar del PC.
        extension[4] = level
        struct.pack_into("<7H", extension, 8, *values)
        return bytes(extension)

    def _replace_move(self, data: bytearray, change: PendingChange | PendingTMTeach) -> None:
        index = int(change.move_slot) - 1
        if not 0 <= index < 4:
            raise ORASLiveError(f"El hueco de movimiento {change.move_slot} no es válido.")
        current_move = struct.unpack_from("<H", data, _MOVE_OFFSETS[index])[0]
        if current_move != int(change.old_move_id or 0):
            raise ORASLiveError(
                f"{change.pokemon} cambió ese movimiento dentro del juego. Pulsa F5 y vuelve a preparar el cambio."
            )

        move_id = int(change.new_move_id or 0)
        if not 0 <= move_id <= 721:
            raise ORASLiveError(f"El movimiento #{move_id} no es válido para ORAS.")
        if move_id == 0:
            for move_index in range(index, 3):
                next_index = move_index + 1
                struct.pack_into(
                    "<H", data, _MOVE_OFFSETS[move_index],
                    struct.unpack_from("<H", data, _MOVE_OFFSETS[next_index])[0],
                )
                data[_MOVE_PP_OFFSETS[move_index]] = data[_MOVE_PP_OFFSETS[next_index]]
                data[_MOVE_PP_UPS_OFFSETS[move_index]] = data[_MOVE_PP_UPS_OFFSETS[next_index]]
            struct.pack_into("<H", data, _MOVE_OFFSETS[3], 0)
            data[_MOVE_PP_OFFSETS[3]] = 0
            data[_MOVE_PP_UPS_OFFSETS[3]] = 0
            return

        try:
            base_pp = int(self.move_pp_for(move_id))
        except Exception as exc:
            raise ORASLiveError(
                f"No se pudo validar el PP del movimiento #{move_id}; no se escribió nada."
            ) from exc
        pp_ups = int(data[_MOVE_PP_UPS_OFFSETS[index]])
        if not 0 <= pp_ups <= 3 or base_pp <= 0:
            raise ORASLiveError(
                f"El PP del movimiento #{move_id} no es válido para el hueco seleccionado."
            )
        pp = base_pp * (5 + pp_ups) // 5
        if pp > 0xFF:
            raise ORASLiveError(f"El PP calculado para el movimiento #{move_id} no cabe en PK6.")
        struct.pack_into("<H", data, _MOVE_OFFSETS[index], move_id)
        data[_MOVE_PP_OFFSETS[index]] = pp

    @staticmethod
    def _refresh_checksum(data: bytearray) -> None:
        struct.pack_into("<H", data, 6, _checksum(data))

    @staticmethod
    def _slot_address(slot: int) -> int:
        return ORAS_PARTY_ADDRESS + (slot - 1) * ORAS_PARTY_STRIDE

    @staticmethod
    def _prepare_inventory_value(
        pocket: bytearray,
        item_id: int,
        quantity: int,
        *,
        label: str,
    ) -> list[int]:
        """Actualiza un único objeto y devuelve su offset objetivo.

        La bolsa se valida completa antes de llegar aquí. Solo permitimos un
        registro existente o un hueco totalmente vacío; no se desplaza ni se
        reordena ningún objeto de la partida.
        """
        if not 1 <= item_id <= 1500 or not 1 <= quantity <= ORAS_MAX_BAG_QUANTITY:
            raise ORASLiveError(f"El valor pedido para {label} no es válido en ORAS.")
        matching: list[int] = []
        empty: list[int] = []
        for offset in range(0, len(pocket), ORAS_ITEM_RECORD_SIZE):
            existing_id, existing_quantity = struct.unpack_from("<HH", pocket, offset)
            if existing_id == item_id:
                matching.append(offset)
            elif existing_id == 0 and existing_quantity == 0:
                empty.append(offset)
        if len(matching) > 1:
            raise ORASLiveError(
                f"El objeto {label} aparece dos veces en la mochila; no se escribió nada."
            )
        if matching:
            offset = matching[0]
        elif empty:
            offset = empty[0]
        else:
            raise ORASLiveError(f"No hay hueco libre para {label} en la mochila de ORAS.")
        struct.pack_into("<HH", pocket, offset, item_id, quantity)
        # También devolvemos el registro cuando ya coincidía. Así una operación
        # idempotente puede vigilar ese mismo bloque tras confirmarse, mientras
        # ``plan`` sigue siendo quien decide si hace falta escribirlo.
        return [offset]

    @staticmethod
    def _validate_money(raw: bytes) -> int:
        if len(raw) != 4:
            raise ORASLiveError("La cantidad de dinero de ORAS tiene un tamaño inesperado.")
        value = struct.unpack("<I", raw)[0]
        if value > ORAS_MAX_MONEY:
            raise ORASLiveError(
                "El valor de dinero leído no es válido para ORAS; no se escribió nada."
            )
        return value

    def _rollback(
        self,
        client: AzaharRPCClient,
        attempted_writes: Sequence[tuple[int, bytes]] | Sequence[int],
        original_slots: dict[int, bytes] | None = None,
    ) -> list[str]:
        errors: list[str] = []
        if original_slots is not None:
            # Compatibilidad con la ruta original de party, que conserva el
            # número de slot y escribe solo los 0xE8 bytes almacenados.
            normalized = [
                (self._slot_address(int(slot)), original_slots[int(slot)][:PK6_STORED_SIZE])
                for slot in attempted_writes
            ]
        else:
            normalized = [
                (int(address), bytes(original))
                for address, original in attempted_writes
            ]
        restored: set[int] = set()
        for address, original in reversed(tuple(normalized)):
            if address in restored:
                continue
            restored.add(address)
            try:
                client.write_memory(address, original)
            except Exception as exc:
                errors.append(f"0x{address:08X}: {exc}")
        return errors

    def apply(
        self,
        current: SaveGameData,
        changes: Sequence[
            PendingChange | PendingRoleChange | PendingPCRoleChange |
            PendingInventoryChange | PendingTMTeach | PendingTeamChange | object
        ],
    ) -> ORASLiveWriteResult:
        """Captura, modifica y verifica cambios de roles/movimientos en RAM.

        No se realiza ninguna escritura hasta que todos los objetivos, movimientos
        previos, checksums y PP se han comprobado contra una captura estable.
        """
        if not changes:
            raise ORASLiveError("No hay cambios pendientes que aplicar en ORAS.")
        if any(
            isinstance(change, (PendingPCRoleChange, PendingInventoryChange, PendingTMTeach, PendingTeamChange))
            for change in changes
        ):
            return self._apply_extended(current, changes)
        unsupported = self._unsupported_changes(changes)
        if unsupported:
            raise ORASLiveError(
                "Esta alpha solo puede sincronizar en vivo roles y movimientos del equipo. "
                f"No se aplicó nada: {', '.join(unsupported)} requiere el flujo normal de guardado."
            )
        supported_changes = [change for change in changes if isinstance(change, (PendingChange, PendingRoleChange))]

        try:
            with self.reader.client_factory() as client:
                process = self.reader._find_oras_process(client.process_list())
                client.set_process(process.process_id)
                original_capture, capture_attempt = self._capture_stable_party(client)
                live_party = self._read_party_members(original_capture, current)
                if not live_party:
                    raise ORASLiveError("La captura estable de ORAS no contiene ningún Pokémon en el equipo.")

                targets = {
                    id(change): self._resolve_target(change, live_party)
                    for change in supported_changes
                }
                original_slots: dict[int, bytes] = {}
                plain_slots: dict[int, bytearray] = {}
                was_encrypted: dict[int, bool] = {}
                for slot in sorted(set(targets.values())):
                    original = original_capture[slot - 1]
                    plain, encrypted = _plain_pk6(original)
                    original_slots[slot] = original
                    plain_slots[slot] = bytearray(plain)
                    was_encrypted[slot] = encrypted

                # Las operaciones se aplican en el orden exacto de la cola. Así
                # un borrado y un cambio posterior del mismo moveset tienen la
                # misma semántica que el flujo de guardado tradicional.
                for change in supported_changes:
                    slot = targets[id(change)]
                    if isinstance(change, PendingRoleChange):
                        self._replace_role(plain_slots[slot], change)
                    else:
                        self._replace_move(plain_slots[slot], change)

                encoded_slots: dict[int, bytes] = {}
                expected_party: dict[int, SavePokemon] = {}
                for slot, plain in plain_slots.items():
                    self._refresh_checksum(plain)
                    encoded = encrypt_pk6(bytes(plain)) if was_encrypted[slot] else bytes(plain)
                    expected = parse_pk6_party(encoded, slot, self.reader.move_names)
                    if expected is None:
                        raise ORASLiveError(f"El slot {slot} quedó vacío durante la preparación; no se escribió nada.")
                    encoded_slots[slot] = encoded
                    expected_party[slot] = expected

                attempted_slots: list[int] = []
                try:
                    for slot in sorted(encoded_slots):
                        attempted_slots.append(slot)
                        # Movimiento, PP, PP-Ups, checksum y marcadores viven
                        # dentro de los 0xE8 bytes almacenados. No se toca la
                        # región separada de estadísticas de combate.
                        client.write_memory(
                            self._slot_address(slot),
                            encoded_slots[slot][:PK6_STORED_SIZE],
                        )

                    verified_capture, verified_attempt = self._capture_stable_party(client)
                    verified_party = self._read_party_members(verified_capture, current)
                    for slot, expected in expected_party.items():
                        actual = verified_party.get(slot)
                        if actual is None or self._pokemon_identity(actual) != self._pokemon_identity(expected):
                            raise ORASLiveError(
                                f"Azahar devolvió un Pokémon distinto en el slot {slot} tras la escritura."
                            )
                        if actual.role != expected.role or actual.move_ids != expected.move_ids:
                            raise ORASLiveError(
                                f"Azahar no confirmó los cambios del slot {slot}; se restaurará el contenido original."
                            )

                    game = self._build_game(
                        verified_capture, current, process, live_write=True,
                    )
                    return ORASLiveWriteResult(
                        game=game,
                        process=process,
                        attempts=max(capture_attempt, verified_attempt),
                        applied_count=len(supported_changes),
                    )
                except Exception as exc:
                    rollback_errors = self._rollback(client, attempted_slots, original_slots)
                    if rollback_errors:
                        raise ORASLiveError(
                            f"La sincronización en vivo falló: {exc}. "
                            "No se pudo confirmar la restauración de todos los slots: "
                            + "; ".join(rollback_errors)
                        ) from exc
                    if attempted_slots:
                        raise ORASLiveError(
                            f"La sincronización en vivo falló: {exc}. "
                            "RoleRun restauró el contenido PK6 original en RAM y no tocó el archivo main."
                        ) from exc
                    raise
        except AzaharRPCError as exc:
            raise ORASLiveError(str(exc)) from exc
