from __future__ import annotations

import struct
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.bdsp_live import (
    BDSP_GENERAL_ITEM_IDS,
    BDSP_INVENTORY_BLOCK_SIZE,
    BDSP_INVENTORY_ITEM_COUNT,
    BDSP_INVENTORY_RECORD_SIZE,
    BDSP_MAX_MONEY,
    BDSP_MYSTATUS_RUNTIME_SIZE,
    BDSP_SP_130_BATTLEPROC_TYPEINFO_OFFSET,
    BDSP_SP_130_HOST_PROFILE,
    BDSP_SP_130_INVENTORY_POINTER,
    BDSP_SP_130_MYSTATUS_POINTER,
    BDSP_SP_130_PARTY_POINTER,
    BDSP_UTILITY_ITEM_IDS,
    BDSPLiveError,
    BDSPLiveWriter,
    BDSPBoxStorageSlot,
    BDSPMoneyReader,
    BDSPPartyReader,
    BDSPBoxRead,
    PB8_PARTY_SIZE,
    PB8_STORED_SIZE,
    calculate_bdsp_stats,
    decrypt_pb8,
    encrypt_pb8,
    parse_bdsp_box_pokemon,
    refresh_pb8_checksum,
)
from app.bdsp_tm_service import BDSPTM, BDSPTMProfile
from app.models import (
    PendingChange,
    PendingInventoryChange,
    PendingPartyHeal,
    PendingRoleChange,
    PendingTMTeach,
    PendingTeamChange,
)
from app.role_rules import role_from_markings
from tests.test_bdsp_live_foundation import _pb8


class _MutableGuestClient:
    profile = BDSP_SP_130_HOST_PROFILE

    def __init__(self, pokemon: bytes, *, item_id: int, quantity: int) -> None:
        self.party_object = 0x10000
        self.member_array = 0x20000
        self.owners = [0x30000 + index * 0x1000 for index in range(6)]
        self.cores = [0x40000 + index * 0x1000 for index in range(6)]
        self.calcs = [0x50000 + index * 0x1000 for index in range(6)]
        self.accessors = [0x60000 + index * 0x1000 for index in range(6)]
        self.owner = self.owners[0]
        self.core = self.cores[0]
        self.calc = self.calcs[0]
        self.accessor = self.accessors[0]
        self.inventory_data = 0x80020
        self.mystatus_data = 0xD0000
        self.name_object = 0xD1000
        inventory = bytearray(BDSP_INVENTORY_BLOCK_SIZE)
        offset = int(item_id) * BDSP_INVENTORY_RECORD_SIZE
        struct.pack_into("<iBBBxxxH", inventory, offset, quantity, 1, 0, 1, 7)
        mystatus = bytearray(BDSP_MYSTATUS_RUNTIME_SIZE)
        struct.pack_into("<QII", mystatus, 0, self.name_object, 0xC36B44CE, 123_456)
        mystatus[0x10:0x15] = bytes((1, 7, 2, 0, 1))
        name = "Timper".encode("utf-16le")
        self.segments: dict[int, bytearray] = {
            self.profile.guest_main: bytearray(self.profile.main_witness),
            self.party_object + 0x10: bytearray(struct.pack("<QI", self.member_array, 1)),
            self.member_array + 0x18: bytearray(struct.pack("<Q", 6)),
            self.member_array + 0x20: bytearray(struct.pack("<6Q", *self.owners)),
            self.inventory_data - 8: bytearray(struct.pack("<Q", BDSP_INVENTORY_ITEM_COUNT)),
            self.inventory_data: inventory,
            self.mystatus_data: mystatus,
            self.name_object + 0x10: bytearray(struct.pack("<I", 6) + name),
        }
        empty = encrypt_pb8(bytes(PB8_PARTY_SIZE))
        for index, (owner, core, calc, accessor) in enumerate(zip(
            self.owners, self.cores, self.calcs, self.accessors,
        )):
            raw = pokemon if index == 0 else empty
            self.segments[owner + 0x10] = bytearray(struct.pack("<3Q", core, calc, accessor))
            self.segments[core + 0x18] = bytearray(struct.pack("<Q", PB8_STORED_SIZE))
            self.segments[calc + 0x18] = bytearray(struct.pack("<Q", PB8_PARTY_SIZE - PB8_STORED_SIZE))
            self.segments[core + 0x20] = bytearray(raw[:PB8_STORED_SIZE])
            self.segments[calc + 0x20] = bytearray(raw[PB8_STORED_SIZE:])
        self.session = SimpleNamespace(
            process=SimpleNamespace(pid=77),
            guest_to_host_delta=0x1000000,
            profile=self.profile,
        )

    def install_party_slot(self, slot: int, pokemon: bytes, *, member_count: int) -> None:
        index = int(slot) - 1
        self.segments[self.cores[index] + 0x20][:] = pokemon[:PB8_STORED_SIZE]
        self.segments[self.calcs[index] + 0x20][:] = pokemon[PB8_STORED_SIZE:]
        struct.pack_into(
            "<I", self.segments[self.party_object + 0x10], 8, int(member_count),
        )

    def resolve_main_pointer(self, jumps) -> int:
        if tuple(jumps) == tuple(BDSP_SP_130_PARTY_POINTER):
            return self.party_object
        if tuple(jumps) == tuple(BDSP_SP_130_INVENTORY_POINTER):
            return self.inventory_data
        if tuple(jumps) == tuple(BDSP_SP_130_MYSTATUS_POINTER):
            return self.mystatus_data
        raise AssertionError(f"Cadena inesperada: {jumps!r}")

    def _range(self, address: int, size: int) -> tuple[bytearray, int]:
        address, size = int(address), int(size)
        for start, data in self.segments.items():
            relative = address - start
            if 0 <= relative and relative + size <= len(data):
                return data, relative
        raise AssertionError(f"Lectura/escritura fuera del fixture: 0x{address:X}+{size}")

    def read_memory(self, address: int, size: int) -> bytes:
        data, relative = self._range(address, size)
        return bytes(data[relative:relative + int(size)])

    def write_memory(self, address: int, value: bytes) -> None:
        data, relative = self._range(address, len(value))
        data[relative:relative + len(value)] = value


