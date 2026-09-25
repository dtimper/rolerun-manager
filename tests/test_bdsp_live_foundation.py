from __future__ import annotations

import struct

import pytest

from app.bdsp_live import (
    BDSP_BOX_COUNT,
    BDSP_BOX_SLOT_COUNT,
    BDSP_SP_130_BATTLE_UI_TYPEINFO_OFFSET,
    BDSP_SP_130_BATTLEPROC_TYPEINFO_OFFSET,
    BDSP_SP_130_HOST_PROFILE,
    BDSP_SP_130_SYSTEM_FLAGS_POINTER,
    BDSP_BADGE_SYSTEM_FLAG_INDICES,
    BDSP_SYSTEM_FLAG_COUNT,
    BDSPBadgeReader,
    BDSPBattlePresentationReader,
    BDSPBattleReader,
    BDSPLiveError,
    BDSPBoxReader,
    BDSPInventoryReader,
    BDSPPartyReader,
    BDSP_INVENTORY_BLOCK_SIZE,
    BDSP_INVENTORY_ITEM_COUNT,
    BDSP_INVENTORY_RECORD_SIZE,
    PB8_PARTY_SIZE,
    PB8_STORED_SIZE,
    _BLOCK_POSITIONS,
    _crypt_words,
    decrypt_pb8,
    parse_bdsp_box_pokemon,
    parse_bdsp_party_pokemon,
)


_BLOCK_POSITION_INVERT = (
    0, 1, 2, 4, 3, 5, 6, 7, 12, 18, 13, 19,
    8, 10, 14, 20, 16, 22, 9, 11, 15, 21, 17, 23,
    0, 1, 2, 4, 3, 5, 6, 7,
)


def _shuffle(data: bytearray, shuffle_value: int) -> None:
    block_size = (PB8_STORED_SIZE - 8) // 4
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


def _pb8(
    *,
    species: int,
    pid: int = 0xAABBCCDD,
    tid: int = 123,
    sid: int = 456,
    form: int = 0,
    nickname: str = "Test",
    held_item_id: int = 0,
    ability_id: int = 1,
    move_ids: tuple[int, int, int, int] = (33, 45, 0, 0),
    move_pp: tuple[int, int, int, int] = (35, 40, 0, 0),
    move_pp_ups: tuple[int, int, int, int] = (0, 1, 0, 0),
    markings: int = 0,
    is_egg: bool = False,
    current_hp: int = 1,
    max_hp: int = 1,
    level: int = 1,
    experience: int = 0,
    nature_id: int = 0,
    stat_nature_id: int = 0,
    ivs: tuple[int, int, int, int, int, int] = (0, 0, 0, 0, 0, 0),
    evs: tuple[int, int, int, int, int, int] = (0, 0, 0, 0, 0, 0),
    stats: tuple[int, int, int, int, int, int] | None = None,
    status_condition: int = 0,
) -> bytes:
    plain = bytearray(PB8_PARTY_SIZE)
    ec = 0 if species == 0 else 0x12345678
    struct.pack_into("<I", plain, 0, ec)
    struct.pack_into("<H", plain, 8, species)
    struct.pack_into("<H", plain, 0x0A, held_item_id)
    struct.pack_into("<H", plain, 0x0C, tid)
    struct.pack_into("<H", plain, 0x0E, sid)
    struct.pack_into("<I", plain, 0x10, experience)
    struct.pack_into("<H", plain, 0x14, ability_id)
    struct.pack_into("<H", plain, 0x18, markings)
    struct.pack_into("<I", plain, 0x1C, pid)
    plain[0x20] = nature_id
    plain[0x21] = stat_nature_id
    plain[0x24] = form
    for offset, value in zip((0x26, 0x27, 0x28, 0x2A, 0x2B, 0x29), evs):
        plain[offset] = value
    encoded_nickname = nickname.encode("utf-16le")[:24]
    plain[0x58:0x58 + len(encoded_nickname)] = encoded_nickname
    struct.pack_into("<4H", plain, 0x72, *move_ids)
    plain[0x7A:0x7E] = bytes(move_pp)
    plain[0x7E:0x82] = bytes(move_pp_ups)
    struct.pack_into("<H", plain, 0x8A, current_hp)
    iv32 = sum(
        (int(value) & 0x1F) << shift
        for value, shift in zip(ivs, (0, 5, 10, 20, 25, 15))
    )
    if is_egg:
        iv32 |= 0x40000000
    struct.pack_into("<I", plain, 0x8C, iv32)
    struct.pack_into("<I", plain, 0x94, status_condition)
    plain[PB8_STORED_SIZE] = level
    struct.pack_into("<H", plain, 0x14A, max_hp)
    for offset, value in zip(
        (0x14A, 0x14C, 0x14E, 0x152, 0x154, 0x150),
        stats or (max_hp, 1, 1, 1, 1, 1),
    ):
        struct.pack_into("<H", plain, offset, value)
    checksum = sum(struct.unpack_from("<160H", plain, 8)) & 0xFFFF
    struct.pack_into("<H", plain, 6, checksum)
    encrypted = bytearray(plain)
    sv = (ec >> 13) & 31
    _shuffle(encrypted, _BLOCK_POSITION_INVERT[sv])
    _crypt_words(encrypted, 8, PB8_STORED_SIZE, ec)
    _crypt_words(encrypted, PB8_STORED_SIZE, PB8_PARTY_SIZE, ec)
    return bytes(encrypted)


