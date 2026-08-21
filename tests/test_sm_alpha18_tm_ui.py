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

from app.models import PendingTMTeach
from app.ui import RoleRunManager


class _AutoApplyHarness:
    _oras_live_auto_apply_available = RoleRunManager._oras_live_auto_apply_available
    _request_oras_live_auto_apply = RoleRunManager._request_oras_live_auto_apply

    def __init__(self, change: PendingTMTeach) -> None:
        self.project = SimpleNamespace(slug="test")
        self.current_save = SimpleNamespace(path="main")
        self.current_game = SimpleNamespace()
        self._oras_live_active = True
        self.save_engine = SimpleNamespace(key="sm")
        self.run = SimpleNamespace(pending_changes=[change])
        self._oras_live_auto_apply_ids: set[int] = set()
        self.scheduled = False

    @staticmethod
    def _active_azahar_realtime_key() -> str:
        return "sm"

    def _schedule_oras_live_auto_apply(self, delay_ms: int = 110) -> None:
        self.scheduled = True


def _tm_change() -> PendingTMTeach:
    return PendingTMTeach(
        role="Asesino",
        pokemon_slot=2,
        pokemon="Pikipek",
        species="Pikipek",
        move_slot=3,
        old_move="—",
        old_move_id=0,
        new_move="Avivar",
        new_move_id=526,
        pokemon_identity="731:123:45:67",
        item_id=344,
        tm_number=17,
        item_name="MT17",
        quantity_before=1,
    )


def test_alpha18_sm_tm_teach_enters_immediate_live_apply_queue() -> None:
    change = _tm_change()
    harness = _AutoApplyHarness(change)
    harness._request_oras_live_auto_apply([change])
    assert id(change) in harness._oras_live_auto_apply_ids
    assert harness.scheduled is True


class _BombCore:
    def read_tm_inventory(self, *_args, **_kwargs):
        raise AssertionError("La mochila viva no debe escanearse durante un render pasivo")


class _PassiveTMHarness:
    _tm_replacement_context = RoleRunManager._tm_replacement_context

    def __init__(self) -> None:
        self.save_engine = SimpleNamespace(key="sm")
        self.current_save = SimpleNamespace(path="main")
        self._oras_live_active = True
        self.realtime_core = _BombCore()


def test_alpha18_sm_passive_team_context_never_scans_fcram() -> None:
    harness = _PassiveTMHarness()
    assert harness._tm_replacement_context() is None