class _Transport:
    def __init__(self, client: _MutableGuestClient, *, fail_on_write: int | None = None) -> None:
        self.client = client
        self.fail_on_write = fail_on_write
        self.write_calls = 0
        self.closed = False

    def open(self, pid: int):
        assert pid == 77
        return object()

    def close(self, _handle) -> None:
        self.closed = True

    def assert_writable(self, _handle, _address: int, _size: int) -> None:
        return None

    def read(self, _handle, host_address: int, size: int) -> bytes:
        guest = int(host_address) - int(self.client.session.guest_to_host_delta)
        return self.client.read_memory(guest, size)

    def write(self, _handle, host_address: int, value: bytes) -> None:
        self.write_calls += 1
        if self.fail_on_write == self.write_calls:
            raise OSError("fallo de escritura simulado")
        guest = int(host_address) - int(self.client.session.guest_to_host_delta)
        self.client.write_memory(guest, value)


class _NoBattleReader:
    def __init__(self, _client) -> None:
        pass

    def read(self):
        return None


class _SingleBoxReader:
    def __init__(self, client: _MutableGuestClient) -> None:
        self.client = client

    def read(self) -> BDSPBoxRead:
        raw = self.client.read_memory(self.client.box_data, PB8_PARTY_SIZE)
        pokemon = parse_bdsp_box_pokemon(raw, box=1, slot=1)
        assert pokemon is not None
        return BDSPBoxRead(
            pokemon=(replace(pokemon, data_pointer=self.client.box_data),),
            total_slots=1200,
            empty_slots=1199,
            pointer_base=self.client.box_pointer_base,
        )


class _ResizeBoxReader:
    def __init__(self, client: _MutableGuestClient) -> None:
        self.client = client

    def read(self) -> BDSPBoxRead:
        raw = self.client.read_memory(self.client.box_data, PB8_PARTY_SIZE)
        pokemon = parse_bdsp_box_pokemon(raw, box=1, slot=1)
        empty = encrypt_pb8(bytes(PB8_PARTY_SIZE))
        storage = []
        for box in range(1, 41):
            for slot in range(1, 31):
                storage.append(BDSPBoxStorageSlot(
                    box=box,
                    slot=slot,
                    data_pointer=(
                        self.client.box_data
                        if (box, slot) == (1, 1)
                        else 0x200000 + ((box - 1) * 30 + slot) * 0x200
                    ),
                    encrypted=raw if (box, slot) == (1, 1) else empty,
                ))
        return BDSPBoxRead(
            pokemon=(
                () if pokemon is None else
                (replace(pokemon, data_pointer=self.client.box_data),)
            ),
            total_slots=1200,
            empty_slots=1200 if pokemon is None else 1199,
            pointer_base=self.client.box_pointer_base,
            storage_slots=tuple(storage),
        )


class _FaintBoxReader:
    """Matriz completa con un origen ocupado y un Cementerio mutable."""

    def __init__(self, client: _MutableGuestClient) -> None:
        self.client = client

    def read(self) -> BDSPBoxRead:
        empty = encrypt_pb8(bytes(PB8_PARTY_SIZE))
        source_raw = self.client.read_memory(self.client.box_data, PB8_PARTY_SIZE)
        grave_raw = self.client.read_memory(self.client.grave_data, PB8_PARTY_SIZE)
        raw_by_pos = {(1, 1): source_raw, (4, 1): grave_raw}
        address_by_pos = {
            (1, 1): self.client.box_data,
            (4, 1): self.client.grave_data,
        }
        storage = []
        pokemon = []
        for box in range(1, 41):
            for slot in range(1, 31):
                pos = (box, slot)
                raw = raw_by_pos.get(pos, empty)
                address = address_by_pos.get(
                    pos, 0x200000 + ((box - 1) * 30 + slot) * 0x200,
                )
                storage.append(BDSPBoxStorageSlot(
                    box=box, slot=slot, data_pointer=address, encrypted=raw,
                ))
                parsed = parse_bdsp_box_pokemon(raw, box=box, slot=slot)
                if parsed is not None:
                    pokemon.append(replace(parsed, data_pointer=address))
        return BDSPBoxRead(
            pokemon=tuple(pokemon), total_slots=1200,
            empty_slots=1200 - len(pokemon),
            pointer_base=self.client.box_pointer_base,
            storage_slots=tuple(storage),
        )


def _profile(*, item_id: int = 328, move_id: int = 85, base_pp: int = 15) -> BDSPTMProfile:
    return BDSPTMProfile(
        source=Path("personal_masterdatas"),
        tms={1: BDSPTM(number=1, item_id=item_id, move_id=move_id)},
        compatibility={(300, 0): (1, 0, 0, 0)},
        move_damage_types={move_id: 2},
        move_base_pp={move_id: base_pp},
        valid_moves={move_id},
        personal_stats={
            (1, 0): (45, 49, 49, 65, 65, 45),
            (300, 0): (50, 45, 45, 35, 35, 50),
        },
    )


