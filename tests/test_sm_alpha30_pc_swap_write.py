from __future__ import annotations

import struct
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

try:
    import customtkinter  # noqa: F401
except ModuleNotFoundError:
    customtkinter = types.ModuleType("customtkinter")
    customtkinter.CTk = object
    sys.modules["customtkinter"] = customtkinter

from app.models import PendingTeamChange
from app.oras_live import encrypt_pk6, encrypt_pk6_stored
from app.oras_tm_service import ORASPersonalStats
from app.realtime.sm_adapter import SMRealTimeAdapter
from app.save_engine_client import SaveGameData, SavePokemon
from app.sm_live import (
    HostPartyTarget,
    PK7_PARTY_SIZE,
    PK7_STORED_SIZE,
    SM_PARTY_STRIDE,
    SMLiveError,
    SMLiveReader,
    SMLiveWriter,
    parse_pk7_boxed,
    parse_pk7_party,
)
from app.sm_rom_service import SM_PERSONAL_RECORD_SIZE, _sm_stats_from_personal_garc
from app.ui import RoleRunManager


def _mon(slot: int, species: int, pid: int, role: str, *, box=None, box_slot=None) -> SavePokemon:
    return SavePokemon(
        slot=slot, species_id=species, species=f"S{species}", nickname=f"M{species}",
        level=10, held_item="Ninguno", ability="A", moves=[], move_ids=[],
        is_egg=False, markings=[False] * 6, role=role, role_symbol="",
        box=box, box_slot=box_slot, pid=pid, tid=11, sid=22,
    )


def _simple_garc(flat: bytes) -> bytes:
    header_size = 0x1C
    file_count = 1
    fato_size = 12 + file_count * 4
    fatb_size = 12 + 4 + 12
    fimb_size = 12
    data_offset = header_size + fato_size + fatb_size + fimb_size
    raw = bytearray(data_offset + len(flat))
    raw[:4] = b"GARC"
    struct.pack_into("<IHHIII", raw, 4, header_size, 0xFEFF, 0x0400, 4, data_offset, len(raw))
    pos = header_size
    raw[pos:pos + 4] = b"FATO"
    struct.pack_into("<IHH", raw, pos + 4, fato_size, file_count, 0)
    pos += fato_size
    raw[pos:pos + 4] = b"FATB"
    struct.pack_into("<II", raw, pos + 4, fatb_size, file_count)
    pos += 12
    struct.pack_into("<I", raw, pos, 1)
    pos += 4
    struct.pack_into("<III", raw, pos, 0, len(flat), len(flat))
    pos += 12
    raw[pos:pos + 4] = b"FIMB"
    struct.pack_into("<II", raw, pos + 4, fimb_size, len(flat))
    raw[data_offset:data_offset + len(flat)] = flat
    return bytes(raw)


def test_alpha34_sm_personal_comes_from_effective_gen7_table_including_forms() -> None:
    records = 809
    flat = bytearray(records * SM_PERSONAL_RECORD_SIZE)
    for index in range(1, 808):
        off = index * SM_PERSONAL_RECORD_SIZE
        flat[off:off + 6] = bytes((40, 50, 60, 70, 80, 90))
        flat[off + 0x15] = 0
    off = 731 * SM_PERSONAL_RECORD_SIZE
    flat[off:off + 6] = bytes((35, 75, 30, 65, 30, 30))
    flat[off + 0x15] = 2
    struct.pack_into("<H", flat, off + 0x1C, 808)
    flat[off + 0x20] = 2
    form = 808 * SM_PERSONAL_RECORD_SIZE
    flat[form:form + 6] = bytes((99, 98, 97, 96, 95, 94))
    flat[form + 0x15] = 5
    stats = _sm_stats_from_personal_garc(_simple_garc(bytes(flat)))
    assert stats[731] == ORASPersonalStats((35, 75, 30, 65, 30, 30), 2)
    assert stats[(731, 1)] == ORASPersonalStats((99, 98, 97, 96, 95, 94), 5)


def test_alpha34_sm_adapter_wires_cached_personal_into_writer() -> None:
    reader = SMLiveReader(Path("missing.json"), stable_delay=0)
    callback = lambda species, form: ORASPersonalStats((1, 2, 3, 4, 5, 6), 0)
    adapter = SMRealTimeAdapter(reader, personal_for=callback)
    assert adapter.writer.personal_for is callback


def test_alpha36_sm_capability_accepts_all_three_team_transfer_modes() -> None:
    manager = SimpleNamespace(_active_azahar_realtime_key=lambda: "sm")
    changes = [
        PendingTeamChange(operation="swap-party-box", party_slot=1, box=1, box_slot=1),
        PendingTeamChange(operation="box-to-party", party_slot=2, box=1, box_slot=1),
        PendingTeamChange(operation="party-to-box", party_slot=1, box=1, box_slot=2),
    ]
    assert RoleRunManager._oras_live_unsupported_changes(manager, changes) == []


