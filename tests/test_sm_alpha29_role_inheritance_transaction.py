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