def test_bdsp_pb8_publishes_nature_stats_ivs_and_evs_in_visible_order() -> None:
    raw = _pb8(
        species=300,
        current_hp=18,
        max_hp=21,
        level=12,
        nature_id=3,
        stat_nature_id=3,
        ivs=(31, 30, 29, 28, 27, 26),
        evs=(4, 252, 0, 0, 0, 252),
        stats=(21, 18, 14, 11, 12, 23),
    )

    party = parse_bdsp_party_pokemon(raw, slot=1)
    boxed = parse_bdsp_box_pokemon(raw, box=1, slot=1)

    assert party.nature_id == party.stat_nature_id == 3
    assert party.ivs == (31, 30, 29, 28, 27, 26)
    assert party.evs == (4, 252, 0, 0, 0, 252)
    assert party.stats == (21, 18, 14, 11, 12, 23)
    assert boxed is not None
    assert boxed.experience == 0
    assert boxed.ivs == party.ivs
    assert boxed.evs == party.evs


@pytest.mark.parametrize("status", [0, 1, 7, 8, 16, 32, 64, 128])
def test_bdsp_party_publishes_the_proven_pb8_status_condition(status: int) -> None:
    party = parse_bdsp_party_pokemon(
        _pb8(species=300, current_hp=18, max_hp=21, level=12, status_condition=status),
        slot=1,
    )

    assert party.status_condition == status


class FakeGuestClient:
    profile = BDSP_SP_130_HOST_PROFILE

    def __init__(self, segments: dict[int, bytes], pointer_base: int) -> None:
        self.segments = {int(address): bytes(data) for address, data in segments.items()}
        self.pointer_base = int(pointer_base)
        self.unstable_at: int | None = None
        self.read_counts: dict[int, int] = {}
        self.resolved_values: list[int] = [int(pointer_base)]
        self.resolve_calls = 0

    def resolve_main_pointer(self, _jumps) -> int:
        self.resolve_calls += 1
        if len(self.resolved_values) > 1:
            return self.resolved_values.pop(0)
        return self.resolved_values[0]

    def read_memory(self, address: int, size: int) -> bytes:
        address = int(address)
        self.read_counts[address] = self.read_counts.get(address, 0) + 1
        data = self.segments[address][:int(size)]
        if address == self.unstable_at and self.read_counts[address] % 2 == 0:
            return bytes((data[0] ^ 1,)) + data[1:]
        return data

    def read_u64(self, address: int) -> int:
        return int(struct.unpack("<Q", self.read_memory(int(address), 8))[0])


