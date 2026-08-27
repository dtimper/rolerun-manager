from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models import PendingTeamChange
from app.oras_tm_service import ORASPersonalStats
from app.realtime.sm_adapter import SMRealTimeAdapter
from app.save_engine_client import SaveGameData, SavePokemon
from app.sm_live import (
    PK7_STORED_SIZE,
    SM_PARTY_STATS_OFFSET,
    SM_PARTY_STATS_SIZE,
    SM_PARTY_STRIDE,
    SMLiveError,
    SMLiveReader,
    SMLiveWriter,
)
from app.ui import RoleRunManager


def _mon(species: int, pid: int, role: str = "Líbero") -> SavePokemon:
    return SavePokemon(
        slot=1,
        species_id=species,
        species=f"S{species}",
        nickname=f"M{species}",
        level=10,
        held_item="Ninguno",
        ability="A",
        moves=[],
        move_ids=[],
        is_egg=False,
        markings=[False] * 6,
        role=role,
        role_symbol="",
        pid=pid,
        tid=11,
        sid=22,
    )


def _game(mon: SavePokemon) -> SaveGameData:
    return SaveGameData("Pokémon Sol", "SAV7SM", 7, "Timper", [mon], {})


def _raw(game: SaveGameData, runtime: bytes):
    return SimpleNamespace(
        game=game,
        process=SimpleNamespace(
            process_id=17320,
            title_id=0x0004000000164800,
            name="niji_loc",
        ),
        attempts=1,
        party_base=0x34195E10,
        memory_blocks=(),
        runtime_party_region=runtime,
    )


def test_alpha31_real_game_party_transition_records_full_runtime_slot(tmp_path: Path, monkeypatch) -> None:
    import app.realtime.sm_adapter as module

    monkeypatch.setattr(module, "LOG_DIR", tmp_path)
    adapter = SMRealTimeAdapter(SMLiveReader(Path("missing.json"), stable_delay=0))

    size = 6 * SM_PARTY_STRIDE
    before = bytearray(size)
    after = bytearray(before)
    # Un byte en cada zona del slot 1. El diagnóstico debe conservarlos todos,
    # no solo el stored+stats que alpha.30 escribía y releía circularmente.
    offsets = (
        0x08,
        PK7_STORED_SIZE + 3,
        SM_PARTY_STATS_OFFSET,
        SM_PARTY_STATS_OFFSET + SM_PARTY_STATS_SIZE + 5,
    )
    for index, offset in enumerate(offsets, start=1):
        after[offset] = 0x20 + index

    adapter._convert(_raw(_game(_mon(724, 0x11112222)), bytes(before)), sequence=1)
    adapter._convert(_raw(_game(_mon(165, 0x33334444)), bytes(after)), sequence=2)

    latest = tmp_path / "sm_party_runtime_transition_latest.json"
    assert latest.is_file()
    payload = json.loads(latest.read_text(encoding="utf-8"))
    assert payload["version"] == "0.2.6-alpha.61"
    assert payload["party_stride"] == SM_PARTY_STRIDE
    assert len(payload["changed_slots"]) == 1
    slot = payload["changed_slots"][0]
    assert slot["slot"] == 1
    assert slot["before"]["species_id"] == 724
    assert slot["after"]["species_id"] == 165
    assert slot["zone_diff_counts"] == {
        "stored": 1,
        "runtime_gap": 1,
        "stats": 1,
        "runtime_tail": 1,
    }
    assert slot["unknown_runtime_diff_offsets"] == [PK7_STORED_SIZE + 3, SM_PARTY_STATS_OFFSET + SM_PARTY_STATS_SIZE + 5]
    assert len(slot["before_runtime_hex"]) == SM_PARTY_STRIDE * 2
    assert len(slot["after_runtime_hex"]) == SM_PARTY_STRIDE * 2
    assert list(tmp_path.glob("sm-party-runtime-*.json"))


def test_alpha31_role_only_change_does_not_create_member_swap_diagnostic(tmp_path: Path, monkeypatch) -> None:
    import app.realtime.sm_adapter as module

    monkeypatch.setattr(module, "LOG_DIR", tmp_path)
    adapter = SMRealTimeAdapter(SMLiveReader(Path("missing.json"), stable_delay=0))
    runtime = bytes(6 * SM_PARTY_STRIDE)
    adapter._convert(_raw(_game(_mon(724, 0x11112222, "Líbero")), runtime), sequence=1)
    adapter._convert(_raw(_game(_mon(724, 0x11112222, "Mago")), runtime), sequence=2)
    assert not (tmp_path / "sm_party_runtime_transition_latest.json").exists()



def test_alpha33_adapter_advertises_live_pc_write_modes() -> None:
    adapter = SMRealTimeAdapter(SMLiveReader(Path("missing.json"), stable_delay=0))
    raw = _raw(_game(_mon(724, 0x11112222)), bytes(6 * SM_PARTY_STRIDE))
    snapshot = adapter._convert(raw, sequence=1)
    assert snapshot.metadata["pc_write_live"] is True
    assert snapshot.metadata["pc_write_modes"] == ("swap-party-box", "party-to-box", "box-to-party")
    assert snapshot.metadata["pc_swap_diagnostic"] is False


def test_sm_adapter_publishes_effective_rom_base_stats_in_ui_order() -> None:
    personal = ORASPersonalStats((78, 107, 75, 70, 100, 100), 3)
    adapter = SMRealTimeAdapter(
        SMLiveReader(Path("missing.json"), stable_delay=0),
        personal_for=lambda species, form: personal if (species, form) == (724, 0) else None,
    )
    raw = _raw(_game(_mon(724, 0x11112222)), bytes(6 * SM_PARTY_STRIDE))

    snapshot = adapter._convert(raw, sequence=1)

    assert snapshot.game.party[0].base_stats == {
        "hp": 78, "attack": 107, "defense": 75,
        "sp_attack": 100, "sp_defense": 100, "speed": 70,
    }


def test_sm_inspector_reads_base_stats_from_the_effective_profile() -> None:
    personal = ORASPersonalStats((78, 107, 75, 70, 100, 100), 3)
    profile = SimpleNamespace(personal_for=lambda species, form: personal)
    manager = SimpleNamespace(
        save_engine=SimpleNamespace(key="sm"),
        _get_sm_rom_tm_profile=lambda prompt=False: profile,
    )
    pokemon = SimpleNamespace(species_id=724, form=0, base_stats={})

    assert RoleRunManager._team_pc_base_stats(manager, pokemon) == {
        "hp": 78, "attack": 107, "defense": 75,
        "sp_attack": 100, "sp_defense": 100, "speed": 70,
    }


def test_opening_configured_sm_preloads_personal_before_reading_the_save() -> None:
    calls: list[str] = []
    source = SimpleNamespace(is_available=True, save_path="main", start_new_run=False)
    manager = SimpleNamespace(
        _set_selected_game_engine=lambda key: calls.append(f"engine:{key}") or True,
        game_source_profiles=SimpleNamespace(get=lambda key: source),
        _configure_game_sources=lambda *args, **kwargs: calls.append("configure"),
        _get_sm_rom_tm_profile=lambda prompt=False: calls.append("profile"),
        select_save=lambda path, force_new_run=False: calls.append(f"save:{path}"),
    )

    RoleRunManager._open_configured_game(manager, "sm")

    assert calls == ["engine:sm", "profile", "save:main"]
