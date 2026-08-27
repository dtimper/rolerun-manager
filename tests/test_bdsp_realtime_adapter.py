from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import json

import pytest

from app.bdsp_live import (
    BDSP_SP_130_HOST_PROFILE,
    BDSPBattlePokemon,
    BDSPBattlePresentationRead,
    BDSPBattlePresentationWindow,
    BDSPBattleRead,
    BDSPBoxPokemon,
    BDSPBoxRead,
    BDSPInventoryItem,
    BDSPInventoryRead,
    BDSPPartyPokemon,
    BDSPPartyRead,
)
from app.live_party_watch import detect_fainted_transitions
from app.realtime.bdsp_adapter import BDSPRealTimeAdapter
from app.realtime.models import DiagnosticLevel, badge_source_is_live
from app.save_engine_client import SaveGameData, SavePokemon


class _Client:
    def __init__(self) -> None:
        self.profile = BDSP_SP_130_HOST_PROFILE
        self.connect_calls = 0
        self.close_calls = 0
        self.session = SimpleNamespace(
            process=SimpleNamespace(
                pid=90210,
                exe_name="Ryujinx.exe",
                window_title="Pokémon Shining Pearl v1.3.0 (010018E011D92000)",
            ),
            profile=BDSP_SP_130_HOST_PROFILE,
            guest_to_host_delta=0x100000000,
        )

    def connect(self) -> None:
        self.connect_calls += 1

    def close(self) -> None:
        self.close_calls += 1

    def read_memory(self, address: int, size: int) -> bytes:
        return bytes([int(address) & 0xFF]) * int(size)


def _party_pokemon(
    slot: int,
    species: int,
    *,
    hp: int,
    max_hp: int,
    level: int,
    nickname: str,
    marked: int | None = None,
) -> BDSPPartyPokemon:
    markings = tuple(index == marked for index in range(6))
    return BDSPPartyPokemon(
        slot=slot,
        species_id=species,
        pid=0xA000 + slot,
        tid=123,
        sid=456,
        form=0,
        nickname=nickname,
        held_item_id=0,
        ability_id=1,
        move_ids=(1, 0, 0, 0),
        move_pp=(35, 0, 0, 0),
        move_pp_ups=(0, 0, 0, 0),
        is_egg=False,
        markings=markings,
        current_hp=hp,
        max_hp=max_hp,
        level=level,
        checksum=0x1234,
        encrypted=b"",
    )


def _party_read(*pokemon: BDSPPartyPokemon) -> BDSPPartyRead:
    return BDSPPartyRead(
        pokemon=tuple(pokemon),
        member_count=len(pokemon),
        party_object=0x200000,
        member_array=0x210000,
    )


def _battle_read(*pokemon: BDSPBattlePokemon) -> BDSPBattleRead:
    return BDSPBattleRead(
        pokemon=tuple(pokemon),
        member_count=len(pokemon),
        battle_party_object=0x300000,
        member_array=0x310000,
    )


def _presentation_read(
    *, hp: int, max_hp: int, poke_id: int, animation: bool = False,
    displayed: bool = True, setup: bool = True,
) -> BDSPBattlePresentationRead:
    return BDSPBattlePresentationRead(
        windows=(BDSPBattlePresentationWindow(
            window_index=0,
            displayed=displayed,
            current_hp=hp,
            max_hp=max_hp,
            level=25,
            poke_id=poke_id,
            is_player=True,
            needs_hp_apply=False,
            hp_animation=animation,
            initialized=True,
            setup=setup,
        ),),
        ui_instance=0x200000,
        status_array=0x210000,
    )


def _current() -> SaveGameData:
    return SaveGameData(
        game="SP", save_type="SAV8BS", generation=8, trainer="Lucía", party=[], raw={},
    )


def _adapter(
    party_read,
    battle_reader,
    client: _Client | None = None,
    presentation_reader=None,
) -> tuple[BDSPRealTimeAdapter, _Client]:
    client = client or _Client()
    adapter = BDSPRealTimeAdapter(
        client_factory=lambda: client,
        party_reader_factory=lambda _client: SimpleNamespace(read=lambda: party_read),
        battle_reader_factory=lambda _client: battle_reader,
        presentation_reader_factory=lambda _client: (
            presentation_reader or SimpleNamespace(read=lambda: None)
        ),
        role_layout_getter=lambda: 2,
    )
    return adapter, client