def _box_memory(first: bytes | None = None) -> tuple[FakeGuestClient, int]:
    pointer_base = 0x10000
    box_pointers = tuple(0x20000 + index * 0x1000 for index in range(BDSP_BOX_COUNT))
    segments: dict[int, bytes] = {
        pointer_base: struct.pack(f"<{BDSP_BOX_COUNT}Q", *box_pointers),
    }
    slot_pointers: list[int] = []
    empty = _pb8(species=0)
    for box_index, box_pointer in enumerate(box_pointers):
        pointers = tuple(
            0x100000 + (box_index * BDSP_BOX_SLOT_COUNT + slot_index) * 0x200
            for slot_index in range(BDSP_BOX_SLOT_COUNT)
        )
        slot_pointers.extend(pointers)
        segments[box_pointer + 0x20] = struct.pack(f"<{BDSP_BOX_SLOT_COUNT}Q", *pointers)
        for pointer in pointers:
            segments[pointer + 0x18] = struct.pack("<Q", PB8_PARTY_SIZE)
            segments[pointer + 0x20] = empty
    if first is not None:
        segments[slot_pointers[0] + 0x20] = bytes(first)
    return FakeGuestClient(segments, pointer_base), slot_pointers[0]


def _party_memory(*members: bytes) -> tuple[FakeGuestClient, list[int]]:
    party = 0x10000
    member_array = 0x20000
    owners = [0x30000 + index * 0x100 for index in range(6)]
    cores = [0x40000 + index * 0x400 for index in range(6)]
    calcs = [0x60000 + index * 0x100 for index in range(6)]
    accessors = [0x70000 + index * 0x100 for index in range(6)]
    segments: dict[int, bytes] = {
        party + 0x10: struct.pack("<QI", member_array, len(members)),
        member_array + 0x18: struct.pack("<Q", 6),
        member_array + 0x20: struct.pack("<6Q", *owners),
    }
    for index, raw in enumerate(members):
        segments[owners[index] + 0x10] = struct.pack(
            "<3Q", cores[index], calcs[index], accessors[index],
        )
        segments[cores[index] + 0x18] = struct.pack("<Q", PB8_STORED_SIZE)
        segments[calcs[index] + 0x18] = struct.pack("<Q", PB8_PARTY_SIZE - PB8_STORED_SIZE)
        segments[cores[index] + 0x20] = raw[:PB8_STORED_SIZE]
        segments[calcs[index] + 0x20] = raw[PB8_STORED_SIZE:]
    return FakeGuestClient(segments, party), cores


def _inventory_memory(
    records: dict[int, tuple[int, int, int, int, int]],
) -> tuple[FakeGuestClient, int]:
    """Records: item ID -> count, vanish-new, favorite, show-name, sort."""
    data_pointer = 0x18020
    raw = bytearray(BDSP_INVENTORY_BLOCK_SIZE)
    for item_id, (count, vanish, favorite, show_name, sort_order) in records.items():
        offset = item_id * BDSP_INVENTORY_RECORD_SIZE
        struct.pack_into("<iBBBxxxH", raw, offset, count, vanish, favorite, show_name, sort_order)
    segments = {
        data_pointer - 8: struct.pack("<Q", BDSP_INVENTORY_ITEM_COUNT),
        data_pointer: bytes(raw),
    }
    return FakeGuestClient(segments, data_pointer), data_pointer


def _badge_memory(*enabled: int) -> tuple[FakeGuestClient, int]:
    data_pointer = 0x18020
    raw = bytearray(BDSP_SYSTEM_FLAG_COUNT)
    for index in enabled:
        raw[int(index)] = 1
    segments = {
        data_pointer - 8: struct.pack("<Q", BDSP_SYSTEM_FLAG_COUNT),
        data_pointer: bytes(raw),
    }
    return FakeGuestClient(segments, data_pointer), data_pointer


