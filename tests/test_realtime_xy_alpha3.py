from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.azahar_rpc import AzaharProcess
from app.models import PendingInventoryChange, PendingRoleChange
from app.realtime import RealTimeCore, RealTimeRegistry, XYRealTimeAdapter
from app.realtime.adapter import RealTimeAdapterError
from app.realtime_memory import MemoryCandidateHint
from app.save_engine_client import SaveGameData, SavePokemon
from app.xy_live import (
    XYLiveError,
    XYLiveReader,
    XYLiveWriter,
    XY_PARTY_ADDRESS,
    XY_PARTY_STATS_OFFSET,
    XY_PARTY_STATS_SIZE,
    XY_PARTY_STRIDE,
    XY_SAVE_MISC_OFFSET,
    XY_SAVE_MISC_SIZE,
    XY_MISC_BADGES_OFFSET,
    XY_TITLE_IDS,
)
from app.oras_live import PK6_STORED_SIZE


def _pokemon() -> SavePokemon:
    return SavePokemon(
        slot=1, species_id=25, species="Pikachu", nickname="Pika", level=20,
        held_item="", ability="Static", moves=["1", "2", "3", "4"], move_ids=[1, 2, 3, 4],
        is_egg=False, markings=[True, False, False, False, False, False],
        role="Líbero", role_symbol="●", pid=123, tid=456, sid=789,
        current_hp=30, max_hp=40,
    )


def _game() -> SaveGameData:
    return SaveGameData("X", "SAV6XY", 6, "Timper", [_pokemon()], {})


class _ReadLogClient:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    def read_memory(self, address: int, size: int) -> bytes:
        self.calls.append((int(address), int(size)))
        return bytes(size)


def test_xy_process_detection_prioritizes_title_id_then_name_fallback() -> None:
    tid = next(iter(XY_TITLE_IDS))
    chosen = XYLiveReader._find_xy_process([
        AzaharProcess(1, 0x111, "kujira-1"),
        AzaharProcess(2, tid, "nombre-raro"),
    ])
    assert chosen.process_id == 2

    fallback = XYLiveReader._find_xy_process([AzaharProcess(3, 0, "kujira-2")])
    assert fallback.process_id == 3

    with pytest.raises(XYLiveError):
        XYLiveReader._find_xy_process([AzaharProcess(4, 0, "sango-2")])


def test_xy_party_reader_uses_xy_sparse_party_base_and_stride() -> None:
    client = _ReadLogClient()
    slots = XYLiveReader._read_party(client)
    assert len(slots) == 6
    expected: list[tuple[int, int]] = []
    for index in range(6):
        base = XY_PARTY_ADDRESS + index * XY_PARTY_STRIDE
        expected.extend([
            (base, PK6_STORED_SIZE),
            (base + XY_PARTY_STATS_OFFSET, XY_PARTY_STATS_SIZE),
        ])
    assert client.calls == expected


class _AdapterReader:
    client_factory = staticmethod(lambda: None)

    def read_monitor(self, current, memory_blocks=()):
        return SimpleNamespace(
            game=current,
            process=AzaharProcess(7, next(iter(XY_TITLE_IDS)), "kujira-1"),
            attempts=1,
            memory_blocks=(),
        )

    read = read_monitor


class _AdapterWriter:
    last_badge_source = "Misc vivo X/Y"
    block_resolver = SimpleNamespace(last_resolutions=())

    def read_badges(self, _save_path):
        return 3

    def apply(self, current, changes):
        return (current, changes)

    def runtime_memory_requests(self):
        return ()

    def reset_runtime_state(self):
        return None


def test_xy_adapter_produces_common_snapshot_and_keeps_optional_lanes_isolated() -> None:
    adapter = XYRealTimeAdapter(_AdapterReader(), _AdapterWriter())
    result = adapter.capture_monitor(_game(), save_path=Path("main"), sequence=9)
    assert result.adapter_key == "xy-azahar-rpc"
    assert result.sequence == 9
    assert result.badges == 3
    assert result.badge_source == "Misc vivo X/Y"
    assert result.battle.state == "unknown"
    assert result.diagnostic("party").level.value == "ok"
    assert result.diagnostic("battle").level.value == "warning"


def test_xy_core_uses_same_registry_and_event_pipeline_as_oras() -> None:
    adapter = XYRealTimeAdapter(_AdapterReader(), _AdapterWriter())
    registry = RealTimeRegistry()
    core = registry.register(adapter)
    assert registry.core_for("XY") is core
    snapshot = core.capture_monitor(_game(), save_path=None)
    assert snapshot.sequence == 1
    assert registry.supported_games == ("xy",)