def test_alpha34_sm_live_team_change_is_not_projected_before_confirmation() -> None:
    outgoing = _mon(1, 724, 10, "Líbero")
    incoming = _mon(1, 165, 99, "Mago", box=1, box_slot=1)
    manager = RoleRunManager.__new__(RoleRunManager)
    manager.current_game = SaveGameData("Pokémon Sol", "SAV7SM", 7, "Timper", [outgoing], {})
    manager.run = SimpleNamespace(pending_changes=[PendingTeamChange(
        operation="swap-party-box", party_slot=1, box=1, box_slot=1,
        incoming_snapshot=RoleRunManager._pokemon_snapshot(manager, incoming),
    )])
    manager.project = None
    manager._active_azahar_realtime_key = lambda: "sm"
    manager._oras_live_auto_apply_available = lambda: True
    party = RoleRunManager._projected_party(manager)
    assert [p.species_id for p in party] == [724]


def _checksum_stored(data: bytes | bytearray) -> int:
    return sum(struct.unpack_from("<112H", data, 8)) & 0xFFFF


def _plain_pk7(species: int, pid: int, *, exp: int = 1000) -> bytes:
    data = bytearray(PK7_STORED_SIZE)
    struct.pack_into("<I", data, 0x00, 0xA5C30000 ^ int(pid))
    struct.pack_into("<H", data, 0x04, 0)
    struct.pack_into("<H", data, 0x08, int(species))
    struct.pack_into("<H", data, 0x0C, 11)
    struct.pack_into("<H", data, 0x0E, 22)
    struct.pack_into("<I", data, 0x10, int(exp))
    data[0x14] = 1
    struct.pack_into("<I", data, 0x18, int(pid))
    data[0x1C] = 0
    struct.pack_into("<H", data, 0x5A, 33)
    iv32 = sum(31 << (5 * index) for index in range(6))
    struct.pack_into("<I", data, 0x74, iv32)
    struct.pack_into("<H", data, 0x06, _checksum_stored(data))
    return bytes(data)


class _RAM:
    def __init__(self, party_base: int, pc_base: int):
        self.party_base = int(party_base)
        self.pc_base = int(pc_base)
        self.party = bytearray(6 * SM_PARTY_STRIDE)
        self.pc = bytearray(32 * 30 * PK7_STORED_SIZE)
        self.writes: list[tuple[int, int]] = []
        self.consume_party_writes = True

    def read(self, address: int, size: int) -> bytes:
        address = int(address); size = int(size)
        if self.party_base <= address and address + size <= self.party_base + len(self.party):
            off = address - self.party_base
            return bytes(self.party[off:off + size])
        if self.pc_base <= address and address + size <= self.pc_base + len(self.pc):
            off = address - self.pc_base
            return bytes(self.pc[off:off + size])
        raise AssertionError(f"read inesperado 0x{address:X}+0x{size:X}")

    def write(self, address: int, data: bytes) -> None:
        address = int(address); data = bytes(data)
        self.writes.append((address, len(data)))
        if self.party_base <= address and address + len(data) <= self.party_base + len(self.party):
            off = address - self.party_base
            self.party[off:off + len(data)] = data
            # Simula el consumo del EncryptedPartyData por el juego: la extensión
            # party se refleja en el mirror sparse runtime de stats (+0x158).
            if self.consume_party_writes and len(data) == PK7_PARTY_SIZE and off % SM_PARTY_STRIDE == 0:
                stats = data[PK7_STORED_SIZE:PK7_STORED_SIZE + 0x16]
                stats_off = off + 0x158
                self.party[stats_off:stats_off + len(stats)] = stats
            return
        if self.pc_base <= address and address + len(data) <= self.pc_base + len(self.pc):
            off = address - self.pc_base
            self.pc[off:off + len(data)] = data
            return
        raise AssertionError(f"write inesperado 0x{address:X}+0x{len(data):X}")


class _Client:
    def __init__(self, ram: _RAM, process): self.ram, self.process = ram, process
    def __enter__(self): return self
    def __exit__(self, *_args): return None
    def process_list(self): return [self.process]
    def set_process(self, _pid: int): return None
    def read_memory(self, address: int, size: int) -> bytes: return self.ram.read(address, size)


class _HostMemory:
    def __init__(self, ram: _RAM, *, delta: int, pid: int):
        self.ram, self.delta, self.pid = ram, int(delta), int(pid)
    def open_process(self, pid: int):
        assert int(pid) == self.pid
        return object()
    def close_process(self, _handle): return None
    def read(self, _handle, address: int, size: int) -> bytes:
        return self.ram.read(int(address) - self.delta, int(size))
    def write(self, _handle, address: int, data: bytes) -> None:
        self.ram.write(int(address) - self.delta, bytes(data))