def test_alpha77_badge_reader_counts_the_exact_bdsp_system_flags() -> None:
    client, data_pointer = _badge_memory(124, 125, 130)

    result = BDSPBadgeReader(client).read()

    assert BDSP_BADGE_SYSTEM_FLAG_INDICES == tuple(range(124, 132))
    assert BDSP_SP_130_SYSTEM_FLAGS_POINTER == (
        0x4E7BE98, 0xB8, 0x10, 0x30, 0x20,
    )
    assert result.count == 3
    assert result.values == (True, True, False, False, False, False, True, False)
    assert result.data_pointer == data_pointer
    assert client.resolve_calls == 2
    assert client.read_counts[data_pointer] == 2


def test_alpha77_badge_reader_rejects_wrong_array_length() -> None:
    client, data_pointer = _badge_memory()
    client.segments[data_pointer - 8] = struct.pack("<Q", 999)

    with pytest.raises(BDSPLiveError, match="declara 999 elementos"):
        BDSPBadgeReader(client).read()


def test_alpha77_badge_reader_rejects_non_boolean_values() -> None:
    client, data_pointer = _badge_memory()
    raw = bytearray(client.segments[data_pointer])
    raw[124] = 2
    client.segments[data_pointer] = bytes(raw)

    with pytest.raises(BDSPLiveError, match="valores no booleanos"):
        BDSPBadgeReader(client).read()


def test_alpha77_badge_reader_rejects_unstable_data_or_root() -> None:
    client, data_pointer = _badge_memory(124)
    client.unstable_at = data_pointer
    with pytest.raises(BDSPLiveError, match="cambió durante la doble lectura"):
        BDSPBadgeReader(client).read()

    client, _data_pointer = _badge_memory(124)
    client.resolved_values = [0x18020, 0x19020]
    with pytest.raises(BDSPLiveError, match="referencia runtime"):
        BDSPBadgeReader(client).read()


def _battle_memory(
    *rows: tuple[int, int, int, int, int],
    initialized: bool = True,
    ended: bool = False,
) -> tuple[FakeGuestClient, list[int]]:
    """Rows: species, current HP, max HP, level, player PokeID."""

    party = 0x10000
    member_array = 0x20000
    type_info = 0x28000
    static_fields = 0x29000
    battle_params = [0x30000 + index * 0x200 for index in range(6)]
    cores = [0x40000 + index * 0x200 for index in range(6)]
    bases = [0x50000 + index * 0x200 for index in range(6)]
    variables = [0x60000 + index * 0x200 for index in range(6)]
    efforts = [0x70000 + index * 0x200 for index in range(6)]
    moves = [0x80000 + index * 0x200 for index in range(6)]
    segments: dict[int, bytes] = {
        BDSP_SP_130_HOST_PROFILE.guest_main + BDSP_SP_130_BATTLEPROC_TYPEINFO_OFFSET:
            struct.pack("<Q", type_info),
        type_info + 0xB8: struct.pack("<Q", static_fields),
        static_fields + 0x8: bytes((int(initialized), int(ended))),
        party + 0x10: struct.pack("<QB", member_array, len(rows)),
        member_array + 0x18: struct.pack("<Q", 6),
        member_array + 0x20: struct.pack("<6Q", *battle_params),
    }
    for index, (species, current_hp, max_hp, level, poke_id) in enumerate(rows):
        segments[battle_params[index] + 0x10] = struct.pack(
            "<5Q", cores[index], bases[index], variables[index], efforts[index], moves[index],
        )
        segments[cores[index] + 0x18] = struct.pack(
            "<IIHHHHHHHBB",
            0,
            1234,
            species,
            0,
            max_hp,
            current_hp,
            0,
            0,
            65,
            level,
            poke_id,
        )
    return FakeGuestClient(segments, party), cores


