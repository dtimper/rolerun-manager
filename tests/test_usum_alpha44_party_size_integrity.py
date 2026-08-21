from __future__ import annotations

import struct
from pathlib import Path
from types import SimpleNamespace

from app.models import PendingTeamChange
from app.oras_live import encrypt_pk6, encrypt_pk6_stored
from app.oras_tm_service import ORASPersonalStats
from app.save_engine_client import SaveGameData
from app.usum_live import (
    HostPartyTarget,
    PK7_PARTY_SIZE,
    PK7_STORED_SIZE,
    USUM_PARTY_COUNT_DELTA,
    USUM_PARTY_STATS_OFFSET,
    USUM_PARTY_STATS_SIZE,
    USUM_PARTY_STRIDE,
    USUMLiveReader,
    USUMLiveWriter,
    parse_pk7_boxed,
    parse_pk7_party,
)


def _checksum(data: bytes | bytearray) -> int:
    return sum(struct.unpack_from("<112H", data, 8)) & 0xFFFF


def _plain_stored(species: int, pid: int) -> bytes:
    data = bytearray(PK7_STORED_SIZE)
    struct.pack_into("<I", data, 0x00, 0xA5C30000 ^ int(pid))
    struct.pack_into("<H", data, 0x04, 0)
    struct.pack_into("<H", data, 0x08, int(species))
    struct.pack_into("<H", data, 0x0C, 11)
    struct.pack_into("<H", data, 0x0E, 22)
    struct.pack_into("<I", data, 0x10, 1000)
    data[0x14] = 1
    struct.pack_into("<I", data, 0x18, int(pid))
    struct.pack_into("<H", data, 0x5A, 33)
    struct.pack_into("<I", data, 0x74, sum(31 << (5 * i) for i in range(6)))
    struct.pack_into("<H", data, 0x06, _checksum(data))
    return bytes(data)


def _personal(_species: int, _form: int) -> ORASPersonalStats:
    return ORASPersonalStats((50, 50, 50, 50, 50, 50), 0)


class _RAM:
    def __init__(self, party_base: int, pc_base: int, count_addr: int):
        self.party_base = int(party_base)
        self.pc_base = int(pc_base)
        self.count_addr = int(count_addr)
        self.party = bytearray(6 * USUM_PARTY_STRIDE)
        self.pc = bytearray(32 * 30 * PK7_STORED_SIZE)
        self.count = bytearray(1)
        self.writes: list[tuple[int, bytes]] = []

    def _area(self, address: int, size: int):
        for base, buf in (
            (self.party_base, self.party),
            (self.pc_base, self.pc),
            (self.count_addr, self.count),
        ):
            if base <= address and address + size <= base + len(buf):
                return buf, address - base
        raise AssertionError(f"RAM address unexpected: 0x{address:X}+0x{size:X}")

    def read(self, address: int, size: int) -> bytes:
        buf, off = self._area(int(address), int(size))
        return bytes(buf[off:off + int(size)])

    def write(self, address: int, data: bytes) -> None:
        raw = bytes(data)
        buf, off = self._area(int(address), len(raw))
        buf[off:off + len(raw)] = raw
        self.writes.append((int(address), raw))


class _Client:
    def __init__(self, ram: _RAM, process): self.ram, self.process = ram, process
    def __enter__(self): return self
    def __exit__(self, *_args): return None
    def process_list(self): return [self.process]
    def set_process(self, _pid: int): return None
    def read_memory(self, address: int, size: int) -> bytes: return self.ram.read(address, size)


class _Host:
    def __init__(self, ram: _RAM, delta: int, pid: int):
        self.ram, self.delta, self.pid = ram, int(delta), int(pid)
    def open_process(self, pid: int):
        assert int(pid) == self.pid
        return object()
    def close_process(self, _handle): return None
    def read(self, _handle, address: int, size: int) -> bytes:
        return self.ram.read(int(address) - self.delta, int(size))
    def write(self, _handle, address: int, data: bytes) -> None:
        self.ram.write(int(address) - self.delta, bytes(data))
    def find_exact_block_in_anchor_region(self, **_kwargs):
        raise AssertionError("alpha.50 no debe escanear FCRAM para PartyCount")
    def find_party_targets(self, *, slot_raws, stored_size: int, stats_offset: int, stats_size: int, stride: int):
        return [HostPartyTarget(self.pid, "azahar.exe", self.ram.party_base + self.delta)]


