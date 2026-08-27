from __future__ import annotations

import json
import os
import struct

import pytest

from app.realtime.bridge import RyujinxBridge, RyujinxGDBDiagnosticBridge
from app.ryujinx_host_memory import (
    RYUJINX_HOST_ADDRESS_SPACE_SIZE,
    RyujinxHostMappedClient,
    RyujinxHostMemoryError,
    RyujinxHostProcess,
    RyujinxHostProfile,
    RyujinxHostRegion,
    RyujinxHostSettings,
    _WindowsRyujinxReadOnlyBackend,
    discover_ryujinx_host_settings,
    parse_ryujinx_window_identity,
    paired_hostmapped_regions,
)


MEM_COMMIT = 0x1000
MEM_MAPPED = 0x40000
PAGE_READWRITE = 0x04


class FakeHostBackend:
    def __init__(self, regions: list[RyujinxHostRegion], segments: dict[int, bytes]) -> None:
        self._regions = regions
        self._segments = {int(address): bytes(data) for address, data in segments.items()}
        self.closed = 0
        self.opened_pid: int | None = None

    def list_processes(self) -> list[RyujinxHostProcess]:
        return [RyujinxHostProcess(77, "Ryujinx.exe", "test", 1, "1.0.0")]

    def open_read_only(self, pid: int):
        self.opened_pid = int(pid)
        return object()

    def close(self, _handle) -> None:
        self.closed += 1

    def regions(self, _handle):
        return iter(self._regions)

    def read(self, _handle, address: int, size: int) -> bytes:
        for base, data in self._segments.items():
            offset = int(address) - int(base)
            if 0 <= offset and offset + int(size) <= len(data):
                return data[offset:offset + int(size)]
        raise RyujinxHostMemoryError(f"unmapped 0x{int(address):X}+{int(size)}")


def _settings() -> RyujinxHostSettings:
    return RyujinxHostSettings(False, "HostMappedUnsafe", None)


def test_discovers_hostmapped_and_gdb_state_without_mutating_config(tmp_path, monkeypatch) -> None:
    path = tmp_path / "Ryujinx" / "Config.json"
    path.parent.mkdir()
    path.write_text(json.dumps({
        "enable_gdb_stub": False,
        "memory_manager_mode": "HostMappedUnsafe",
    }), encoding="utf-8")
    before = path.read_bytes()
    monkeypatch.setenv("APPDATA", str(tmp_path))

    settings = discover_ryujinx_host_settings()

    assert settings == RyujinxHostSettings(False, "HostMappedUnsafe", path)
    assert path.read_bytes() == before


def test_parses_observed_and_custom_ryujinx_window_identities() -> None:
    assert parse_ryujinx_window_identity(
        "Ryujinx 1.3.3 - Pokémon Perla Reluciente v1.3.0 (010018E011D92000) (64-bit)"
    ) == (0x010018E011D92000, "1.3.0")
    assert parse_ryujinx_window_identity(
        "Ryujinx 1.3.3\nPokémon Perla Reluciente\nv1.3.0\n(010018E011D92000) (64-bit)"
    ) == (0x010018E011D92000, "1.3.0")
    assert parse_ryujinx_window_identity("Ryujinx 1.3.3") is None


@pytest.mark.skipif(os.name != "nt", reason="La producción Ryujinx HostMapped es Windows-only.")
def test_windows_backend_binds_window_identity_through_user32() -> None:
    backend = _WindowsRyujinxReadOnlyBackend()

    assert backend.user32.EnumWindows
    assert backend.user32.GetWindowThreadProcessId
    assert backend.user32.GetWindowTextW


def test_selects_only_equal_committed_mapped_pairs_separated_by_39_bits() -> None:
    lower = RyujinxHostRegion(0x10000000000, 0x4000, MEM_COMMIT, PAGE_READWRITE, MEM_MAPPED)
    mirror = RyujinxHostRegion(
        lower.base + RYUJINX_HOST_ADDRESS_SPACE_SIZE,
        lower.size,
        MEM_COMMIT,
        PAGE_READWRITE,
        MEM_MAPPED,
    )
    private = RyujinxHostRegion(0x30000000000, 0x4000, MEM_COMMIT, PAGE_READWRITE, 0x20000)

    assert paired_hostmapped_regions((lower, mirror, private)) == (lower,)