def _presentation_memory(
    *,
    player_hp: int = 12,
    player_max_hp: int = 58,
    player_poke_id: int = 0,
    hp_animation: bool = False,
    ui_class_name: str = "BattleViewUISystem",
    window_count: int = 4,
) -> FakeGuestClient:
    type_info = 0x28000
    type_name = 0x28100
    static_fields = 0x29000
    ui_instance = 0x2A000
    status_array = 0x2B000
    window_type = 0x2C000
    window_type_name = 0x2C100
    hp_bar_type = 0x2D000
    hp_bar_type_name = 0x2D100
    windows = [0x30000 + index * 0x200 for index in range(4)]
    hp_bars = [0x40000 + index * 0x100 for index in range(4)]
    segments: dict[int, bytes] = {
        BDSP_SP_130_HOST_PROFILE.guest_main + BDSP_SP_130_BATTLE_UI_TYPEINFO_OFFSET:
            struct.pack("<Q", type_info),
        type_info + 0x10: struct.pack("<Q", type_name),
        type_name: ui_class_name.encode("ascii").ljust(32, b"\0"),
        type_info + 0xB8: struct.pack("<Q", static_fields),
        static_fields + 0x20: struct.pack("<Q", ui_instance),
        ui_instance: struct.pack("<Q", type_info),
        ui_instance + 0x20: struct.pack("<Q", status_array),
        status_array + 0x18: struct.pack("<Q", window_count),
        status_array + 0x20: struct.pack("<4Q", *windows),
        window_type + 0x10: struct.pack("<Q", window_type_name),
        window_type_name: b"BUIStatusWindow\0".ljust(32, b"\0"),
        hp_bar_type + 0x10: struct.pack("<Q", hp_bar_type_name),
        hp_bar_type_name: b"HpBar\0".ljust(32, b"\0"),
    }
    for index, (window, hp_bar) in enumerate(zip(windows, hp_bars)):
        status = bytearray(0x32)
        status[0] = int(index < 2)
        hp = player_hp if index == 0 else (35 if index == 1 else 0)
        max_hp = player_max_hp if index == 0 else (35 if index == 1 else 0)
        struct.pack_into("<II", status, 4, hp, max_hp)
        status[12:16] = bytes((25, player_poke_id if index == 0 else 12, int(index == 0), 0))
        status[0x30:0x32] = bytes((int(index < 2), 0))
        segments[window] = struct.pack("<Q", window_type)
        segments[window + 0xA0] = struct.pack("<Q", hp_bar)
        segments[window + 0xD8] = bytes(status)
        segments[hp_bar] = struct.pack("<Q", hp_bar_type)
        segments[hp_bar + 0x54] = bytes((int(hp_animation and index == 0),))
    return FakeGuestClient(segments, pointer_base=0x10000)


def test_pb8_decrypt_checksum_and_identity_roundtrip() -> None:
    raw = _pb8(species=25, pid=0x10203040, tid=111, sid=222)

    pokemon = parse_bdsp_box_pokemon(raw, box=1, slot=1)

    assert pokemon is not None
    assert (pokemon.species_id, pokemon.pid, pokemon.tid, pokemon.sid) == (25, 0x10203040, 111, 222)
    assert decrypt_pb8(raw)[8:10] == struct.pack("<H", 25)


