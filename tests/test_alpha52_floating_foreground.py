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


def test_hacer_clic_en_el_emulador_durante_el_arranque_si_flota() -> None:
    """Hallazgo del usuario el 31-08-2026.

    Mientras BDSP/Sol-Luna validan los PS iniciales, la shell principal puede
    tardar en terminar de componerse (`_shell_built` sigue en False). Antes,
    ``_on_main_focus_out`` exigía la shell terminada para siquiera programar
    el auto-float, así que RoleRun se quedaba en primer plano ese rato entero
    aunque el usuario clicase en el emulador. ``_render_floating_bar`` no
    depende de la shell principal —solo de ``_projected_party``/``project``,
    ya disponibles antes—, así que no hacía falta esperar a eso.
    """
    programados: list[tuple[int, object]] = []
    manager = types.SimpleNamespace(
        _auto_floating_guard=False,
        _shell_built=False,  # la shell principal todavía no ha terminado
        current_game=object(),
        _faint_picker_blocks_floating=lambda: False,
        floating_bar=None,
        _focus_out_after_id=None,
        _auto_float_if_background=lambda: None,
        after=lambda ms, callback: programados.append((ms, callback)) or "id",
    )

    RoleRunManager._on_main_focus_out(manager)

    assert programados and programados[0][0] == 220


def test_el_auto_float_tampoco_exige_la_shell_terminada() -> None:
    llamadas: list[str] = []
    manager = types.SimpleNamespace(
        _auto_floating_guard=False,
        _shell_built=False,
        current_game=object(),
        _faint_picker_blocks_floating=lambda: False,
        _foreground_belongs_to_this_process=lambda: False,
        state=lambda: "normal",
        _foreground_is_supported_emulator=lambda: True,
        open_floating_bar=lambda: llamadas.append("flotar"),
    )

    RoleRunManager._auto_float_if_background(manager)

    assert llamadas == ["flotar"]
