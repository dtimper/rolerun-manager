from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Callable, Sequence

from .bdsp_tm_service import BDSPTMProfile
from .models import (
    PendingChange,
    PendingInventoryChange,
    PendingPartyHeal,
    PendingRoleChange,
    PendingTMTeach,
    PendingTeamChange,
)
from .role_rules import ROLE_ORDER, ROLE_TO_MARKING, canonical_role, role_from_markings
from .ryujinx_host_memory import (
    RYUJINX_HOST_ADDRESS_SPACE_SIZE,
    RyujinxHostMappedClient,
    RyujinxHostMemoryError,
    RyujinxHostProfile,
)
from .ryujinx_host_write import RyujinxHostWriteTransport


BDSP_SP_130_TITLE_ID = 0x010018E011D92000
BDSP_SP_130_MAIN_BASE = 0x08504000
BDSP_SP_130_BOX_POINTER = (0x4E7BE98, 0xB8, 0x10, 0xA0, 0x20)
# PlayerWork.SaveData.saveItem. PKHeX-Plugins c8e23a43 fija esta cadena
# específica de SP 1.3.0 y convierte 3.000 SaveItem IL2CPP de 0xC bytes al
# bloque SAV8BS de 0x10 bytes por entrada. OpenDPR 5b0cb0c8 demuestra tanto
# los campos como ItemSaveSize=3000. La comparación física completa está en
# diagnostics/manual/bdsp_sp130_inventory_live_save_PROOF_20260822.json.
BDSP_SP_130_INVENTORY_POINTER = (0x4E7BE98, 0xB8, 0x10, 0x48, 0x20)
# PlayerWork._saveData.playerData.mystatus.gold. OpenDPR demuestra el orden
# exacto SaveData -> PLAYER_DATA -> MYSTATUS; la inspección FieldInfo/runtime
# acotada de SP 1.3.0 sitúa MYSTATUS en PlayerWork+0xE0 y gold en +0xEC.
# Nombre, ID32, dinero, edición y medallas coincidieron con el save físico.
# Véase diagnostics/manual/bdsp_alpha85_money_and_utility_layout_PROOF_20260822.json.
BDSP_SP_130_MYSTATUS_POINTER = (0x4E7BE98, 0xB8, 0x10, 0xE0)
BDSP_MYSTATUS_RUNTIME_SIZE = 0x38
BDSP_MYSTATUS_MONEY_OFFSET = 0x0C
BDSP_MAX_MONEY = 999_999
BDSP_UTILITY_ITEM_IDS = {
    "rare-candy": 50,
    "max-repel": 77,
}
# PKHeX 26.07.07 (fcfb5026), ItemStorage8BDSP.General. ItemInfo.count de
# OpenDPR 5b0cb0c8 asigna al primer alta el siguiente SortNumber del bolsillo;
# MyItem8b.SetItemQuantity confirma que es max(SortOrder)+1. La lista exacta
# evita mezclar los órdenes independientes de medicina, bolas, MT u otros
# bolsillos cuando la utilidad crea por primera vez un objeto general.
BDSP_GENERAL_ITEM_IDS = (
    45, 46, 47, 48, 49, 50, 51, 52, 53, 72, 73, 74, 75, 76, 77, 78, 79,
    80, 81, 82, 83, 84, 85, 93, 94, 107, 108, 109, 110, 111, 112, 135, 136,
    213, 214, 215, 217, 218, 219, 220, 221, 222, 223, 224, 225, 226, 227,
    228, 229, 230, 231, 232, 233, 234, 235, 236, 237, 238, 239, 240, 241,
    242, 243, 244, 245, 246, 247, 248, 249, 250, 251, 252, 253, 254, 255,
    256, 257, 258, 259, 260, 261, 262, 263, 264, 265, 266, 267, 268, 269,
    270, 271, 272, 273, 274, 275, 276, 277, 278, 279, 280, 281, 282, 283,
    284, 285, 286, 287, 288, 289, 290, 291, 292, 293, 294, 295, 296, 297,
    298, 299, 300, 301, 302, 303, 304, 305, 306, 307, 308, 309, 310, 311,
    312, 313, 314, 315, 316, 317, 318, 319, 320, 321, 322, 323, 324, 325,
    326, 327, 537, 565, 566, 567, 568, 569, 570, 644, 645, 849, 1231,
    1232, 1233, 1234, 1235, 1236, 1237, 1238, 1239, 1240, 1241, 1242,
    1243, 1244, 1245, 1246, 1247, 1248, 1249, 1250, 1251, 1606,
)
# PlayerWork.SaveData.systemFlags. OpenDPR 5b0cb0c8 demuestra que
# FlagWork.BadgeCount() suma exactamente los índices 124..131; PKHeX 26.07.07
# usa la misma representación en FlagWork8b. En SP 1.3.0 físico, el campo
# PlayerWork+0x30 resolvió un único bool[1000] estable y sus ocho valores
# coincidieron con el save y con MYSTATUS.badge. Véase el proof alpha.77.
# PlayerWork._saveData.playTime. Demostrado leyendo la partida viva con el
# personaje quieto en el mapa: el byte de 0x11B sube solo y da la vuelta en 59,
# y al hacerlo incrementa el de 0x11A. Es el unico campo conocido que avanza sin
# que el jugador haga nada, asi que sirve de latido: si deja de moverse, el juego
# se ha parado. Sin el, un congelado es indistinguible de estarse quieto.
BDSP_SP_130_PLAYTIME_POINTER = (0x4E7BE98, 0xB8, 0x10, 0x118)
BDSP_PLAYTIME_SIZE = 4

BDSP_SP_130_SYSTEM_FLAGS_POINTER = (0x4E7BE98, 0xB8, 0x10, 0x30, 0x20)
BDSP_SYSTEM_FLAG_COUNT = 1000
BDSP_BADGE_SYSTEM_FLAG_INDICES = tuple(range(124, 132))
# PlayerWork singleton -> nonserialized PlayerWork._playerParty. This is not
# SaveData.playerParty. The exact object graph and +0x808 field were proven
# read-only on SP 1.3.0; see the runtime-party proof under diagnostics/manual.
BDSP_SP_130_PARTY_POINTER = (0x4E7BE98, 0xB8, 0x10, 0x808, 0x0)
# BattleProc TypeInfo and the player-client party inside the client BattleEnv.
# The server lane at MainModule+0x108 and this client lane at +0x110 returned
# the same six HP. The client lane is used because it is the state presented to
# the local player. See bdsp_sp130_battle_to_party_convergence_AUTO_*.jsonl.
BDSP_SP_130_BATTLEPROC_TYPEINFO_OFFSET = 0x4E71D00
# BattleViewUISystem TypeInfo. La dirección y cada offset inferior se
# comprobaron contra los nombres/FieldInfo IL2CPP de SP 1.3.0 y mediante una
# lectura física de sus cuatro BUIStatusWindow. Desde alpha.69 gobierna solo la
# publicación temporal del KO BDSP ya demostrado.
BDSP_SP_130_BATTLE_UI_TYPEINFO_OFFSET = 0x4E70E40
BDSP_SP_130_BATTLE_PARTY_POINTER = (
    BDSP_SP_130_BATTLEPROC_TYPEINFO_OFFSET,
    0x58,  # BattleProc TypeInfo -> SingletonMonoBehaviour<BattleProc> parent
    0xB8,  # parent -> static fields
    0x0,   # static fields -> _instance
    0x20,  # BattleProc -> MainModule
    0x110, # MainModule -> client BattleEnv
    0x10,  # BattleEnv -> POKECON
    0x18,  # POKECON -> BTL_PARTY[5]
    0x20,  # client 0 element
    0x0,   # -> BTL_PARTY
)
BDSP_BOX_COUNT = 40
BDSP_BOX_SLOT_COUNT = 30
PB8_STORED_SIZE = 0x148
PB8_PARTY_SIZE = 0x158
BDSP_MAX_SPECIES_ID = 493
BDSP_MAX_MOVE_ID = 826
BDSP_INVENTORY_ITEM_COUNT = 3000
BDSP_INVENTORY_RECORD_SIZE = 0xC
BDSP_INVENTORY_BLOCK_SIZE = BDSP_INVENTORY_ITEM_COUNT * BDSP_INVENTORY_RECORD_SIZE

# Evidencia física, Perla Reluciente 1.3.0, Ryujinx 1.3.3 HostMappedUnsafe:
# - GDB y ReadProcessMemory devolvieron la misma huella y el mismo PB8;
# - tras reiniciar con GDB apagado apareció una sola coincidencia y la cadena
#   produjo 40×30 PB8, 11 ocupados, todos con checksum correcto.
# Véase diagnostics/manual/bdsp_sp130_hostmapped_bridge_proof_20260822.json y
# diagnostics/manual/bdsp_sp130_hostmapped_no_gdb_PROOF_20260822.json.
_BDSP_SP_130_MAIN_WITNESS = bytes.fromhex(
    "00000000080000004d4f44302806b704f82fc504481f060508a3ea0354060504"
    "c030c504000000000000000000000000ff4302d1f44f07a9fd7b08a9fd030291"
)

BDSP_SP_130_HOST_PROFILE = RyujinxHostProfile(
    key="bdsp-sp-1.3.0",
    game_name="Pokemon Shining Pearl",
    revision="1.3.0",
    title_id=BDSP_SP_130_TITLE_ID,
    guest_main=BDSP_SP_130_MAIN_BASE,
    main_witness=_BDSP_SP_130_MAIN_WITNESS,
)


class BDSPLiveError(RuntimeError):
    pass


def read_bdsp_play_time(client) -> tuple[int, int, int] | None:
    """Horas, minutos y segundos del reloj del juego, o ``None`` si no se pudo.

    Nunca propaga: es una señal de diagnóstico y no puede tumbar una captura
    real. Un ``None`` en la traza significa «no se pudo leer», que ya es
    información.
    """
    try:
        direccion = client.resolve_main_pointer(BDSP_SP_130_PLAYTIME_POINTER)
        crudo = client.read_memory(int(direccion), BDSP_PLAYTIME_SIZE)
    except Exception:
        return None
    horas = int(struct.unpack_from("<H", crudo, 0)[0])
    return (horas, int(crudo[2]), int(crudo[3]))


@dataclass(frozen=True, slots=True)
class BDSPBoxPokemon:
    box: int
    slot: int
    species_id: int
    pid: int
    tid: int
    sid: int
    form: int
    nickname: str
    held_item_id: int
    ability_id: int
    move_ids: tuple[int, int, int, int]
    move_pp: tuple[int, int, int, int]
    move_pp_ups: tuple[int, int, int, int]
    is_egg: bool
    markings: tuple[bool, bool, bool, bool, bool, bool]
    checksum: int
    encrypted: bytes = field(repr=False)
    data_pointer: int = field(default=0, repr=False)
    nature_id: int = 0
    stat_nature_id: int = 0
    experience: int = 0
    ivs: tuple[int, int, int, int, int, int] = (0, 0, 0, 0, 0, 0)
    evs: tuple[int, int, int, int, int, int] = (0, 0, 0, 0, 0, 0)


@dataclass(frozen=True, slots=True)
class BDSPBoxStorageSlot:
    box: int
    slot: int
    data_pointer: int
    encrypted: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class BDSPBoxRead:
    pokemon: tuple[BDSPBoxPokemon, ...]
    total_slots: int
    empty_slots: int
    pointer_base: int
    storage_slots: tuple[BDSPBoxStorageSlot, ...] = ()


@dataclass(frozen=True, slots=True)
class BDSPInventoryItem:
    item_id: int
    count: int
    vanish_new: bool
    favorite: bool
    show_move_name: bool
    sort_order: int


@dataclass(frozen=True, slots=True)
class BDSPInventoryRead:
    items: tuple[BDSPInventoryItem, ...]
    total_records: int
    array_object: int
    data_pointer: int
    raw: bytes = field(default=b"", repr=False)


@dataclass(frozen=True, slots=True)
class BDSPMoneyRead:
    trainer_name: str
    trainer_id: int
    money: int
    badge_count: int
    rom_code: int
    data_pointer: int
    raw: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class BDSPBadgeRead:
    count: int
    values: tuple[bool, bool, bool, bool, bool, bool, bool, bool]
    array_object: int
    data_pointer: int


@dataclass(frozen=True, slots=True)
class BDSPPartyPokemon:
    slot: int
    species_id: int
    pid: int
    tid: int
    sid: int
    form: int
    nickname: str
    held_item_id: int
    ability_id: int
    move_ids: tuple[int, int, int, int]
    move_pp: tuple[int, int, int, int]
    move_pp_ups: tuple[int, int, int, int]
    is_egg: bool
    markings: tuple[bool, bool, bool, bool, bool, bool]
    current_hp: int
    max_hp: int
    level: int
    checksum: int
    encrypted: bytes = field(repr=False)
    pokemon_param_pointer: int = field(default=0, repr=False)
    core_data_pointer: int = field(default=0, repr=False)
    calc_data_pointer: int = field(default=0, repr=False)
    nature_id: int = 0
    stat_nature_id: int = 0
    ivs: tuple[int, int, int, int, int, int] = (0, 0, 0, 0, 0, 0)
    evs: tuple[int, int, int, int, int, int] = (0, 0, 0, 0, 0, 0)
    stats: tuple[int, int, int, int, int, int] = (0, 0, 0, 0, 0, 0)
    status_condition: int = 0


@dataclass(frozen=True, slots=True)
class BDSPPartyStorageSlot:
    slot: int
    pokemon_param_pointer: int
    core_data_pointer: int
    calc_data_pointer: int
    encrypted: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class BDSPPartyRead:
    pokemon: tuple[BDSPPartyPokemon, ...]
    member_count: int
    party_object: int
    member_array: int
    member_count_address: int = 0
    storage_slots: tuple[BDSPPartyStorageSlot, ...] = ()


@dataclass(frozen=True, slots=True)
class BDSPBattlePokemon:
    row: int
    party_index: int
    species_id: int
    current_hp: int
    max_hp: int
    level: int


@dataclass(frozen=True, slots=True)
class BDSPBattleRead:
    pokemon: tuple[BDSPBattlePokemon, ...]
    member_count: int
    battle_party_object: int
    member_array: int


@dataclass(frozen=True, slots=True)
class BDSPBattlePresentationWindow:
    window_index: int
    displayed: bool
    current_hp: int
    max_hp: int
    level: int
    poke_id: int
    is_player: bool
    needs_hp_apply: bool
    hp_animation: bool
    initialized: bool
    setup: bool


@dataclass(frozen=True, slots=True)
class BDSPBattlePresentationRead:
    windows: tuple[BDSPBattlePresentationWindow, ...]
    ui_instance: int
    status_array: int


@dataclass(frozen=True, slots=True)
class BDSPWriteMemoryWatch:
    address: int
    expected: bytes


@dataclass(frozen=True, slots=True)
class BDSPWriteReceipt:
    party: BDSPPartyRead
    inventory: BDSPInventoryRead
    process: object
    attempts: int
    applied_count: int
    memory_watches: tuple[BDSPWriteMemoryWatch, ...] = ()
    already_applied: bool = False
    money: BDSPMoneyRead | None = None


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


def _crypt_words(data: bytearray, start: int, end: int, seed: int) -> None:
    for offset in range(start, end, 2):
        seed = (0x41C64E6D * seed + 0x6073) & 0xFFFFFFFF
        value = struct.unpack_from("<H", data, offset)[0] ^ (seed >> 16)
        struct.pack_into("<H", data, offset, value)


def decrypt_pb8(raw: bytes) -> bytes:
    """Descifra un PB8 party de 0x158 bytes sin modificar el origen."""

    if len(raw) != PB8_PARTY_SIZE:
        raise BDSPLiveError(f"Un PB8 debe medir {PB8_PARTY_SIZE} bytes.")
    data = bytearray(raw)
    encryption_constant = struct.unpack_from("<I", data, 0)[0]
    _crypt_words(data, 8, PB8_STORED_SIZE, encryption_constant)
    _crypt_words(data, PB8_STORED_SIZE, PB8_PARTY_SIZE, encryption_constant)
    block_size = (PB8_STORED_SIZE - 8) // 4
    desired = _BLOCK_POSITIONS[(encryption_constant >> 13) & 31]
    blocks = [
        bytes(data[8 + index * block_size:8 + (index + 1) * block_size])
        for index in range(4)
    ]
    layout = [0, 1, 2, 3]
    for index in range(3):
        other = layout.index(desired[index])
        if other == index:
            continue
        blocks[index], blocks[other] = blocks[other], blocks[index]
        layout[index], layout[other] = layout[other], layout[index]
    data[8:PB8_STORED_SIZE] = b"".join(blocks)
    return bytes(data)


_BLOCK_POSITION_INVERT = (
    0, 1, 2, 4, 3, 5, 6, 7, 12, 18, 13, 19,
    8, 10, 14, 20, 16, 22, 9, 11, 15, 21, 17, 23,
    0, 1, 2, 4, 3, 5, 6, 7,
)