def _setup(party_defs: list[tuple[int, int, str]], pc_defs: dict[int, tuple[int, int, str]]):
    guest_party = 0x33F7FA44
    guest_pc = 0x33015AB0
    guest_count = guest_party + USUM_PARTY_COUNT_DELTA
    delta = 0x20000000000
    pid = 9002
    process = SimpleNamespace(process_id=88, title_id=0x00040000001B5000, name="momiji")
    ram = _RAM(guest_party, guest_pc, guest_count)
    reader = USUMLiveReader(Path("missing.json"), client_factory=lambda: _Client(ram, process), stable_delay=0, snapshot_attempts=1)
    reader._locate_party_base = lambda _client, _process, _current: guest_party
    writer = USUMLiveWriter(reader, host_memory_factory=lambda: _Host(ram, delta, pid), personal_for=_personal)

    full_records: list[bytes] = []
    for index, (species, mon_pid, role) in enumerate(party_defs):
        stored = bytearray(_plain_stored(species, mon_pid))
        writer._set_role(stored, role)
        writer._refresh_checksum(stored)
        plain = bytes(stored) + writer._party_extension(stored, _personal(species, 0))
        raw = encrypt_pk6(plain)
        full_records.append(raw)
        off = index * USUM_PARTY_STRIDE
        ram.party[off:off + PK7_PARTY_SIZE] = raw
        ram.party[off + USUM_PARTY_STATS_OFFSET:off + USUM_PARTY_STATS_OFFSET + USUM_PARTY_STATS_SIZE] = raw[PK7_STORED_SIZE:PK7_STORED_SIZE + USUM_PARTY_STATS_SIZE]

    blank = encrypt_pk6(bytes(PK7_PARTY_SIZE))
    for index in range(len(party_defs), 6):
        off = index * USUM_PARTY_STRIDE
        ram.party[off:off + PK7_PARTY_SIZE] = blank
        ram.party[off + USUM_PARTY_STATS_OFFSET:off + USUM_PARTY_STATS_OFFSET + USUM_PARTY_STATS_SIZE] = blank[PK7_STORED_SIZE:PK7_STORED_SIZE + USUM_PARTY_STATS_SIZE]
    ram.count[0] = len(party_defs)

    for index, (species, mon_pid, role) in pc_defs.items():
        stored = bytearray(_plain_stored(species, mon_pid))
        writer._set_role(stored, role)
        writer._refresh_checksum(stored)
        raw = encrypt_pk6_stored(bytes(stored))
        off = int(index) * PK7_STORED_SIZE
        ram.pc[off:off + PK7_STORED_SIZE] = raw
    empty_box = encrypt_pk6_stored(bytes(PK7_STORED_SIZE))
    for index in range(32 * 30):
        off = index * PK7_STORED_SIZE
        if not any(ram.pc[off:off + PK7_STORED_SIZE]):
            ram.pc[off:off + PK7_STORED_SIZE] = empty_box

    current_party = []
    for index in range(len(party_defs)):
        off = index * USUM_PARTY_STRIDE
        sparse = bytes(ram.party[off:off + PK7_STORED_SIZE]) + bytes(
            ram.party[off + USUM_PARTY_STATS_OFFSET:off + USUM_PARTY_STATS_OFFSET + USUM_PARTY_STATS_SIZE]
        ) + b"\0" * (PK7_PARTY_SIZE - PK7_STORED_SIZE - USUM_PARTY_STATS_SIZE)
        mon = parse_pk7_party(sparse, index + 1, {})
        assert mon is not None
        current_party.append(mon)
    current = SaveGameData("Pokémon UltraSol", "SAV7USUM", 7, "Timper", current_party, {})
    session = (int(process.title_id), int(process.process_id), str(process.name), int(guest_party))
    writer._pc_live_cache = (session, pid, guest_pc + delta, guest_pc, 32, 30)
    writer._validated_pc_party_target = lambda **_kw: HostPartyTarget(pid, "azahar.exe", guest_party + delta)
    return writer, ram, current, guest_party, guest_pc, guest_count