def test_bdsp_adapter_maps_reordered_battle_rows_by_poke_id_not_row() -> None:
    party = _party_read(
        _party_pokemon(1, 300, hp=21, max_hp=21, level=12, nickname="Skibidi", marked=0),
        _party_pokemon(2, 353, hp=58, max_hp=58, level=25, nickname="Shuppet", marked=1),
    )
    battle = _battle_read(
        # Después del cambio físico, la fila 1 era party index 1 y la fila 2 index 0.
        BDSPBattlePokemon(1, 1, 353, 41, 58, 25),
        BDSPBattlePokemon(2, 0, 300, 0, 21, 12),
    )
    adapter, client = _adapter(party, SimpleNamespace(read=lambda: battle))

    snapshot = adapter.capture_monitor(_current(), save_path=None, sequence=7)

    assert client.connect_calls == 1
    assert snapshot.sequence == 7
    assert snapshot.game.game == "SP"
    assert snapshot.game.party[0].species == "Skitty"
    assert snapshot.game.party[0].nickname == "Skibidi"
    assert snapshot.game.party[0].moves[0] == "Destructor"
    assert snapshot.game.party[0].role == "Líbero"
    assert snapshot.game.party[1].role == "Asesino"
    assert snapshot.battle.state == "battle"
    assert snapshot.battle.hp_pairs == ((0, 21), (41, 58))
    assert snapshot.battle.health_game is not None
    assert [pokemon.current_hp for pokemon in snapshot.battle.health_game.party] == [0, 41]
    assert snapshot.game.party[0].current_hp == 21  # PlayerWork sigue stale en combate.
    assert snapshot.diagnostic("battle").level is DiagnosticLevel.OK
    assert snapshot.metadata["writes_enabled"] is True


def test_bdsp_adapter_exposes_effective_nature_stats_ivs_and_evs() -> None:
    raw = replace(
        _party_pokemon(1, 300, hp=21, max_hp=21, level=12, nickname="Skibidi"),
        nature_id=3,
        stat_nature_id=3,
        ivs=(31, 30, 29, 28, 27, 26),
        evs=(4, 252, 0, 0, 0, 252),
        stats=(21, 18, 14, 11, 12, 23),
    )
    adapter, _client = _adapter(_party_read(raw), SimpleNamespace(read=lambda: None))

    pokemon = adapter.capture_monitor(_current(), save_path=None).game.party[0]

    assert pokemon.nature == "Firme"
    assert pokemon.nature_increased == "attack"
    assert pokemon.nature_decreased == "sp_attack"
    assert pokemon.stats == {
        "hp": 21, "attack": 18, "defense": 14,
        "sp_attack": 11, "sp_defense": 12, "speed": 23,
    }
    assert pokemon.ivs["speed"] == 26
    assert pokemon.evs == {
        "hp": 4, "attack": 252, "defense": 0,
        "sp_attack": 0, "sp_defense": 0, "speed": 252,
    }


def test_alpha77_bdsp_adapter_publishes_live_badges_and_source() -> None:
    party = _party_read(
        _party_pokemon(1, 300, hp=21, max_hp=21, level=12, nickname="Skitty"),
    )
    adapter = BDSPRealTimeAdapter(
        client_factory=_Client,
        party_reader_factory=lambda _client: SimpleNamespace(read=lambda: party),
        badge_reader_factory=lambda _client: SimpleNamespace(
            read=lambda: SimpleNamespace(count=2),
        ),
        battle_reader_factory=lambda _client: SimpleNamespace(read=lambda: None),
    )

    snapshot = adapter.capture_monitor(_current(), save_path=None, sequence=77)

    assert snapshot.badges == 2
    assert snapshot.badge_source == "SystemFlags vivos · PlayerWork.SaveData"
    assert badge_source_is_live(snapshot.badge_source) is True
    assert snapshot.diagnostic("badges").level is DiagnosticLevel.OK
    assert adapter.runtime_state()["capabilities"]["progress"] == (
        "read-live-alpha.77-system-flags-validated"
    )


