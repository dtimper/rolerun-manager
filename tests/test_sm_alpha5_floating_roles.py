from __future__ import annotations

from types import SimpleNamespace

from app.ui import RoleRunManager


class FakeScheduler:
    def __init__(self) -> None:
        self.callbacks = []

    def winfo_exists(self) -> bool:
        return True

    def after_idle(self, callback) -> None:
        self.callbacks.append(callback)


class FloatingReleaseManager:
    _end_role_drag = RoleRunManager._end_role_drag

    def __init__(self) -> None:
        self._role_drag_source_identity = "mon-a"
        self._role_drag_source_role = "Líbero"
        self._role_drag_context = "floating"
        self._role_drag_origin = (10, 10)
        self._role_drag_moved = True
        self._role_drag_started = True
        self._role_drag_container = object()
        self._floating_role_drag_consumed = True
        self.floating_bar = FakeScheduler()
        self.moves = []

    def _drop_target_role_at(self, _x, _y, _context):
        return "Asesino"

    def _destroy_role_drag_visuals(self) -> None:
        pass

    def _find_projected_pokemon_by_identity(self, identity):
        return SimpleNamespace(identity=identity)

    def _move_pokemon_to_role_by_drag(self, source, target_role, context="main") -> None:
        self.moves.append((source.identity, target_role, context))

    def after(self, _delay, callback):
        # El reset del flag no participa en la escritura; puede ejecutarse ya.
        callback()
        return "after-id"


def test_floating_role_drop_is_completed_after_buttonrelease_not_inside_event() -> None:
    manager = FloatingReleaseManager()
    event = SimpleNamespace(x_root=100, y_root=50)
    result = manager._end_role_drag(event)
    assert result == "break"
    # La mutación todavía no ocurrió dentro del handler ButtonRelease.
    assert manager.moves == []
    assert len(manager.floating_bar.callbacks) == 1
    manager.floating_bar.callbacks[0]()
    assert manager.moves == [("mon-a", "Asesino", "floating")]