def _change(*, quantity: int = 2) -> PendingTMTeach:
    return PendingTMTeach(
        role="Líbero",
        pokemon_slot=1,
        pokemon="Skibidi",
        species="Skitty",
        move_slot=2,
        old_move="Gruñido",
        old_move_id=45,
        new_move="Rayo",
        new_move_id=85,
        pokemon_identity=f"300:{0xAABBCCDD}:123:456",
        item_id=328,
        tm_number=1,
        item_name="MT01",
        quantity_before=quantity,
    )


def _writer(client: _MutableGuestClient, transport: _Transport) -> BDSPLiveWriter:
    return BDSPLiveWriter(
        client,
        tm_profile_getter=_profile,
        transport_factory=lambda: transport,
        battle_reader_factory=_NoBattleReader,
    )


def _swap_writer(client: _MutableGuestClient, transport: _Transport) -> BDSPLiveWriter:
    return BDSPLiveWriter(
        client,
        tm_profile_getter=_profile,
        transport_factory=lambda: transport,
        battle_reader_factory=_NoBattleReader,
        box_reader_factory=_SingleBoxReader,
    )


def _resize_writer(client: _MutableGuestClient, transport: _Transport) -> BDSPLiveWriter:
    return BDSPLiveWriter(
        client,
        tm_profile_getter=_profile,
        transport_factory=lambda: transport,
        battle_reader_factory=_NoBattleReader,
        box_reader_factory=_ResizeBoxReader,
    )


def _faint_writer(client: _MutableGuestClient, transport: _Transport) -> BDSPLiveWriter:
    return BDSPLiveWriter(
        client,
        tm_profile_getter=_profile,
        transport_factory=lambda: transport,
        battle_reader_factory=_NoBattleReader,
        box_reader_factory=_FaintBoxReader,
    )


def _install_box(client: _MutableGuestClient, pokemon: bytes) -> None:
    client.box_pointer_base = 0x90000
    client.box_data = 0xA0020
    client.segments[client.box_data] = bytearray(pokemon)


def _install_faint_boxes(
    client: _MutableGuestClient, incoming: bytes, grave: bytes,
) -> None:
    client.box_pointer_base = 0x90000
    client.box_data = 0xA0020
    client.grave_data = 0xB0020
    client.segments[client.box_data] = bytearray(incoming)
    client.segments[client.grave_data] = bytearray(grave)


def _swap_change() -> PendingTeamChange:
    return PendingTeamChange(
        operation="swap-party-box", party_slot=1, box=1, box_slot=1,
        incoming_pokemon="Entrante", incoming_species="Turtwig",
        outgoing_pokemon="Saliente", outgoing_species="Skitty",
        incoming_role="Líbero",
        incoming_identity=f"387:{0x11223344}:321:654",
        outgoing_identity=f"300:{0xAABBCCDD}:123:456",
    )


def test_bdsp_party_box_swap_moves_all_344_bytes_and_inherits_role() -> None:
    outgoing = _pb8(species=300, current_hp=17, max_hp=25, level=12)
    incoming = _pb8(
        species=387, pid=0x11223344, tid=321, sid=654,
        current_hp=31, max_hp=31, level=16,
    )
    client = _MutableGuestClient(outgoing, item_id=328, quantity=2)
    _install_box(client, incoming)
    transport = _Transport(client)

    receipt = _swap_writer(client, transport).apply([_swap_change()])

    party = BDSPPartyReader(client).read().pokemon[0]
    boxed = parse_bdsp_box_pokemon(
        client.read_memory(client.box_data, PB8_PARTY_SIZE), box=1, slot=1,
    )
    assert party.species_id == 387
    assert (party.current_hp, party.max_hp, party.level) == (31, 31, 16)
    assert role_from_markings(party.markings, layout=2)[0] == "Líbero"
    assert boxed is not None and boxed.species_id == 300
    assert transport.write_calls == 3
    assert [len(watch.expected) for watch in receipt.memory_watches] == [328, 16, 344]


def test_bdsp_party_box_swap_rolls_back_core_calc_and_box_on_failure() -> None:
    outgoing = _pb8(species=300, current_hp=17, max_hp=25, level=12)
    incoming = _pb8(
        species=387, pid=0x11223344, tid=321, sid=654,
        current_hp=31, max_hp=31, level=16,
    )
    client = _MutableGuestClient(outgoing, item_id=328, quantity=2)
    _install_box(client, incoming)
    transport = _Transport(client, fail_on_write=3)

    with pytest.raises(BDSPLiveError, match="restauró y verificó los tres bloques"):
        _swap_writer(client, transport).apply([_swap_change()])

    assert client.read_memory(client.core + 0x20, PB8_STORED_SIZE) == outgoing[:PB8_STORED_SIZE]
    assert client.read_memory(client.calc + 0x20, PB8_PARTY_SIZE - PB8_STORED_SIZE) == outgoing[PB8_STORED_SIZE:]
    assert client.read_memory(client.box_data, PB8_PARTY_SIZE) == incoming