def test_alpha77_bdsp_badge_failure_is_optional_and_preserves_party() -> None:
    party = _party_read(
        _party_pokemon(1, 300, hp=21, max_hp=21, level=12, nickname="Skitty"),
    )
    adapter = BDSPRealTimeAdapter(
        client_factory=_Client,
        party_reader_factory=lambda _client: SimpleNamespace(read=lambda: party),
        badge_reader_factory=lambda _client: SimpleNamespace(
            read=lambda: (_ for _ in ()).throw(RuntimeError("flags inestables")),
        ),
        battle_reader_factory=lambda _client: SimpleNamespace(read=lambda: None),
    )

    snapshot = adapter.capture_monitor(_current(), save_path=None)

    assert [pokemon.species_id for pokemon in snapshot.game.party] == [300]
    assert snapshot.badges is None
    assert snapshot.badge_source is None
    assert snapshot.diagnostic("badges").level is DiagnosticLevel.WARNING
    assert "flags inestables" in snapshot.diagnostic("badges").message


def test_bdsp_adapter_health_lane_exposes_only_positive_to_zero_transition() -> None:
    party = _party_read(
        _party_pokemon(1, 300, hp=21, max_hp=21, level=12, nickname="Skitty"),
    )
    samples = iter((
        _battle_read(BDSPBattlePokemon(1, 0, 300, 7, 21, 12)),
        _battle_read(BDSPBattlePokemon(1, 0, 300, 0, 21, 12)),
        _battle_read(BDSPBattlePokemon(1, 0, 300, 0, 21, 12)),
    ))
    presentation_samples = iter((
        _presentation_read(hp=7, max_hp=21, poke_id=0),
        _presentation_read(hp=0, max_hp=21, poke_id=0, animation=True),
        _presentation_read(hp=0, max_hp=21, poke_id=0, animation=False),
    ))
    adapter, _client = _adapter(
        party,
        SimpleNamespace(read=lambda: next(samples)),
        presentation_reader=SimpleNamespace(read=lambda: next(presentation_samples)),
    )

    before = adapter.capture_full(_current(), save_path=None).battle.health_game
    during = adapter.capture_monitor(_current(), save_path=None).battle.health_game
    after = adapter.capture_monitor(_current(), save_path=None).battle.health_game

    assert before is not None and during is not None and after is not None
    assert detect_fainted_transitions(before, during) == ()
    transitions = detect_fainted_transitions(before, after)
    assert len(transitions) == 1
    assert transitions[0].identity == (300, 0xA001, 123, 456)
    assert transitions[0].previous_hp == 7


def test_bdsp_adapter_waits_for_visible_zero_and_animation_completion(tmp_path) -> None:
    party = _party_read(
        _party_pokemon(1, 353, hp=58, max_hp=58, level=25, nickname="Shuppet"),
    )
    battle_samples = iter((
        _battle_read(BDSPBattlePokemon(1, 0, 353, 12, 58, 25)),
        _battle_read(BDSPBattlePokemon(1, 0, 353, 0, 58, 25)),
        _battle_read(BDSPBattlePokemon(1, 0, 353, 0, 58, 25)),
        _battle_read(BDSPBattlePokemon(1, 0, 353, 0, 58, 25)),
    ))
    presentation_samples = iter((
        _presentation_read(hp=12, max_hp=58, poke_id=0),
        # El cero lógico se adelanta 6,17 s al HP que presenta el juego.
        _presentation_read(hp=12, max_hp=58, poke_id=0),
        # _currentHP ya contiene el objetivo cero, pero la barra sigue bajando.
        _presentation_read(hp=0, max_hp=58, poke_id=0, animation=True),
        # Primera frontera que la captura física demuestra posterior al visual.
        _presentation_read(hp=0, max_hp=58, poke_id=0, animation=False),
    ))
    trace = tmp_path / "visible-gate.jsonl"
    adapter = BDSPRealTimeAdapter(
        client_factory=_Client,
        party_reader_factory=lambda _client: SimpleNamespace(read=lambda: party),
        battle_reader_factory=lambda _client: SimpleNamespace(
            read=lambda: next(battle_samples),
        ),
        presentation_reader_factory=lambda _client: SimpleNamespace(
            read=lambda: next(presentation_samples),
        ),
        trace_path=trace,
    )

    snapshots = [
        adapter.capture_monitor(_current(), save_path=None, sequence=index)
        for index in range(1, 5)
    ]

    published_hp = [snapshot.battle.hp_pairs[0][0] for snapshot in snapshots]
    assert published_hp == [12, 12, 12, 0]
    assert detect_fainted_transitions(
        snapshots[0].battle.health_game, snapshots[1].battle.health_game,
    ) == ()
    assert detect_fainted_transitions(
        snapshots[1].battle.health_game, snapshots[2].battle.health_game,
    ) == ()
    transitions = detect_fainted_transitions(
        snapshots[2].battle.health_game, snapshots[3].battle.health_game,
    )
    assert len(transitions) == 1
    rows = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    assert rows[1]["battle_logical_health"][0]["hp"] == 0
    assert rows[1]["battle_health"][0]["hp"] == 12
    assert rows[1]["battle_health_gate"][0]["reason"] == "presentation-pending"
    assert rows[2]["battle_health_gate"][0]["reason"] == "presentation-pending"
    assert rows[3]["battle_health_gate"][0]["reason"] == (
        "presentation-zero-animation-complete"
    )


