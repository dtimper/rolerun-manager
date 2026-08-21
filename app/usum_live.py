from __future__ import annotations

import hashlib
import json
import struct
import time
from datetime import datetime
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Sequence

from .azahar_rpc import AzaharProcess, AzaharRPCClient, AzaharRPCError
from .config import APP_VERSION, LOG_DIR
from .models import PendingChange, PendingInventoryChange, PendingRoleChange, PendingTMTeach, PendingTeamChange
from .oras_live import decrypt_pk6, encrypt_pk6, decrypt_pk6_stored, encrypt_pk6_stored
from .role_rules import ROLE_ORDER, ROLE_TO_MARKING, canonical_role, role_from_markings
from .save_engine_client import SaveGameData, SavePokemon
from .usum_rom_service import usum_tm_item_id
from .boxed_metadata import ability_name, boxed_level, level_for_experience, item_name
from .oras_tm_service import ORASPersonalStats
from .win_process_memory import HostPartyTarget, WindowsProcessMemory, WindowsProcessMemoryError


class USUMLiveError(RuntimeError):
    """Error seguro/presentable del backend vivo de Pokémon UltraSol/UltraLuna."""


# Identidad real de las ediciones retail de Pokémon UltraSol/UltraLuna.
USUM_TITLE_IDS = {
    0x00040000001B5000,  # Pokémon Ultra Sol
    0x00040000001B5100,  # Pokémon Ultra Luna
}
USUM_PROCESS_NAMES = {"niji_loc"}

# PKHeX: PK7 usa el mismo tamaño físico Gen6/7: 0xE8 almacenado y 0x104 party.
PK7_STORED_SIZE = 0xE8
PK7_PARTY_SIZE = 0x104
PK7_MAX_STRUCTURAL_SPECIES = 807  # límite estructural Gen7; la identidad del main valida USUM.

# CANDIDATA USUM DE CALIBRACIÓN, no un offset aceptado a ciegas.
# PokeStreamer-Tools distingue expresamente SM (0x34195E10) de USUM
# (0x33F7FA44) y para ambas usa stride 484, 0xE8 bytes almacenados + stats.
# RoleRun solo permite que esta candidata llegue a una escritura DESPUÉS de
# demostrarla en la ejecución actual: checksum PK7 válido + coincidencia completa
# por slot en especie+PID+TID+SID con el main de ESTA Run.
USUM_PARTY_REFERENCE_ADDRESS = 0x33F7FA44
# PKMN-NTR también documenta una segunda representación de party USUM en
# 0x330128E4 ("Could also be"). Alpha.49 NO escribe ahí: se usa únicamente
# como sonda acotada para demostrar el verdadero campo que acompaña al tamaño
# lógico del equipo mediante una transición 6↔5 hecha desde el propio juego.
USUM_PARTY_ALTERNATE_REFERENCE_ADDRESS = 0x330128E4
USUM_PARTY_STRIDE = 0x1E4  # 484
# La fuente que documenta 0x33F7FA44 NO presenta el PK7 de party como 0x104
# bytes contiguos. Lee 0xE8 bytes almacenados al principio del slot y los 0x16
# bytes de estado/estadísticas desde +0x158. Los 6 bytes finales del formato
# PK7 de party no contienen campos usados por RoleRun y se rellenan con cero
# únicamente en la copia local que se descifra/valida. Es el mismo patrón sparse
# que el backend ORAS ya maneja de forma probada.
USUM_PARTY_STATS_OFFSET = 0x158
USUM_PARTY_STATS_SIZE = 0x16
USUM_PARTY_TAIL_PADDING = PK7_PARTY_SIZE - PK7_STORED_SIZE - USUM_PARTY_STATS_SIZE
USUM_PARTY_SCAN_RADIUS = 0x400
USUM_PARTY_SPAN = (5 * USUM_PARTY_STRIDE) + USUM_PARTY_STATS_OFFSET + USUM_PARTY_STATS_SIZE
# Alpha.49 demostró físicamente en UltraSol una transición real 6→5 hecha desde
# el PC del propio juego. En una sonda acotada de 0x33F7F944.., el ÚNICO byte
# que cambió exactamente 6→5 fue 0x33F7F9D0. Como la party demostrada empieza
# en 0x33F7FA44, el tamaño lógico vive en PARTY_BASE - 0x74. La representación
# alternativa 0x330128E4 no cambió ningún byte y queda descartada para este fin.
# Esta relación es runtime de USUM; NO procede de extrapolar offsets del SAV.
USUM_PARTY_COUNT_DELTA = -0x74
USUM_PARTY_COUNT_SIZE = 1

# USUM — sonda de PS intra-combate de UltraSol/UltraLuna.
# Evidencia primaria: el plugin USUMCheatMenu adapta códigos de S/M específicamente
# a UltraSol/UltraLuna. Estas direcciones de combate se mantienen como candidatas
# y RoleRun exige además que Max HP coincida con la party PK7 ya demostrada antes
# de publicar Displayed/Actual HP.
# RoleRun NO las acepta a ciegas: durante cada batalla valida el vector de
# Max HP contra la party PK7 live ya demostrada antes de publicar ningún PS.
USUM_BATTLE_STATE_ADDRESS = 0x30000158
USUM_BATTLE_STATE_ACTIVE_VALUE = 0x00040001
USUM_BATTLE_PLAYER_MAX_HP_BASE = 0x30002776
USUM_BATTLE_PLAYER_DISPLAY_HP_BASE = 0x30002778
USUM_BATTLE_PLAYER_ACTUAL_HP_BASE = 0x30009760
USUM_BATTLE_PLAYER_STRIDE = 0x330
USUM_BATTLE_HP_SIZE = 2

# Azahar 263745c RPC: HandleWriteMemory permite PROCESS_IMAGE, HEAP,
# LINEAR_HEAP y N3DS_EXTRA_RAM, pero NO NEW_LINEAR_HEAP (0x30000000...).
# La party USUM candidata vive en NEW_LINEAR_HEAP (0x33xxxxxx). El backend de SM demostró que
# trasladar una dirección NEW_LINEAR_HEAP a LINEAR_HEAP no puede asumirse como alias. USUM
# mantiene esa barrera y calibra el backing FCRAM del proceso Windows por contenido exacto
# de la party antes de cualquier escritura.
_AZAHAR_PROCESS_IMAGE = (0x00100000, 0x04000000)
_AZAHAR_HEAP = (0x08000000, 0x10000000)
_AZAHAR_LINEAR_HEAP = (0x14000000, 0x1C000000)
_AZAHAR_N3DS_EXTRA_RAM = (0x1E800000, 0x1EC00000)
_AZAHAR_RPC_DIRECT_WRITE_RANGES = (
    _AZAHAR_PROCESS_IMAGE, _AZAHAR_HEAP, _AZAHAR_LINEAR_HEAP, _AZAHAR_N3DS_EXTRA_RAM,
)
_AZAHAR_NEW_LINEAR_HEAP = 0x30000000
_AZAHAR_NEW_LINEAR_HEAP_OLD_ALIAS_END = 0x38000000  # primeros 128 MiB


# PKHeX PK7: IDs de movimientos, PP actuales y PP Ups viven en estos offsets
# del bloque descifrado. Se mantienen separados de cualquier dirección RAM: son
# parte del formato PK7, no un offset de proceso.
_PK7_MOVE_OFFSETS = (0x5A, 0x5C, 0x5E, 0x60)
_PK7_MOVE_PP_OFFSETS = (0x62, 0x63, 0x64, 0x65)
_PK7_MOVE_PP_UPS_OFFSETS = (0x66, 0x67, 0x68, 0x69)

# PKHeX SAV7USUM save blocks used ONLY as runtime witnesses. RoleRun never assumes
# these save offsets are RAM offsets: it first finds an exact block inside the
# already-proven host FCRAM region and then confirms the same bytes through RPC.
USUM_SAVE_ITEM_BLOCK_OFFSET = 0x00000
USUM_SAVE_ITEM_BLOCK_SIZE = 0x00E28
USUM_SAVE_PARTY_BLOCK_OFFSET = 0x01600
USUM_SAVE_MISC_BLOCK_OFFSET = 0x04400
USUM_SAVE_MISC_BLOCK_SIZE = 0x001FC
# PKHeX SaveBlockAccessor7SM: BoxLayout (bloque 13) y BoxPokemon (bloque 14).
# Son offsets DEL ARCHIVO SAV7USUM, nunca direcciones RAM. Alpha.21 solo los usa
# después de demostrar en la sesión actual que Items -> Misc -> BoxLayout viven
# con exactamente la misma relación relativa tanto en host FCRAM como en guest RPC.
USUM_SAVE_BOX_LAYOUT_BLOCK_OFFSET = 0x04C00
USUM_SAVE_BOX_LAYOUT_BLOCK_SIZE = 0x005E6
# PKHeX BoxLayout7: PCFlags 0x5E0, BoxesUnlocked 0x5E1 y LastViewedBox 0x5E3
# dentro del bloque BoxLayout. Son offsets de SAVE, nunca direcciones RAM.
USUM_SAVE_BOX_LAYOUT_UNLOCKED_OFFSET = 0x05E1
USUM_SAVE_BOX_LAYOUT_CURRENT_BOX_OFFSET = 0x05E3
USUM_SAVE_PC_BLOCK_OFFSET = 0x05200
USUM_SAVE_PC_BLOCK_SIZE = 0x36600
USUM_MISC_MONEY_OFFSET = 0x04
USUM_MAX_MONEY = 9_999_999
USUM_UTILITY_ITEM_IDS = {"rare-candy": 50, "max-repel": 77}

# Alpha.15: Money can live in the same Misc structure even when unrelated
# runtime fields no longer byte-match the last saved ``main``. The fallback
# below never guesses an address: it requires a unique structural consensus
# inside the already-proven FCRAM allocation and exact host/guest equality.
USUM_MISC_STRUCTURAL_WINDOW_SIZE = 16
USUM_MISC_STRUCTURAL_MIN_WINDOWS = 6
USUM_MISC_STRUCTURAL_MIN_QUARTILES = 3
USUM_MISC_STRUCTURAL_MIN_EQUAL_BYTES = 160

# Alpha.16: la mochila completa puede divergir del último main por objetos
# obtenidos/usados. Para MT solo aceptamos una estructura viva si varias ventanas
# exactas distribuidas por el bloque convergen en una única base host y la misma
# base guest devuelve exactamente esos bytes.
USUM_ITEMS_STRUCTURAL_WINDOW_SIZE = 16
USUM_ITEMS_STRUCTURAL_MIN_WINDOWS = 8
USUM_ITEMS_STRUCTURAL_MIN_QUARTILES = 3
USUM_ITEMS_STRUCTURAL_MIN_EQUAL_BYTES = 1800

# Alpha.20: el PC se descubre desde el ``main`` real y la propia RAM; no hay una
# dirección de cajas hardcodeada. El tamaño de matriz tampoco se fija aquí: llega
# desde PKHeX/SaveEngine para el guardado abierto. Estos límites solo rechazan
# metadatos absurdos antes de leer memoria.
USUM_PC_MAX_BOX_COUNT = 64
USUM_PC_MAX_BOX_SLOT_COUNT = 60
# Formato SAV7USUM validado: 32 cajas de 30 slots. Se usan también para la
# calibración live autosuficiente de Equipo↔PC; no dependen del main.
USUM_PC_BOX_COUNT = 32
USUM_PC_BOX_SLOT_COUNT = 30
USUM_PC_WITNESS_LIMIT = 16
USUM_PC_READ_STABLE_DELAY = 0.030
# Prueba adicional del espejo de guardado vivo usada cuando el último main no
# contiene ningún Pokémon de caja. Misc conserva sus umbrales alpha.15; para
# BoxLayout exigimos además coincidencia distribuida y mayoría de bytes iguales.
USUM_PC_LAYOUT_MIN_WINDOWS = 4
USUM_PC_LAYOUT_MIN_QUARTILES = 2
USUM_PC_LAYOUT_MIN_EQUAL_BYTES = 1000
# Alpha.23 direct BoxPokemon discovery. These are search/validation limits, not
# RAM offsets: the 960 slots and 0xE8 record size come from the PK7 box format.
USUM_PC_DIRECT_MAX_HEADER_CANDIDATES = 32768  # alpha.24: límite POST validación PK7, no sanity hits
USUM_PC_DIRECT_MAX_VALID_RECORDS = 4096
# PKMN-NTR LookupTable.BoxOffset declara explícitamente esta dirección como
# "Location of Pokémon Box data in RAM" para GameVersion.US y GameVersion.UM.
# RoleRun sigue tratándola como CANDIDATA runtime: para lectura exige dos lecturas
# guest idénticas + parse completo de los 960 PK7 + coherencia party↔PC. Para
# escritura exige además demostrar la copia host exacta; la referencia nunca
# autoriza por sí sola un WriteProcessMemory.
USUM_PC_BOX_BASE_REFERENCE = 0x33015AB0
USUM_PC_CURRENT_BOX_REFERENCE = 0x33015AA7

# PKMN-NTR LookupTable.ItemsOffset/ItemsSize declara para GameVersion.US/UM
# la mochila viva en 0x33011934 y una ventana de 0x1000 bytes. A diferencia de
# alpha.53, esta dirección NO se deriva de offsets SAV: es una referencia RAM
# específica de USUM. RoleRun la trata como candidata y exige estabilidad +
# testigo estructural contra el main antes de publicar MTs.
USUM_ITEMS_BASE_REFERENCE = 0x33011934
USUM_ITEMS_REFERENCE_READ_SIZE = 0x1000

# USUM — progreso de Kahunas mediante el bolsillo Z-Crystals de SAV7USUM.
# La estructura oficial de PKHeX/PKSM sitúa Items en 0x00000 (0xE28 bytes) y
# el bolsillo Z-Crystals en 0xD70, con 35 entradas de 4 bytes. Los cuatro premios
# de Gran Prueba se comprueban en orden narrativo: Hala/Fightinium,
# Olivia/Rockium, Nanu/Darkinium, Hapu/Groundium.
USUM_ZCRYSTAL_POCKET_OFFSET = 0x0D70
USUM_ZCRYSTAL_POCKET_SLOT_COUNT = 35
USUM_ITEM_RECORD_SIZE = 4
USUM_ZCRYSTAL_KEY_IDS = frozenset((*range(807, 836), *range(927, 933)))
USUM_KAHUNA_ZCRYSTAL_KEY_IDS = (813, 819, 822, 815)
# No existe una dirección live externa de Items/BoxPokemon aceptada para USUM.
# La localización se demuestra por huellas estructurales de la sesión real.
USUM_ITEMS_LIVEHEX_REFERENCE = None


def parse_usum_zcrystal_keys(raw: bytes) -> frozenset[int] | None:
    """Devuelve los Z-Crystals de mochila solo si el bolsillo es estructuralmente válido.

    SAV7USUM codifica cada entrada en 4 bytes: 10 bits ItemID + 10 bits cantidad.
    Para el bolsillo Z-Crystals USUM la estructura fija cantidad máxima 1 y 35 slots.
    """
    if len(raw) != USUM_SAVE_ITEM_BLOCK_SIZE:
        return None
    start = USUM_ZCRYSTAL_POCKET_OFFSET
    end = start + (USUM_ZCRYSTAL_POCKET_SLOT_COUNT * USUM_ITEM_RECORD_SIZE)
    if end > len(raw):
        return None
    result: set[int] = set()
    for offset in range(start, end, USUM_ITEM_RECORD_SIZE):
        word = struct.unpack_from("<I", raw, offset)[0]
        item_id = int(word & 0x3FF)
        count = int((word >> 10) & 0x3FF)
        if item_id == 0:
            if count != 0:
                return None
            continue
        if item_id not in USUM_ZCRYSTAL_KEY_IDS:
            return None
        if count != 1 or item_id in result:
            return None
        result.add(item_id)
    return frozenset(result)


def count_usum_kahuna_badges(raw: bytes) -> int | None:
    """Cuenta Grandes Pruebas completadas por sus cuatro Z-Crystals persistentes.

    La secuencia debe ser un prefijo exacto. Un cristal posterior sin todos los
    anteriores se rechaza para no convertir una región errónea/corrupta en progreso.
    """
    crystals = parse_usum_zcrystal_keys(raw)
    if crystals is None:
        return None
    present = tuple(item_id in crystals for item_id in USUM_KAHUNA_ZCRYSTAL_KEY_IDS)
    first_missing = next((i for i, value in enumerate(present) if not value), len(present))
    if any(present[first_missing:]):
        return None
    return int(first_missing)


def parse_usum_saved_kahuna_badges(save_path: Path | str | None) -> int | None:
    if save_path is None:
        return None
    try:
        raw = Path(save_path).expanduser().resolve().read_bytes()
    except (OSError, TypeError, ValueError):
        return None
    end = USUM_SAVE_ITEM_BLOCK_OFFSET + USUM_SAVE_ITEM_BLOCK_SIZE
    if len(raw) < end:
        return None
    return count_usum_kahuna_badges(bytes(raw[USUM_SAVE_ITEM_BLOCK_OFFSET:end]))