def test_bdsp_tail_member_can_be_deposited_with_count_and_empty_readback() -> None:
    first = _pb8(species=300, current_hp=17, max_hp=25, level=12)
    outgoing = _pb8(
        species=387, pid=0x11223344, tid=321, sid=654,
        current_hp=31, max_hp=31, level=16,
    )
    empty = encrypt_pb8(bytes(PB8_PARTY_SIZE))
    client = _MutableGuestClient(first, item_id=328, quantity=2)
    client.install_party_slot(2, outgoing, member_count=2)
    _install_box(client, empty)
    transport = _Transport(client)
    change = PendingTeamChange(
        operation="party-to-box", party_slot=2,
        outgoing_pokemon="Turtwig", outgoing_species="Turtwig",
        outgoing_identity=f"387:{0x11223344}:321:654",
    )

    receipt = _resize_writer(client, transport).apply([change])

    party = BDSPPartyReader(client).read()
    boxed = parse_bdsp_box_pokemon(
        client.read_memory(client.box_data, PB8_PARTY_SIZE), box=1, slot=1,
    )
    assert party.member_count == 1
    assert [pokemon.species_id for pokemon in party.pokemon] == [300]
    assert party.storage_slots[1].encrypted == empty
    assert boxed is not None and boxed.species_id == 387
    assert (change.box, change.box_slot) == (1, 1)
    assert transport.write_calls == 4
    assert [len(watch.expected) for watch in receipt.memory_watches] == [344, 328, 16, 4]


def test_bdsp_box_member_can_be_appended_and_source_gets_canonical_empty() -> None:
    first = _pb8(species=300, current_hp=17, max_hp=25, level=12)
    incoming = _pb8(
        species=387, pid=0x11223344, tid=321, sid=654,
        current_hp=31, max_hp=31, level=16,
    )
    empty = encrypt_pb8(bytes(PB8_PARTY_SIZE))
    client = _MutableGuestClient(first, item_id=328, quantity=2)
    _install_box(client, incoming)
    transport = _Transport(client)
    change = PendingTeamChange(
        operation="box-to-party", party_slot=2, box=1, box_slot=1,
        incoming_pokemon="Turtwig", incoming_species="Turtwig",
        incoming_role="Mago",
        incoming_identity=f"387:{0x11223344}:321:654",
    )

    receipt = _resize_writer(client, transport).apply([change])

    party = BDSPPartyReader(client).read()
    assert party.member_count == 2
    assert [pokemon.species_id for pokemon in party.pokemon] == [300, 387]
    assert role_from_markings(party.pokemon[1].markings, layout=2)[0] == "Mago"
    assert client.read_memory(client.box_data, PB8_PARTY_SIZE) == empty
    assert transport.write_calls == 4
    assert [len(watch.expected) for watch in receipt.memory_watches] == [328, 16, 344, 4]


def test_bdsp_tail_deposit_rolls_back_party_box_and_count_on_failure() -> None:
    first = _pb8(species=300, current_hp=17, max_hp=25, level=12)
    outgoing = _pb8(
        species=387, pid=0x11223344, tid=321, sid=654,
        current_hp=31, max_hp=31, level=16,
    )
    empty = encrypt_pb8(bytes(PB8_PARTY_SIZE))
    client = _MutableGuestClient(first, item_id=328, quantity=2)
    client.install_party_slot(2, outgoing, member_count=2)
    _install_box(client, empty)
    transport = _Transport(client, fail_on_write=4)
    change = PendingTeamChange(
        operation="party-to-box", party_slot=2,
        outgoing_identity=f"387:{0x11223344}:321:654",
    )

    with pytest.raises(BDSPLiveError, match="restauró y verificó los 4 bloques"):
        _resize_writer(client, transport).apply([change])

    party = BDSPPartyReader(client).read()
    assert party.member_count == 2
    assert [pokemon.species_id for pokemon in party.pokemon] == [300, 387]
    assert client.read_memory(client.box_data, PB8_PARTY_SIZE) == empty


def test_bdsp_middle_deposit_compacts_exact_344_byte_members_and_empties_tail() -> None:
    members = tuple(
        _pb8(species=species, pid=0x1000 + index, level=10 + index)
        for index, species in enumerate((300, 387, 17, 79, 21, 25), start=1)
    )
    empty = encrypt_pb8(bytes(PB8_PARTY_SIZE))
    client = _MutableGuestClient(members[0], item_id=328, quantity=2)
    for slot, raw in enumerate(members[1:], start=2):
        client.install_party_slot(slot, raw, member_count=6)
    _install_box(client, empty)
    transport = _Transport(client)
    change = PendingTeamChange(
        operation="party-to-box", party_slot=2,
        outgoing_identity=f"387:{0x1002}:123:456",
    )

    receipt = _resize_writer(client, transport).apply([change])

    party = BDSPPartyReader(client).read()
    assert party.member_count == 5
    assert [pokemon.species_id for pokemon in party.pokemon] == [300, 17, 79, 21, 25]
    expected_storage = [members[0], *members[2:], empty]
    assert [item.encrypted for item in party.storage_slots] == expected_storage
    assert client.read_memory(client.box_data, PB8_PARTY_SIZE) == members[1]
    assert transport.write_calls == 12
    assert [len(watch.expected) for watch in receipt.memory_watches] == [
        344, 328, 16, 328, 16, 328, 16, 328, 16, 328, 16, 4,
    ]


def test_bdsp_middle_deposit_rolls_back_every_shift_if_count_write_fails() -> None:
    members = tuple(
        _pb8(species=species, pid=0x2000 + index, level=10 + index)
        for index, species in enumerate((300, 387, 17, 79, 21, 25), start=1)
    )
    empty = encrypt_pb8(bytes(PB8_PARTY_SIZE))
    client = _MutableGuestClient(members[0], item_id=328, quantity=2)
    for slot, raw in enumerate(members[1:], start=2):
        client.install_party_slot(slot, raw, member_count=6)
    _install_box(client, empty)
    transport = _Transport(client, fail_on_write=12)
    change = PendingTeamChange(
        operation="party-to-box", party_slot=2,
        outgoing_identity=f"387:{0x2002}:123:456",
    )

    with pytest.raises(BDSPLiveError, match="restauró y verificó los 12 bloques"):
        _resize_writer(client, transport).apply([change])

    party = BDSPPartyReader(client).read()
    assert party.member_count == 6
    assert [item.encrypted for item in party.storage_slots] == list(members)
    assert client.read_memory(client.box_data, PB8_PARTY_SIZE) == empty