def test_box_reader_requires_stable_40_by_30_matrix_and_valid_checksums() -> None:
    client, _ = _box_memory(_pb8(
        species=387, pid=0x55667788, form=2, nickname="Turtwig",
        held_item_id=149, ability_id=65, move_ids=(33, 45, 0, 0),
        move_pp=(35, 40, 0, 0), move_pp_ups=(1, 2, 0, 0),
        markings=(1 << 2), is_egg=True, nature_id=3, stat_nature_id=13,
        ivs=(31, 30, 29, 28, 27, 26), evs=(4, 8, 12, 16, 20, 24),
        experience=1728,
    ))

    result = BDSPBoxReader(client).read()  # type: ignore[arg-type]

    assert result.total_slots == 1200
    assert result.empty_slots == 1199
    assert len(result.pokemon) == 1
    assert (result.pokemon[0].box, result.pokemon[0].slot) == (1, 1)
    assert (result.pokemon[0].species_id, result.pokemon[0].pid) == (387, 0x55667788)
    assert result.pokemon[0].form == 2
    assert result.pokemon[0].nickname == "Turtwig"
    assert (result.pokemon[0].held_item_id, result.pokemon[0].ability_id) == (149, 65)
    assert result.pokemon[0].move_ids == (33, 45, 0, 0)
    assert result.pokemon[0].move_pp == (35, 40, 0, 0)
    assert result.pokemon[0].move_pp_ups == (1, 2, 0, 0)
    assert result.pokemon[0].markings == (False, True, False, False, False, False)
    assert result.pokemon[0].is_egg is True
    assert result.pokemon[0].nature_id == 3
    assert result.pokemon[0].stat_nature_id == 13
    assert result.pokemon[0].ivs == (31, 30, 29, 28, 27, 26)
    assert result.pokemon[0].evs == (4, 8, 12, 16, 20, 24)
    assert result.pokemon[0].experience == 1728


def test_box_reader_rejects_a_pb8_checksum_corruption() -> None:
    damaged = bytearray(_pb8(species=25))
    damaged[40] ^= 0x80
    client, _ = _box_memory(bytes(damaged))

    with pytest.raises(BDSPLiveError, match="checksum inválido"):
        BDSPBoxReader(client).read()  # type: ignore[arg-type]


def test_box_reader_rejects_a_sample_that_changes_between_reads() -> None:
    client, first_slot = _box_memory(_pb8(species=25))
    client.unstable_at = first_slot + 0x20

    with pytest.raises(BDSPLiveError, match="cambió durante la doble lectura"):
        BDSPBoxReader(client).read()  # type: ignore[arg-type]


def test_party_reader_reconstructs_runtime_core_and_calc_with_hp() -> None:
    client, _ = _party_memory(
        _pb8(
            species=25,
            pid=0x10203040,
            form=3,
            nickname="Pika",
            held_item_id=149,
            ability_id=9,
            move_ids=(85, 98, 45, 0),
            move_pp=(15, 30, 40, 0),
            move_pp_ups=(1, 0, 2, 0),
            markings=(1 << 0) | (2 << 4),
            is_egg=True,
            current_hp=17,
            max_hp=42,
            level=12,
        ),
        _pb8(species=133, pid=0x50607080, current_hp=0, max_hp=38, level=11),
    )

    result = BDSPPartyReader(client).read()  # type: ignore[arg-type]

    assert result.member_count == 2
    assert [(item.slot, item.species_id, item.pid) for item in result.pokemon] == [
        (1, 25, 0x10203040),
        (2, 133, 0x50607080),
    ]
    assert [(item.current_hp, item.max_hp, item.level) for item in result.pokemon] == [
        (17, 42, 12),
        (0, 38, 11),
    ]
    first = result.pokemon[0]
    assert (first.form, first.nickname, first.held_item_id, first.ability_id) == (3, "Pika", 149, 9)
    assert first.move_ids == (85, 98, 45, 0)
    assert first.move_pp == (15, 30, 40, 0)
    assert first.move_pp_ups == (1, 0, 2, 0)
    assert first.is_egg is True
    assert first.markings == (True, False, True, False, False, False)


def test_inventory_reader_publishes_live_counts_by_item_index() -> None:
    client, data_pointer = _inventory_memory({
        22: (9, 0, 0, 0, 4),
        337: (2, 1, 1, 1, 3),
    })

    result = BDSPInventoryReader(client).read()  # type: ignore[arg-type]

    assert result.total_records == 3000
    assert result.data_pointer == data_pointer
    assert result.array_object == data_pointer - 0x20
    assert len(result.raw) == BDSP_INVENTORY_BLOCK_SIZE
    assert [
        (
            item.item_id, item.count, item.vanish_new, item.favorite,
            item.show_move_name, item.sort_order,
        )
        for item in result.items
    ] == [
        (22, 9, False, False, False, 4),
        (337, 2, True, True, True, 3),
    ]
    assert client.resolve_calls == 2
    assert client.read_counts[data_pointer] == 2