def encrypt_pb8(plain: bytes) -> bytes:
    """Serializa el PB8 descifrado con el cifrado y shuffle propios de BDSP.

    El llamador debe haber actualizado primero el checksum almacenado. Separar
    ambas operaciones permite comprobar el diff semántico antes de cifrarlo.
    """

    if len(plain) != PB8_PARTY_SIZE:
        raise BDSPLiveError(f"Un PB8 debe medir {PB8_PARTY_SIZE} bytes.")
    data = bytearray(plain)
    encryption_constant = int(struct.unpack_from("<I", data, 0)[0])
    block_size = (PB8_STORED_SIZE - 8) // 4
    shuffle_value = _BLOCK_POSITION_INVERT[(encryption_constant >> 13) & 31]
    desired = _BLOCK_POSITIONS[shuffle_value & 31]
    blocks = [
        bytes(data[8 + index * block_size:8 + (index + 1) * block_size])
        for index in range(4)
    ]
    layout = [0, 1, 2, 3]
    for index in range(3):
        other = layout.index(desired[index])
        if other == index:
            continue
        blocks[index], blocks[other] = blocks[other], blocks[index]
        layout[index], layout[other] = layout[other], layout[index]
    data[8:PB8_STORED_SIZE] = b"".join(blocks)
    _crypt_words(data, 8, PB8_STORED_SIZE, encryption_constant)
    _crypt_words(data, PB8_STORED_SIZE, PB8_PARTY_SIZE, encryption_constant)
    return bytes(data)


def refresh_pb8_checksum(plain: bytearray) -> None:
    if len(plain) != PB8_PARTY_SIZE:
        raise BDSPLiveError(f"Un PB8 debe medir {PB8_PARTY_SIZE} bytes.")
    struct.pack_into("<H", plain, 6, pb8_checksum(plain))


def pb8_checksum(plain: bytes) -> int:
    if len(plain) < PB8_STORED_SIZE:
        raise BDSPLiveError("El PB8 no contiene el bloque almacenado completo.")
    return sum(struct.unpack_from("<160H", plain, 8)) & 0xFFFF


def _decode_pb8_string(raw: bytes, *, label: str) -> str:
    try:
        value = raw.decode("utf-16le")
    except UnicodeDecodeError as exc:
        raise BDSPLiveError(f"{label} no contiene texto UTF-16LE válido.") from exc
    return value.split("\0", 1)[0]


def _pb8_training_values(
    plain: bytes,
) -> tuple[int, int, tuple[int, int, int, int, int, int], tuple[int, int, int, int, int, int]]:
    """Extrae naturaleza, naturaleza efectiva, IV y EV en orden visible.

    PKHeX ``G8PKM`` demuestra Nature/StatNature en 0x20/0x21, los EV en
    0x26..0x2B y el empaquetado de IV32 en 0x8C. El orden devuelto siempre es
    PS, Ataque, Defensa, Ataque Especial, Defensa Especial y Velocidad.
    """

    iv32 = int(struct.unpack_from("<I", plain, 0x8C)[0])
    ivs = tuple((iv32 >> shift) & 0x1F for shift in (0, 5, 10, 20, 25, 15))
    evs = tuple(int(plain[offset]) for offset in (0x26, 0x27, 0x28, 0x2A, 0x2B, 0x29))
    return int(plain[0x20]), int(plain[0x21]), ivs, evs  # type: ignore[return-value]


def _pb8_party_stats(plain: bytes) -> tuple[int, int, int, int, int, int]:
    """Devuelve los seis stats calculados de la extensión party PB8."""

    return tuple(
        int(struct.unpack_from("<H", plain, offset)[0])
        for offset in (0x14A, 0x14C, 0x14E, 0x152, 0x154, 0x150)
    )  # type: ignore[return-value]