def _faint_change() -> PendingTeamChange:
    return PendingTeamChange(
        operation="replace-fainted", party_slot=1,
        box=1, box_slot=1, graveyard_box=4, graveyard_box_slot=1,
        outgoing_pokemon="Debilitado", outgoing_species="Skitty",
        incoming_pokemon="Sustituto", incoming_species="Turtwig",
        incoming_role="Líbero",
        outgoing_identity=f"300:{0xAABBCCDD}:123:456",
        incoming_identity=f"387:{0x11223344}:321:654",
    )


def test_bdsp_faint_replacement_moves_exact_party_to_grave_and_empties_source() -> None:
    outgoing = _pb8(
        species=300, current_hp=0, max_hp=25, level=12, markings=1,
    )
    incoming = _pb8(
        species=387, pid=0x11223344, tid=321, sid=654,
        current_hp=31, max_hp=31, level=16,
    )
    empty = encrypt_pb8(bytes(PB8_PARTY_SIZE))
    client = _MutableGuestClient(outgoing, item_id=328, quantity=2)
    _install_faint_boxes(client, incoming, empty)
    transport = _Transport(client)
    change = _faint_change()

    receipt = _faint_writer(client, transport).apply([change])

    party = BDSPPartyReader(client).read()
    assert party.member_count == 1
    assert party.pokemon[0].species_id == 387
    assert role_from_markings(party.pokemon[0].markings, layout=2)[0] == "Líbero"
    assert client.read_memory(client.box_data, PB8_PARTY_SIZE) == empty
    assert client.read_memory(client.grave_data, PB8_PARTY_SIZE) == outgoing
    assert change.incoming_role == "Líbero"
    assert transport.write_calls == 4
    assert [len(watch.expected) for watch in receipt.memory_watches] == [344, 344, 328, 16]


def test_bdsp_faint_replacement_rolls_back_party_source_and_grave_on_failure() -> None:
    outgoing = _pb8(
        species=300, current_hp=0, max_hp=25, level=12, markings=1,
    )
    incoming = _pb8(
        species=387, pid=0x11223344, tid=321, sid=654,
        current_hp=31, max_hp=31, level=16,
    )
    empty = encrypt_pb8(bytes(PB8_PARTY_SIZE))
    client = _MutableGuestClient(outgoing, item_id=328, quantity=2)
    _install_faint_boxes(client, incoming, empty)
    transport = _Transport(client, fail_on_write=4)

    with pytest.raises(BDSPLiveError, match="restauró y verificó los 4 bloques"):
        _faint_writer(client, transport).apply([_faint_change()])

    party = BDSPPartyReader(client).read()
    assert party.member_count == 1
    assert party.storage_slots[0].encrypted == outgoing
    assert client.read_memory(client.box_data, PB8_PARTY_SIZE) == incoming
    assert client.read_memory(client.grave_data, PB8_PARTY_SIZE) == empty


def test_bdsp_faint_replacement_rejects_a_party_member_that_is_alive() -> None:
    outgoing = _pb8(
        species=300, current_hp=1, max_hp=25, level=12, markings=1,
    )
    incoming = _pb8(
        species=387, pid=0x11223344, tid=321, sid=654,
        current_hp=31, max_hp=31, level=16,
    )
    empty = encrypt_pb8(bytes(PB8_PARTY_SIZE))
    client = _MutableGuestClient(outgoing, item_id=328, quantity=2)
    _install_faint_boxes(client, incoming, empty)
    transport = _Transport(client)

    with pytest.raises(BDSPLiveError, match="ya no está debilitado"):
        _faint_writer(client, transport).apply([_faint_change()])

    assert transport.write_calls == 0
    assert client.read_memory(client.box_data, PB8_PARTY_SIZE) == incoming
    assert client.read_memory(client.grave_data, PB8_PARTY_SIZE) == empty


def test_bdsp_tm_write_is_atomic_and_preserves_the_rest_of_saveitem() -> None:
    original = _pb8(species=300, move_ids=(33, 45, 0, 0), move_pp=(35, 40, 0, 0))
    client = _MutableGuestClient(original, item_id=328, quantity=2)
    transport = _Transport(client)
    item_address = client.inventory_data + 328 * BDSP_INVENTORY_RECORD_SIZE
    item_before = client.read_memory(item_address, BDSP_INVENTORY_RECORD_SIZE)

    receipt = _writer(client, transport).apply([_change()])

    verified = BDSPPartyReader(client).read().pokemon[0]
    item_after = client.read_memory(item_address, BDSP_INVENTORY_RECORD_SIZE)
    assert verified.move_ids == (33, 85, 0, 0)
    assert verified.move_pp == (35, 15, 0, 0)
    assert verified.move_pp_ups == (0, 0, 0, 0)
    assert struct.unpack_from("<i", item_after)[0] == 1
    assert item_after[4:] == item_before[4:]
    assert transport.write_calls == 2
    assert transport.closed is True
    assert receipt.applied_count == 1
    assert [len(watch.expected) for watch in receipt.memory_watches] == [328, 12]


def test_bdsp_money_reader_validates_the_complete_runtime_mystatus() -> None:
    client = _MutableGuestClient(_pb8(species=300), item_id=50, quantity=7)

    result = BDSPMoneyReader(client).read()

    assert result.trainer_name == "Timper"
    assert result.trainer_id == 0xC36B44CE
    assert result.money == 123_456
    assert (result.badge_count, result.rom_code) == (2, 1)
    assert result.data_pointer == client.mystatus_data
    assert len(result.raw) == BDSP_MYSTATUS_RUNTIME_SIZE