def _personal(_species: int, _form: int) -> ORASPersonalStats:
    return ORASPersonalStats((50, 50, 50, 50, 50, 50), 0)


def _full_party(writer: SMLiveWriter, species: int, pid: int, role: str) -> bytes:
    stored = bytearray(_plain_pk7(species, pid))
    writer._set_role(stored, role)
    writer._refresh_checksum(stored)
    plain = bytes(stored) + writer._party_extension(stored, _personal(species, 0))
    assert len(plain) == PK7_PARTY_SIZE
    return encrypt_pk6(plain)


def _boxed(writer: SMLiveWriter, species: int, pid: int, role: str = "SIN ROL") -> bytes:
    stored = bytearray(_plain_pk7(species, pid))
    writer._set_role(stored, role)
    writer._refresh_checksum(stored)
    return encrypt_pk6_stored(bytes(stored))


def _setup_writer(party_defs: list[tuple[int, int, str]], pc_defs: dict[int, tuple[int, int, str]]):
    guest_party = 0x34195E10
    guest_pc = 0x330D9838
    delta = 0x20000000000
    host_pid = 9001
    process = SimpleNamespace(process_id=77, title_id=0x0004000000164800, name="niji_loc")
    ram = _RAM(guest_party, guest_pc)
    reader = SMLiveReader(Path("missing.json"), client_factory=lambda: _Client(ram, process), stable_delay=0, snapshot_attempts=1)
    reader._locate_party_base = lambda _client, _process, _current: guest_party
    writer = SMLiveWriter(reader, host_memory_factory=lambda: _HostMemory(ram, delta=delta, pid=host_pid), personal_for=_personal)
    for index, (species, pid, role) in enumerate(party_defs):
        raw = _full_party(writer, species, pid, role)
        start = index * SM_PARTY_STRIDE
        ram.party[start:start + PK7_PARTY_SIZE] = raw
        ram.party[start + 0x158:start + 0x158 + 0x16] = raw[PK7_STORED_SIZE:PK7_STORED_SIZE + 0x16]
    for slot_index, (species, pid, role) in pc_defs.items():
        raw = _boxed(writer, species, pid, role)
        off = int(slot_index) * PK7_STORED_SIZE
        ram.pc[off:off + PK7_STORED_SIZE] = raw
    current_party = []
    for index in range(len(party_defs)):
        start = index * SM_PARTY_STRIDE
        stored = bytes(ram.party[start:start + PK7_STORED_SIZE])
        stats = bytes(ram.party[start + 0x158:start + 0x158 + 0x16])
        sparse = stored + stats + (b"\0" * (PK7_PARTY_SIZE - PK7_STORED_SIZE - 0x16))
        parsed = parse_pk7_party(sparse, index + 1, {})
        assert parsed is not None
        current_party.append(parsed)
    current = SaveGameData("Pokémon Sol", "SAV7SM", 7, "Timper", current_party, {})
    session = (int(process.title_id), int(process.process_id), str(process.name), int(guest_party))
    writer._pc_live_cache = (session, host_pid, guest_pc + delta, guest_pc, 32, 30)
    writer._validated_pc_party_target = lambda **_kwargs: HostPartyTarget(host_pid, "azahar.exe", guest_party + delta)
    return writer, ram, current, guest_party, guest_pc


def test_alpha35_swap_writes_full_0x104_and_sparse_stats_and_inherits_outgoing_role() -> None:
    writer, ram, current, party_base, pc_base = _setup_writer(
        [(724, 10, "Líbero")], {0: (165, 99, "Mago")},
    )
    change = PendingTeamChange(
        operation="swap-party-box", party_slot=1, box=1, box_slot=1,
        outgoing_identity="724:10:11:22", incoming_identity="165:99:11:22",
        incoming_pokemon="Ledyba", outgoing_pokemon="Decidueye",
    )
    result = writer.apply(current, [change])
    assert result.game.party[0].species_id == 165
    assert result.game.party[0].role == "Líbero"
    boxed = parse_pk7_boxed(ram.read(pc_base, PK7_STORED_SIZE), 1, 1, {})
    assert boxed is not None and boxed.species_id == 724
    assert (party_base, PK7_PARTY_SIZE) in ram.writes
    assert (party_base + 0x158, 0x16) in ram.writes
    assert not any(address == party_base and size == PK7_STORED_SIZE for address, size in ram.writes)


