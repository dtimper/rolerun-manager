from __future__ import annotations

import struct
from pathlib import Path
from types import SimpleNamespace

from app.azahar_rpc import AzaharProcess
from app.oras_live import PK6_PARTY_SIZE, PK6_STORED_SIZE, _checksum, encrypt_pk6
from app.xy_live import (
    XYLiveReader,
    XY_PC_KNOWN_ADDRESS,
    XY_PC_SIZE,
    XY_TITLE_IDS,
)
from app.realtime_memory import MemoryCandidateHint
from app.ui import RoleRunManager


def _pk6(*, species: int, pid: int, nickname: str) -> bytes:
    data = bytearray(PK6_PARTY_SIZE)
    struct.pack_into("<I", data, 0, 0x12345678)
    struct.pack_into("<H", data, 8, species)
    struct.pack_into("<H", data, 0x0C, 55730)
    struct.pack_into("<H", data, 0x0E, 50155)
    struct.pack_into("<I", data, 0x18, pid)
    encoded = nickname.encode("utf-16le")
    data[0x40:0x40 + len(encoded)] = encoded
    struct.pack_into("<4H", data, 0x5A, 33, 45, 0, 0)
    struct.pack_into("<I", data, 0x74, 0x3FFFFFFF)
    struct.pack_into("<H", data, 6, _checksum(data))
    return encrypt_pk6(bytes(data))[:PK6_STORED_SIZE]


class _MemoryClient:
    def __init__(self, actual_base: int, matrix: bytes):
        self.actual_base = int(actual_base)
        self.matrix = bytes(matrix)
        self.process = AzaharProcess(11, next(iter(XY_TITLE_IDS)), "kujira-1")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def process_list(self):
        return [self.process]

    def set_process(self, _process_id):
        return None

    def read_memory(self, address: int, size: int) -> bytes:
        result = bytearray(size)
        overlap_start = max(int(address), self.actual_base)
        overlap_end = min(int(address) + int(size), self.actual_base + len(self.matrix))
        if overlap_start < overlap_end:
            result[overlap_start - int(address):overlap_end - int(address)] = self.matrix[
                overlap_start - self.actual_base:overlap_end - self.actual_base
            ]
        return bytes(result)


def test_xy_live_pc_without_save_anchors_calibrates_unique_populated_matrix() -> None:
    """Regresión de v0.2.4-alpha.5: tres PK6 no pueden publicarse como PC vacío."""
    actual_base = XY_PC_KNOWN_ADDRESS - 0x10
    matrix = bytearray(XY_PC_SIZE)
    expected = (
        (406, 497061732, "Budew"),
        (165, 1908924382, "Ledyba"),
        (300, 3812017955, "Skitty"),
    )
    for index, (species, pid, nickname) in enumerate(expected):
        start = index * PK6_STORED_SIZE
        matrix[start:start + PK6_STORED_SIZE] = _pk6(
            species=species, pid=pid, nickname=nickname,
        )
    client = _MemoryClient(actual_base, matrix)
    reader = XYLiveReader(Path("missing.json"), client_factory=lambda: client, stable_delay=0)

    _process, resolved, slots = reader.read_pc([])

    assert resolved == actual_base
    assert [slots[(1, slot)].species_id for slot in (1, 2, 3)] == [406, 165, 300]
    assert all(slots[(1, slot)] is not None for slot in (1, 2, 3))


def test_xy_cached_nominal_base_is_replaced_by_new_structural_evidence() -> None:
    actual_base = XY_PC_KNOWN_ADDRESS - 0x10
    matrix = bytearray(XY_PC_SIZE)
    for index, (species, pid, nickname) in enumerate((
        (406, 1, "Budew"), (165, 2, "Ledyba"), (300, 3, "Skitty"),
    )):
        start = index * PK6_STORED_SIZE
        matrix[start:start + PK6_STORED_SIZE] = _pk6(
            species=species, pid=pid, nickname=nickname,
        )
    client = _MemoryClient(actual_base, matrix)
    reader = XYLiveReader(Path("missing.json"), client_factory=lambda: client, stable_delay=0)
    key = (int(client.process.title_id), client.process.name, reader.transport_label)
    reader._pc_bases_by_process[key] = XY_PC_KNOWN_ADDRESS

    _process, resolved, slots = reader.read_pc([])

    assert resolved == actual_base
    assert reader._pc_bases_by_process[key] == actual_base
    assert sum(pokemon is not None for pokemon in slots.values()) == 3


def test_xy_pc_without_anchors_rejects_ambiguous_structural_matrices() -> None:
    client = _MemoryClient(XY_PC_KNOWN_ADDRESS, bytes(XY_PC_SIZE))
    reader = XYLiveReader(Path("missing.json"), client_factory=lambda: client, stable_delay=0)
    reader._discover_pc_base_near_known_from_structure = lambda _client: (
        MemoryCandidateHint(XY_PC_KNOWN_ADDRESS - 0x10, "matriz A", 3),
        MemoryCandidateHint(XY_PC_KNOWN_ADDRESS + 0x10, "matriz B", 2),
    )

    _process, resolved, slots = reader.read_pc([])

    assert resolved == XY_PC_KNOWN_ADDRESS
    assert all(pokemon is None for pokemon in slots.values())


def test_xy_initial_sync_requests_live_pc_even_when_party_did_not_change() -> None:
    """La caja viva debe publicarse también con una party inicial idéntica."""
    calls: list[str] = []

    def finish_live_sync(*_args, **_kwargs) -> None:
        calls.append("party-published")
        manager._oras_live_active = True

    manager = SimpleNamespace(
        _oras_auto_sync_in_progress=True,
        _oras_auto_sync_token=7,
        _session_generation=3,
        project=SimpleNamespace(slug="xy-test"),
        current_game=object(),
        save_engine=SimpleNamespace(key="xy"),
        _oras_live_active=False,
        _initial_shell_waiting=False,
        _initial_shell_live_probe_complete=False,
        _active_azahar_realtime_key=lambda: "xy",
        _finish_oras_live_sync=finish_live_sync,
        _schedule_gen6_live_pc_refresh=lambda: calls.append("pc-refreshed"),
        after=lambda _delay, callback: callback(),
    )

    RoleRunManager._finish_oras_initial_auto_sync(
        manager, 3, "xy-test", 7, SimpleNamespace(), None,
    )

    assert calls == ["party-published", "pc-refreshed"]