def test_bdsp_utilities_write_the_exact_item_ids_and_bdsp_money_limit() -> None:
    client = _MutableGuestClient(_pb8(species=300), item_id=50, quantity=7)
    # El ID 79 es Repelente normal y debe permanecer intacto. El Máximo (77)
    # todavía no existe, igual que en la reproducción física de alpha.85.
    struct.pack_into(
        "<iBBBxxxH", client.segments[client.inventory_data],
        79 * BDSP_INVENTORY_RECORD_SIZE, 3, 1, 0, 0, 9,
    )
    struct.pack_into(
        "<iBBBxxxH", client.segments[client.inventory_data],
        217 * BDSP_INVENTORY_RECORD_SIZE, 0, 0, 0, 0, 12,
    )
    inventory_before = bytes(client.segments[client.inventory_data])
    mystatus_before = bytes(client.segments[client.mystatus_data])
    transport = _Transport(client)
    changes = [
        PendingInventoryChange("rare-candy", "Caramelo Raro", 999),
        PendingInventoryChange("max-repel", "Repelente Máximo", 999),
        PendingInventoryChange("money-max", "Dinero", BDSP_MAX_MONEY),
    ]

    receipt = _writer(client, transport).apply(changes)

    inventory_after = bytes(client.segments[client.inventory_data])
    expected_inventory = bytearray(inventory_before)
    struct.pack_into("<i", expected_inventory, 50 * BDSP_INVENTORY_RECORD_SIZE, 999)
    struct.pack_into(
        "<iBBBxxxH", expected_inventory,
        77 * BDSP_INVENTORY_RECORD_SIZE, 999, 0, 0, 0, 13,
    )
    expected_mystatus = bytearray(mystatus_before)
    struct.pack_into("<I", expected_mystatus, 0x0C, BDSP_MAX_MONEY)
    assert inventory_after == bytes(expected_inventory)
    assert bytes(client.segments[client.mystatus_data]) == bytes(expected_mystatus)
    assert BDSPMoneyReader(client).read().money == BDSP_MAX_MONEY
    assert struct.unpack_from(
        "<i", inventory_after, 79 * BDSP_INVENTORY_RECORD_SIZE,
    )[0] == 3
    assert transport.write_calls == 3
    assert receipt.applied_count == 3
    assert [len(watch.expected) for watch in receipt.memory_watches] == [12, 12, 4]


def test_bdsp_utility_creates_an_unowned_general_item_with_the_next_pocket_order() -> None:
    client = _MutableGuestClient(_pb8(species=300), item_id=328, quantity=2)
    struct.pack_into(
        "<iBBBxxxH", client.segments[client.inventory_data],
        217 * BDSP_INVENTORY_RECORD_SIZE, 0, 0, 0, 0, 8,
    )
    transport = _Transport(client)
    change = PendingInventoryChange("rare-candy", "Caramelo Raro", 999)

    receipt = _writer(client, transport).apply([change])

    offset = 50 * BDSP_INVENTORY_RECORD_SIZE
    assert bytes(client.segments[client.inventory_data][offset:offset + 12]) == struct.pack(
        "<iBBBxxxH", 999, 0, 0, 0, 9,
    )
    assert transport.write_calls == 1
    assert transport.closed is True
    assert receipt.applied_count == 1


def test_bdsp_utility_rolls_back_both_items_when_money_write_fails() -> None:
    client = _MutableGuestClient(_pb8(species=300), item_id=50, quantity=7)
    struct.pack_into(
        "<iBBBxxxH", client.segments[client.inventory_data],
        79 * BDSP_INVENTORY_RECORD_SIZE, 3, 1, 0, 0, 9,
    )
    inventory_before = bytes(client.segments[client.inventory_data])
    mystatus_before = bytes(client.segments[client.mystatus_data])
    transport = _Transport(client, fail_on_write=3)
    changes = [
        PendingInventoryChange("rare-candy", "Caramelo Raro", 999),
        PendingInventoryChange("max-repel", "Repelente Máximo", 999),
        PendingInventoryChange("money-max", "Dinero", BDSP_MAX_MONEY),
    ]

    with pytest.raises(BDSPLiveError, match="restauró y verificó mochila y MYSTATUS"):
        _writer(client, transport).apply(changes)

    assert bytes(client.segments[client.inventory_data]) == inventory_before
    assert bytes(client.segments[client.mystatus_data]) == mystatus_before
    assert transport.write_calls == 6
    assert transport.closed is True


def test_bdsp_utility_ids_match_the_pkhex_spanish_catalog() -> None:
    names = (
        Path(__file__).parents[1] / "data" / "pkhex_items_es.txt"
    ).read_text(encoding="utf-8-sig").splitlines()

    assert names[50] == "Caramelo Raro"
    assert names[77] == "Repelente Máximo"
    assert names[79] == "Repelente"
    assert BDSP_UTILITY_ITEM_IDS == {"rare-candy": 50, "max-repel": 77}
    assert 50 in BDSP_GENERAL_ITEM_IDS
    assert 77 in BDSP_GENERAL_ITEM_IDS


