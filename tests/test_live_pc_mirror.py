from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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
    return SaveGameData("AS", "SAV6AO", 6, "Timper", list(party), {})


class _ImmediateThread:
    def __init__(self, *, target, **_kwargs):
        self.target = target

    def start(self) -> None:
        self.target()


def _pc(*pokemon: SavePokemon) -> SavePCData:
    boxes = [SaveBox(index, f"Caja {index}", []) for index in range(1, 5)]
    for p in pokemon:
        assert p.box is not None and p.box_slot is not None
        boxes[int(p.box) - 1].pokemon.append(p)
    return SavePCData(
        game="AS", box_count=4, box_slot_count=30, current_box=2,
        boxes=boxes, next_open_box=1, next_open_box_slot=1, open_slots=[], raw={},
    )


def _manager(tmp_path: Path, pc: SavePCData, live_slots: dict[tuple[int, int], SavePokemon | None]):
    save = tmp_path / "main"
    save.write_bytes(b"save")
    signature = RoleRunManager._save_file_signature(save)
    manager = SimpleNamespace(
        project=SimpleNamespace(slug="run"), current_save=SimpleNamespace(path=save),
        _session_generation=1, _oras_pc_reconcile_last_key=None,
        _oras_pc_reconcile_in_progress=False, _oras_pc_reconcile_token=0,
        _pc_cache=pc, _pc_cache_signature=signature,
        _oras_live_pc_overrides={}, _oras_live_pc_empty_overrides=set(),
        _pokemon_identity=lambda p: "" if p is None else f"{p.species_id}:{p.pid}",
        _pending_team_changes=lambda: [],
        _project_pc_box_pokemon=lambda data, box, solo_confirmado=False: RoleRunManager._project_pc_box_pokemon(manager, data, box, solo_confirmado=solo_confirmado),
        _save_file_signature=RoleRunManager._save_file_signature,
        _floating_bar_is_visible=lambda: False,
        _main_ui_dirty_while_floating=False, active_page="team",
        _smooth_render_page=lambda **kwargs: None,
        save_engine=SimpleNamespace(read_boxes=lambda _path: pc),
        oras_live_reader=SimpleNamespace(read_pc=lambda _anchors: (SimpleNamespace(), 0x1234, live_slots)),
        after=lambda _delay, callback: callback(),
    )
    return manager


def _run_reconcile(manager, before, after) -> None:
    with patch("app.ui.threading.Thread", _ImmediateThread):
        RoleRunManager._schedule_oras_external_pc_reconcile(manager, before, after)


def test_game_side_move_swap_mirrors_outgoing_into_incoming_slot(tmp_path: Path) -> None:
    staraptor = mon(1, 398, pid=100, role="Líbero")
    hitmontop_boxed = mon(7, 237, pid=200, box=2, box_slot=7)
    pc = _pc(hitmontop_boxed)
    live_staraptor = mon(7, 398, pid=100, box=2, box_slot=7, role="Líbero")
    manager = _manager(tmp_path, pc, {(2, 7): live_staraptor})

    _run_reconcile(manager, game(staraptor), game(mon(1, 237, pid=200, role="Líbero")))

    mirrored = manager._oras_live_pc_overrides[(2, 7)]
    assert mirrored.species_id == 398
    assert mirrored.pid == 100
    assert mirrored.box == 2 and mirrored.box_slot == 7
    assert (2, 7) not in manager._oras_live_pc_empty_overrides


def test_game_side_withdraw_marks_source_pc_slot_empty(tmp_path: Path) -> None:
    anchor = mon(1, 248, pid=300, box=1, box_slot=1)
    hitmontop_boxed = mon(7, 237, pid=200, box=2, box_slot=7)
    pc = _pc(anchor, hitmontop_boxed)
    # En la lectura viva Hitmontop ya salió de 2:7; el anchor sigue en su sitio.
    manager = _manager(tmp_path, pc, {(1, 1): anchor, (2, 7): None})
    existing = mon(1, 398, pid=100, role="Líbero")
    incoming = mon(2, 237, pid=200, role="Tanque")

    _run_reconcile(manager, game(existing), game(existing, incoming))

    assert (2, 7) in manager._oras_live_pc_empty_overrides
    assert (2, 7) not in manager._oras_live_pc_overrides


def test_game_side_deposit_places_outgoing_in_actual_live_pc_slot(tmp_path: Path) -> None:
    # Este es el caso que alpha.29 no podía inferir: al usar "Dejar Pokémon" solo
    # sabemos quién salió de la party, no en qué casilla de caja lo dejó ORAS.
    anchor = mon(1, 248, pid=300, box=1, box_slot=1)
    pc = _pc(anchor)
    deposited_live = mon(8, 398, pid=100, box=2, box_slot=8, role="Líbero")
    manager = _manager(tmp_path, pc, {(1, 1): anchor, (2, 8): deposited_live})
    staraptor = mon(1, 398, pid=100, role="Líbero")
    survivor = mon(2, 609, pid=400, role="Mago")

    _run_reconcile(manager, game(staraptor, survivor), game(mon(1, 609, pid=400, role="Mago")))

    mirrored = manager._oras_live_pc_overrides[(2, 8)]
    assert mirrored.species_id == 398 and mirrored.pid == 100
    assert mirrored.level == 50  # conservado desde la party viva conocida
    assert mirrored.box == 2 and mirrored.box_slot == 8
    assert (2, 8) not in manager._oras_live_pc_empty_overrides
