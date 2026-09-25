"""Los editores de rol (equipo y PC) no se podían recorrer con flechas ni
mando, solo con ratón. Pedido del usuario 09-09-2026, con captura: "debería
dejarte pasar de un rol a otro, seleccionarlo, etc."; misma tarde, pedido de
que CANCELAR/ACEPTAR ROL también se alcancen con flechas.

`_bind_role_grid_arrow_navigation` reutiliza el mismo motor de rejilla
lógica (`SpatialSelection`/`SpatialTarget`) que ya usan Equipo/PC,
Movimientos y Drafteos, para una rejilla fija de 4 columnas más una fila
final de dos acciones (CANCELAR, ACEPTAR ROL).
"""

from __future__ import annotations

from types import SimpleNamespace

from app.ui import RoleRunManager


class _FakeToplevel:
    def __init__(self) -> None:
        self.bindings: dict[str, object] = {}

    def bind(self, sequence, callback, add="+"):
        self.bindings[sequence] = callback


class _FakeButton:
    """Un `CTkButton` de mentira: solo lo que `configurar_si_cambia` toca."""

    def __init__(self, border_color: str, border_width: int) -> None:
        self._options = {"border_color": border_color, "border_width": border_width}

    def cget(self, option: str):
        return self._options[option]

    def configure(self, **options) -> None:
        self._options.update(options)


def _seven_roles() -> dict[str, object]:
    # 4 columnas -> fila 0: 0..3, fila 1: 4..6 (igual que ROLE_OPTIONS real:
    # los seis roles más SIN ROL). La fila de acciones queda en la fila 2.
    return {f"role-{index}": SimpleNamespace() for index in range(7)}


def _bind(
    toplevel, buttons, render_preview, accept_role, current_role,
    *, cancel_action=None, cancel_button=None, confirm_button=None,
):
    cancel_button = cancel_button or _FakeButton("#4A4A4A", 1)
    confirm_button = confirm_button or _FakeButton("#000000", 0)
    RoleRunManager._bind_role_grid_arrow_navigation(
        toplevel, buttons, render_preview, accept_role, current_role,
        cancel_button=cancel_button, confirm_button=confirm_button,
        cancel_action=cancel_action or (lambda: None),
    )
    return cancel_button, confirm_button


def test_right_and_left_move_along_the_same_row() -> None:
    buttons = _seven_roles()
    previews: list[str] = []
    toplevel = _FakeToplevel()

    _bind(toplevel, buttons, previews.append, lambda _e=None: None, "role-0")

    toplevel.bindings["<KeyPress-Right>"](None)
    assert previews[-1] == "role-1"

    toplevel.bindings["<KeyPress-Right>"](None)
    assert previews[-1] == "role-2"

    toplevel.bindings["<KeyPress-Left>"](None)
    assert previews[-1] == "role-1"


def test_down_and_up_move_between_rows_by_column() -> None:
    buttons = _seven_roles()
    previews: list[str] = []
    toplevel = _FakeToplevel()

    # role-2 está en la fila 0, columna 2.
    _bind(toplevel, buttons, previews.append, lambda _e=None: None, "role-2")

    toplevel.bindings["<KeyPress-Down>"](None)
    assert previews[-1] == "role-6"  # fila 1, columna 2

    toplevel.bindings["<KeyPress-Up>"](None)
    assert previews[-1] == "role-2"


def test_the_short_second_row_does_not_crash_going_right() -> None:
    """La fila 1 solo tiene 3 elementos (columnas 0-2), sin columna 3 propia.

    `SpatialSelection.move` (el mismo motor que ya usan Equipo/PC y
    Movimientos) no restringe izquierda/derecha a la misma fila: sin ningún
    candidato en la fila 1 con columna mayor que 2, salta al único que sí
    cumple "columna > 2" en toda la rejilla -role-3, fila 0-. Es el
    comportamiento ya establecido del motor compartido; aquí solo importa
    que no explote con una fila más corta que las demás.
    """
    buttons = _seven_roles()
    previews: list[str] = []
    toplevel = _FakeToplevel()

    _bind(toplevel, buttons, previews.append, lambda _e=None: None, "role-6")

    toplevel.bindings["<KeyPress-Right>"](None)

    assert previews == ["role-3"]