def test_alpha137_sm_swap_applies_prepared_role_evs_in_the_atomic_team_write() -> None:
    writer, ram, current, _party_base, _pc_base = _setup_writer(
        [(724, 10, "Líbero")], {0: (165, 99, "Mago")},
    )
    change = PendingTeamChange(
        operation="swap-party-box", party_slot=1, box=1, box_slot=1,
        outgoing_identity="724:10:11:22", incoming_identity="165:99:11:22",
        incoming_pokemon="Ledyba", outgoing_pokemon="Decidueye",
        incoming_role="Líbero",
        incoming_snapshot={
            "role": "Líbero",
            "evs": {
                "hp": 252, "attack": 0, "defense": 0,
                "sp_attack": 0, "sp_defense": 0, "speed": 252,
            },
        },
    )

    result = writer.apply(current, [change])

    incoming = result.game.party[0]
    assert incoming.species_id == 165
    assert incoming.role == "Líbero"
    assert incoming.evs == {
        "hp": 252, "attack": 0, "defense": 0,
        "sp_attack": 0, "sp_defense": 0, "speed": 252,
    }


def test_alpha137_sm_swap_rejects_incomplete_prepared_evs_before_any_write() -> None:
    writer, ram, current, _party_base, _pc_base = _setup_writer(
        [(724, 10, "Líbero")], {0: (165, 99, "Mago")},
    )
    before_party = bytes(ram.party)
    before_pc = bytes(ram.pc)
    change = PendingTeamChange(
        operation="swap-party-box", party_slot=1, box=1, box_slot=1,
        outgoing_identity="724:10:11:22", incoming_identity="165:99:11:22",
        incoming_role="Líbero",
        incoming_snapshot={"role": "Líbero", "evs": {"hp": 252}},
    )

    with pytest.raises(SMLiveError, match="incompleto"):
        writer.apply(current, [change])

    assert bytes(ram.party) == before_party
    assert bytes(ram.pc) == before_pc
    assert ram.writes == []


def test_alpha35_swap_does_not_depend_on_game_copying_sparse_stats() -> None:
    writer, ram, current, party_base, _pc_base = _setup_writer(
        [(724, 10, "Líbero")], {0: (165, 99, "Mago")},
    )
    ram.consume_party_writes = False
    change = PendingTeamChange(
        operation="swap-party-box", party_slot=1, box=1, box_slot=1,
        outgoing_identity="724:10:11:22", incoming_identity="165:99:11:22",
        incoming_pokemon="Ledyba", outgoing_pokemon="Decidueye",
    )
    result = writer.apply(current, [change])
    assert result.game.party[0].species_id == 165
    assert (party_base + 0x158, 0x16) in ram.writes


class _AutoProofHostMemory(_HostMemory):
    def find_party_targets(self, *, slot_raws, stored_size, stats_offset, stats_size, stride):
        return [HostPartyTarget(self.pid, "azahar.exe", self.ram.party_base + self.delta)]

    def writable_region_for_address(self, *, pid: int, address: int):
        assert int(pid) == self.pid
        host_pc = self.ram.pc_base + self.delta
        assert host_pc <= int(address) < host_pc + len(self.ram.pc)
        return host_pc, len(self.ram.pc)


def test_alpha37_team_write_auto_proves_pc_without_opening_pc_page() -> None:
    writer, ram, current, _party_base, pc_base = _setup_writer(
        [(724, 10, "Líbero"), (731, 11, "Asesino")], {},
    )
    delta = 0x20000000000
    writer._pc_live_cache = None
    writer._pc_party_anchor = None
    writer.host_memory_factory = lambda: _AutoProofHostMemory(ram, delta=delta, pid=9001)
    change = PendingTeamChange(
        operation="party-to-box", party_slot=2, box=None, box_slot=None,
        outgoing_identity="731:11:11:22", outgoing_pokemon="S731",
    )
    result = writer.apply(current, [change])
    assert [p.species_id for p in result.game.party] == [724]
    boxed = parse_pk7_boxed(ram.read(pc_base, PK7_STORED_SIZE), 1, 1, {})
    assert boxed is not None and boxed.species_id == 731
    assert writer._pc_live_cache is not None
    assert "team-write auto proof" in str(writer._pc_last_resolution.get("source"))


def test_alpha34_preflight_accepts_opaque_runtime_bytes_between_stored_and_sparse_stats() -> None:
    writer, ram, current, _party_base, _pc_base = _setup_writer(
        [(724, 10, "Líbero")], {0: (165, 99, "Mago")},
    )
    # Reproduce el layout real que motivó alpha.34: el prefijo 0xE8 sigue siendo
    # el PK7 stored demostrado y +0x158 contiene stats válidos, pero 0xE8..0x103
    # no es una extensión PartyData estándar contigua. Alpha.33 lo rechazaba.
    ram.party[PK7_STORED_SIZE:PK7_PARTY_SIZE] = bytes(range(PK7_PARTY_SIZE - PK7_STORED_SIZE))
    change = PendingTeamChange(
        operation="swap-party-box", party_slot=1, box=1, box_slot=1,
        outgoing_identity="724:10:11:22", incoming_identity="165:99:11:22",
        incoming_pokemon="Ledyba", outgoing_pokemon="Decidueye",
    )
    result = writer.apply(current, [change])
    assert result.game.party[0].species_id == 165
    assert result.game.party[0].role == "Líbero"