def test_unique_profile_witness_calibrates_guest_reads_and_pointer_chain() -> None:
    lower_base = 0x10000000000
    lower = RyujinxHostRegion(lower_base, 0x10000, MEM_COMMIT, PAGE_READWRITE, MEM_MAPPED)
    mirror = RyujinxHostRegion(
        lower_base + RYUJINX_HOST_ADDRESS_SPACE_SIZE,
        lower.size,
        MEM_COMMIT,
        PAGE_READWRITE,
        MEM_MAPPED,
    )
    profile = RyujinxHostProfile(
        "test", "Test Game", "1.0.0", 1, 0x1000, b"RoleRun-main-witness",
    )
    region = bytearray(lower.size)
    host_main = lower_base + 0x1000
    region[0x1000:0x1000 + len(profile.main_witness)] = profile.main_witness
    struct.pack_into("<Q", region, 0x1040, 0x2000)
    struct.pack_into("<Q", region, 0x2010, 0x3000)
    region[0x3020:0x3028] = b"RoleRun!"
    backend = FakeHostBackend([lower, mirror], {lower_base: bytes(region)})

    with RyujinxHostMappedClient(
        profile, backend=backend, settings=_settings(), scan_budget=lower.size,
    ) as client:
        assert client.session.host_main == host_main
        assert client.session.guest_to_host_delta == lower_base
        assert client.resolve_main_pointer((0x40, 0x10, 0x20)) == 0x3020
        assert client.read_memory(0x3020, 8) == b"RoleRun!"
        assert not hasattr(client, "write_memory")

    assert backend.opened_pid == 77
    assert backend.closed == 1


def test_rejects_gdb_enabled_before_opening_process() -> None:
    profile = RyujinxHostProfile("test", "Test", "1", 1, 0x1000, b"witness")
    backend = FakeHostBackend([], {})
    client = RyujinxHostMappedClient(
        profile,
        backend=backend,
        settings=RyujinxHostSettings(True, "HostMappedUnsafe", None),
    )

    with pytest.raises(RyujinxHostMemoryError, match="GDB Stub debe estar desactivado"):
        client.connect()

    assert backend.opened_pid is None


def test_rejects_wrong_title_before_opening_process() -> None:
    profile = RyujinxHostProfile("sp", "SP", "1.3.0", 0x010018E011D92000, 0x1000, b"witness")
    backend = FakeHostBackend([], {})

    with pytest.raises(RyujinxHostMemoryError, match="el perfil exige 010018E011D92000"):
        RyujinxHostMappedClient(profile, backend=backend, settings=_settings()).connect()

    assert backend.opened_pid is None


def test_rejects_ambiguous_main_witness() -> None:
    gap = RYUJINX_HOST_ADDRESS_SPACE_SIZE
    profile = RyujinxHostProfile("test", "Test", "1.0.0", 1, 0x1000, b"same-witness")
    regions: list[RyujinxHostRegion] = []
    segments: dict[int, bytes] = {}
    for lower_base in (0x10000000000, 0x30000000000):
        lower = RyujinxHostRegion(lower_base, 0x4000, MEM_COMMIT, PAGE_READWRITE, MEM_MAPPED)
        regions.extend((
            lower,
            RyujinxHostRegion(lower_base + gap, lower.size, MEM_COMMIT, PAGE_READWRITE, MEM_MAPPED),
        ))
        data = bytearray(lower.size)
        data[0x1000:0x1000 + len(profile.main_witness)] = profile.main_witness
        segments[lower_base] = bytes(data)
    backend = FakeHostBackend(regions, segments)

    with pytest.raises(RyujinxHostMemoryError, match="produjo 2 candidatos"):
        RyujinxHostMappedClient(
            profile, backend=backend, settings=_settings(), scan_budget=0x8000,
        ).connect()

    assert backend.closed == 1


def test_realtime_bridge_defaults_to_hostmapped_and_keeps_gdb_diagnostic_separate() -> None:
    host = RyujinxBridge(client_factory=lambda: None)  # type: ignore[arg-type]
    diagnostic = RyujinxGDBDiagnosticBridge(client_factory=lambda: None)  # type: ignore[arg-type]

    assert host.info.key == "ryujinx"
    assert host.info.transport == "HostMapped read-only"
    assert diagnostic.info.key == "ryujinx-gdb-diagnostic"