def test_bdsp_adapter_waits_for_visible_positive_damage_animation(tmp_path) -> None:
    party = _party_read(
        _party_pokemon(1, 353, hp=58, max_hp=58, level=25, nickname="Shuppet"),
    )
    battle_samples = iter((
        _battle_read(BDSPBattlePokemon(1, 0, 353, 58, 58, 25)),
        _battle_read(BDSPBattlePokemon(1, 0, 353, 31, 58, 25)),
        _battle_read(BDSPBattlePokemon(1, 0, 353, 31, 58, 25)),
        _battle_read(BDSPBattlePokemon(1, 0, 353, 31, 58, 25)),
    ))
    presentation_samples = iter((
        _presentation_read(hp=58, max_hp=58, poke_id=0),
        _presentation_read(hp=58, max_hp=58, poke_id=0),
        _presentation_read(hp=31, max_hp=58, poke_id=0, animation=True),
        _presentation_read(hp=31, max_hp=58, poke_id=0, animation=False),
    ))
    adapter = BDSPRealTimeAdapter(
        client_factory=_Client,
        party_reader_factory=lambda _client: SimpleNamespace(read=lambda: party),
        battle_reader_factory=lambda _client: SimpleNamespace(read=lambda: next(battle_samples)),
        presentation_reader_factory=lambda _client: SimpleNamespace(read=lambda: next(presentation_samples)),
        trace_path=tmp_path / "positive-damage-gate.jsonl",
    )

    snapshots = [adapter.capture_monitor(_current(), save_path=None, sequence=index)
                 for index in range(1, 5)]

    assert [snapshot.battle.hp_pairs[0][0] for snapshot in snapshots] == [58, 58, 58, 31]


def test_bdsp_adapter_holds_logical_ko_when_presentation_is_unavailable() -> None:
    party = _party_read(
        _party_pokemon(1, 353, hp=58, max_hp=58, level=25, nickname="Shuppet"),
    )
    battle_samples = iter((
        _battle_read(BDSPBattlePokemon(1, 0, 353, 12, 58, 25)),
        _battle_read(BDSPBattlePokemon(1, 0, 353, 0, 58, 25)),
    ))
    presentation_samples = iter((
        _presentation_read(hp=12, max_hp=58, poke_id=0),
        None,
    ))
    adapter = BDSPRealTimeAdapter(
        client_factory=_Client,
        party_reader_factory=lambda _client: SimpleNamespace(read=lambda: party),
        battle_reader_factory=lambda _client: SimpleNamespace(
            read=lambda: next(battle_samples),
        ),
        presentation_reader_factory=lambda _client: SimpleNamespace(
            read=lambda: next(presentation_samples),
        ),
    )

    before = adapter.capture_monitor(_current(), save_path=None).battle.health_game
    held = adapter.capture_monitor(_current(), save_path=None).battle.health_game

    assert before is not None and held is not None
    assert held.party[0].current_hp == 12
    assert detect_fainted_transitions(before, held) == ()