def test_alpha36_box_to_party_uses_first_free_role_and_clears_pc_slot() -> None:
    writer, ram, current, party_base, pc_base = _setup_writer(
        [(724, 10, "Líbero"), (731, 11, "Mago")],
        {0: (165, 99, "Support")},
    )
    change = PendingTeamChange(
        operation="box-to-party", party_slot=3, box=1, box_slot=1,
        incoming_identity="165:99:11:22", incoming_pokemon="Ledyba",
        # Aunque la UI arrastrase un rol viejo del PC, el writer debe decidirlo
        # desde la party viva: el primer libre es Asesino.
        incoming_role="Support",
    )
    result = writer.apply(current, [change])
    assert [p.species_id for p in result.game.party] == [724, 731, 165]
    assert result.game.party[2].role == "Asesino"
    empty = encrypt_pk6_stored(bytes(PK7_STORED_SIZE))
    assert any(empty)
    assert ram.read(pc_base, PK7_STORED_SIZE) == empty
    assert parse_pk7_boxed(empty, 1, 1, {}) is None
    assert (party_base + 2 * SM_PARTY_STRIDE, PK7_PARTY_SIZE) in ram.writes
    assert (party_base + 2 * SM_PARTY_STRIDE + 0x158, 0x16) in ram.writes


def test_alpha137_sm_box_to_party_applies_the_first_free_roles_prepared_evs() -> None:
    writer, ram, current, _party_base, pc_base = _setup_writer(
        [(724, 10, "Líbero"), (731, 11, "Mago")],
        {0: (165, 99, "Support")},
    )
    change = PendingTeamChange(
        operation="box-to-party", party_slot=3, box=1, box_slot=1,
        incoming_identity="165:99:11:22", incoming_pokemon="Ledyba",
        incoming_role="Asesino",
        incoming_snapshot={
            "role": "Asesino",
            "evs": {
                "hp": 0, "attack": 252, "defense": 0,
                "sp_attack": 0, "sp_defense": 0, "speed": 252,
            },
        },
    )

    result = writer.apply(current, [change])

    incoming = result.game.party[2]
    assert incoming.role == "Asesino"
    assert incoming.evs == {
        "hp": 0, "attack": 252, "defense": 0,
        "sp_attack": 0, "sp_defense": 0, "speed": 252,
    }
    empty = encrypt_pk6_stored(bytes(PK7_STORED_SIZE))
    assert any(empty)
    assert ram.read(pc_base, PK7_STORED_SIZE) == empty
    assert parse_pk7_boxed(empty, 1, 1, {}) is None


def test_alpha36_party_to_box_compacts_full_six_member_party_and_preserves_roles() -> None:
    party_defs = [
        (724, 10, "Líbero"),
        (731, 11, "Asesino"),
        (25, 12, "Mago"),
        (19, 13, "Tanque"),
        (165, 14, "Prisma"),
        (734, 15, "Support"),
    ]
    writer, ram, current, party_base, pc_base = _setup_writer(party_defs, {})
    change = PendingTeamChange(
        operation="party-to-box", party_slot=2, box=1, box_slot=1,
        outgoing_identity="731:11:11:22", outgoing_pokemon="S731",
    )
    result = writer.apply(current, [change])
    assert [p.species_id for p in result.game.party] == [724, 25, 19, 165, 734]
    assert [p.role for p in result.game.party] == ["Líbero", "Mago", "Tanque", "Prisma", "Support"]
    boxed = parse_pk7_boxed(ram.read(pc_base, PK7_STORED_SIZE), 1, 1, {})
    assert boxed is not None and boxed.species_id == 731 and boxed.role == "Asesino"
    # El sexto slot físico queda vacío incluso partiendo de una party de seis.
    last = party_base + 5 * SM_PARTY_STRIDE
    assert ram.read(last, PK7_STORED_SIZE) == b"\0" * PK7_STORED_SIZE
    assert ram.read(last + 0x158, 0x16) == b"\0" * 0x16


def test_alpha37_party_to_box_uses_first_free_live_slot_not_stale_requested_slot() -> None:
    writer, ram, current, _party_base, pc_base = _setup_writer(
        [(724, 10, "Líbero"), (731, 11, "Asesino")],
        {0: (165, 99, "Mago")},
    )
    change = PendingTeamChange(
        operation="party-to-box", party_slot=2, box=1, box_slot=1,
        outgoing_identity="731:11:11:22", outgoing_pokemon="S731",
    )
    result = writer.apply(current, [change])
    assert [p.species_id for p in result.game.party] == [724]
    first = parse_pk7_boxed(ram.read(pc_base, PK7_STORED_SIZE), 1, 1, {})
    second = parse_pk7_boxed(ram.read(pc_base + PK7_STORED_SIZE, PK7_STORED_SIZE), 1, 2, {})
    assert first is not None and first.species_id == 165
    assert second is not None and second.species_id == 731


