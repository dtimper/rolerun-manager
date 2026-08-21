from __future__ import annotations

import json
import zipfile
from pathlib import Path

from app.realtime import RealTimeCore, RealTimeReplay
from app.realtime.adapter import RealTimeGameAdapter
from app.realtime.models import LiveMemoryBlock, LiveProcessInfo, RealTimeSnapshot
from app.realtime_memory import LiveBlockResolver, MemoryCandidateHint
from app.save_engine_client import SaveGameData, SavePokemon


def _pokemon() -> SavePokemon:
    return SavePokemon(
        slot=1, species_id=25, species="Pikachu", nickname="Pika", level=10,
        held_item="", ability="Static", moves=["1", "2", "3", "4"], move_ids=[1, 2, 3, 4],
        is_egg=False, markings=[False] * 6, role="Líbero", role_symbol="●",
        pid=1, tid=2, sid=3, current_hp=20, max_hp=30,
    )


def _game() -> SaveGameData:
    return SaveGameData("AS", "SAV6AO", 6, "Timper", [_pokemon()], {})


def test_live_block_resolver_prefers_best_initial_candidate_then_keeps_cache_on_regression() -> None:
    memory = {0x1000: b"\x02", 0x2000: b"\x08"}
    resolver = LiveBlockResolver()

    def read(address: int):
        return memory.get(address)

    def validate(raw: bytes):
        return (raw[0],) if raw and raw[0] <= 8 else None

    first = resolver.resolve(
        "badges", (1, "game"), read_at=read, validate=validate,
        preferred=(
            MemoryCandidateHint(0x1000, "old", 0),
            MemoryCandidateHint(0x2000, "active", 0),
        ),
    )
    assert first.address == 0x2000
    assert not first.cache_hit

    # Cargar un state anterior debe conservar la misma estructura viva, aunque
    # otra copia de RAM siga mostrando más progreso.
    memory[0x2000] = b"\x05"
    second = resolver.resolve(
        "badges", (1, "game"), read_at=read, validate=validate,
        preferred=(MemoryCandidateHint(0x1000, "old", 999),),
    )
    assert second.address == 0x2000
    assert second.cache_hit
    assert second.score == (5,)


def test_live_block_resolver_scans_only_after_direct_candidates_fail() -> None:
    memory = {0x3000: b"OK"}
    scans = 0
    resolver = LiveBlockResolver()

    def discover():
        nonlocal scans
        scans += 1
        return [MemoryCandidateHint(0x3000, "signature", 0)]

    result = resolver.resolve(
        "inventory", "session", read_at=lambda a: memory.get(a),
        validate=lambda raw: (1,) if raw == b"OK" else None,
        preferred=(MemoryCandidateHint(0x1000, "nominal", 100),),
        discover=discover,
    )
    assert scans == 1
    assert result.success and result.address == 0x3000
    assert result.source == "signature"


class RecordingAdapter(RealTimeGameAdapter):
    key = "recording"
    game_key = "recording"
    display_name = "Recording"

    def __init__(self) -> None:
        self.memory_requests = ()

    def capture_monitor(self, current, *, save_path, memory_requests=(), sequence=0):
        self.memory_requests = tuple(memory_requests)
        blocks = tuple(LiveMemoryBlock(address, bytes([size & 0xFF])) for address, size in memory_requests)
        return RealTimeSnapshot(
            game=current,
            process=LiveProcessInfo("fake", 1, 2, "fake-process"),
            attempts=1, adapter_key=self.key, profile="test", badges=3,
            sequence=sequence, memory_blocks=blocks,
        )

    capture_full = capture_monitor

    def diagnostic_memory_requests(self):
        return ((0x2000, 16),)

    def runtime_state(self):
        return {"adapter": self.key, "memory_resolutions": [{"block": "bag", "address": 0x2000, "success": True}]}


def test_recording_augments_snapshot_with_adapter_diagnostic_blocks_and_packages_replay(tmp_path: Path) -> None:
    adapter = RecordingAdapter()
    core = RealTimeCore(adapter)
    raw = tmp_path / "session.ndjson"
    package = tmp_path / "session.zip"
    core.start_recording(raw)
    core.capture_monitor(_game(), save_path=None, memory_requests=((0x1000, 4),))
    result = core.stop_recording(package_path=package, metadata={"app_version": "test"})

    assert result == package
    assert adapter.memory_requests == ((0x1000, 4), (0x2000, 16))
    assert package.exists()
    with zipfile.ZipFile(package) as archive:
        assert {"session.ndjson", "manifest.json", "LEEME.txt"}.issubset(archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["frames"] == 1
        assert manifest["app_version"] == "test"
        row = json.loads(archive.read("session.ndjson").decode("utf-8").strip())
        assert row["runtime_state"]["adapter"] == "recording"
        assert {block["address"] for block in row["memory_blocks"]} == {0x1000, 0x2000}

    summary = RealTimeReplay(package).summary()
    assert summary.frames == 1
    assert summary.badges_seen == (3,)
    assert summary.adapters == ("recording",)


def test_diagnostic_report_is_useful_without_ui() -> None:
    adapter = RecordingAdapter()
    core = RealTimeCore(adapter)
    core.capture_monitor(_game(), save_path=None)
    report = core.diagnostic_report()
    assert "REAL-TIME CORE" in report
    assert "Medallas: 3" in report
    assert "BLOQUES DE RAM RESUELTOS" in report
