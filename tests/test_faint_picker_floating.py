from __future__ import annotations

from types import SimpleNamespace

from app.ui import RoleRunManager


class _FakeAfterManager:
    _cancel_pending_faint_picker_request = RoleRunManager._cancel_pending_faint_picker_request
    _next_unshown_pending_faint = RoleRunManager._next_unshown_pending_faint
    _next_ready_pending_faint = RoleRunManager._next_ready_pending_faint
    _schedule_pending_faint_picker = RoleRunManager._schedule_pending_faint_picker

    def __init__(self, *, shown: bool = False, battle_ended: bool = True) -> None:
        self.project = SimpleNamespace(
            pending_faints=[{
                "identity": "dead-1", "prompt_shown": shown,
                "battle_ended": battle_ended,
            }]
        )
        self._oras_faint_picker_after_id = None
        self.cancelled: list[str] = []
        self.scheduled: list[tuple[int, object]] = []

    def after(self, delay, callback):
        ident = f"after-{len(self.scheduled) + 1}"
        self.scheduled.append((delay, callback))
        return ident

    def after_cancel(self, ident):
        self.cancelled.append(ident)

    def _maybe_open_pending_faint_picker(self):
        raise AssertionError("the callback must not run synchronously")


def test_faint_picker_schedule_is_debounced_to_one_after() -> None:
    manager = _FakeAfterManager()
    manager._schedule_pending_faint_picker(500)
    first = manager._oras_faint_picker_after_id
    manager._schedule_pending_faint_picker(700)

    assert first == "after-1"
    assert manager.cancelled == ["after-1"]
    assert manager._oras_faint_picker_after_id == "after-2"
    assert [delay for delay, _ in manager.scheduled] == [500, 700]


def test_prompt_already_shown_is_never_scheduled_again() -> None:
    manager = _FakeAfterManager(shown=True)
    manager._schedule_pending_faint_picker(650)
    assert manager._oras_faint_picker_after_id is None
    assert manager.scheduled == []


def test_faint_never_blocks_auto_floating_in_alpha27() -> None:
    manager = SimpleNamespace()
    assert RoleRunManager._faint_picker_blocks_floating(manager) is False


def test_ready_faint_returns_from_floating_bar_before_opening_picker() -> None:
    calls: list[str] = []
    manager = SimpleNamespace(
        _oras_faint_picker_after_id="after-1",
        project=SimpleNamespace(pending_faints=[{
            "identity": "dead-1", "prompt_shown": False, "battle_ended": True,
        }]),
        current_game=object(),
        run=SimpleNamespace(pending_changes=[]),
        _live_write_in_progress=False,
        _live_sync_in_progress=False,
        _oras_live_monitor_in_progress=False,
        _auto_floating_guard=False,
        _body_swap_in_progress=False,
        _next_ready_pending_faint=lambda: {
            "identity": "dead-1", "prompt_shown": False, "battle_ended": True,
        },
        _floating_bar_is_visible=lambda: True,
        _floating_logo_to_dashboard=lambda: calls.append("return-from-floating"),
    )

    RoleRunManager._maybe_open_pending_faint_picker(manager)
    assert manager._oras_faint_picker_after_id is None
    assert calls == ["return-from-floating"]


def test_faint_is_not_scheduled_before_battle_end() -> None:
    manager = _FakeAfterManager(battle_ended=False)
    manager._schedule_pending_faint_picker(500)
    assert manager._oras_faint_picker_after_id is None
    assert manager.scheduled == []


def test_mapping_main_window_hides_a_still_visible_floating_bar_before_picker() -> None:
    calls: list[str] = []
    bar = SimpleNamespace(
        winfo_exists=lambda: True,
        state=lambda: "normal",
        withdraw=lambda: calls.append("bar-withdraw"),
    )
    manager = SimpleNamespace(
        floating_bar=bar,
        _floating_bar_is_visible=lambda: True,
        _floating_bar_poll_id="poll-1",
        _floating_role_reordered=True,
        _floating_suspended_modal=None,
        _main_ui_dirty_while_floating=False,
        _save_floating_bar_position=lambda: calls.append("save-pos"),
        after_cancel=lambda ident: calls.append(f"cancel:{ident}"),
        _set_auto_floating_guard_temporarily=lambda ms: calls.append(f"guard:{ms}"),
        _schedule_pending_faint_picker=lambda delay: calls.append(f"picker:{delay}"),
    )
    RoleRunManager._on_main_map(manager)
    assert calls[:4] == ["save-pos", "cancel:poll-1", "bar-withdraw", "guard:650"]
    assert manager._floating_bar_poll_id is None
    assert manager._floating_role_reordered is False
    assert calls[-1] == "picker:700"


def test_replace_fainted_is_eligible_for_oras_auto_apply() -> None:
    from app.models import PendingTeamChange

    change = PendingTeamChange(
        operation="replace-fainted", party_slot=1, box=2, box_slot=3,
        outgoing_pokemon="Chompo", incoming_pokemon="Golem",
    )
    scheduled: list[bool] = []
    manager = SimpleNamespace(
        run=SimpleNamespace(pending_changes=[change]),
        _oras_live_auto_apply_ids=set(),
        _oras_live_auto_apply_available=lambda: True,
        _schedule_oras_live_auto_apply=lambda: scheduled.append(True),
    )
    RoleRunManager._request_oras_live_auto_apply(manager, [change])
    assert id(change) in manager._oras_live_auto_apply_ids
    assert scheduled == [True]


def test_floating_bar_opening_guard_prevents_second_toplevel_creation() -> None:
    manager = SimpleNamespace(
        project=object(),
        current_game=object(),
        _floating_bar_opening=True,
        _suspend_modal_for_floating_bar=lambda: (_ for _ in ()).throw(
            AssertionError("a concurrent open must stop before touching any window")
        ),
    )
    RoleRunManager.open_floating_bar(manager)
