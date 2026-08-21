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

from app.models import PendingChange
from app.ui import RoleRunManager


def _move_change(move_id: int = 94) -> PendingChange:
    return PendingChange(
        role="Mago", pokemon_slot=1, pokemon="Velado", species="Chandelure",
        move_slot=4, old_move="Respiro", old_move_id=355,
        new_move="Psíquico", new_move_id=move_id, pokemon_identity="pk-1",
    )


def test_failed_automatic_write_discards_only_failed_projection_and_restarts_monitor() -> None:
    failed = _move_change()
    unrelated = _move_change(95)
    calls: list[tuple[str, object]] = []
    manager = SimpleNamespace(
        _live_write_in_progress=True, _session_generation=1,
        _oras_live_system_role_assignment_ids=set(),
        _oras_live_death_replacement_ids=set(),
        _oras_live_undo_inverse_ids=set(),
        _oras_live_undo_batch=None,
        project=SimpleNamespace(slug="run"),
        current_game=object(),
        run=SimpleNamespace(pending_changes=[unrelated, failed]),
        _oras_live_auto_apply_ids={id(failed)},
        current_results=[1], selected_pokemon=object(), _pc_cache=object(), _pc_cache_signature=object(),
        _floating_bar_last_signature=object(), floating_bar=None, _oras_live_active=True,
        _stop_oras_live_auto_apply_for=lambda changes: calls.append(("stop", tuple(changes))),
        _refresh_main_after_oras_live_write=lambda: calls.append(("refresh", None)),
        _update_top_status=lambda: None,
        _show_live_sync_toast=lambda *args: calls.append(("toast", args)),
        _schedule_oras_live_reconciliation=lambda delay=0: calls.append(("reconcile", delay)),
    )

    RoleRunManager._finish_oras_live_write(
        manager, 1, "run", [failed], None, "fallo de prueba", True,
    )

    assert manager.run.pending_changes == [unrelated]
    assert id(failed) not in manager._oras_live_auto_apply_ids
    assert ("reconcile", 220) in calls
    assert manager.current_results == []
    assert manager.selected_pokemon is None


def test_auto_apply_accepts_requested_subset_even_with_unrelated_pending_change() -> None:
    unrelated = _move_change(95)
    requested = _move_change(94)
    calls: list[object] = []
    manager = SimpleNamespace(
        _oras_live_auto_apply_after_id="timer",
        _session_generation=3,
        project=SimpleNamespace(slug="run"),
        run=SimpleNamespace(pending_changes=[unrelated, requested], role_rules_activation_pending=False),
        _oras_live_auto_apply_ids={id(requested)},
        _live_write_in_progress=False, _live_sync_in_progress=False, _oras_live_monitor_in_progress=False,
        _oras_live_auto_apply_available=lambda: True,
        _role_rules_are_active=lambda: True,
        _projected_party=lambda: [],
        _team_role_conflicts=lambda _party: False,
        _save_oras_live_changes=lambda changes, automatic=False: calls.append((list(changes), automatic)),
        _stop_oras_live_auto_apply_for=lambda _changes: None,
        _schedule_oras_live_auto_apply=lambda _delay=0: None,
    )

    RoleRunManager._flush_oras_live_auto_apply(manager, 3, "run")

    assert calls == [([requested], True)]
