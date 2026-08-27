from __future__ import annotations

import struct
import sys
import types
from types import SimpleNamespace

import pytest

try:
    import customtkinter  # noqa: F401
except ModuleNotFoundError:
    customtkinter = types.ModuleType("customtkinter")
    customtkinter.CTk = object
    sys.modules["customtkinter"] = customtkinter

from app.config import APP_VERSION
from app.oras_live import encrypt_pk6
from app.save_engine_client import SaveGameData, SavePokemon
from app.sm_live import PK7_PARTY_SIZE, PK7_STORED_SIZE, SMLiveError, SMLiveWriter
from app.win_process_memory import HostPartyTarget, WindowsProcessMemory


def _checksum(data: bytes) -> int:
    return sum(struct.unpack_from("<112H", data, 8)) & 0xFFFF


def _stored_pk7(species: int, pid: int) -> bytes:
    data = bytearray(PK7_PARTY_SIZE)
    struct.pack_into("<I", data, 0x00, 0xA5C30000 ^ int(pid))
    struct.pack_into("<H", data, 0x04, 0)
    struct.pack_into("<H", data, 0x08, int(species))
    struct.pack_into("<H", data, 0x0C, 11)
    struct.pack_into("<H", data, 0x0E, 22)
    data[0x14] = 65
    struct.pack_into("<I", data, 0x18, int(pid))
    name = f"M{species}".encode("utf-16le") + b"\0\0"
    data[0x40:0x40 + len(name)] = name
    struct.pack_into("<H", data, 0x5A, 33)
    struct.pack_into("<H", data, 0x5C, 45)
    struct.pack_into("<I", data, 0x74, 31 | (31 << 5))
    struct.pack_into("<H", data, 0x06, _checksum(data))
    return encrypt_pk6(bytes(data))[:PK7_STORED_SIZE]


def _party_mon(species: int = 6, pid: int = 0x99887766) -> SavePokemon:
    return SavePokemon(
        slot=1, species_id=species, species=f"Species {species}", nickname=f"Party {species}",
        level=30, held_item="Ninguno", ability="Ability", moves=["A", "B", "—", "—"],
        move_ids=[1, 2, 0, 0], is_egg=False, markings=[False] * 6,
        role="SIN ROL", role_symbol="", pid=pid, tid=11, sid=22,
    )


def _recent_anchor(species: int, pid: int) -> SavePokemon:
    return SavePokemon(
        slot=1, species_id=species, species=f"Species {species}", nickname=f"Recent {species}",
        level=20, held_item="Ninguno", ability="Ability", moves=["A", "—", "—", "—"],
        move_ids=[1, 0, 0, 0], is_egg=False, markings=[False] * 6,
        role="SIN ROL", role_symbol="", pid=pid, tid=11, sid=22, box=None, box_slot=None,
    )


class _Memory:
    def __init__(self, base: int, data: bytes):
        self.base = int(base)
        self.data = bytes(data)

    def writable_region_for_address(self, *, pid: int, address: int):
        assert self.base <= int(address) < self.base + len(self.data)
        return self.base, len(self.data)

    def find_zero_sanity_records_in_anchor_region(self, **kwargs):
        return WindowsProcessMemory._candidate_zero_sanity_records(
            self.data, absolute_base=self.base,
            record_size=int(kwargs["record_size"]), sanity_offset=int(kwargs["sanity_offset"]),
            max_candidates=int(kwargs["max_candidates"]),
            candidate_validator=kwargs.get("candidate_validator"),
            scan_stats=kwargs.get("scan_stats"),
        )

    def open_process(self, _pid: int):
        return object()

    def close_process(self, _handle):
        return None

    def read(self, _handle, address: int, size: int) -> bytes:
        offset = int(address) - self.base
        if offset < 0 or offset + int(size) > len(self.data):
            raise RuntimeError("host read outside region")
        return self.data[offset:offset + int(size)]