def test_alpha36_party_to_box_reuses_existing_live_blank_when_party_has_less_than_six() -> None:
    writer, ram, current, party_base, pc_base = _setup_writer(
        [(724, 10, "Líbero"), (731, 11, "Asesino"), (25, 12, "Mago")], {},
    )
    # El slot 4 está vacío, pero contiene bytes opacos fuera del stored. Alpha.36
    # debe reutilizar su ventana live en vez de fabricar esos bytes.
    blank4 = 3 * SM_PARTY_STRIDE
    ram.party[blank4 + PK7_STORED_SIZE:blank4 + PK7_PARTY_SIZE] = bytes(range(PK7_PARTY_SIZE - PK7_STORED_SIZE))
    change = PendingTeamChange(
        operation="party-to-box", party_slot=1, box=1, box_slot=1,
        outgoing_identity="724:10:11:22", outgoing_pokemon="S724",
    )
    result = writer.apply(current, [change])
    assert [p.species_id for p in result.game.party] == [731, 25]
    boxed = parse_pk7_boxed(ram.read(pc_base, PK7_STORED_SIZE), 1, 1, {})
    assert boxed is not None and boxed.species_id == 724
    # El antiguo slot 3 recibe exactamente la ventana 0x104 del slot vacío 4.
    assert ram.read(party_base + 2 * SM_PARTY_STRIDE, PK7_PARTY_SIZE) == bytes(ram.party[blank4:blank4 + PK7_PARTY_SIZE])


def test_alpha36_party_to_box_refuses_to_empty_last_party_member() -> None:
    writer, ram, current, _party_base, _pc_base = _setup_writer(
        [(724, 10, "Líbero")], {},
    )
    before_party = bytes(ram.party)
    before_pc = bytes(ram.pc)
    change = PendingTeamChange(
        operation="party-to-box", party_slot=1, box=1, box_slot=1,
        outgoing_identity="724:10:11:22",
    )
    with pytest.raises(SMLiveError, match="al menos un Pokémon"):
        writer.apply(current, [change])
    assert bytes(ram.party) == before_party
    assert bytes(ram.pc) == before_pc


class _FailingHostMemory(_HostMemory):
    def __init__(self, ram: _RAM, *, delta: int, pid: int, fail_on_write: int):
        super().__init__(ram, delta=delta, pid=pid)
        self.fail_on_write = int(fail_on_write)
        self.write_count = 0

    def write(self, _handle, address: int, data: bytes) -> None:
        self.write_count += 1
        if self.write_count == self.fail_on_write:
            raise RuntimeError("fallo forzado de escritura")
        super().write(_handle, address, data)


def test_alpha36_party_to_box_rolls_back_pc_and_shifted_party_on_mid_transaction_failure() -> None:
    writer, ram, current, _party_base, _pc_base = _setup_writer(
        [(724, 10, "Líbero"), (731, 11, "Asesino"), (25, 12, "Mago")], {},
    )
    delta = 0x20000000000
    writer.host_memory_factory = lambda: _FailingHostMemory(ram, delta=delta, pid=9001, fail_on_write=3)
    before_party = bytes(ram.party)
    before_pc = bytes(ram.pc)
    change = PendingTeamChange(
        operation="party-to-box", party_slot=1, box=1, box_slot=1,
        outgoing_identity="724:10:11:22",
    )
    with pytest.raises(SMLiveError, match="restauró y verificó"):
        writer.apply(current, [change])
    assert bytes(ram.party) == before_party
    assert bytes(ram.pc) == before_pc


def test_alpha36_box_to_party_rolls_back_pc_and_party_on_stats_failure() -> None:
    writer, ram, current, _party_base, _pc_base = _setup_writer(
        [(724, 10, "Líbero")], {0: (165, 99, "Mago")},
    )
    delta = 0x20000000000
    writer.host_memory_factory = lambda: _FailingHostMemory(ram, delta=delta, pid=9001, fail_on_write=3)
    before_party = bytes(ram.party)
    before_pc = bytes(ram.pc)
    change = PendingTeamChange(
        operation="box-to-party", party_slot=2, box=1, box_slot=1,
        incoming_identity="165:99:11:22",
    )
    with pytest.raises(SMLiveError, match="restauró y verificó"):
        writer.apply(current, [change])
    assert bytes(ram.party) == before_party
    assert bytes(ram.pc) == before_pc


