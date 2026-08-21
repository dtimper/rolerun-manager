from __future__ import annotations

import sys
import types

try:
    import customtkinter  # noqa: F401
except ModuleNotFoundError:
    customtkinter = types.ModuleType("customtkinter")
    customtkinter.CTk = object
    sys.modules["customtkinter"] = customtkinter

import app.ui as ui
from app.ui import RoleRunManager


def test_alpha52_foreground_retry_does_nothing_when_main_is_already_foreground(monkeypatch) -> None:
    calls: list[str] = []
    manager = types.SimpleNamespace(
        state=lambda: "zoomed",
        _foreground_belongs_to_this_process=lambda: True,
        _force_native_main_foreground=lambda: calls.append("force"),
    )
    monkeypatch.setattr(ui.os, "name", "nt")

    RoleRunManager._retry_native_main_foreground(manager)

    assert calls == []


def test_alpha52_foreground_retry_forces_activation_when_emulator_is_still_foreground(monkeypatch) -> None:
    calls: list[str] = []
    manager = types.SimpleNamespace(
        state=lambda: "zoomed",
        _foreground_belongs_to_this_process=lambda: False,
        _force_native_main_foreground=lambda: calls.append("force"),
    )
    monkeypatch.setattr(ui.os, "name", "nt")

    RoleRunManager._retry_native_main_foreground(manager)

    assert calls == ["force"]


class _RestoreHarness:
    def __init__(self) -> None:
        self.calls: list[object] = []
        self._floating_suspended_modal = None

    def _set_auto_floating_guard_temporarily(self, milliseconds: int = 320) -> None:
        self.calls.append(("guard", milliseconds))

    def deiconify(self) -> None:
        self.calls.append("deiconify")

    def _force_native_main_maximize(self) -> bool:
        self.calls.append("maximize")
        return True

    def state(self, *args):
        if args:
            self.calls.append(("state", args[0]))
            return None
        return "zoomed"

    def attributes(self, *args):
        self.calls.append(("attributes",) + args)
        return None

    def update_idletasks(self) -> None:
        self.calls.append("idletasks")

    def lift(self) -> None:
        self.calls.append("lift")

    def focus_force(self) -> None:
        self.calls.append("focus_force")

    def _force_native_main_foreground(self) -> bool:
        self.calls.append("foreground")
        return True

    def _retry_native_main_foreground(self) -> None:
        self.calls.append("retry")

    def after(self, delay: int, callback) -> str:
        self.calls.append(("after", delay, callback))
        return f"after-{delay}"


def test_alpha52_restore_from_floating_requests_foreground_and_two_bounded_retries(monkeypatch) -> None:
    manager = _RestoreHarness()
    monkeypatch.setattr(ui.os, "name", "nt")

    RoleRunManager._restore_main_window_maximized(manager, settle_before_show=False)

    assert "foreground" in manager.calls
    delays = [entry[1] for entry in manager.calls if isinstance(entry, tuple) and entry[0] == "after"]
    assert delays == [60, 180]
    assert manager.calls.index("foreground") > manager.calls.index("lift")