class _Client:
    def __init__(self, base: int, data: bytes):
        self.base = int(base)
        self.data = bytes(data)

    def read_memory(self, address: int, size: int) -> bytes:
        offset = int(address) - self.base
        if offset < 0 or offset + int(size) > len(self.data):
            raise RuntimeError("guest read outside region")
        return self.data[offset:offset + int(size)]


def _fixture(*, occupied: list[tuple[int, int]], leading_empty_slots: int = 0):
    slots = 32 * 30
    matrix = bytearray(slots * PK7_STORED_SIZE)
    for index, (species, pid) in enumerate(occupied):
        slot_index = 2 + index * 40
        start = slot_index * PK7_STORED_SIZE
        matrix[start:start + PK7_STORED_SIZE] = _stored_pk7(species, pid)

    prefix_records = 7
    prefix = bytearray(b"\xA5" * (prefix_records * PK7_STORED_SIZE))
    if leading_empty_slots:
        prefix.extend(b"\0" * (leading_empty_slots * PK7_STORED_SIZE))
    suffix = b"\x5A" * (7 * PK7_STORED_SIZE)
    data = bytes(prefix) + bytes(matrix) + suffix
    host_region = 0x50000000
    guest_region = 0x33000000
    matrix_host = host_region + len(prefix)
    matrix_guest = guest_region + len(prefix)
    party_offset = 3 * PK7_STORED_SIZE
    target = HostPartyTarget(77, "azahar.exe", host_region + party_offset)
    party_guest = guest_region + party_offset
    return data, host_region, guest_region, matrix_host, matrix_guest, target, party_guest


def test_alpha23_version() -> None:
    assert APP_VERSION == "0.2.6-alpha.46"


def test_alpha23_zero_sanity_prefilter_skips_huge_zero_area_but_keeps_pk7() -> None:
    record = _stored_pk7(25, 0x1234ABCD)
    data = b"\0" * (1024 * 1024) + record + b"\0" * (1024 * 1024)
    found = WindowsProcessMemory._candidate_zero_sanity_records(
        data, absolute_base=0x10000000, record_size=PK7_STORED_SIZE, sanity_offset=4,
    )
    starts = {address for address, raw in found if raw == record}
    assert 0x10000000 + 1024 * 1024 in starts


def test_alpha23_direct_matrix_finds_exact_960_slot_run_without_main_pc() -> None:
    data, host_base, guest_base, matrix_host, matrix_guest, target, party_guest = _fixture(
        occupied=[(25, 0x11112222), (133, 0x33334444)],
    )
    memory = _Memory(host_base, data)
    client = _Client(guest_base, data)
    writer = SMLiveWriter(SimpleNamespace(move_names={33: "Placaje", 45: "Gruñido"}))
    current = SaveGameData("Pokémon Sol", "SAV7SM", 7, "T", [_party_mon()], {})

    pid, host_pc, guest_pc, parsed, evaluated = writer._resolve_pc_from_direct_pk7_matrix(
        client=client, host_memory=memory, party_base=party_guest, party_targets=[target],
        current=current, anchors=[], box_count=32, box_slot_count=30,
    )
    assert pid == 77
    assert host_pc == matrix_host
    assert guest_pc == matrix_guest
    assert sum(1 for value in parsed.values() if value is not None) == 2
    assert parsed[(1, 3)] is not None and parsed[(1, 3)].species_id == 25
    assert any(entry.get("accepted") is True for entry in evaluated)