def test_bdsp_tm_write_accepts_the_demonstrated_unloaded_battleproc_state() -> None:
    original = _pb8(species=300, move_ids=(33, 45, 0, 0), move_pp=(35, 40, 0, 0))
    client = _MutableGuestClient(original, item_id=328, quantity=2)
    client.segments[
        client.profile.guest_main + BDSP_SP_130_BATTLEPROC_TYPEINFO_OFFSET
    ] = bytearray(struct.pack("<Q", 0))
    transport = _Transport(client)
    writer = BDSPLiveWriter(
        client,
        tm_profile_getter=_profile,
        transport_factory=lambda: transport,
    )

    writer.apply([_change()])

    assert BDSPPartyReader(client).read().pokemon[0].move_ids == (33, 85, 0, 0)
    assert transport.write_calls == 2


def test_bdsp_tm_write_keeps_blocking_a_nonzero_invalid_battleproc_typeinfo() -> None:
    original = _pb8(species=300, move_ids=(33, 45, 0, 0), move_pp=(35, 40, 0, 0))
    client = _MutableGuestClient(original, item_id=328, quantity=2)
    client.segments[
        client.profile.guest_main + BDSP_SP_130_BATTLEPROC_TYPEINFO_OFFSET
    ] = bytearray(struct.pack("<Q", 0x800))
    transport = _Transport(client)
    writer = BDSPLiveWriter(
        client,
        tm_profile_getter=_profile,
        transport_factory=lambda: transport,
    )

    with pytest.raises(BDSPLiveError, match="TypeInfo inválido"):
        writer.apply([_change()])

    assert transport.write_calls == 0
    assert transport.closed is False


def test_bdsp_tm_write_rejects_a_stale_quantity_before_opening_rw() -> None:
    original = _pb8(species=300, move_ids=(33, 45, 0, 0), move_pp=(35, 40, 0, 0))
    client = _MutableGuestClient(original, item_id=328, quantity=1)
    transport = _Transport(client)

    with pytest.raises(BDSPLiveError, match="cantidad viva"):
        _writer(client, transport).apply([_change(quantity=2)])

    assert transport.write_calls == 0
    assert transport.closed is False


def test_bdsp_tm_write_rolls_back_the_pokemon_if_item_write_fails() -> None:
    original = _pb8(species=300, move_ids=(33, 45, 0, 0), move_pp=(35, 40, 0, 0))
    client = _MutableGuestClient(original, item_id=328, quantity=2)
    transport = _Transport(client, fail_on_write=2)
    core_address = client.core + 0x20
    item_address = client.inventory_data + 328 * BDSP_INVENTORY_RECORD_SIZE
    core_before = client.read_memory(core_address, PB8_STORED_SIZE)
    item_before = client.read_memory(item_address, BDSP_INVENTORY_RECORD_SIZE)

    with pytest.raises(BDSPLiveError, match="restauró y verificó"):
        _writer(client, transport).apply([_change()])

    assert client.read_memory(core_address, PB8_STORED_SIZE) == core_before
    assert client.read_memory(item_address, BDSP_INVENTORY_RECORD_SIZE) == item_before
    assert transport.write_calls == 4
    assert transport.closed is True


def test_bdsp_move_deletion_compacts_ids_pp_and_pp_ups_in_runtime_pb8() -> None:
    original = _pb8(
        species=300,
        move_ids=(33, 45, 85, 98),
        move_pp=(35, 40, 15, 10),
        move_pp_ups=(0, 1, 2, 3),
    )
    client = _MutableGuestClient(original, item_id=328, quantity=2)
    transport = _Transport(client)
    change = PendingChange(
        role="Líbero", pokemon_slot=1, pokemon="Skibidi", species="Skitty",
        move_slot=2, old_move="Gruñido", old_move_id=45,
        new_move="—", new_move_id=0,
        pokemon_identity=f"300:{0xAABBCCDD}:123:456",
    )

    _writer(client, transport).apply([change])

    verified = BDSPPartyReader(client).read().pokemon[0]
    assert verified.move_ids == (33, 85, 98, 0)
    assert verified.move_pp == (35, 15, 10, 0)
    assert verified.move_pp_ups == (0, 2, 3, 0)
    assert transport.write_calls == 1


def test_bdsp_party_heal_restores_hp_status_and_pp_without_touching_training() -> None:
    encrypted = _pb8(
        species=300, current_hp=3, max_hp=25, level=12,
        move_ids=(33, 45, 85, 0), move_pp=(1, 2, 3, 0),
        move_pp_ups=(0, 1, 2, 0), evs=(12, 34, 56, 78, 90, 110),
    )
    plain = bytearray(decrypt_pb8(encrypted))
    struct.pack_into("<I", plain, 0x94, 0x20)
    refresh_pb8_checksum(plain)
    client = _MutableGuestClient(encrypt_pb8(bytes(plain)), item_id=328, quantity=2)
    transport = _Transport(client)
    profile = replace(
        _profile(),
        move_base_pp={33: 35, 45: 40, 85: 15},
        valid_moves={33, 45, 85},
    )
    writer = BDSPLiveWriter(
        client, tm_profile_getter=lambda: profile,
        transport_factory=lambda: transport,
        battle_reader_factory=_NoBattleReader,
    )
    change = PendingPartyHeal(
        pokemon_slot=1, pokemon="Skibidi", species="Skitty",
        pokemon_identity=f"300:{0xAABBCCDD}:123:456",
    )

    writer.apply([change])

    verified = BDSPPartyReader(client).read().pokemon[0]
    verified_plain = decrypt_pb8(verified.encrypted)
    assert verified.current_hp == verified.max_hp == 25
    assert struct.unpack_from("<I", verified_plain, 0x94)[0] == 0
    assert verified.move_pp == (35, 48, 21, 0)
    assert verified.evs == (12, 34, 56, 78, 90, 110)


