from __future__ import annotations

from types import SimpleNamespace

from app.config import DANGER
from app.ui import RoleRunManager


class DummyManager:
    _active_azahar_realtime_key = RoleRunManager._active_azahar_realtime_key
    _uses_instant_realtime_ui = RoleRunManager._uses_instant_realtime_ui
    _pending_changes_block_live_capture = RoleRunManager._pending_changes_block_live_capture

    def __init__(self, key: str, pending_count: int = 0) -> None:
        self.save_engine = SimpleNamespace(key=key)
        self.run = SimpleNamespace(pending_changes=[object() for _ in range(pending_count)])


def test_sm_uses_same_instant_header_model_as_oras_and_xy() -> None:
    assert DummyManager("oras")._uses_instant_realtime_ui() is True
    assert DummyManager("xy")._uses_instant_realtime_ui() is True
    assert DummyManager("sm")._uses_instant_realtime_ui() is True
    assert DummyManager("bdsp")._uses_instant_realtime_ui() is True


def test_sm_legacy_pending_changes_do_not_block_live_capture() -> None:
    manager = DummyManager("sm", pending_count=6)
    assert manager._pending_changes_block_live_capture() is False


def test_gen6_pending_changes_keep_existing_capture_barrier() -> None:
    assert DummyManager("oras", pending_count=1)._pending_changes_block_live_capture() is True
    assert DummyManager("xy", pending_count=1)._pending_changes_block_live_capture() is True
    assert DummyManager("xy", pending_count=0)._pending_changes_block_live_capture() is False


class DummyLabel:
    def __init__(self) -> None:
        self.config = {}

    def configure(self, **kwargs) -> None:
        self.config.update(kwargs)


class DummyTopStatusManager:
    _update_top_status = RoleRunManager._update_top_status
    _uses_instant_realtime_ui = RoleRunManager._uses_instant_realtime_ui

    def __init__(self, sync_status: str) -> None:
        self._shell_built = True
        self.top_status = DummyLabel()
        self.review_changes_button = None
        self.discard_changes_button = None
        self.save_changes_button = None
        self.run = SimpleNamespace(pending_changes=[])
        self._oras_live_review_batches = []
        self._live_write_in_progress = False
        self._pending_ds_install = None
        self.save_engine = SimpleNamespace(key="sm")
        self.project = SimpleNamespace(name="Timper")
        self.current_game = SimpleNamespace(raw={})
        self.sync_status = sync_status

    @staticmethod
    def _widget_alive(widget) -> bool:
        return widget is not None


def test_sm_sync_error_is_not_painted_as_success_green() -> None:
    manager = DummyTopStatusManager("⚠ Sol/Luna · No se pudo demostrar la dirección viva")
    manager._update_top_status()
    assert manager.top_status.config["text_color"] == DANGER


def test_sm_live_gate_allows_roles_moves_and_inventory_in_alpha14() -> None:
    from app.models import PendingChange, PendingInventoryChange, PendingRoleChange

    class Gate:
        _oras_live_unsupported_changes = RoleRunManager._oras_live_unsupported_changes

        @staticmethod
        def _active_azahar_realtime_key() -> str:
            return "sm"

    gate = Gate()
    role = PendingRoleChange(
        pokemon_slot=1, pokemon="Rowlet", species="Rowlet",
        old_role="SIN ROL", new_role="Líbero", pokemon_identity="722:1:2:3",
    )
    move = PendingChange(
        role="Líbero", pokemon_slot=1, pokemon="Rowlet", species="Rowlet",
        move_slot=1, old_move="Placaje", old_move_id=33,
        new_move="Gruñido", new_move_id=45, pokemon_identity="722:1:2:3",
    )
    assert gate._oras_live_unsupported_changes([role]) == []
    assert gate._oras_live_unsupported_changes([move]) == []
    inventory = PendingInventoryChange("rare-candy", "Caramelo Raro", 999)
    assert gate._oras_live_unsupported_changes([inventory]) == []


def test_sm_alpha18_auto_apply_queues_moves_inventory_and_tm() -> None:
    from app.models import PendingChange, PendingInventoryChange, PendingTMTeach

    move = PendingChange(
        role="Líbero", pokemon_slot=1, pokemon="Rowlet", species="Rowlet",
        move_slot=1, old_move="Placaje", old_move_id=33,
        new_move="Gruñido", new_move_id=45, pokemon_identity="722:1:2:3",
    )
    inventory = PendingInventoryChange("max-repel", "Repelente Máximo", 999)
    tm = PendingTMTeach(
        role="Líbero", pokemon_slot=1, pokemon="Rowlet", species="Rowlet",
        move_slot=1, old_move="Placaje", old_move_id=33,
        new_move="Gruñido", new_move_id=45, pokemon_identity="722:1:2:3",
        item_id=328, tm_number=1, item_name="MT01", quantity_before=1,
    )

    class QueueManager:
        _request_oras_live_auto_apply = RoleRunManager._request_oras_live_auto_apply

        def __init__(self) -> None:
            self.run = SimpleNamespace(pending_changes=[move, inventory, tm])
            self._oras_live_auto_apply_ids = set()
            self.scheduled = 0

        @staticmethod
        def _oras_live_auto_apply_available() -> bool:
            return True

        @staticmethod
        def _active_azahar_realtime_key() -> str:
            return "sm"

        def _schedule_oras_live_auto_apply(self) -> None:
            self.scheduled += 1

    manager = QueueManager()
    manager._request_oras_live_auto_apply([move, inventory, tm])
    assert manager._oras_live_auto_apply_ids == {id(move), id(inventory), id(tm)}
    assert manager.scheduled == 1