def test_return_on_a_role_still_confirms_directly() -> None:
    """Atajo de siempre: no hace falta bajar hasta ACEPTAR ROL para
    confirmar el rol que ya se está previsualizando."""
    buttons = _seven_roles()
    accepted: list[bool] = []
    toplevel = _FakeToplevel()

    _bind(
        toplevel, buttons, lambda _role: None,
        lambda _e=None: accepted.append(True), "role-0",
    )

    toplevel.bindings["<KeyPress-Return>"](None)

    assert accepted == [True]


def test_down_from_the_last_role_row_reaches_cancel_and_confirm() -> None:
    """Pedido del usuario 09-09-2026, misma tarde: "falta que se pueda ir con
    flechas a Aceptar Rol o Cancelar"."""
    buttons = _seven_roles()
    accepted: list[bool] = []
    cancelled: list[bool] = []
    toplevel = _FakeToplevel()

    cancel_button, confirm_button = _bind(
        toplevel, buttons, lambda _role: None,
        lambda _e=None: accepted.append(True), "role-4",  # fila 1, columna 0
        cancel_action=lambda: cancelled.append(True),
    )

    toplevel.bindings["<KeyPress-Down>"](None)  # a CANCELAR (columna 0)
    assert cancel_button.cget("border_color") == "#F2C45E"
    assert confirm_button.cget("border_color") == "#000000"  # sin tocar

    toplevel.bindings["<KeyPress-Return>"](None)
    assert cancelled == [True]
    assert accepted == []

    toplevel.bindings["<KeyPress-Right>"](None)  # de CANCELAR a ACEPTAR ROL
    assert confirm_button.cget("border_color") == "#F2C45E"
    assert cancel_button.cget("border_color") == "#4A4A4A"  # se le devolvió su borde de reposo

    toplevel.bindings["<KeyPress-Return>"](None)
    assert accepted == [True]


def test_moving_back_up_from_an_action_button_clears_its_focus_highlight() -> None:
    buttons = _seven_roles()
    toplevel = _FakeToplevel()

    cancel_button, _confirm_button = _bind(
        toplevel, buttons, lambda _role: None, lambda _e=None: None, "role-4",
    )

    toplevel.bindings["<KeyPress-Down>"](None)  # a CANCELAR
    assert cancel_button.cget("border_color") == "#F2C45E"

    toplevel.bindings["<KeyPress-Up>"](None)  # de vuelta a la rejilla de roles

    assert cancel_button.cget("border_color") == "#4A4A4A"
    assert cancel_button.cget("border_width") == 1


def test_open_role_editor_wires_the_shared_navigation_helper() -> None:
    import inspect

    fuente = inspect.getsource(RoleRunManager.open_role_editor)
    assert "self._bind_role_grid_arrow_navigation(" in fuente
    assert "window.winfo_toplevel(), buttons, render_preview, accept_role, current_role" in fuente
    assert "cancel_button=team_cancel_button, confirm_button=team_confirm_button" in fuente


def test_pc_role_editor_wires_the_shared_navigation_helper_and_restores_owner() -> None:
    import inspect

    fuente = inspect.getsource(RoleRunManager._open_pc_role_editor)
    assert "self._bind_role_grid_arrow_navigation(" in fuente
    assert "cancel_button=pc_cancel_button, confirm_button=pc_confirm_button" in fuente
    # `IntegratedWindowSurface` comparte el root con la página de fondo -a
    # diferencia del editor de equipo (`TransparentWindowSurface`, un
    # `CTkToplevel` propio)-, así que aquí hace falta apartar y devolver la
    # autoridad de navegación para que las flechas no muevan también el
    # resalte de la página de detrás.
    assert "self._set_navigation_owner(None)" in fuente
    assert "self._set_navigation_owner(previous_navigation_owner)" in fuente
