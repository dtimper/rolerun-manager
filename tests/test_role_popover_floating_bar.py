"""El editor de rol (TransparentWindowSurface) se quedaba flotando -topmost,
por delante de TODO, emulador incluido- en cuanto RoleRun pasaba a la barra
flotante con el editor todavía abierto. Reportado por el usuario 09-09-2026,
con captura: "cuando no cierras la página y pulsas el emulador, por lo que
se pone automáticamente en barra flotante, [el editor] debería no aparecer".

Causa: `TransparentWindowSurface` usa dos `CTkToplevel` propios (velo +
contenido) que nunca toman un grab real de Tk -su `grab_set()` es un no-op-,
así que el mecanismo genérico ya existente (`_suspend_modal_for_floating_bar`,
basado en `grab_current()`) nunca lo encontraba. Se añadió un rastro aparte,
`self._active_transparent_popover`.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

from app.ui import RoleRunManager


class _FakePopover:
    def __init__(self) -> None:
        self._state = "normal"
        self.exists = True

    def winfo_exists(self) -> bool:
        return self.exists

    def state(self) -> str:
        return self._state

    def withdraw(self) -> None:
        self._state = "withdrawn"

    def deiconify(self) -> None:
        self._state = "normal"


def _manager(popover, *, main_state: str = "normal") -> SimpleNamespace:
    return SimpleNamespace(
        _active_transparent_popover=popover,
        _floating_suspended_modal=None,
        _floating_suspended_modal_had_grab=False,
        grab_current=lambda: None,
        floating_bar=None,
        state=lambda: main_state,
        _cancel_role_drag=lambda: None,
    )


def test_switching_to_floating_bar_withdraws_the_open_role_popover() -> None:
    popover = _FakePopover()
    manager = _manager(popover)

    RoleRunManager._suspend_modal_for_floating_bar(manager)

    assert popover.state() == "withdrawn"
    # A diferencia de `_floating_suspended_modal`, esto no se "consume": el
    # editor sigue siendo EL MISMO objeto mientras siga abierto.
    assert manager._active_transparent_popover is popover


def test_returning_to_rolerun_reopens_the_popover() -> None:
    popover = _FakePopover()
    popover.withdraw()
    manager = _manager(popover, main_state="normal")

    RoleRunManager._restore_suspended_modal_after_floating(manager)

    assert popover.state() == "normal"


def test_it_stays_hidden_while_rolerun_itself_is_still_hidden() -> None:
    """No reaparece por delante de una ventana principal que sigue minimizada
    -mismo criterio que ya usa el modal genérico un poco más abajo."""
    popover = _FakePopover()
    popover.withdraw()
    manager = _manager(popover, main_state="withdrawn")

    RoleRunManager._restore_suspended_modal_after_floating(manager)

    assert popover.state() == "withdrawn"


def test_a_destroyed_popover_is_left_alone_without_crashing() -> None:
    popover = _FakePopover()
    popover.exists = False
    manager = _manager(popover)

    RoleRunManager._suspend_modal_for_floating_bar(manager)
    RoleRunManager._restore_suspended_modal_after_floating(manager)

    assert popover.state() == "normal", "no se tocó -winfo_exists() era False"


def test_open_role_editor_tracks_and_untracks_the_popover() -> None:
    fuente = inspect.getsource(RoleRunManager.open_role_editor)
    assert "self._active_transparent_popover = window" in fuente
    assert "window.destroy = destroy_and_untrack" in fuente
    assert "self._active_transparent_popover = None" in fuente