def test_alpha38_party_to_box_accepts_nonzero_encrypted_empty_pc_slot() -> None:
    """CAJAS PC y el writer deben compartir la misma semántica de hueco vacío.

    Un PK7 vacío cifrado puede tener muchos bytes no-cero aunque, tras descifrarlo,
    species sea 0 y sanity/checksum sean válidos. Alpha.37 lo mostraba vacío en la
    UI pero lo rechazaba en ENVIAR AL PC mediante ``any(raw)``.
    """
    writer, ram, current, _party_base, pc_base = _setup_writer(
        [(724, 10, "Líbero"), (731, 11, "Asesino")],
        {0: (165, 99, "Mago")},
    )
    encrypted_empty = encrypt_pk6_stored(bytes(PK7_STORED_SIZE))
    assert any(encrypted_empty)
    assert parse_pk7_boxed(encrypted_empty, 1, 2, {}) is None
    ram.pc[PK7_STORED_SIZE:2 * PK7_STORED_SIZE] = encrypted_empty

    change = PendingTeamChange(
        operation="party-to-box", party_slot=2, box=None, box_slot=None,
        outgoing_identity="731:11:11:22", outgoing_pokemon="S731",
    )
    result = writer.apply(current, [change])

    assert [p.species_id for p in result.game.party] == [724]
    first = parse_pk7_boxed(ram.read(pc_base, PK7_STORED_SIZE), 1, 1, {})
    second = parse_pk7_boxed(ram.read(pc_base + PK7_STORED_SIZE, PK7_STORED_SIZE), 1, 2, {})
    assert first is not None and first.species_id == 165
    assert second is not None and second.species_id == 731


def test_alpha38_box_to_party_accepts_nonzero_encrypted_empty_party_slot() -> None:
    writer, ram, current, party_base, pc_base = _setup_writer(
        [(724, 10, "Líbero")],
        {0: (165, 99, "SIN ROL")},
    )
    encrypted_empty_party = encrypt_pk6(bytes(PK7_PARTY_SIZE))
    assert any(encrypted_empty_party)
    assert parse_pk7_party(encrypted_empty_party, 2, {}) is None
    start = SM_PARTY_STRIDE
    ram.party[start:start + PK7_PARTY_SIZE] = encrypted_empty_party
    ram.party[start + 0x158:start + 0x158 + 0x16] = encrypted_empty_party[PK7_STORED_SIZE:PK7_STORED_SIZE + 0x16]

    change = PendingTeamChange(
        operation="box-to-party", party_slot=2, box=1, box_slot=1,
        incoming_identity="165:99:11:22", incoming_pokemon="S165",
    )
    result = writer.apply(current, [change])
    assert [p.species_id for p in result.game.party] == [724, 165]
    assert result.game.party[1].role == "Asesino"
    assert parse_pk7_boxed(ram.read(pc_base, PK7_STORED_SIZE), 1, 1, {}) is None


def test_alpha38_party_compaction_reuses_nonzero_encrypted_empty_party_slot() -> None:
    writer, ram, current, party_base, pc_base = _setup_writer(
        [(724, 10, "Líbero"), (731, 11, "Asesino"), (25, 12, "Mago")],
        {},
    )
    encrypted_empty_party = encrypt_pk6(bytes(PK7_PARTY_SIZE))
    assert parse_pk7_party(encrypted_empty_party, 4, {}) is None
    start = 3 * SM_PARTY_STRIDE
    ram.party[start:start + PK7_PARTY_SIZE] = encrypted_empty_party
    ram.party[start + 0x158:start + 0x158 + 0x16] = encrypted_empty_party[PK7_STORED_SIZE:PK7_STORED_SIZE + 0x16]

    change = PendingTeamChange(
        operation="party-to-box", party_slot=1, box=None, box_slot=None,
        outgoing_identity="724:10:11:22", outgoing_pokemon="S724",
    )
    result = writer.apply(current, [change])
    assert [p.species_id for p in result.game.party] == [731, 25]
    boxed = parse_pk7_boxed(ram.read(pc_base, PK7_STORED_SIZE), 1, 1, {})
    assert boxed is not None and boxed.species_id == 724


def test_alpha39_party_to_box_reports_verified_live_destination_for_immediate_ui_refresh() -> None:
    """El destino elegido por el writer debe volver a la UI solo tras éxito.

    ENVIAR AL PC deja box/box_slot en None para que la autoridad sea el PC live.
    Tras demostrar y escribir el primer hueco libre, alpha.39 anota esa posición
    real en el PendingTeamChange. La capa UI ya existente puede así crear su
    override inmediato sin obligar a abrir CAJAS PC para reconciliar.
    """
    writer, ram, current, _party_base, pc_base = _setup_writer(
        [(724, 10, "Líbero"), (731, 11, "Asesino")],
        {0: (165, 99, "Mago")},
    )
    change = PendingTeamChange(
        operation="party-to-box", party_slot=2, box=None, box_slot=None,
        outgoing_identity="731:11:11:22", outgoing_pokemon="S731",
    )

    result = writer.apply(current, [change])

    assert [p.species_id for p in result.game.party] == [724]
    assert (change.box, change.box_slot) == (1, 2)
    first = parse_pk7_boxed(ram.read(pc_base, PK7_STORED_SIZE), 1, 1, {})
    second = parse_pk7_boxed(ram.read(pc_base + PK7_STORED_SIZE, PK7_STORED_SIZE), 1, 2, {})
    assert first is not None and first.species_id == 165
    assert second is not None and second.species_id == 731


