from types import SimpleNamespace

import pytest

from app.oras_live import ORASLiveError, calculate_pk6_stats
from app.oras_tm_service import ORASPersonalStats
from app.pokemon_stats import stat_dict
from app.realtime.oras_adapter import ORASRealTimeAdapter
from app.save_engine_client import SaveBox, SavePCData, SavePokemon
from app.ui import RoleRunManager


def _pokemon(*, boxed: bool) -> SavePokemon:
    return SavePokemon(
        slot=1,
        species_id=557,
        species="Dwebble",
        nickname="Dwebble",
        level=10,
        held_item="Ninguno",
        ability="Espíritu Vital",
        moves=["Patada Ígnea"],
        move_ids=[7],
        is_egg=False,
        markings=[],
        role="",
        role_symbol="",
        box=1 if boxed else None,
        box_slot=1 if boxed else None,
        nature_id=0,
        stat_nature_id=0,
        ivs=stat_dict((31, 31, 31, 31, 31, 31)),
        evs=stat_dict((0, 0, 0, 0, 0, 0)),
    )


def test_oras_pc_enrichment_publishes_base_and_calculated_stats() -> None:
    # Orden Personal Gen 6: PS, Atq., Def., Vel., At. Esp., Def. Esp.
    personal = ORASPersonalStats((50, 60, 70, 80, 90, 100), 0)
    adapter = ORASRealTimeAdapter.__new__(ORASRealTimeAdapter)
    adapter.writer = SimpleNamespace(personal_for=lambda species, form: personal)

    enriched = adapter._enrich_pokemon(_pokemon(boxed=True))

    assert enriched.base_stats == {
        "hp": 50, "attack": 60, "defense": 70,
        "sp_attack": 90, "sp_defense": 100, "speed": 80,
    }
    assert enriched.stats == {
        "hp": 33, "attack": 20, "defense": 22,
        "sp_attack": 26, "sp_defense": 28, "speed": 24,
    }


def test_oras_party_enrichment_publishes_effective_rom_base_stats() -> None:
    personal = ORASPersonalStats((50, 60, 70, 80, 90, 100), 0)
    adapter = ORASRealTimeAdapter.__new__(ORASRealTimeAdapter)
    adapter.writer = SimpleNamespace(personal_for=lambda species, form: personal)
    pokemon = _pokemon(boxed=False)
    pokemon.stats = stat_dict((31, 20, 22, 26, 28, 24))

    enriched = adapter._enrich_pokemon(pokemon)

    assert enriched.base_stats == {
        "hp": 50, "attack": 60, "defense": 70,
        "sp_attack": 90, "sp_defense": 100, "speed": 80,
    }
    assert enriched.stats == pokemon.stats


def test_oras_inspector_reads_base_stats_from_active_rom_profile() -> None:
    personal = ORASPersonalStats((50, 60, 70, 80, 90, 100), 0)
    profile = SimpleNamespace(personal_for=lambda species, form: personal)
    manager = SimpleNamespace(
        save_engine=SimpleNamespace(key="oras"),
        _get_oras_rom_tm_profile=lambda prompt=False: profile,
    )

    assert RoleRunManager._team_pc_base_stats(manager, _pokemon(boxed=False)) == {
        "hp": 50, "attack": 60, "defense": 70,
        "sp_attack": 90, "sp_defense": 100, "speed": 80,
    }


def test_oras_live_metadata_profile_is_prepared_before_capture() -> None:
    profile = object()
    calls: list[bool] = []
    manager = SimpleNamespace(
        save_engine=SimpleNamespace(key="oras"),
        _get_oras_rom_tm_profile=lambda prompt=False: (
            calls.append(prompt) or profile
        ),
    )

    result = RoleRunManager._prepare_oras_live_metadata_profile(manager)

    assert result is profile
    assert calls == [False]


def test_live_metadata_profile_does_not_load_for_other_backends() -> None:
    manager = SimpleNamespace(
        save_engine=SimpleNamespace(key="xy"),
        _get_oras_rom_tm_profile=lambda prompt=False: pytest.fail(
            "X/Y no debe cargar el Personal de ORAS"
        ),
    )

    assert RoleRunManager._prepare_oras_live_metadata_profile(manager) is None


def test_calculate_pk6_stats_rejects_incomplete_training_metadata() -> None:
    personal = ORASPersonalStats((50, 60, 70, 80, 90, 100), 0)

    with pytest.raises(ORASLiveError, match="IV/EV completos"):
        calculate_pk6_stats(
            level=10,
            nature_id=0,
            personal=personal,
            ivs={"hp": 31},
            evs=stat_dict((0, 0, 0, 0, 0, 0)),
        )


def test_oras_pc_reconcile_keeps_live_metadata_when_identity_did_not_move() -> None:
    stored = _pokemon(boxed=True)
    stored.stats = {}
    stored.base_stats = {}
    stored.ivs = {}
    stored.evs = {}
    live = _pokemon(boxed=True)
    live.stats = stat_dict((33, 20, 22, 26, 28, 24))
    live.base_stats = stat_dict((50, 60, 70, 90, 100, 80))
    base = SavePCData(
        game="ORAS", box_count=1, box_slot_count=30, current_box=1,
        boxes=[SaveBox(index=1, name="Caja 1", pokemon=[stored])],
        next_open_box=1, next_open_box_slot=2, open_slots=[], raw={},
    )
    manager = RoleRunManager.__new__(RoleRunManager)
    manager.project_service = SimpleNamespace(
        pokemon_identity_key=lambda species, pid, tid, sid, nickname="": (
            f"{species}:{pid}:{tid}:{sid}"
        ),
    )

    merged = manager._pc_data_with_live_presentation(base, {(1, 1): live})
    pokemon = merged.boxes[0].pokemon[0]

    assert pokemon.stats == live.stats
    assert pokemon.base_stats == live.base_stats
    assert pokemon.ivs == live.ivs
    assert pokemon.evs == live.evs
    assert base.boxes[0].pokemon[0].stats == {}
