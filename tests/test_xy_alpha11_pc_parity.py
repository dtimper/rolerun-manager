from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:
    import customtkinter  # noqa: F401
except ModuleNotFoundError:
    customtkinter = types.ModuleType("customtkinter")
    customtkinter.CTk = object
    sys.modules["customtkinter"] = customtkinter

from app.save_engine_client import SaveBox, SaveGameData, SavePCData, SavePokemon
from app.ui import RoleRunManager


def mon(slot: int, species: int, *, pid: int, box=None, box_slot=None, role="SIN ROL") -> SavePokemon:
    return SavePokemon(
        slot=slot, species_id=species, species=f"Species {species}", nickname=f"Mon {species}",
        level=50, held_item="Ninguno", ability="Ability", moves=["A", "B", "C", "D"],
        move_ids=[1, 2, 3, 4], is_egg=False, markings=[False] * 6,
        role=role, role_symbol="", box=box, box_slot=box_slot,
        pid=pid, tid=1, sid=2, current_hp=100, max_hp=100,
    )


def game(*party: SavePokemon) -> SaveGameData:
    return SaveGameData("X", "SAV6XY", 6, "Timper", list(party), {})


def pc_data(*pokemon: SavePokemon) -> SavePCData:
    boxes = [SaveBox(index, f"Caja {index}", []) for index in range(1, 5)]
    occupied = set()
    for p in pokemon:
        assert p.box is not None and p.box_slot is not None
        boxes[int(p.box) - 1].pokemon.append(p)
        occupied.add((int(p.box), int(p.box_slot)))
    open_slots = [
        (box, slot)
        for box in range(1, 5)
        for slot in range(1, 31)
        if (box, slot) not in occupied
    ]
    next_open = open_slots[0] if open_slots else (None, None)
    return SavePCData(
        game="X", box_count=4, box_slot_count=30, current_box=1, boxes=boxes,
        next_open_box=next_open[0], next_open_box_slot=next_open[1],
        open_slots=open_slots, raw={},
    )


class _ImmediateThread:
    def __init__(self, *, target, **_kwargs):
        self.target = target

    def start(self) -> None:
        self.target()


def test_xy_force_pc_refresh_reads_live_matrix_without_party_change(tmp_path: Path) -> None:
    save = tmp_path / "main"
    save.write_bytes(b"save")
    boxed = mon(1, 25, pid=100, box=1, box_slot=1)
    pc = pc_data(boxed)
    live_boxed = mon(1, 133, pid=200, box=1, box_slot=1)
    current = game(mon(1, 6, pid=300, role="Mago"))
    calls = []
    manager = SimpleNamespace(
        project=SimpleNamespace(slug="run"), current_save=SimpleNamespace(path=save), current_game=current,
        _session_generation=1, _oras_pc_reconcile_last_key=None,
        _oras_pc_reconcile_in_progress=False, _oras_pc_reconcile_token=0,
        _pc_cache=pc, _pc_cache_signature=RoleRunManager._save_file_signature(save),
        _oras_live_pc_overrides={}, _oras_live_pc_empty_overrides=set(),
        _pokemon_identity=lambda p: "" if p is None else f"{p.species_id}:{p.pid}",
        _pending_team_changes=lambda: [],
        _project_pc_box_pokemon=lambda data, box: RoleRunManager._project_pc_box_pokemon(manager, data, box),
        _save_file_signature=RoleRunManager._save_file_signature,
        _floating_bar_is_visible=lambda: False,
        _main_ui_dirty_while_floating=False, active_page="team",
        _smooth_render_page=lambda **kwargs: None,
        _active_azahar_realtime_key=lambda: "xy",
        save_engine=SimpleNamespace(read_boxes=lambda _path: pc),
        realtime_core=SimpleNamespace(
            read_pc=lambda anchors: calls.append(tuple(anchors)) or (SimpleNamespace(), 0x1234, {(1, 1): live_boxed})
        ),
        after=lambda _delay, callback: callback(),
    )

    with patch("app.ui.threading.Thread", _ImmediateThread):
        RoleRunManager._schedule_oras_external_pc_reconcile(manager, current, current, force=True)

    assert calls, "La apertura forzada del PC debe consultar la matriz viva de X/Y."
    assert manager._oras_live_pc_overrides[(1, 1)].species_id == 133
    assert manager._oras_live_pc_overrides[(1, 1)].pid == 200