def test_inventory_reader_rejects_wrong_length_or_unstable_block() -> None:
    wrong_length, data_pointer = _inventory_memory({337: (2, 0, 0, 0, 3)})
    wrong_length.segments[data_pointer - 8] = struct.pack("<Q", 2999)
    with pytest.raises(BDSPLiveError, match="2999 registros"):
        BDSPInventoryReader(wrong_length).read()  # type: ignore[arg-type]

    unstable, data_pointer = _inventory_memory({337: (2, 0, 0, 0, 3)})
    unstable.unstable_at = data_pointer
    with pytest.raises(BDSPLiveError, match="bloque saveItem.*cambió"):
        BDSPInventoryReader(unstable).read()  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "record, message",
    [
        ((1000, 0, 0, 0, 1), "cantidad imposible"),
        ((1, 2, 0, 0, 1), "flags booleanos inválidos"),
        ((1, 0, 0, 0, 0), "sin orden de mochila"),
    ],
)
def test_inventory_reader_rejects_records_outside_the_demonstrated_layout(
    record: tuple[int, int, int, int, int], message: str,
) -> None:
    client, _ = _inventory_memory({337: record})

    with pytest.raises(BDSPLiveError, match=message):
        BDSPInventoryReader(client).read()  # type: ignore[arg-type]


def test_party_reader_rejects_move_or_pp_up_values_outside_bdsp_contract() -> None:
    bad_move, _ = _party_memory(_pb8(species=25, move_ids=(827, 0, 0, 0)))
    with pytest.raises(BDSPLiveError, match="movimientos fuera del catálogo BDSP"):
        BDSPPartyReader(bad_move).read()  # type: ignore[arg-type]

    bad_pp_up, _ = _party_memory(_pb8(species=25, move_pp_ups=(4, 0, 0, 0)))
    with pytest.raises(BDSPLiveError, match="PP Ups incoherentes"):
        BDSPPartyReader(bad_pp_up).read()  # type: ignore[arg-type]


def test_party_reader_rejects_runtime_hp_that_changes_mid_capture() -> None:
    client, cores = _party_memory(_pb8(species=25, current_hp=17, max_hp=42, level=12))
    client.unstable_at = cores[0] + 0x20

    with pytest.raises(BDSPLiveError, match="cambió durante la doble lectura"):
        BDSPPartyReader(client).read()  # type: ignore[arg-type]


def test_party_reader_rejects_incoherent_hp_instead_of_publishing_it() -> None:
    client, _ = _party_memory(_pb8(species=25, current_hp=43, max_hp=42, level=12))

    with pytest.raises(BDSPLiveError, match="HP incoherente 43/42"):
        BDSPPartyReader(client).read()  # type: ignore[arg-type]


def test_party_reader_rejects_a_runtime_root_that_changes() -> None:
    client, _ = _party_memory(_pb8(species=25, current_hp=17, max_hp=42, level=12))
    client.resolved_values = [client.pointer_base, client.pointer_base + 0x1000]

    with pytest.raises(BDSPLiveError, match="referencia runtime.*cambió"):
        BDSPPartyReader(client).read()  # type: ignore[arg-type]


def test_battle_reader_publishes_player_rows_and_party_indices() -> None:
    client, _ = _battle_memory(
        (359, 58, 67, 22, 0),
        (353, 58, 58, 23, 1),
    )

    result = BDSPBattleReader(client).read()  # type: ignore[arg-type]

    assert result is not None
    assert result.member_count == 2
    assert [
        (item.row, item.party_index, item.species_id, item.current_hp, item.max_hp, item.level)
        for item in result.pokemon
    ] == [
        (1, 0, 359, 58, 67, 22),
        (2, 1, 353, 58, 58, 23),
    ]