def test_bdsp_adapter_does_not_accept_a_hidden_status_window_as_visible_proof() -> None:
    party = _party_read(
        _party_pokemon(1, 353, hp=58, max_hp=58, level=25, nickname="Shuppet"),
    )
    battle_samples = iter((
        _battle_read(BDSPBattlePokemon(1, 0, 353, 12, 58, 25)),
        _battle_read(BDSPBattlePokemon(1, 0, 353, 0, 58, 25)),
        _battle_read(BDSPBattlePokemon(1, 0, 353, 0, 58, 25)),
    ))
    presentation_samples = iter((
        _presentation_read(hp=12, max_hp=58, poke_id=0),
        _presentation_read(
            hp=0, max_hp=58, poke_id=0, animation=True, displayed=False,
        ),
        _presentation_read(hp=0, max_hp=58, poke_id=0, displayed=False),
    ))
    adapter = BDSPRealTimeAdapter(
        client_factory=_Client,
        party_reader_factory=lambda _client: SimpleNamespace(read=lambda: party),
        battle_reader_factory=lambda _client: SimpleNamespace(
            read=lambda: next(battle_samples),
        ),
        presentation_reader_factory=lambda _client: SimpleNamespace(
            read=lambda: next(presentation_samples),
        ),
    )

    snapshots = [
        adapter.capture_monitor(_current(), save_path=None)
        for _index in range(3)
    ]

    assert [snapshot.battle.hp_pairs[0][0] for snapshot in snapshots] == [12, 12, 12]


def test_bdsp_adapter_initial_zero_is_a_baseline_not_a_retrospective_death() -> None:
    party = _party_read(
        _party_pokemon(1, 300, hp=0, max_hp=21, level=12, nickname="Skitty"),
    )
    battle = _battle_read(BDSPBattlePokemon(1, 0, 300, 0, 21, 12))
    adapter, _client = _adapter(party, SimpleNamespace(read=lambda: battle))

    initial = adapter.capture_full(_current(), save_path=None).battle.health_game

    assert initial is not None
    assert detect_fainted_transitions(initial, initial) == ()


def test_bdsp_adapter_rejects_battle_identity_mismatch_without_losing_party() -> None:
    party = _party_read(
        _party_pokemon(1, 300, hp=21, max_hp=21, level=12, nickname="Skitty"),
    )
    wrong = _battle_read(BDSPBattlePokemon(1, 0, 353, 0, 21, 12))
    adapter, _client = _adapter(party, SimpleNamespace(read=lambda: wrong))

    snapshot = adapter.capture_monitor(_current(), save_path=None)

    assert snapshot.game.party[0].species_id == 300
    assert snapshot.battle.state == "unknown"
    assert snapshot.battle.health_game is None
    assert snapshot.diagnostic("battle").level is DiagnosticLevel.WARNING
    assert "no coincide" in snapshot.diagnostic("battle").message


def test_bdsp_adapter_battle_failure_is_an_optional_lane() -> None:
    party = _party_read(
        _party_pokemon(1, 300, hp=21, max_hp=21, level=12, nickname="Skitty"),
    )

    def fail() -> None:
        raise RuntimeError("BattleProc transitorio")

    adapter, client = _adapter(party, SimpleNamespace(read=fail))
    snapshot = adapter.capture_monitor(_current(), save_path=None)

    assert snapshot.game.party[0].current_hp == 21
    assert snapshot.battle.state == "unknown"
    assert client.close_calls == 0


def test_bdsp_adapter_reuses_connection_and_reset_closes_it() -> None:
    party = _party_read(
        _party_pokemon(1, 300, hp=21, max_hp=21, level=12, nickname="Skitty"),
    )
    adapter, client = _adapter(party, SimpleNamespace(read=lambda: None))

    first = adapter.capture_full(_current(), save_path=None)
    second = adapter.capture_monitor(_current(), save_path=None)
    adapter.reset_runtime_state()

    assert first.battle.state == second.battle.state == "none"
    assert client.connect_calls == 1
    assert client.close_calls == 1


def test_bdsp_adapter_auxiliary_memory_is_double_read_and_reports_party_writer() -> None:
    party = _party_read(
        _party_pokemon(1, 300, hp=21, max_hp=21, level=12, nickname="Skitty"),
    )
    adapter, _client = _adapter(party, SimpleNamespace(read=lambda: None))

    snapshot = adapter.capture_monitor(
        _current(), save_path=None, memory_requests=((0x1234, 4),),
    )

    assert [(block.address, block.data) for block in snapshot.memory_blocks] == [
        (0x1234, b"4444"),
    ]
    assert adapter.runtime_state()["writes_enabled"] is True


