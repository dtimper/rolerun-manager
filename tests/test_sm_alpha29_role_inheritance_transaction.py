from __future__ import annotations

import sys
import types
from types import SimpleNamespace

try:
    import customtkinter  # noqa: F401
except ModuleNotFoundError:
    customtkinter = types.ModuleType("customtkinter")
    customtkinter.CTk = object
    sys.modules["customtkinter"] = customtkinter

from app.live_party_watch import infer_incoming_role_assignments
from app.models import PendingRoleChange
from app.save_engine_client import SaveGameData, SavePokemon
from app.ui import RoleRunManager


def mon(slot: int, species: int, pid: int, role: str) -> SavePokemon:
    return SavePokemon(
        slot=slot, species_id=species, species=f"S{species}", nickname=f"M{species}",
        level=10, held_item="Ninguno", ability="A", moves=[], move_ids=[],
        is_egg=False, markings=[False] * 6, role=role, role_symbol="",
        pid=pid, tid=1, sid=2,
    )


def game(*party: SavePokemon) -> SaveGameData:
    return SaveGameData("Pokémon Sol", "SAV7SM", 7, "Timper", list(party), {})


def identity(p: SavePokemon) -> str:
    return f"{p.species_id}:{p.pid}:{p.tid}:{p.sid}"


def test_in_game_pc_entry_to_libero_waits_for_explicit_ev_choice() -> None:
    outgoing = mon(1, 724, 10, "Líbero")
    incoming = mon(1, 165, 99, "SIN ROL")
    incoming.evs = {key: value for key, value in zip(
        ("hp", "attack", "defense", "sp_attack", "sp_defense", "speed"),
        (1, 2, 3, 4, 5, 6),
    )}
    before = game(outgoing)
    after = game(incoming)
    manager = SimpleNamespace(
        current_game=after,
        project=SimpleNamespace(slug="run"),
        _session_generation=7,
        _automatic_libero_ev_prompt_key=None,
        _active_azahar_realtime_key=lambda: "sm",
        _pokemon_identity=identity,
        _floating_bar_is_visible=lambda: True,
        _update_top_status=lambda: None,
        sync_status="",
    )
    manager._bdsp_role_evs = RoleRunManager._bdsp_role_evs
    changes = RoleRunManager._incoming_oras_role_changes(manager, before, after)
    assert len(changes) == 1
    assert changes[0].new_role == "Líbero"
    assert changes[0].new_evs is None

    prompts = []
    writes = []
    manager._prompt_libero_role = lambda pokemon, callback, *, context: prompts.append(
        (pokemon, callback, context)
    )
    manager._save_oras_live_changes = lambda batch, **kwargs: writes.append((list(batch), kwargs)) or True

    assert RoleRunManager._defer_automatic_libero_role_until_ev_choice(
        manager, changes, base_game=after,
    ) is True
    assert len(prompts) == 1
    assert prompts[0][2] == "floating"
    assert writes == []

    prompts[0][1](("hp", "attack"))
    assert len(writes) == 1
    written = writes[0][0][0]
    assert written.old_evs == (1, 2, 3, 4, 5, 6)
    assert written.new_evs == (252, 252, 0, 0, 0, 0)
    assert writes[0][1] == {"automatic": True, "base_game": after}


def test_in_game_pc_entry_to_fixed_role_carries_ev_normalization_without_prompt() -> None:
    outgoing = mon(1, 724, 10, "Asesino")
    incoming = mon(1, 165, 99, "SIN ROL")
    incoming.evs = {key: 4 for key in ("hp", "attack", "defense", "sp_attack", "sp_defense", "speed")}
    manager = SimpleNamespace(
        _active_azahar_realtime_key=lambda: "usum",
        _pokemon_identity=identity,
    )

    changes = RoleRunManager._incoming_oras_role_changes(manager, game(outgoing), game(incoming))

    assert len(changes) == 1
    assert changes[0].new_role == "Asesino"
    assert changes[0].old_evs == (4, 4, 4, 4, 4, 4)
    assert changes[0].new_evs == (0, 252, 0, 0, 0, 252)