def test_alpha44_party_to_box_6_to_5_updates_valid_empty_and_party_count() -> None:
    defs = [
        (115, 10, "Líbero"), (761, 11, "Asesino"), (455, 12, "Mago"),
        (133, 13, "Tanque"), (379, 14, "Prisma"), (137, 15, "Support"),
    ]
    writer, ram, current, party_base, pc_base, save_base = _setup(defs, {})
    # Simula reinicio de RoleRun: no hay caché PC. Alpha.45 debe resolver la
    # candidata finita y NO caer al escaneo estructural de FCRAM desde el botón.
    writer._pc_live_cache = None
    writer._resolve_pc_from_direct_pk7_matrix = lambda **_kwargs: (_ for _ in ()).throw(
        AssertionError("ENVIAR AL PC no debe ejecutar el resolver estructural pesado")
    )
    change = PendingTeamChange(
        operation="party-to-box", party_slot=1, box=None, box_slot=None,
        outgoing_identity="115:10:11:22", outgoing_pokemon="Kangaskhan",
    )
    result = writer.apply(current, [change])
    assert [p.species_id for p in result.game.party] == [761, 455, 133, 379, 137]
    assert ram.count[0] == 5
    sparse_last = ram.read(party_base + 5 * USUM_PARTY_STRIDE, PK7_STORED_SIZE)
    assert any(sparse_last)
    blank_sparse = sparse_last + ram.read(
        party_base + 5 * USUM_PARTY_STRIDE + USUM_PARTY_STATS_OFFSET, USUM_PARTY_STATS_SIZE
    ) + b"\0" * (PK7_PARTY_SIZE - PK7_STORED_SIZE - USUM_PARTY_STATS_SIZE)
    assert parse_pk7_party(blank_sparse, 6, {}) is None
    boxed = parse_pk7_boxed(ram.read(pc_base, PK7_STORED_SIZE), 1, 1, {})
    assert boxed is not None and boxed.species_id == 115


def test_alpha44_box_to_party_increments_count_and_leaves_encrypted_empty_box() -> None:
    writer, ram, current, _party_base, pc_base, _save_base = _setup(
        [(115, 10, "Líbero"), (761, 11, "Mago")],
        {0: (133, 99, "SIN ROL")},
    )
    change = PendingTeamChange(
        operation="box-to-party", party_slot=3, box=1, box_slot=1,
        incoming_identity="133:99:11:22", incoming_pokemon="Eevee",
    )
    result = writer.apply(current, [change])
    assert [p.species_id for p in result.game.party] == [115, 761, 133]
    assert ram.count[0] == 3
    raw_empty = ram.read(pc_base, PK7_STORED_SIZE)
    assert any(raw_empty)
    assert parse_pk7_boxed(raw_empty, 1, 1, {}) is None

class _FailCountHost(_Host):
    def write(self, _handle, address: int, data: bytes) -> None:
        guest = int(address) - self.delta
        if guest == self.ram.count_addr:
            raise RuntimeError("forced PartyCount write failure")
        super().write(_handle, address, data)


def test_alpha44_party_count_failure_rolls_back_pc_sparse_party_and_save_mirror() -> None:
    defs = [
        (115, 10, "Líbero"), (761, 11, "Asesino"), (455, 12, "Mago"),
        (133, 13, "Tanque"), (379, 14, "Prisma"), (137, 15, "Support"),
    ]
    writer, ram, current, _party_base, _pc_base, _save_base = _setup(defs, {})
    before_party = bytes(ram.party)
    before_pc = bytes(ram.pc)
    before_count = bytes(ram.count)
    delta = 0x20000000000
    writer.host_memory_factory = lambda: _FailCountHost(ram, delta, 9002)
    change = PendingTeamChange(
        operation="party-to-box", party_slot=1, box=None, box_slot=None,
        outgoing_identity="115:10:11:22", outgoing_pokemon="Kangaskhan",
    )
    import pytest
    from app.usum_live import USUMLiveError
    with pytest.raises(USUMLiveError, match="restauró y verificó"):
        writer.apply(current, [change])
    assert bytes(ram.party) == before_party
    assert bytes(ram.pc) == before_pc
    assert bytes(ram.count) == before_count


def test_alpha55_usum_faint_replacement_leaves_encrypted_empty_source_box() -> None:
    writer, ram, current, _party_base, pc_base, _count_addr = _setup(
        [(115, 10, "Líbero"), (761, 11, "Asesino")],
        {0: (133, 99, "Mago")},
    )
    grave_index = (4 - 1) * 30
    change = PendingTeamChange(
        operation="replace-fainted", party_slot=1, box=1, box_slot=1,
        outgoing_identity="115:10:11:22", incoming_identity="133:99:11:22",
        outgoing_pokemon="Kangaskhan", incoming_pokemon="Eevee",
        graveyard_box=4, graveyard_box_slot=1,
    )
    result = writer.apply(current, [change])
    assert [p.species_id for p in result.game.party] == [133, 761]
    assert result.game.party[0].role == "Líbero"

    source_empty = ram.read(pc_base, PK7_STORED_SIZE)
    assert source_empty == encrypt_pk6_stored(bytes(PK7_STORED_SIZE))
    assert any(source_empty)
    assert parse_pk7_boxed(source_empty, 1, 1, {}) is None

    grave_addr = pc_base + grave_index * PK7_STORED_SIZE
    grave = parse_pk7_boxed(ram.read(grave_addr, PK7_STORED_SIZE), 4, 1, {})
    assert grave is not None and grave.species_id == 115 and grave.role == "Líbero"