def calculate_bdsp_stats(
    base_stats: tuple[int, int, int, int, int, int],
    ivs: tuple[int, int, int, int, int, int],
    evs: tuple[int, int, int, int, int, int],
    level: int,
    stat_nature_id: int,
) -> tuple[int, int, int, int, int, int]:
    """Calcula stats Gen 8 en el orden visible del PB8.

    El resultado se acepta para escritura únicamente cuando esta misma función
    reproduce primero el bloque calc vivo anterior.
    """
    if not 1 <= int(level) <= 100:
        raise BDSPLiveError(f"El nivel {level} queda fuera de 1..100.")
    if any(not 1 <= int(value) <= 255 for value in base_stats):
        raise BDSPLiveError("PersonalTable contiene stats base inválidos.")
    if any(not 0 <= int(value) <= 31 for value in ivs):
        raise BDSPLiveError("El PB8 contiene IV fuera de 0..31.")
    if any(not 0 <= int(value) <= 252 for value in evs) or sum(evs) > 510:
        raise BDSPLiveError("La distribución EV queda fuera de los límites del juego.")
    nature = int(stat_nature_id)
    if not 0 <= nature <= 24:
        raise BDSPLiveError(f"La naturaleza efectiva #{nature} no es válida.")
    hp = ((2 * int(base_stats[0]) + int(ivs[0]) + int(evs[0]) // 4) * int(level)) // 100
    result = [hp + int(level) + 10]
    # IDs de naturaleza: fila aumenta y columna reduce en el orden
    # Ataque, Defensa, Velocidad, At. Esp., Def. Esp.
    nature_order = (1, 2, 5, 3, 4)
    increased, decreased = divmod(nature, 5)
    for visible_index in range(1, 6):
        value = ((2 * int(base_stats[visible_index]) + int(ivs[visible_index]) + int(evs[visible_index]) // 4) * int(level)) // 100 + 5
        nature_index = nature_order.index(visible_index)
        if increased != decreased:
            if nature_index == increased:
                value = value * 110 // 100
            elif nature_index == decreased:
                value = value * 90 // 100
        result.append(value)
    return tuple(result)  # type: ignore[return-value]


def _set_pb8_evs_and_stats(
    plain: bytearray,
    *,
    pokemon: BDSPPartyPokemon,
    expected_evs: tuple[int, int, int, int, int, int],
    desired_evs: tuple[int, int, int, int, int, int],
    base_stats: tuple[int, int, int, int, int, int],
) -> None:
    _nature, stat_nature, stored_ivs, actual_evs = _pb8_training_values(plain)
    if actual_evs != tuple(expected_evs):
        raise BDSPLiveError(
            f"Los EV vivos de {pokemon.nickname or '#' + str(pokemon.species_id)} "
            f"cambiaron ({actual_evs} != {tuple(expected_evs)})."
        )
    desired_evs = tuple(int(value) for value in desired_evs)
    # El bloque calc actúa como testigo de IV efectivos. Si un stat no cuadra
    # con el IV almacenado pero sí con 31, el PB8 está hiperentrenado en él.
    effective_ivs: list[int] = []
    for index, stored in enumerate(stored_ivs):
        with_stored = calculate_bdsp_stats(base_stats, stored_ivs, actual_evs, pokemon.level, stat_nature)[index]
        with_perfect_tuple = list(stored_ivs)
        with_perfect_tuple[index] = 31
        with_perfect = calculate_bdsp_stats(base_stats, tuple(with_perfect_tuple), actual_evs, pokemon.level, stat_nature)[index]
        current = int(pokemon.stats[index])
        if current == with_stored:
            effective_ivs.append(int(stored))
        elif current == with_perfect:
            effective_ivs.append(31)
        else:
            raise BDSPLiveError(
                f"El stat vivo {index + 1} de {pokemon.nickname or pokemon.species_id} "
                "no coincide con PersonalTable/IV/EV/nivel/naturaleza; no se escribió RAM."
            )
    new_stats = calculate_bdsp_stats(
        base_stats, tuple(effective_ivs), desired_evs, pokemon.level, stat_nature,
    )
    for offset, value in zip((0x26, 0x27, 0x28, 0x2A, 0x2B, 0x29), desired_evs):
        plain[offset] = int(value)
    old_current, old_max = int(pokemon.current_hp), int(pokemon.max_hp)
    missing_hp = max(0, old_max - old_current)
    new_max = int(new_stats[0])
    new_current = 0 if old_current == 0 else max(1, new_max - missing_hp)
    struct.pack_into("<H", plain, 0x8A, min(new_current, new_max))
    for offset, value in zip((0x14A, 0x14C, 0x14E, 0x152, 0x154, 0x150), new_stats):
        struct.pack_into("<H", plain, offset, int(value))


def parse_bdsp_box_pokemon(raw: bytes, *, box: int, slot: int) -> BDSPBoxPokemon | None:
    plain = decrypt_pb8(raw)
    sanity = int(struct.unpack_from("<H", plain, 4)[0])
    if sanity != 0:
        raise BDSPLiveError(
            f"El PB8 de caja {box}, slot {slot} declara sanity inválido {sanity}."
        )
    expected = int(struct.unpack_from("<H", plain, 6)[0])
    calculated = pb8_checksum(plain)
    if expected != calculated:
        raise BDSPLiveError(
            f"El PB8 de caja {box}, slot {slot} tiene checksum inválido "
            f"({expected} != {calculated})."
        )
    species = int(struct.unpack_from("<H", plain, 8)[0])
    if species == 0:
        return None
    if not 1 <= species <= BDSP_MAX_SPECIES_ID:
        raise BDSPLiveError(
            f"El PB8 de caja {box}, slot {slot} declara la especie imposible #{species}."
        )
    move_ids = tuple(int(value) for value in struct.unpack_from("<4H", plain, 0x72))
    move_pp = tuple(int(value) for value in plain[0x7A:0x7E])
    move_pp_ups = tuple(int(value) for value in plain[0x7E:0x82])
    if any(move_id > BDSP_MAX_MOVE_ID for move_id in move_ids):
        raise BDSPLiveError(
            f"Caja {box}, slot {slot}: movimientos fuera del catálogo BDSP: {move_ids}."
        )
    if any(value > 3 for value in move_pp_ups):
        raise BDSPLiveError(
            f"Caja {box}, slot {slot}: PP Ups incoherentes: {move_pp_ups}."
        )
    nature_id, stat_nature_id, ivs, evs = _pb8_training_values(plain)
    return BDSPBoxPokemon(
        box=int(box),
        slot=int(slot),
        species_id=species,
        pid=int(struct.unpack_from("<I", plain, 0x1C)[0]),
        tid=int(struct.unpack_from("<H", plain, 0x0C)[0]),
        sid=int(struct.unpack_from("<H", plain, 0x0E)[0]),
        form=int(plain[0x24]),
        nickname=_decode_pb8_string(
            plain[0x58:0x72], label=f"El apodo de caja {box}, slot {slot}",
        ),
        held_item_id=int(struct.unpack_from("<H", plain, 0x0A)[0]),
        ability_id=int(struct.unpack_from("<H", plain, 0x14)[0]),
        move_ids=move_ids,  # type: ignore[arg-type]
        move_pp=move_pp,  # type: ignore[arg-type]
        move_pp_ups=move_pp_ups,  # type: ignore[arg-type]
        is_egg=bool(struct.unpack_from("<I", plain, 0x8C)[0] & 0x40000000),
        markings=tuple(
            bool(struct.unpack_from("<H", plain, 0x18)[0] & (0b11 << (index * 2)))
            for index in range(6)
        ),  # type: ignore[arg-type]
        checksum=expected,
        encrypted=bytes(raw),
        nature_id=nature_id,
        stat_nature_id=stat_nature_id,
        # PB8 stored conserva EXP en 0x10 aunque no conserva el byte de nivel
        # de la extensión party. El adaptador deriva el nivel con la curva de
        # la PersonalTable de esta misma ROM activa.
        experience=int(struct.unpack_from("<I", plain, 0x10)[0]),
        ivs=ivs,
        evs=evs,
    )


def parse_bdsp_party_pokemon(raw: bytes, *, slot: int) -> BDSPPartyPokemon:
    plain = decrypt_pb8(raw)
    sanity = int(struct.unpack_from("<H", plain, 4)[0])
    if sanity != 0:
        raise BDSPLiveError(f"El PB8 runtime del slot {slot} declara sanity inválido {sanity}.")
    expected = int(struct.unpack_from("<H", plain, 6)[0])
    calculated = pb8_checksum(plain)
    if expected != calculated:
        raise BDSPLiveError(
            f"El PB8 runtime del slot {slot} tiene checksum inválido "
            f"({expected} != {calculated})."
        )
    species = int(struct.unpack_from("<H", plain, 8)[0])
    if not 1 <= species <= BDSP_MAX_SPECIES_ID:
        raise BDSPLiveError(
            f"El PB8 runtime del slot {slot} declara la especie imposible #{species}."
        )
    current_hp = int(struct.unpack_from("<H", plain, 0x8A)[0])
    status_condition = int(struct.unpack_from("<I", plain, 0x94)[0])
    level = int(plain[PB8_STORED_SIZE])
    max_hp = int(struct.unpack_from("<H", plain, 0x14A)[0])
    move_ids = tuple(int(value) for value in struct.unpack_from("<4H", plain, 0x72))
    move_pp = tuple(int(value) for value in plain[0x7A:0x7E])
    move_pp_ups = tuple(int(value) for value in plain[0x7E:0x82])
    if any(move_id > BDSP_MAX_MOVE_ID for move_id in move_ids):
        raise BDSPLiveError(
            f"El slot runtime {slot} declara movimientos fuera del catálogo BDSP: {move_ids}."
        )
    if any(value > 3 for value in move_pp_ups):
        raise BDSPLiveError(
            f"El slot runtime {slot} declara PP Ups incoherentes: {move_pp_ups}."
        )
    if not 1 <= level <= 100:
        raise BDSPLiveError(f"El slot runtime {slot} declara el nivel imposible {level}.")
    if max_hp <= 0 or current_hp > max_hp:
        raise BDSPLiveError(
            f"El slot runtime {slot} declara HP incoherente {current_hp}/{max_hp}."
        )
    nature_id, stat_nature_id, ivs, evs = _pb8_training_values(plain)
    return BDSPPartyPokemon(
        slot=int(slot),
        species_id=species,
        pid=int(struct.unpack_from("<I", plain, 0x1C)[0]),
        tid=int(struct.unpack_from("<H", plain, 0x0C)[0]),
        sid=int(struct.unpack_from("<H", plain, 0x0E)[0]),
        form=int(plain[0x24]),
        nickname=_decode_pb8_string(
            plain[0x58:0x72], label=f"El apodo del slot runtime {slot}",
        ),
        held_item_id=int(struct.unpack_from("<H", plain, 0x0A)[0]),
        ability_id=int(struct.unpack_from("<H", plain, 0x14)[0]),
        move_ids=move_ids,  # type: ignore[arg-type]
        move_pp=move_pp,  # type: ignore[arg-type]
        move_pp_ups=move_pp_ups,  # type: ignore[arg-type]
        is_egg=bool(struct.unpack_from("<I", plain, 0x8C)[0] & 0x40000000),
        markings=tuple(
            bool(struct.unpack_from("<H", plain, 0x18)[0] & (0b11 << (index * 2)))
            for index in range(6)
        ),  # type: ignore[arg-type]
        current_hp=current_hp,
        max_hp=max_hp,
        level=level,
        checksum=expected,
        encrypted=bytes(raw),
        nature_id=nature_id,
        stat_nature_id=stat_nature_id,
        ivs=ivs,
        evs=evs,
        stats=_pb8_party_stats(plain),
        status_condition=status_condition,
    )


class BDSPInventoryReader:
    """Lector estable del array ``PlayerWork.SaveData.saveItem`` de SP 1.3.0."""

    def __init__(self, client: RyujinxHostMappedClient) -> None:
        if client.profile != BDSP_SP_130_HOST_PROFILE:
            raise BDSPLiveError(
                "El lector de mochila disponible solo cubre Perla Reluciente 1.3.0."
            )
        self.client = client

    @staticmethod
    def _valid_guest_pointer(value: int) -> bool:
        return 0x1000 <= int(value) < RYUJINX_HOST_ADDRESS_SPACE_SIZE

    def _stable(self, address: int, size: int, label: str) -> bytes:
        first = self.client.read_memory(int(address), int(size))
        second = self.client.read_memory(int(address), int(size))
        if first != second:
            raise BDSPLiveError(f"{label} cambió durante la doble lectura.")
        return second

    def read(self) -> BDSPInventoryRead:
        try:
            first_data = self.client.resolve_main_pointer(BDSP_SP_130_INVENTORY_POINTER)
            second_data = self.client.resolve_main_pointer(BDSP_SP_130_INVENTORY_POINTER)
            if first_data != second_data or not self._valid_guest_pointer(first_data):
                raise BDSPLiveError(
                    "La referencia runtime de la mochila cambió durante la captura."
                )

            array_object = int(first_data) - 0x20
            if not self._valid_guest_pointer(array_object):
                raise BDSPLiveError("La mochila no contiene un array IL2CPP válido.")
            length = int(struct.unpack(
                "<Q", self._stable(
                    array_object + 0x18, 8, "La longitud del array saveItem",
                ),
            )[0])
            if length != BDSP_INVENTORY_ITEM_COUNT:
                raise BDSPLiveError(
                    f"El array saveItem declara {length} registros; se esperaban "
                    f"{BDSP_INVENTORY_ITEM_COUNT}."
                )

            raw = self._stable(
                first_data, BDSP_INVENTORY_BLOCK_SIZE, "El bloque saveItem",
            )
            items: list[BDSPInventoryItem] = []
            for item_id in range(BDSP_INVENTORY_ITEM_COUNT):
                offset = item_id * BDSP_INVENTORY_RECORD_SIZE
                count = int(struct.unpack_from("<i", raw, offset)[0])
                vanish_new, favorite, show_move_name = raw[offset + 4:offset + 7]
                padding = raw[offset + 7:offset + 10]
                sort_order = int(struct.unpack_from("<H", raw, offset + 10)[0])
                if not 0 <= count <= 999:
                    raise BDSPLiveError(
                        f"saveItem[{item_id}] declara la cantidad imposible {count}."
                    )
                if any(value not in (0, 1) for value in (
                    vanish_new, favorite, show_move_name,
                )):
                    raise BDSPLiveError(
                        f"saveItem[{item_id}] contiene flags booleanos inválidos."
                    )
                if padding != b"\0\0\0":
                    raise BDSPLiveError(
                        f"saveItem[{item_id}] contiene padding no nulo."
                    )
                if sort_order > BDSP_INVENTORY_ITEM_COUNT:
                    raise BDSPLiveError(
                        f"saveItem[{item_id}] declara el orden imposible {sort_order}."
                    )
                if count > 0 and sort_order == 0:
                    raise BDSPLiveError(
                        f"saveItem[{item_id}] tiene cantidad {count} sin orden de mochila."
                    )
                if count <= 0:
                    continue
                items.append(BDSPInventoryItem(
                    item_id=item_id,
                    count=count,
                    vanish_new=bool(vanish_new),
                    favorite=bool(favorite),
                    show_move_name=bool(show_move_name),
                    sort_order=sort_order,
                ))

            return BDSPInventoryRead(
                items=tuple(items),
                total_records=length,
                array_object=array_object,
                data_pointer=int(first_data),
                raw=bytes(raw),
            )
        except RyujinxHostMemoryError as exc:
            raise BDSPLiveError(str(exc)) from exc


class BDSPMoneyReader:
    """Lee y valida el ``MYSTATUS`` vivo de Perla Reluciente 1.3.0."""

    def __init__(self, client: RyujinxHostMappedClient) -> None:
        if client.profile != BDSP_SP_130_HOST_PROFILE:
            raise BDSPLiveError(
                "El lector de dinero disponible solo cubre Perla Reluciente 1.3.0."
            )
        self.client = client

    @staticmethod
    def _valid_guest_pointer(value: int) -> bool:
        return 0x1000 <= int(value) < RYUJINX_HOST_ADDRESS_SPACE_SIZE

    def _stable(self, address: int, size: int, label: str) -> bytes:
        first = self.client.read_memory(int(address), int(size))
        second = self.client.read_memory(int(address), int(size))
        if first != second:
            raise BDSPLiveError(f"{label} cambió durante la doble lectura.")
        return second

    def read(self) -> BDSPMoneyRead:
        try:
            first_pointer = self.client.resolve_main_pointer(BDSP_SP_130_MYSTATUS_POINTER)
            second_pointer = self.client.resolve_main_pointer(BDSP_SP_130_MYSTATUS_POINTER)
            if (
                first_pointer != second_pointer
                or not self._valid_guest_pointer(first_pointer)
            ):
                raise BDSPLiveError(
                    "La referencia runtime de MYSTATUS cambió durante la captura."
                )
            raw = self._stable(
                first_pointer, BDSP_MYSTATUS_RUNTIME_SIZE, "El MYSTATUS vivo",
            )
            name_pointer = int(struct.unpack_from("<Q", raw, 0)[0])
            if not self._valid_guest_pointer(name_pointer):
                raise BDSPLiveError("MYSTATUS no contiene una referencia de nombre válida.")
            name_length = int(struct.unpack(
                "<I", self._stable(
                    name_pointer + 0x10, 4, "La longitud del nombre del entrenador",
                ),
            )[0])
            if not 1 <= name_length <= 12:
                raise BDSPLiveError(
                    f"MYSTATUS declara un nombre de {name_length} caracteres."
                )
            trainer_name = self._stable(
                name_pointer + 0x14, name_length * 2, "El nombre del entrenador",
            ).decode("utf-16le", errors="strict")
            trainer_id = int(struct.unpack_from("<I", raw, 0x08)[0])
            money = int(struct.unpack_from("<I", raw, BDSP_MYSTATUS_MONEY_OFFSET)[0])
            sex = int(raw[0x10])
            badge_count = int(raw[0x12])
            rom_code = int(raw[0x14])
            if trainer_id == 0:
                raise BDSPLiveError("MYSTATUS no contiene un ID de entrenador válido.")
            if not 0 <= money <= BDSP_MAX_MONEY:
                raise BDSPLiveError(
                    f"MYSTATUS declara {money} ₽; BDSP admite hasta {BDSP_MAX_MONEY}."
                )
            if sex not in (0, 1) or not 0 <= badge_count <= 8 or rom_code not in (0, 1):
                raise BDSPLiveError(
                    "MYSTATUS no supera los invariantes de sexo, medallas y edición."
                )
            return BDSPMoneyRead(
                trainer_name=trainer_name,
                trainer_id=trainer_id,
                money=money,
                badge_count=badge_count,
                rom_code=rom_code,
                data_pointer=int(first_pointer),
                raw=bytes(raw),
            )
        except (RyujinxHostMemoryError, UnicodeDecodeError) as exc:
            raise BDSPLiveError(str(exc)) from exc


class BDSPBadgeReader:
    """Lee los ocho SystemFlags que el propio BDSP cuenta como medallas."""

    def __init__(self, client: RyujinxHostMappedClient) -> None:
        if client.profile != BDSP_SP_130_HOST_PROFILE:
            raise BDSPLiveError(
                "El lector de medallas disponible solo cubre Perla Reluciente 1.3.0."
            )
        self.client = client

    @staticmethod
    def _valid_guest_pointer(value: int) -> bool:
        return 0x1000 <= int(value) < RYUJINX_HOST_ADDRESS_SPACE_SIZE

    def _stable(self, address: int, size: int, label: str) -> bytes:
        first = self.client.read_memory(int(address), int(size))
        second = self.client.read_memory(int(address), int(size))
        if first != second:
            raise BDSPLiveError(f"{label} cambió durante la doble lectura.")
        return second

    def read(self) -> BDSPBadgeRead:
        try:
            first_data = self.client.resolve_main_pointer(
                BDSP_SP_130_SYSTEM_FLAGS_POINTER,
            )
            second_data = self.client.resolve_main_pointer(
                BDSP_SP_130_SYSTEM_FLAGS_POINTER,
            )
            if first_data != second_data or not self._valid_guest_pointer(first_data):
                raise BDSPLiveError(
                    "La referencia runtime de SystemFlags cambió durante la captura."
                )

            array_object = int(first_data) - 0x20
            if not self._valid_guest_pointer(array_object):
                raise BDSPLiveError("SystemFlags no contiene un array IL2CPP válido.")
            length = int(struct.unpack(
                "<Q", self._stable(
                    array_object + 0x18, 8, "La longitud del array SystemFlags",
                ),
            )[0])
            if length != BDSP_SYSTEM_FLAG_COUNT:
                raise BDSPLiveError(
                    f"SystemFlags declara {length} elementos; se esperaban "
                    f"{BDSP_SYSTEM_FLAG_COUNT}."
                )

            raw = self._stable(
                first_data, BDSP_SYSTEM_FLAG_COUNT, "El array SystemFlags",
            )
            if any(value not in (0, 1) for value in raw):
                raise BDSPLiveError("SystemFlags contiene valores no booleanos.")
            values = tuple(
                bool(raw[index]) for index in BDSP_BADGE_SYSTEM_FLAG_INDICES
            )
            return BDSPBadgeRead(
                count=sum(values),
                values=values,  # type: ignore[arg-type]
                array_object=array_object,
                data_pointer=int(first_data),
            )
        except RyujinxHostMemoryError as exc:
            raise BDSPLiveError(str(exc)) from exc


class BDSPPartyReader:
    """Lector estable de PlayerWork._playerParty para SP 1.3.0."""

    def __init__(self, client: RyujinxHostMappedClient) -> None:
        if client.profile != BDSP_SP_130_HOST_PROFILE:
            raise BDSPLiveError("El lector de party disponible solo cubre Perla Reluciente 1.3.0.")
        self.client = client

    @staticmethod
    def _valid_guest_pointer(value: int) -> bool:
        return 0x1000 <= int(value) < RYUJINX_HOST_ADDRESS_SPACE_SIZE

    def _stable(self, address: int, size: int, label: str) -> bytes:
        first = self.client.read_memory(int(address), int(size))
        second = self.client.read_memory(int(address), int(size))
        if first != second:
            raise BDSPLiveError(f"{label} cambió durante la doble lectura.")
        return second

    def read(self) -> BDSPPartyRead:
        try:
            first_party = self.client.resolve_main_pointer(BDSP_SP_130_PARTY_POINTER)
            second_party = self.client.resolve_main_pointer(BDSP_SP_130_PARTY_POINTER)
            if first_party != second_party or not self._valid_guest_pointer(first_party):
                raise BDSPLiveError("La referencia runtime de la party cambió durante la captura.")

            party_header = self._stable(first_party + 0x10, 12, "La cabecera de PokeParty")
            member_array = int(struct.unpack_from("<Q", party_header, 0)[0])
            member_count = int(struct.unpack_from("<I", party_header, 8)[0])
            if not self._valid_guest_pointer(member_array):
                raise BDSPLiveError("PokeParty contiene un puntero de miembros inválido.")
            if not 1 <= member_count <= 6:
                raise BDSPLiveError(f"PokeParty declara {member_count} miembros; se esperaban entre 1 y 6.")

            array_length = int(struct.unpack("<Q", self._stable(
                member_array + 0x18, 8, "La longitud del array de party",
            ))[0])
            if array_length != 6:
                raise BDSPLiveError(
                    f"El array runtime de party declara longitud {array_length}; se esperaba 6."
                )
            pointers_raw = self._stable(
                member_array + 0x20, 48, "Los punteros del array de party",
            )
            member_pointers = struct.unpack("<6Q", pointers_raw)
            active_pointers = member_pointers[:member_count]
            if any(not self._valid_guest_pointer(value) for value in active_pointers):
                raise BDSPLiveError("La party contiene un puntero PokemonParam inválido.")
            if len(set(active_pointers)) != member_count:
                raise BDSPLiveError("La party contiene miembros duplicados por puntero.")

            result: list[BDSPPartyPokemon] = []
            storage_slots: list[BDSPPartyStorageSlot] = []
            for slot, pokemon_param in enumerate(member_pointers, start=1):
                active = slot <= member_count
                if not self._valid_guest_pointer(pokemon_param):
                    if active:
                        raise BDSPLiveError(
                            f"PokemonParam del slot {slot} contiene un puntero inválido.",
                        )
                    # Fixtures antiguos y estados ajenos al contrato 5↔6 pueden
                    # no exponer los objetos inactivos. La lectura activa sigue
                    # siendo válida; el writer de tamaño exigirá los seis.
                    continue
                try:
                    fields = self._stable(
                        int(pokemon_param) + 0x10, 24,
                        f"PokemonParam del slot {slot}",
                    )
                    core_pointer, calc_pointer, accessor_pointer = struct.unpack(
                        "<3Q", fields,
                    )
                    if any(
                        not self._valid_guest_pointer(value)
                        for value in (core_pointer, calc_pointer, accessor_pointer)
                    ):
                        raise BDSPLiveError(
                            f"PokemonParam del slot {slot} contiene punteros inválidos.",
                        )
                    core_length = int(struct.unpack("<Q", self._stable(
                        core_pointer + 0x18, 8,
                        f"La longitud core del slot {slot}",
                    ))[0])
                    calc_length = int(struct.unpack("<Q", self._stable(
                        calc_pointer + 0x18, 8,
                        f"La longitud calc del slot {slot}",
                    ))[0])
                    if (
                        core_length != PB8_STORED_SIZE
                        or calc_length != PB8_PARTY_SIZE - PB8_STORED_SIZE
                    ):
                        raise BDSPLiveError(
                            f"PokemonParam del slot {slot} declara tamaños "
                            f"{core_length}+{calc_length}; se esperaban 328+16."
                        )
                    core = self._stable(
                        core_pointer + 0x20, PB8_STORED_SIZE,
                        f"El core PB8 del slot {slot}",
                    )
                    calc = self._stable(
                        calc_pointer + 0x20,
                        PB8_PARTY_SIZE - PB8_STORED_SIZE,
                        f"Los datos calculados del slot {slot}",
                    )
                except Exception:
                    if active:
                        raise
                    continue

                encrypted = core + calc
                storage_slots.append(BDSPPartyStorageSlot(
                    slot=slot,
                    pokemon_param_pointer=int(pokemon_param),
                    core_data_pointer=int(core_pointer) + 0x20,
                    calc_data_pointer=int(calc_pointer) + 0x20,
                    encrypted=encrypted,
                ))
                if not active:
                    continue
                parsed = parse_bdsp_party_pokemon(encrypted, slot=slot)
                result.append(BDSPPartyPokemon(
                    **{
                        field_name: getattr(parsed, field_name)
                        for field_name in (
                            "slot", "species_id", "pid", "tid", "sid", "form",
                            "nickname", "held_item_id", "ability_id", "move_ids",
                            "move_pp", "move_pp_ups", "is_egg", "markings",
                            "current_hp", "max_hp", "level", "checksum", "encrypted",
                            "nature_id", "stat_nature_id", "ivs", "evs", "stats",
                        )
                    },
                    pokemon_param_pointer=int(pokemon_param),
                    core_data_pointer=int(core_pointer) + 0x20,
                    calc_data_pointer=int(calc_pointer) + 0x20,
                ))

            return BDSPPartyRead(
                pokemon=tuple(result),
                member_count=member_count,
                party_object=first_party,
                member_array=member_array,
                member_count_address=int(first_party) + 0x18,
                storage_slots=tuple(storage_slots),
            )
        except RyujinxHostMemoryError as exc:
            raise BDSPLiveError(str(exc)) from exc


class BDSPBattleReader:
    """Lector de HP del cliente jugador mientras BattleProc está activo."""

    def __init__(self, client: RyujinxHostMappedClient) -> None:
        if client.profile != BDSP_SP_130_HOST_PROFILE:
            raise BDSPLiveError("El lector de batalla disponible solo cubre Perla Reluciente 1.3.0.")
        self.client = client

    @staticmethod
    def _valid_guest_pointer(value: int) -> bool:
        return 0x1000 <= int(value) < RYUJINX_HOST_ADDRESS_SPACE_SIZE

    def _stable(self, address: int, size: int, label: str) -> bytes:
        first = self.client.read_memory(int(address), int(size))
        second = self.client.read_memory(int(address), int(size))
        if first != second:
            raise BDSPLiveError(f"{label} cambió durante la doble lectura.")
        return second

    def _lifecycle(self) -> tuple[bool, bool]:
        type_info_raw = self._stable(
            self.client.profile.guest_main + BDSP_SP_130_BATTLEPROC_TYPEINFO_OFFSET,
            8,
            "La referencia TypeInfo de BattleProc",
        )
        type_info = int(struct.unpack("<Q", type_info_raw)[0])
        # En SP 1.3.0 la ranura IL2CPP puede quedar literalmente a cero cuando
        # BattleProc todavía no se ha cargado en la sesión. La captura física
        # alpha.75 lo observó estable fuera de combate mientras PlayerWork y
        # BattleViewUISystem seguían siendo legibles. Cero significa por tanto
        # "clase ausente"; cualquier otro valor no direccionable continúa siendo
        # corrupción/una revisión incompatible y se rechaza.
        if type_info == 0:
            return False, False
        if not self._valid_guest_pointer(type_info):
            raise BDSPLiveError("BattleProc contiene un TypeInfo inválido.")
        static_raw = self._stable(type_info + 0xB8, 8, "Los campos estáticos de BattleProc")
        static_fields = int(struct.unpack("<Q", static_raw)[0])
        if not self._valid_guest_pointer(static_fields):
            raise BDSPLiveError("BattleProc no contiene campos estáticos válidos.")
        initialized, ended = self._stable(
            static_fields + 0x8, 2, "El ciclo de vida de BattleProc",
        )
        return bool(initialized), bool(ended)

    def read(self) -> BDSPBattleRead | None:
        try:
            initialized, ended = self._lifecycle()
            if not initialized or ended:
                return None

            first_party = self.client.resolve_main_pointer(BDSP_SP_130_BATTLE_PARTY_POINTER)
            second_party = self.client.resolve_main_pointer(BDSP_SP_130_BATTLE_PARTY_POINTER)
            if first_party != second_party or not self._valid_guest_pointer(first_party):
                raise BDSPLiveError("La referencia de la party de batalla cambió durante la captura.")

            header = self._stable(first_party + 0x10, 9, "La cabecera de BTL_PARTY")
            member_array = int(struct.unpack_from("<Q", header, 0)[0])
            member_count = int(header[8])
            if not self._valid_guest_pointer(member_array):
                raise BDSPLiveError("BTL_PARTY contiene un puntero de miembros inválido.")
            if not 1 <= member_count <= 6:
                raise BDSPLiveError(f"BTL_PARTY declara {member_count} miembros; se esperaban entre 1 y 6.")
            array_length = int(struct.unpack("<Q", self._stable(
                member_array + 0x18, 8, "La longitud del array BTL_PARTY",
            ))[0])
            if array_length != 6:
                raise BDSPLiveError(
                    f"El array BTL_PARTY declara longitud {array_length}; se esperaba 6."
                )
            member_raw = self._stable(
                member_array + 0x20, 48, "Los punteros de BTL_PARTY",
            )
            members = struct.unpack("<6Q", member_raw)[:member_count]
            if any(not self._valid_guest_pointer(value) for value in members):
                raise BDSPLiveError("BTL_PARTY contiene un puntero BTL_POKEPARAM inválido.")
            if len(set(members)) != member_count:
                raise BDSPLiveError("BTL_PARTY contiene miembros duplicados por puntero.")

            result: list[BDSPBattlePokemon] = []
            party_indices: set[int] = set()
            for row, battle_param in enumerate(members, start=1):
                object_fields = self._stable(
                    int(battle_param) + 0x10, 40, f"BTL_POKEPARAM de la fila {row}",
                )
                core_pointer, base_pointer, variable_pointer, effort_pointer, moves_pointer = struct.unpack(
                    "<5Q", object_fields,
                )
                if any(
                    not self._valid_guest_pointer(value)
                    for value in (
                        core_pointer, base_pointer, variable_pointer, effort_pointer, moves_pointer,
                    )
                ):
                    raise BDSPLiveError(f"BTL_POKEPARAM de la fila {row} contiene punteros inválidos.")
                core = self._stable(
                    core_pointer + 0x18, 24, f"CORE_PARAM de la fila {row}",
                )
                (
                    _personal_random,
                    _experience,
                    species,
                    _form,
                    max_hp,
                    current_hp,
                    _item,
                    _used_item,
                    _ability,
                    level,
                    poke_id,
                ) = struct.unpack("<IIHHHHHHHBB", core)
                if not 1 <= species <= BDSP_MAX_SPECIES_ID:
                    raise BDSPLiveError(
                        f"La fila de batalla {row} declara la especie imposible #{species}."
                    )
                if max_hp <= 0 or current_hp > max_hp:
                    raise BDSPLiveError(
                        f"La fila de batalla {row} declara HP incoherente {current_hp}/{max_hp}."
                    )
                if not 1 <= level <= 100:
                    raise BDSPLiveError(
                        f"La fila de batalla {row} declara el nivel imposible {level}."
                    )
                # PokeID.cs demuestra que los IDs 0..5 pertenecen al cliente
                # jugador y se convierten directamente al índice de su party.
                if not 0 <= poke_id < 6:
                    raise BDSPLiveError(
                        f"La fila de batalla {row} no pertenece a la party del jugador: PokeID {poke_id}."
                    )
                if poke_id in party_indices:
                    raise BDSPLiveError(f"BTL_PARTY repite el índice de party {poke_id}.")
                party_indices.add(poke_id)
                result.append(BDSPBattlePokemon(
                    row=row,
                    party_index=poke_id,
                    species_id=int(species),
                    current_hp=int(current_hp),
                    max_hp=int(max_hp),
                    level=int(level),
                ))

            return BDSPBattleRead(
                pokemon=tuple(result),
                member_count=member_count,
                battle_party_object=first_party,
                member_array=member_array,
            )
        except RyujinxHostMemoryError as exc:
            # Desaparecer durante el final de la escena es una muestra inválida,
            # no una party vacía. El siguiente tick observará lifecycle inactivo.
            raise BDSPLiveError(str(exc)) from exc


class BDSPBattlePresentationReader:
    """Observa la barra visible de HP sin convertirla aún en autoridad de KO.

    ``BTL_POKEPARAM.CORE_PARAM.hp`` es estado lógico y la prueba alpha.67
    demostró que llega a cero antes de que el usuario vea la animación. BDSP
    mantiene por separado cuatro ``BUIStatusWindow`` con el HP presentado y el
    flag ``HpBar.IsAnimation``. Este reader registra esa frontera para demostrar
    su temporización física antes de cambiar el compromiso de una muerte.
    """

    _EXPECTED_WINDOW_COUNT = 4

    def __init__(self, client: RyujinxHostMappedClient) -> None:
        if client.profile != BDSP_SP_130_HOST_PROFILE:
            raise BDSPLiveError(
                "El lector de presentación disponible solo cubre Perla Reluciente 1.3.0."
            )
        self.client = client

    @staticmethod
    def _valid_guest_pointer(value: int) -> bool:
        return 0x1000 <= int(value) < RYUJINX_HOST_ADDRESS_SPACE_SIZE

    def _stable(self, address: int, size: int, label: str) -> bytes:
        first = self.client.read_memory(int(address), int(size))
        second = self.client.read_memory(int(address), int(size))
        if first != second:
            raise BDSPLiveError(f"{label} cambió durante la doble lectura.")
        return second

    def _pointer(self, address: int, label: str) -> int:
        value = int(struct.unpack("<Q", self._stable(address, 8, label))[0])
        if not self._valid_guest_pointer(value):
            raise BDSPLiveError(f"{label} contiene un puntero inválido.")
        return value

    def _class_name(self, type_info: int, label: str) -> str:
        name_pointer = self._pointer(type_info + 0x10, f"El nombre IL2CPP de {label}")
        raw = self._stable(name_pointer, 32, f"El nombre IL2CPP de {label}")
        return raw.split(b"\0", 1)[0].decode("ascii", errors="replace")

    def read(self) -> BDSPBattlePresentationRead:
        try:
            type_info = self._pointer(
                self.client.profile.guest_main + BDSP_SP_130_BATTLE_UI_TYPEINFO_OFFSET,
                "La referencia TypeInfo de BattleViewUISystem",
            )
            if self._class_name(type_info, "BattleViewUISystem") != "BattleViewUISystem":
                raise BDSPLiveError(
                    "El TypeInfo nominal no identifica BattleViewUISystem."
                )
            static_fields = self._pointer(
                type_info + 0xB8, "Los campos estáticos de BattleViewUISystem",
            )
            # FieldInfo IL2CPP: _instance es el quinto campo estático y queda a
            # +0x20; los tres arrays readonly y dos escalares anteriores fueron
            # comprobados en la clase física SP 1.3.0.
            ui_instance = self._pointer(
                static_fields + 0x20, "BattleViewUISystem._instance",
            )
            instance_type = int(struct.unpack(
                "<Q", self._stable(ui_instance, 8, "La clase de BattleViewUISystem")
            )[0])
            if instance_type != type_info:
                raise BDSPLiveError(
                    "BattleViewUISystem._instance no pertenece al TypeInfo esperado."
                )
            # _statusWindows es el segundo campo de instancia: +0x20.
            status_array = self._pointer(
                ui_instance + 0x20, "BattleViewUISystem._statusWindows",
            )
            count = int(struct.unpack(
                "<Q", self._stable(status_array + 0x18, 8, "La longitud de _statusWindows")
            )[0])
            if count != self._EXPECTED_WINDOW_COUNT:
                raise BDSPLiveError(
                    f"_statusWindows declara {count} ventanas; se esperaban 4."
                )
            window_pointers = struct.unpack(
                "<4Q", self._stable(status_array + 0x20, 32, "Las ventanas de estado")
            )
            if any(not self._valid_guest_pointer(value) for value in window_pointers):
                raise BDSPLiveError("_statusWindows contiene una ventana inválida.")
            if len(set(window_pointers)) != count:
                raise BDSPLiveError("_statusWindows contiene ventanas duplicadas.")

            windows: list[BDSPBattlePresentationWindow] = []
            for index, window in enumerate(window_pointers):
                window_type = self._pointer(window, f"La clase de BUIStatusWindow {index}")
                if self._class_name(window_type, f"BUIStatusWindow {index}") != "BUIStatusWindow":
                    raise BDSPLiveError(
                        f"La ventana {index} no pertenece a BUIStatusWindow."
                    )
                hp_bar = self._pointer(window + 0xA0, f"El HpBar de la ventana {index}")
                hp_bar_type = self._pointer(hp_bar, f"La clase HpBar de la ventana {index}")
                if self._class_name(hp_bar_type, f"HpBar {index}") != "HpBar":
                    raise BDSPLiveError(f"La ventana {index} no contiene un HpBar válido.")
                # FieldInfo BUIStatusWindow: DoDisplay +0xD8, current/max HP
                # +0xDC/+0xE0, level/PokeID/player/apply +0xE4..E7 y flags de
                # inicialización +0x108/+0x109. HpBar.IsAnimation está a +0x54.
                status = self._stable(
                    window + 0xD8, 0x32, f"El estado visible de la ventana {index}",
                )
                displayed = bool(status[0])
                current_hp, max_hp = struct.unpack_from("<II", status, 4)
                level, poke_id, is_player, needs_hp_apply = status[12:16]
                initialized, setup = status[0x30:0x32]
                hp_animation = bool(self._stable(
                    hp_bar + 0x54, 1, f"La animación HP de la ventana {index}",
                )[0])
                if initialized and (max_hp <= 0 or current_hp > max_hp):
                    raise BDSPLiveError(
                        f"La ventana {index} declara HP visible incoherente "
                        f"{current_hp}/{max_hp}."
                    )
                if is_player and not 0 <= poke_id < 6:
                    raise BDSPLiveError(
                        f"La ventana jugador {index} declara PokeID {poke_id}."
                    )
                windows.append(BDSPBattlePresentationWindow(
                    window_index=index,
                    displayed=displayed,
                    current_hp=int(current_hp),
                    max_hp=int(max_hp),
                    level=int(level),
                    poke_id=int(poke_id),
                    is_player=bool(is_player),
                    needs_hp_apply=bool(needs_hp_apply),
                    hp_animation=hp_animation,
                    initialized=bool(initialized),
                    setup=bool(setup),
                ))

            return BDSPBattlePresentationRead(
                windows=tuple(windows),
                ui_instance=ui_instance,
                status_array=status_array,
            )
        except RyujinxHostMemoryError as exc:
            raise BDSPLiveError(str(exc)) from exc


class BDSPBoxReader:
    """Lector estable de cajas autorizado solo para el perfil SP 1.3.0."""

    def __init__(self, client: RyujinxHostMappedClient) -> None:
        if client.profile != BDSP_SP_130_HOST_PROFILE:
            raise BDSPLiveError("El lector de cajas disponible solo cubre Perla Reluciente 1.3.0.")
        self.client = client

    @staticmethod
    def _valid_guest_pointer(value: int) -> bool:
        return 0x1000 <= int(value) < RYUJINX_HOST_ADDRESS_SPACE_SIZE

    def _stable(self, address: int, size: int, label: str) -> bytes:
        first = self.client.read_memory(int(address), int(size))
        second = self.client.read_memory(int(address), int(size))
        if first != second:
            raise BDSPLiveError(f"{label} cambió durante la doble lectura.")
        return second

    def read(self) -> BDSPBoxRead:
        try:
            pointer_base = self.client.resolve_main_pointer(BDSP_SP_130_BOX_POINTER)
            outer_raw = self._stable(pointer_base, BDSP_BOX_COUNT * 8, "La matriz de cajas")
            box_pointers = struct.unpack(f"<{BDSP_BOX_COUNT}Q", outer_raw)
            if any(not self._valid_guest_pointer(value) for value in box_pointers):
                raise BDSPLiveError("La matriz de cajas contiene punteros fuera del espacio invitado.")

            result: list[BDSPBoxPokemon] = []
            storage_slots: list[BDSPBoxStorageSlot] = []
            empty = 0
            for box_index, box_pointer in enumerate(box_pointers, start=1):
                slots_raw = self._stable(
                    int(box_pointer) + 0x20,
                    BDSP_BOX_SLOT_COUNT * 8,
                    f"La matriz de slots de la caja {box_index}",
                )
                slot_pointers = struct.unpack(f"<{BDSP_BOX_SLOT_COUNT}Q", slots_raw)
                if any(not self._valid_guest_pointer(value) for value in slot_pointers):
                    raise BDSPLiveError(f"La caja {box_index} contiene un puntero de slot inválido.")
                for slot_index, slot_pointer in enumerate(slot_pointers, start=1):
                    length_raw = self._stable(
                        int(slot_pointer) + 0x18, 8,
                        f"La longitud PB8 de caja {box_index}, slot {slot_index}",
                    )
                    length = int(struct.unpack("<Q", length_raw)[0])
                    if length != PB8_PARTY_SIZE:
                        raise BDSPLiveError(
                            f"Caja {box_index}, slot {slot_index}: longitud PB8 {length}; "
                            f"se esperaba {PB8_PARTY_SIZE}."
                        )
                    raw = self._stable(
                        int(slot_pointer) + 0x20,
                        PB8_PARTY_SIZE,
                        f"El PB8 de caja {box_index}, slot {slot_index}",
                    )
                    storage_slots.append(BDSPBoxStorageSlot(
                        box=box_index,
                        slot=slot_index,
                        data_pointer=int(slot_pointer) + 0x20,
                        encrypted=raw,
                    ))
                    pokemon = parse_bdsp_box_pokemon(raw, box=box_index, slot=slot_index)
                    if pokemon is None:
                        empty += 1
                    else:
                        result.append(BDSPBoxPokemon(
                            **{
                                field_name: getattr(pokemon, field_name)
                                for field_name in (
                                    "box", "slot", "species_id", "pid", "tid", "sid",
                                    "form", "nickname", "held_item_id", "ability_id",
                                    "move_ids", "move_pp", "move_pp_ups", "is_egg",
                                    "markings", "checksum", "encrypted", "nature_id",
                                    "stat_nature_id", "experience", "ivs", "evs",
                                )
                            },
                            data_pointer=int(slot_pointer) + 0x20,
                        ))
            return BDSPBoxRead(
                pokemon=tuple(result),
                total_slots=BDSP_BOX_COUNT * BDSP_BOX_SLOT_COUNT,
                empty_slots=empty,
                pointer_base=pointer_base,
                storage_slots=tuple(storage_slots),
            )
        except RyujinxHostMemoryError as exc:
            raise BDSPLiveError(str(exc)) from exc


class BDSPLiveWriter:
    """Writer transaccional de party + MT para SP 1.3.0 HostMapped.

    La implementación no descubre offsets nuevos ni escanea memoria. Reutiliza
    exclusivamente el grafo IL2CPP ya validado por los readers, exige dos
    capturas completas iguales, escribe la unidad almacenada PB8 y el registro
    SaveItem exacto, y verifica tanto el significado como los bytes. Cualquier
    fallo restaura ambos destinos y comprueba también el rollback.
    """

    def __init__(
        self,
        client: RyujinxHostMappedClient,
        *,
        tm_profile_getter: Callable[[], BDSPTMProfile | None],
        transport_factory: Callable[[], object] = RyujinxHostWriteTransport,
        party_reader_factory: Callable[[RyujinxHostMappedClient], BDSPPartyReader] = BDSPPartyReader,
        inventory_reader_factory: Callable[[RyujinxHostMappedClient], BDSPInventoryReader] = BDSPInventoryReader,
        money_reader_factory: Callable[[RyujinxHostMappedClient], BDSPMoneyReader] = BDSPMoneyReader,
        battle_reader_factory: Callable[[RyujinxHostMappedClient], BDSPBattleReader] = BDSPBattleReader,
        box_reader_factory: Callable[[RyujinxHostMappedClient], BDSPBoxReader] = BDSPBoxReader,
    ) -> None:
        if client.profile != BDSP_SP_130_HOST_PROFILE:
            raise BDSPLiveError(
                "El writer disponible solo cubre Perla Reluciente 1.3.0."
            )
        self.client = client
        self.tm_profile_getter = tm_profile_getter
        self.transport_factory = transport_factory
        self.party_reader_factory = party_reader_factory
        self.inventory_reader_factory = inventory_reader_factory
        self.money_reader_factory = money_reader_factory
        self.battle_reader_factory = battle_reader_factory
        self.box_reader_factory = box_reader_factory

    @staticmethod
    def _identity(pokemon: BDSPPartyPokemon) -> str:
        return (
            f"{int(pokemon.species_id)}:{int(pokemon.pid)}:"
            f"{int(pokemon.tid)}:{int(pokemon.sid)}"
        )

    @staticmethod
    def _role_from_plain(plain: bytes | bytearray) -> str:
        value = int(struct.unpack_from("<H", plain, 0x18)[0])
        markings = [bool(value & (0b11 << (index * 2))) for index in range(6)]
        return role_from_markings(markings, layout=2)[0]

    @staticmethod
    def _set_role(plain: bytearray, role: str) -> None:
        normalized = canonical_role(role)
        try:
            selected = int(ROLE_TO_MARKING[normalized])
        except KeyError as exc:
            raise BDSPLiveError(
                f"El rol '{role}' no es válido para BDSP en vivo."
            ) from exc
        value = int(struct.unpack_from("<H", plain, 0x18)[0]) & 0xF000
        if selected >= 0:
            value |= 0b01 << (selected * 2)
        struct.pack_into("<H", plain, 0x18, value)

    @staticmethod
    def _set_move(
        plain: bytearray,
        change: PendingChange | PendingTMTeach,
        *,
        base_pp: int,
    ) -> None:
        index = int(change.move_slot) - 1
        if not 0 <= index < 4:
            raise BDSPLiveError(
                f"El hueco de movimiento {change.move_slot} no es válido para BDSP."
            )
        current = int(struct.unpack_from("<H", plain, 0x72 + index * 2)[0])
        if current != int(change.old_move_id or 0):
            raise BDSPLiveError(
                f"{change.pokemon} cambió ese movimiento dentro del juego "
                f"({current} != {int(change.old_move_id or 0)}). Vuelve a abrir el selector."
            )
        move_id = int(change.new_move_id or 0)
        if move_id == 0:
            # CoreParam.RemoveWaza/CloseUpWazaPos se representa compactando los
            # tres campos paralelos: movimiento, PP y PP Ups.
            for target in range(index, 3):
                source = target + 1
                struct.pack_into(
                    "<H", plain, 0x72 + target * 2,
                    struct.unpack_from("<H", plain, 0x72 + source * 2)[0],
                )
                plain[0x7A + target] = plain[0x7A + source]
                plain[0x7E + target] = plain[0x7E + source]
            struct.pack_into("<H", plain, 0x72 + 3 * 2, 0)
            plain[0x7A + 3] = 0
            plain[0x7E + 3] = 0
            return
        if not 1 <= int(base_pp) <= 255:
            raise BDSPLiveError(
                f"WazaTable no demuestra los PP base del movimiento #{move_id}."
            )
        # OpenDPR CoreParam.SetWaza: SetWazaNo, PP Ups=0, PP=basePP.
        struct.pack_into("<H", plain, 0x72 + index * 2, move_id)
        plain[0x7E + index] = 0
        plain[0x7A + index] = int(base_pp)

    @staticmethod
    def _stable_guest(client: RyujinxHostMappedClient, address: int, size: int, label: str) -> bytes:
        first = client.read_memory(int(address), int(size))
        second = client.read_memory(int(address), int(size))
        if first != second:
            raise BDSPLiveError(f"{label} cambió durante la precondición.")
        return second

    @staticmethod
    def _same_party(first: BDSPPartyRead, second: BDSPPartyRead) -> bool:
        return (
            int(first.party_object) == int(second.party_object)
            and int(first.member_array) == int(second.member_array)
            and int(first.member_count) == int(second.member_count)
            and int(first.member_count_address) == int(second.member_count_address)
            and tuple(first.storage_slots) == tuple(second.storage_slots)
            and tuple(
                (BDSPLiveWriter._identity(pokemon), int(pokemon.core_data_pointer), bytes(pokemon.encrypted))
                for pokemon in first.pokemon
            ) == tuple(
                (BDSPLiveWriter._identity(pokemon), int(pokemon.core_data_pointer), bytes(pokemon.encrypted))
                for pokemon in second.pokemon
            )
        )

    @staticmethod
    def _same_box(first: BDSPBoxRead, second: BDSPBoxRead) -> bool:
        return (
            int(first.pointer_base) == int(second.pointer_base)
            and int(first.total_slots) == int(second.total_slots) == BDSP_BOX_COUNT * BDSP_BOX_SLOT_COUNT
            and tuple(first.storage_slots) == tuple(second.storage_slots)
            and tuple(
                (
                    int(pokemon.box), int(pokemon.slot),
                    BDSPLiveWriter._identity(pokemon), int(pokemon.data_pointer),
                    bytes(pokemon.encrypted),
                )
                for pokemon in first.pokemon
            ) == tuple(
                (
                    int(pokemon.box), int(pokemon.slot),
                    BDSPLiveWriter._identity(pokemon), int(pokemon.data_pointer),
                    bytes(pokemon.encrypted),
                )
                for pokemon in second.pokemon
            )
        )

    @staticmethod
    def _empty_pb8() -> bytes:
        """PB8 vacío observado en party y caja durante 6→5→6 físico."""
        return encrypt_pb8(bytes(PB8_PARTY_SIZE))

    @staticmethod
    def _party_storage(raw: BDSPPartyRead, slot: int) -> BDSPPartyStorageSlot:
        matches = [item for item in raw.storage_slots if int(item.slot) == int(slot)]
        if len(matches) != 1:
            raise BDSPLiveError(
                f"PokeParty no conserva un único objeto runtime para el slot {slot}.",
            )
        return matches[0]

    @staticmethod
    def _box_storage(
        raw: BDSPBoxRead, box: int, slot: int,
    ) -> BDSPBoxStorageSlot:
        matches = [
            item for item in raw.storage_slots
            if (int(item.box), int(item.slot)) == (int(box), int(slot))
        ]
        if len(matches) != 1:
            raise BDSPLiveError(
                f"La matriz viva no conserva un único slot Caja {box}:{slot}.",
            )
        return matches[0]

    @staticmethod
    def _box_unchanged_except(
        before: BDSPBoxRead, after: BDSPBoxRead,
        changed: tuple[int, int] | set[tuple[int, int]],
    ) -> bool:
        changed_positions = (
            {changed}
            if isinstance(changed, tuple) and len(changed) == 2
            and all(isinstance(value, int) for value in changed)
            else set(changed)
        )

        def rows(raw: BDSPBoxRead):
            return tuple(
                (int(item.box), int(item.slot), int(item.data_pointer), bytes(item.encrypted))
                for item in raw.storage_slots
                if (int(item.box), int(item.slot)) not in changed_positions
            )
        return (
            int(before.pointer_base) == int(after.pointer_base)
            and int(before.total_slots) == int(after.total_slots)
            and rows(before) == rows(after)
        )

    def _apply_party_box_resize(self, change: PendingTeamChange) -> BDSPWriteReceipt:
        """Aplica el contrato de tamaño y compactación demostrado físicamente.

        Alpha.82 demostró la cola 5↔6. Alpha.83 añade la retirada intermedia:
        cada objeto fijo recibe literalmente los 344 bytes del siguiente, el
        último recibe el vacío canónico y el contador se escribe al final.
        """
        if change.operation not in {"party-to-box", "box-to-party"}:
            raise BDSPLiveError("La operación no pertenece al writer de tamaño BDSP.")
        if self.battle_reader_factory(self.client).read() is not None:
            raise BDSPLiveError("No se cambia el tamaño del equipo durante un combate de BDSP.")

        first_party = self.party_reader_factory(self.client).read()
        second_party = self.party_reader_factory(self.client).read()
        if not self._same_party(first_party, second_party):
            raise BDSPLiveError("La party cambió entre las dos capturas completas.")
        first_box = self.box_reader_factory(self.client).read()
        second_box = self.box_reader_factory(self.client).read()
        if not self._same_box(first_box, second_box):
            raise BDSPLiveError("Las cajas cambiaron entre las dos capturas completas.")
        if len(second_party.storage_slots) != 6 or len(second_box.storage_slots) != 1200:
            raise BDSPLiveError(
                "La captura no conserva los seis objetos de party y los 1.200 slots de caja.",
            )
        count = int(second_party.member_count)
        if int(second_party.member_count_address) != int(second_party.party_object) + 0x18:
            raise BDSPLiveError("La dirección runtime del contador de party no coincide.")
        occupied_slots = [int(pokemon.slot) for pokemon in second_party.pokemon]
        if occupied_slots != list(range(1, int(second_party.member_count) + 1)):
            raise BDSPLiveError("La party viva no es compacta o su contador no coincide.")

        empty = self._empty_pb8()
        changed_box: tuple[int, int]
        destinations: tuple[tuple[int, bytes, bytes, str], ...]
        incoming_identity = ""
        outgoing_identity = ""

        if change.operation == "party-to-box":
            if count <= 1:
                raise BDSPLiveError("BDSP no permite dejar el equipo completamente vacío.")
            removed_slot = int(change.party_slot)
            if not 1 <= removed_slot <= count:
                raise BDSPLiveError("El miembro que sale ya no ocupa un slot activo de la party.")
            for pokemon in second_party.pokemon:
                storage = self._party_storage(second_party, int(pokemon.slot))
                if bytes(storage.encrypted) != bytes(pokemon.encrypted):
                    raise BDSPLiveError(
                        f"El almacenamiento del slot {pokemon.slot} no coincide con el miembro activo.",
                    )
            outgoing_matches = [
                pokemon for pokemon in second_party.pokemon
                if int(pokemon.slot) == removed_slot
                and self._identity(pokemon) == str(change.outgoing_identity or "")
            ]
            if len(outgoing_matches) != 1:
                raise BDSPLiveError("El miembro que sale ya no coincide con la selección.")
            outgoing = outgoing_matches[0]
            outgoing_identity = self._identity(outgoing)

            if change.box is None or change.box_slot is None:
                empty_slots = [
                    item for item in second_box.storage_slots
                    if parse_bdsp_box_pokemon(
                        item.encrypted, box=int(item.box), slot=int(item.slot),
                    ) is None
                ]
                if not empty_slots:
                    raise BDSPLiveError("Las cajas BDSP no tienen ningún hueco libre.")
                destination = empty_slots[0]
                change.box, change.box_slot = int(destination.box), int(destination.slot)
            else:
                destination = self._box_storage(
                    second_box, int(change.box), int(change.box_slot),
                )
                if parse_bdsp_box_pokemon(
                    destination.encrypted,
                    box=int(destination.box), slot=int(destination.slot),
                ) is not None:
                    raise BDSPLiveError("El destino de caja elegido ya no está vacío.")
            changed_box = (int(destination.box), int(destination.slot))
            writes: list[tuple[int, bytes, bytes, str]] = [
                (int(destination.data_pointer), bytes(destination.encrypted), bytes(outgoing.encrypted), "caja destino"),
            ]
            for target_slot in range(removed_slot, count):
                target = self._party_storage(second_party, target_slot)
                source = self._party_storage(second_party, target_slot + 1)
                writes.extend((
                    (
                        int(target.core_data_pointer),
                        bytes(target.encrypted[:PB8_STORED_SIZE]),
                        bytes(source.encrypted[:PB8_STORED_SIZE]),
                        f"party core {target_slot}←{target_slot + 1}",
                    ),
                    (
                        int(target.calc_data_pointer),
                        bytes(target.encrypted[PB8_STORED_SIZE:]),
                        bytes(source.encrypted[PB8_STORED_SIZE:]),
                        f"party calc {target_slot}←{target_slot + 1}",
                    ),
                ))
            last_storage = self._party_storage(second_party, count)
            writes.extend((
                (
                    int(last_storage.core_data_pointer),
                    bytes(last_storage.encrypted[:PB8_STORED_SIZE]),
                    empty[:PB8_STORED_SIZE],
                    "party core final vacío",
                ),
                (
                    int(last_storage.calc_data_pointer),
                    bytes(last_storage.encrypted[PB8_STORED_SIZE:]),
                    empty[PB8_STORED_SIZE:],
                    "party calc final vacío",
                ),
                (
                    int(second_party.member_count_address),
                    struct.pack("<I", count),
                    struct.pack("<I", count - 1),
                    "contador de party",
                ),
            ))
            destinations = tuple(writes)
            expected_count = count - 1
        else:
            if count >= 6:
                raise BDSPLiveError("El equipo BDSP ya tiene seis miembros.")
            if change.box is None or change.box_slot is None:
                raise BDSPLiveError("La incorporación BDSP no identifica su slot de caja.")
            if int(change.party_slot) != count + 1:
                raise BDSPLiveError("El nuevo miembro debe ocupar exactamente el siguiente slot de party.")
            incoming_matches = [
                pokemon for pokemon in second_box.pokemon
                if (int(pokemon.box), int(pokemon.slot)) == (
                    int(change.box), int(change.box_slot),
                )
                and self._identity(pokemon) == str(change.incoming_identity or "")
            ]
            if len(incoming_matches) != 1:
                raise BDSPLiveError("El Pokémon de caja ya no coincide con la selección.")
            incoming = incoming_matches[0]
            incoming_identity = self._identity(incoming)
            source = self._box_storage(second_box, int(change.box), int(change.box_slot))
            party_storage = self._party_storage(second_party, count + 1)
            if bytes(party_storage.encrypted) != empty:
                raise BDSPLiveError("El siguiente objeto de party no contiene el vacío canónico demostrado.")
            desired_plain = bytearray(decrypt_pb8(incoming.encrypted))
            self._set_role(desired_plain, change.incoming_role)
            refresh_pb8_checksum(desired_plain)
            desired_party = encrypt_pb8(bytes(desired_plain))
            parsed = parse_bdsp_party_pokemon(desired_party, slot=count + 1)
            if self._identity(parsed) != incoming_identity:
                raise BDSPLiveError("La preparación de la entrada alteró su identidad.")
            changed_box = (int(change.box), int(change.box_slot))
            destinations = (
                (int(party_storage.core_data_pointer), empty[:PB8_STORED_SIZE], desired_party[:PB8_STORED_SIZE], "party core entrante"),
                (int(party_storage.calc_data_pointer), empty[PB8_STORED_SIZE:], desired_party[PB8_STORED_SIZE:], "party calc entrante"),
                (int(source.data_pointer), bytes(source.encrypted), empty, "caja origen"),
                (int(second_party.member_count_address), struct.pack("<I", count), struct.pack("<I", count + 1), "contador de party"),
            )
            expected_count = count + 1

        session = self.client.session
        if self.client.read_memory(
            int(session.profile.guest_main), len(session.profile.main_witness),
        ) != session.profile.main_witness:
            raise BDSPLiveError("La huella principal de Ryujinx cambió antes de escribir.")
        transport = self.transport_factory()
        handle = None
        attempted: list[tuple[int, bytes, str]] = []
        try:
            handle = transport.open(int(session.process.pid))
            delta = int(session.guest_to_host_delta)
            for guest, original, desired, label in destinations:
                host = guest + delta
                transport.assert_writable(handle, host, len(desired))
                if self._stable_guest(
                    self.client, guest, len(original), f"La precondición {label}",
                ) != original:
                    raise BDSPLiveError(f"La precondición guest de {label} cambió.")
                if transport.read(handle, host, len(original)) != original:
                    raise BDSPLiveError(f"La precondición host de {label} no coincide.")
            for guest, original, desired, label in destinations:
                host = guest + delta
                attempted.append((host, original, label))
                transport.write(handle, host, desired)
                if (
                    transport.read(handle, host, len(desired)) != desired
                    or self.client.read_memory(guest, len(desired)) != desired
                ):
                    raise BDSPLiveError(f"El readback de {label} falló.")

            verified_party = self.party_reader_factory(self.client).read()
            verified_box = self.box_reader_factory(self.client).read()
            if int(verified_party.member_count) != expected_count:
                raise BDSPLiveError("La verificación semántica del contador falló.")
            if not self._box_unchanged_except(second_box, verified_box, changed_box):
                raise BDSPLiveError("Un slot de caja no implicado cambió durante la operación.")
            verified_storage = self._party_storage(
                verified_party, count if change.operation == "party-to-box" else count + 1,
            )
            verified_box_storage = self._box_storage(
                verified_box, changed_box[0], changed_box[1],
            )
            if change.operation == "party-to-box":
                if bytes(verified_storage.encrypted) != empty:
                    raise BDSPLiveError("El último objeto no quedó con el vacío canónico.")
                boxed = parse_bdsp_box_pokemon(
                    verified_box_storage.encrypted,
                    box=changed_box[0], slot=changed_box[1],
                )
                if boxed is None or self._identity(boxed) != outgoing_identity:
                    raise BDSPLiveError("La verificación perdió el Pokémon depositado.")
                expected_storage = [
                    bytes(item.encrypted) for item in second_party.storage_slots
                ]
                del expected_storage[removed_slot - 1]
                expected_storage.append(empty)
                actual_storage = [
                    bytes(item.encrypted) for item in verified_party.storage_slots
                ]
                if actual_storage != expected_storage:
                    raise BDSPLiveError("La compactación no reprodujo los 344 bytes esperados por slot.")
                before_ids = tuple(
                    self._identity(item) for item in second_party.pokemon
                    if int(item.slot) != removed_slot
                )
                after_ids = tuple(self._identity(item) for item in verified_party.pokemon)
                if before_ids != after_ids:
                    raise BDSPLiveError("Los miembros no implicados cambiaron al reducir la party.")
            else:
                if parse_bdsp_box_pokemon(
                    verified_box_storage.encrypted,
                    box=changed_box[0], slot=changed_box[1],
                ) is not None or bytes(verified_box_storage.encrypted) != empty:
                    raise BDSPLiveError("La caja origen no quedó con el vacío canónico.")
                entered = verified_party.pokemon[-1]
                if self._identity(entered) != incoming_identity:
                    raise BDSPLiveError("La verificación perdió el Pokémon incorporado.")
                if role_from_markings(entered.markings, layout=2)[0] != canonical_role(change.incoming_role):
                    raise BDSPLiveError("La verificación del rol asignado falló.")
                before_ids = tuple(self._identity(item) for item in second_party.pokemon)
                after_ids = tuple(self._identity(item) for item in verified_party.pokemon[:-1])
                if before_ids != after_ids:
                    raise BDSPLiveError("Los miembros no implicados cambiaron al ampliar la party.")
            inventory = self.inventory_reader_factory(self.client).read()
            return BDSPWriteReceipt(
                party=verified_party, inventory=inventory, process=session.process,
                attempts=2, applied_count=1,
                memory_watches=tuple(
                    BDSPWriteMemoryWatch(guest, desired)
                    for guest, _old, desired, _label in destinations
                ),
            )
        except Exception as exc:
            rollback_errors: list[str] = []
            if handle is not None:
                for host, original, label in reversed(attempted):
                    try:
                        transport.write(handle, host, original)
                        if transport.read(handle, host, len(original)) != original:
                            rollback_errors.append(f"{label}: readback host distinto")
                    except Exception as rollback_exc:
                        rollback_errors.append(f"{label}: {rollback_exc}")
            if attempted and not rollback_errors:
                delta = int(session.guest_to_host_delta)
                for host, original, label in attempted:
                    if self.client.read_memory(int(host) - delta, len(original)) != original:
                        rollback_errors.append(f"{label}: readback guest distinto")
            if rollback_errors:
                raise BDSPLiveError(
                    f"Falló el cambio de tamaño y también su rollback: {'; '.join(rollback_errors)}",
                ) from exc
            if attempted:
                raise BDSPLiveError(
                    f"Falló el cambio de tamaño; RoleRun restauró y verificó "
                    f"los {len(destinations)} bloques. Causa: {exc}",
                ) from exc
            raise
        finally:
            if handle is not None:
                transport.close(handle)

    def _apply_faint_replacement(self, change: PendingTeamChange) -> BDSPWriteReceipt:
        """Sustituye una baja sin cambiar el tamaño ni el orden de la party.

        Esta transacción compone únicamente unidades ya demostradas en BDSP:
        PB8 completo de caja (344 bytes) y el mismo PB8 dividido en core(328) +
        calc(16) dentro del objeto fijo de party. El origen del sustituto queda
        con el vacío canónico observado y el debilitado se conserva byte a byte
        en el hueco vacío elegido del Cementerio.
        """
        if change.operation != "replace-fainted":
            raise BDSPLiveError("La operación no pertenece al writer de sustitución por baja BDSP.")
        if change.box is None or change.box_slot is None:
            raise BDSPLiveError("La sustitución no identifica el origen PC del sustituto.")
        if change.graveyard_box is None or change.graveyard_box_slot is None:
            raise BDSPLiveError("La sustitución no identifica un destino de Cementerio.")
        source_pos = (int(change.box), int(change.box_slot))
        grave_pos = (int(change.graveyard_box), int(change.graveyard_box_slot))
        if source_pos == grave_pos:
            raise BDSPLiveError("El sustituto y el Cementerio no pueden usar el mismo slot de caja.")
        if self.battle_reader_factory(self.client).read() is not None:
            raise BDSPLiveError("No se sustituye una baja durante un combate de BDSP.")

        first_party = self.party_reader_factory(self.client).read()
        second_party = self.party_reader_factory(self.client).read()
        if not self._same_party(first_party, second_party):
            raise BDSPLiveError("La party cambió entre las dos capturas completas.")
        first_box = self.box_reader_factory(self.client).read()
        second_box = self.box_reader_factory(self.client).read()
        if not self._same_box(first_box, second_box):
            raise BDSPLiveError("Las cajas cambiaron entre las dos capturas completas.")
        if len(second_party.storage_slots) != 6 or len(second_box.storage_slots) != 1200:
            raise BDSPLiveError(
                "La captura no conserva los seis objetos de party y los 1.200 slots de caja.",
            )
        if int(second_party.member_count_address) != int(second_party.party_object) + 0x18:
            raise BDSPLiveError("La dirección runtime del contador de party no coincide.")
        for pokemon in second_party.pokemon:
            storage = self._party_storage(second_party, int(pokemon.slot))
            if bytes(storage.encrypted) != bytes(pokemon.encrypted):
                raise BDSPLiveError(
                    f"El almacenamiento del slot {pokemon.slot} no coincide con el miembro activo.",
                )

        party_matches = [
            pokemon for pokemon in second_party.pokemon
            if int(pokemon.slot) == int(change.party_slot)
            and self._identity(pokemon) == str(change.outgoing_identity or "")
        ]
        incoming_matches = [
            pokemon for pokemon in second_box.pokemon
            if (int(pokemon.box), int(pokemon.slot)) == source_pos
            and self._identity(pokemon) == str(change.incoming_identity or "")
        ]
        if len(party_matches) != 1:
            raise BDSPLiveError("El Pokémon debilitado ya no coincide con la baja pendiente.")
        if len(incoming_matches) != 1:
            raise BDSPLiveError("El sustituto ya no coincide con el slot PC elegido.")
        outgoing, incoming = party_matches[0], incoming_matches[0]
        if int(outgoing.current_hp) != 0:
            raise BDSPLiveError(
                "El Pokémon pendiente ya no está debilitado; no se escribió ningún byte.",
            )
        result_role = canonical_role(role_from_markings(outgoing.markings, layout=2)[0])
        if result_role not in ROLE_ORDER:
            raise BDSPLiveError(
                "El Pokémon debilitado no conserva un único rol válido; sincroniza antes de sustituirlo.",
            )

        party_storage = self._party_storage(second_party, int(change.party_slot))
        source_storage = self._box_storage(second_box, *source_pos)
        grave_storage = self._box_storage(second_box, *grave_pos)
        if min(
            int(party_storage.core_data_pointer), int(party_storage.calc_data_pointer),
            int(source_storage.data_pointer), int(grave_storage.data_pointer),
        ) <= 0:
            raise BDSPLiveError("Una región de la sustitución no conserva una dirección válida.")
        if bytes(party_storage.encrypted) != bytes(outgoing.encrypted):
            raise BDSPLiveError("El objeto fijo de party no coincide con el Pokémon debilitado.")
        if bytes(source_storage.encrypted) != bytes(incoming.encrypted):
            raise BDSPLiveError("El bloque PC origen no coincide con el sustituto validado.")
        if parse_bdsp_box_pokemon(
            grave_storage.encrypted, box=grave_pos[0], slot=grave_pos[1],
        ) is not None:
            raise BDSPLiveError(
                f"La Caja {grave_pos[0]}, hueco {grave_pos[1]} del Cementerio ya no está vacía.",
            )

        incoming_plain = bytearray(decrypt_pb8(incoming.encrypted))
        self._set_role(incoming_plain, result_role)
        refresh_pb8_checksum(incoming_plain)
        desired_party = encrypt_pb8(bytes(incoming_plain))
        desired_source = self._empty_pb8()
        desired_grave = bytes(outgoing.encrypted)
        prepared_party = parse_bdsp_party_pokemon(
            desired_party, slot=int(change.party_slot),
        )
        prepared_grave = parse_bdsp_box_pokemon(
            desired_grave, box=grave_pos[0], slot=grave_pos[1],
        )
        incoming_identity = self._identity(incoming)
        outgoing_identity = self._identity(outgoing)
        if self._identity(prepared_party) != incoming_identity:
            raise BDSPLiveError("La preparación del sustituto alteró su identidad.")
        if prepared_grave is None or self._identity(prepared_grave) != outgoing_identity:
            raise BDSPLiveError("La preparación del Cementerio alteró la identidad del debilitado.")
        if role_from_markings(prepared_party.markings, layout=2)[0] != result_role:
            raise BDSPLiveError("La preparación no asignó al sustituto el rol heredado.")

        destinations = (
            (int(source_storage.data_pointer), bytes(source_storage.encrypted), desired_source, "PC sustituto"),
            (int(grave_storage.data_pointer), bytes(grave_storage.encrypted), desired_grave, "PC Cementerio"),
            (int(party_storage.core_data_pointer), bytes(outgoing.encrypted[:PB8_STORED_SIZE]), desired_party[:PB8_STORED_SIZE], "party core"),
            (int(party_storage.calc_data_pointer), bytes(outgoing.encrypted[PB8_STORED_SIZE:]), desired_party[PB8_STORED_SIZE:], "party calc"),
        )
        ranges = sorted((address, address + len(desired), label) for address, _old, desired, label in destinations)
        if any(left_end > right_start for (_left, left_end, _label), (right_start, _right, _other) in zip(ranges, ranges[1:])):
            raise BDSPLiveError("Las cuatro regiones de la sustitución se solapan inesperadamente.")

        session = self.client.session
        if self.client.read_memory(
            int(session.profile.guest_main), len(session.profile.main_witness),
        ) != session.profile.main_witness:
            raise BDSPLiveError("La huella principal de Ryujinx cambió antes de escribir.")
        transport = self.transport_factory()
        handle = None
        attempted: list[tuple[int, bytes, str]] = []
        try:
            handle = transport.open(int(session.process.pid))
            delta = int(session.guest_to_host_delta)
            for guest, original, desired, label in destinations:
                host = guest + delta
                transport.assert_writable(handle, host, len(desired))
                if self._stable_guest(
                    self.client, guest, len(original), f"La precondición {label}",
                ) != original:
                    raise BDSPLiveError(f"La precondición guest de {label} cambió.")
                if transport.read(handle, host, len(original)) != original:
                    raise BDSPLiveError(f"La precondición host de {label} no coincide.")
            for guest, original, desired, label in destinations:
                host = guest + delta
                attempted.append((host, original, label))
                transport.write(handle, host, desired)
                if (
                    transport.read(handle, host, len(desired)) != desired
                    or self.client.read_memory(guest, len(desired)) != desired
                ):
                    raise BDSPLiveError(f"El readback de {label} falló.")

            verified_party = self.party_reader_factory(self.client).read()
            verified_box = self.box_reader_factory(self.client).read()
            if (
                int(verified_party.member_count) != int(second_party.member_count)
                or int(verified_party.party_object) != int(second_party.party_object)
                or int(verified_party.member_array) != int(second_party.member_array)
                or int(verified_party.member_count_address) != int(second_party.member_count_address)
                or tuple(
                    (
                        int(item.slot), int(item.pokemon_param_pointer),
                        int(item.core_data_pointer), int(item.calc_data_pointer),
                    )
                    for item in verified_party.storage_slots
                ) != tuple(
                    (
                        int(item.slot), int(item.pokemon_param_pointer),
                        int(item.core_data_pointer), int(item.calc_data_pointer),
                    )
                    for item in second_party.storage_slots
                )
            ):
                raise BDSPLiveError("La estructura o el tamaño de party cambió durante la sustitución.")
            expected_party_storage = [bytes(item.encrypted) for item in second_party.storage_slots]
            expected_party_storage[int(change.party_slot) - 1] = desired_party
            if [bytes(item.encrypted) for item in verified_party.storage_slots] != expected_party_storage:
                raise BDSPLiveError("Un objeto de party no implicado cambió durante la sustitución.")
            expected_ids = [self._identity(item) for item in second_party.pokemon]
            expected_ids[int(change.party_slot) - 1] = incoming_identity
            if [self._identity(item) for item in verified_party.pokemon] != expected_ids:
                raise BDSPLiveError("La composición final de la party no coincide con la sustitución.")
            verified_incoming = verified_party.pokemon[int(change.party_slot) - 1]
            if role_from_markings(verified_incoming.markings, layout=2)[0] != result_role:
                raise BDSPLiveError("La verificación semántica del rol heredado falló.")
            if not self._box_unchanged_except(second_box, verified_box, {source_pos, grave_pos}):
                raise BDSPLiveError("Un slot PC no implicado cambió durante la sustitución.")
            verified_source = self._box_storage(verified_box, *source_pos)
            verified_grave = self._box_storage(verified_box, *grave_pos)
            if (
                int(verified_source.data_pointer) != int(source_storage.data_pointer)
                or int(verified_grave.data_pointer) != int(grave_storage.data_pointer)
            ):
                raise BDSPLiveError("Las direcciones PC cambiaron durante la sustitución.")
            if (
                bytes(verified_source.encrypted) != desired_source
                or parse_bdsp_box_pokemon(
                    verified_source.encrypted, box=source_pos[0], slot=source_pos[1],
                ) is not None
            ):
                raise BDSPLiveError("El hueco origen del sustituto no quedó vacío.")
            grave_mon = parse_bdsp_box_pokemon(
                verified_grave.encrypted, box=grave_pos[0], slot=grave_pos[1],
            )
            if (
                bytes(verified_grave.encrypted) != desired_grave
                or grave_mon is None
                or self._identity(grave_mon) != outgoing_identity
            ):
                raise BDSPLiveError("El Cementerio no confirmó al Pokémon debilitado exacto.")

            inventory = self.inventory_reader_factory(self.client).read()
            change.incoming_role = result_role
            return BDSPWriteReceipt(
                party=verified_party, inventory=inventory, process=session.process,
                attempts=2, applied_count=1,
                memory_watches=tuple(
                    BDSPWriteMemoryWatch(guest, desired)
                    for guest, _old, desired, _label in destinations
                ),
            )
        except Exception as exc:
            rollback_errors: list[str] = []
            if handle is not None:
                for host, original, label in reversed(attempted):
                    try:
                        transport.write(handle, host, original)
                        if transport.read(handle, host, len(original)) != original:
                            rollback_errors.append(f"{label}: readback host distinto")
                    except Exception as rollback_exc:
                        rollback_errors.append(f"{label}: {rollback_exc}")
            if attempted and not rollback_errors:
                delta = int(session.guest_to_host_delta)
                for host, original, label in attempted:
                    if self.client.read_memory(int(host) - delta, len(original)) != original:
                        rollback_errors.append(f"{label}: readback guest distinto")
            if rollback_errors:
                raise BDSPLiveError(
                    "Falló la sustitución por baja y también su rollback: "
                    + "; ".join(rollback_errors),
                ) from exc
            if attempted:
                raise BDSPLiveError(
                    "Falló la sustitución por baja; RoleRun restauró y verificó "
                    f"los {len(destinations)} bloques. Causa: {exc}",
                ) from exc
            raise
        finally:
            if handle is not None:
                transport.close(handle)

    def _apply_party_box_swap(self, change: PendingTeamChange) -> BDSPWriteReceipt:
        if change.operation != "swap-party-box":
            raise BDSPLiveError(
                "BDSP solo tiene demostrada la sustitución 1↔1; los cambios de tamaño siguen bloqueados."
            )
        if change.box is None or change.box_slot is None:
            raise BDSPLiveError("El intercambio BDSP no identifica un slot de caja.")
        if self.battle_reader_factory(self.client).read() is not None:
            raise BDSPLiveError("No se intercambia Equipo↔PC durante un combate de BDSP.")

        first_party = self.party_reader_factory(self.client).read()
        second_party = self.party_reader_factory(self.client).read()
        if not self._same_party(first_party, second_party):
            raise BDSPLiveError("La party cambió entre las dos capturas completas.")
        first_box = self.box_reader_factory(self.client).read()
        second_box = self.box_reader_factory(self.client).read()
        if not self._same_box(first_box, second_box):
            raise BDSPLiveError("Las cajas cambiaron entre las dos capturas completas.")

        party_matches = [
            pokemon for pokemon in second_party.pokemon
            if int(pokemon.slot) == int(change.party_slot)
            and self._identity(pokemon) == str(change.outgoing_identity or "")
        ]
        box_matches = [
            pokemon for pokemon in second_box.pokemon
            if (int(pokemon.box), int(pokemon.slot)) == (int(change.box), int(change.box_slot))
            and self._identity(pokemon) == str(change.incoming_identity or "")
        ]
        if len(party_matches) != 1 or len(box_matches) != 1:
            raise BDSPLiveError(
                "Las identidades vivas de Equipo/PC ya no coinciden con la selección. Vuelve a abrir Cajas PC."
            )
        outgoing, incoming = party_matches[0], box_matches[0]
        if int(outgoing.core_data_pointer) <= 0 or int(outgoing.calc_data_pointer) <= 0:
            raise BDSPLiveError("El miembro de la party no conserva sus dos bloques PB8.")
        if int(incoming.data_pointer) <= 0:
            raise BDSPLiveError("El slot de caja no conserva su bloque PB8 completo.")

        incoming_plain = bytearray(decrypt_pb8(incoming.encrypted))
        self._set_role(incoming_plain, change.incoming_role)
        refresh_pb8_checksum(incoming_plain)
        desired_party = encrypt_pb8(bytes(incoming_plain))
        desired_box = bytes(outgoing.encrypted)
        # SerializedPokemonFull, PokemonParam.DATASIZE y CopyFrom demuestran que
        # el movimiento del juego usa los 344 bytes completos. La party los
        # conserva en arrays core(328)+calc(16); la caja, en un único byte[344].
        parsed_party = parse_bdsp_party_pokemon(desired_party, slot=int(change.party_slot))
        parsed_box = parse_bdsp_box_pokemon(desired_box, box=int(change.box), slot=int(change.box_slot))
        if parsed_box is None or self._identity(parsed_party) != self._identity(incoming):
            raise BDSPLiveError("La preparación del intercambio alteró la identidad entrante.")
        if self._identity(parsed_box) != self._identity(outgoing):
            raise BDSPLiveError("La preparación del intercambio alteró la identidad saliente.")

        destinations = (
            (int(outgoing.core_data_pointer), bytes(outgoing.encrypted[:PB8_STORED_SIZE]), desired_party[:PB8_STORED_SIZE], "party core"),
            (int(outgoing.calc_data_pointer), bytes(outgoing.encrypted[PB8_STORED_SIZE:]), desired_party[PB8_STORED_SIZE:], "party calc"),
            (int(incoming.data_pointer), bytes(incoming.encrypted), desired_box, "caja PB8"),
        )
        session = self.client.session
        if self.client.read_memory(int(session.profile.guest_main), len(session.profile.main_witness)) != session.profile.main_witness:
            raise BDSPLiveError("La huella principal de Ryujinx cambió antes de escribir.")
        transport = self.transport_factory()
        handle = None
        attempted: list[tuple[int, bytes, str]] = []
        try:
            handle = transport.open(int(session.process.pid))
            delta = int(session.guest_to_host_delta)
            for guest, original, desired, label in destinations:
                host = guest + delta
                transport.assert_writable(handle, host, len(desired))
                if self._stable_guest(self.client, guest, len(original), f"La precondición {label}") != original:
                    raise BDSPLiveError(f"La precondición guest de {label} cambió.")
                if transport.read(handle, host, len(original)) != original:
                    raise BDSPLiveError(f"La precondición host de {label} no coincide.")
            for guest, original, desired, label in destinations:
                host = guest + delta
                attempted.append((host, original, label))
                transport.write(handle, host, desired)
                if transport.read(handle, host, len(desired)) != desired or self.client.read_memory(guest, len(desired)) != desired:
                    raise BDSPLiveError(f"El readback de {label} falló.")

            verified_party = self.party_reader_factory(self.client).read()
            verified_box = self.box_reader_factory(self.client).read()
            verified_party_mon = next((p for p in verified_party.pokemon if int(p.slot) == int(change.party_slot)), None)
            verified_box_mon = next((p for p in verified_box.pokemon if (int(p.box), int(p.slot)) == (int(change.box), int(change.box_slot))), None)
            if verified_party_mon is None or self._identity(verified_party_mon) != self._identity(incoming):
                raise BDSPLiveError("La verificación semántica perdió el Pokémon entrante.")
            if verified_box_mon is None or self._identity(verified_box_mon) != self._identity(outgoing):
                raise BDSPLiveError("La verificación semántica perdió el Pokémon saliente.")
            if role_from_markings(verified_party_mon.markings, layout=2)[0] != canonical_role(change.incoming_role):
                raise BDSPLiveError("La verificación semántica del rol heredado falló.")
            inventory = self.inventory_reader_factory(self.client).read()
            return BDSPWriteReceipt(
                party=verified_party, inventory=inventory, process=session.process,
                attempts=2, applied_count=1,
                memory_watches=tuple(BDSPWriteMemoryWatch(guest, desired) for guest, _old, desired, _label in destinations),
            )
        except Exception as exc:
            rollback_errors: list[str] = []
            if handle is not None:
                for host, original, label in reversed(attempted):
                    try:
                        transport.write(handle, host, original)
                        if transport.read(handle, host, len(original)) != original:
                            rollback_errors.append(f"{label}: readback host distinto")
                    except Exception as rollback_exc:
                        rollback_errors.append(f"{label}: {rollback_exc}")
            if attempted and not rollback_errors:
                delta = int(session.guest_to_host_delta)
                for host, original, label in attempted:
                    if self.client.read_memory(int(host) - delta, len(original)) != original:
                        rollback_errors.append(f"{label}: readback guest distinto")
            if rollback_errors:
                raise BDSPLiveError(f"Falló el intercambio y también su rollback: {'; '.join(rollback_errors)}") from exc
            if attempted:
                raise BDSPLiveError(f"Falló el intercambio; RoleRun restauró y verificó los tres bloques. Causa: {exc}") from exc
            raise
        finally:
            if handle is not None:
                transport.close(handle)

    def _apply_inventory_utilities(
        self, changes: Sequence[PendingInventoryChange],
    ) -> BDSPWriteReceipt:
        """Aplica objetos/dinero sin reconstruir ningún campo desconocido."""
        if not changes:
            raise BDSPLiveError("No hay utilidades BDSP que aplicar.")
        keys = [str(change.item_key) for change in changes]
        if len(set(keys)) != len(keys):
            raise BDSPLiveError("La misma utilidad BDSP aparece dos veces en la transacción.")
        for change in changes:
            if change.item_key in BDSP_UTILITY_ITEM_IDS:
                if not 0 <= int(change.quantity) <= 999:
                    raise BDSPLiveError(
                        f"{change.item_name} declara la cantidad imposible {change.quantity}."
                    )
            elif change.item_key == "money-max":
                if not 0 <= int(change.quantity) <= BDSP_MAX_MONEY:
                    raise BDSPLiveError(
                        f"BDSP admite como máximo {BDSP_MAX_MONEY} ₽."
                    )
            else:
                raise BDSPLiveError(
                    f"La utilidad '{change.item_key}' no está demostrada para BDSP."
                )

        battle = self.battle_reader_factory(self.client).read()
        if battle is not None:
            raise BDSPLiveError(
                "No se modifican objetos ni dinero durante un combate de BDSP. "
                "Termina el combate y vuelve a pulsar la utilidad."
            )
        first_party = self.party_reader_factory(self.client).read()
        second_party = self.party_reader_factory(self.client).read()
        if not self._same_party(first_party, second_party):
            raise BDSPLiveError(
                "La party o sus referencias cambiaron durante la precondición de utilidades."
            )
        first_inventory = self.inventory_reader_factory(self.client).read()
        second_inventory = self.inventory_reader_factory(self.client).read()
        if (
            int(first_inventory.array_object) != int(second_inventory.array_object)
            or int(first_inventory.data_pointer) != int(second_inventory.data_pointer)
            or int(first_inventory.total_records) != int(second_inventory.total_records)
            or first_inventory.items != second_inventory.items
            or bytes(first_inventory.raw) != bytes(second_inventory.raw)
        ):
            raise BDSPLiveError(
                "La mochila o su referencia cambiaron entre las dos capturas completas."
            )
        first_money = self.money_reader_factory(self.client).read()
        second_money = self.money_reader_factory(self.client).read()
        if first_money != second_money:
            raise BDSPLiveError(
                "MYSTATUS o su referencia cambiaron entre las dos capturas completas."
            )

        inventory_before = bytes(second_inventory.raw)
        if len(inventory_before) != BDSP_INVENTORY_BLOCK_SIZE:
            raise BDSPLiveError("La captura de mochila no conserva sus 36.000 bytes.")
        mystatus_before = bytes(second_money.raw)
        inventory_after = bytearray(inventory_before)
        mystatus_after = bytearray(mystatus_before)
        target_item_ids: set[int] = set()
        money_requested = False
        for change in changes:
            if change.item_key == "money-max":
                struct.pack_into(
                    "<I", mystatus_after, BDSP_MYSTATUS_MONEY_OFFSET,
                    int(change.quantity),
                )
                money_requested = True
                continue
            item_id = int(BDSP_UTILITY_ITEM_IDS[change.item_key])
            offset = item_id * BDSP_INVENTORY_RECORD_SIZE
            record = inventory_after[offset:offset + BDSP_INVENTORY_RECORD_SIZE]
            current_count = int(struct.unpack_from("<i", record, 0)[0])
            sort_order = int(struct.unpack_from("<H", record, 10)[0])
            if current_count == 0 and int(change.quantity) > 0 and sort_order == 0:
                if item_id not in BDSP_GENERAL_ITEM_IDS:
                    raise BDSPLiveError(
                        f"El bolsillo de {change.item_name} no está demostrado para BDSP."
                    )
                sort_order = max(
                    int(struct.unpack_from(
                        "<H", inventory_after,
                        pocket_item_id * BDSP_INVENTORY_RECORD_SIZE + 10,
                    )[0])
                    for pocket_item_id in BDSP_GENERAL_ITEM_IDS
                ) + 1
                if not 1 <= sort_order <= BDSP_INVENTORY_ITEM_COUNT:
                    raise BDSPLiveError(
                        "No existe un SortNumber válido para añadir el objeto a la mochila."
                    )
                struct.pack_into("<H", inventory_after, offset + 10, sort_order)
            struct.pack_into("<i", inventory_after, offset, int(change.quantity))
            target_item_ids.add(item_id)

        item_patches: dict[int, tuple[bytes, bytes]] = {}
        for item_id in sorted(target_item_ids):
            offset = item_id * BDSP_INVENTORY_RECORD_SIZE
            before = inventory_before[offset:offset + BDSP_INVENTORY_RECORD_SIZE]
            after = bytes(inventory_after[offset:offset + BDSP_INVENTORY_RECORD_SIZE])
            if before != after:
                item_patches[item_id] = (before, after)
        money_before = mystatus_before[
            BDSP_MYSTATUS_MONEY_OFFSET:BDSP_MYSTATUS_MONEY_OFFSET + 4
        ]
        money_after = bytes(mystatus_after[
            BDSP_MYSTATUS_MONEY_OFFSET:BDSP_MYSTATUS_MONEY_OFFSET + 4
        ])
        money_changed = bool(money_requested and money_before != money_after)
        if not item_patches and not money_changed:
            return BDSPWriteReceipt(
                party=second_party,
                inventory=second_inventory,
                process=self.client.session.process,
                attempts=2,
                applied_count=len(changes),
                already_applied=True,
                money=second_money,
            )

        session = self.client.session
        if self.client.read_memory(
            int(session.profile.guest_main), len(session.profile.main_witness),
        ) != session.profile.main_witness:
            raise BDSPLiveError("La huella principal de Ryujinx cambió antes de escribir.")

        expected_inventory = bytes(inventory_after)
        expected_mystatus = bytes(mystatus_after)
        transport = self.transport_factory()
        handle = None
        attempted: list[tuple[int, bytes, str]] = []
        try:
            handle = transport.open(int(session.process.pid))
            delta = int(session.guest_to_host_delta)
            inventory_host = int(second_inventory.data_pointer) + delta
            mystatus_host = int(second_money.data_pointer) + delta
            if self._stable_guest(
                self.client, int(second_inventory.data_pointer),
                BDSP_INVENTORY_BLOCK_SIZE, "La mochila inmediatamente antes del write",
            ) != inventory_before:
                raise BDSPLiveError("La mochila cambió inmediatamente antes del write.")
            if self._stable_guest(
                self.client, int(second_money.data_pointer),
                BDSP_MYSTATUS_RUNTIME_SIZE, "MYSTATUS inmediatamente antes del write",
            ) != mystatus_before:
                raise BDSPLiveError("MYSTATUS cambió inmediatamente antes del write.")
            if transport.read(
                handle, inventory_host, BDSP_INVENTORY_BLOCK_SIZE,
            ) != inventory_before:
                raise BDSPLiveError("La mochila no coincide entre guest y host.")
            if transport.read(
                handle, mystatus_host, BDSP_MYSTATUS_RUNTIME_SIZE,
            ) != mystatus_before:
                raise BDSPLiveError("MYSTATUS no coincide entre guest y host.")

            for item_id, (before, after) in sorted(item_patches.items()):
                guest = (
                    int(second_inventory.data_pointer)
                    + item_id * BDSP_INVENTORY_RECORD_SIZE
                )
                host = guest + delta
                transport.assert_writable(handle, host, len(after))
                attempted.append((host, before, f"SaveItem #{item_id}"))
                transport.write(handle, host, after)
                if transport.read(handle, host, len(after)) != after:
                    raise BDSPLiveError(f"El readback host del objeto #{item_id} falló.")
                if self.client.read_memory(guest, len(after)) != after:
                    raise BDSPLiveError(f"El readback guest del objeto #{item_id} falló.")
            if money_changed:
                guest = int(second_money.data_pointer) + BDSP_MYSTATUS_MONEY_OFFSET
                host = guest + delta
                transport.assert_writable(handle, host, len(money_after))
                attempted.append((host, money_before, "MYSTATUS.gold"))
                transport.write(handle, host, money_after)
                if transport.read(handle, host, len(money_after)) != money_after:
                    raise BDSPLiveError("El readback host del dinero falló.")
                if self.client.read_memory(guest, len(money_after)) != money_after:
                    raise BDSPLiveError("El readback guest del dinero falló.")

            if self.client.read_memory(
                int(second_inventory.data_pointer), BDSP_INVENTORY_BLOCK_SIZE,
            ) != expected_inventory:
                raise BDSPLiveError(
                    "La verificación completa de la mochila detectó cambios colaterales."
                )
            if self.client.read_memory(
                int(second_money.data_pointer), BDSP_MYSTATUS_RUNTIME_SIZE,
            ) != expected_mystatus:
                raise BDSPLiveError(
                    "La verificación completa de MYSTATUS detectó cambios colaterales."
                )
            verified_party = self.party_reader_factory(self.client).read()
            if not self._same_party(second_party, verified_party):
                raise BDSPLiveError("La party cambió durante la utilidad BDSP.")
            verified_inventory = self.inventory_reader_factory(self.client).read()
            verified_money = self.money_reader_factory(self.client).read()
            counts = {
                int(item.item_id): int(item.count)
                for item in verified_inventory.items
            }
            for change in changes:
                if change.item_key in BDSP_UTILITY_ITEM_IDS:
                    item_id = int(BDSP_UTILITY_ITEM_IDS[change.item_key])
                    if counts.get(item_id, 0) != int(change.quantity):
                        raise BDSPLiveError(
                            f"La verificación semántica de {change.item_name} falló."
                        )
                elif int(verified_money.money) != int(change.quantity):
                    raise BDSPLiveError("La verificación semántica del dinero falló.")

            watches = [
                BDSPWriteMemoryWatch(
                    int(second_inventory.data_pointer)
                    + item_id * BDSP_INVENTORY_RECORD_SIZE,
                    after,
                )
                for item_id, (_before, after) in sorted(item_patches.items())
            ]
            if money_changed:
                watches.append(BDSPWriteMemoryWatch(
                    int(second_money.data_pointer) + BDSP_MYSTATUS_MONEY_OFFSET,
                    money_after,
                ))
            return BDSPWriteReceipt(
                party=verified_party,
                inventory=verified_inventory,
                process=session.process,
                attempts=2,
                applied_count=len(changes),
                memory_watches=tuple(watches),
                already_applied=False,
                money=verified_money,
            )
        except Exception as exc:
            rollback_errors: list[str] = []
            if handle is not None:
                for host, original, label in reversed(attempted):
                    try:
                        transport.write(handle, host, original)
                        if transport.read(handle, host, len(original)) != original:
                            rollback_errors.append(f"{label}: readback host distinto")
                    except Exception as rollback_exc:
                        rollback_errors.append(f"{label}: {rollback_exc}")
            if attempted and not rollback_errors:
                if self.client.read_memory(
                    int(second_inventory.data_pointer), BDSP_INVENTORY_BLOCK_SIZE,
                ) != inventory_before:
                    rollback_errors.append("mochila: readback guest distinto")
                if self.client.read_memory(
                    int(second_money.data_pointer), BDSP_MYSTATUS_RUNTIME_SIZE,
                ) != mystatus_before:
                    rollback_errors.append("MYSTATUS: readback guest distinto")
            if rollback_errors:
                raise BDSPLiveError(
                    "Falló la utilidad y también su rollback: "
                    + "; ".join(rollback_errors)
                ) from exc
            if attempted:
                raise BDSPLiveError(
                    "Falló la utilidad; RoleRun restauró y verificó mochila y "
                    f"MYSTATUS. Causa: {exc}"
                ) from exc
            raise
        finally:
            if handle is not None:
                transport.close(handle)

    def _profile_for(self, changes: Sequence[object]) -> BDSPTMProfile | None:
        movement_changes = [
            change for change in changes
            if isinstance(change, (PendingChange, PendingTMTeach))
            and int(change.new_move_id or 0) > 0
        ]
        if not movement_changes and not any(isinstance(change, PendingPartyHeal) for change in changes):
            return None
        profile = self.tm_profile_getter()
        if profile is None:
            raise BDSPLiveError(
                "No está disponible personal_masterdatas; no se puede demostrar "
                "el movimiento ni sus PP en la ROM activa."
            )
        for change in movement_changes:
            move_id = int(change.new_move_id)
            if move_id not in profile.valid_moves or profile.base_pp(move_id) <= 0:
                raise BDSPLiveError(
                    f"El movimiento #{move_id} no está activo con PP válidos en WazaTable."
                )
            if isinstance(change, PendingTMTeach):
                tm = profile.tm(int(change.tm_number))
                if (
                    tm is None
                    or int(tm.item_id) != int(change.item_id)
                    or int(tm.move_id) != move_id
                ):
                    raise BDSPLiveError(
                        f"MT{int(change.tm_number):02d} ya no coincide con "
                        "personal_masterdatas. No se escribió ningún byte."
                    )
        return profile

    def apply(self, changes: Sequence[object]) -> BDSPWriteReceipt:
        supported = list(changes)
        if not supported:
            raise BDSPLiveError("No hay cambios BDSP que aplicar.")
        if all(isinstance(change, PendingInventoryChange) for change in supported):
            return self._apply_inventory_utilities(supported)
        if len(supported) == 1 and isinstance(supported[0], PendingTeamChange):
            if supported[0].operation == "replace-fainted":
                return self._apply_faint_replacement(supported[0])
            if supported[0].operation == "swap-party-box":
                return self._apply_party_box_swap(supported[0])
            if supported[0].operation in {"party-to-box", "box-to-party"}:
                return self._apply_party_box_resize(supported[0])
            raise BDSPLiveError(
                f"La operación Equipo↔PC '{supported[0].operation}' no está demostrada en BDSP.",
            )
        if any(
            not isinstance(change, (PendingRoleChange, PendingPartyHeal, PendingChange, PendingTMTeach))
            for change in supported
        ):
            raise BDSPLiveError(
                "Esta transacción BDSP solo admite curación, roles y movimientos de la party. "
                "Equipo↔PC sigue bloqueado hasta disponer de su writer propio."
            )

        profile = self._profile_for(supported)
        battle = self.battle_reader_factory(self.client).read()
        if battle is not None:
            raise BDSPLiveError(
                "No se cura ni se escriben movimientos o roles durante un combate de BDSP. "
                "Termina el combate y vuelve a pulsar la acción."
            )

        first_party = self.party_reader_factory(self.client).read()
        second_party = self.party_reader_factory(self.client).read()
        if not self._same_party(first_party, second_party):
            raise BDSPLiveError(
                "La party o sus referencias cambiaron entre las dos capturas completas."
            )
        first_inventory = self.inventory_reader_factory(self.client).read()
        second_inventory = self.inventory_reader_factory(self.client).read()
        if (
            int(first_inventory.data_pointer) != int(second_inventory.data_pointer)
            or first_inventory.items != second_inventory.items
            or bytes(first_inventory.raw) != bytes(second_inventory.raw)
        ):
            raise BDSPLiveError(
                "La mochila o su referencia cambiaron entre las dos capturas completas."
            )

        by_identity: dict[str, list[BDSPPartyPokemon]] = {}
        for pokemon in second_party.pokemon:
            by_identity.setdefault(self._identity(pokemon), []).append(pokemon)
        targets: dict[int, BDSPPartyPokemon] = {}
        for change in supported:
            identity = str(getattr(change, "pokemon_identity", "") or "")
            matches = by_identity.get(identity, ())
            if len(matches) != 1:
                raise BDSPLiveError(
                    f"La identidad de {getattr(change, 'pokemon', 'el Pokémon')} "
                    f"produjo {len(matches)} coincidencias en la party viva."
                )
            targets[id(change)] = matches[0]

        original_core: dict[int, bytes] = {}
        original_calc: dict[int, tuple[int, bytes]] = {}
        plain_by_pointer: dict[int, bytearray] = {}
        pokemon_by_pointer: dict[int, BDSPPartyPokemon] = {}
        for pokemon in targets.values():
            pointer = int(pokemon.core_data_pointer)
            if pointer in original_core:
                continue
            raw = bytes(pokemon.encrypted)
            if pointer <= 0 or len(raw) != PB8_PARTY_SIZE:
                raise BDSPLiveError("El PokemonParam objetivo no conserva un core PB8 válido.")
            original_core[pointer] = raw[:PB8_STORED_SIZE]
            original_calc[pointer] = (
                int(pokemon.calc_data_pointer), raw[PB8_STORED_SIZE:],
            )
            plain_by_pointer[pointer] = bytearray(decrypt_pb8(raw))
            pokemon_by_pointer[pointer] = pokemon

        inventory_records: dict[int, bytearray] = {}
        inventory_counts = {
            int(item.item_id): int(item.count) for item in second_inventory.items
        }
        for change in supported:
            pointer = int(targets[id(change)].core_data_pointer)
            plain = plain_by_pointer[pointer]
            if isinstance(change, PendingRoleChange):
                actual = self._role_from_plain(plain)
                expected = canonical_role(str(change.old_role or "SIN ROL"))
                if actual != expected:
                    raise BDSPLiveError(
                        f"{change.pokemon} cambió de rol dentro del juego "
                        f"({actual}); RoleRun esperaba {expected}."
                    )
                self._set_role(plain, change.new_role)
                if change.new_evs is not None:
                    if change.old_evs is None:
                        raise BDSPLiveError("El cambio de EV no conserva la precondición anterior.")
                    if profile is None:
                        profile = self.tm_profile_getter()
                    base_stats = None if profile is None else profile.base_stats(
                        targets[id(change)].species_id, targets[id(change)].form,
                    )
                    if base_stats is None:
                        raise BDSPLiveError(
                            "PersonalTable no contiene los stats base de la especie/forma objetivo."
                        )
                    _set_pb8_evs_and_stats(
                        plain,
                        pokemon=targets[id(change)],
                        expected_evs=tuple(change.old_evs),
                        desired_evs=tuple(change.new_evs),
                        base_stats=base_stats,
                    )
                continue

            if isinstance(change, PendingPartyHeal):
                if profile is None:
                    raise BDSPLiveError(
                        "No está disponible personal_masterdatas; no se pueden demostrar los PP máximos."
                    )
                pokemon = targets[id(change)]
                struct.pack_into("<H", plain, 0x8A, int(pokemon.max_hp))
                # PKHeX.Core PB8.Status_Condition fue contrastado por reflexión
                # contra el buffer PB8: ocupa el entero LE de 0x94..0x97.
                struct.pack_into("<I", plain, 0x94, 0)
                for index, move_id in enumerate(pokemon.move_ids):
                    move_id = int(move_id)
                    if move_id <= 0:
                        plain[0x7A + index] = 0
                        continue
                    base_pp = int(profile.base_pp(move_id))
                    pp_ups = int(pokemon.move_pp_ups[index])
                    if base_pp <= 0 or not 0 <= pp_ups <= 3:
                        raise BDSPLiveError(
                            f"No se pudieron demostrar los PP máximos del movimiento #{move_id}."
                        )
                    plain[0x7A + index] = base_pp * (5 + pp_ups) // 5
                continue

            assert isinstance(change, (PendingChange, PendingTMTeach))
            if isinstance(change, PendingTMTeach):
                item_id = int(change.item_id)
                if not 0 <= item_id < BDSP_INVENTORY_ITEM_COUNT:
                    raise BDSPLiveError(f"El ID de objeto {item_id} queda fuera de saveItem.")
                count = inventory_counts.get(item_id, 0)
                if count != int(change.quantity_before):
                    raise BDSPLiveError(
                        f"La cantidad viva de {change.item_name} cambió "
                        f"({count} != {int(change.quantity_before)}). Vuelve a abrir el selector."
                    )
                record_address = int(second_inventory.data_pointer) + item_id * BDSP_INVENTORY_RECORD_SIZE
                if item_id not in inventory_records:
                    inventory_records[item_id] = bytearray(self._stable_guest(
                        self.client, record_address, BDSP_INVENTORY_RECORD_SIZE,
                        f"El registro vivo de {change.item_name}",
                    ))
                struct.pack_into("<i", inventory_records[item_id], 0, count - 1)
                inventory_counts[item_id] = count - 1

            move_id = int(change.new_move_id or 0)
            base_pp = profile.base_pp(move_id) if profile is not None and move_id > 0 else 0
            self._set_move(plain, change, base_pp=base_pp)

        desired_core: dict[int, bytes] = {}
        desired_calc: dict[int, tuple[int, bytes]] = {}
        for pointer, plain in plain_by_pointer.items():
            refresh_pb8_checksum(plain)
            encoded = encrypt_pb8(bytes(plain))
            parsed = parse_bdsp_party_pokemon(
                encoded, slot=int(pokemon_by_pointer[pointer].slot),
            )
            if self._identity(parsed) != self._identity(pokemon_by_pointer[pointer]):
                raise BDSPLiveError("La transformación PB8 alteró la identidad del Pokémon.")
            desired_core[pointer] = encoded[:PB8_STORED_SIZE]
            desired_calc[pointer] = (
                original_calc[pointer][0], encoded[PB8_STORED_SIZE:],
            )

        changed_core = {
            pointer: desired for pointer, desired in desired_core.items()
            if desired != original_core[pointer]
        }
        changed_calc = {
            core_pointer: desired
            for core_pointer, desired in desired_calc.items()
            if desired[1] != original_calc[core_pointer][1]
        }
        changed_items = {
            item_id: bytes(record) for item_id, record in inventory_records.items()
            if bytes(record) != self._stable_guest(
                self.client,
                int(second_inventory.data_pointer) + item_id * BDSP_INVENTORY_RECORD_SIZE,
                BDSP_INVENTORY_RECORD_SIZE,
                f"La precondición final del objeto #{item_id}",
            )
        }
        if not changed_core and not changed_calc and not changed_items:
            return BDSPWriteReceipt(
                party=second_party,
                inventory=second_inventory,
                process=self.client.session.process,
                attempts=2,
                applied_count=len(supported),
                already_applied=True,
            )

        # Invalida una sesión reiniciada/reemplazada justo antes de abrir RW.
        session = self.client.session
        if self.client.read_memory(
            int(session.profile.guest_main), len(session.profile.main_witness),
        ) != session.profile.main_witness:
            raise BDSPLiveError("La huella principal de Ryujinx cambió antes de escribir.")

        transport = self.transport_factory()
        handle = None
        attempted: list[tuple[int, bytes, str]] = []
        original_items: dict[int, bytes] = {}
        try:
            handle = transport.open(int(session.process.pid))
            delta = int(session.guest_to_host_delta)
            for pointer, desired in sorted(changed_core.items()):
                host = pointer + delta
                transport.assert_writable(handle, host, len(desired))
                before = transport.read(handle, host, len(desired))
                if before != original_core[pointer]:
                    raise BDSPLiveError(
                        f"El core PB8 0x{pointer:X} cambió antes del write."
                    )
            for core_pointer, (pointer, desired) in sorted(changed_calc.items()):
                host = pointer + delta
                transport.assert_writable(handle, host, len(desired))
                before = transport.read(handle, host, len(desired))
                if before != original_calc[core_pointer][1]:
                    raise BDSPLiveError(
                        f"El bloque calc PB8 0x{pointer:X} cambió antes del write."
                    )
            for item_id, desired in sorted(changed_items.items()):
                guest = int(second_inventory.data_pointer) + item_id * BDSP_INVENTORY_RECORD_SIZE
                host = guest + delta
                before = self._stable_guest(
                    self.client, guest, len(desired), f"El registro final del objeto #{item_id}",
                )
                original_items[item_id] = before
                transport.assert_writable(handle, host, len(desired))
                if transport.read(handle, host, len(desired)) != before:
                    raise BDSPLiveError(
                        f"El registro del objeto #{item_id} no coincide entre guest y host."
                    )

            # Primero el Pokémon, después el consumo. Si el segundo write falla,
            # el bloque PB8 también se restaura dentro de la misma transacción.
            for pointer, desired in sorted(changed_core.items()):
                host = pointer + delta
                attempted.append((host, original_core[pointer], f"PB8 0x{pointer:X}"))
                transport.write(handle, host, desired)
                if transport.read(handle, host, len(desired)) != desired:
                    raise BDSPLiveError(f"El readback host del PB8 0x{pointer:X} falló.")
                if self.client.read_memory(pointer, len(desired)) != desired:
                    raise BDSPLiveError(f"El readback guest del PB8 0x{pointer:X} falló.")
            for core_pointer, (pointer, desired) in sorted(changed_calc.items()):
                host = pointer + delta
                attempted.append((host, original_calc[core_pointer][1], f"PB8 calc 0x{pointer:X}"))
                transport.write(handle, host, desired)
                if transport.read(handle, host, len(desired)) != desired:
                    raise BDSPLiveError(f"El readback host del calc PB8 0x{pointer:X} falló.")
                if self.client.read_memory(pointer, len(desired)) != desired:
                    raise BDSPLiveError(f"El readback guest del calc PB8 0x{pointer:X} falló.")
            for item_id, desired in sorted(changed_items.items()):
                guest = int(second_inventory.data_pointer) + item_id * BDSP_INVENTORY_RECORD_SIZE
                host = guest + delta
                attempted.append((host, original_items[item_id], f"SaveItem #{item_id}"))
                transport.write(handle, host, desired)
                if transport.read(handle, host, len(desired)) != desired:
                    raise BDSPLiveError(f"El readback host del objeto #{item_id} falló.")
                if self.client.read_memory(guest, len(desired)) != desired:
                    raise BDSPLiveError(f"El readback guest del objeto #{item_id} falló.")

            verified_party = self.party_reader_factory(self.client).read()
            verified_inventory = self.inventory_reader_factory(self.client).read()
            verified_by_identity = {
                self._identity(pokemon): pokemon for pokemon in verified_party.pokemon
            }
            for change in supported:
                verified = verified_by_identity.get(str(getattr(change, "pokemon_identity", "")))
                if verified is None:
                    raise BDSPLiveError("La verificación perdió el Pokémon objetivo.")
                if isinstance(change, PendingRoleChange):
                    if role_from_markings(verified.markings, layout=2)[0] != canonical_role(change.new_role):
                        raise BDSPLiveError("La verificación semántica del rol falló.")
                    if change.new_evs is not None and verified.evs != tuple(change.new_evs):
                        raise BDSPLiveError("La verificación semántica de EV falló.")
                elif isinstance(change, PendingPartyHeal):
                    verified_plain = decrypt_pb8(verified.encrypted)
                    if int(verified.current_hp) != int(verified.max_hp):
                        raise BDSPLiveError("La verificación semántica de PS curados falló.")
                    if int(struct.unpack_from("<I", verified_plain, 0x94)[0]) != 0:
                        raise BDSPLiveError("La verificación semántica del estado curado falló.")
                    for index, move_id in enumerate(verified.move_ids):
                        if int(move_id) <= 0:
                            continue
                        expected_pp = int(profile.base_pp(int(move_id))) * (5 + int(verified.move_pp_ups[index])) // 5
                        if int(verified.move_pp[index]) != expected_pp:
                            raise BDSPLiveError("La verificación semántica de PP curados falló.")
                else:
                    index = int(change.move_slot) - 1
                    # Para borrados, la compactación puede traer el siguiente
                    # movimiento; el PB8 completo ya fue comparado byte a byte.
                    if int(change.new_move_id or 0) > 0 and int(verified.move_ids[index]) != int(change.new_move_id):
                        raise BDSPLiveError("La verificación semántica del movimiento falló.")
            counts = {int(item.item_id): int(item.count) for item in verified_inventory.items}
            for item_id, expected in inventory_counts.items():
                if item_id in inventory_records and counts.get(item_id, 0) != expected:
                    raise BDSPLiveError("La verificación semántica de la mochila falló.")

            watches = tuple(
                [
                    BDSPWriteMemoryWatch(pointer, desired)
                    for pointer, desired in sorted(changed_core.items())
                ]
                + [
                    BDSPWriteMemoryWatch(pointer, desired)
                    for _core, (pointer, desired) in sorted(changed_calc.items())
                ]
                + [
                    BDSPWriteMemoryWatch(
                        int(second_inventory.data_pointer) + item_id * BDSP_INVENTORY_RECORD_SIZE,
                        desired,
                    )
                    for item_id, desired in sorted(changed_items.items())
                ]
            )
            return BDSPWriteReceipt(
                party=verified_party,
                inventory=verified_inventory,
                process=session.process,
                attempts=2,
                applied_count=len(supported),
                memory_watches=watches,
                already_applied=False,
            )
        except Exception as exc:
            rollback_errors: list[str] = []
            if handle is not None:
                for host, original, label in reversed(attempted):
                    try:
                        transport.write(handle, host, original)
                        if transport.read(handle, host, len(original)) != original:
                            rollback_errors.append(f"{label}: readback host distinto")
                    except Exception as rollback_exc:
                        rollback_errors.append(f"{label}: {rollback_exc}")
            if attempted and not rollback_errors:
                try:
                    delta = int(session.guest_to_host_delta)
                    for host, original, label in attempted:
                        guest = int(host) - delta
                        if self.client.read_memory(guest, len(original)) != original:
                            rollback_errors.append(f"{label}: readback guest distinto")
                except Exception as rollback_exc:
                    rollback_errors.append(f"readback guest: {rollback_exc}")
            if rollback_errors:
                raise BDSPLiveError(
                    f"La escritura BDSP falló: {exc}. No se pudo confirmar todo el rollback: "
                    + "; ".join(rollback_errors)
                ) from exc
            if attempted:
                raise BDSPLiveError(
                    f"La escritura BDSP falló: {exc}. RoleRun restauró y verificó "
                    "el PB8 y la mochila originales."
                ) from exc
            raise
        finally:
            if handle is not None:
                try:
                    transport.close(handle)
                except Exception:
                    pass