def load_usum_move_pp(path: Path) -> dict[int, int]:
    """Carga PP base Gen7 desde una tabla local derivada de PKHeX.Core.

    La tabla solo aporta una propiedad del formato de movimientos. La existencia
    del movimiento en la edición concreta se valida además contra ``sav.MaxMoveID``
    expuesto por el motor del guardado activo antes de escribir en RAM.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        values = raw.get("pp", {})
        result = {int(move_id): int(pp) for move_id, pp in values.items()}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}
    return {
        move_id: pp for move_id, pp in result.items()
        if move_id > 0 and 1 <= pp <= 255
    }


@dataclass(frozen=True, slots=True)
class USUMLiveMemoryBlock:
    address: int
    data: bytes


@dataclass(frozen=True, slots=True)
class USUMLiveSnapshot:
    game: SaveGameData
    process: AzaharProcess
    attempts: int
    party_base: int
    memory_blocks: tuple[USUMLiveMemoryBlock, ...] = ()
    # Alpha.31 diagnostic: full 6×0x1E4 runtime party span. The normal
    # reader still parses only the proven sparse PK7 stored+stats fields; this
    # raw span is retained solely to compare a real in-game swap byte-for-byte.
    runtime_party_region: bytes = b""


@dataclass(frozen=True, slots=True)
class USUMBattleProbe:
    """Muestra independiente del motor de batalla de UltraSol/UltraLuna.

    ``state`` es ``battle`` o ``none``. ``displayed_hp`` es el HP que el juego
    está mostrando durante la animación; ``actual_hp`` se conserva como testigo
    adicional, pero no se usa para adelantar visualmente una muerte.
    """

    state: str
    health_game: SaveGameData | None = None
    hp_pairs: tuple[tuple[int, int], ...] = ()
    actual_hp_pairs: tuple[tuple[int, int], ...] = ()
    validated: bool = False
    reason: str = ""


@dataclass(frozen=True, slots=True)
class USUMLiveWriteResult:
    """Resultado de una escritura de rol PK7 confirmada en la RAM de SM."""

    game: SaveGameData
    process: AzaharProcess
    attempts: int
    applied_count: int
    already_applied: bool = False


def _checksum67(data: bytes) -> int:
    if len(data) < PK7_STORED_SIZE:
        return -1
    return sum(struct.unpack_from("<112H", data, 8)) & 0xFFFF


def decrypt_pk7(raw: bytes) -> bytes:
    """Descifra un PK7 de party usando el algoritmo común Gen6/7.

    PKHeX documenta que PK7 conserva SIZE_6PARTY y usa Decrypt67. El helper
    probado de ORAS implementa exactamente ese cifrado/shuffle 6/7; se reutiliza
    aquí solo para lectura y sin compartir ninguna dirección RAM de Gen6.
    """
    if len(raw) != PK7_PARTY_SIZE:
        raise USUMLiveError(f"Un slot PK7 debe medir {PK7_PARTY_SIZE} bytes.")
    try:
        return decrypt_pk6(raw)
    except Exception as exc:
        raise USUMLiveError("No se pudo descifrar el bloque PK7 leído.") from exc


def _valid_plain_pk7(data: bytes, *, allow_empty: bool = True) -> bool:
    if len(data) != PK7_PARTY_SIZE:
        return False
    if struct.unpack_from("<H", data, 4)[0] != 0:
        return False
    if struct.unpack_from("<H", data, 6)[0] != _checksum67(data):
        return False
    species = struct.unpack_from("<H", data, 8)[0]
    if species == 0:
        return bool(allow_empty)
    level = int(data[0xEC])
    return 1 <= species <= PK7_MAX_STRUCTURAL_SPECIES and 1 <= level <= 100


def _plain_pk7_with_state(raw: bytes) -> tuple[bytes, bool]:
    """Devuelve PK7 plano y si la representación de RAM estaba cifrada."""
    if len(raw) != PK7_PARTY_SIZE:
        raise USUMLiveError(f"Un slot PK7 debe medir {PK7_PARTY_SIZE} bytes.")
    if not any(raw):
        return raw, False
    if _valid_plain_pk7(raw):
        return raw, False
    decrypted = decrypt_pk7(raw)
    if _valid_plain_pk7(decrypted):
        return decrypted, True
    raise USUMLiveError("El PK7 no superó sanity/checksum/especie/nivel.")


def _plain_pk7(raw: bytes) -> bytes:
    return _plain_pk7_with_state(raw)[0]


def _identity(pokemon: SavePokemon) -> tuple[int, int, int, int]:
    return (
        int(pokemon.species_id),
        int(pokemon.pid or 0),
        int(pokemon.tid or 0),
        int(pokemon.sid or 0),
    )


def _slot_identity_map(party: Sequence[SavePokemon]) -> dict[int, tuple[int, int, int, int]]:
    return {int(pokemon.slot): _identity(pokemon) for pokemon in party if int(pokemon.species_id) > 0}


def _decode_basic_utf16(data: bytes) -> str:
    """Fallback visual conservador; la etiqueta exacta se preserva desde PKHeX.

    Gen7 tiene reglas especiales para ciertos codepoints. Alpha.3 no intenta
    reimplementarlas: el nickname del main se conserva cuando la identidad
    coincide, que es además el requisito de calibración inicial.
    """
    chars: list[str] = []
    for offset in range(0, len(data) - 1, 2):
        value = struct.unpack_from("<H", data, offset)[0]
        if value in {0, 0xFFFF}:
            break
        if 0xD800 <= value <= 0xDFFF:
            return ""
        chars.append(chr(value))
    return "".join(chars).strip()


def parse_pk7_party(raw: bytes, slot: int, move_names: dict[int, str]) -> SavePokemon | None:
    if len(raw) != PK7_PARTY_SIZE:
        raise USUMLiveError(f"El slot {slot} tiene un tamaño PK7 inesperado.")
    if not any(raw):
        return None

    data = _plain_pk7(raw)
    species_id = struct.unpack_from("<H", data, 8)[0]
    if species_id == 0:
        return None

    held_item_id = struct.unpack_from("<H", data, 0x0A)[0]
    tid = struct.unpack_from("<H", data, 0x0C)[0]
    sid = struct.unpack_from("<H", data, 0x0E)[0]
    ability_id = data[0x14]
    pid = struct.unpack_from("<I", data, 0x18)[0]
    form = data[0x1D] >> 3
    nickname = _decode_basic_utf16(data[0x40:0x58])
    species_name = nickname or f"Especie #{species_id}"
    move_ids = [struct.unpack_from("<H", data, offset)[0] for offset in (0x5A, 0x5C, 0x5E, 0x60)]
    moves = [
        "—" if move_id == 0 else move_names.get(move_id, f"Movimiento #{move_id}")
        for move_id in move_ids
    ]
    iv32 = struct.unpack_from("<I", data, 0x74)[0]

    # PKHeX PK7: MarkingValue es un ushort en 0x16; cada símbolo ocupa 2 bits.
    # Para RoleRun cualquier color distinto de None (0) significa marca activa.
    marking_value = struct.unpack_from("<H", data, 0x16)[0]
    markings = [bool((marking_value >> (index * 2)) & 0b11) for index in range(6)]
    role, role_symbol = role_from_markings(markings, layout=2)
    return SavePokemon(
        slot=int(slot),
        species_id=int(species_id),
        species=species_name,
        nickname=nickname or species_name,
        level=int(data[0xEC]),
        held_item=item_name(held_item_id),
        ability=ability_name(ability_id),
        moves=moves,
        move_ids=move_ids,
        is_egg=bool(iv32 & 0x40000000),
        markings=markings,
        role=role,
        role_symbol=role_symbol,
        pid=int(pid),
        tid=int(tid),
        sid=int(sid),
        form=int(form),
        current_hp=struct.unpack_from("<H", data, 0xF0)[0],
        max_hp=struct.unpack_from("<H", data, 0xF2)[0],
    )



def _valid_plain_pk7_stored(data: bytes, *, allow_empty: bool = True) -> bool:
    if len(data) != PK7_STORED_SIZE:
        return False
    if struct.unpack_from("<H", data, 4)[0] != 0:
        return False
    if struct.unpack_from("<H", data, 6)[0] != _checksum67(data):
        return False
    species = struct.unpack_from("<H", data, 8)[0]
    if species == 0:
        return bool(allow_empty)
    return 1 <= species <= PK7_MAX_STRUCTURAL_SPECIES


def _plain_pk7_stored_with_state(raw: bytes) -> tuple[bytes, bool]:
    """Devuelve un PK7 de caja plano y si la representación estaba cifrada."""
    if len(raw) != PK7_STORED_SIZE:
        raise USUMLiveError(f"Un PK7 almacenado debe medir {PK7_STORED_SIZE} bytes.")
    if not any(raw):
        return bytes(raw), False
    if _valid_plain_pk7_stored(raw):
        return bytes(raw), False
    try:
        decrypted = decrypt_pk6_stored(raw)
    except Exception as exc:
        raise USUMLiveError("No se pudo descifrar el PK7 almacenado de caja.") from exc
    if _valid_plain_pk7_stored(decrypted):
        return bytes(decrypted), True
    raise USUMLiveError("El PK7 de caja no superó sanity/checksum/especie.")


def _is_structurally_valid_occupied_pk7(raw: bytes) -> bool:
    """Cheap-enough semantic gate for the byte-wide FCRAM scanner.

    ``sanity == 0`` alone is not evidence of a PK7. A record reaches the direct
    PC resolver only after the stored block can be interpreted (plain/encrypted),
    its checksum matches and its species is a real occupied Gen7 species.
    """
    if len(raw) != PK7_STORED_SIZE or not any(raw):
        return False
    try:
        data, _encrypted = _plain_pk7_stored_with_state(bytes(raw))
    except Exception:
        return False
    return 1 <= int(struct.unpack_from("<H", data, 8)[0]) <= PK7_MAX_STRUCTURAL_SPECIES


def parse_pk7_boxed(
    raw: bytes, box: int, box_slot: int, move_names: dict[int, str],
) -> SavePokemon | None:
    """Interpreta exclusivamente el bloque PK7 almacenado (0xE8) de una caja SM."""
    if len(raw) != PK7_STORED_SIZE:
        raise USUMLiveError(f"El hueco {box}:{box_slot} del PC tiene un tamaño PK7 inesperado.")
    if not any(raw):
        return None
    data, _encrypted = _plain_pk7_stored_with_state(raw)
    species_id = struct.unpack_from("<H", data, 8)[0]
    if species_id == 0:
        return None

    held_item_id = struct.unpack_from("<H", data, 0x0A)[0]
    tid = struct.unpack_from("<H", data, 0x0C)[0]
    sid = struct.unpack_from("<H", data, 0x0E)[0]
    ability_id = data[0x14]
    pid = struct.unpack_from("<I", data, 0x18)[0]
    form = data[0x1D] >> 3
    experience = struct.unpack_from("<I", data, 0x10)[0]
    level = boxed_level("sm", species_id, form, experience)
    nickname = _decode_basic_utf16(data[0x40:0x58])
    species_name = nickname or f"Especie #{species_id}"
    move_ids = [struct.unpack_from("<H", data, offset)[0] for offset in _PK7_MOVE_OFFSETS]
    moves = [
        "—" if move_id == 0 else move_names.get(move_id, f"Movimiento #{move_id}")
        for move_id in move_ids
    ]
    iv32 = struct.unpack_from("<I", data, 0x74)[0]
    marking_value = struct.unpack_from("<H", data, 0x16)[0]
    markings = [bool((marking_value >> (index * 2)) & 0b11) for index in range(6)]
    role, role_symbol = role_from_markings(markings, layout=2)
    return SavePokemon(
        slot=int(box_slot), species_id=int(species_id), species=species_name,
        nickname=nickname or species_name, level=level,
        held_item=item_name(held_item_id),
        ability=ability_name(ability_id), moves=moves, move_ids=move_ids,
        is_egg=bool(iv32 & 0x40000000), markings=markings,
        role=role, role_symbol=role_symbol, box=int(box), box_slot=int(box_slot),
        pid=int(pid), tid=int(tid), sid=int(sid), form=int(form),
    )


def _pc_identity(pokemon: SavePokemon | None) -> tuple[int, int, int, int] | None:
    if pokemon is None or int(pokemon.species_id) <= 0:
        return None
    return _identity(pokemon)


def _pc_matrix_size(box_count: int, box_slot_count: int) -> int:
    boxes = int(box_count)
    slots = int(box_slot_count)
    if not 1 <= boxes <= USUM_PC_MAX_BOX_COUNT or not 1 <= slots <= USUM_PC_MAX_BOX_SLOT_COUNT:
        raise USUMLiveError(
            f"PKHeX devolvió dimensiones de PC no válidas para esta partida ({boxes}×{slots})."
        )
    return boxes * slots * PK7_STORED_SIZE


def _pc_slot_index(box: int, box_slot: int, box_slot_count: int) -> int:
    if int(box) < 1 or int(box_slot) < 1 or int(box_slot) > int(box_slot_count):
        raise USUMLiveError("Caja/slot de PC fuera de rango al preparar un testigo SM.")
    return (int(box) - 1) * int(box_slot_count) + (int(box_slot) - 1)


def _parse_pc_matrix(
    raw: bytes, *, box_count: int, box_slot_count: int, move_names: dict[int, str],
) -> dict[tuple[int, int], SavePokemon | None]:
    expected = _pc_matrix_size(box_count, box_slot_count)
    if len(raw) != expected:
        raise USUMLiveError("La matriz viva del PC SM tiene un tamaño distinto al informado por PKHeX.")
    result: dict[tuple[int, int], SavePokemon | None] = {}
    for index in range(int(box_count) * int(box_slot_count)):
        start = index * PK7_STORED_SIZE
        box, slot_index = divmod(index, int(box_slot_count))
        box += 1
        box_slot = slot_index + 1
        try:
            result[(box, box_slot)] = parse_pk7_boxed(
                raw[start:start + PK7_STORED_SIZE], box, box_slot, move_names,
            )
        except USUMLiveError as exc:
            raise USUMLiveError(
                f"La matriz candidata del PC no contiene PK7 válidos en Caja {box}, hueco {box_slot}: {exc}"
            ) from exc
    return result


def _saved_pc_matrix_candidates(
    save_bytes: bytes, anchors: Sequence[SavePokemon], *, box_count: int, box_slot_count: int,
    move_names: dict[int, str],
) -> tuple[int, bytes, dict[tuple[int, int], SavePokemon | None]]:
    """Descubre el bloque de cajas DENTRO del main usando identidades posicionadas.

    El offset hallado es un offset de archivo, jamás una dirección RAM. Solo sirve
    para extraer los PK7 testigo que después se vuelven a demostrar en host+guest.
    """
    matrix_size = _pc_matrix_size(box_count, box_slot_count)
    raw_save = bytes(save_bytes)
    usable = [
        p for p in anchors
        if p.box is not None and p.box_slot is not None and 1 <= int(p.box) <= int(box_count)
        and 1 <= int(p.box_slot) <= int(box_slot_count) and _pc_identity(p) is not None
    ]
    if not usable:
        raise USUMLiveError(
            "El último main no contiene ningún Pokémon posicionado en el PC con el que demostrar la matriz viva. "
            "Guarda dentro del juego con al menos un Pokémon en una caja y vuelve a abrir CAJAS PC."
        )
    targets: dict[tuple[int, int, int, int], list[int]] = {}
    for pokemon in usable:
        identity = _pc_identity(pokemon)
        if identity is None:
            continue
        targets.setdefault(identity, []).append(
            _pc_slot_index(int(pokemon.box), int(pokemon.box_slot), box_slot_count)
        )

    candidate_bases: set[int] = set()
    limit = len(raw_save) - PK7_STORED_SIZE
    for offset in range(0, max(0, limit) + 1):
        # Sanity vive en la cabecera no cifrada. Este filtro no presupone un
        # offset/alineación y evita descifrar bytes aleatorios del resto del main.
        if raw_save[offset + 4:offset + 6] != b"\0\0":
            continue
        chunk = raw_save[offset:offset + PK7_STORED_SIZE]
        if not any(chunk[:8]):
            continue
        try:
            pokemon = parse_pk7_boxed(chunk, 1, 1, move_names)
        except Exception:
            continue
        identity = _pc_identity(pokemon)
        indexes = targets.get(identity) if identity is not None else None
        if not indexes:
            continue
        for index in indexes:
            base = int(offset) - int(index) * PK7_STORED_SIZE
            if 0 <= base and base + matrix_size <= len(raw_save):
                candidate_bases.add(base)

    proven: list[tuple[int, bytes, dict[tuple[int, int], SavePokemon | None]]] = []
    expected_ids = {
        (int(p.box), int(p.box_slot)): _pc_identity(p)
        for p in usable if p.box is not None and p.box_slot is not None
    }
    for base in sorted(candidate_bases):
        matrix = raw_save[base:base + matrix_size]
        try:
            parsed = _parse_pc_matrix(
                matrix, box_count=box_count, box_slot_count=box_slot_count, move_names=move_names,
            )
        except USUMLiveError:
            continue
        if any(_pc_identity(parsed.get(pos)) != identity for pos, identity in expected_ids.items()):
            continue
        proven.append((int(base), bytes(matrix), parsed))
        if len(proven) > 1:
            break
    if len(proven) != 1:
        raise USUMLiveError(
            "No se pudo demostrar una única matriz de cajas dentro del main real de UltraSol/UltraLuna. "
            f"Candidatas válidas: {len(proven)}. No se usará ese archivo como dirección RAM."
        )
    return proven[0]


def _pc_exact_witnesses_from_saved_matrix(
    matrix: bytes, parsed: dict[tuple[int, int], SavePokemon | None], *, box_slot_count: int,
) -> list[tuple[int, bytes]]:
    """Elige PK7 completos, exactos y distribuidos para localizar la copia viva."""
    occupied: list[tuple[int, int, bytes]] = []
    total = max(1, len(matrix))
    for (box, slot), pokemon in parsed.items():
        if pokemon is None:
            continue
        index = _pc_slot_index(box, slot, box_slot_count)
        relative = index * PK7_STORED_SIZE
        raw = matrix[relative:relative + PK7_STORED_SIZE]
        try:
            plain, _encrypted = _plain_pk7_stored_with_state(raw)
            canonical_encrypted = encrypt_pk6_stored(plain)
        except Exception:
            continue
        # Priorizamos entropía y distribución; no hay ningún offset RAM aquí.
        score = len(set(canonical_encrypted))
        occupied.append((relative, score, canonical_encrypted))
    if not occupied:
        return []
    quartiles: list[list[tuple[int, int, bytes]]] = [[], [], [], []]
    for item in occupied:
        quartile = min(3, (item[0] * 4) // total)
        quartiles[quartile].append(item)
    selected: list[tuple[int, bytes]] = []
    per_quartile = max(1, USUM_PC_WITNESS_LIMIT // 4)
    for group in quartiles:
        group.sort(key=lambda item: (-item[1], item[0]))
        selected.extend((relative, raw) for relative, _score, raw in group[:per_quartile])
    if len(selected) < min(USUM_PC_WITNESS_LIMIT, len(occupied)):
        existing = {relative for relative, _raw in selected}
        for relative, _score, raw in sorted(occupied, key=lambda item: (-item[1], item[0])):
            if relative in existing:
                continue
            selected.append((relative, raw))
            existing.add(relative)
            if len(selected) >= USUM_PC_WITNESS_LIMIT:
                break
    return sorted(selected, key=lambda item: item[0])


class USUMLiveReader:
    """Backend alpha.5 de party + marcadores/movimientos para UltraSol/UltraLuna sobre AzaharPlus RPC.

    La referencia RAM pública solo sirve como punto de partida de calibración.
    La base no se considera válida hasta que una party PK7 completa y estable
    queda vinculada al último estado conocido mediante identidades fuertes.
    Alpha.27 permite además transiciones demostrables (reorden, alta/baja o una
    sustitución 1-a-1) para no exigir que el ``main`` se guarde tras cada cambio.
    """

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
        self._party_bases_by_process: dict[tuple[int, int, str], int] = {}
        self._last_resolution: dict[str, object] = {}
        # Alpha.58: traza acotada de HP de batalla USUM. Se usa únicamente para
        # demostrar por qué el primer Pokémon activo puede no registrar una baja
        # mientras un sustituto posterior sí. No escribe RAM ni escanea FCRAM.
        self._battle_trace_active = False
        self._battle_trace_sequence = 0
        self._battle_trace_path = LOG_DIR / "usum_battle_health_trace_latest.jsonl"


    def _battle_trace_write(self, payload: dict[str, object], *, reset: bool = False) -> None:
        """Escribe una línea JSON compacta del carril HP de batalla.

        La traza es deliberadamente pequeña: solo contiene el flag, las seis filas
        Max/Displayed/Actual y la party PK7 usada como testigo. Nunca incluye el
        bloque RAM completo ni ejecuta búsquedas adicionales.
        """
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            mode = "w" if reset else "a"
            with self._battle_trace_path.open(mode, encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        except OSError:
            pass

    def _battle_trace_start(self, current: SaveGameData) -> None:
        if self._battle_trace_active:
            return
        self._battle_trace_active = True
        self._battle_trace_sequence = 0
        self._battle_trace_write({
            "event": "battle-start",
            "created_at": datetime.now().isoformat(timespec="milliseconds"),
            "version": APP_VERSION,
            "party": [
                {
                    "party_index": index + 1,
                    "slot": int(getattr(pokemon, "slot", index + 1) or index + 1),
                    "species_id": int(getattr(pokemon, "species_id", 0) or 0),
                    "name": str(getattr(pokemon, "nickname", "") or getattr(pokemon, "species", "")),
                    "current_hp": int(getattr(pokemon, "current_hp", 0) or 0),
                    "max_hp": int(getattr(pokemon, "max_hp", 0) or 0),
                }
                for index, pokemon in enumerate(current.party[:6])
            ],
        }, reset=True)

    def _battle_trace_end(self, *, flag_value: int) -> None:
        if not self._battle_trace_active:
            return
        self._battle_trace_write({
            "event": "battle-end",
            "created_at": datetime.now().isoformat(timespec="milliseconds"),
            "flag": f"0x{int(flag_value):08X}",
            "sequence": int(self._battle_trace_sequence),
        })
        self._battle_trace_active = False

    def _battle_trace_sample(
        self, *, current: SaveGameData, max_raw: bytes, displayed_raw: bytes, actual_raw: bytes,
        validated_slots: Sequence[int], rejected_slots: Sequence[str],
    ) -> None:
        if not self._battle_trace_active:
            self._battle_trace_start(current)
        self._battle_trace_sequence += 1
        party = [pokemon for pokemon in current.party if int(getattr(pokemon, "species_id", 0) or 0) > 0][:6]
        party_maxes = [int(getattr(pokemon, "max_hp", 0) or 0) for pokemon in party]
        rows = []
        for index in range(len(party)):
            offset = index * USUM_BATTLE_PLAYER_STRIDE
            max_hp = int(struct.unpack_from("<H", max_raw, offset)[0])
            displayed_hp = int(struct.unpack_from("<H", displayed_raw, offset)[0])
            actual_hp = int(struct.unpack_from("<H", actual_raw, offset)[0])
            rows.append({
                "battle_row": index + 1,
                "max_hp": max_hp,
                "displayed_hp": displayed_hp,
                "actual_hp": actual_hp,
                "same_index_party_max": party_maxes[index] if index < len(party_maxes) else None,
                "same_index_valid": (index + 1) in set(validated_slots),
                "max_hp_candidate_party_slots": [
                    candidate + 1 for candidate, known_max in enumerate(party_maxes)
                    if known_max > 0 and known_max == max_hp
                ],
            })
        self._battle_trace_write({
            "event": "battle-sample",
            "created_at": datetime.now().isoformat(timespec="milliseconds"),
            "sequence": int(self._battle_trace_sequence),
            "party": [
                {
                    "party_index": index + 1,
                    "slot": int(getattr(pokemon, "slot", index + 1) or index + 1),
                    "species_id": int(getattr(pokemon, "species_id", 0) or 0),
                    "name": str(getattr(pokemon, "nickname", "") or getattr(pokemon, "species", "")),
                    "current_hp": int(getattr(pokemon, "current_hp", 0) or 0),
                    "max_hp": int(getattr(pokemon, "max_hp", 0) or 0),
                }
                for index, pokemon in enumerate(party)
            ],
            "rows": rows,
            "validated_slots": list(validated_slots),
            "rejected_slots": list(rejected_slots),
        })

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
    def _find_usum_process(processes: list[AzaharProcess]) -> AzaharProcess:
        title_matches = [process for process in processes if int(process.title_id) in USUM_TITLE_IDS]
        if len(title_matches) == 1:
            return title_matches[0]
        if len(title_matches) > 1:
            raise USUMLiveError("Azahar expone más de un proceso de UltraSol/UltraLuna y no se puede elegir con seguridad.")

        # USUM comparte el nombre de proceso ``niji_loc`` con Sol/Luna. Un
        # transporte que no exponga Title ID NO permite distinguir ambas parejas
        # de juegos, por lo que aceptar solo el nombre sería una suposición
        # peligrosa. UltraSol/UltraLuna exige siempre un Title ID retail exacto.
        running = ", ".join(
            f"{process.name}[{int(process.title_id):016X}]" for process in processes
        ) or "ninguno"
        raise USUMLiveError(
            "Azahar responde, pero no aparece Pokémon UltraSol/UltraLuna con un Title ID válido "
            f"(procesos visibles: {running})."
        )

    @staticmethod
    def _normalize_memory_requests(
        memory_blocks: Sequence[tuple[int, int]],
    ) -> tuple[tuple[int, int], ...]:
        result: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        for address, size in memory_blocks:
            key = (int(address), int(size))
            if key[0] <= 0 or key[1] <= 0:
                raise USUMLiveError("Se solicitó un bloque auxiliar de RAM inválido.")
            if key in seen:
                continue
            seen.add(key)
            result.append(key)
        return tuple(result)

    @staticmethod
    def _read_memory_blocks(
        client: AzaharRPCClient,
        memory_blocks: Sequence[tuple[int, int]],
    ) -> tuple[USUMLiveMemoryBlock, ...]:
        return tuple(
            USUMLiveMemoryBlock(address, client.read_memory(address, size))
            for address, size in memory_blocks
        )

    @staticmethod
    def _compose_party_slot(stored: bytes, stats: bytes) -> bytes:
        if len(stored) != PK7_STORED_SIZE or len(stats) != USUM_PARTY_STATS_SIZE:
            raise USUMLiveError("La captura sparse PK7 está truncada.")
        return bytes(stored) + bytes(stats) + (b"\0" * USUM_PARTY_TAIL_PADDING)

    @classmethod
    def _read_party_at(cls, client: AzaharRPCClient, base_address: int) -> tuple[bytes, ...]:
        """Reconstruye los seis PK7 desde el layout sparse real de la party SM."""
        slots: list[bytes] = []
        for index in range(6):
            slot_address = int(base_address) + index * USUM_PARTY_STRIDE
            stored = client.read_memory(slot_address, PK7_STORED_SIZE)
            stats = client.read_memory(slot_address + USUM_PARTY_STATS_OFFSET, USUM_PARTY_STATS_SIZE)
            slots.append(cls._compose_party_slot(stored, stats))
        return tuple(slots)

    def _parse_slots(self, slots: Sequence[bytes]) -> list[SavePokemon]:
        party: list[SavePokemon] = []
        for index, raw in enumerate(slots, start=1):
            pokemon = parse_pk7_party(bytes(raw), index, self.move_names)
            if pokemon is not None:
                party.append(pokemon)
        return party

    @staticmethod
    def _party_continuity_proof(
        live: Sequence[SavePokemon], current: SaveGameData,
    ) -> str | None:
        """Demuestra una candidata de party sin exigir que el ``main`` esté al día.

        La calibración inicial sigue prefiriendo la coincidencia completa por slot.
        Alpha.27 añade únicamente transiciones que pueden demostrarse a partir de
        identidades fuertes ya conocidas por RoleRun: mismos miembros reordenados,
        crecimiento/encogimiento por inclusión completa o una sustitución 1-a-1
        conservando todos los demás miembros. Nunca se acepta una party nueva que
        no conserve evidencia suficiente del estado conocido.
        """
        expected_by_slot = _slot_identity_map(current.party)
        observed_by_slot = _slot_identity_map(live)
        if not expected_by_slot or not observed_by_slot:
            return None
        if observed_by_slot == expected_by_slot:
            return "exact-slot-identity"

        expected = tuple(expected_by_slot[slot] for slot in sorted(expected_by_slot))
        observed = tuple(observed_by_slot[slot] for slot in sorted(observed_by_slot))
        if len(set(expected)) != len(expected) or len(set(observed)) != len(observed):
            return None

        expected_set = set(expected)
        observed_set = set(observed)
        # Mismos Pokémon, distinto orden: la identidad completa de TODOS los
        # miembros sigue demostrando la misma party aunque el usuario la reordene.
        if expected_set == observed_set and len(expected) >= 2:
            return "same-members-reordered"

        def is_subsequence(shorter, longer) -> bool:
            iterator = iter(longer)
            return all(any(candidate == value for candidate in iterator) for value in shorter)

        # Depositar uno o más Pokémon compacta el equipo. Todos los miembros que
        # permanecen deben ser identidades ya conocidas y mantener su orden relativo.
        if observed_set < expected_set and is_subsequence(observed, expected):
            # Con una party conocida de varios miembros exigimos al menos dos
            # testigos fuertes; evita aceptar por casualidad un único PK7 aislado.
            if len(expected) == 1 or len(observed) >= 2:
                return "party-shrank-known-subsequence"

        # Retirar/capturar hacia huecos libres conserva íntegramente la party
        # anterior y añade miembros. La party conocida completa actúa como testigo.
        if expected_set < observed_set and is_subsequence(expected, observed):
            if len(expected) >= 1:
                return "party-grew-known-supersequence"

        # Sustitución directa: mismo tamaño y exactamente un saliente/entrante.
        # Solo se acepta con >=2 identidades fuertes comunes y orden conservado.
        if len(expected) == len(observed) and len(expected) >= 3:
            common = expected_set & observed_set
            if len(common) == len(expected) - 1:
                expected_common = tuple(value for value in expected if value in common)
                observed_common = tuple(value for value in observed if value in common)
                if expected_common == observed_common:
                    return "single-replacement-known-members"
        return None

    @classmethod
    def _party_matches_witness(cls, live: Sequence[SavePokemon], current: SaveGameData) -> bool:
        return cls._party_continuity_proof(live, current) is not None

    @staticmethod
    def _party_is_compact_prefix(live: Sequence[SavePokemon]) -> bool:
        """Una party real ocupa siempre los slots 1..N sin huecos intermedios."""
        slots = sorted(int(pokemon.slot) for pokemon in live if int(pokemon.species_id) > 0)
        return bool(slots) and slots == list(range(1, len(slots) + 1))

    def _validate_candidate(
        self,
        client: AzaharRPCClient,
        base_address: int,
        current: SaveGameData,
    ) -> list[SavePokemon] | None:
        try:
            slots = self._read_party_at(client, int(base_address))
            parsed = self._parse_slots(slots)
        except (USUMLiveError, AzaharRPCError, OSError, ValueError, struct.error):
            return None
        if (
            not parsed
            or not self._party_is_compact_prefix(parsed)
            or not self._party_matches_witness(parsed, current)
        ):
            return None
        return parsed

    def _scan_reference_window(
        self,
        client: AzaharRPCClient,
        current: SaveGameData,
    ) -> tuple[int, list[SavePokemon]] | None:
        """Busca una base única alrededor de la referencia sin escribir RAM.

        No presupone alineación: cada byte de la ventana puede ser candidato. El
        coste es local (~4.7 KiB de lectura + validación en memoria) y solo ocurre
        en la primera calibración del proceso.
        """
        scan_start = USUM_PARTY_REFERENCE_ADDRESS - USUM_PARTY_SCAN_RADIUS
        scan_size = USUM_PARTY_SPAN + 2 * USUM_PARTY_SCAN_RADIUS
        region = bytes(client.read_memory(scan_start, scan_size))
        if len(region) != scan_size:
            return None

        expected = _slot_identity_map(current.party)
        if not expected:
            raise USUMLiveError(
                "El main cargado no contiene ningún Pokémon testigo; alpha.3 no puede demostrar la party viva."
            )

        expected_ids = set(expected.values())
        matches: list[tuple[int, list[SavePokemon], str, int]] = []
        for delta in range(0, 2 * USUM_PARTY_SCAN_RADIUS + 1):
            base_offset = delta
            party: list[SavePokemon] = []
            failed = False
            for index in range(6):
                start = base_offset + index * USUM_PARTY_STRIDE
                stored = region[start:start + PK7_STORED_SIZE]
                stats_start = start + USUM_PARTY_STATS_OFFSET
                stats = region[stats_start:stats_start + USUM_PARTY_STATS_SIZE]
                if len(stored) != PK7_STORED_SIZE or len(stats) != USUM_PARTY_STATS_SIZE:
                    failed = True
                    break
                try:
                    raw = self._compose_party_slot(stored, stats)
                    pokemon = parse_pk7_party(raw, index + 1, self.move_names)
                except (USUMLiveError, ValueError, struct.error):
                    failed = True
                    break
                if pokemon is not None:
                    party.append(pokemon)
            if failed or not party or not self._party_is_compact_prefix(party):
                continue
            proof = self._party_continuity_proof(party, current)
            if proof is None:
                continue
            overlap = len(expected_ids & {_identity(pokemon) for pokemon in party})
            matches.append((scan_start + delta, party, proof, overlap))

        if not matches:
            return None
        # La ventana puede contener la misma party vista un stride más tarde. No
        # elegimos por cercanía: elegimos únicamente la candidata respaldada por
        # el MAYOR número de identidades fuertes conocidas. Un empate sigue siendo
        # ambigüedad real y se rechaza.
        best_overlap = max(item[3] for item in matches)
        strongest = [item for item in matches if item[3] == best_overlap]
        if len(strongest) == 1:
            base, party, _proof, _overlap = strongest[0]
            return base, party
        raise USUMLiveError(
            "La calibración de la party SM encontró más de una base con la misma evidencia fuerte. "
            "No se eligió ninguna por cercanía ni por suposición."
        )

    def _locate_party_base(
        self,
        client: AzaharRPCClient,
        process: AzaharProcess,
        current: SaveGameData,
    ) -> int:
        key = (int(process.process_id), int(process.title_id), str(process.name))
        cached = self._party_bases_by_process.get(key)
        if cached is not None:
            # La base ya fue demostrada para este proceso. Se revalida su estructura
            # después en cada snapshot, pero no contra el main: así el equipo puede
            # cambiar jugando sin exigir guardar de nuevo.
            self._last_resolution = {
                "source": "cache demostrada",
                "address": int(cached),
                "witness_count": len(current.party),
            }
            return int(cached)

        if not current.party:
            raise USUMLiveError(
                "El main cargado no tiene Pokémon en el equipo. Alpha.3 necesita al menos un PK7 testigo para calibrar RAM."
            )

        exact = self._validate_candidate(client, USUM_PARTY_REFERENCE_ADDRESS, current)
        if exact is not None:
            base = int(USUM_PARTY_REFERENCE_ADDRESS)
            proof = self._party_continuity_proof(exact, current) or "structural-only-rejected"
            self._party_bases_by_process[key] = base
            self._last_resolution = {
                "source": (
                    "referencia PKMN-NTR + testigo completo"
                    if proof == "exact-slot-identity" else
                    f"referencia pública + {proof}"
                ),
                "address": base,
                "witness_count": len(exact),
                "continuity_proof": proof,
            }
            return base

        scanned = self._scan_reference_window(client, current)
        if scanned is not None:
            base, party = scanned
            proof = self._party_continuity_proof(party, current) or "structural-only-rejected"
            self._party_bases_by_process[key] = int(base)
            self._last_resolution = {
                "source": (
                    "ventana de solo lectura + testigo completo"
                    if proof == "exact-slot-identity" else
                    f"ventana de solo lectura + {proof}"
                ),
                "address": int(base),
                "witness_count": len(party),
                "continuity_proof": proof,
            }
            return int(base)

        self._last_resolution = {
            "source": "sin resolver",
            "address": None,
            "witness_count": len(current.party),
        }
        raise USUMLiveError(
            "No se pudo demostrar la dirección viva del equipo de UltraSol/UltraLuna. "
            "Se probó la referencia pública y una ventana local de solo lectura, pero ninguna party PK7 pudo "
            "vincularse por identidades fuertes con el último estado conocido (coincidencia, reorden, alta/baja o "
            "sustitución 1-a-1 demostrable). No se escribió ningún byte. Pulsa F5; si persiste, necesitaremos "
            "un diagnóstico de RAM, no un guardado forzado."
        )

    def _preserve_known_labels(self, pokemon: SavePokemon, current: SaveGameData) -> SavePokemon:
        previous = next((item for item in current.party if _identity(item) == _identity(pokemon)), None)
        if previous is None:
            return pokemon
        pokemon.species = previous.species
        pokemon.nickname = previous.nickname
        # held_item y ability ya se decodifican del PK7 vivo. Preservarlos desde
        # la captura anterior congelaba cambios hechos dentro del propio juego
        # (p. ej. quitar una MT equipada). Solo conservamos las etiquetas de
        # especie/nickname que este lector mínimo aún no localiza por sí solo.
        return pokemon

    def _build_game(
        self,
        slots: Sequence[bytes],
        current: SaveGameData,
        process: AzaharProcess,
        party_base: int,
        *,
        live_write: bool = False,
    ) -> SaveGameData:
        party = [
            self._preserve_known_labels(pokemon, current)
            for pokemon in self._parse_slots(slots)
        ]
        if not party:
            raise USUMLiveError("La captura estable de UltraSol/UltraLuna no contiene ningún Pokémon en el equipo.")
        return SaveGameData(
            game=current.game,
            save_type=f"{current.save_type} + Azahar RPC (USUM en vivo)",
            generation=current.generation,
            trainer=current.trainer,
            party=party,
            raw={
                **current.raw,
                "liveSync": True,
                "liveWrite": bool(live_write),
                "liveProcess": process.name,
                "liveTitleId": f"{process.title_id:016X}",
                "liveProfile": "USUM-alpha.43-parity-candidate",
                "livePartyBase": f"0x{int(party_base):08X}",
            },
        )

    def _capture(
        self,
        current: SaveGameData,
        *,
        memory_blocks: Sequence[tuple[int, int]],
    ) -> USUMLiveSnapshot:
        requests = self._normalize_memory_requests(memory_blocks)
        try:
            with self.client_factory() as client:
                process = self._find_usum_process(client.process_list())
                client.set_process(process.process_id)
                party_base = self._locate_party_base(client, process, current)
                runtime_span = 6 * USUM_PARTY_STRIDE
                for attempt in range(1, self.snapshot_attempts + 1):
                    first_party = self._read_party_at(client, party_base)
                    first_blocks = self._read_memory_blocks(client, requests)
                    first_runtime = bytes(client.read_memory(int(party_base), runtime_span))
                    if len(first_runtime) != runtime_span:
                        raise USUMLiveError("La captura runtime completa de la party quedó truncada.")
                    if self.stable_delay:
                        time.sleep(self.stable_delay)
                    second_party = self._read_party_at(client, party_base)
                    second_blocks = self._read_memory_blocks(client, requests)
                    second_runtime = bytes(client.read_memory(int(party_base), runtime_span))
                    if (
                        first_party != second_party
                        or first_blocks != second_blocks
                        or first_runtime != second_runtime
                    ):
                        continue
                    # La validación estructural se repite SIEMPRE, incluso con base cacheada.
                    game = self._build_game(second_party, current, process, party_base)
                    return USUMLiveSnapshot(
                        game=game,
                        process=process,
                        attempts=attempt,
                        party_base=int(party_base),
                        memory_blocks=second_blocks,
                        runtime_party_region=second_runtime,
                    )
        except AzaharRPCError as exc:
            raise USUMLiveError(str(exc)) from exc

        raise USUMLiveError(
            "El equipo de UltraSol/UltraLuna cambió durante todas las dobles lecturas; se reintentará automáticamente."
        )

    def read(
        self,
        current: SaveGameData,
        memory_blocks: Sequence[tuple[int, int]] = (),
    ) -> USUMLiveSnapshot:
        return self._capture(current, memory_blocks=memory_blocks)

    def read_monitor(
        self,
        current: SaveGameData,
        memory_blocks: Sequence[tuple[int, int]] = (),
    ) -> USUMLiveSnapshot:
        return self._capture(current, memory_blocks=memory_blocks)

    def read_battle_probe(self, current: SaveGameData) -> USUMBattleProbe | None:
        """Lee PS visibles de batalla sin mezclarlos con la captura estable.

        La dirección procede de código público específico de Sun/Moon, pero
        RoleRun exige dos pruebas en la ejecución actual antes de usarla:

        1. el flag de batalla debe valer 0x00040001 antes Y después de leer HP;
        2. el Max HP de cada slot ocupado debe coincidir exactamente con el Max
           HP de la party PK7 live ya validada.

        Si cualquiera de esas pruebas falla, devuelve una sonda sin ``health_game``
        y el detector conserva el fallback post-combate de alpha.40.
        """
        try:
            with self.client_factory() as client:
                process = self._find_usum_process(client.process_list())
                client.set_process(process.process_id)

                before = bytes(client.read_memory(USUM_BATTLE_STATE_ADDRESS, 4))
                if len(before) != 4:
                    return None
                before_state = struct.unpack_from("<I", before, 0)[0]
                if int(before_state) != USUM_BATTLE_STATE_ACTIVE_VALUE:
                    self._battle_trace_end(flag_value=int(before_state))
                    return USUMBattleProbe(
                        state="none", validated=True,
                        reason=f"battle_flag=0x{int(before_state):08X}",
                    )

                self._battle_trace_start(current)

                party = [pokemon for pokemon in current.party if int(pokemon.species_id) > 0]
                count = min(6, len(party))
                if count <= 0:
                    return USUMBattleProbe(
                        state="battle", validated=False,
                        reason="La party viva no contiene slots ocupados para validar HP de batalla.",
                    )

                span = ((count - 1) * USUM_BATTLE_PLAYER_STRIDE) + USUM_BATTLE_HP_SIZE
                max_raw = bytes(client.read_memory(USUM_BATTLE_PLAYER_MAX_HP_BASE, span))
                displayed_raw = bytes(client.read_memory(USUM_BATTLE_PLAYER_DISPLAY_HP_BASE, span))
                actual_raw = bytes(client.read_memory(USUM_BATTLE_PLAYER_ACTUAL_HP_BASE, span))
                after = bytes(client.read_memory(USUM_BATTLE_STATE_ADDRESS, 4))
                if (
                    len(max_raw) != span or len(displayed_raw) != span
                    or len(actual_raw) != span or len(after) != 4
                ):
                    return None
                after_state = struct.unpack_from("<I", after, 0)[0]
                if int(after_state) != USUM_BATTLE_STATE_ACTIVE_VALUE:
                    # El combate terminó mientras leíamos. No mezclamos dos estados.
                    return None
        except Exception:
            return None

        displayed_pairs: list[tuple[int, int]] = []
        actual_pairs: list[tuple[int, int]] = []
        clones: list[SavePokemon] = []
        validated_slots: list[int] = []
        rejected_slots: list[str] = []
        for index, pokemon in enumerate(party):
            offset = index * USUM_BATTLE_PLAYER_STRIDE
            max_hp = int(struct.unpack_from("<H", max_raw, offset)[0])
            displayed_hp = int(struct.unpack_from("<H", displayed_raw, offset)[0])
            actual_hp = int(struct.unpack_from("<H", actual_raw, offset)[0])
            known_max = int(getattr(pokemon, "max_hp", 0) or 0)

            # Alpha.56: la validación del carril de batalla es POR SLOT. La
            # fuente USUMCheatMenu documenta seis filas del equipo del jugador
            # con stride 0x330; aun así RoleRun solo publica HP para una fila si
            # su Max HP coincide con la PartyData live de ese mismo slot.
            #
            # Antes, una sola discrepancia invalidaba los seis slots y hacía que
            # cualquier KO se viera únicamente al finalizar el combate. Esto es
            # especialmente frágil tras un PC→party, donde un slot runtime puede
            # tardar en converger aunque los demás sigan siendo demostrables.
            valid_slot = (
                known_max > 0 and max_hp == known_max
                and 0 <= displayed_hp <= max_hp
                and 0 <= actual_hp <= max_hp
            )
            if valid_slot:
                validated_slots.append(index + 1)
                displayed_pairs.append((displayed_hp, max_hp))
                actual_pairs.append((actual_hp, max_hp))
                clones.append(replace(
                    pokemon,
                    moves=list(pokemon.moves),
                    move_ids=list(pokemon.move_ids),
                    markings=list(pokemon.markings),
                    current_hp=displayed_hp,
                    max_hp=max_hp,
                ))
            else:
                # Un slot no demostrado no puede contaminar a los demás. Para él
                # conservamos la lectura de party normal (que es segura pero puede
                # ir retrasada durante el combate), de modo que jamás inventamos HP.
                rejected_slots.append(
                    f"{index + 1}:{max_hp}/{displayed_hp}/{actual_hp} vs PK7 {known_max}"
                )
                displayed_pairs.append((int(getattr(pokemon, "current_hp", 0) or 0), known_max))
                actual_pairs.append((int(getattr(pokemon, "current_hp", 0) or 0), known_max))
                clones.append(replace(
                    pokemon,
                    moves=list(pokemon.moves),
                    move_ids=list(pokemon.move_ids),
                    markings=list(pokemon.markings),
                ))

        self._battle_trace_sample(
            current=current, max_raw=max_raw, displayed_raw=displayed_raw, actual_raw=actual_raw,
            validated_slots=validated_slots, rejected_slots=rejected_slots,
        )

        if not validated_slots:
            return USUMBattleProbe(
                state="battle", validated=False,
                reason=(
                    "ningún slot de batalla pudo vincularse por Max HP a la party PK7 live; "
                    + "; ".join(rejected_slots)
                ),
            )

        health = SaveGameData(
            game=current.game,
            save_type=f"{current.save_type} + PS visibles batalla Azahar RPC",
            generation=current.generation,
            trainer=current.trainer,
            party=clones,
            raw={
                **current.raw,
                "liveBattleHealth": True,
                "liveBattleState": "battle",
                "liveBattleHealthSource": "SM displayed HP",
                "liveBattleActualHp": [pair[0] for pair in actual_pairs],
            },
        )
        reason = f"flag activo + Max HP validado por slot ({len(validated_slots)}/{count})"
        if rejected_slots:
            reason += "; ignorados: " + "; ".join(rejected_slots)
        return USUMBattleProbe(
            state="battle", health_game=health,
            hp_pairs=tuple(displayed_pairs), actual_hp_pairs=tuple(actual_pairs),
            validated=True, reason=reason,
        )

    def runtime_state(self) -> dict[str, object]:
        return {
            "party_reference": f"0x{USUM_PARTY_REFERENCE_ADDRESS:08X}",
            "party_stride": USUM_PARTY_STRIDE,
            "party_size": PK7_PARTY_SIZE,
            "last_resolution": dict(self._last_resolution),
            "cached_processes": [
                {"process_id": process_id, "title_id": f"{title_id:016X}", "name": name, "address": f"0x{address:08X}"}
                for (process_id, title_id, name), address in sorted(self._party_bases_by_process.items())
            ],
        }

    def _ensure_pc_live_cache_for_team_write(
        self, *, client, process: AzaharProcess, party_base: int, original_capture: Sequence[bytes],
        current: SaveGameData, host_memory,
    ) -> tuple[tuple[int, int, str, int], int, int, int, int, int]:
        """Demuestra BoxPokemon en el propio flujo Equipo↔PC si aún no hay caché.

        Alpha.37 elimina el requisito artificial de abrir CAJAS PC antes de usar
        ENVIAR AL PC / PC→Equipo. La operación usa la misma prueba live ya
        validada desde alpha.25: referencia guest conocida solo como CANDIDATA,
        copia host derivada desde una party host demostrada y matriz completa
        32×30 estable con host == guest. El ``main`` no interviene.
        """
        session = (int(process.title_id), int(process.process_id), str(process.name), int(party_base))
        cached = self._pc_live_cache
        if (
            cached is not None and cached[0] == session
            and int(cached[4]) == USUM_PC_BOX_COUNT
            and int(cached[5]) == USUM_PC_BOX_SLOT_COUNT
        ):
            return cached

        try:
            party_targets = host_memory.find_party_targets(
                slot_raws=original_capture, stored_size=PK7_STORED_SIZE,
                stats_offset=USUM_PARTY_STATS_OFFSET, stats_size=USUM_PARTY_STATS_SIZE,
                stride=USUM_PARTY_STRIDE,
            )
        except Exception as exc:
            raise USUMLiveError(
                "RoleRun no pudo demostrar una copia host de la party necesaria para localizar el PC vivo. "
                "No se escribió ningún byte."
            ) from exc
        if not party_targets:
            raise USUMLiveError(
                "RoleRun no encontró una copia host demostrable de la party para localizar el PC vivo. "
                "No se escribió ningún byte."
            )

        try:
            pid, host_base, guest_base, _parsed, evaluated = self._resolve_pc_from_direct_pk7_matrix(
                client=client, host_memory=host_memory, party_base=int(party_base),
                party_targets=party_targets, current=current, anchors=(),
                box_count=USUM_PC_BOX_COUNT, box_slot_count=USUM_PC_BOX_SLOT_COUNT,
            )
        except Exception as exc:
            raise USUMLiveError(
                "RoleRun no pudo demostrar automáticamente la matriz PC viva de esta sesión. "
                "No se escribió ningún byte. " + str(exc)
            ) from exc

        delta = int(guest_base) - int(party_base)
        matching_party_targets = [
            target for target in party_targets
            if int(target.pid) == int(pid)
            and int(target.host_party_base) + delta == int(host_base)
        ]
        self._pc_party_anchor = (
            session,
            HostPartyTarget(
                int(matching_party_targets[0].pid),
                str(matching_party_targets[0].exe_name),
                int(matching_party_targets[0].host_party_base),
            ),
        ) if len(matching_party_targets) == 1 else None
        self._pc_live_cache = (
            session, int(pid), int(host_base), int(guest_base),
            USUM_PC_BOX_COUNT, USUM_PC_BOX_SLOT_COUNT,
        )
        self._pc_last_resolution = {
            "source": "team-write fast finite candidates -> full 960-slot host==guest",
            "host_base": int(host_base), "guest_base": int(guest_base),
            "box_count": USUM_PC_BOX_COUNT, "box_slot_count": USUM_PC_BOX_SLOT_COUNT,
            "evaluated": evaluated,
        }
        return self._pc_live_cache

    def reset_runtime_state(self) -> None:
        self._party_bases_by_process.clear()
        self._last_resolution = {}


class USUMLiveWriter:
    """Escritor vivo seguro de roles y movimientos del equipo SM.

    La base de party debe haber sido demostrada por ``USUMLiveReader``. Cada cambio
    valida identidad + estado anterior, modifica únicamente campos del PK7
    documentados (MarkingValue o moves/PP/PP Ups), recalcula checksum y usa la
    vía de escritura ya validada en alpha.12. Si la verificación falla, restaura
    los bytes originales de todos los slots tocados.
    """

    def __init__(
        self,
        reader: USUMLiveReader,
        *,
        diagnostic_dir: Path | None = None,
        diagnostic_delays: Sequence[float] = (0.05, 0.15, 0.50),
        host_memory_factory: Callable[[], object] | None = None,
        move_pp_for: Callable[[int], int] | None = None,
        move_allowed: Callable[[int], bool] | None = None,
        personal_for: Callable[[int, int], ORASPersonalStats | None] | None = None,
    ) -> None:
        self.reader = reader
        custom_diagnostic_dir = Path(diagnostic_dir) if diagnostic_dir is not None else None
        self.diagnostic_dir = custom_diagnostic_dir or (LOG_DIR / "USUM-Write-Diagnostics")
        self.diagnostic_latest_path = (
            self.diagnostic_dir / "usum_write_diagnostic_latest.json"
            if custom_diagnostic_dir is not None else
            LOG_DIR / "usum_write_diagnostic_latest.json"
        )
        self.diagnostic_delays = tuple(max(0.0, float(value)) for value in diagnostic_delays)
        self.last_diagnostic_path: Path | None = None
        self.host_memory_factory = host_memory_factory or WindowsProcessMemory
        self.move_pp_for = move_pp_for
        self.move_allowed = move_allowed
        # Para pasar un PK7 stored del PC a la party necesitamos reconstruir
        # nivel/PS/stats. Esta función DEBE venir del Personal efectivo de la ROM
        # activa (incluyendo randomizer/mod), nunca de una tabla vanilla asumida.
        self.personal_for = personal_for
        # kind -> (windows_pid, host_base, guest_base, last_verified_block)
        self._utility_block_cache: dict[str, tuple[int, int, int, bytes]] = {}
        self._tm_inventory_session: tuple[int, int, str, int] | None = None
        # Alpha.53: para enseñar MT no se escribe la mochila. Se conserva una
        # prueba guest independiente: (sesión, guest_items_base, bloque validado).
        # Las utilidades que SÍ modifican inventario siguen exigiendo host+guest.
        self._tm_guest_inventory_anchor: tuple[tuple[int, int, str, int], int, bytes] | None = None
        # Sesión guest + ancla host de party demostrada por la cadena completa
        # party host -> mochila host -> mochila guest. Para una MT, esta prueba
        # permite distinguir de forma segura la party viva aunque Azahar conserve
        # otras copias/buffers byte-a-byte idénticos en el proceso.
        self._tm_party_anchor: tuple[tuple[int, int, str, int], HostPartyTarget] | None = None
        # Alpha.21: (sesión guest, pid host, base host, base guest, cajas, slots).
        # La base se reutiliza solo tras volver a demostrar host==guest y parsear
        # la matriz PK7 completa; que la caché exista nunca basta por sí solo.
        self._pc_live_cache: tuple[tuple[int, int, str, int], int, int, int, int, int] | None = None
        # Alpha.27: una lectura PC demostrada host↔guest identifica también qué
        # copia host de la party pertenece a ese mismo backing FCRAM. Se conserva
        # solo para la sesión exacta y se relee completa antes de cualquier uso.
        self._pc_party_anchor: tuple[tuple[int, int, str, int], HostPartyTarget] | None = None
        self._pc_last_resolution: dict[str, object] = {}
        # Alpha.42: la lectura de progreso es solo lectura y mantiene su propia
        # procedencia. Un fallo del descubrimiento estructural pesado entra en
        # cooldown para no repetir búsquedas FCRAM en cada tick del monitor.
        self._last_badge_source: str | None = None
        self._badge_full_scan_failed_at = 0.0

    @property
    def last_badge_source(self) -> str | None:
        return self._last_badge_source

    @staticmethod
    def _pokemon_identity(pokemon: SavePokemon) -> str:
        if int(pokemon.pid or 0) or int(pokemon.tid or 0) or int(pokemon.sid or 0):
            return f"{int(pokemon.species_id)}:{int(pokemon.pid or 0)}:{int(pokemon.tid or 0)}:{int(pokemon.sid or 0)}"
        return f"fallback:{int(pokemon.species_id)}:{(pokemon.nickname or pokemon.species).strip().casefold()}"

    @staticmethod
    def _role_from_plain(data: bytes | bytearray) -> str:
        marking_value = struct.unpack_from("<H", data, 0x16)[0]
        markings = [bool((marking_value >> (index * 2)) & 0b11) for index in range(6)]
        return role_from_markings(markings, layout=2)[0]

    @staticmethod
    def _set_role(data: bytearray, role: str) -> None:
        role = canonical_role(role)
        try:
            selected = int(ROLE_TO_MARKING[role])
        except KeyError as exc:
            raise USUMLiveError(f"El rol '{role}' no es válido para UltraSol/UltraLuna en vivo.") from exc
        value = struct.unpack_from("<H", data, 0x16)[0]
        value &= 0xF000  # conserva los 4 bits superiores no usados por las seis marcas
        if selected >= 0:
            value |= 0b01 << (selected * 2)
        struct.pack_into("<H", data, 0x16, value)

    @staticmethod
    def _refresh_checksum(data: bytearray) -> None:
        struct.pack_into("<H", data, 0x06, _checksum67(data))

    def _replace_move(self, data: bytearray, change: PendingChange | PendingTMTeach) -> None:
        index = int(change.move_slot) - 1
        if not 0 <= index < 4:
            raise USUMLiveError(f"El hueco de movimiento {change.move_slot} no es válido.")

        current_move = struct.unpack_from("<H", data, _PK7_MOVE_OFFSETS[index])[0]
        if current_move != int(change.old_move_id or 0):
            raise USUMLiveError(
                f"{change.pokemon} cambió ese movimiento dentro del juego. Pulsa F5 y vuelve a intentarlo."
            )

        move_id = int(change.new_move_id or 0)
        if move_id == 0:
            # Borrar compacta movimiento, PP y PP Ups para no dejar huecos.
            for move_index in range(index, 3):
                next_index = move_index + 1
                struct.pack_into(
                    "<H", data, _PK7_MOVE_OFFSETS[move_index],
                    struct.unpack_from("<H", data, _PK7_MOVE_OFFSETS[next_index])[0],
                )
                data[_PK7_MOVE_PP_OFFSETS[move_index]] = data[_PK7_MOVE_PP_OFFSETS[next_index]]
                data[_PK7_MOVE_PP_UPS_OFFSETS[move_index]] = data[_PK7_MOVE_PP_UPS_OFFSETS[next_index]]
            struct.pack_into("<H", data, _PK7_MOVE_OFFSETS[3], 0)
            data[_PK7_MOVE_PP_OFFSETS[3]] = 0
            data[_PK7_MOVE_PP_UPS_OFFSETS[3]] = 0
            return

        if self.move_allowed is None or not bool(self.move_allowed(move_id)):
            raise USUMLiveError(
                f"El movimiento #{move_id} no está demostrado como disponible en este guardado de UltraSol/UltraLuna."
            )
        if self.move_pp_for is None:
            raise USUMLiveError("No está disponible la tabla de PP de Gen 7; no se escribió ningún byte.")
        try:
            base_pp = int(self.move_pp_for(move_id))
        except Exception as exc:
            raise USUMLiveError(
                f"No se pudo validar el PP del movimiento #{move_id}; no se escribió ningún byte."
            ) from exc
        pp_ups = int(data[_PK7_MOVE_PP_UPS_OFFSETS[index]])
        if not 0 <= pp_ups <= 3 or not 1 <= base_pp <= 255:
            raise USUMLiveError(f"Los PP del movimiento #{move_id} no son válidos para PK7.")
        pp = base_pp * (5 + pp_ups) // 5
        if pp > 0xFF:
            raise USUMLiveError(f"El PP calculado para el movimiento #{move_id} no cabe en PK7.")
        struct.pack_into("<H", data, _PK7_MOVE_OFFSETS[index], move_id)
        data[_PK7_MOVE_PP_OFFSETS[index]] = pp

    def _capture_stable_party(self, client, party_base: int) -> tuple[list[bytes], int]:
        for attempt in range(1, self.reader.snapshot_attempts + 1):
            first = self.reader._read_party_at(client, party_base)
            if self.reader.stable_delay:
                time.sleep(self.reader.stable_delay)
            second = self.reader._read_party_at(client, party_base)
            if first == second:
                self.reader._parse_slots(second)
                return second, attempt
        raise USUMLiveError(
            "El equipo de UltraSol/UltraLuna cambió durante todas las dobles lecturas; no se escribió ningún byte."
        )

    def _read_party_members(self, slots: Sequence[bytes], current: SaveGameData) -> dict[int, SavePokemon]:
        party: dict[int, SavePokemon] = {}
        for index, raw in enumerate(slots, start=1):
            pokemon = parse_pk7_party(raw, index, self.reader.move_names)
            if pokemon is not None:
                party[index] = self.reader._preserve_known_labels(pokemon, current)
        return party

    def _read_proven_party_injection_windows(
        self, *, client, host_memory, host_pid: int, host_party_base: int, guest_party_base: int,
        expected_sparse: dict[int, SavePokemon],
    ) -> tuple[bytes, ...]:
        """Demuestra las ventanas contiguas de 0x104 usadas para inyección de party.

        Importante: el layout *vivo* de UltraSol/UltraLuna que RoleRun ya validó es sparse:
        0xE8 bytes stored al comienzo del slot y 0x16 bytes de stats en +0x158.
        Por tanto los bytes 0xE8..0x103 de la ventana contigua NO se interpretan
        como Party Stats del estado actual. Alpha.33 hacía precisamente esa
        suposición y rechazaba parties reales.

        La ventana se acepta únicamente si dos lecturas host y guest son idénticas
        y estables, y si su prefijo stored de 0xE8 demuestra exactamente las mismas
        identidades fuertes que el reader sparse ya validado. El tramo restante se
        conserva opaco para rollback.
        """
        handle = None
        try:
            handle = host_memory.open_process(int(host_pid))

            def capture() -> tuple[tuple[bytes, ...], tuple[bytes, ...]]:
                host_slots: list[bytes] = []
                guest_slots: list[bytes] = []
                for index in range(6):
                    host_addr = int(host_party_base) + index * USUM_PARTY_STRIDE
                    guest_addr = int(guest_party_base) + index * USUM_PARTY_STRIDE
                    host_slots.append(bytes(host_memory.read(handle, host_addr, PK7_PARTY_SIZE)))
                    guest_slots.append(bytes(client.read_memory(guest_addr, PK7_PARTY_SIZE)))
                return tuple(host_slots), tuple(guest_slots)

            host_first, guest_first = capture()
            if self.reader.stable_delay:
                time.sleep(max(0.01, float(self.reader.stable_delay)))
            host_second, guest_second = capture()
        except Exception as exc:
            raise USUMLiveError(
                "No se pudieron demostrar las ventanas de inyección 0x104 de la party UltraSol/UltraLuna."
            ) from exc
        finally:
            if handle is not None:
                try:
                    host_memory.close_process(handle)
                except Exception:
                    pass

        if not (host_first == guest_first == host_second == guest_second):
            raise USUMLiveError(
                "Las ventanas de inyección de la party no fueron estables o no coincidieron host↔guest; "
                "no se escribió ningún byte."
            )

        actual_ids: dict[int, tuple[int, int, int, int]] = {}
        for slot, raw in enumerate(guest_second, start=1):
            stored = bytes(raw[:PK7_STORED_SIZE])
            if not any(stored):
                continue
            try:
                plain, _encrypted = _plain_pk7_stored_with_state(stored)
            except Exception as exc:
                raise USUMLiveError(
                    f"El prefijo stored del slot {slot} no contiene un PK7 válido de 0xE8 bytes."
                ) from exc
            species = int(struct.unpack_from("<H", plain, 0x08)[0])
            # Igual que en BoxPokemon, un slot físico vacío puede estar cifrado
            # y contener muchos bytes no-cero. species=0 es la semántica real
            # de vacío; no debe aparecer como una identidad espuria.
            if species == 0:
                continue
            pid = int(struct.unpack_from("<I", plain, 0x18)[0])
            tid = int(struct.unpack_from("<H", plain, 0x0C)[0])
            sid = int(struct.unpack_from("<H", plain, 0x0E)[0])
            actual_ids[int(slot)] = (species, pid, tid, sid)

        expected_ids = {
            int(slot): (
                int(p.species_id), int(p.pid or 0), int(p.tid or 0), int(p.sid or 0),
            )
            for slot, p in expected_sparse.items()
        }
        if actual_ids != expected_ids:
            raise USUMLiveError(
                "Las ventanas de inyección no coinciden por identidad con la party sparse ya validada. "
                "RoleRun no escribirá sobre dos estados distintos."
            )
        return guest_second

    def _save_partycount_probe(self, payload: dict[str, object]) -> Path | None:
        """Guarda una sonda acotada para localizar el tamaño lógico real de party.

        La sonda no escanea FCRAM ni escribe memoria. Solo conserva dos ventanas
        públicas/acotadas de USUM para poder comparar una transición 6↔5 hecha
        desde el propio juego y demostrar qué byte/campo cambia realmente.
        """
        wrapped = {
            "format": "rolerun-usum-partycount-probe-v1",
            "version": APP_VERSION,
            "created_at": datetime.now().isoformat(timespec="milliseconds"),
            **payload,
        }
        try:
            self.diagnostic_dir.mkdir(parents=True, exist_ok=True)
            count = int(payload.get("party_count", -1))
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            archive = self.diagnostic_dir / f"usum-partycount-{count}-{stamp}.json"
            latest = LOG_DIR / "usum_partycount_probe_latest.json"
            text = json.dumps(wrapped, ensure_ascii=False, indent=2, sort_keys=True)
            archive.write_text(text, encoding="utf-8")
            latest.parent.mkdir(parents=True, exist_ok=True)
            latest.write_text(text, encoding="utf-8")
            self.last_diagnostic_path = latest
            return latest
        except Exception:
            return None

    def _collect_partycount_probe(self, *, client, expected_sparse: dict[int, SavePokemon]) -> Path | None:
        """Captura ventanas pequeñas alrededor de las dos parties USUM publicadas.

        No busca firmas ni recorre regiones grandes. Las dos ventanas cubren los
        seis slots físicos (6×0x1E4) y un margen antes/después donde podría vivir
        metadata asociada. Si existe una sonda previa con otro tamaño, alpha.49
        calcula además todos los bytes que cambiaron exactamente N→M.
        """
        count = len(expected_sparse)
        margin_before = 0x100
        margin_after = 0x300
        span = (6 * USUM_PARTY_STRIDE) + margin_before + margin_after
        regions: dict[str, dict[str, object]] = {}
        for name, base in (
            ("primary", int(USUM_PARTY_REFERENCE_ADDRESS)),
            ("alternate", int(USUM_PARTY_ALTERNATE_REFERENCE_ADDRESS)),
        ):
            start = int(base) - margin_before
            try:
                first = bytes(client.read_memory(start, span))
                if self.reader.stable_delay:
                    time.sleep(max(0.01, float(self.reader.stable_delay)))
                second = bytes(client.read_memory(start, span))
                stable = first == second
                raw = second
                regions[name] = {
                    "base": f"0x{int(base):08X}",
                    "start": f"0x{start:08X}",
                    "size": int(span),
                    "stable": bool(stable),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "raw_hex": raw.hex(),
                }
            except Exception as exc:
                regions[name] = {
                    "base": f"0x{int(base):08X}",
                    "start": f"0x{start:08X}",
                    "size": int(span),
                    "error": f"{type(exc).__name__}: {exc}",
                }

        payload: dict[str, object] = {
            "stage": "alpha49-bounded-partycount-probe",
            "party_count": int(count),
            "party_slots": sorted(int(slot) for slot in expected_sparse),
            "regions": regions,
            "fcram_scan_attempted": False,
            "writes_attempted": False,
        }

        # Busca la sonda más reciente con otro tamaño y calcula diferencias.
        try:
            candidates = sorted(
                self.diagnostic_dir.glob("usum-partycount-*-*.json"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            previous = None
            previous_path = None
            for path in candidates:
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if int(data.get("party_count", -1)) != int(count):
                    previous = data
                    previous_path = path
                    break
            if previous is not None:
                prev_count = int(previous.get("party_count", -1))
                comparisons: dict[str, object] = {}
                for name, current_entry in regions.items():
                    previous_entry = (previous.get("regions") or {}).get(name) if isinstance(previous.get("regions"), dict) else None
                    if not isinstance(previous_entry, dict):
                        continue
                    cur_hex = current_entry.get("raw_hex")
                    old_hex = previous_entry.get("raw_hex")
                    if not isinstance(cur_hex, str) or not isinstance(old_hex, str):
                        continue
                    cur = bytes.fromhex(cur_hex)
                    old = bytes.fromhex(old_hex)
                    start = int(str(current_entry.get("start", "0")), 16)
                    changed = []
                    exact_count_transitions = []
                    for offset, (before, after) in enumerate(zip(old, cur)):
                        if before == after:
                            continue
                        entry = {
                            "address": f"0x{start + offset:08X}",
                            "offset": f"0x{offset:X}",
                            "before": int(before),
                            "after": int(after),
                        }
                        if len(changed) < 512:
                            changed.append(entry)
                        if before == prev_count and after == count:
                            exact_count_transitions.append(entry)
                    comparisons[name] = {
                        "previous_count": int(prev_count),
                        "current_count": int(count),
                        "changed_byte_count": sum(1 for a, b in zip(old, cur) if a != b),
                        "changed_bytes": changed,
                        "exact_previous_to_current_count": exact_count_transitions,
                    }
                payload["comparison"] = {
                    "previous_probe": previous_path.name if previous_path is not None else None,
                    "previous_count": int(prev_count),
                    "regions": comparisons,
                }
        except Exception as exc:
            payload["comparison_error"] = f"{type(exc).__name__}: {exc}"

        return self._save_partycount_probe(payload)

    def _resolve_live_party_count(
        self, *, client, host_memory, host_pid: int, host_party_base: int,
        guest_party_base: int, expected_count: int,
    ) -> tuple[int, int, bytes]:
        """Demuestra el PartyCount live de USUM sin extrapolar el layout del SAV.

        Alpha.49 comparó una party real de 6 miembros con la misma sesión tras
        depositar manualmente uno desde el PC del propio juego. En la región
        primaria de party, 0x33F7F9D0 fue el único byte con transición exacta
        6→5; equivale a PARTY_BASE-0x74. La región alternativa no cambió.

        Antes de cualquier cambio de tamaño exigimos: dirección derivada solo
        desde la party live ya demostrada, doble lectura estable, host==guest y
        valor exacto igual al número de miembros que el parser PK7 ve ahora.
        """
        expected = int(expected_count)
        if not 1 <= expected <= 6:
            raise USUMLiveError("El tamaño actual de la party USUM está fuera de 1..6; no se escribió ningún byte.")

        guest_addr = int(guest_party_base) + int(USUM_PARTY_COUNT_DELTA)
        host_addr = int(host_party_base) + int(USUM_PARTY_COUNT_DELTA)
        if guest_addr < 0 or host_addr <= 0:
            raise USUMLiveError("La dirección demostrada de PartyCount quedó fuera de rango; no se escribió ningún byte.")

        handle = None
        try:
            handle = host_memory.open_process(int(host_pid))
            h1 = bytes(host_memory.read(handle, host_addr, USUM_PARTY_COUNT_SIZE))
            g1 = bytes(client.read_memory(guest_addr, USUM_PARTY_COUNT_SIZE))
            if self.reader.stable_delay:
                time.sleep(max(0.01, float(self.reader.stable_delay)))
            h2 = bytes(host_memory.read(handle, host_addr, USUM_PARTY_COUNT_SIZE))
            g2 = bytes(client.read_memory(guest_addr, USUM_PARTY_COUNT_SIZE))
        except Exception as exc:
            raise USUMLiveError("No se pudo demostrar PartyCount junto a la party USUM; no se escribió ningún byte.") from exc
        finally:
            if handle is not None:
                try:
                    host_memory.close_process(handle)
                except Exception:
                    pass

        if not (h1 == g1 == h2 == g2) or len(g2) != 1:
            raise USUMLiveError("PartyCount no fue estable o no coincidió host↔guest; no se escribió ningún byte.")
        actual = int(g2[0])
        if actual != expected:
            raise USUMLiveError(
                f"PartyCount live ({actual}) no coincide con los {expected} miembros PK7 de la party; "
                "no se cambió el tamaño del equipo."
            )
        return int(host_addr), int(guest_addr), bytes(g2)

    @staticmethod
    def _first_free_role(live_party: dict[int, SavePokemon]) -> str:
        occupied = {canonical_role(p.role) for p in live_party.values()}
        for role in ROLE_ORDER:
            if role not in occupied:
                return role
        return "SIN ROL"

    def _party_payload_from_box(
        self, raw_box: bytes, *, role: str, remove_move_slots: Sequence[int],
    ) -> tuple[bytes, SavePokemon]:
        """Convierte un PK7 stored demostrado en EncryptedPartyData 0x104.

        La representación (cifrada/plana) se conserva según el PK7 de caja real;
        nivel y estadísticas se reconstruyen exclusivamente con el Personal de la
        ROM efectiva ya cargada por RoleRun.
        """
        if self.personal_for is None:
            raise USUMLiveError(
                "No está disponible el Personal efectivo de la ROM UltraSol/UltraLuna; no se escribió ningún byte."
            )
        plain_stored, was_encrypted = _plain_pk7_stored_with_state(bytes(raw_box))
        data = bytearray(plain_stored)
        self._set_role(data, role)
        self._remove_move_slots(data, remove_move_slots)
        self._refresh_checksum(data)
        species_id = struct.unpack_from("<H", data, 8)[0]
        form = int(data[0x1D] >> 3)
        personal = self.personal_for(int(species_id), int(form))
        if personal is None:
            raise USUMLiveError(
                f"La ROM efectiva no aportó Personal para especie #{species_id}, forma {form}; no se escribió ningún byte."
            )
        full_plain = bytes(data) + self._party_extension(data, personal)
        if len(full_plain) != PK7_PARTY_SIZE:
            raise USUMLiveError("La reconstrucción EncryptedPartyData produjo un tamaño distinto de 0x104.")
        raw_party = encrypt_pk6(full_plain) if was_encrypted else full_plain
        parsed = parse_pk7_party(raw_party, 1, self.reader.move_names)
        if parsed is None:
            raise USUMLiveError("El EncryptedPartyData preparado no contiene un Pokémon válido.")
        return raw_party, parsed

    def _resolve_target(self, change: PendingRoleChange, live_party: dict[int, SavePokemon]) -> int:
        identity = str(change.pokemon_identity or "")
        if identity:
            matches = [slot for slot, pokemon in live_party.items() if self._pokemon_identity(pokemon) == identity]
            if len(matches) == 1:
                return int(matches[0])
            if not matches:
                raise USUMLiveError(
                    f"{change.pokemon or 'El Pokémon'} ya no está en el equipo vivo. Pulsa F5 y vuelve a intentarlo."
                )
            raise USUMLiveError("La identidad del Pokémon objetivo aparece más de una vez; no se escribió nada.")

        slot = int(change.pokemon_slot)
        pokemon = live_party.get(slot)
        if pokemon is None:
            raise USUMLiveError(f"El slot {slot} ya no contiene el Pokémon que se iba a editar.")
        declared = {str(change.pokemon or "").strip().casefold(), str(change.species or "").strip().casefold()}
        declared.discard("")
        actual = {pokemon.nickname.strip().casefold(), pokemon.species.strip().casefold()}
        if declared and not declared.intersection(actual):
            raise USUMLiveError(
                f"El slot {slot} ya no corresponde a {change.pokemon}. Pulsa F5 antes de cambiar el rol."
            )
        return slot

    def _resolve_team_swap_party_target(
        self, change: PendingTeamChange, live_party: dict[int, SavePokemon],
    ) -> int:
        """Resuelve el Pokémon saliente por identidad fuerte antes de escribir."""
        identity = str(change.outgoing_identity or "")
        if identity:
            matches = [
                slot for slot, pokemon in live_party.items()
                if self._pokemon_identity(pokemon) == identity
            ]
            if len(matches) == 1:
                return int(matches[0])
            if not matches:
                raise USUMLiveError(
                    f"{change.outgoing_pokemon or 'El Pokémon elegido'} ya no está en el equipo vivo. "
                    "Pulsa F5 y vuelve a preparar la sustitución."
                )
            raise USUMLiveError(
                "La identidad del Pokémon saliente aparece más de una vez; no se escribió ningún byte."
            )
        slot = int(change.party_slot)
        pokemon = live_party.get(slot)
        if pokemon is None:
            raise USUMLiveError(f"El slot {slot} ya no contiene el Pokémon que iba a salir.")
        declared = {
            str(change.outgoing_pokemon or "").strip().casefold(),
            str(change.outgoing_species or "").strip().casefold(),
        }
        declared.discard("")
        actual = {pokemon.nickname.strip().casefold(), pokemon.species.strip().casefold()}
        if declared and not declared.intersection(actual):
            raise USUMLiveError(
                f"El slot {slot} ya no corresponde a {change.outgoing_pokemon}. Pulsa F5 antes de sustituirlo."
            )
        return slot

    @staticmethod
    def _remove_move_slots(data: bytearray, slots: Sequence[int]) -> None:
        for one_based in sorted({int(value) for value in slots}, reverse=True):
            index = one_based - 1
            if not 0 <= index < 4:
                raise USUMLiveError(f"El hueco de movimiento {one_based} no es válido.")
            for move_index in range(index, 3):
                next_index = move_index + 1
                struct.pack_into(
                    "<H", data, _PK7_MOVE_OFFSETS[move_index],
                    struct.unpack_from("<H", data, _PK7_MOVE_OFFSETS[next_index])[0],
                )
                data[_PK7_MOVE_PP_OFFSETS[move_index]] = data[_PK7_MOVE_PP_OFFSETS[next_index]]
                data[_PK7_MOVE_PP_UPS_OFFSETS[move_index]] = data[_PK7_MOVE_PP_UPS_OFFSETS[next_index]]
            struct.pack_into("<H", data, _PK7_MOVE_OFFSETS[3], 0)
            data[_PK7_MOVE_PP_OFFSETS[3]] = 0
            data[_PK7_MOVE_PP_UPS_OFFSETS[3]] = 0

    @staticmethod
    def _party_extension(stored: bytes | bytearray, personal: ORASPersonalStats) -> bytes:
        """Reconstruye la extensión PK7 de party desde Personal efectivo + PK7 stored.

        SM guarda en la RAM sparse los primeros 0x16 bytes de esta extensión en
        ``slot+0x158``. El cálculo usa la misma disposición de EV/IV/naturaleza
        que el PK7 almacenado y nunca hereda stats del Pokémon que sale.
        """
        if len(stored) != PK7_STORED_SIZE:
            raise USUMLiveError("El PK7 de caja no tiene 0xE8 bytes para entrar al equipo.")
        experience = struct.unpack_from("<I", stored, 0x10)[0]
        try:
            level = level_for_experience(experience, int(personal.exp_growth))
        except Exception as exc:
            raise USUMLiveError("La ROM efectiva devolvió una curva de experiencia no válida.") from exc
        nature = int(stored[0x1C])
        if not 0 <= nature <= 24:
            raise USUMLiveError("El PK7 del PC contiene una naturaleza no válida.")
        evs = [int(stored[0x1E + index]) for index in range(6)]
        if any(not 0 <= ev <= 252 for ev in evs) or sum(evs) > 510:
            raise USUMLiveError("El PK7 del PC contiene EV no válidos.")
        iv32 = struct.unpack_from("<I", stored, 0x74)[0]
        ivs = [(iv32 >> (5 * index)) & 0x1F for index in range(6)]
        base = tuple(int(value) for value in personal.base_stats)
        if len(base) != 6 or any(not 1 <= value <= 255 for value in base):
            raise USUMLiveError("La ROM efectiva devolvió estadísticas base no válidas.")

        hp = 1 if base[0] == 1 else ((ivs[0] + 2 * base[0] + evs[0] // 4 + 100) * level // 100) + 10
        # Orden nativo: HP, Atk, Def, Spe, SpA, SpD.
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
            raise USUMLiveError("Las estadísticas calculadas no caben en la extensión PK7 de party.")

        extension = bytearray(PK7_PARTY_SIZE - PK7_STORED_SIZE)
        struct.pack_into("<I", extension, 0, 0)  # estado curado al retirar del PC
        extension[4] = int(level)
        struct.pack_into("<7H", extension, 8, *values)
        return bytes(extension)

    @staticmethod
    def _diff_offsets(left: bytes, right: bytes) -> list[int]:
        limit = min(len(left), len(right))
        result = [index for index in range(limit) if left[index] != right[index]]
        result.extend(range(limit, max(len(left), len(right))))
        return result

    @staticmethod
    def _range_fits(address: int, size: int, region: tuple[int, int]) -> bool:
        start, end = region
        return int(address) >= int(start) and int(address) + int(size) <= int(end)

    def _resolve_write_address(self, client, canonical_address: int, original_stored: bytes) -> tuple[int, str] | None:
        """Demuestra una dirección que Azahar RPC sí acepta para escribir.

        El diagnóstico alpha.10 demostró que el RPC de Azahar responde OK pero
        ignora silenciosamente escrituras a 0x34xxxxxx. El código fuente exacto
        de Azahar 263745c explica por qué: NEW_LINEAR_HEAP no figura entre las
        regiones autorizadas por HandleWriteMemory.

        Para SM, 0x34xxxxxx está dentro de NEW_LINEAR_HEAP y el propio Azahar
        mapea NEW_LINEAR_HEAP y LINEAR_HEAP al mismo backing FCRAM por offset.
        El alias solo se usa si una lectura previa confirma byte por byte que
        ambos virtual addresses contienen el MISMO PK7 que acabamos de validar.
        """
        canonical_address = int(canonical_address)
        size = len(original_stored)

        for region in _AZAHAR_RPC_DIRECT_WRITE_RANGES:
            if self._range_fits(canonical_address, size, region):
                current = bytes(client.read_memory(canonical_address, size))
                if current != bytes(original_stored):
                    raise USUMLiveError(
                        f"La RAM cambió en 0x{canonical_address:08X} antes de escribir; no se escribió ningún byte."
                    )
                return canonical_address, "direct-rpc-region"

        if (
            canonical_address >= _AZAHAR_NEW_LINEAR_HEAP
            and canonical_address + size <= _AZAHAR_NEW_LINEAR_HEAP_OLD_ALIAS_END
        ):
            offset = canonical_address - _AZAHAR_NEW_LINEAR_HEAP
            alias = _AZAHAR_LINEAR_HEAP[0] + offset
            canonical = bytes(client.read_memory(canonical_address, size))
            alias_bytes = bytes(client.read_memory(alias, size))
            expected = bytes(original_stored)
            if canonical != expected:
                raise USUMLiveError(
                    f"La party viva cambió en 0x{canonical_address:08X} antes de escribir; no se escribió ningún byte."
                )
            if alias_bytes == expected:
                return alias, "linear-heap-fcram-alias-validated"
            # En Azahar 263745c LINEAR_HEAP y NEW_LINEAR_HEAP no tienen por qué
            # estar mapeados simultáneamente al mismo virtual address del proceso.
            # El diagnóstico alpha.11 demostró que este alias NO coincide en la
            # ejecución real. Devolvemos None para activar el fallback Windows,
            # que localiza el backing FCRAM por contenido exacto y no por offset.
            return None

        if canonical_address >= _AZAHAR_NEW_LINEAR_HEAP:
            return None

        raise USUMLiveError(
            f"Azahar RPC no autoriza escrituras en 0x{canonical_address:08X}. No se escribió ningún byte."
        )

    def _diagnostic_slot_snapshot(
        self, client, *, address: int, expected_stored: bytes, original_stored: bytes, label: str,
    ) -> dict[str, object]:
        stored = bytes(client.read_memory(int(address), PK7_STORED_SIZE))
        stats = bytes(client.read_memory(int(address) + USUM_PARTY_STATS_OFFSET, USUM_PARTY_STATS_SIZE))
        contiguous = bytes(client.read_memory(int(address), PK7_PARTY_SIZE))
        snapshot: dict[str, object] = {
            "label": str(label),
            "address": f"0x{int(address):08X}",
            "stored_hex": stored.hex(),
            "stats_hex": stats.hex(),
            "contiguous_104_hex": contiguous.hex(),
            "stored_matches_expected": stored == bytes(expected_stored),
            "stored_matches_original": stored == bytes(original_stored),
            "diff_vs_expected": self._diff_offsets(stored, bytes(expected_stored)),
            "diff_vs_original": self._diff_offsets(stored, bytes(original_stored)),
        }
        try:
            raw = self.reader._compose_party_slot(stored, stats)
            plain, encrypted = _plain_pk7_with_state(raw)
            snapshot.update({
                "parse_ok": True,
                "encrypted": bool(encrypted),
                "role": self._role_from_plain(plain),
                "marking_value": f"0x{struct.unpack_from('<H', plain, 0x16)[0]:04X}",
                "checksum_stored": f"0x{struct.unpack_from('<H', plain, 0x06)[0]:04X}",
                "checksum_calculated": f"0x{_checksum67(plain):04X}",
                "species": int(struct.unpack_from('<H', plain, 0x08)[0]),
                "pid": int(struct.unpack_from('<I', plain, 0x18)[0]),
                "move_ids": [
                    int(struct.unpack_from('<H', plain, offset)[0]) for offset in _PK7_MOVE_OFFSETS
                ],
            })
        except Exception as exc:
            snapshot.update({"parse_ok": False, "parse_error": f"{type(exc).__name__}: {exc}"})
        return snapshot

    def _save_diagnostic(self, payload: dict[str, object]) -> Path | None:
        try:
            self.diagnostic_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            archive = self.diagnostic_dir / f"sm-write-{stamp}.json"
            latest = self.diagnostic_latest_path
            text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
            archive.write_text(text, encoding="utf-8")
            latest.parent.mkdir(parents=True, exist_ok=True)
            latest.write_text(text, encoding="utf-8")
            self.last_diagnostic_path = latest
            return latest
        except Exception:
            self.last_diagnostic_path = None
            return None

    def _collect_failure_diagnostic(
        self, client, *, process: AzaharProcess, party_base: int, attempted_slots: Sequence[int],
        originals: dict[int, bytes], encoded_slots: dict[int, bytes], changes: Sequence[object],
        immediate: dict[int, dict[str, object]], write_addresses: dict[int, int],
        write_modes: dict[int, str], error: Exception,
    ) -> tuple[dict[str, object], Path | None]:
        payload: dict[str, object] = {
            "format": "rolerun-usum-write-diagnostic-v2",
            "version": APP_VERSION,
            "created_at": datetime.now().isoformat(timespec="milliseconds"),
            "error": f"{type(error).__name__}: {error}",
            "process": {
                "process_id": int(process.process_id),
                "title_id": f"{int(process.title_id):016X}",
                "name": str(process.name),
            },
            "party_base": f"0x{int(party_base):08X}",
            "party_stride": int(USUM_PARTY_STRIDE),
            "stored_size": int(PK7_STORED_SIZE),
            "party_size": int(PK7_PARTY_SIZE),
            "stats_offset": int(USUM_PARTY_STATS_OFFSET),
            "changes": [
                (
                    {
                        "type": "role",
                        "slot": int(change.pokemon_slot),
                        "pokemon": str(change.pokemon),
                        "species": str(change.species),
                        "old_role": str(change.old_role),
                        "new_role": str(change.new_role),
                        "identity": str(change.pokemon_identity or ""),
                    }
                    if isinstance(change, PendingRoleChange) else
                    {
                        "type": "move",
                        "slot": int(change.pokemon_slot),
                        "pokemon": str(change.pokemon),
                        "species": str(change.species),
                        "move_slot": int(change.move_slot),
                        "old_move_id": int(change.old_move_id or 0),
                        "new_move_id": int(change.new_move_id or 0),
                        "identity": str(change.pokemon_identity or ""),
                    }
                )
                for change in changes
            ],
            "slots": {},
        }
        slots_payload: dict[str, object] = {}
        for slot in attempted_slots:
            original = bytes(originals[int(slot)][:PK7_STORED_SIZE])
            expected = bytes(encoded_slots[int(slot)][:PK7_STORED_SIZE])
            slots_payload[str(slot)] = {
                "address": f"0x{int(party_base) + (int(slot) - 1) * USUM_PARTY_STRIDE:08X}",
                "write_address": (
                    f"0x{int(write_addresses[int(slot)]):X}" if int(slot) in write_addresses else None
                ),
                "write_mode": write_modes.get(int(slot)),
                "original_stored_hex": original.hex(),
                "expected_stored_hex": expected.hex(),
                "planned_diff_offsets": self._diff_offsets(original, expected),
                "immediate_readback": immediate.get(int(slot)),
                "timed_readbacks": [],
            }
        payload["slots"] = slots_payload

        started = time.monotonic()
        previous = 0.0
        for delay in sorted(self.diagnostic_delays):
            wait = max(0.0, delay - previous)
            if wait:
                time.sleep(wait)
            elapsed = time.monotonic() - started
            previous = delay
            for slot in attempted_slots:
                address = int(party_base) + (int(slot) - 1) * USUM_PARTY_STRIDE
                try:
                    snap = self._diagnostic_slot_snapshot(
                        client, address=address,
                        expected_stored=encoded_slots[int(slot)][:PK7_STORED_SIZE],
                        original_stored=originals[int(slot)][:PK7_STORED_SIZE],
                        label=f"failure+{elapsed * 1000:.0f}ms",
                    )
                except Exception as exc:
                    snap = {"label": f"failure+{elapsed * 1000:.0f}ms", "read_error": f"{type(exc).__name__}: {exc}"}
                slots_payload[str(slot)]["timed_readbacks"].append(snap)
        path = self._save_diagnostic(payload)
        return payload, path

    def _rollback(
        self, client, party_base: int, attempted_slots: Sequence[int], originals: dict[int, bytes],
        write_addresses: dict[int, int], write_modes: dict[int, str], *,
        host_memory=None, host_handle=None,
    ) -> list[str]:
        errors: list[str] = []
        for slot in reversed(tuple(attempted_slots)):
            original = originals.get(int(slot))
            write_address = write_addresses.get(int(slot))
            if original is None or write_address is None:
                continue
            canonical = int(party_base) + (int(slot) - 1) * USUM_PARTY_STRIDE
            expected = bytes(original[:PK7_STORED_SIZE])
            try:
                if write_modes.get(int(slot)) == "windows-host-fcram-content-validated":
                    if host_memory is None or host_handle is None:
                        raise USUMLiveError("el transporte host ya no está disponible para rollback")
                    host_memory.write(host_handle, int(write_address), expected)
                    confirmed_write = bytes(host_memory.read(host_handle, int(write_address), PK7_STORED_SIZE))
                else:
                    client.write_memory(int(write_address), expected)
                    confirmed_write = bytes(client.read_memory(int(write_address), PK7_STORED_SIZE))
                confirmed_canonical = bytes(client.read_memory(canonical, PK7_STORED_SIZE))
                if confirmed_canonical != expected or confirmed_write != expected:
                    errors.append(f"slot {slot}: la relectura canonical/transporte no coincide")
            except Exception as exc:
                errors.append(f"slot {slot}: {exc}")
        return errors

    @staticmethod
    def _inventory_patch(change: PendingInventoryChange) -> tuple[str, bytes, bytes, int, bytes, bytes]:
        """Valida el diff PKHeX del ``main`` y devuelve un parche mínimo demostrado."""
        if change.item_key in USUM_UTILITY_ITEM_IDS:
            original = bytes(getattr(change, "save_inventory_witness", b"") or b"")
            desired = bytes(getattr(change, "desired_inventory_witness", b"") or b"")
            if len(original) != USUM_SAVE_ITEM_BLOCK_SIZE or len(desired) != USUM_SAVE_ITEM_BLOCK_SIZE:
                raise USUMLiveError(
                    "UltraSol/UltraLuna necesita una huella PKHeX completa de la mochila. Guarda dentro del juego, pulsa F5 y vuelve a intentarlo."
                )
            target_id = int(USUM_UTILITY_ITEM_IDS[change.item_key])
            target_count = int(change.quantity)
            candidates: list[int] = []
            for offset in range(0, len(desired), 4):
                word = struct.unpack_from("<I", desired, offset)[0]
                item_id = int(word & 0x3FF)
                count = int((word >> 10) & 0x3FF)
                if item_id == target_id and count == target_count:
                    candidates.append(offset)
            if len(candidates) != 1:
                raise USUMLiveError(
                    f"PKHeX no dejó una única entrada demostrable para {change.item_name} ×{target_count}; no se escribió ningún byte."
                )
            offset = candidates[0]
            diff = [i for i, (a, b) in enumerate(zip(original, desired)) if a != b]
            if diff and any(not (offset <= i < offset + 4) for i in diff):
                raise USUMLiveError(
                    f"La previsualización PKHeX de {change.item_name} modificó más de un registro de mochila; por seguridad no se escribió RAM."
                )
            old_word = struct.unpack_from("<I", original, offset)[0]
            old_id = int(old_word & 0x3FF)
            if old_id not in (0, target_id):
                raise USUMLiveError("El registro de mochila objetivo no coincide con el objeto esperado; no se escribió RAM.")
            return "items", original, desired, offset, original[offset:offset + 4], desired[offset:offset + 4]

        if change.item_key == "money-max":
            original = bytes(getattr(change, "save_misc_witness", b"") or b"")
            desired = bytes(getattr(change, "desired_misc_witness", b"") or b"")
            if len(original) != USUM_SAVE_MISC_BLOCK_SIZE or len(desired) != USUM_SAVE_MISC_BLOCK_SIZE:
                raise USUMLiveError(
                    "UltraSol/UltraLuna necesita una huella PKHeX completa del bloque Misc. Guarda dentro del juego, pulsa F5 y vuelve a intentarlo."
                )
            diff = [i for i, (a, b) in enumerate(zip(original, desired)) if a != b]
            allowed = set(range(USUM_MISC_MONEY_OFFSET, USUM_MISC_MONEY_OFFSET + 4))
            if any(i not in allowed for i in diff):
                raise USUMLiveError("La previsualización PKHeX del dinero modificó campos ajenos a Money; no se escribió RAM.")
            desired_money = struct.unpack_from("<I", desired, USUM_MISC_MONEY_OFFSET)[0]
            if int(desired_money) != USUM_MAX_MONEY:
                raise USUMLiveError("PKHeX no confirmó 9.999.999 como dinero objetivo; no se escribió RAM.")
            offset = USUM_MISC_MONEY_OFFSET
            return "misc", original, desired, offset, original[offset:offset + 4], desired[offset:offset + 4]

        raise USUMLiveError(f"La utilidad '{change.item_key}' no está habilitada para UltraSol/UltraLuna.")

    @staticmethod
    def _misc_structural_metrics(
        original: bytes, live: bytes, matching_offsets: Sequence[int],
    ) -> dict[str, object]:
        excluded = set(range(USUM_MISC_MONEY_OFFSET, USUM_MISC_MONEY_OFFSET + 4))
        equal_offsets = [
            index for index, (saved, current) in enumerate(zip(bytes(original), bytes(live)))
            if index not in excluded and saved == current
        ]
        quartiles = sorted({
            min(3, (int(offset) * 4) // max(1, len(original)))
            for offset in matching_offsets
        })
        covered: set[int] = set()
        for offset in matching_offsets:
            covered.update(
                index for index in range(int(offset), min(len(original), int(offset) + USUM_MISC_STRUCTURAL_WINDOW_SIZE))
                if index not in excluded
            )
        return {
            "matching_windows": len(tuple(matching_offsets)),
            "matching_window_offsets": [int(value) for value in matching_offsets],
            "quartiles": quartiles,
            "quartile_count": len(quartiles),
            "equal_nonmoney_bytes": len(equal_offsets),
            "exact_window_covered_bytes": len(covered),
        }

    @staticmethod
    def _misc_structural_metrics_are_strong(metrics: dict[str, object]) -> bool:
        return (
            int(metrics.get("matching_windows", 0)) >= USUM_MISC_STRUCTURAL_MIN_WINDOWS
            and int(metrics.get("quartile_count", 0)) >= USUM_MISC_STRUCTURAL_MIN_QUARTILES
            and int(metrics.get("equal_nonmoney_bytes", 0)) >= USUM_MISC_STRUCTURAL_MIN_EQUAL_BYTES
        )

    def _save_utility_diagnostic(self, payload: dict[str, object]) -> Path | None:
        wrapped = {
            "format": "rolerun-usum-utility-diagnostic-v1",
            "version": APP_VERSION,
            "created_at": datetime.now().isoformat(timespec="milliseconds"),
            **payload,
        }
        try:
            self.diagnostic_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            archive = self.diagnostic_dir / f"sm-utility-{stamp}.json"
            latest = LOG_DIR / "usum_utility_diagnostic_latest.json"
            text = json.dumps(wrapped, ensure_ascii=False, indent=2, sort_keys=True)
            archive.write_text(text, encoding="utf-8")
            latest.parent.mkdir(parents=True, exist_ok=True)
            latest.write_text(text, encoding="utf-8")
            self.last_diagnostic_path = latest
            return latest
        except Exception:
            return None

    def _resolve_live_misc_structurally(
        self, *, client, host_memory, host_target: HostPartyTarget, party_base: int, original: bytes,
    ) -> tuple[object, int, int, bytes]:
        """Fallback for Money: prove the live Misc by exact distributed witnesses."""
        excluded = ((USUM_MISC_MONEY_OFFSET, USUM_MISC_MONEY_OFFSET + 4),)
        try:
            candidates, selected_offsets = host_memory.find_structural_block_candidates_in_anchor_region(
                pid=int(host_target.pid), anchor_address=int(host_target.host_party_base),
                pattern=bytes(original), excluded_ranges=excluded,
                window_size=USUM_MISC_STRUCTURAL_WINDOW_SIZE, windows_per_quartile=4, max_candidates=32,
            )
        except WindowsProcessMemoryError as exc:
            path = self._save_utility_diagnostic({
                "kind": "misc",
                "stage": "structural-scan",
                "error": str(exc),
                "selected_window_offsets": [],
                "candidates": [],
            })
            suffix = f" Diagnóstico: {path}" if path is not None else ""
            raise USUMLiveError(f"{exc}{suffix}") from exc

        evaluated: list[dict[str, object]] = []
        proven: list[tuple[int, int, bytes, dict[str, object]]] = []
        for host_base, matching_offsets in candidates:
            delta = int(host_base) - int(host_target.host_party_base)
            guest_base = int(party_base) + delta
            entry: dict[str, object] = {
                "host_base": f"0x{int(host_base):X}",
                "guest_base": f"0x{int(guest_base) & 0xFFFFFFFF:08X}",
                "matching_window_offsets": [int(value) for value in matching_offsets],
            }
            if guest_base < 0 or guest_base + len(original) > 0x1_0000_0000:
                entry["rejected"] = "guest-out-of-range"
                evaluated.append(entry)
                continue
            handle = None
            try:
                handle = host_memory.open_process(int(host_target.pid))
                host_now = bytes(host_memory.read(handle, int(host_base), len(original)))
                guest_now = bytes(client.read_memory(int(guest_base), len(original)))
            except Exception as exc:
                entry["rejected"] = f"read-failed: {type(exc).__name__}: {exc}"
                evaluated.append(entry)
                continue
            finally:
                if handle is not None:
                    try:
                        host_memory.close_process(handle)
                    except Exception:
                        pass

            entry["host_guest_equal"] = host_now == guest_now
            if host_now != guest_now:
                entry["rejected"] = "host-guest-mismatch"
                evaluated.append(entry)
                continue
            metrics = self._misc_structural_metrics(original, host_now, matching_offsets)
            entry.update(metrics)
            live_money = struct.unpack_from("<I", host_now, USUM_MISC_MONEY_OFFSET)[0]
            entry["live_money"] = int(live_money)
            if live_money > USUM_MAX_MONEY:
                entry["rejected"] = "money-out-of-range"
                evaluated.append(entry)
                continue
            if not self._misc_structural_metrics_are_strong(metrics):
                entry["rejected"] = "insufficient-structural-proof"
                evaluated.append(entry)
                continue
            entry["accepted"] = True
            evaluated.append(entry)
            proven.append((int(host_base), int(guest_base), host_now, metrics))

        if len(proven) != 1:
            path = self._save_utility_diagnostic({
                "kind": "misc",
                "stage": "structural-proof",
                "selected_window_offsets": [int(value) for value in selected_offsets],
                "thresholds": {
                    "min_windows": USUM_MISC_STRUCTURAL_MIN_WINDOWS,
                    "min_quartiles": USUM_MISC_STRUCTURAL_MIN_QUARTILES,
                    "min_equal_nonmoney_bytes": USUM_MISC_STRUCTURAL_MIN_EQUAL_BYTES,
                    "window_size": USUM_MISC_STRUCTURAL_WINDOW_SIZE,
                },
                "candidates": evaluated,
                "accepted_count": len(proven),
            })
            hint = f" Diagnóstico guardado en: {path}" if path is not None else ""
            if not proven:
                raise USUMLiveError(
                    "RoleRun encontró fragmentos de Misc en FCRAM, pero no pudo demostrar una única estructura viva con evidencia suficiente. "
                    "No se escribió ningún byte." + hint
                )
            raise USUMLiveError(
                f"RoleRun encontró {len(proven)} estructuras Misc igualmente demostrables. Por seguridad no se escribió ningún byte." + hint
            )

        host_base, guest_base, live_block, metrics = proven[0]
        handle = host_memory.open_process(int(host_target.pid))
        try:
            host_check = bytes(host_memory.read(handle, host_base, len(original)))
            guest_check = bytes(client.read_memory(guest_base, len(original)))
            if host_check != live_block or guest_check != live_block:
                raise USUMLiveError("El bloque Misc vivo cambió durante la calibración estructural; no se escribió ningún byte.")
        except Exception:
            host_memory.close_process(handle)
            raise
        self._save_utility_diagnostic({
            "kind": "misc",
            "stage": "structural-proof-ok",
            "host_base": f"0x{host_base:X}",
            "guest_base": f"0x{guest_base:08X}",
            "metrics": metrics,
            "live_money": int(struct.unpack_from("<I", live_block, USUM_MISC_MONEY_OFFSET)[0]),
        })
        return handle, host_base, guest_base, live_block

    @staticmethod
    def _parse_tm_items_block(raw: bytes) -> dict[int, int]:
        """Extrae únicamente las MT01..100 del bloque de mochila ya demostrado.

        El formato de 4 bytes (10 bits ItemID + 10 bits cantidad) es exactamente
        el mismo que alpha.14/15 ya validó físicamente al escribir Caramelo Raro
        y Repelente Máximo; aquí solo se reutiliza para lectura.
        """
        if len(raw) != USUM_SAVE_ITEM_BLOCK_SIZE:
            raise USUMLiveError("El bloque vivo de mochila de UltraSol/UltraLuna tiene un tamaño inesperado.")
        tm_ids = {int(item_id) for number in range(1, 101) if (item_id := usum_tm_item_id(number)) is not None}
        result: dict[int, int] = {}
        for offset in range(0, len(raw), 4):
            word = struct.unpack_from("<I", raw, offset)[0]
            item_id = int(word & 0x3FF)
            count = int((word >> 10) & 0x3FF)
            if item_id in tm_ids and count > 0:
                # Una misma MT no debería ocupar dos slots. Si una ROM/save
                # corrupto lo hace, sumar sería ocultarlo; abortamos arriba.
                if item_id in result:
                    raise USUMLiveError(
                        f"La mochila viva contiene el objeto MT #{item_id} en más de un registro; no se usará para enseñar movimientos."
                    )
                result[item_id] = count
        return result

    @staticmethod
    def _items_structural_metrics(saved: bytes, live: bytes, matching_offsets: Sequence[int]) -> dict[str, object]:
        equal_bytes = sum(1 for a, b in zip(saved, live) if a == b)
        quartiles = sorted({
            min(3, (int(offset) * 4) // max(1, len(saved)))
            for offset in matching_offsets
        })
        return {
            "matching_windows": len(set(int(v) for v in matching_offsets)),
            "quartiles": quartiles,
            "quartile_count": len(quartiles),
            "equal_bytes": int(equal_bytes),
        }

    @staticmethod
    def _items_structural_metrics_are_strong(metrics: dict[str, object]) -> bool:
        return (
            int(metrics.get("matching_windows", 0)) >= USUM_ITEMS_STRUCTURAL_MIN_WINDOWS
            and int(metrics.get("quartile_count", 0)) >= USUM_ITEMS_STRUCTURAL_MIN_QUARTILES
            and int(metrics.get("equal_bytes", 0)) >= USUM_ITEMS_STRUCTURAL_MIN_EQUAL_BYTES
        )

    def _resolve_live_items_structurally(
        self, *, client, host_memory, host_target: HostPartyTarget, party_base: int, original: bytes,
    ) -> tuple[object, int, int, bytes]:
        try:
            candidates, selected_offsets = host_memory.find_structural_block_candidates_in_anchor_region(
                pid=int(host_target.pid), anchor_address=int(host_target.host_party_base),
                pattern=bytes(original), excluded_ranges=(),
                window_size=USUM_ITEMS_STRUCTURAL_WINDOW_SIZE, windows_per_quartile=6, max_candidates=32,
            )
        except WindowsProcessMemoryError as exc:
            raise USUMLiveError(str(exc)) from exc

        evaluated: list[dict[str, object]] = []
        proven: list[tuple[int, int, bytes, dict[str, object]]] = []
        for host_base, matching_offsets in candidates:
            delta = int(host_base) - int(host_target.host_party_base)
            guest_base = int(party_base) + delta
            entry: dict[str, object] = {
                "host_base": f"0x{int(host_base):X}",
                "guest_base": f"0x{int(guest_base) & 0xFFFFFFFF:08X}",
                "matching_window_offsets": [int(v) for v in matching_offsets],
            }
            if guest_base < 0 or guest_base + len(original) > 0x1_0000_0000:
                entry["rejected"] = "guest-out-of-range"
                evaluated.append(entry)
                continue
            handle = None
            try:
                handle = host_memory.open_process(int(host_target.pid))
                host_now = bytes(host_memory.read(handle, int(host_base), len(original)))
                guest_now = bytes(client.read_memory(int(guest_base), len(original)))
            except Exception as exc:
                entry["rejected"] = f"read-failed: {type(exc).__name__}: {exc}"
                evaluated.append(entry)
                continue
            finally:
                if handle is not None:
                    try:
                        host_memory.close_process(handle)
                    except Exception:
                        pass
            if host_now != guest_now:
                entry["rejected"] = "host-guest-mismatch"
                evaluated.append(entry)
                continue
            metrics = self._items_structural_metrics(original, host_now, matching_offsets)
            entry.update(metrics)
            if not self._items_structural_metrics_are_strong(metrics):
                entry["rejected"] = "insufficient-structural-proof"
                evaluated.append(entry)
                continue
            try:
                self._parse_tm_items_block(host_now)
            except USUMLiveError as exc:
                entry["rejected"] = f"invalid-item-block: {exc}"
                evaluated.append(entry)
                continue
            entry["accepted"] = True
            evaluated.append(entry)
            proven.append((int(host_base), int(guest_base), host_now, metrics))

        if len(proven) != 1:
            path = self._save_utility_diagnostic({
                "kind": "items",
                "stage": "tm-structural-proof",
                "selected_window_offsets": [int(v) for v in selected_offsets],
                "candidates": evaluated,
                "accepted_count": len(proven),
            })
            hint = f" Diagnóstico guardado en: {path}" if path is not None else ""
            if not proven:
                raise USUMLiveError(
                    "RoleRun no pudo demostrar una única mochila viva de UltraSol/UltraLuna a partir del main testigo. No se enseñará ninguna MT." + hint
                )
            raise USUMLiveError(
                f"RoleRun encontró {len(proven)} mochilas igualmente demostrables. Por seguridad no se enseñará ninguna MT." + hint
            )
        host_base, guest_base, live_block, _metrics = proven[0]
        handle = host_memory.open_process(int(host_target.pid))
        host_check = bytes(host_memory.read(handle, host_base, len(original)))
        guest_check = bytes(client.read_memory(guest_base, len(original)))
        if host_check != live_block or guest_check != live_block:
            host_memory.close_process(handle)
            raise USUMLiveError("La mochila viva cambió durante su calibración; vuelve a abrir el selector de MT.")
        return handle, host_base, guest_base, live_block

    @staticmethod
    def _matching_item_windows(saved: bytes, live: bytes) -> tuple[int, ...]:
        """Ventanas exactas distribuidas usadas como testigo SAV7USUM→RAM.

        No convierte offsets de save en direcciones RAM. Solo puntúa un bloque
        RAM candidato que ya fue leído por otra vía y exige coincidencia fuerte
        con el ``main`` real, tolerando que objetos/contadores hayan cambiado.
        """
        if len(saved) != USUM_SAVE_ITEM_BLOCK_SIZE or len(live) != USUM_SAVE_ITEM_BLOCK_SIZE:
            return ()
        size = USUM_ITEMS_STRUCTURAL_WINDOW_SIZE
        return tuple(
            offset for offset in range(0, len(saved) - size + 1, size)
            if saved[offset:offset + size] == live[offset:offset + size]
        )

    def _validated_kahuna_count_from_live_items(
        self, saved: bytes, live: bytes,
    ) -> tuple[bool, int | None]:
        """Valida que ``live`` sea Items y, por separado, el prefijo de Kahunas.

        ``structural_ok=True, count=None`` significa que la mochila sí quedó
        demostrada pero su secuencia de premios no es un prefijo válido. En ese
        caso NO se cae al main: hacerlo ocultaría una contradicción viva.
        """
        matching = self._matching_item_windows(saved, live)
        metrics = self._items_structural_metrics(saved, live, matching)
        if not self._items_structural_metrics_are_strong(metrics):
            return False, None
        # Un bloque de ceros puede coincidir con muchos bytes vacíos de un save
        # real. Para una candidata guest sin ancla host exigimos además al menos
        # dos ventanas NO VACÍAS de 16 bytes que coincidan exactamente con el
        # main. Así "RAM legible llena de 0" jamás se convierte en 0 medallas.
        nonzero_matching_windows = sum(
            1 for offset in matching
            if any(saved[int(offset):int(offset) + USUM_ITEMS_STRUCTURAL_WINDOW_SIZE])
        )
        if nonzero_matching_windows < 2:
            return False, None
        if parse_usum_zcrystal_keys(live) is None:
            return False, None
        return True, count_usum_kahuna_badges(live)

    def _read_stable_guest_items(self, client, address: int) -> bytes | None:
        try:
            first = bytes(client.read_memory(int(address), USUM_SAVE_ITEM_BLOCK_SIZE))
            if self.reader.stable_delay:
                time.sleep(self.reader.stable_delay)
            second = bytes(client.read_memory(int(address), USUM_SAVE_ITEM_BLOCK_SIZE))
        except Exception:
            return None
        if first != second or len(second) != USUM_SAVE_ITEM_BLOCK_SIZE:
            return None
        return second

    def read_kahuna_badges_for_game(
        self, current: SaveGameData, save_path: Path | str | None, *, party_base: int | None = None,
        allow_full_scan: bool = True,
    ) -> int | None:
        """Lee el progreso 0..4 de las Grandes Pruebas sin contar combates.

        Igual que ORAS/X/Y, publica un VALOR ABSOLUTO reconstruido desde progreso
        persistente. La señal primaria son los cuatro Z-Crystals de Gran Prueba
        dentro del bolsillo Z-Crystals de SAV7USUM. Ninguna dirección guest se
        acepta por valor nominal: las cachés ya demostradas se revalidan y, si
        aún no existen, la mochila se descubre por testigos estructurales host↔guest.
        """
        self._last_badge_source = None
        if save_path is None:
            return None
        path = Path(save_path).expanduser().resolve()
        try:
            saved_file = path.read_bytes()
        except OSError:
            return None
        end = USUM_SAVE_ITEM_BLOCK_OFFSET + USUM_SAVE_ITEM_BLOCK_SIZE
        if len(saved_file) < end:
            return None
        saved_items = bytes(saved_file[USUM_SAVE_ITEM_BLOCK_OFFSET:end])
        saved_badges = count_usum_kahuna_badges(saved_items)

        try:
            with self.reader.client_factory() as client:
                process = self.reader._find_usum_process(client.process_list())
                client.set_process(process.process_id)
                resolved_party_base = int(party_base) if party_base is not None else int(
                    self.reader._locate_party_base(client, process, current)
                )
                session = (
                    int(process.title_id), int(process.process_id), str(process.name), resolved_party_base,
                )

                # 1) Mochila ya demostrada por el sistema de MT: ruta más fuerte
                # y barata. La sesión debe coincidir exactamente y el bloque guest
                # vuelve a superar estabilidad + testigo SAV antes de usarse.
                cached_items = self._utility_block_cache.get("items")
                if cached_items is not None and self._tm_inventory_session == session:
                    _host_pid, _host_base, guest_base, _previous = cached_items
                    live = self._read_stable_guest_items(client, int(guest_base))
                    if live is not None:
                        structural_ok, value = self._validated_kahuna_count_from_live_items(saved_items, live)
                        if structural_ok:
                            self._utility_block_cache["items"] = (
                                int(cached_items[0]), int(cached_items[1]), int(guest_base), bytes(live)
                            )
                            self._last_badge_source = "Z-Crystals vivos · mochila MT validada"
                            return value

                # 2) Si PC ya fue demostrado host↔guest en esta sesión, su base
                # fija la relación con Items que ESA MISMA calibración demostró.
                # Aun así releemos y exigimos el mismo testigo estructural.
                pc_cache = self._pc_live_cache
                if pc_cache is not None and pc_cache[0] == session:
                    guest_items_base = int(pc_cache[3]) - (
                        USUM_SAVE_PC_BLOCK_OFFSET - USUM_SAVE_ITEM_BLOCK_OFFSET
                    )
                    live = self._read_stable_guest_items(client, guest_items_base)
                    if live is not None:
                        structural_ok, value = self._validated_kahuna_count_from_live_items(saved_items, live)
                        if structural_ok:
                            self._last_badge_source = "Z-Crystals vivos · relación PC→Items revalidada"
                            return value

                # 3) USUM no deriva Items de una base externa de PC no demostrada.
                # Si todavía no existe una calibración de mochila/PC propia de
                # esta sesión, se pasa al descubrimiento estructural del paso 4.
        except (USUMLiveError, AzaharRPCError, OSError, ValueError):
            pass

        # 4) Fallback autosuficiente: reutiliza el descubrimiento estructural de
        # la mochila que ya está probado para las MT. Es potencialmente pesado,
        # por lo que solo se intenta una vez por ventana de cooldown si las rutas
        # rápidas no sirven. Se ejecuta en el worker de monitor, nunca en render.
        now = time.monotonic()
        if allow_full_scan and now - float(self._badge_full_scan_failed_at) >= 30.0:
            try:
                self.read_tm_inventory_for_game(current, path)
                cached_items = self._utility_block_cache.get("items")
                if cached_items is not None:
                    live = bytes(cached_items[3])
                    structural_ok, value = self._validated_kahuna_count_from_live_items(saved_items, live)
                    if structural_ok:
                        self._last_badge_source = "Z-Crystals vivos · mochila calibrada estructuralmente"
                        self._badge_full_scan_failed_at = 0.0
                        return value
            except Exception:
                self._badge_full_scan_failed_at = now

        # El main es solo respaldo, igual que en ORAS/X/Y. Si todavía no se ha
        # guardado tras derrotar al Kahuna, la próxima lectura live será la que
        # actualice inmediatamente; nunca fabricamos progreso por diferencia.
        if saved_badges is not None:
            self._last_badge_source = "main · Z-Crystals (fallback)"
        return saved_badges

    def _prove_tm_guest_inventory_from_reference(
        self, *, client, process: AzaharProcess, party_base: int,
        current: SaveGameData, saved_items: bytes,
    ) -> tuple[dict[int, int], int, bytes]:
        """Demuestra la mochila guest de USUM usando su ItemsOffset publicado.

        PKMN-NTR LookupTable (US/UM) documenta ItemsOffset=0x33011934 y
        ItemsSize=0x1000. Alpha.54 deja de trasladar distancias del archivo SAV
        a RAM. La referencia publicada solo forma una candidata: RoleRun exige
        dos lecturas guest estables y que el prefijo SAV7USUM Items (0xE28)
        conserve una huella estructural fuerte y distribuida frente al ``main``.

        Esta ruta es solo lectura; enseñar una MT no modifica la mochila.
        """
        try:
            first = bytes(client.read_memory(int(USUM_ITEMS_BASE_REFERENCE), int(USUM_ITEMS_REFERENCE_READ_SIZE)))
            if self.reader.stable_delay:
                time.sleep(self.reader.stable_delay)
            second = bytes(client.read_memory(int(USUM_ITEMS_BASE_REFERENCE), int(USUM_ITEMS_REFERENCE_READ_SIZE)))
        except Exception as exc:
            path = self._save_utility_diagnostic({
                "kind": "items",
                "stage": "alpha54-pkmn-ntr-items-reference-read",
                "guest_items_reference": f"0x{int(USUM_ITEMS_BASE_REFERENCE):08X}",
                "reference_read_size": int(USUM_ITEMS_REFERENCE_READ_SIZE),
                "fcram_scan_attempted": False,
                "accepted": False,
                "error": f"{type(exc).__name__}: {exc}",
            })
            hint = f" Diagnóstico guardado en: {path}" if path is not None else ""
            raise USUMLiveError(
                "No se pudo releer de forma estable la referencia ItemsOffset de USUM; "
                "no se enseñará ninguna MT." + hint
            ) from exc
        if first != second or len(second) != int(USUM_ITEMS_REFERENCE_READ_SIZE):
            path = self._save_utility_diagnostic({
                "kind": "items",
                "stage": "alpha54-pkmn-ntr-items-reference-unstable",
                "guest_items_reference": f"0x{int(USUM_ITEMS_BASE_REFERENCE):08X}",
                "reference_read_size": int(USUM_ITEMS_REFERENCE_READ_SIZE),
                "fcram_scan_attempted": False,
                "accepted": False,
            })
            hint = f" Diagnóstico guardado en: {path}" if path is not None else ""
            raise USUMLiveError(
                "La referencia ItemsOffset de USUM cambió entre dos lecturas; "
                "no se enseñará ninguna MT." + hint
            )

        live = bytes(second[:USUM_SAVE_ITEM_BLOCK_SIZE])
        matching = self._matching_item_windows(bytes(saved_items), live)
        metrics = self._items_structural_metrics(bytes(saved_items), live, matching)
        nonzero_matching_windows = sum(
            1 for offset in matching
            if any(saved_items[int(offset):int(offset) + USUM_ITEMS_STRUCTURAL_WINDOW_SIZE])
        )
        if (
            not self._items_structural_metrics_are_strong(metrics)
            or int(nonzero_matching_windows) < 2
        ):
            path = self._save_utility_diagnostic({
                "kind": "items",
                "stage": "alpha54-pkmn-ntr-items-reference-proof",
                "party_base": f"0x{int(party_base):08X}",
                "guest_items_reference": f"0x{int(USUM_ITEMS_BASE_REFERENCE):08X}",
                "reference_read_size": int(USUM_ITEMS_REFERENCE_READ_SIZE),
                "metrics": metrics,
                "nonzero_matching_windows": int(nonzero_matching_windows),
                "fcram_scan_attempted": False,
                "accepted": False,
            })
            hint = f" Diagnóstico guardado en: {path}" if path is not None else ""
            raise USUMLiveError(
                "La referencia ItemsOffset publicada para USUM no coincide de forma estructural suficiente "
                "con el main testigo de esta Run; no se enseñará ninguna MT." + hint
            )

        inventory = self._parse_tm_items_block(live)
        self._save_utility_diagnostic({
            "kind": "items",
            "stage": "alpha54-pkmn-ntr-items-reference-proof",
            "party_base": f"0x{int(party_base):08X}",
            "guest_items_reference": f"0x{int(USUM_ITEMS_BASE_REFERENCE):08X}",
            "reference_read_size": int(USUM_ITEMS_REFERENCE_READ_SIZE),
            "metrics": metrics,
            "nonzero_matching_windows": int(nonzero_matching_windows),
            "tm_count": len(inventory),
            "fcram_scan_attempted": False,
            "accepted": True,
        })
        return inventory, int(USUM_ITEMS_BASE_REFERENCE), live

    def read_tm_inventory_for_game(
        self, current: SaveGameData, save_path: Path | str,
    ) -> tuple[dict[int, int], AzaharProcess, int]:
        """Lee las MT poseídas desde la mochila RAM específica de USUM.

        Alpha.54 no ejecuta ningún descubrimiento FCRAM desde el selector de MT.
        La dirección ItemsOffset publicada se revalida contra el ``main`` y, si
        falla, se aborta con diagnóstico preciso. Las utilidades que SÍ escriben
        inventario conservan su calibración host+guest separada.
        """
        path = Path(save_path).expanduser().resolve()
        try:
            saved = path.read_bytes()
        except OSError as exc:
            raise USUMLiveError(
                "No se pudo leer el main testigo para validar la mochila viva de UltraSol/UltraLuna."
            ) from exc
        end = USUM_SAVE_ITEM_BLOCK_OFFSET + USUM_SAVE_ITEM_BLOCK_SIZE
        if len(saved) < end:
            raise USUMLiveError(
                "El main de UltraSol/UltraLuna es demasiado pequeño para contener el bloque de mochila esperado por PKHeX."
            )
        original = bytes(saved[USUM_SAVE_ITEM_BLOCK_OFFSET:end])
        try:
            with self.reader.client_factory() as client:
                process = self.reader._find_usum_process(client.process_list())
                client.set_process(process.process_id)
                party_base = self.reader._locate_party_base(client, process, current)
                expected_session = (
                    int(process.title_id), int(process.process_id), str(process.name), int(party_base)
                )

                guest_anchor = self._tm_guest_inventory_anchor
                if guest_anchor is not None and guest_anchor[0] == expected_session:
                    guest_base = int(guest_anchor[1])
                    guest_now = self._read_stable_guest_items(client, guest_base)
                    if guest_now is not None:
                        matching = self._matching_item_windows(original, guest_now)
                        metrics = self._items_structural_metrics(original, guest_now, matching)
                        nonzero_matching_windows = sum(
                            1 for offset in matching
                            if any(original[int(offset):int(offset) + USUM_ITEMS_STRUCTURAL_WINDOW_SIZE])
                        )
                        if (
                            self._items_structural_metrics_are_strong(metrics)
                            and int(nonzero_matching_windows) >= 2
                        ):
                            inventory = self._parse_tm_items_block(guest_now)
                            self._tm_guest_inventory_anchor = (
                                expected_session, guest_base, bytes(guest_now)
                            )
                            self._tm_inventory_session = expected_session
                            return inventory, process, 1
                    self._tm_guest_inventory_anchor = None

                inventory, guest_items_base, guest_items = self._prove_tm_guest_inventory_from_reference(
                    client=client, process=process, party_base=int(party_base),
                    current=current, saved_items=original,
                )
                self._tm_inventory_session = expected_session
                self._tm_guest_inventory_anchor = (
                    expected_session, int(guest_items_base), bytes(guest_items)
                )
                return inventory, process, 1
        except AzaharRPCError as exc:
            raise USUMLiveError(str(exc)) from exc

    def _assert_live_tm_available(
        self, client, process: AzaharProcess, party_base: int, change: PendingTMTeach,
    ) -> None:
        expected_session = (
            int(process.title_id), int(process.process_id), str(process.name), int(party_base)
        )

        # Alpha.53: una MT es reutilizable y RoleRun NO modifica la mochila al
        # enseñarla. Por tanto basta una prueba guest viva, estable y ligada a la
        # sesión exacta. La escritura del movimiento se valida por separado sobre
        # el PK7 de party como cualquier otro cambio de movimiento.
        guest_anchor = self._tm_guest_inventory_anchor
        if guest_anchor is not None and guest_anchor[0] == expected_session:
            _session, guest_base, _previous = guest_anchor
            guest_live = self._read_stable_guest_items(client, int(guest_base))
            if guest_live is None:
                self._tm_guest_inventory_anchor = None
                self._tm_inventory_session = None
                raise USUMLiveError(
                    "La mochila guest dejó de ser estable antes de enseñar la MT. Abre de nuevo el selector."
                )
            inventory = self._parse_tm_items_block(guest_live)
            quantity = int(inventory.get(int(change.item_id), 0))
            if quantity <= 0:
                raise USUMLiveError(
                    f"{change.item_name} ya no está en la mochila viva. No se escribió ningún byte; abre de nuevo el selector."
                )
            self._tm_guest_inventory_anchor = (
                expected_session, int(guest_base), bytes(guest_live)
            )
            return

        # Compatibilidad con una calibración host+guest histórica que ya pudiera
        # estar demostrada en la sesión. Las utilidades de inventario siguen
        # usando esta prueba fuerte porque ellas sí escriben la mochila.
        cached = self._utility_block_cache.get("items")
        session = self._tm_inventory_session
        if cached is None or session != expected_session:
            raise USUMLiveError(
                "La mochila viva no está demostrada para esta sesión. Abre de nuevo el selector de MT antes de enseñar el movimiento."
            )
        host_pid, host_base, guest_base, _expected = cached
        host_memory = self.host_memory_factory()
        list_processes = getattr(host_memory, "list_azahar_processes", None)
        if callable(list_processes):
            try:
                if not any(int(info.pid) == int(host_pid) for info in list_processes()):
                    raise USUMLiveError("El proceso host de Azahar cambió desde que se validó la mochila.")
            except USUMLiveError:
                raise
            except Exception as exc:
                raise USUMLiveError("No se pudo volver a validar el proceso host de Azahar antes de enseñar la MT.") from exc
        handle = None
        try:
            handle = host_memory.open_process(int(host_pid))
            host_live = bytes(host_memory.read(handle, int(host_base), USUM_SAVE_ITEM_BLOCK_SIZE))
            guest_live = bytes(client.read_memory(int(guest_base), USUM_SAVE_ITEM_BLOCK_SIZE))
        except Exception as exc:
            self._utility_block_cache.pop("items", None)
            self._tm_inventory_session = None
            self._tm_guest_inventory_anchor = None
            self._tm_party_anchor = None
            raise USUMLiveError("No se pudo volver a leer la mochila host+guest antes de enseñar la MT.") from exc
        finally:
            if handle is not None:
                try:
                    host_memory.close_process(handle)
                except Exception:
                    pass
        if host_live != guest_live:
            self._utility_block_cache.pop("items", None)
            self._tm_inventory_session = None
            self._tm_guest_inventory_anchor = None
            self._tm_party_anchor = None
            raise USUMLiveError(
                "La mochila host y guest dejaron de ser la misma copia viva. Abre de nuevo el selector antes de enseñar la MT."
            )
        self._utility_block_cache["items"] = (
            int(host_pid), int(host_base), int(guest_base), bytes(guest_live)
        )
        inventory = self._parse_tm_items_block(guest_live)
        quantity = int(inventory.get(int(change.item_id), 0))
        if quantity <= 0:
            raise USUMLiveError(
                f"{change.item_name} ya no está en la mochila viva. No se escribió ningún byte; abre de nuevo el selector."
            )

    def _validated_tm_party_target(
        self, *, process: AzaharProcess, party_base: int, original_capture: Sequence[bytes], host_memory,
    ) -> HostPartyTarget:
        """Revalida la ancla host de party demostrada al abrir la mochila de MT.

        Una party exacta puede existir varias veces en el proceso de Azahar. El
        selector de MT ya resolvió esa ambigüedad usando una segunda estructura
        independiente (la mochila) y una igualdad host+guest. Reutilizamos solo
        esa relación demostrada y volvemos a comprobar TODOS los PK7/stats vivos
        antes de escribir; nunca escogemos una copia por orden o dirección.
        """
        expected_session = (
            int(process.title_id), int(process.process_id), str(process.name), int(party_base)
        )
        anchor = self._tm_party_anchor
        if anchor is None or anchor[0] != expected_session:
            raise USUMLiveError(
                "La party host ligada a la mochila de MT no está demostrada para esta sesión. "
                "Abre de nuevo el selector de MT; no se escribió ningún byte."
            )
        target = anchor[1]
        list_processes = getattr(host_memory, "list_azahar_processes", None)
        if callable(list_processes):
            try:
                if not any(int(info.pid) == int(target.pid) for info in list_processes()):
                    raise USUMLiveError(
                        "El proceso host de Azahar cambió desde que se demostró la party de la MT. "
                        "Abre de nuevo el selector; no se escribió ningún byte."
                    )
            except USUMLiveError:
                raise
            except Exception as exc:
                raise USUMLiveError(
                    "No se pudo revalidar el proceso host de Azahar antes de escribir la MT; no se escribió ningún byte."
                ) from exc

        raws = [bytes(raw) for raw in original_capture]
        nonempty = [
            index for index, raw in enumerate(raws)
            if len(raw) >= PK7_STORED_SIZE and any(raw[:PK7_STORED_SIZE])
        ]
        if not nonempty:
            raise USUMLiveError("La party viva quedó vacía antes de escribir la MT; no se escribió ningún byte.")
        handle = None
        try:
            handle = host_memory.open_process(int(target.pid))
            for index in nonempty:
                raw = raws[index]
                address = int(target.host_party_base) + index * USUM_PARTY_STRIDE
                stored = bytes(host_memory.read(handle, address, PK7_STORED_SIZE))
                stats = bytes(host_memory.read(handle, address + USUM_PARTY_STATS_OFFSET, USUM_PARTY_STATS_SIZE))
                expected_stats = raw[PK7_STORED_SIZE:PK7_STORED_SIZE + USUM_PARTY_STATS_SIZE]
                if stored != raw[:PK7_STORED_SIZE] or (
                    len(expected_stats) == USUM_PARTY_STATS_SIZE and stats != expected_stats
                ):
                    raise USUMLiveError(
                        "La party host ligada a la mochila ya no coincide byte por byte con la party guest actual. "
                        "Abre de nuevo el selector de MT; no se escribió ningún byte."
                    )
        except WindowsProcessMemoryError as exc:
            raise USUMLiveError(str(exc)) from exc
        finally:
            if handle is not None:
                try:
                    host_memory.close_process(handle)
                except Exception:
                    pass
        return HostPartyTarget(int(target.pid), str(target.exe_name), int(target.host_party_base))

    def _validated_pc_party_target(
        self, *, client, process: AzaharProcess, party_base: int, original_capture: Sequence[bytes], host_memory,
    ) -> HostPartyTarget:
        """Demuestra de nuevo qué copia host corresponde a la party guest actual.

        Alpha.29 no depende únicamente de la ancla de party capturada antes de un
        movimiento Equipo↔PC. Azahar puede conservar buffers idénticos y una
        transición puede invalidar esa fotografía justo cuando necesitamos escribir
        el marcador del entrante. Si existe una matriz PC ya demostrada para la
        sesión, la relemos COMPLETA host+guest y usamos su traslación probada para
        derivar la dirección host de la party actual. Después volvemos a comparar
        stored+stats de todos los miembros vivos antes de devolver una dirección.
        """
        expected_session = (
            int(process.title_id), int(process.process_id), str(process.name), int(party_base)
        )

        candidate_targets: list[HostPartyTarget] = []
        anchor = self._pc_party_anchor
        if anchor is not None and anchor[0] == expected_session:
            candidate_targets.append(anchor[1])

        # La dirección de BoxPokemon puede seguir siendo válida aunque su CONTENIDO
        # haya cambiado por el intercambio. Revalidamos la matriz actual y, solo si
        # host==guest vuelve a cumplirse, reutilizamos la misma traducción FCRAM.
        cached = self._pc_live_cache
        cache_error: Exception | None = None
        if cached is not None and cached[0] == expected_session:
            try:
                host_pid = int(cached[1])
                host_pc_base = int(cached[2])
                guest_pc_base = int(cached[3])
                box_count = int(cached[4])
                box_slot_count = int(cached[5])
                self._read_proven_pc_matrix(
                    client=client, host_memory=host_memory,
                    host_pid=host_pid, host_base=host_pc_base, guest_base=guest_pc_base,
                    box_count=box_count, box_slot_count=box_slot_count,
                )
                exe_name = "azahar.exe"
                list_processes = getattr(host_memory, "list_azahar_processes", None)
                if callable(list_processes):
                    for info in list_processes():
                        if int(info.pid) == host_pid:
                            exe_name = str(info.exe_name)
                            break
                elif anchor is not None and int(anchor[1].pid) == host_pid:
                    exe_name = str(anchor[1].exe_name)
                derived_party_base = host_pc_base + (int(party_base) - guest_pc_base)
                candidate_targets.append(HostPartyTarget(host_pid, exe_name, derived_party_base))
            except Exception as exc:
                cache_error = exc

        # Misma dirección demostrada por dos caminos = una sola candidatura.
        deduped: dict[tuple[int, int], HostPartyTarget] = {}
        for target in candidate_targets:
            deduped[(int(target.pid), int(target.host_party_base))] = target
        candidate_targets = list(deduped.values())
        if not candidate_targets:
            detail = f" ({cache_error})" if cache_error is not None else ""
            raise USUMLiveError(
                "La relación party↔PC no pudo demostrarse para la sesión actual" + detail + ". "
                "No se escribió ningún byte."
            )

        raws = [bytes(raw) for raw in original_capture]
        nonempty = [
            index for index, raw in enumerate(raws)
            if len(raw) >= PK7_STORED_SIZE and any(raw[:PK7_STORED_SIZE])
        ]
        if not nonempty:
            raise USUMLiveError("La party viva quedó vacía; no se reutilizó la prueba del PC.")

        live_pids: set[int] | None = None
        list_processes = getattr(host_memory, "list_azahar_processes", None)
        if callable(list_processes):
            try:
                live_pids = {int(info.pid) for info in list_processes()}
            except Exception as exc:
                raise USUMLiveError(
                    "No se pudo revalidar el proceso host de Azahar ligado al PC; no se escribió ningún byte."
                ) from exc

        valid: list[HostPartyTarget] = []
        for target in candidate_targets:
            if live_pids is not None and int(target.pid) not in live_pids:
                continue
            handle = None
            try:
                handle = host_memory.open_process(int(target.pid))
                matches = True
                for index in nonempty:
                    raw = raws[index]
                    address = int(target.host_party_base) + index * USUM_PARTY_STRIDE
                    stored = bytes(host_memory.read(handle, address, PK7_STORED_SIZE))
                    stats = bytes(host_memory.read(
                        handle, address + USUM_PARTY_STATS_OFFSET, USUM_PARTY_STATS_SIZE,
                    ))
                    expected_stats = raw[PK7_STORED_SIZE:PK7_STORED_SIZE + USUM_PARTY_STATS_SIZE]
                    if stored != raw[:PK7_STORED_SIZE] or stats != expected_stats:
                        matches = False
                        break
                if matches:
                    valid.append(target)
            except WindowsProcessMemoryError:
                continue
            finally:
                if handle is not None:
                    try:
                        host_memory.close_process(handle)
                    except Exception:
                        pass

        if len(valid) != 1:
            if not valid:
                raise USUMLiveError(
                    "La prueba PC host↔guest no conduce a una party host que coincida byte por byte con la party guest actual; "
                    "no se escribió ningún byte."
                )
            raise USUMLiveError(
                f"La prueba PC todavía conduce a {len(valid)} copias host válidas de la party; "
                "por seguridad no se escribió ningún byte."
            )
        target = valid[0]
        # Refrescamos la ancla con la composición ACTUAL. La siguiente escritura
        # de la misma transición no vuelve a depender de la fotografía anterior.
        self._pc_party_anchor = (
            expected_session,
            HostPartyTarget(int(target.pid), str(target.exe_name), int(target.host_party_base)),
        )
        return HostPartyTarget(int(target.pid), str(target.exe_name), int(target.host_party_base))

    def _resolve_live_utility_block(
        self, *, client, host_memory, host_target: HostPartyTarget, party_base: int,
        kind: str, original: bytes,
    ) -> tuple[object, int, int, bytes]:
        """Localiza un bloque solo si host FCRAM y guest RPC prueban la misma copia."""
        cached = self._utility_block_cache.get(kind)
        if cached is not None and int(cached[0]) == int(host_target.pid):
            _pid, host_base, guest_base, expected = cached
            handle = host_memory.open_process(int(host_target.pid))
            try:
                host_now = bytes(host_memory.read(handle, int(host_base), len(expected)))
                guest_now = bytes(client.read_memory(int(guest_base), len(expected)))
                if host_now == expected and guest_now == expected:
                    return handle, int(host_base), int(guest_base), expected
            except Exception:
                pass
            host_memory.close_process(handle)
            self._utility_block_cache.pop(kind, None)

        try:
            matches = host_memory.find_exact_block_in_anchor_region(
                pid=int(host_target.pid), anchor_address=int(host_target.host_party_base), pattern=bytes(original),
            )
        except WindowsProcessMemoryError as exc:
            raise USUMLiveError(str(exc)) from exc
        proven: list[tuple[int, int]] = []
        for host_base in matches:
            delta = int(host_base) - int(host_target.host_party_base)
            guest_base = int(party_base) + delta
            if guest_base < 0 or guest_base + len(original) > 0x1_0000_0000:
                continue
            try:
                if bytes(client.read_memory(guest_base, len(original))) == bytes(original):
                    proven.append((int(host_base), int(guest_base)))
            except Exception:
                continue
        if not proven and kind == "misc":
            # Alpha.14 required all 0x200 bytes to equal the last save. Runtime
            # fields can legitimately diverge while Money remains in the same
            # Misc structure. Alpha.15 falls back to distributed exact witnesses
            # and still requires a single host+guest-proven candidate.
            return self._resolve_live_misc_structurally(
                client=client, host_memory=host_memory, host_target=host_target,
                party_base=party_base, original=original,
            )

        if len(proven) != 1:
            if not proven:
                raise USUMLiveError(
                    "RoleRun no pudo demostrar una única copia viva del bloque de UltraSol/UltraLuna dentro del backing FCRAM. "
                    "Guarda dentro del juego, espera a volver al overworld, pulsa F5 y vuelve a intentarlo. No se escribió ningún byte."
                )
            raise USUMLiveError(
                f"RoleRun encontró {len(proven)} copias indistinguibles del bloque vivo de UltraSol/UltraLuna. Por seguridad no se escribió ningún byte."
            )
        host_base, guest_base = proven[0]
        handle = host_memory.open_process(int(host_target.pid))
        host_now = bytes(host_memory.read(handle, host_base, len(original)))
        guest_now = bytes(client.read_memory(guest_base, len(original)))
        if host_now != bytes(original) or guest_now != bytes(original):
            host_memory.close_process(handle)
            raise USUMLiveError("El bloque vivo cambió durante la calibración; no se escribió ningún byte.")
        return handle, host_base, guest_base, bytes(original)

    def _apply_inventory(self, current: SaveGameData, changes: Sequence[PendingInventoryChange]) -> USUMLiveWriteResult:
        if not changes:
            raise USUMLiveError("No hay utilidades de inventario que aplicar.")
        try:
            with self.reader.client_factory() as client:
                process = self.reader._find_usum_process(client.process_list())
                client.set_process(process.process_id)
                party_base = self.reader._locate_party_base(client, process, current)
                original_capture, capture_attempt = self._capture_stable_party(client, party_base)
                try:
                    host_memory = self.host_memory_factory()
                    party_targets = host_memory.find_party_targets(
                        slot_raws=original_capture,
                        stored_size=PK7_STORED_SIZE,
                        stats_offset=USUM_PARTY_STATS_OFFSET,
                        stats_size=USUM_PARTY_STATS_SIZE,
                        stride=USUM_PARTY_STRIDE,
                    )
                except WindowsProcessMemoryError as exc:
                    raise USUMLiveError(str(exc)) from exc
                if len(party_targets) != 1:
                    raise USUMLiveError(
                        "No se pudo demostrar una única party host de Azahar antes de tocar el inventario; no se escribió ningún byte."
                    )
                host_target = party_targets[0]
                applied: list[tuple[object, int, int, bytes, bytes, str]] = []
                handles: list[object] = []
                try:
                    for change in changes:
                        kind, original, _desired, patch_offset, old_patch, new_patch = self._inventory_patch(change)
                        handle, host_base, guest_base, current_block = self._resolve_live_utility_block(
                            client=client, host_memory=host_memory, host_target=host_target,
                            party_base=party_base, kind=kind, original=original,
                        )
                        handles.append(handle)
                        current_patch = current_block[patch_offset:patch_offset + len(new_patch)]
                        # Para mochila seguimos exigiendo que el registro vivo sea
                        # exactamente el del save o el objetivo ya aplicado. Money
                        # es distinto: tras demostrar estructuralmente Misc, el saldo
                        # puede haber cambiado legítimamente desde el último guardado.
                        if kind == "misc" and change.item_key == "money-max":
                            if len(current_patch) != 4:
                                raise USUMLiveError("El campo Money vivo no mide 4 bytes; no se escribió ningún byte.")
                            current_money = struct.unpack("<I", current_patch)[0]
                            if current_money > USUM_MAX_MONEY:
                                raise USUMLiveError("El campo Money vivo no contiene un saldo válido de UltraSol/UltraLuna; no se escribió ningún byte.")
                        elif current_patch != old_patch and current_patch != new_patch:
                            raise USUMLiveError(
                                f"El campo vivo de {change.item_name} cambió respecto al main testigo. Guarda dentro del juego y vuelve a intentarlo."
                            )
                        if current_patch == new_patch:
                            continue
                        new_block = bytearray(current_block)
                        new_block[patch_offset:patch_offset + len(new_patch)] = new_patch
                        host_address = host_base + patch_offset
                        guest_address = guest_base + patch_offset
                        try:
                            host_memory.write(handle, host_address, new_patch)
                            host_check = bytes(host_memory.read(handle, host_address, len(new_patch)))
                            guest_check = bytes(client.read_memory(guest_address, len(new_patch)))
                            full_guest = bytes(client.read_memory(guest_base, len(new_block)))
                        except WindowsProcessMemoryError as exc:
                            raise USUMLiveError(str(exc)) from exc
                        if host_check != new_patch or guest_check != new_patch or full_guest != bytes(new_block):
                            # rollback inmediato del único campo tocado
                            try:
                                host_memory.write(handle, host_address, current_patch)
                            except Exception:
                                pass
                            raise USUMLiveError(
                                f"Azahar no confirmó {change.item_name} en la copia guest viva; RoleRun restauró el campo original."
                            )
                        applied.append((handle, host_address, guest_address, current_patch, new_patch, kind))
                        self._utility_block_cache[kind] = (
                            int(host_target.pid), int(host_base), int(guest_base), bytes(new_block)
                        )

                    game = self.reader._build_game(original_capture, current, process, party_base)
                    return USUMLiveWriteResult(
                        game=game, process=process, attempts=capture_attempt,
                        applied_count=len(changes), already_applied=not bool(applied),
                    )
                except Exception as exc:
                    rollback_errors: list[str] = []
                    for handle, host_address, guest_address, old_patch, _new_patch, kind in reversed(applied):
                        try:
                            host_memory.write(handle, host_address, old_patch)
                            if bytes(host_memory.read(handle, host_address, len(old_patch))) != old_patch:
                                rollback_errors.append(f"{kind}: host no confirmó rollback")
                            if bytes(client.read_memory(guest_address, len(old_patch))) != old_patch:
                                rollback_errors.append(f"{kind}: guest no confirmó rollback")
                            self._utility_block_cache.pop(kind, None)
                        except Exception as rollback_exc:
                            rollback_errors.append(f"{kind}: {rollback_exc}")
                    if rollback_errors:
                        raise USUMLiveError(
                            f"La utilidad SM falló: {exc}. Además no se pudo confirmar todo el rollback: " + "; ".join(rollback_errors)
                        ) from exc
                    raise
                finally:
                    seen: set[int] = set()
                    for handle in handles:
                        key = int(getattr(handle, "value", 0) or 0) if hasattr(handle, "value") else id(handle)
                        if key in seen:
                            continue
                        seen.add(key)
                        try:
                            host_memory.close_process(handle)
                        except Exception:
                            pass
        except AzaharRPCError as exc:
            raise USUMLiveError(str(exc)) from exc

    @staticmethod
    def _relative_block_match_metrics(
        saved: bytes, live: bytes, *, window_size: int = 16, windows_per_quartile: int = 4,
        excluded_ranges: Sequence[tuple[int, int]] = (),
    ) -> dict[str, object]:
        """Mide evidencia estructural sin buscar ninguna dirección.

        Se usa únicamente DESPUÉS de que una base host/guest ya haya quedado
        anclada por otro bloque independiente. Compara el bloque relativo de esa
        misma imagen viva con el ``main`` y exige ventanas exactas distribuidas.
        """
        original = bytes(saved)
        current = bytes(live)
        if len(original) != len(current):
            return {
                "matching_windows": 0, "matching_window_offsets": [],
                "quartiles": [], "quartile_count": 0, "equal_bytes": 0,
                "selected_window_count": 0,
            }
        windows = WindowsProcessMemory._structural_windows(
            original, excluded_ranges=excluded_ranges,
            window_size=int(window_size), windows_per_quartile=int(windows_per_quartile),
        )
        matching = [
            int(offset) for offset, chunk in windows
            if current[int(offset):int(offset) + len(chunk)] == bytes(chunk)
        ]
        quartiles = sorted({
            min(3, (int(offset) * 4) // max(1, len(original))) for offset in matching
        })
        excluded: set[int] = set()
        for begin, end in excluded_ranges:
            excluded.update(range(max(0, int(begin)), min(len(original), int(end))))
        equal_bytes = sum(
            1 for index, (a, b) in enumerate(zip(original, current))
            if index not in excluded and a == b
        )
        return {
            "matching_windows": len(matching),
            "matching_window_offsets": matching,
            "quartiles": quartiles,
            "quartile_count": len(quartiles),
            "equal_bytes": int(equal_bytes),
            "selected_window_count": len(windows),
        }

    def _resolve_pc_from_live_save_mirror(
        self, *, client, host_memory, party_base: int, party_targets: Sequence[HostPartyTarget],
        saved_bytes: bytes, current: SaveGameData, anchors: Sequence[SavePokemon],
        box_count: int, box_slot_count: int,
    ) -> tuple[int, int, int, dict[tuple[int, int], SavePokemon | None], list[dict[str, object]]]:
        """Fallback alpha.21: demuestra BoxPokemon aunque el main tuviera PC vacío.

        PKHeX define Items/Misc/BoxLayout/BoxPokemon como bloques del mismo SAV7USUM.
        RoleRun NO convierte esos offsets de archivo directamente en RAM. Primero
        localiza Items por contenido real dentro del backing FCRAM ya anclado a la
        party y lo confirma por RPC; después exige que Misc y BoxLayout aparezcan
        exactamente a sus deltas de archivo, con host==guest y evidencia estructural
        fuerte. Solo entonces prueba BoxPokemon en +0x4E00, vuelve a exigir
        host==guest estable y parsea los 960 PK7/slots vacíos completos.
        """
        matrix_size = _pc_matrix_size(box_count, box_slot_count)
        if matrix_size != USUM_SAVE_PC_BLOCK_SIZE:
            raise USUMLiveError(
                "Las dimensiones que PKHeX devolvió para UltraSol/UltraLuna no corresponden al bloque BoxPokemon oficial "
                f"(esperado 0x{USUM_SAVE_PC_BLOCK_SIZE:X}, recibido 0x{matrix_size:X})."
            )
        required_end = USUM_SAVE_PC_BLOCK_OFFSET + USUM_SAVE_PC_BLOCK_SIZE
        if len(saved_bytes) < required_end:
            raise USUMLiveError("El main SAV7USUM es demasiado pequeño para validar la disposición de bloques del PC.")

        saved_items = bytes(saved_bytes[
            USUM_SAVE_ITEM_BLOCK_OFFSET:USUM_SAVE_ITEM_BLOCK_OFFSET + USUM_SAVE_ITEM_BLOCK_SIZE
        ])
        saved_misc = bytes(saved_bytes[
            USUM_SAVE_MISC_BLOCK_OFFSET:USUM_SAVE_MISC_BLOCK_OFFSET + USUM_SAVE_MISC_BLOCK_SIZE
        ])
        saved_layout = bytes(saved_bytes[
            USUM_SAVE_BOX_LAYOUT_BLOCK_OFFSET:USUM_SAVE_BOX_LAYOUT_BLOCK_OFFSET + USUM_SAVE_BOX_LAYOUT_BLOCK_SIZE
        ])

        unlocated_anchor_ids = {
            _pc_identity(pokemon) for pokemon in anchors
            if pokemon.box is None and pokemon.box_slot is None and _pc_identity(pokemon) is not None
        }
        live_party_ids = {
            _pc_identity(pokemon) for pokemon in current.party if _pc_identity(pokemon) is not None
        }

        evaluated: list[dict[str, object]] = []
        proofs: dict[int, tuple[int, int, dict[tuple[int, int], SavePokemon | None]]] = {}
        for target in party_targets:
            entry: dict[str, object] = {
                "pid": int(target.pid),
                "host_party_base": f"0x{int(target.host_party_base):X}",
            }
            items_handle = None
            try:
                exact_error = None
                try:
                    items_handle, host_items_base, guest_items_base, live_items = self._resolve_live_utility_block(
                        client=client, host_memory=host_memory, host_target=target,
                        party_base=party_base, kind="items", original=saved_items,
                    )
                    entry["items_proof_mode"] = "exact-main-block"
                except USUMLiveError as exc:
                    exact_error = str(exc)
                    items_handle, host_items_base, guest_items_base, live_items = self._resolve_live_items_structurally(
                        client=client, host_memory=host_memory, host_target=target,
                        party_base=party_base, original=saved_items,
                    )
                    entry["items_proof_mode"] = "distributed-structural-witnesses"
                if exact_error is not None:
                    entry["items_exact_rejected"] = exact_error
                entry["host_items_base"] = f"0x{int(host_items_base):X}"
                entry["guest_items_base"] = f"0x{int(guest_items_base):08X}"
                entry["host_party_to_items_delta"] = int(host_items_base) - int(target.host_party_base)
                entry["guest_party_to_items_delta"] = int(guest_items_base) - int(party_base)
                # La propia resolución de Items ya confirmó host==guest; releemos
                # aquí para que toda la cadena use una fotografía coherente.
                if bytes(live_items) != bytes(client.read_memory(int(guest_items_base), USUM_SAVE_ITEM_BLOCK_SIZE)):
                    raise USUMLiveError("Items cambió durante la demostración del espejo SAV7USUM.")
            except Exception as exc:
                entry["rejected"] = f"items-proof-failed: {type(exc).__name__}: {exc}"
                evaluated.append(entry)
                continue
            finally:
                if items_handle is not None:
                    try:
                        host_memory.close_process(items_handle)
                    except Exception:
                        pass

            host_misc_base = int(host_items_base) + (USUM_SAVE_MISC_BLOCK_OFFSET - USUM_SAVE_ITEM_BLOCK_OFFSET)
            guest_misc_base = int(guest_items_base) + (USUM_SAVE_MISC_BLOCK_OFFSET - USUM_SAVE_ITEM_BLOCK_OFFSET)
            host_layout_base = int(host_items_base) + (USUM_SAVE_BOX_LAYOUT_BLOCK_OFFSET - USUM_SAVE_ITEM_BLOCK_OFFSET)
            guest_layout_base = int(guest_items_base) + (USUM_SAVE_BOX_LAYOUT_BLOCK_OFFSET - USUM_SAVE_ITEM_BLOCK_OFFSET)
            host_pc_base = int(host_items_base) + (USUM_SAVE_PC_BLOCK_OFFSET - USUM_SAVE_ITEM_BLOCK_OFFSET)
            guest_pc_base = int(guest_items_base) + (USUM_SAVE_PC_BLOCK_OFFSET - USUM_SAVE_ITEM_BLOCK_OFFSET)
            entry.update({
                "host_misc_base": f"0x{host_misc_base:X}",
                "guest_misc_base": f"0x{guest_misc_base:08X}",
                "host_boxlayout_base": f"0x{host_layout_base:X}",
                "guest_boxlayout_base": f"0x{guest_layout_base:08X}",
                "host_boxpokemon_base": f"0x{host_pc_base:X}",
                "guest_boxpokemon_base": f"0x{guest_pc_base:08X}",
                "assumed_relative_deltas": {
                    "misc_from_items": int(USUM_SAVE_MISC_BLOCK_OFFSET - USUM_SAVE_ITEM_BLOCK_OFFSET),
                    "boxlayout_from_items": int(USUM_SAVE_BOX_LAYOUT_BLOCK_OFFSET - USUM_SAVE_ITEM_BLOCK_OFFSET),
                    "boxpokemon_from_items": int(USUM_SAVE_PC_BLOCK_OFFSET - USUM_SAVE_ITEM_BLOCK_OFFSET),
                },
            })

            handle = None
            try:
                handle = host_memory.open_process(int(target.pid))
                live_misc_host = bytes(host_memory.read(handle, host_misc_base, USUM_SAVE_MISC_BLOCK_SIZE))
                live_misc_guest = bytes(client.read_memory(guest_misc_base, USUM_SAVE_MISC_BLOCK_SIZE))
                live_layout_host = bytes(host_memory.read(handle, host_layout_base, USUM_SAVE_BOX_LAYOUT_BLOCK_SIZE))
                live_layout_guest = bytes(client.read_memory(guest_layout_base, USUM_SAVE_BOX_LAYOUT_BLOCK_SIZE))
            except Exception as exc:
                entry["rejected"] = f"relative-block-read-failed: {type(exc).__name__}: {exc}"
                evaluated.append(entry)
                continue
            finally:
                if handle is not None:
                    try:
                        host_memory.close_process(handle)
                    except Exception:
                        pass

            if live_misc_host != live_misc_guest:
                entry["rejected"] = "relative-misc-host-guest-mismatch"
                evaluated.append(entry)
                continue
            misc_windows = WindowsProcessMemory._structural_windows(
                saved_misc,
                excluded_ranges=((USUM_MISC_MONEY_OFFSET, USUM_MISC_MONEY_OFFSET + 4),),
                window_size=USUM_MISC_STRUCTURAL_WINDOW_SIZE,
                windows_per_quartile=4,
            )
            misc_matching = [
                offset for offset, chunk in misc_windows
                if live_misc_guest[offset:offset + len(chunk)] == chunk
            ]
            misc_metrics = self._misc_structural_metrics(saved_misc, live_misc_guest, misc_matching)
            entry["misc_metrics"] = misc_metrics
            live_money = struct.unpack_from("<I", live_misc_guest, USUM_MISC_MONEY_OFFSET)[0]
            entry["live_money"] = int(live_money)
            if live_money > USUM_MAX_MONEY or not self._misc_structural_metrics_are_strong(misc_metrics):
                entry["rejected"] = "relative-misc-structural-proof-failed"
                evaluated.append(entry)
                continue

            if live_layout_host != live_layout_guest:
                entry["rejected"] = "relative-boxlayout-host-guest-mismatch"
                evaluated.append(entry)
                continue
            layout_metrics = self._relative_block_match_metrics(
                saved_layout, live_layout_guest, window_size=16, windows_per_quartile=4,
            )
            entry["boxlayout_metrics"] = layout_metrics
            if not (
                int(layout_metrics.get("matching_windows", 0)) >= USUM_PC_LAYOUT_MIN_WINDOWS
                and int(layout_metrics.get("quartile_count", 0)) >= USUM_PC_LAYOUT_MIN_QUARTILES
                and int(layout_metrics.get("equal_bytes", 0)) >= USUM_PC_LAYOUT_MIN_EQUAL_BYTES
            ):
                entry["rejected"] = "relative-boxlayout-structural-proof-failed"
                evaluated.append(entry)
                continue

            try:
                _raw, parsed = self._read_proven_pc_matrix(
                    client=client, host_memory=host_memory, host_pid=int(target.pid),
                    host_base=host_pc_base, guest_base=guest_pc_base,
                    box_count=box_count, box_slot_count=box_slot_count,
                )
            except Exception as exc:
                entry["rejected"] = f"boxpokemon-proof-failed: {type(exc).__name__}: {exc}"
                evaluated.append(entry)
                continue

            pc_ids = {
                _pc_identity(pokemon) for pokemon in parsed.values() if _pc_identity(pokemon) is not None
            }
            overlap = sorted(live_party_ids & pc_ids)
            if overlap:
                entry["rejected"] = "boxpokemon-overlaps-live-party"
                entry["overlap_count"] = len(overlap)
                evaluated.append(entry)
                continue
            if unlocated_anchor_ids and not (unlocated_anchor_ids & pc_ids):
                entry["rejected"] = "missing-recent-party-to-pc-witness"
                evaluated.append(entry)
                continue

            entry.update({
                "accepted": True,
                "host_pc_base": f"0x{host_pc_base:X}",
                "guest_pc_base": f"0x{guest_pc_base:08X}",
                "occupied_live_slots": sum(1 for value in parsed.values() if value is not None),
            })
            evaluated.append(entry)
            existing = proofs.get(int(guest_pc_base))
            if existing is not None and existing[2] != parsed:
                raise USUMLiveError("Una misma base guest de BoxPokemon produjo dos lecturas incompatibles.")
            proofs[int(guest_pc_base)] = (int(target.pid), int(host_pc_base), parsed)

        if len(proofs) != 1:
            self._pc_last_resolution = {
                "source": "live-save-mirror-sin-resolver",
                "proofs": len(proofs),
                "evaluated": evaluated,
            }
            if not proofs:
                raise USUMLiveError(
                    "RoleRun no pudo demostrar una única imagen SAV7USUM viva mediante Items + Misc + BoxLayout + BoxPokemon. "
                    "No se publicará el PC como si estuviera vacío."
                )
            raise USUMLiveError(
                f"RoleRun encontró {len(proofs)} imágenes SAV7USUM completas igualmente válidas. Por seguridad no eligió ninguna."
            )
        guest_base, (pid, host_base, parsed) = next(iter(proofs.items()))
        return int(pid), int(host_base), int(guest_base), parsed, evaluated


    def _resolve_pc_from_direct_pk7_matrix(
        self, *, client, host_memory, party_base: int, party_targets: Sequence[HostPartyTarget],
        current: SaveGameData, anchors: Sequence[SavePokemon], box_count: int, box_slot_count: int,
    ) -> tuple[int, int, int, dict[tuple[int, int], SavePokemon | None], list[dict[str, object]]]:
        """Alpha.24: descubre BoxPokemon directamente por estructura PK7 viva.

        No usa el offset de BoxPokemon del SAV, no necesita Pokémon guardados en
        ``main`` y no presupone que Items/Misc/BoxLayout sean contiguos en RAM.
        La búsqueda queda restringida a la región RW que ya contiene una copia
        host COMPLETA de la party viva. Dentro de esa región:

        * sanity==0 solo dispara una comprobación barata; NO cuenta como PK7;
        * antes de conservar un candidato debe superar descifrado/checksum/especie PK7 real;
        * se buscan carreras alineadas de exactamente ``box_count*slot_count``
          registros de 0xE8 donde cada slot sea cero o un PK7 válido;
        * una carrera más larga es ambigua y NO permite elegir una frontera;
        * incluso con una sola ocupación, la frontera exacta de 960 slots y la
          unicidad global de la candidatura deben quedar demostradas;
        * cada base host se traslada a guest exclusivamente por el delta de una
          party host ya demostrada y la matriz completa se relee dos veces en
          host y guest, exigiendo igualdad total antes de publicar el PC.
        """
        total_slots = int(box_count) * int(box_slot_count)
        matrix_size = _pc_matrix_size(box_count, box_slot_count)
        if matrix_size != total_slots * PK7_STORED_SIZE:
            raise USUMLiveError("Las dimensiones del PC no forman una matriz PK7 coherente.")

        live_party_ids = {
            _pc_identity(pokemon) for pokemon in current.party if _pc_identity(pokemon) is not None
        }
        recent_pc_ids = {
            _pc_identity(pokemon) for pokemon in anchors
            if pokemon.box is None and pokemon.box_slot is None and _pc_identity(pokemon) is not None
        }

        # Varias copias de party dentro de la misma asignación RW no justifican
        # releer/reescanear el backing completo. Se agrupan por región.
        groups: dict[tuple[int, int, int], list[HostPartyTarget]] = {}
        evaluated: list[dict[str, object]] = []
        for target in party_targets:
            try:
                region_base, region_size = host_memory.writable_region_for_address(
                    pid=int(target.pid), address=int(target.host_party_base),
                )
            except Exception as exc:
                evaluated.append({
                    "pid": int(target.pid), "host_party_base": f"0x{int(target.host_party_base):X}",
                    "rejected": f"party-region-proof-failed: {type(exc).__name__}: {exc}",
                })
                continue
            groups.setdefault((int(target.pid), int(region_base), int(region_size)), []).append(target)
        if not groups:
            self._pc_last_resolution = {
                "source": "direct-pk7-matrix-sin-regiones", "proofs": 0, "evaluated": evaluated,
            }
            raise USUMLiveError(
                "No se pudo demostrar una región RW de Azahar que contenga la party host viva; no se buscó BoxPokemon."
            )

        proofs: dict[int, tuple[int, int, dict[tuple[int, int], SavePokemon | None]]] = {}
        zero_record = b"\0" * PK7_STORED_SIZE
        for (pid, region_base, region_size), targets in groups.items():
            group_entry: dict[str, object] = {
                "pid": int(pid), "region_base": f"0x{int(region_base):X}",
                "region_size": int(region_size), "party_copy_count": len(targets),
            }
            scan_stats: dict[str, int] = {}
            try:
                header_records = host_memory.find_zero_sanity_records_in_anchor_region(
                    pid=int(pid), anchor_address=int(targets[0].host_party_base),
                    record_size=PK7_STORED_SIZE, sanity_offset=4,
                    max_candidates=USUM_PC_DIRECT_MAX_HEADER_CANDIDATES,
                    candidate_validator=_is_structurally_valid_occupied_pk7,
                    scan_stats=scan_stats,
                )
            except Exception as exc:
                group_entry["pk7_prefilter_stats"] = dict(scan_stats)
                group_entry["rejected"] = f"pk7-header-scan-failed: {type(exc).__name__}: {exc}"
                evaluated.append(group_entry)
                continue
            group_entry["pk7_prefilter_stats"] = dict(scan_stats)
            group_entry["structurally_valid_occupied_header_count"] = len(header_records)

            valid_records: dict[int, SavePokemon | None] = {}
            occupied_records: dict[int, SavePokemon] = {}
            for address, raw in header_records:
                try:
                    parsed = parse_pk7_boxed(bytes(raw), 1, 1, self.reader.move_names)
                except Exception:
                    continue
                valid_records[int(address)] = parsed
                if parsed is not None:
                    occupied_records[int(address)] = parsed
                if len(valid_records) > USUM_PC_DIRECT_MAX_VALID_RECORDS:
                    group_entry["rejected"] = "too-many-structurally-valid-pk7-records"
                    break
            if group_entry.get("rejected"):
                group_entry["valid_record_count"] = len(valid_records)
                group_entry["occupied_record_count"] = len(occupied_records)
                evaluated.append(group_entry)
                continue
            group_entry["valid_record_count"] = len(valid_records)
            group_entry["occupied_record_count"] = len(occupied_records)
            if not occupied_records:
                group_entry["rejected"] = "no-live-boxed-pk7-records-found"
                evaluated.append(group_entry)
                continue

            # Los slots de una misma matriz comparten residuo módulo 0xE8. Solo
            # residuos con al menos un PK7 ocupado pueden contener el PC no vacío.
            occupied_by_residue: dict[int, list[int]] = {}
            for address in occupied_records:
                occupied_by_residue.setdefault(int(address) % PK7_STORED_SIZE, []).append(int(address))

            run_diagnostics: list[dict[str, object]] = []
            candidate_host_bases: dict[int, dict[str, object]] = {}
            handle = None
            try:
                handle = host_memory.open_process(int(pid))
                region_end = int(region_base) + int(region_size)
                last_record_start = region_end - PK7_STORED_SIZE
                for residue, occupied_addresses in occupied_by_residue.items():
                    occupied_addresses.sort()
                    # Separamos clusters que no podrían pertenecer a una misma
                    # matriz de 960 slots. Cada cluster se inspecciona con un
                    # margen completo a ambos lados para demostrar sus fronteras.
                    clusters: list[list[int]] = []
                    for address in occupied_addresses:
                        if not clusters or int(address) - int(clusters[-1][-1]) > matrix_size:
                            clusters.append([int(address)])
                        else:
                            clusters[-1].append(int(address))
                    for cluster in clusters:
                        margin = (total_slots + 2) * PK7_STORED_SIZE
                        wanted_start = max(int(region_base), int(cluster[0]) - margin)
                        wanted_end = min(int(last_record_start), int(cluster[-1]) + margin)
                        lane_start = wanted_start + ((int(residue) - wanted_start) % PK7_STORED_SIZE)
                        lane_last = wanted_end - ((wanted_end - int(residue)) % PK7_STORED_SIZE)
                        if lane_last < lane_start:
                            continue
                        lane_count = ((lane_last - lane_start) // PK7_STORED_SIZE) + 1
                        span_size = (lane_count - 1) * PK7_STORED_SIZE + PK7_STORED_SIZE
                        try:
                            span = bytes(host_memory.read(handle, int(lane_start), int(span_size)))
                        except Exception as exc:
                            run_diagnostics.append({
                                "residue": int(residue), "cluster_occupied": len(cluster),
                                "rejected": f"lane-read-failed: {type(exc).__name__}: {exc}",
                            })
                            continue

                        states: list[int] = []  # 0 invalid, 1 valid empty, 2 valid occupied
                        parsed_by_index: dict[int, SavePokemon] = {}
                        for index in range(int(lane_count)):
                            begin = index * PK7_STORED_SIZE
                            raw = span[begin:begin + PK7_STORED_SIZE]
                            if raw == zero_record:
                                states.append(1)
                                continue
                            try:
                                parsed = parse_pk7_boxed(raw, 1, 1, self.reader.move_names)
                            except Exception:
                                states.append(0)
                                continue
                            if parsed is None:
                                states.append(1)
                            else:
                                states.append(2)
                                parsed_by_index[index] = parsed

                        index = 0
                        while index < len(states):
                            if states[index] == 0:
                                index += 1
                                continue
                            start_index = index
                            occupied_count = 0
                            identities: set[tuple[int, int, int, int]] = set()
                            while index < len(states) and states[index] != 0:
                                if states[index] == 2:
                                    occupied_count += 1
                                    identity = _pc_identity(parsed_by_index.get(index))
                                    if identity is not None:
                                        identities.add(identity)
                                index += 1
                            run_len = index - start_index
                            if occupied_count <= 0 or run_len < total_slots:
                                continue
                            host_base = int(lane_start) + start_index * PK7_STORED_SIZE
                            entry = {
                                "residue": int(residue), "host_run_base": f"0x{host_base:X}",
                                "run_slots": int(run_len), "occupied_slots": int(occupied_count),
                                "touches_scan_start": bool(start_index == 0),
                                "touches_scan_end": bool(index == len(states)),
                            }
                            if run_len != total_slots:
                                entry["rejected"] = "valid-slot-run-boundary-ambiguous"
                                run_diagnostics.append(entry)
                                continue
                            matched_recent = bool(recent_pc_ids & identities)
                            entry["recent_party_to_pc_identity_match"] = matched_recent
                            if recent_pc_ids and not matched_recent:
                                entry["rejected"] = "missing-recent-party-to-pc-witness"
                                run_diagnostics.append(entry)
                                continue
                            candidate_host_bases.setdefault(int(host_base), entry)
                            entry["candidate"] = True
                            run_diagnostics.append(entry)
            finally:
                if handle is not None:
                    try:
                        host_memory.close_process(handle)
                    except Exception:
                        pass

            group_entry["run_candidate_count"] = len(candidate_host_bases)
            group_entry["runs"] = run_diagnostics[:64]
            if not candidate_host_bases:
                group_entry["rejected"] = "no-exact-960-slot-pk7-run"
                evaluated.append(group_entry)
                continue

            for host_base, candidate_meta in candidate_host_bases.items():
                for target in targets:
                    guest_base = int(party_base) + (int(host_base) - int(target.host_party_base))
                    proof_entry: dict[str, object] = {
                        "pid": int(pid), "host_party_base": f"0x{int(target.host_party_base):X}",
                        "host_pc_base": f"0x{int(host_base):X}",
                        "guest_pc_base": f"0x{int(guest_base):08X}",
                        "occupied_slots": int(candidate_meta.get("occupied_slots", 0)),
                    }
                    if guest_base < 0 or guest_base + matrix_size > 0x1_0000_0000:
                        proof_entry["rejected"] = "guest-base-out-of-range"
                        evaluated.append(proof_entry)
                        continue
                    try:
                        _raw, parsed = self._read_proven_pc_matrix(
                            client=client, host_memory=host_memory, host_pid=int(pid),
                            host_base=int(host_base), guest_base=int(guest_base),
                            box_count=box_count, box_slot_count=box_slot_count,
                        )
                    except Exception as exc:
                        proof_entry["rejected"] = f"host-guest-full-matrix-proof-failed: {type(exc).__name__}: {exc}"
                        evaluated.append(proof_entry)
                        continue
                    pc_ids = {
                        _pc_identity(pokemon) for pokemon in parsed.values() if _pc_identity(pokemon) is not None
                    }
                    overlap = live_party_ids & pc_ids
                    if overlap:
                        proof_entry["rejected"] = "boxpokemon-overlaps-live-party"
                        proof_entry["overlap_count"] = len(overlap)
                        evaluated.append(proof_entry)
                        continue
                    if recent_pc_ids and not (recent_pc_ids & pc_ids):
                        proof_entry["rejected"] = "missing-recent-party-to-pc-witness-after-full-read"
                        evaluated.append(proof_entry)
                        continue
                    proof_entry["accepted"] = True
                    proof_entry["occupied_live_slots"] = sum(1 for value in parsed.values() if value is not None)
                    evaluated.append(proof_entry)
                    existing = proofs.get(int(guest_base))
                    if existing is not None and existing[2] != parsed:
                        raise USUMLiveError("Una misma base guest de BoxPokemon produjo dos matrices incompatibles.")
                    proofs[int(guest_base)] = (int(pid), int(host_base), parsed)
            evaluated.append(group_entry)

        if len(proofs) != 1:
            self._pc_last_resolution = {
                "source": "direct-pk7-matrix-sin-resolver", "proofs": len(proofs), "evaluated": evaluated,
            }
            if not proofs:
                raise USUMLiveError(
                    "RoleRun no pudo demostrar una única matriz BoxPokemon viva directamente por estructura PK7. "
                    "No se publicará el PC como si estuviera vacío."
                )
            raise USUMLiveError(
                f"RoleRun encontró {len(proofs)} matrices BoxPokemon completas igualmente válidas. "
                "Por seguridad no eligió ninguna."
            )
        guest_base, (pid, host_base, parsed) = next(iter(proofs.items()))
        return int(pid), int(host_base), int(guest_base), parsed, evaluated

    def _save_pc_diagnostic(self, payload: dict[str, object]) -> Path | None:
        """Persiste evidencia compacta del localizador PC sin volcar Pokémon/RAM completos."""
        wrapped = {
            "format": "rolerun-usum-pc-diagnostic-v2",
            "version": APP_VERSION,
            "created_at": datetime.now().isoformat(timespec="milliseconds"),
            **payload,
        }
        try:
            self.diagnostic_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            archive = self.diagnostic_dir / f"usum-pc-{stamp}.json"
            latest = LOG_DIR / "usum_pc_diagnostic_latest.json"
            text = json.dumps(wrapped, ensure_ascii=False, indent=2, sort_keys=True)
            archive.write_text(text, encoding="utf-8")
            latest.parent.mkdir(parents=True, exist_ok=True)
            latest.write_text(text, encoding="utf-8")
            self.last_diagnostic_path = latest
            return latest
        except Exception:
            return None

    @staticmethod
    def _pc_record_diagnostic(raw: bytes, *, box: int, box_slot: int, move_names: dict[int, str]) -> dict[str, object]:
        """Clasifica un slot PC sin convertir un fallo estructural en un PC vacío.

        Alpha.47 usa esta ruta únicamente para conservar evidencia cuando la matriz
        publicada de USUM deja de ser PK7 válida. No relaja el parser normal.
        """
        chunk = bytes(raw)
        entry: dict[str, object] = {
            "box": int(box),
            "slot": int(box_slot),
            "nonzero_bytes": int(sum(1 for value in chunk if value)),
            "sha256": hashlib.sha256(chunk).hexdigest(),
        }
        if len(chunk) != PK7_STORED_SIZE:
            entry["state"] = "truncated"
            entry["size"] = len(chunk)
            return entry
        if not any(chunk):
            entry["state"] = "zero-empty"
            return entry
        try:
            pokemon = parse_pk7_boxed(chunk, int(box), int(box_slot), move_names)
        except Exception as exc:
            entry["state"] = "invalid"
            entry["error"] = f"{type(exc).__name__}: {exc}"
            return entry
        if pokemon is None:
            entry["state"] = "valid-empty"
            return entry
        entry.update({
            "state": "valid-occupied",
            "species_id": int(pokemon.species_id),
            "pid": int(pokemon.pid or 0),
            "tid": int(pokemon.tid or 0),
            "sid": int(pokemon.sid or 0),
        })
        return entry

    def _build_pc_layout_diagnostic(
        self, *, client, live_raw: bytes, save_path: str | Path, guest_base: int,
        box_count: int, box_slot_count: int, party_base: int,
    ) -> dict[str, object]:
        """Compara la candidata RAM con el ``main`` y BoxLayout sin escanear FCRAM.

        La salida está pensada para decidir la siguiente implementación sobre datos
        físicos de la Run del usuario. El método nunca escribe memoria.
        """
        total_slots = int(box_count) * int(box_slot_count)
        expected_size = total_slots * PK7_STORED_SIZE
        raw_live = bytes(live_raw[:expected_size])
        payload: dict[str, object] = {
            "stage": "alpha48-bounded-pc-layout-diagnostic",
            "party_base": f"0x{int(party_base):08X}",
            "guest_pc_base": f"0x{int(guest_base):08X}",
            "matrix_size": int(expected_size),
            "box_count": int(box_count),
            "box_slot_count": int(box_slot_count),
            "fcram_scan_attempted": False,
            "live_matrix_sha256": hashlib.sha256(raw_live).hexdigest(),
        }

        # La referencia pública de CurrentBox es una lectura pequeña e independiente.
        try:
            current_box_raw = bytes(client.read_memory(int(USUM_PC_CURRENT_BOX_REFERENCE), 1))
            payload["guest_current_box_reference"] = {
                "address": f"0x{int(USUM_PC_CURRENT_BOX_REFERENCE):08X}",
                "raw_hex": current_box_raw.hex(),
                "value": int(current_box_raw[0]) if len(current_box_raw) == 1 else None,
            }
        except Exception as exc:
            payload["guest_current_box_reference"] = {"error": f"{type(exc).__name__}: {exc}"}

        saved_file: bytes | None = None
        path = Path(save_path).expanduser().resolve()
        try:
            saved_file = path.read_bytes()
            payload["save"] = {
                "path_name": path.name,
                "size": len(saved_file),
                "sha256": hashlib.sha256(saved_file).hexdigest(),
            }
        except Exception as exc:
            payload["save"] = {"path_name": path.name, "error": f"{type(exc).__name__}: {exc}"}

        saved_matrix: bytes | None = None
        if saved_file is not None:
            layout_start = int(USUM_SAVE_BOX_LAYOUT_BLOCK_OFFSET)
            layout_end = layout_start + int(USUM_SAVE_BOX_LAYOUT_BLOCK_SIZE)
            pc_start = int(USUM_SAVE_PC_BLOCK_OFFSET)
            pc_end = pc_start + expected_size
            if len(saved_file) >= layout_end:
                unlocked_abs = layout_start + int(USUM_SAVE_BOX_LAYOUT_UNLOCKED_OFFSET)
                current_abs = layout_start + int(USUM_SAVE_BOX_LAYOUT_CURRENT_BOX_OFFSET)
                payload["saved_boxlayout"] = {
                    "block_offset": f"0x{layout_start:X}",
                    "boxes_unlocked_field_offset": f"0x{unlocked_abs:X}",
                    "boxes_unlocked_raw": int(saved_file[unlocked_abs]),
                    "current_box_field_offset": f"0x{current_abs:X}",
                    "current_box_raw": int(saved_file[current_abs]),
                }
            else:
                payload["saved_boxlayout"] = {"error": "main-too-small-for-boxlayout"}
            if len(saved_file) >= pc_end:
                saved_matrix = bytes(saved_file[pc_start:pc_end])
                payload["saved_pc_matrix_sha256"] = hashlib.sha256(saved_matrix).hexdigest()
            else:
                payload["saved_pc_matrix_error"] = "main-too-small-for-boxpokemon"

        per_box: list[dict[str, object]] = []
        invalid_examples: list[dict[str, object]] = []
        contiguous_valid_slots = 0
        prefix_open = True
        for box_index in range(int(box_count)):
            counters = {
                "valid_occupied": 0, "valid_empty": 0, "zero_empty": 0, "invalid": 0,
                "saved_valid_occupied": 0, "saved_valid_empty": 0, "saved_zero_empty": 0, "saved_invalid": 0,
                "exact_save_matches": 0,
            }
            for slot_index in range(int(box_slot_count)):
                index = box_index * int(box_slot_count) + slot_index
                start = index * PK7_STORED_SIZE
                chunk = raw_live[start:start + PK7_STORED_SIZE]
                info = self._pc_record_diagnostic(
                    chunk, box=box_index + 1, box_slot=slot_index + 1, move_names=self.reader.move_names,
                )
                state = str(info.get("state"))
                counters[{
                    "valid-occupied": "valid_occupied",
                    "valid-empty": "valid_empty",
                    "zero-empty": "zero_empty",
                    "invalid": "invalid",
                    "truncated": "invalid",
                }.get(state, "invalid")] += 1
                if prefix_open and state != "invalid" and state != "truncated":
                    contiguous_valid_slots += 1
                else:
                    prefix_open = False

                saved_info: dict[str, object] | None = None
                saved_chunk: bytes | None = None
                if saved_matrix is not None:
                    saved_chunk = saved_matrix[start:start + PK7_STORED_SIZE]
                    saved_info = self._pc_record_diagnostic(
                        saved_chunk, box=box_index + 1, box_slot=slot_index + 1, move_names=self.reader.move_names,
                    )
                    saved_state = str(saved_info.get("state"))
                    counters[{
                        "valid-occupied": "saved_valid_occupied",
                        "valid-empty": "saved_valid_empty",
                        "zero-empty": "saved_zero_empty",
                        "invalid": "saved_invalid",
                        "truncated": "saved_invalid",
                    }.get(saved_state, "saved_invalid")] += 1
                    if bytes(chunk) == bytes(saved_chunk):
                        counters["exact_save_matches"] += 1

                if state in {"invalid", "truncated"} and len(invalid_examples) < 12:
                    example = dict(info)
                    example.update({
                        "absolute_address": f"0x{int(guest_base) + start:08X}",
                        "raw_hex": bytes(chunk).hex(),
                    })
                    if saved_info is not None and saved_chunk is not None:
                        example["saved_state"] = saved_info.get("state")
                        example["saved_sha256"] = saved_info.get("sha256")
                        example["saved_raw_hex"] = bytes(saved_chunk).hex()
                        example["matches_saved_exactly"] = bytes(chunk) == bytes(saved_chunk)
                    invalid_examples.append(example)
            per_box.append({"box": box_index + 1, **counters})

        payload["contiguous_valid_slot_prefix"] = int(contiguous_valid_slots)
        payload["contiguous_fully_valid_boxes"] = int(contiguous_valid_slots // int(box_slot_count))
        payload["first_invalid_examples"] = invalid_examples
        payload["per_box"] = per_box
        return payload

    def _read_stable_guest_pc_bytes(
        self, *, client, guest_base: int, box_count: int, box_slot_count: int,
    ) -> bytes:
        """Doble lectura acotada del BoxOffset publicado, sin interpretar slots."""
        size = _pc_matrix_size(box_count, box_slot_count)
        try:
            first = bytes(client.read_memory(int(guest_base), size))
            if USUM_PC_READ_STABLE_DELAY:
                time.sleep(USUM_PC_READ_STABLE_DELAY)
            second = bytes(client.read_memory(int(guest_base), size))
        except Exception as exc:
            raise USUMLiveError(
                "No se pudo completar la doble lectura guest de las cajas UltraSol/UltraLuna."
            ) from exc
        if len(first) != size or len(second) != size:
            raise USUMLiveError(
                f"La lectura guest de BoxPokemon quedó truncada ({len(second)}/{size} bytes)."
            )
        if first != second:
            raise USUMLiveError(
                "La candidatura BoxPokemon cambió entre las dos lecturas guest; se descartó."
            )
        return second

    def _read_stable_guest_pc_matrix(
        self, *, client, guest_base: int, box_count: int, box_slot_count: int,
    ) -> tuple[bytes, dict[tuple[int, int], SavePokemon | None]]:
        """Demuestra una matriz BoxPokemon para LECTURA sin tocar memoria host."""
        raw = self._read_stable_guest_pc_bytes(
            client=client, guest_base=guest_base, box_count=box_count, box_slot_count=box_slot_count,
        )
        parsed = _parse_pc_matrix(
            raw, box_count=box_count, box_slot_count=box_slot_count,
            move_names=self.reader.move_names,
        )
        return raw, parsed

    def _read_proven_pc_matrix(
        self, *, client, host_memory, host_pid: int, host_base: int, guest_base: int,
        box_count: int, box_slot_count: int,
    ) -> tuple[bytes, dict[tuple[int, int], SavePokemon | None]]:
        """Doble lectura estable de toda la matriz y prueba explícita host==guest."""
        size = _pc_matrix_size(box_count, box_slot_count)
        handle = None
        try:
            handle = host_memory.open_process(int(host_pid))
            host_first = bytes(host_memory.read(handle, int(host_base), size))
            guest_first = bytes(client.read_memory(int(guest_base), size))
            if USUM_PC_READ_STABLE_DELAY:
                time.sleep(USUM_PC_READ_STABLE_DELAY)
            host_second = bytes(host_memory.read(handle, int(host_base), size))
            guest_second = bytes(client.read_memory(int(guest_base), size))
        except Exception as exc:
            raise USUMLiveError("No se pudo completar la doble lectura host+guest de las cajas UltraSol/UltraLuna.") from exc
        finally:
            if handle is not None:
                try:
                    host_memory.close_process(handle)
                except Exception:
                    pass
        if not (host_first == guest_first == host_second == guest_second):
            raise USUMLiveError(
                "La candidatura de PC no fue estable o no era la misma copia en host y guest; se descartó."
            )
        parsed = _parse_pc_matrix(
            guest_second, box_count=box_count, box_slot_count=box_slot_count,
            move_names=self.reader.move_names,
        )
        return guest_second, parsed

    def read_pc_for_game(
        self, current: SaveGameData, save_path: str | Path, anchors: Sequence[SavePokemon], *,
        box_count: int, box_slot_count: int,
    ) -> tuple[AzaharProcess, int, dict[tuple[int, int], SavePokemon | None]]:
        """Lee BoxPokemon USUM por la referencia RAM publicada, sin escanear FCRAM.

        PKMN-NTR declara 0x33015AB0 como ``BoxOffset`` para Ultra Sun y Ultra
        Moon. Alpha.46 no convierte esa fuente en una suposición: en CADA sesión
        relee la matriz completa dos veces por RPC, exige estabilidad, parsea los
        960 registros PK7 y rechaza cualquier identidad que aparezca a la vez en
        la party live. CAJAS PC es lectura, por lo que no exige ni busca una copia
        host; el host se demuestra por separado únicamente cuando una operación
        vaya a escribir en BoxPokemon.
        """
        # ``save_path`` se conserva: si la referencia RAM falla, el diagnóstico
        # acotado debe poder contrastar esa fotografía live con el ``main`` real
        # y su BoxLayout. Alpha.47 lo borraba aquí y el propio diagnóstico
        # terminaba en UnboundLocalError antes de aportar esa evidencia.
        del anchors
        matrix_size = _pc_matrix_size(box_count, box_slot_count)
        guest_base = int(USUM_PC_BOX_BASE_REFERENCE)

        try:
            with self.reader.client_factory() as client:
                process = self.reader._find_usum_process(client.process_list())
                client.set_process(process.process_id)
                party_base = self.reader._locate_party_base(client, process, current)
                session = (int(process.title_id), int(process.process_id), str(process.name), int(party_base))

                try:
                    raw_guest = self._read_stable_guest_pc_bytes(
                        client=client, guest_base=guest_base,
                        box_count=box_count, box_slot_count=box_slot_count,
                    )
                    parsed = _parse_pc_matrix(
                        raw_guest, box_count=box_count, box_slot_count=box_slot_count,
                        move_names=self.reader.move_names,
                    )
                except Exception as exc:
                    self._pc_live_cache = None
                    self._pc_party_anchor = None
                    self._pc_last_resolution = {
                        "source": "PKMN-NTR USUM BoxOffset · guest rechazado",
                        "guest_base": int(guest_base),
                        "matrix_size": int(matrix_size),
                        "box_count": int(box_count),
                        "box_slot_count": int(box_slot_count),
                        "error": f"{type(exc).__name__}: {exc}",
                        "fcram_scan_attempted": False,
                    }
                    diagnostic_payload: dict[str, object] = {
                        "stage": "alpha48-boxoffset-proof-failed-with-layout-diagnostic",
                        "party_base": f"0x{int(party_base):08X}",
                        "guest_pc_base": f"0x{guest_base:08X}",
                        "matrix_size": int(matrix_size),
                        "box_count": int(box_count),
                        "box_slot_count": int(box_slot_count),
                        "error": f"{type(exc).__name__}: {exc}",
                        "fcram_scan_attempted": False,
                    }
                    if 'raw_guest' in locals() and isinstance(raw_guest, (bytes, bytearray)):
                        try:
                            diagnostic_payload = self._build_pc_layout_diagnostic(
                                client=client, live_raw=bytes(raw_guest), save_path=save_path,
                                guest_base=guest_base, box_count=box_count, box_slot_count=box_slot_count,
                                party_base=party_base,
                            )
                            diagnostic_payload["error"] = f"{type(exc).__name__}: {exc}"
                        except Exception as diag_exc:
                            diagnostic_payload["diagnostic_error"] = f"{type(diag_exc).__name__}: {diag_exc}"
                    diag = self._save_pc_diagnostic(diagnostic_payload)
                    hint = f" Diagnóstico: {diag}" if diag is not None else ""
                    raise USUMLiveError(
                        "La dirección BoxOffset publicada para UltraSol/UltraLuna no superó la prueba "
                        "completa. Alpha.48 ha generado un diagnóstico acotado RAM↔main↔BoxLayout; "
                        "no se hizo ningún escaneo FCRAM ni ninguna escritura." + hint
                    ) from exc

                live_party_ids = {
                    _pc_identity(pokemon) for pokemon in current.party
                    if _pc_identity(pokemon) is not None
                }
                pc_ids = {
                    _pc_identity(pokemon) for pokemon in parsed.values()
                    if _pc_identity(pokemon) is not None
                }
                overlap = sorted(live_party_ids & pc_ids)
                if overlap:
                    self._pc_live_cache = None
                    self._pc_party_anchor = None
                    self._pc_last_resolution = {
                        "source": "PKMN-NTR USUM BoxOffset · solapamiento party/PC",
                        "guest_base": int(guest_base),
                        "overlap_count": len(overlap),
                        "fcram_scan_attempted": False,
                    }
                    diag = self._save_pc_diagnostic({
                        "stage": "alpha46-pkmn-ntr-boxoffset-party-overlap",
                        "party_base": f"0x{int(party_base):08X}",
                        "guest_pc_base": f"0x{guest_base:08X}",
                        "overlap_count": len(overlap),
                        "overlap": [list(identity) for identity in overlap[:12]],
                        "fcram_scan_attempted": False,
                    })
                    hint = f" Diagnóstico: {diag}" if diag is not None else ""
                    raise USUMLiveError(
                        "La matriz candidata del PC contiene al menos un Pokémon que también está en la "
                        "party viva. Se rechazó para no publicar un PC incoherente." + hint
                    )

                # Lectura demostrada != escritura demostrada. No fabricamos una
                # _pc_live_cache host aquí: ENVIAR AL PC deberá demostrar el
                # backing host por separado antes de WriteProcessMemory.
                self._pc_last_resolution = {
                    "source": "PKMN-NTR USUM BoxOffset -> doble guest -> 960 PK7",
                    "guest_base": int(guest_base),
                    "matrix_size": int(matrix_size),
                    "box_count": int(box_count),
                    "box_slot_count": int(box_slot_count),
                    "occupied_live_slots": sum(1 for value in parsed.values() if value is not None),
                    "host_write_proven": False,
                    "fcram_scan_attempted": False,
                }
                self._save_pc_diagnostic({
                    "stage": "alpha46-pkmn-ntr-boxoffset-guest-proof-ok",
                    "party_base": f"0x{int(party_base):08X}",
                    "guest_pc_base": f"0x{guest_base:08X}",
                    "matrix_size": int(matrix_size),
                    "box_count": int(box_count),
                    "box_slot_count": int(box_slot_count),
                    "occupied_live_slots": sum(1 for value in parsed.values() if value is not None),
                    "host_write_proven": False,
                    "fcram_scan_attempted": False,
                })
                return process, int(guest_base), parsed
        except AzaharRPCError as exc:
            raise USUMLiveError(str(exc)) from exc

    def _try_fast_usum_pc_candidates(
        self, *, client, host_memory, party_base: int, party_targets: Sequence[HostPartyTarget],
        current: SaveGameData, box_count: int, box_slot_count: int,
    ) -> tuple[int, int, int, dict[tuple[int, int], SavePokemon | None], list[dict[str, object]]] | None:
        """Demuestra el backing host del BoxOffset USUM sin escanear FCRAM.

        La base guest 0x33015AB0 está documentada como BoxOffset por PKMN-NTR.
        Para ESCRIBIR no basta: cada copia host derivada de una party host ya
        demostrada debe contener exactamente la misma matriz completa que guest.
        No se prueban offsets vecinos ni se realiza descubrimiento estructural.
        """
        candidates = (int(USUM_PC_BOX_BASE_REFERENCE),)
        live_party_ids = {
            _pc_identity(pokemon) for pokemon in current.party if _pc_identity(pokemon) is not None
        }
        proofs: dict[int, tuple[int, int, dict[tuple[int, int], SavePokemon | None]]] = {}
        evaluated: list[dict[str, object]] = []
        for guest_base in candidates:
            for target in party_targets:
                host_base = int(target.host_party_base) + (int(guest_base) - int(party_base))
                entry: dict[str, object] = {
                    "guest_pc_base": f"0x{int(guest_base):08X}",
                    "host_pc_base": f"0x{int(host_base):X}",
                    "host_party_base": f"0x{int(target.host_party_base):X}",
                    "pid": int(target.pid),
                }
                try:
                    _raw, parsed = self._read_proven_pc_matrix(
                        client=client, host_memory=host_memory, host_pid=int(target.pid),
                        host_base=int(host_base), guest_base=int(guest_base),
                        box_count=int(box_count), box_slot_count=int(box_slot_count),
                    )
                except Exception as exc:
                    entry["rejected"] = f"full-matrix-proof-failed: {type(exc).__name__}: {exc}"
                    evaluated.append(entry)
                    continue
                pc_ids = {
                    _pc_identity(pokemon) for pokemon in parsed.values() if _pc_identity(pokemon) is not None
                }
                overlap = live_party_ids & pc_ids
                if overlap:
                    entry["rejected"] = "boxpokemon-overlaps-live-party"
                    entry["overlap_count"] = len(overlap)
                    evaluated.append(entry)
                    continue
                entry["accepted"] = True
                entry["occupied_live_slots"] = sum(1 for value in parsed.values() if value is not None)
                evaluated.append(entry)
                existing = proofs.get(int(guest_base))
                if existing is not None and existing[2] != parsed:
                    raise USUMLiveError(
                        "Una misma candidata rápida de BoxPokemon produjo dos matrices incompatibles."
                    )
                proofs[int(guest_base)] = (int(target.pid), int(host_base), parsed)

        if not proofs:
            return None
        if len(proofs) != 1:
            raise USUMLiveError(
                f"Las referencias BoxOffset USUM demostraron {len(proofs)} matrices BoxPokemon distintas; "
                "por seguridad no se eligió ninguna."
            )
        guest_base, (pid, host_base, parsed) = next(iter(proofs.items()))
        return int(pid), int(host_base), int(guest_base), parsed, evaluated

    def _ensure_pc_live_cache_for_team_write(
        self, *, client, process: AzaharProcess, party_base: int, original_capture: Sequence[bytes],
        current: SaveGameData, host_memory,
    ) -> tuple[tuple[int, int, str, int], int, int, int, int, int]:
        """Demuestra BoxPokemon en el propio flujo Equipo↔PC si aún no hay caché.

        Alpha.37 elimina el requisito artificial de abrir CAJAS PC antes de usar
        ENVIAR AL PC / PC→Equipo. La operación usa la misma prueba live ya
        validada desde alpha.25: referencia guest conocida solo como CANDIDATA,
        copia host derivada desde una party host demostrada y matriz completa
        32×30 estable con host == guest. El ``main`` no interviene.
        """
        session = (int(process.title_id), int(process.process_id), str(process.name), int(party_base))
        cached = self._pc_live_cache
        if (
            cached is not None and cached[0] == session
            and int(cached[4]) == USUM_PC_BOX_COUNT
            and int(cached[5]) == USUM_PC_BOX_SLOT_COUNT
        ):
            return cached

        try:
            party_targets = host_memory.find_party_targets(
                slot_raws=original_capture, stored_size=PK7_STORED_SIZE,
                stats_offset=USUM_PARTY_STATS_OFFSET, stats_size=USUM_PARTY_STATS_SIZE,
                stride=USUM_PARTY_STRIDE,
            )
        except Exception as exc:
            raise USUMLiveError(
                "RoleRun no pudo demostrar una copia host de la party necesaria para localizar el PC vivo. "
                "No se escribió ningún byte."
            ) from exc
        if not party_targets:
            raise USUMLiveError(
                "RoleRun no encontró una copia host demostrable de la party para localizar el PC vivo. "
                "No se escribió ningún byte."
            )

        # Alpha.46: ni ENVIAR AL PC ni CAJAS PC lanzan descubrimientos FCRAM
        # estructurales. Para escritura se parte exclusivamente del BoxOffset USUM
        # publicado y se exige demostrar su backing host por matriz completa
        # host==guest. Si no pasa, se aborta de inmediato sin tocar memoria.
        try:
            fast = self._try_fast_usum_pc_candidates(
                client=client, host_memory=host_memory, party_base=int(party_base),
                party_targets=party_targets, current=current,
                box_count=USUM_PC_BOX_COUNT, box_slot_count=USUM_PC_BOX_SLOT_COUNT,
            )
        except Exception as exc:
            raise USUMLiveError(
                "RoleRun no pudo validar de forma rápida la matriz PC viva de esta sesión. "
                "No se escribió ningún byte. " + str(exc)
            ) from exc
        if fast is None:
            raise USUMLiveError(
                "RoleRun puede leer el BoxOffset guest publicado de USUM, pero no pudo demostrar todavía "
                "su copia host exacta para escribir en esta sesión. No se escribió ningún byte y no se hará "
                "ningún escaneo FCRAM automático."
            )
        pid, host_base, guest_base, _parsed, evaluated = fast

        delta = int(guest_base) - int(party_base)
        matching_party_targets = [
            target for target in party_targets
            if int(target.pid) == int(pid)
            and int(target.host_party_base) + delta == int(host_base)
        ]
        self._pc_party_anchor = (
            session,
            HostPartyTarget(
                int(matching_party_targets[0].pid),
                str(matching_party_targets[0].exe_name),
                int(matching_party_targets[0].host_party_base),
            ),
        ) if len(matching_party_targets) == 1 else None
        self._pc_live_cache = (
            session, int(pid), int(host_base), int(guest_base),
            USUM_PC_BOX_COUNT, USUM_PC_BOX_SLOT_COUNT,
        )
        self._pc_last_resolution = {
            "source": "team-write auto proof -> direct exact PK7 matrix -> host==guest",
            "host_base": int(host_base), "guest_base": int(guest_base),
            "box_count": USUM_PC_BOX_COUNT, "box_slot_count": USUM_PC_BOX_SLOT_COUNT,
            "evaluated": evaluated,
        }
        return self._pc_live_cache

    def reset_runtime_state(self) -> None:
        self._utility_block_cache.clear()
        self._tm_inventory_session = None
        self._tm_guest_inventory_anchor = None
        self._tm_party_anchor = None
        self._pc_live_cache = None
        self._pc_party_anchor = None
        self._pc_last_resolution = {}
        self._last_badge_source = None
        self._badge_full_scan_failed_at = 0.0

    def _apply_faint_replacement(self, current: SaveGameData, change: PendingTeamChange) -> USUMLiveWriteResult:
        """Sustituye un debilitado y lo mueve al Cementerio en una transacción.

        Reutiliza únicamente estructuras ya demostradas en UltraSol/UltraLuna:
        BoxPokemon 0xE8, PartyData 0x104 y mirror runtime +0x158. El sustituto
        hereda el rol del debilitado; su hueco PC queda vacío y el PK7 stored
        exacto del debilitado se deposita en la posición de Cementerio elegida.
        """
        if change.box is None or change.box_slot is None:
            raise USUMLiveError("La sustitución por baja no contiene el origen PC del sustituto.")
        if change.graveyard_box is None or change.graveyard_box_slot is None:
            raise USUMLiveError("La sustitución por baja no contiene un destino de Cementerio.")
        source_box, source_slot = int(change.box), int(change.box_slot)
        grave_box, grave_slot = int(change.graveyard_box), int(change.graveyard_box_slot)
        if (source_box, source_slot) == (grave_box, grave_slot):
            raise USUMLiveError("El sustituto no puede proceder del mismo hueco reservado para el Cementerio.")

        host_memory = None
        host_handle = None
        attempted: list[tuple[int, int, bytes, str]] = []
        try:
            with self.reader.client_factory() as client:
                process = self.reader._find_usum_process(client.process_list())
                client.set_process(process.process_id)
                party_base = self.reader._locate_party_base(client, process, current)
                original_capture, capture_attempt = self._capture_stable_party(client, party_base)
                live_party = self._read_party_members(original_capture, current)
                if not live_party:
                    raise USUMLiveError("La party viva quedó vacía antes de sustituir al debilitado.")
                occupied_slots = sorted(live_party)
                if occupied_slots != list(range(1, len(occupied_slots) + 1)):
                    raise USUMLiveError("La party viva contiene huecos internos inesperados; no se escribió ningún byte.")

                target_slot = self._resolve_team_swap_party_target(change, live_party)
                outgoing = live_party.get(target_slot)
                if outgoing is None:
                    raise USUMLiveError("El Pokémon debilitado ya no está en el slot esperado.")
                outgoing_identity = self._pokemon_identity(outgoing)
                declared_outgoing = str(change.outgoing_identity or "")
                if declared_outgoing and outgoing_identity != declared_outgoing:
                    raise USUMLiveError("El Pokémon debilitado cambió antes de la sustitución; no se escribió ningún byte.")
                result_role = canonical_role(outgoing.role)
                if result_role not in ROLE_ORDER:
                    raise USUMLiveError("El Pokémon debilitado no conserva un único rol válido; pulsa F5 antes de sustituirlo.")

                host_memory = self.host_memory_factory()
                cached = self._ensure_pc_live_cache_for_team_write(
                    client=client, process=process, party_base=int(party_base),
                    original_capture=original_capture, current=current, host_memory=host_memory,
                )
                host_pid = int(cached[1])
                host_pc_base = int(cached[2])
                guest_pc_base = int(cached[3])
                box_count = int(cached[4])
                box_slot_count = int(cached[5])
                matrix_raw, matrix_parsed = self._read_proven_pc_matrix(
                    client=client, host_memory=host_memory, host_pid=host_pid,
                    host_base=host_pc_base, guest_base=guest_pc_base,
                    box_count=box_count, box_slot_count=box_slot_count,
                )

                source_index = _pc_slot_index(source_box, source_slot, box_slot_count)
                grave_index = _pc_slot_index(grave_box, grave_slot, box_slot_count)
                source_off = source_index * PK7_STORED_SIZE
                grave_off = grave_index * PK7_STORED_SIZE
                source_original = bytes(matrix_raw[source_off:source_off + PK7_STORED_SIZE])
                grave_original = bytes(matrix_raw[grave_off:grave_off + PK7_STORED_SIZE])
                incoming = matrix_parsed.get((source_box, source_slot))
                if incoming is None:
                    raise USUMLiveError("El sustituto ya no está en el hueco PC elegido.")
                incoming_identity = self._pokemon_identity(incoming)
                declared_incoming = str(change.incoming_identity or "")
                if declared_incoming and incoming_identity != declared_incoming:
                    raise USUMLiveError("El Pokémon del PC cambió antes de la sustitución; no se escribió ningún byte.")
                if matrix_parsed.get((grave_box, grave_slot)) is not None:
                    raise USUMLiveError(
                        f"La Caja {grave_box}, hueco {grave_slot} del Cementerio ya no está vacía; no se escribió ningún byte."
                    )

                host_party = self._validated_pc_party_target(
                    client=client, process=process, party_base=party_base,
                    original_capture=original_capture, host_memory=host_memory,
                )
                if int(host_party.pid) != host_pid:
                    raise USUMLiveError("Party y BoxPokemon no pertenecen al mismo proceso host demostrado; no se escribió ningún byte.")
                host_party_base = int(host_party.host_party_base)
                guest_party_base = int(party_base)
                party_payloads = self._read_proven_party_injection_windows(
                    client=client, host_memory=host_memory, host_pid=host_pid,
                    host_party_base=host_party_base, guest_party_base=guest_party_base,
                    expected_sparse=live_party,
                )
                if len(party_payloads) != 6:
                    raise USUMLiveError("La lectura demostrada de PartyData no devolvió los seis slots físicos.")

                incoming_raw, incoming_prepared = self._party_payload_from_box(
                    source_original, role=result_role, remove_move_slots=change.remove_move_slots,
                )
                if self._pokemon_identity(incoming_prepared) != incoming_identity:
                    raise USUMLiveError("El PK7 preparado para sustituir al debilitado perdió su identidad fuerte.")
                if canonical_role(incoming_prepared.role) != result_role:
                    raise USUMLiveError("El sustituto no recibió el rol heredado del debilitado.")

                outgoing_stored = bytes(party_payloads[target_slot - 1][:PK7_STORED_SIZE])
                # Gen 7 no debe vaciar un BoxPokemon escribiendo 0xE8 ceros.
                # El hueco libre real es un PK7 stored cifrado con species=0;
                # escribir ceros puede hacer que el juego lo materialice como Huevo.
                empty_pc_stored = encrypt_pk6_stored(bytes(PK7_STORED_SIZE))
                incoming_stats = bytes(incoming_raw[PK7_STORED_SIZE:PK7_STORED_SIZE + USUM_PARTY_STATS_SIZE])
                party_original = bytes(party_payloads[target_slot - 1])
                party_stats_original = bytes(
                    original_capture[target_slot - 1][PK7_STORED_SIZE:PK7_STORED_SIZE + USUM_PARTY_STATS_SIZE]
                )

                host_source = host_pc_base + source_off
                guest_source = guest_pc_base + source_off
                host_grave = host_pc_base + grave_off
                guest_grave = guest_pc_base + grave_off
                host_party_addr = host_party_base + (target_slot - 1) * USUM_PARTY_STRIDE
                guest_party_addr = guest_party_base + (target_slot - 1) * USUM_PARTY_STRIDE
                host_stats_addr = host_party_addr + USUM_PARTY_STATS_OFFSET
                guest_stats_addr = guest_party_addr + USUM_PARTY_STATS_OFFSET

                host_handle = host_memory.open_process(host_pid)
                # Preflight completo de las cuatro regiones de la transacción.
                checks = (
                    (host_source, guest_source, source_original, "PC sustituto"),
                    (host_grave, guest_grave, grave_original, "PC Cementerio"),
                    (host_party_addr, guest_party_addr, party_original, "PartyData"),
                    (host_stats_addr, guest_stats_addr, party_stats_original, "mirror stats"),
                )
                for haddr, gaddr, original, label in checks:
                    if bytes(host_memory.read(host_handle, haddr, len(original))) != original:
                        raise USUMLiveError(f"{label} host cambió antes de escribir; no se tocó ningún byte.")
                    if bytes(client.read_memory(gaddr, len(original))) != original:
                        raise USUMLiveError(f"{label} guest cambió antes de escribir; no se tocó ningún byte.")

                try:
                    writes = (
                        (host_source, guest_source, source_original, empty_pc_stored, "PC sustituto"),
                        (host_grave, guest_grave, grave_original, outgoing_stored, "PC Cementerio"),
                        (host_party_addr, guest_party_addr, party_original, bytes(incoming_raw), "PartyData"),
                        (host_stats_addr, guest_stats_addr, party_stats_original, incoming_stats, "mirror stats"),
                    )
                    for haddr, gaddr, original, desired, label in writes:
                        host_memory.write(host_handle, haddr, desired)
                        attempted.append((int(haddr), int(gaddr), bytes(original), label))
                        if bytes(host_memory.read(host_handle, haddr, len(desired))) != bytes(desired):
                            raise USUMLiveError(f"WriteProcessMemory no confirmó {label}.")

                    expected_members = dict(live_party)
                    expected_members[target_slot] = incoming_prepared
                    expected_ids = {slot: self._pokemon_identity(mon) for slot, mon in expected_members.items()}

                    def verify() -> tuple[tuple[bytes, ...], dict[int, SavePokemon]]:
                        direct = self._read_proven_party_injection_windows(
                            client=client, host_memory=host_memory, host_pid=host_pid,
                            host_party_base=host_party_base, guest_party_base=guest_party_base,
                            expected_sparse=expected_members,
                        )
                        if bytes(direct[target_slot - 1]) != bytes(incoming_raw):
                            raise USUMLiveError("PartyData no confirmó al sustituto final.")
                        sparse_capture, _ = self._capture_stable_party(client, guest_party_base)
                        sparse_party = self._read_party_members(sparse_capture, current)
                        actual_ids = {slot: self._pokemon_identity(mon) for slot, mon in sparse_party.items()}
                        if actual_ids != expected_ids:
                            raise USUMLiveError("El reader live normal no confirmó la sustitución por baja.")
                        sparse_actual = bytes(sparse_capture[target_slot - 1])
                        expected_sparse = (
                            bytes(incoming_raw[:PK7_STORED_SIZE]) + incoming_stats + (b"\0" * USUM_PARTY_TAIL_PADDING)
                        )
                        if sparse_actual != expected_sparse:
                            raise USUMLiveError("El slot runtime sparse no convergió al sustituto esperado.")

                        _raw, parsed = self._read_proven_pc_matrix(
                            client=client, host_memory=host_memory, host_pid=host_pid,
                            host_base=host_pc_base, guest_base=guest_pc_base,
                            box_count=box_count, box_slot_count=box_slot_count,
                        )
                        if parsed.get((source_box, source_slot)) is not None:
                            raise USUMLiveError("El hueco origen del sustituto no quedó vacío.")
                        if bytes(client.read_memory(guest_source, PK7_STORED_SIZE)) != empty_pc_stored:
                            raise USUMLiveError("El hueco origen del sustituto no confirmó el PK7 vacío cifrado esperado.")
                        grave_mon = parsed.get((grave_box, grave_slot))
                        if grave_mon is None or self._pokemon_identity(grave_mon) != outgoing_identity:
                            raise USUMLiveError("El Cementerio no confirmó al Pokémon debilitado.")
                        if bytes(client.read_memory(guest_grave, PK7_STORED_SIZE)) != outgoing_stored:
                            raise USUMLiveError("El Cementerio no confirmó los 0xE8 bytes exactos del debilitado.")
                        return sparse_capture, sparse_party

                    time.sleep(max(0.12, float(getattr(self.reader, "stable_delay", 0.06)) * 2.0))
                    verify()
                    time.sleep(max(0.45, float(getattr(self.reader, "stable_delay", 0.06)) * 5.0))
                    verified_sparse, _ = verify()
                    game = self.reader._build_game(verified_sparse, current, process, party_base, live_write=True)
                    change.incoming_role = result_role
                    session = (int(process.title_id), int(process.process_id), str(process.name), int(party_base))
                    self._pc_party_anchor = (
                        session, HostPartyTarget(host_pid, str(host_party.exe_name), host_party_base),
                    )
                    return USUMLiveWriteResult(
                        game=game, process=process, attempts=int(capture_attempt),
                        applied_count=1, already_applied=False,
                    )
                except Exception as exc:
                    rollback_errors: list[str] = []
                    for haddr, gaddr, original, label in reversed(attempted):
                        try:
                            host_memory.write(host_handle, haddr, original)
                            if bytes(host_memory.read(host_handle, haddr, len(original))) != original:
                                rollback_errors.append(f"{label}: host no confirmó rollback")
                        except Exception as rollback_exc:
                            rollback_errors.append(f"{label}: {rollback_exc}")
                    if attempted and not rollback_errors:
                        try:
                            time.sleep(max(0.03, float(getattr(self.reader, "stable_delay", 0.06))))
                            for _haddr, gaddr, original, label in attempted:
                                if bytes(client.read_memory(gaddr, len(original))) != original:
                                    rollback_errors.append(f"{label}: guest no confirmó rollback")
                        except Exception as rollback_exc:
                            rollback_errors.append(f"guest rollback: {rollback_exc}")
                    if rollback_errors:
                        raise USUMLiveError(
                            f"La sustitución por baja falló: {exc}. No se pudo confirmar toda la restauración: "
                            + "; ".join(rollback_errors)
                        ) from exc
                    if attempted:
                        raise USUMLiveError(
                            f"La sustitución por baja falló: {exc}. RoleRun restauró y verificó party + PC + Cementerio originales."
                        ) from exc
                    raise
        except AzaharRPCError as exc:
            raise USUMLiveError(str(exc)) from exc
        finally:
            if host_memory is not None and host_handle is not None:
                try:
                    host_memory.close_process(host_handle)
                except Exception:
                    pass

    def _apply_team_swap(self, current: SaveGameData, change: PendingTeamChange) -> USUMLiveWriteResult:
        """Aplica un traslado Equipo↔PC sobre las representaciones live demostradas.

        Alpha.37 extiende el writer 1↔1 validado en alpha.35 a las dos operaciones
        que cambian el tamaño del equipo:

        - ``party-to-box``: deposita el miembro saliente en un hueco PC vacío y
          compacta la party usando los PartyData + mirrors YA leídos de los miembros
          que se desplazan. No reconstruye sus bytes runtime.
        - ``box-to-party``: ocupa exclusivamente el primer slot vacío al final de
          una party compacta y asigna el primer rol libre de izquierda a derecha.

        En las tres operaciones el PC (0xE8), PartyData contiguo (0x104) y mirror
        sparse de stats (+0x158, 0x16) se escriben en una única transacción. La UI
        no recibe éxito hasta que host↔guest, el reader sparse normal y BoxPokemon
        confirman la composición final. Cualquier fallo restaura todos los bytes.
        """
        operation = str(change.operation)
        if operation not in {"swap-party-box", "party-to-box", "box-to-party"}:
            raise USUMLiveError(
                "UltraSol/UltraLuna alpha.37 permite CAMBIAR CON PC, ENVIAR AL PC y PC→Equipo con hueco libre. "
                "La operación solicitada todavía no está soportada; no se escribió ningún byte."
            )
        if operation != "party-to-box" and (change.box is None or change.box_slot is None):
            raise USUMLiveError("El cambio Equipo↔PC no contiene una posición de caja válida.")
        host_memory = None
        host_handle = None
        # (host_addr, guest_addr, original_bytes, label). Cada región se añade
        # solo después de haber sido escrita y verificada en host, de modo que el
        # rollback conoce exactamente qué debe restaurar.
        attempted: list[tuple[int, int, bytes, str]] = []
        try:
            with self.reader.client_factory() as client:
                process = self.reader._find_usum_process(client.process_list())
                client.set_process(process.process_id)
                party_base = self.reader._locate_party_base(client, process, current)
                original_capture, capture_attempt = self._capture_stable_party(client, party_base)
                live_party = self._read_party_members(original_capture, current)
                if not live_party:
                    raise USUMLiveError("La party viva quedó vacía antes del cambio Equipo↔PC.")

                occupied_slots = sorted(live_party)
                if occupied_slots != list(range(1, len(occupied_slots) + 1)):
                    raise USUMLiveError("La party viva contiene huecos internos inesperados; no se escribió ningún byte.")
                party_count = len(occupied_slots)
                if operation == "party-to-box" and party_count <= 1:
                    raise USUMLiveError("Pokémon UltraSol/UltraLuna necesita al menos un Pokémon en el equipo; no se escribió ningún byte.")
                if operation == "box-to-party" and party_count >= 6:
                    raise USUMLiveError("El equipo ya tiene seis Pokémon; no se escribió ningún byte.")

                session = (int(process.title_id), int(process.process_id), str(process.name), int(party_base))
                host_memory = self.host_memory_factory()
                cached = self._ensure_pc_live_cache_for_team_write(
                    client=client, process=process, party_base=int(party_base),
                    original_capture=original_capture, current=current, host_memory=host_memory,
                )
                host_pid = int(cached[1])
                host_pc_base = int(cached[2])
                guest_pc_base = int(cached[3])
                box_count = int(cached[4])
                box_slot_count = int(cached[5])

                matrix_raw, matrix_parsed = self._read_proven_pc_matrix(
                    client=client, host_memory=host_memory, host_pid=host_pid,
                    host_base=host_pc_base, guest_base=guest_pc_base,
                    box_count=box_count, box_slot_count=box_slot_count,
                )

                # ENVIAR AL PC significa «primer hueco libre REAL». La UI puede
                # haber calculado un destino desde un main/caché desfasado; para
                # UltraSol/UltraLuna la autoridad es la matriz live que acabamos de demostrar.
                if operation == "party-to-box":
                    destination = next((
                        (box_no, slot_no)
                        for box_no in range(1, box_count + 1)
                        for slot_no in range(1, box_slot_count + 1)
                        if matrix_parsed.get((box_no, slot_no)) is None
                    ), None)
                    if destination is None:
                        raise USUMLiveError("El PC vivo está lleno; no se escribió ningún byte.")
                    box, box_slot = destination
                else:
                    box = int(change.box)
                    box_slot = int(change.box_slot)

                slot_index = _pc_slot_index(box, box_slot, box_slot_count)
                pc_offset = slot_index * PK7_STORED_SIZE

                host_party = self._validated_pc_party_target(
                    client=client, process=process, party_base=party_base,
                    original_capture=original_capture, host_memory=host_memory,
                )
                if int(host_party.pid) != host_pid:
                    raise USUMLiveError(
                        "Party y BoxPokemon no pertenecen al mismo proceso host demostrado; no se escribió ningún byte."
                    )

                party_payloads = self._read_proven_party_injection_windows(
                    client=client, host_memory=host_memory, host_pid=host_pid,
                    host_party_base=int(host_party.host_party_base), guest_party_base=int(party_base),
                    expected_sparse=live_party,
                )
                if len(party_payloads) != 6:
                    raise USUMLiveError("La lectura demostrada de PartyData no devolvió los seis slots físicos.")

                # Alpha.50: los cambios de tamaño usan exclusivamente el PartyCount
                # runtime demostrado por alpha.49 en PARTY_BASE-0x74. No se deriva
                # ningún PokePartySave desde los offsets del archivo SAV.
                party_count_host_addr: int | None = None
                party_count_guest_addr: int | None = None
                party_count_original: bytes | None = None
                if operation in {"party-to-box", "box-to-party"}:
                    party_count_host_addr, party_count_guest_addr, party_count_original = (
                        self._resolve_live_party_count(
                            client=client, host_memory=host_memory, host_pid=host_pid,
                            host_party_base=int(host_party.host_party_base), guest_party_base=int(party_base),
                            expected_count=party_count,
                        )
                    )

                pc_original = bytes(matrix_raw[pc_offset:pc_offset + PK7_STORED_SIZE])
                pc_current = matrix_parsed.get((box, box_slot))
                host_pc_addr = host_pc_base + pc_offset
                guest_pc_addr = guest_pc_base + pc_offset
                host_party_base = int(host_party.host_party_base)
                guest_party_base = int(party_base)

                # Estado final esperado, expresado exclusivamente mediante bytes
                # ya demostrados o mediante PartyData construido a partir del PK7
                # real de caja con Personal de la ROM efectiva.
                expected_party_raw: dict[int, bytes] = {}
                expected_stats: dict[int, bytes] = {}
                expected_ids: dict[int, str] = {
                    slot: self._pokemon_identity(pokemon) for slot, pokemon in live_party.items()
                }
                expected_sparse_members: dict[int, SavePokemon] = dict(live_party)
                party_count_expected: int | None = None
                pc_expected: bytes
                pc_expected_identity: str | None
                incoming_prepared: SavePokemon | None = None
                target_party_slot: int | None = None
                outgoing_identity = ""

                if operation in {"swap-party-box", "box-to-party"}:
                    if pc_current is None:
                        raise USUMLiveError(f"La caja {box}, hueco {box_slot} está vacía. No se escribió ningún byte.")
                    incoming_identity = self._pokemon_identity(pc_current)
                    declared_incoming = str(change.incoming_identity or "")
                    if declared_incoming and incoming_identity != declared_incoming:
                        raise USUMLiveError(
                            f"{change.incoming_pokemon or 'El Pokémon elegido'} ya no está en la caja {box}:{box_slot}. "
                            "Pulsa F5 y vuelve a intentarlo."
                        )
                else:
                    incoming_identity = ""
                    # La ocupación del PC se decide por el MISMO parser PK7 que
                    # alimenta CAJAS PC. Un hueco vacío puede contener bytes
                    # cifrados no-cero (species=0 con sanity/checksum válidos),
                    # así que ``any(pc_original)`` NO demuestra que haya un
                    # Pokémon. La matriz completa acaba de quedar estable y
                    # host==guest; si su parser devuelve None, el hueco es vacío.
                    if pc_current is not None:
                        raise USUMLiveError(
                            f"La caja {box}, hueco {box_slot} ya no está vacía. Pulsa F5 y vuelve a intentarlo."
                        )

                if operation == "swap-party-box":
                    target_party_slot = self._resolve_team_swap_party_target(change, live_party)
                    outgoing = live_party.get(target_party_slot)
                    if outgoing is None:
                        raise USUMLiveError("El slot de party elegido para salir ya está vacío.")
                    outgoing_identity = self._pokemon_identity(outgoing)
                    declared_outgoing = str(change.outgoing_identity or "")
                    if declared_outgoing and outgoing_identity != declared_outgoing:
                        raise USUMLiveError("El Pokémon saliente cambió antes del swap; no se escribió ningún byte.")

                    # Sustitución directa: el rol pertenece a la casilla lógica.
                    result_role = canonical_role(outgoing.role)
                    if result_role not in ROLE_ORDER:
                        raise USUMLiveError("El Pokémon saliente no tiene un único rol válido. Pulsa F5 antes de sustituirlo.")
                    incoming_raw, incoming_prepared = self._party_payload_from_box(
                        pc_original, role=result_role, remove_move_slots=change.remove_move_slots,
                    )
                    if self._pokemon_identity(incoming_prepared) != incoming_identity:
                        raise USUMLiveError("El PK7 preparado para entrar perdió su identidad fuerte.")
                    if canonical_role(incoming_prepared.role) != result_role:
                        raise USUMLiveError("El PK7 entrante no conservó el rol heredado preparado.")

                    expected_party_raw[target_party_slot] = bytes(incoming_raw)
                    expected_stats[target_party_slot] = bytes(
                        incoming_raw[PK7_STORED_SIZE:PK7_STORED_SIZE + USUM_PARTY_STATS_SIZE]
                    )
                    expected_ids[target_party_slot] = incoming_identity
                    expected_sparse_members[target_party_slot] = incoming_prepared
                    pc_expected = bytes(party_payloads[target_party_slot - 1][:PK7_STORED_SIZE])
                    pc_expected_identity = outgoing_identity

                elif operation == "box-to-party":
                    # Una entrada sin sustitución ocupa únicamente el primer slot
                    # físico libre de la party compacta y recibe el primer rol libre.
                    target_party_slot = party_count + 1
                    if int(change.party_slot or target_party_slot) != target_party_slot:
                        raise USUMLiveError(
                            "La party cambió antes de incorporar el Pokémon del PC. Pulsa F5 y vuelve a intentarlo."
                        )
                    if target_party_slot in live_party:
                        raise USUMLiveError("El primer slot libre de party dejó de estar vacío; no se escribió ningún byte.")
                    # La ausencia de target_party_slot en live_party ya ha sido
                    # demostrada por el parser PK7 estable. No usamos ``any(raw)``:
                    # un slot vacío cifrado puede contener bytes no-cero.
                    current_target = bytes(party_payloads[target_party_slot - 1])
                    current_sparse = bytes(original_capture[target_party_slot - 1])

                    result_role = self._first_free_role(live_party)
                    if result_role not in ROLE_ORDER:
                        raise USUMLiveError("No existe ningún rol libre para el Pokémon que entra; no se escribió ningún byte.")
                    incoming_raw, incoming_prepared = self._party_payload_from_box(
                        pc_original, role=result_role, remove_move_slots=change.remove_move_slots,
                    )
                    if self._pokemon_identity(incoming_prepared) != incoming_identity:
                        raise USUMLiveError("El PK7 preparado para entrar perdió su identidad fuerte.")
                    if canonical_role(incoming_prepared.role) != result_role:
                        raise USUMLiveError("El PK7 entrante no recibió el primer rol libre preparado.")

                    expected_party_raw[target_party_slot] = bytes(incoming_raw)
                    expected_stats[target_party_slot] = bytes(
                        incoming_raw[PK7_STORED_SIZE:PK7_STORED_SIZE + USUM_PARTY_STATS_SIZE]
                    )
                    expected_ids[target_party_slot] = incoming_identity
                    expected_sparse_members[target_party_slot] = incoming_prepared
                    # Un hueco PK7 real no es un bloque a cero: Gen6/7 usa
                    # la representación cifrada de un PK7 vacío (species=0).
                    pc_expected = encrypt_pk6_stored(bytes(PK7_STORED_SIZE))
                    pc_expected_identity = None
                    if party_count_original is None:
                        raise USUMLiveError("PartyCount live no quedó demostrado antes de ampliar el equipo.")
                    party_count_expected = party_count + 1

                else:  # party-to-box
                    target_party_slot = self._resolve_team_swap_party_target(change, live_party)
                    outgoing = live_party.get(target_party_slot)
                    if outgoing is None:
                        raise USUMLiveError("El slot de party elegido para enviar al PC ya está vacío.")
                    outgoing_identity = self._pokemon_identity(outgoing)
                    declared_outgoing = str(change.outgoing_identity or "")
                    if declared_outgoing and outgoing_identity != declared_outgoing:
                        raise USUMLiveError("El Pokémon saliente cambió antes de enviarlo al PC; no se escribió ningún byte.")

                    # El PC recibe exactamente el PK7 stored live del saliente,
                    # incluido su marcador/último rol utilizado.
                    pc_expected = bytes(party_payloads[target_party_slot - 1][:PK7_STORED_SIZE])
                    pc_expected_identity = outgoing_identity

                    # Compactación: cada miembro posterior reutiliza literalmente
                    # su PartyData y su mirror ya demostrados. No se recalculan stats,
                    # moves, estado ni bytes opacos de esos Pokémon.
                    new_sparse: dict[int, SavePokemon] = {}
                    new_ids: dict[int, str] = {}
                    for slot in range(1, target_party_slot):
                        new_sparse[slot] = live_party[slot]
                        new_ids[slot] = self._pokemon_identity(live_party[slot])
                    for dest_slot in range(target_party_slot, party_count):
                        source_slot = dest_slot + 1
                        source_mon = live_party[source_slot]
                        expected_party_raw[dest_slot] = bytes(party_payloads[source_slot - 1])
                        expected_stats[dest_slot] = bytes(
                            original_capture[source_slot - 1][PK7_STORED_SIZE:PK7_STORED_SIZE + USUM_PARTY_STATS_SIZE]
                        )
                        new_sparse[dest_slot] = source_mon
                        new_ids[dest_slot] = self._pokemon_identity(source_mon)

                    # El último slot ocupado debe quedar vacío con un PK7
                    # cifrado válido (species=0). Es la representación real Gen7;
                    # un bloque 0x104 a cero fue la causa del Huevo fantasma de
                    # alpha.43 al reducir 6→5.
                    blank_party = encrypt_pk6(bytes(PK7_PARTY_SIZE))
                    blank_stats = bytes(
                        blank_party[PK7_STORED_SIZE:PK7_STORED_SIZE + USUM_PARTY_STATS_SIZE]
                    )
                    expected_party_raw[party_count] = blank_party
                    expected_stats[party_count] = blank_stats
                    expected_ids = new_ids
                    expected_sparse_members = new_sparse

                    if party_count_original is None:
                        raise USUMLiveError("PartyCount live no quedó demostrado antes de reducir el equipo.")
                    party_count_expected = party_count - 1

                # Direcciones/originales de todas las regiones que se van a tocar.
                party_original_raw: dict[int, bytes] = {}
                party_original_stats: dict[int, bytes] = {}
                for slot in sorted(expected_party_raw):
                    party_original_raw[slot] = bytes(party_payloads[slot - 1])
                    party_original_stats[slot] = bytes(
                        original_capture[slot - 1][PK7_STORED_SIZE:PK7_STORED_SIZE + USUM_PARTY_STATS_SIZE]
                    )

                if party_count_expected is not None:
                    if party_count_original is None or party_count_host_addr is None or party_count_guest_addr is None:
                        raise USUMLiveError("La transacción perdió la prueba de PartyCount antes del preflight.")
                    if int(party_count_original[0]) != party_count:
                        raise USUMLiveError("PartyCount dejó de coincidir con la party antes del preflight.")

                host_handle = host_memory.open_process(host_pid)
                # Preflight COMPLETO de todas las regiones antes de tocar un byte.
                for slot in sorted(expected_party_raw):
                    host_addr = host_party_base + (slot - 1) * USUM_PARTY_STRIDE
                    guest_addr = guest_party_base + (slot - 1) * USUM_PARTY_STRIDE
                    host_stats_addr = host_addr + USUM_PARTY_STATS_OFFSET
                    guest_stats_addr = guest_addr + USUM_PARTY_STATS_OFFSET
                    original_raw = party_original_raw[slot]
                    original_stats = party_original_stats[slot]
                    if bytes(host_memory.read(host_handle, host_addr, PK7_PARTY_SIZE)) != original_raw:
                        raise USUMLiveError(f"Party host cambió antes de escribir el slot {slot}; no se tocó ningún byte.")
                    if bytes(client.read_memory(guest_addr, PK7_PARTY_SIZE)) != original_raw:
                        raise USUMLiveError(f"Party guest cambió antes de escribir el slot {slot}; no se tocó ningún byte.")
                    if bytes(host_memory.read(host_handle, host_stats_addr, USUM_PARTY_STATS_SIZE)) != original_stats:
                        raise USUMLiveError(f"El mirror host de stats cambió antes de escribir el slot {slot}; no se tocó ningún byte.")
                    if bytes(client.read_memory(guest_stats_addr, USUM_PARTY_STATS_SIZE)) != original_stats:
                        raise USUMLiveError(f"El mirror guest de stats cambió antes de escribir el slot {slot}; no se tocó ningún byte.")
                if bytes(host_memory.read(host_handle, host_pc_addr, PK7_STORED_SIZE)) != pc_original:
                    raise USUMLiveError("BoxPokemon host cambió antes de escribir; no se tocó ningún byte.")
                if bytes(client.read_memory(guest_pc_addr, PK7_STORED_SIZE)) != pc_original:
                    raise USUMLiveError("BoxPokemon guest cambió antes de escribir; no se tocó ningún byte.")

                if party_count_expected is not None:
                    assert party_count_host_addr is not None and party_count_guest_addr is not None and party_count_original is not None
                    if bytes(host_memory.read(host_handle, party_count_host_addr, 1)) != party_count_original:
                        raise USUMLiveError("PartyCount host cambió antes de escribir.")
                    if bytes(client.read_memory(party_count_guest_addr, 1)) != party_count_original:
                        raise USUMLiveError("PartyCount guest cambió antes de escribir.")

                try:
                    # Primero BoxPokemon y después todas las representaciones de
                    # party. La UI permanece en el último estado confirmado hasta
                    # que la verificación tardía complete la transacción.
                    host_memory.write(host_handle, host_pc_addr, pc_expected)
                    attempted.append((int(host_pc_addr), int(guest_pc_addr), pc_original, "PC"))
                    if bytes(host_memory.read(host_handle, host_pc_addr, PK7_STORED_SIZE)) != pc_expected:
                        raise USUMLiveError("WriteProcessMemory no confirmó el slot PC.")

                    for slot in sorted(expected_party_raw):
                        host_addr = host_party_base + (slot - 1) * USUM_PARTY_STRIDE
                        guest_addr = guest_party_base + (slot - 1) * USUM_PARTY_STRIDE
                        expected_raw = expected_party_raw[slot]
                        original_raw = party_original_raw[slot]
                        host_memory.write(host_handle, host_addr, expected_raw)
                        attempted.append((int(host_addr), int(guest_addr), original_raw, f"party slot {slot} 0x104"))
                        if bytes(host_memory.read(host_handle, host_addr, PK7_PARTY_SIZE)) != expected_raw:
                            raise USUMLiveError(f"WriteProcessMemory no confirmó PartyData del slot {slot}.")

                    for slot in sorted(expected_stats):
                        host_addr = host_party_base + (slot - 1) * USUM_PARTY_STRIDE + USUM_PARTY_STATS_OFFSET
                        guest_addr = guest_party_base + (slot - 1) * USUM_PARTY_STRIDE + USUM_PARTY_STATS_OFFSET
                        expected = expected_stats[slot]
                        original = party_original_stats[slot]
                        host_memory.write(host_handle, host_addr, expected)
                        attempted.append((int(host_addr), int(guest_addr), original, f"party slot {slot} stats mirror"))
                        if bytes(host_memory.read(host_handle, host_addr, USUM_PARTY_STATS_SIZE)) != expected:
                            raise USUMLiveError(f"WriteProcessMemory no confirmó el mirror runtime del slot {slot}.")

                    # PartyCount se escribe al final, cuando los slots sparse ya
                    # representan el nuevo tamaño lógico. Es el byte runtime
                    # demostrado en alpha.49, no una copia inferida desde el SAV.
                    if party_count_expected is not None:
                        assert party_count_host_addr is not None and party_count_guest_addr is not None and party_count_original is not None
                        count_expected = bytes((int(party_count_expected),))
                        host_memory.write(host_handle, party_count_host_addr, count_expected)
                        attempted.append((int(party_count_host_addr), int(party_count_guest_addr), party_count_original, "PartyCount"))
                        if bytes(host_memory.read(host_handle, party_count_host_addr, 1)) != count_expected:
                            raise USUMLiveError("WriteProcessMemory no confirmó PartyCount.")

                    def verify_game_consumed_state() -> tuple[tuple[bytes, ...], dict[int, SavePokemon]]:
                        # 1) Ventanas 0x104 completas estables host↔guest y con las
                        # identidades finales exactas.
                        direct_raw = self._read_proven_party_injection_windows(
                            client=client, host_memory=host_memory, host_pid=host_pid,
                            host_party_base=host_party_base, guest_party_base=guest_party_base,
                            expected_sparse=expected_sparse_members,
                        )
                        for slot, expected in expected_party_raw.items():
                            if bytes(direct_raw[slot - 1]) != bytes(expected):
                                raise USUMLiveError(f"PartyData 0x104 del slot {slot} no confirmó el estado final.")

                        if party_count_expected is not None:
                            assert party_count_guest_addr is not None
                            if bytes(client.read_memory(party_count_guest_addr, 1)) != bytes((int(party_count_expected),)):
                                raise USUMLiveError("PartyCount no confirmó el nuevo tamaño del equipo.")

                        # 2) Reader sparse histórico independiente: composición,
                        # compactación y stored+stats deben converger exactamente.
                        sparse_capture, _ = self._capture_stable_party(client, guest_party_base)
                        sparse_party = self._read_party_members(sparse_capture, current)
                        actual_sparse_ids = {
                            slot: self._pokemon_identity(pokemon) for slot, pokemon in sparse_party.items()
                        }
                        if actual_sparse_ids != expected_ids:
                            raise USUMLiveError("El reader live normal no confirmó la nueva composición del equipo.")
                        for slot in sorted(expected_party_raw):
                            sparse_actual = bytes(sparse_capture[slot - 1])
                            expected_sparse_raw = (
                                bytes(expected_party_raw[slot][:PK7_STORED_SIZE])
                                + bytes(expected_stats[slot])
                                + (b"\0" * USUM_PARTY_TAIL_PADDING)
                            )
                            if sparse_actual != expected_sparse_raw:
                                raise USUMLiveError(
                                    f"El slot runtime sparse {slot} no convergió al stored+stats esperado."
                                )

                        # 3) BoxPokemon debe reflejar exactamente el otro lado del
                        # traslado: saliente en PC o hueco vacío.
                        _matrix, parsed_pc = self._read_proven_pc_matrix(
                            client=client, host_memory=host_memory, host_pid=host_pid,
                            host_base=host_pc_base, guest_base=guest_pc_base,
                            box_count=box_count, box_slot_count=box_slot_count,
                        )
                        boxed = parsed_pc.get((box, box_slot))
                        if pc_expected_identity is None:
                            if boxed is not None:
                                raise USUMLiveError("BoxPokemon no confirmó que el hueco del PC quedara vacío.")
                            if bytes(client.read_memory(guest_pc_addr, PK7_STORED_SIZE)) != pc_expected:
                                raise USUMLiveError("BoxPokemon no confirmó el PK7 vacío cifrado esperado.")
                        else:
                            if boxed is None or self._pokemon_identity(boxed) != pc_expected_identity:
                                raise USUMLiveError("BoxPokemon no confirmó la identidad esperada tras el traslado.")
                            if bytes(client.read_memory(guest_pc_addr, PK7_STORED_SIZE)) != pc_expected:
                                raise USUMLiveError("BoxPokemon guest no confirmó los 0xE8 bytes exactos esperados.")
                        return sparse_capture, sparse_party

                    time.sleep(max(0.12, float(getattr(self.reader, "stable_delay", 0.06)) * 2.0))
                    verify_game_consumed_state()
                    time.sleep(max(0.45, float(getattr(self.reader, "stable_delay", 0.06)) * 5.0))
                    verified_sparse, _verified_party = verify_game_consumed_state()

                    game = self.reader._build_game(
                        verified_sparse, current, process, party_base, live_write=True,
                    )
                    # Alpha.39: ENVIAR AL PC deja que el writer escoja el primer
                    # hueco libre de la matriz *live*. Esa posición real debe
                    # volver a la capa UI una vez verificada la transacción; de
                    # lo contrario el selector + solo conoce el main antiguo
                    # hasta que CAJAS PC fuerza otra reconciliación. No cambia
                    # ningún byte ni la elección del destino: únicamente publica
                    # la posición que ya acaba de quedar confirmada host↔guest.
                    if operation == "party-to-box":
                        change.box = int(box)
                        change.box_slot = int(box_slot)
                    self._pc_party_anchor = (
                        session,
                        HostPartyTarget(host_pid, str(host_party.exe_name), host_party_base),
                    )
                    return USUMLiveWriteResult(
                        game=game, process=process, attempts=int(capture_attempt),
                        applied_count=1, already_applied=False,
                    )
                except Exception as exc:
                    rollback_errors: list[str] = []
                    for host_addr, guest_addr, original, label in reversed(attempted):
                        try:
                            host_memory.write(host_handle, host_addr, original)
                            if bytes(host_memory.read(host_handle, host_addr, len(original))) != original:
                                rollback_errors.append(f"{label}: host no confirmó rollback")
                        except Exception as rollback_exc:
                            rollback_errors.append(f"{label}: {rollback_exc}")

                    if attempted and not rollback_errors:
                        try:
                            time.sleep(max(0.03, float(getattr(self.reader, "stable_delay", 0.06))))
                            for _host_addr, guest_addr, original, label in attempted:
                                if bytes(client.read_memory(guest_addr, len(original))) != original:
                                    rollback_errors.append(f"{label}: guest no confirmó rollback")
                        except Exception as rollback_exc:
                            rollback_errors.append(f"guest rollback: {rollback_exc}")
                    if rollback_errors:
                        raise USUMLiveError(
                            f"El traslado Equipo↔PC falló: {exc}. No se pudo confirmar toda la restauración: "
                            + "; ".join(rollback_errors)
                        ) from exc
                    if attempted:
                        raise USUMLiveError(
                            f"El traslado Equipo↔PC falló: {exc}. RoleRun restauró y verificó party + PC originales."
                        ) from exc
                    raise
        except AzaharRPCError as exc:
            raise USUMLiveError(str(exc)) from exc
        finally:
            if host_memory is not None and host_handle is not None:
                try:
                    host_memory.close_process(host_handle)
                except Exception:
                    pass

    def apply(self, current: SaveGameData, changes: Sequence[object]) -> USUMLiveWriteResult:
        if not changes:
            raise USUMLiveError("No hay cambios que aplicar en UltraSol/UltraLuna.")
        if all(isinstance(change, PendingInventoryChange) for change in changes):
            return self._apply_inventory(current, list(changes))
        team_changes = [change for change in changes if isinstance(change, PendingTeamChange)]
        if team_changes:
            if len(team_changes) != 1 or len(changes) != 1:
                raise USUMLiveError(
                    "Los cambios Equipo↔PC de UltraSol/UltraLuna se aplican como una transacción aislada. "
                    "Espera a que termine la acción anterior y vuelve a intentarlo."
                )
            if str(team_changes[0].operation) == "replace-fainted":
                return self._apply_faint_replacement(current, team_changes[0])
            return self._apply_team_swap(current, team_changes[0])
        if any(isinstance(change, PendingInventoryChange) for change in changes):
            raise USUMLiveError(
                "Por seguridad, las utilidades de inventario de UltraSol/UltraLuna se aplican en una transacción separada de roles/movimientos. "
                "Espera a que termine el cambio anterior y vuelve a intentarlo."
            )
        if any(not isinstance(change, (PendingRoleChange, PendingChange, PendingTMTeach)) for change in changes):
            raise USUMLiveError(
                f"{APP_VERSION} permite roles, movimientos, MT, utilidades, traslados Equipo↔PC y sustituciones por baja. "
                "Los cambios directos de rol de un Pokémon que permanece en el PC siguen bloqueados; no se escribió ningún byte."
            )
        supported = list(changes)

        try:
            with self.reader.client_factory() as client:
                process = self.reader._find_usum_process(client.process_list())
                client.set_process(process.process_id)
                party_base = self.reader._locate_party_base(client, process, current)
                original_capture, capture_attempt = self._capture_stable_party(client, party_base)
                live_party = self._read_party_members(original_capture, current)
                if not live_party:
                    raise USUMLiveError("La captura estable de UltraSol/UltraLuna no contiene Pokémon en el equipo.")

                targets = {id(change): self._resolve_target(change, live_party) for change in supported}
                original_slots: dict[int, bytes] = {}
                plain_slots: dict[int, bytearray] = {}
                was_encrypted: dict[int, bool] = {}
                for slot in sorted(set(targets.values())):
                    original = original_capture[slot - 1]
                    plain, encrypted = _plain_pk7_with_state(original)
                    original_slots[slot] = original
                    plain_slots[slot] = bytearray(plain)
                    was_encrypted[slot] = encrypted

                # Se respeta el orden de la cola para que varios cambios sobre el
                # mismo Pokémon se validen contra el estado proyectado anterior.
                for change in supported:
                    slot = targets[id(change)]
                    if isinstance(change, PendingRoleChange):
                        actual = self._role_from_plain(plain_slots[slot])
                        expected = canonical_role(str(change.old_role or "SIN ROL"))
                        if actual != expected:
                            raise USUMLiveError(
                                f"{change.pokemon or 'El Pokémon'} cambió de rol dentro del juego ({actual}). "
                                f"RoleRun esperaba {expected}; no se escribió ningún byte."
                            )
                        self._set_role(plain_slots[slot], change.new_role)
                    elif isinstance(change, (PendingChange, PendingTMTeach)):
                        if isinstance(change, PendingTMTeach):
                            self._assert_live_tm_available(client, process, party_base, change)
                        self._replace_move(plain_slots[slot], change)

                encoded_slots: dict[int, bytes] = {}
                expected_party: dict[int, SavePokemon] = {}
                any_byte_change = False
                for slot, plain in plain_slots.items():
                    self._refresh_checksum(plain)
                    encoded = encrypt_pk6(bytes(plain)) if was_encrypted[slot] else bytes(plain)
                    expected = parse_pk7_party(encoded, slot, self.reader.move_names)
                    if expected is None:
                        raise USUMLiveError(f"El slot {slot} quedó vacío al preparar los cambios; no se escribió nada.")
                    encoded_slots[slot] = encoded
                    expected_party[slot] = expected
                    if encoded[:PK7_STORED_SIZE] != original_slots[slot][:PK7_STORED_SIZE]:
                        any_byte_change = True

                if not any_byte_change:
                    game = self.reader._build_game(original_capture, current, process, party_base)
                    return USUMLiveWriteResult(
                        game=game, process=process, attempts=capture_attempt,
                        applied_count=len(supported), already_applied=True,
                    )

                attempted_slots: list[int] = []
                immediate_readbacks: dict[int, dict[str, object]] = {}
                write_addresses: dict[int, int] = {}
                write_modes: dict[int, str] = {}
                host_memory = None
                host_handle = None
                host_target = None
                try:
                    # Preflight COMPLETO antes de tocar RAM. Si Azahar RPC no puede
                    # escribir la NEW_LINEAR_HEAP y tampoco existe alias virtual
                    # válido, alpha.12 calibra el backing FCRAM del proceso Windows
                    # por contenido exacto de TODA la party (stored + stats + stride).
                    host_slots: list[int] = []
                    for slot in sorted(encoded_slots):
                        if encoded_slots[slot][:PK7_STORED_SIZE] == original_slots[slot][:PK7_STORED_SIZE]:
                            continue
                        canonical = int(party_base) + (slot - 1) * USUM_PARTY_STRIDE
                        resolved = self._resolve_write_address(
                            client, canonical, original_slots[slot][:PK7_STORED_SIZE]
                        )
                        if resolved is None:
                            host_slots.append(slot)
                        else:
                            write_address, write_mode = resolved
                            write_addresses[slot] = int(write_address)
                            write_modes[slot] = str(write_mode)

                    if host_slots:
                        try:
                            host_memory = self.host_memory_factory()
                            # Alpha.53: enseñar una MT no escribe la mochila, así
                            # que el transporte host del PK7 se resuelve igual que
                            # para cualquier otro cambio de movimiento. Si la party
                            # aparece una sola vez, esa copia basta; si Azahar conserva
                            # buffers idénticos, la relación party↔PC ya validada es
                            # la segunda ancla independiente.
                            matches = host_memory.find_party_targets(
                                slot_raws=original_capture,
                                stored_size=PK7_STORED_SIZE,
                                stats_offset=USUM_PARTY_STATS_OFFSET,
                                stats_size=USUM_PARTY_STATS_SIZE,
                                stride=USUM_PARTY_STRIDE,
                            )
                            if len(matches) == 1:
                                host_target = matches[0]
                            else:
                                try:
                                    host_target = self._validated_pc_party_target(
                                        client=client, process=process, party_base=party_base,
                                        original_capture=original_capture, host_memory=host_memory,
                                    )
                                except USUMLiveError as anchor_exc:
                                    if not matches:
                                        raise USUMLiveError(
                                            "Azahar RPC no puede escribir la NEW_LINEAR_HEAP y RoleRun no encontró en el proceso Windows "
                                            "una única copia viva de la party. La ancla PC tampoco pudo revalidarse; "
                                            "no se escribió ningún byte."
                                        ) from anchor_exc
                                    raise USUMLiveError(
                                        f"Azahar RPC no puede escribir la NEW_LINEAR_HEAP y se encontraron {len(matches)} copias host "
                                        "indistinguibles de la party. La relación party↔PC demostrada tampoco pudo revalidarse; "
                                        "por seguridad no se escribió ningún byte."
                                    ) from anchor_exc
                        except WindowsProcessMemoryError as exc:
                            raise USUMLiveError(str(exc)) from exc
                        try:
                            host_handle = host_memory.open_process(int(host_target.pid))
                        except WindowsProcessMemoryError as exc:
                            raise USUMLiveError(str(exc)) from exc
                        for slot in host_slots:
                            host_addr = int(host_target.host_party_base) + (slot - 1) * USUM_PARTY_STRIDE
                            expected_stored = bytes(original_slots[slot][:PK7_STORED_SIZE])
                            expected_stats = bytes(original_slots[slot][PK7_STORED_SIZE:PK7_STORED_SIZE + USUM_PARTY_STATS_SIZE])
                            try:
                                host_stored = bytes(host_memory.read(host_handle, host_addr, PK7_STORED_SIZE))
                                host_stats = bytes(host_memory.read(host_handle, host_addr + USUM_PARTY_STATS_OFFSET, USUM_PARTY_STATS_SIZE))
                            except WindowsProcessMemoryError as exc:
                                raise USUMLiveError(str(exc)) from exc
                            if host_stored != expected_stored or host_stats != expected_stats:
                                raise USUMLiveError(
                                    f"La copia host calibrada cambió antes de escribir el slot {slot}; no se escribió ningún byte."
                                )
                            write_addresses[slot] = host_addr
                            write_modes[slot] = "windows-host-fcram-content-validated"

                    for slot in sorted(write_addresses):
                        attempted_slots.append(slot)
                        canonical = int(party_base) + (slot - 1) * USUM_PARTY_STRIDE
                        write_address = int(write_addresses[slot])
                        expected_stored = bytes(encoded_slots[slot][:PK7_STORED_SIZE])
                        if write_modes[slot] == "windows-host-fcram-content-validated":
                            try:
                                host_memory.write(host_handle, write_address, expected_stored)
                                transport_readback = bytes(host_memory.read(host_handle, write_address, PK7_STORED_SIZE))
                            except WindowsProcessMemoryError as exc:
                                raise USUMLiveError(str(exc)) from exc
                            label = "immediate-after-write-via-windows-host-fcram"
                        else:
                            client.write_memory(write_address, expected_stored)
                            transport_readback = bytes(client.read_memory(write_address, PK7_STORED_SIZE))
                            label = "immediate-after-write-via-rpc"

                        immediate_readbacks[slot] = self._diagnostic_slot_snapshot(
                            client, address=canonical,
                            expected_stored=expected_stored,
                            original_stored=original_slots[slot][:PK7_STORED_SIZE],
                            label=label,
                        )
                        immediate_readbacks[slot]["write_address"] = f"0x{write_address:X}"
                        immediate_readbacks[slot]["write_mode"] = write_modes[slot]
                        if host_target is not None and write_modes[slot] == "windows-host-fcram-content-validated":
                            immediate_readbacks[slot]["windows_pid"] = int(host_target.pid)
                            immediate_readbacks[slot]["windows_exe"] = str(host_target.exe_name)
                        immediate_readbacks[slot]["write_address_stored_hex"] = transport_readback.hex()
                        immediate_readbacks[slot]["write_address_matches_expected"] = transport_readback == expected_stored
                        if not immediate_readbacks[slot]["stored_matches_expected"] or not immediate_readbacks[slot]["write_address_matches_expected"]:
                            raise USUMLiveError(
                                f"La escritura del slot {slot} llegó al transporte, pero la party viva de UltraSol/UltraLuna no la confirmó."
                            )

                    verified_capture, verified_attempt = self._capture_stable_party(client, party_base)
                    verified_party = self._read_party_members(verified_capture, current)
                    for slot, expected in expected_party.items():
                        actual = verified_party.get(slot)
                        if actual is None or self._pokemon_identity(actual) != self._pokemon_identity(expected):
                            raise USUMLiveError(f"Azahar devolvió un Pokémon distinto en el slot {slot} tras escribir el rol.")
                        if canonical_role(actual.role) != canonical_role(expected.role):
                            raise USUMLiveError(
                                f"Azahar no confirmó el rol del slot {slot}; se restaurará el PK7 original."
                            )
                        if [int(v or 0) for v in actual.move_ids[:4]] != [int(v or 0) for v in expected.move_ids[:4]]:
                            raise USUMLiveError(
                                f"Azahar no confirmó los movimientos del slot {slot}; se restaurará el PK7 original."
                            )

                    game = self.reader._build_game(verified_capture, current, process, party_base)
                    return USUMLiveWriteResult(
                        game=game, process=process, attempts=max(capture_attempt, verified_attempt),
                        applied_count=len(supported), already_applied=False,
                    )
                except Exception as exc:
                    diagnostic_path: Path | None = None
                    if attempted_slots:
                        _payload, diagnostic_path = self._collect_failure_diagnostic(
                            client, process=process, party_base=party_base,
                            attempted_slots=attempted_slots, originals=original_slots,
                            encoded_slots=encoded_slots, changes=supported,
                            immediate=immediate_readbacks, write_addresses=write_addresses,
                            write_modes=write_modes, error=exc,
                        )
                    rollback_errors = self._rollback(
                        client, party_base, attempted_slots, original_slots, write_addresses, write_modes,
                        host_memory=host_memory, host_handle=host_handle,
                    )
                    diagnostic_hint = (
                        f" Diagnóstico guardado en: {diagnostic_path}"
                        if diagnostic_path is not None else
                        " No se pudo guardar el diagnóstico automático."
                    )
                    if rollback_errors:
                        raise USUMLiveError(
                            f"La escritura PK7 de SM falló: {exc}. No se pudo confirmar toda la restauración: "
                            + "; ".join(rollback_errors) + diagnostic_hint
                        ) from exc
                    if attempted_slots:
                        raise USUMLiveError(
                            f"La escritura PK7 de SM falló: {exc}. RoleRun restauró los PK7 originales en RAM."
                            + diagnostic_hint
                        ) from exc
                    raise
                finally:
                    if host_memory is not None and host_handle is not None:
                        try:
                            host_memory.close_process(host_handle)
                        except Exception:
                            pass
        except AzaharRPCError as exc:
            raise USUMLiveError(str(exc)) from exc