def test_bdsp_adapter_publishes_full_read_only_pc_matrix_with_role_and_anchor_level(
    tmp_path,
) -> None:
    boxed = BDSPBoxPokemon(
        box=3, slot=7, species_id=353, pid=0xA001, tid=123, sid=456,
        form=0, nickname="Shuppet", held_item_id=0, ability_id=15,
        move_ids=(1, 45, 0, 0), move_pp=(35, 40, 0, 0),
        move_pp_ups=(0, 1, 0, 0), is_egg=False,
        markings=(False, True, False, False, False, False),
        checksum=0x1234, encrypted=b"",
    )
    raw = BDSPBoxRead(
        pokemon=(boxed,), total_slots=1200, empty_slots=1199,
        pointer_base=0x440000,
    )
    anchor = SavePokemon(
        slot=1, species_id=353, species="Shuppet", nickname="Shuppet", level=25,
        held_item="Ninguno", ability="Insomnio", moves=["Destructor"],
        move_ids=[1], is_egg=False, markings=[False, True, False, False, False, False],
        role="Asesino", role_symbol="", pid=0xA001, tid=123, sid=456,
    )
    trace = tmp_path / "pc.jsonl"
    adapter = BDSPRealTimeAdapter(
        client_factory=_Client,
        box_reader_factory=lambda _client: SimpleNamespace(read=lambda: raw),
        trace_path=trace,
    )

    process, base, slots = adapter.read_pc(
        [anchor], box_count=40, box_slot_count=30,
    )

    assert process.pid == 90210
    assert base == 0x440000
    live = slots[(3, 7)]
    assert (live.species_id, live.pid, live.tid, live.sid) == (353, 0xA001, 123, 456)
    assert live.level == 25
    assert live.role == "Asesino"
    assert live.move_ids == [1, 45, 0, 0]
    row = json.loads(trace.read_text(encoding="utf-8").splitlines()[0])
    assert row["event"] == "pc-read"
    assert row["occupied_slots"] == 1
    assert row["slots"][0]["box"] == 3
    assert row["slots"][0]["identity"]
    assert "40961" not in trace.read_text(encoding="utf-8")


def test_bdsp_pc_derives_level_and_stats_without_a_party_anchor() -> None:
    boxed = BDSPBoxPokemon(
        box=1, slot=8, species_id=397, pid=0xB001, tid=123, sid=456,
        form=0, nickname="Ornita", held_item_id=0, ability_id=26,
        move_ids=(33, 0, 0, 0), move_pp=(35, 0, 0, 0),
        move_pp_ups=(0, 0, 0, 0), is_egg=False,
        markings=(False,) * 6, checksum=0x1234, encrypted=b"",
        experience=1728, nature_id=0, stat_nature_id=0,
        ivs=(10, 11, 12, 13, 14, 15), evs=(0, 0, 0, 0, 0, 0),
    )
    raw = BDSPBoxRead(
        pokemon=(boxed,), total_slots=1200, empty_slots=1199,
        pointer_base=0x440000,
    )
    profile = SimpleNamespace(
        exp_growth=lambda species, form: 0,
        base_stats=lambda species, form: (55, 75, 50, 40, 40, 80),
    )
    adapter = BDSPRealTimeAdapter(
        client_factory=_Client,
        box_reader_factory=lambda _client: SimpleNamespace(read=lambda: raw),
        tm_profile_getter=lambda: profile,
    )

    _process, _base, slots = adapter.read_pc([])

    ornita = slots[(1, 8)]
    assert ornita.level == 12
    assert set(ornita.stats) == {
        "hp", "attack", "defense", "sp_attack", "sp_defense", "speed",
    }
    assert ornita.base_stats == {
        "hp": 55, "attack": 75, "defense": 50,
        "sp_attack": 40, "sp_defense": 40, "speed": 80,
    }
    assert all(int(value) > 0 for value in ornita.stats.values())