def test_alpha39_failed_party_to_box_does_not_publish_unverified_destination() -> None:
    """Un rollback no debe dejar a la UI una posición PC que nunca se confirmó."""
    writer, ram, current, _party_base, _pc_base = _setup_writer(
        [(724, 10, "Líbero"), (731, 11, "Asesino"), (25, 12, "Mago")], {},
    )
    delta = 0x20000000000
    writer.host_memory_factory = lambda: _FailingHostMemory(ram, delta=delta, pid=9001, fail_on_write=3)
    change = PendingTeamChange(
        operation="party-to-box", party_slot=1, box=None, box_slot=None,
        outgoing_identity="724:10:11:22", outgoing_pokemon="S724",
    )

    with pytest.raises(SMLiveError, match="restauró y verificó"):
        writer.apply(current, [change])

    assert change.box is None
    assert change.box_slot is None


def test_alpha40_sm_capability_accepts_replace_fainted() -> None:
    manager = SimpleNamespace(_active_azahar_realtime_key=lambda: "sm")
    change = PendingTeamChange(
        operation="replace-fainted", party_slot=1, box=1, box_slot=1,
        graveyard_box=4, graveyard_box_slot=1,
    )
    assert RoleRunManager._oras_live_unsupported_changes(manager, [change]) == []


def test_alpha40_replace_fainted_moves_dead_to_box4_and_inherits_role() -> None:
    writer, ram, current, _party_base, pc_base = _setup_writer(
        [(724, 10, "Líbero"), (731, 11, "Asesino")],
        {0: (165, 99, "Mago")},
    )
    grave_index = (4 - 1) * 30
    change = PendingTeamChange(
        operation="replace-fainted", party_slot=1, box=1, box_slot=1,
        outgoing_identity="724:10:11:22", incoming_identity="165:99:11:22",
        outgoing_pokemon="Decidueye", incoming_pokemon="Ledyba",
        incoming_role="Líbero",
        incoming_snapshot={
            "role": "Líbero",
            "evs": {
                "hp": 252, "attack": 252, "defense": 0,
                "sp_attack": 0, "sp_defense": 0, "speed": 0,
            },
        },
        graveyard_box=4, graveyard_box_slot=1,
    )
    result = writer.apply(current, [change])
    assert [p.species_id for p in result.game.party] == [165, 731]
    assert result.game.party[0].role == "Líbero"
    assert result.game.party[0].evs == {
        "hp": 252, "attack": 252, "defense": 0,
        "sp_attack": 0, "sp_defense": 0, "speed": 0,
    }
    assert change.incoming_role == "Líbero"
    source_empty = ram.read(pc_base, PK7_STORED_SIZE)
    assert source_empty == encrypt_pk6_stored(bytes(PK7_STORED_SIZE))
    assert any(source_empty)
    assert parse_pk7_boxed(source_empty, 1, 1, {}) is None
    grave_addr = pc_base + grave_index * PK7_STORED_SIZE
    grave = parse_pk7_boxed(ram.read(grave_addr, PK7_STORED_SIZE), 4, 1, {})
    assert grave is not None and grave.species_id == 724 and grave.role == "Líbero"


def test_alpha40_replace_fainted_rolls_back_source_graveyard_and_party() -> None:
    writer, ram, current, _party_base, _pc_base = _setup_writer(
        [(724, 10, "Líbero"), (731, 11, "Asesino")],
        {0: (165, 99, "Mago")},
    )
    delta = 0x20000000000
    writer.host_memory_factory = lambda: _FailingHostMemory(ram, delta=delta, pid=9001, fail_on_write=4)
    before_party = bytes(ram.party)
    before_pc = bytes(ram.pc)
    change = PendingTeamChange(
        operation="replace-fainted", party_slot=1, box=1, box_slot=1,
        outgoing_identity="724:10:11:22", incoming_identity="165:99:11:22",
        graveyard_box=4, graveyard_box_slot=1,
    )
    with pytest.raises(SMLiveError, match="restauró y verificó"):
        writer.apply(current, [change])
    assert bytes(ram.party) == before_party
    assert bytes(ram.pc) == before_pc