def test_xy_external_party_swap_uses_same_live_pc_reconciler(tmp_path: Path) -> None:
    save = tmp_path / "main"
    save.write_bytes(b"save")
    incoming_boxed = mon(7, 237, pid=200, box=2, box_slot=7)
    anchor = mon(1, 25, pid=400, box=1, box_slot=1)
    pc = pc_data(anchor, incoming_boxed)
    outgoing = mon(1, 398, pid=100, role="Líbero")
    incoming = mon(1, 237, pid=200, role="Líbero")
    live_outgoing = mon(7, 398, pid=100, box=2, box_slot=7, role="Líbero")
    manager = SimpleNamespace(
        project=SimpleNamespace(slug="run"), current_save=SimpleNamespace(path=save),
        _session_generation=1, _oras_pc_reconcile_last_key=None,
        _oras_pc_reconcile_in_progress=False, _oras_pc_reconcile_token=0,
        _pc_cache=pc, _pc_cache_signature=RoleRunManager._save_file_signature(save),
        _oras_live_pc_overrides={}, _oras_live_pc_empty_overrides=set(),
        _pokemon_identity=lambda p: "" if p is None else f"{p.species_id}:{p.pid}",
        _pending_team_changes=lambda: [],
        _project_pc_box_pokemon=lambda data, box: RoleRunManager._project_pc_box_pokemon(manager, data, box),
        _save_file_signature=RoleRunManager._save_file_signature,
        _floating_bar_is_visible=lambda: False,
        _main_ui_dirty_while_floating=False, active_page="team",
        _smooth_render_page=lambda **kwargs: None,
        _active_azahar_realtime_key=lambda: "xy",
        save_engine=SimpleNamespace(read_boxes=lambda _path: pc),
        realtime_core=SimpleNamespace(read_pc=lambda _anchors: (SimpleNamespace(), 0x1234, {
            (1, 1): anchor, (2, 7): live_outgoing,
        })),
        after=lambda _delay, callback: callback(),
    )

    with patch("app.ui.threading.Thread", _ImmediateThread):
        RoleRunManager._schedule_oras_external_pc_reconcile(manager, game(outgoing), game(incoming))

    mirrored = manager._oras_live_pc_overrides[(2, 7)]
    assert mirrored.species_id == 398 and mirrored.pid == 100


def test_live_empty_override_becomes_reusable_pc_destination() -> None:
    occupied = mon(1, 25, pid=100, box=1, box_slot=1)
    pc = pc_data(occupied)
    # Simula que el juego sacó el Pokémon de 1:1 después del último main.
    manager = SimpleNamespace(
        _oras_live_pc_empty_overrides={(1, 1)},
        _oras_live_pc_overrides={},
        _pending_team_changes=lambda: [],
    )
    manager._projected_pc_occupied_positions = (
        lambda data: RoleRunManager._projected_pc_occupied_positions(manager, data)
    )
    result = RoleRunManager._projected_open_pc_slots(manager, pc)
    assert (1, 1) in result
    assert result[0] == (1, 1)


def test_navigate_to_pc_schedules_one_live_refresh() -> None:
    calls = []
    manager = SimpleNamespace(
        active_page="team",
        _cancel_help_animations=lambda: None,
        _smooth_render_page=lambda **kwargs: calls.append(("render", kwargs)),
        _schedule_gen6_live_pc_refresh=lambda: calls.append(("refresh", None)),
        after=lambda delay, callback: calls.append(("after", delay)) or callback(),
    )
    RoleRunManager.navigate(manager, "pc")
    assert manager.active_page == "pc"
    assert ("after", 90) in calls
    assert ("refresh", None) in calls

    calls.clear()
    RoleRunManager.navigate(manager, "pc")
    assert not any(kind == "refresh" for kind, _value in calls)