def test_alpha23_direct_matrix_rejects_ambiguous_961_slot_valid_run() -> None:
    data, host_base, guest_base, _matrix_host, _matrix_guest, target, party_guest = _fixture(
        occupied=[(25, 0x11112222), (133, 0x33334444)], leading_empty_slots=1,
    )
    writer = SMLiveWriter(SimpleNamespace(move_names={33: "Placaje", 45: "Gruñido"}))
    with pytest.raises(SMLiveError, match="directamente por estructura PK7"):
        writer._resolve_pc_from_direct_pk7_matrix(
            client=_Client(guest_base, data), host_memory=_Memory(host_base, data),
            party_base=party_guest, party_targets=[target],
            current=SaveGameData("Pokémon Sol", "SAV7SM", 7, "T", [_party_mon()], {}),
            anchors=[], box_count=32, box_slot_count=30,
        )
    assert any(
        run.get("rejected") == "valid-slot-run-boundary-ambiguous"
        for entry in writer._pc_last_resolution.get("evaluated", [])
        for run in entry.get("runs", [])
    )


def test_alpha23_single_occupied_is_enough_when_exact_960_slot_boundary_is_unique() -> None:
    species, pid = 25, 0x11112222
    data, host_base, guest_base, matrix_host, matrix_guest, target, party_guest = _fixture(
        occupied=[(species, pid)],
    )
    current = SaveGameData("Pokémon Sol", "SAV7SM", 7, "T", [_party_mon()], {})
    writer = SMLiveWriter(SimpleNamespace(move_names={33: "Placaje", 45: "Gruñido"}))
    result = writer._resolve_pc_from_direct_pk7_matrix(
        client=_Client(guest_base, data), host_memory=_Memory(host_base, data),
        party_base=party_guest, party_targets=[target], current=current, anchors=[],
        box_count=32, box_slot_count=30,
    )
    assert result[1] == matrix_host
    assert result[2] == matrix_guest
    assert sum(1 for value in result[3].values() if value is not None) == 1


def test_alpha23_recent_party_to_pc_anchor_must_match_if_one_exists() -> None:
    species, pid = 25, 0x11112222
    data, host_base, guest_base, matrix_host, matrix_guest, target, party_guest = _fixture(
        occupied=[(species, pid)],
    )
    current = SaveGameData("Pokémon Sol", "SAV7SM", 7, "T", [_party_mon()], {})
    writer = SMLiveWriter(SimpleNamespace(move_names={33: "Placaje", 45: "Gruñido"}))
    with pytest.raises(SMLiveError):
        writer._resolve_pc_from_direct_pk7_matrix(
            client=_Client(guest_base, data), host_memory=_Memory(host_base, data),
            party_base=party_guest, party_targets=[target], current=current,
            anchors=[_recent_anchor(133, 0x77778888)], box_count=32, box_slot_count=30,
        )

    writer2 = SMLiveWriter(SimpleNamespace(move_names={33: "Placaje", 45: "Gruñido"}))
    result = writer2._resolve_pc_from_direct_pk7_matrix(
        client=_Client(guest_base, data), host_memory=_Memory(host_base, data),
        party_base=party_guest, party_targets=[target], current=current,
        anchors=[_recent_anchor(species, pid)], box_count=32, box_slot_count=30,
    )
    assert result[1] == matrix_host
    assert result[2] == matrix_guest


def test_alpha24_raw_sanity_noise_does_not_consume_semantic_candidate_limit() -> None:
    # Reproduce el fallo real de alpha.23: más candidatos con sanity=0 que el
    # límite, pero ninguno es un PK7 salvo el último. El límite debe contar solo
    # los registros que superan el validador semántico.
    fake = bytearray(b"\xA5" * PK7_STORED_SIZE)
    fake[4:6] = b"\0\0"
    valid = _stored_pk7(25, 0x1234ABCD)
    noise_count = 33000
    data = bytes(fake) * noise_count + valid
    stats: dict[str, int] = {}
    found = WindowsProcessMemory._candidate_zero_sanity_records(
        data, absolute_base=0x10000000, record_size=PK7_STORED_SIZE, sanity_offset=4,
        max_candidates=1, candidate_validator=lambda raw: raw == valid, scan_stats=stats,
    )
    assert len(found) == 1
    assert found[0][1] == valid
    assert stats["nonempty_sanity_candidates"] > 1
    assert stats["semantic_rejections"] >= noise_count
    assert stats["accepted_candidates"] == 1