def test_xy_alpha3_adapter_surface_can_be_extended_by_later_core_versions() -> None:
    # Alpha.6 conecta estas operaciones al adapter. Los dobles antiguos no las
    # implementan; el contrato real se cubre en test_realtime_xy_alpha6.py.
    adapter = XYRealTimeAdapter(_AdapterReader(), _AdapterWriter())
    with pytest.raises(AttributeError):
        adapter.read_tm_inventory({})
    with pytest.raises(AttributeError):
        adapter.read_pc(())


def test_xy_writer_rejects_mixing_inventory_with_pokemon_changes_before_touching_rpc() -> None:
    touched = False

    def client_factory():
        nonlocal touched
        touched = True
        raise AssertionError("No debe abrir RPC para un lote mixto protegido.")

    reader = XYLiveReader(Path("missing.json"), client_factory=client_factory, stable_delay=0)
    writer = XYLiveWriter(reader, move_pp_for=lambda _move: 10)
    inventory = PendingInventoryChange("money-max", "Dinero", 9_999_999)
    role = PendingRoleChange(1, "Prueba", "Pikachu", "Líbero", "Mago")
    with pytest.raises(XYLiveError, match="no se mezclan"):
        writer.apply(_game(), [inventory, role])
    assert not touched


def _saved_misc(badges: int) -> bytes:
    raw = bytearray(XY_SAVE_MISC_SIZE)
    # Huella estable suficientemente rica, fuera de dinero/medallas/BP.
    for index in range(0x50, 0xA0):
        raw[index] = ((index * 37) % 251) + 1
    raw[XY_MISC_BADGES_OFFSET] = badges
    return bytes(raw)


class _MiscClient:
    def __init__(self, memory: dict[int, bytes]) -> None:
        self.memory = memory
        self.process = AzaharProcess(55, next(iter(XY_TITLE_IDS)), "kujira-1")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def process_list(self):
        return [self.process]

    def set_process(self, _pid: int):
        return None

    def read_memory(self, address: int, size: int):
        raw = self.memory.get(int(address))
        if raw is None:
            return bytes(size)
        return bytes(raw[:size]).ljust(size, b"\0")


def test_xy_misc_resolver_picks_advanced_live_copy_then_keeps_it_after_state_regression(tmp_path: Path) -> None:
    save = tmp_path / "main"
    saved = _saved_misc(2)
    payload = bytearray(XY_SAVE_MISC_OFFSET + XY_SAVE_MISC_SIZE)
    payload[XY_SAVE_MISC_OFFSET:XY_SAVE_MISC_OFFSET + XY_SAVE_MISC_SIZE] = saved
    save.write_bytes(payload)

    old_address = 0x08C00000
    live_address = 0x08C10000
    old = bytearray(saved)
    live = bytearray(saved)
    old[XY_MISC_BADGES_OFFSET] = 2
    live[XY_MISC_BADGES_OFFSET] = 8
    memory = {old_address: bytes(old), live_address: bytes(live)}

    reader = XYLiveReader(Path("missing.json"), client_factory=lambda: _MiscClient(memory), stable_delay=0)
    writer = XYLiveWriter(reader, move_pp_for=lambda _move: 10)
    writer._discover_misc = lambda _client, _saved: (
        MemoryCandidateHint(old_address, "copia antigua", 0),
        MemoryCandidateHint(live_address, "copia viva", 0),
    )

    assert writer.read_badges(save) == 8
    assert writer.block_resolver.cached_address(
        (next(iter(XY_TITLE_IDS)), "kujira-1"), "xy.misc"
    ) == live_address

    # Un state-load puede bajar el progreso; la estructura cacheada sigue siendo
    # la fuente de verdad en vez de saltar a otra copia histórica.
    regressed = bytearray(live)
    regressed[XY_MISC_BADGES_OFFSET] = 5
    memory[live_address] = bytes(regressed)
    assert writer.read_badges(save) == 5
    assert writer.last_badge_source == "Misc vivo X/Y"


def test_xy_runtime_state_advertises_only_capabilities_calibrated_in_alpha3() -> None:
    adapter = XYRealTimeAdapter(_AdapterReader(), _AdapterWriter())
    state = adapter.runtime_state()
    caps = state["capabilities"]
    assert caps["party"] == "read-write"
    assert caps["badges"] == "read-live-with-save-fallback"
    assert caps["pc"] == "read-live"
    assert caps["tm_inventory"] == "read-live"
    assert caps["battle"] == "read-live-with-postbattle-fallback"
