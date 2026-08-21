from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.realtime import (
    BattleState,
    DiagnosticLevel,
    LiveDiagnostic,
    LiveProcessInfo,
    ORASRealTimeAdapter,
    RealTimeCore,
    RealTimeEventType,
    RealTimeSnapshot,
)
from app.realtime.adapter import RealTimeGameAdapter
from app.save_engine_client import SaveGameData, SavePokemon


def pokemon(*, role="Líbero", hp=20, level=10, moves=(1, 2, 3, 4)) -> SavePokemon:
    return SavePokemon(
        slot=1, species_id=25, species="Pikachu", nickname="Pika", level=level,
        held_item="", ability="Static", moves=[str(x) for x in moves], move_ids=list(moves),
        is_egg=False, markings=[False] * 6, role=role, role_symbol="●",
        pid=123, tid=456, sid=789, current_hp=hp, max_hp=35,
    )


def game(p: SavePokemon | None = None) -> SaveGameData:
    return SaveGameData("AS", "SAV6AO", 6, "Timper", [p or pokemon()], {})


class FakeAdapter(RealTimeGameAdapter):
    key = "fake"
    game_key = "test"
    display_name = "Fake"

    def __init__(self, snapshots):
        self.snapshots = list(snapshots)
        self.full_calls = 0
        self.monitor_calls = 0
        self.tm_calls = 0

    def _next(self, sequence: int):
        source = self.snapshots.pop(0)
        return RealTimeSnapshot(
            game=source.game, process=source.process, attempts=source.attempts,
            adapter_key=self.key, profile="test", battle=source.battle,
            badges=source.badges, badge_source=source.badge_source,
            diagnostics=source.diagnostics, sequence=sequence,
        )

    def capture_monitor(self, current, *, save_path, memory_requests=(), sequence=0):
        self.monitor_calls += 1
        return self._next(sequence)

    def capture_full(self, current, *, save_path, memory_requests=(), sequence=0):
        self.full_calls += 1
        return self._next(sequence)

    def read_tm_inventory(self, saved_items=None):
        self.tm_calls += 1
        return {328: 1}, object(), 1


def snap(g: SaveGameData, badges=0, battle="none"):
    return RealTimeSnapshot(
        game=g,
        process=LiveProcessInfo("azahar", 1, 2, "sango-2"),
        attempts=1, adapter_key="fake", profile="test",
        battle=BattleState(battle), badges=badges,
    )


def test_core_sequences_snapshots_and_generates_semantic_events() -> None:
    first = snap(game(pokemon(hp=20)), badges=2, battle="none")
    second = snap(game(pokemon(hp=0)), badges=3, battle="trainer")
    adapter = FakeAdapter([first, second])
    core = RealTimeCore(adapter)

    one = core.capture_monitor(first.game, save_path=None)
    assert one.sequence == 1
    assert core.last_events == ()

    two = core.capture_monitor(first.game, save_path=None)
    assert two.sequence == 2
    types = {event.type for event in core.last_events}
    assert RealTimeEventType.POKEMON_FAINTED in types
    assert RealTimeEventType.BADGE_CHANGED in types
    assert RealTimeEventType.BATTLE_STATE_CHANGED in types


def test_reset_history_keeps_sequence_but_breaks_cross_state_diff() -> None:
    first = snap(game(), badges=2)
    second = snap(game(pokemon(role="Mago")), badges=3)
    core = RealTimeCore(FakeAdapter([first, second]))
    core.capture_monitor(first.game, save_path=None)
    core.reset_history()
    result = core.capture_monitor(first.game, save_path=None)
    assert result.sequence == 2
    assert core.last_events == ()


def test_tm_inventory_goes_through_adapter() -> None:
    adapter = FakeAdapter([])
    core = RealTimeCore(adapter)
    inventory, _process, attempts = core.read_tm_inventory({328: 1})
    assert inventory == {328: 1}
    assert attempts == 1
    assert adapter.tm_calls == 1


def test_recorder_writes_replayable_json_line(tmp_path: Path) -> None:
    source = snap(game(), badges=8)
    core = RealTimeCore(FakeAdapter([source]))
    output = tmp_path / "session.ndjson"
    core.start_recording(output)
    core.capture_monitor(source.game, save_path=None)
    core.stop_recording()

    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["adapter"] == "fake"
    assert rows[0]["badges"] == 8
    assert rows[0]["party"][0]["species_id"] == 25


class FailingBattleReader:
    stable_delay = 0
    snapshot_attempts = 1
    client_factory = lambda self: None

    def read_monitor(self, current, memory_blocks=()):
        return SimpleNamespace(
            game=current,
            process=SimpleNamespace(process_id=7, title_id=8, name="sango-2"),
            attempts=1,
            memory_blocks=(),
        )

    read = read_monitor

    def read_battle_probe(self, current):
        raise RuntimeError("battle exploded")

    def read_pc(self, anchors):
        return "process", 123, "pc"


class BadgeWriter:
    last_badge_source = "Premios líderes · MT/MO"

    def read_badges(self, save_path):
        return 8

    def read_tm_inventory(self, saved_items=None):
        return {328: 1}, "process", 1


def test_oras_adapter_keeps_party_valid_when_optional_battle_lane_fails() -> None:
    adapter = ORASRealTimeAdapter(FailingBattleReader(), BadgeWriter())
    source = game()
    result = adapter.capture_monitor(source, save_path=Path("main"), sequence=4)
    assert result.sequence == 4
    assert result.game is source
    assert result.badges == 8
    assert result.battle.state == "unknown"
    battle_diag = result.diagnostic("battle")
    assert battle_diag is not None
    assert battle_diag.level is DiagnosticLevel.WARNING
    assert "battle exploded" in battle_diag.message
    badges_diag = result.diagnostic("badges")
    assert badges_diag is not None and badges_diag.level is DiagnosticLevel.OK


def test_oras_full_capture_does_not_depend_on_optional_lanes() -> None:
    adapter = ORASRealTimeAdapter(FailingBattleReader(), BadgeWriter())
    source = game()
    result = adapter.capture_full(source, save_path=Path("main"), sequence=1)
    assert result.game is source
    assert result.badges is None
    assert result.battle.state == "unknown"
    assert [diag.lane for diag in result.diagnostics] == ["party"]


def test_registry_resolves_core_by_game_key() -> None:
    from app.realtime import RealTimeRegistry

    adapter = FakeAdapter([])
    registry = RealTimeRegistry()
    core = registry.register(adapter)
    assert registry.core_for("TEST") is core
    assert registry.supported_games == ("test",)
    assert registry.core_for("xy") is None