def test_bdsp_role_write_changes_only_the_canonical_marker() -> None:
    original = _pb8(species=300, markings=0)
    client = _MutableGuestClient(original, item_id=328, quantity=2)
    transport = _Transport(client)
    change = PendingRoleChange(
        pokemon_slot=1, pokemon="Skibidi", species="Skitty",
        old_role="SIN ROL", new_role="Mago",
        pokemon_identity=f"300:{0xAABBCCDD}:123:456",
    )

    _writer(client, transport).apply([change])

    verified = BDSPPartyReader(client).read().pokemon[0]
    assert role_from_markings(verified.markings, layout=2)[0] == "Mago"
    assert verified.markings == (False, False, True, False, False, False)
    assert transport.write_calls == 1


def test_bdsp_role_ev_transaction_recalculates_core_calc_and_preserves_missing_hp() -> None:
    old_stats = calculate_bdsp_stats(
        (45, 49, 49, 65, 65, 45), (31, 31, 31, 31, 31, 31),
        (0, 0, 0, 0, 0, 0), 24, 3,
    )
    original = _pb8(
        species=1, current_hp=50, max_hp=old_stats[0], level=24,
        stat_nature_id=3, ivs=(31, 31, 31, 31, 31, 31),
        evs=(0, 0, 0, 0, 0, 0), stats=old_stats,
    )
    client = _MutableGuestClient(original, item_id=328, quantity=2)
    transport = _Transport(client)
    change = PendingRoleChange(
        pokemon_slot=1, pokemon="Bulbasaur", species="Bulbasaur",
        old_role="SIN ROL", new_role="Tanque",
        pokemon_identity=f"1:{0xAABBCCDD}:123:456",
        old_evs=(0, 0, 0, 0, 0, 0),
        new_evs=(252, 0, 252, 0, 0, 0),
    )

    receipt = _writer(client, transport).apply([change])

    verified = BDSPPartyReader(client).read().pokemon[0]
    assert verified.evs == (252, 0, 252, 0, 0, 0)
    assert verified.stats == calculate_bdsp_stats(
        (45, 49, 49, 65, 65, 45), (31, 31, 31, 31, 31, 31),
        verified.evs, 24, 3,
    )
    assert verified.max_hp == 78
    assert verified.current_hp == 65  # conserva los 13 PS que faltaban
    assert role_from_markings(verified.markings, layout=2)[0] == "Tanque"
    assert transport.write_calls == 2
    assert len(receipt.memory_watches) == 2


def test_bdsp_role_ev_transaction_rolls_back_core_and_calc_together() -> None:
    old_stats = calculate_bdsp_stats(
        (45, 49, 49, 65, 65, 45), (31, 31, 31, 31, 31, 31),
        (0, 0, 0, 0, 0, 0), 24, 3,
    )
    original = _pb8(
        species=1, current_hp=50, max_hp=old_stats[0], level=24,
        stat_nature_id=3, ivs=(31, 31, 31, 31, 31, 31),
        evs=(0, 0, 0, 0, 0, 0), stats=old_stats,
    )
    client = _MutableGuestClient(original, item_id=328, quantity=2)
    transport = _Transport(client, fail_on_write=2)
    core_before = client.read_memory(client.core + 0x20, PB8_STORED_SIZE)
    calc_before = client.read_memory(client.calc + 0x20, PB8_PARTY_SIZE - PB8_STORED_SIZE)
    change = PendingRoleChange(
        pokemon_slot=1, pokemon="Bulbasaur", species="Bulbasaur",
        old_role="SIN ROL", new_role="Tanque",
        pokemon_identity=f"1:{0xAABBCCDD}:123:456",
        old_evs=(0, 0, 0, 0, 0, 0),
        new_evs=(252, 0, 252, 0, 0, 0),
    )

    with pytest.raises(BDSPLiveError, match="restauró y verificó"):
        _writer(client, transport).apply([change])

    assert client.read_memory(client.core + 0x20, PB8_STORED_SIZE) == core_before
    assert client.read_memory(client.calc + 0x20, PB8_PARTY_SIZE - PB8_STORED_SIZE) == calc_before


def test_bdsp_role_ev_transaction_rejects_an_unexplained_live_stat_before_rw() -> None:
    original = _pb8(
        species=1, current_hp=50, max_hp=63, level=24,
        stat_nature_id=3, ivs=(31, 31, 31, 31, 31, 31),
        evs=(0, 0, 0, 0, 0, 0),
        # Ataque 999 no puede proceder de Personal/IV/EV/nivel/naturaleza.
        stats=(63, 999, 35, 38, 43, 34),
    )
    client = _MutableGuestClient(original, item_id=328, quantity=2)
    transport = _Transport(client)
    change = PendingRoleChange(
        pokemon_slot=1, pokemon="Bulbasaur", species="Bulbasaur",
        old_role="SIN ROL", new_role="Tanque",
        pokemon_identity=f"1:{0xAABBCCDD}:123:456",
        old_evs=(0, 0, 0, 0, 0, 0),
        new_evs=(252, 0, 252, 0, 0, 0),
    )

    with pytest.raises(BDSPLiveError, match="no coincide.*no se escribió RAM"):
        _writer(client, transport).apply([change])

    assert transport.write_calls == 0
    assert transport.closed is False


def test_bdsp_encrypt_roundtrip_preserves_the_unmodified_party_data() -> None:
    from app.bdsp_live import encrypt_pb8

    encrypted = _pb8(
        species=300,
        move_ids=(33, 45, 85, 0),
        move_pp=(35, 40, 15, 0),
        move_pp_ups=(1, 2, 3, 0),
    )
    assert encrypt_pb8(decrypt_pb8(encrypted)) == encrypted