def test_floating_refresh_preserves_open_libero_ev_selector() -> None:
    class Child:
        def __init__(self) -> None:
            self.destroyed = False

        def destroy(self) -> None:
            self.destroyed = True

    regular_widget = Child()
    libero_selector = Child()
    bar = SimpleNamespace(winfo_children=lambda: [regular_widget, libero_selector])
    manager = SimpleNamespace(_floating_modal_windows={libero_selector})

    RoleRunManager._clear_floating_bar_render_children(manager, bar)

    assert regular_widget.destroyed is True
    assert libero_selector.destroyed is False


def test_direct_pc_replacement_retains_outgoing_role_intent_until_pc_proof() -> None:
    before = game(
        mon(1, 724, 10, "Líbero"),
        mon(2, 731, 11, "Asesino"),
        mon(3, 731, 12, "Mago"),
        mon(4, 731, 13, "Tanque"),
        mon(5, 734, 14, "Prisma"),
        mon(6, 735, 15, "Support"),
    )
    ledyba = mon(1, 165, 99, "SIN ROL")
    after = game(
        ledyba,
        mon(2, 731, 11, "Asesino"),
        mon(3, 731, 12, "Mago"),
        mon(4, 731, 13, "Tanque"),
        mon(5, 734, 14, "Prisma"),
        mon(6, 735, 15, "Support"),
    )
    assignments = infer_incoming_role_assignments(
        before, after, ("Líbero", "Asesino", "Mago", "Tanque", "Prisma", "Support"),
    )
    assert len(assignments) == 1
    assert assignments[0].new_role == "Líbero"
    assert assignments[0].reason == "direct-replacement"

    change = PendingRoleChange(
        pokemon_slot=1, pokemon="Ledyba", species="Ledyba", old_role="SIN ROL",
        new_role="Líbero", pokemon_identity=identity(ledyba),
    )
    writes: list[list[PendingRoleChange]] = []
    manager = SimpleNamespace(
        current_game=after,
        _sm_pending_role_transition=None,
        _active_azahar_realtime_key=lambda: "sm",
        _pokemon_identity=identity,
        _oras_live_system_role_assignment_ids=set(),
        _save_oras_live_changes=lambda changes, **_kwargs: writes.append(list(changes)) or True,
        _update_top_status=lambda: None,
        _schedule_oras_live_reconciliation=lambda _delay: None,
        sync_status="",
    )
    manager._sm_role_transition_key = RoleRunManager._sm_role_transition_key.__get__(manager)
    manager._queue_sm_role_transition = RoleRunManager._queue_sm_role_transition.__get__(manager)
    manager._flush_sm_role_transition_after_pc_proof = RoleRunManager._flush_sm_role_transition_after_pc_proof.__get__(manager)

    assert manager._queue_sm_role_transition(after, [change]) is True
    assert writes == []  # nunca se escribe antes de la prueba PC
    assert manager._flush_sm_role_transition_after_pc_proof() is True
    assert len(writes) == 1
    assert writes[0][0].new_role == "Líbero"
    assert manager._sm_pending_role_transition is None


def test_stale_transition_is_discarded_instead_of_writing_wrong_role() -> None:
    incoming = mon(1, 165, 99, "SIN ROL")
    observed = game(incoming)
    changed_again = game(mon(1, 10, 100, "SIN ROL"))
    change = PendingRoleChange(
        pokemon_slot=1, pokemon="Ledyba", species="Ledyba", old_role="SIN ROL",
        new_role="Support", pokemon_identity=identity(incoming),
    )
    writes = []
    manager = SimpleNamespace(
        current_game=changed_again,
        _sm_pending_role_transition=None,
        _active_azahar_realtime_key=lambda: "sm",
        _pokemon_identity=identity,
        _oras_live_system_role_assignment_ids=set(),
        _save_oras_live_changes=lambda changes, **_kwargs: writes.append(list(changes)) or True,
        _update_top_status=lambda: None,
        _schedule_oras_live_reconciliation=lambda _delay: None,
        sync_status="",
    )
    manager._sm_role_transition_key = RoleRunManager._sm_role_transition_key.__get__(manager)
    manager._queue_sm_role_transition = RoleRunManager._queue_sm_role_transition.__get__(manager)
    manager._flush_sm_role_transition_after_pc_proof = RoleRunManager._flush_sm_role_transition_after_pc_proof.__get__(manager)

    manager._queue_sm_role_transition(observed, [change])
    assert manager._flush_sm_role_transition_after_pc_proof() is False
    assert writes == []
    assert manager._sm_pending_role_transition is None