def test_bdsp_adapter_rejects_foreign_pc_dimensions_before_reading() -> None:
    called = False

    def read():
        nonlocal called
        called = True
        raise AssertionError("no debe leer una geometría ajena")

    adapter = BDSPRealTimeAdapter(
        client_factory=_Client,
        box_reader_factory=lambda _client: SimpleNamespace(read=read),
    )

    with pytest.raises(ValueError, match="40 cajas"):
        adapter.read_pc([], box_count=32, box_slot_count=30)
    assert called is False


def test_bdsp_adapter_publishes_live_inventory_instead_of_stale_save(tmp_path) -> None:
    raw = BDSPInventoryRead(
        items=(
            BDSPInventoryItem(22, 9, False, False, False, 4),
            BDSPInventoryItem(337, 2, True, False, False, 3),
        ),
        total_records=3000,
        array_object=0x550000,
        data_pointer=0x550020,
    )
    trace = tmp_path / "inventory.jsonl"
    adapter = BDSPRealTimeAdapter(
        client_factory=_Client,
        inventory_reader_factory=lambda _client: SimpleNamespace(read=lambda: raw),
        trace_path=trace,
    )

    inventory, process, pointer = adapter.read_tm_inventory({22: 10, 337: 2})

    assert inventory == {22: 9, 337: 2}
    assert process.pid == 90210
    assert pointer == 0x550020
    row = json.loads(trace.read_text(encoding="utf-8").splitlines()[0])
    assert row == {
        "version": row["version"],
        "timestamp": row["timestamp"],
        "event": "tm-inventory-read",
        "data_pointer": 0x550020,
        "total_records": 3000,
        "positive_records": 2,
        "saved_witness_records": 2,
        "differing_from_save": [22],
    }


def test_bdsp_adapter_trace_records_snapshot_and_ui_boundary(tmp_path) -> None:
    party = _party_read(
        _party_pokemon(1, 300, hp=21, max_hp=21, level=12, nickname="Skitty"),
    )
    client = _Client()
    trace = tmp_path / "bdsp-trace.jsonl"
    adapter = BDSPRealTimeAdapter(
        client_factory=lambda: client,
        party_reader_factory=lambda _client: SimpleNamespace(read=lambda: party),
        battle_reader_factory=lambda _client: SimpleNamespace(read=lambda: None),
        trace_path=trace,
    )

    adapter.capture_monitor(_current(), save_path=None, sequence=3)
    adapter.record_ui_event("save-watcher-reload", live_active=True)

    rows = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    assert [row["event"] for row in rows] == ["snapshot", "save-watcher-reload"]
    assert rows[0]["party"][0] == {
        "slot": 1, "species": 300, "hp": 21, "max_hp": 21,
    }
    assert rows[1]["live_active"] is True


def test_bdsp_adapter_trace_keeps_presentation_separate_from_logical_hp(tmp_path) -> None:
    party = _party_read(
        _party_pokemon(1, 353, hp=58, max_hp=58, level=25, nickname="Shuppet"),
    )
    battle = _battle_read(BDSPBattlePokemon(1, 0, 353, 0, 58, 25))
    presentation = BDSPBattlePresentationRead(
        windows=(BDSPBattlePresentationWindow(
            window_index=0,
            displayed=True,
            current_hp=12,
            max_hp=58,
            level=25,
            poke_id=0,
            is_player=True,
            needs_hp_apply=False,
            hp_animation=False,
            initialized=True,
            setup=True,
        ),),
        ui_instance=0x200000,
        status_array=0x210000,
    )
    trace = tmp_path / "presentation.jsonl"
    adapter = BDSPRealTimeAdapter(
        client_factory=_Client,
        party_reader_factory=lambda _client: SimpleNamespace(read=lambda: party),
        battle_reader_factory=lambda _client: SimpleNamespace(read=lambda: battle),
        presentation_reader_factory=lambda _client: SimpleNamespace(
            read=lambda: presentation,
        ),
        trace_path=trace,
    )

    snapshot = adapter.capture_monitor(_current(), save_path=None, sequence=4)

    row = json.loads(trace.read_text(encoding="utf-8").splitlines()[0])
    assert snapshot.battle.hp_pairs == ((0, 58),)
    assert row["battle_health"][0]["hp"] == 0
    assert row["battle_presentation"][0]["hp"] == 12
    assert row["battle_presentation"][0]["hp_animation"] is False
    assert snapshot.diagnostic("presentation").level is DiagnosticLevel.OK