@pytest.mark.parametrize("initialized,ended", [(False, False), (False, True), (True, True)])
def test_battle_reader_returns_absent_before_or_after_battle(
    initialized: bool,
    ended: bool,
) -> None:
    client, _ = _battle_memory(
        (359, 58, 67, 22, 0),
        initialized=initialized,
        ended=ended,
    )

    assert BDSPBattleReader(client).read() is None  # type: ignore[arg-type]
    assert client.resolve_calls == 0


def test_battle_reader_treats_a_stable_null_typeinfo_as_an_unloaded_battleproc() -> None:
    type_info_slot = (
        BDSP_SP_130_HOST_PROFILE.guest_main
        + BDSP_SP_130_BATTLEPROC_TYPEINFO_OFFSET
    )
    client = FakeGuestClient({type_info_slot: struct.pack("<Q", 0)}, 0x10000)

    assert BDSPBattleReader(client).read() is None  # type: ignore[arg-type]
    assert client.resolve_calls == 0


def test_battle_reader_still_rejects_a_nonzero_invalid_typeinfo() -> None:
    type_info_slot = (
        BDSP_SP_130_HOST_PROFILE.guest_main
        + BDSP_SP_130_BATTLEPROC_TYPEINFO_OFFSET
    )
    client = FakeGuestClient({type_info_slot: struct.pack("<Q", 0x800)}, 0x10000)

    with pytest.raises(BDSPLiveError, match="TypeInfo inválido"):
        BDSPBattleReader(client).read()  # type: ignore[arg-type]


def test_battle_reader_rejects_a_core_that_changes_mid_capture() -> None:
    client, cores = _battle_memory((359, 58, 67, 22, 0))
    client.unstable_at = cores[0] + 0x18

    with pytest.raises(BDSPLiveError, match="CORE_PARAM.*cambió"):
        BDSPBattleReader(client).read()  # type: ignore[arg-type]


def test_battle_reader_rejects_duplicate_player_party_mapping() -> None:
    client, _ = _battle_memory(
        (359, 58, 67, 22, 0),
        (353, 58, 58, 23, 0),
    )

    with pytest.raises(BDSPLiveError, match="repite el índice de party 0"):
        BDSPBattleReader(client).read()  # type: ignore[arg-type]


def test_battle_reader_rejects_a_non_player_poke_id() -> None:
    client, _ = _battle_memory((359, 58, 67, 22, 12))

    with pytest.raises(BDSPLiveError, match="no pertenece a la party del jugador"):
        BDSPBattleReader(client).read()  # type: ignore[arg-type]


def test_presentation_reader_exposes_player_visible_hp_and_animation() -> None:
    client = _presentation_memory(player_hp=12, player_max_hp=58, hp_animation=True)

    result = BDSPBattlePresentationReader(client).read()  # type: ignore[arg-type]

    assert len(result.windows) == 4
    player = result.windows[0]
    assert (player.window_index, player.poke_id, player.is_player) == (0, 0, True)
    assert (player.current_hp, player.max_hp) == (12, 58)
    assert player.displayed is True
    assert player.hp_animation is True
    assert result.ui_instance == 0x2A000
    assert result.status_array == 0x2B000


def test_presentation_reader_rejects_wrong_typeinfo_identity() -> None:
    client = _presentation_memory(ui_class_name="AnotherClass")

    with pytest.raises(BDSPLiveError, match="no identifica BattleViewUISystem"):
        BDSPBattlePresentationReader(client).read()  # type: ignore[arg-type]


def test_presentation_reader_rejects_wrong_window_geometry() -> None:
    client = _presentation_memory(window_count=3)

    with pytest.raises(BDSPLiveError, match="se esperaban 4"):
        BDSPBattlePresentationReader(client).read()  # type: ignore[arg-type]
