from __future__ import annotations

from types import SimpleNamespace

from app.sdl_gamepad import BUTTON_NAMES, GamepadSample
from app.ui import RoleRunManager


def test_sdl_standard_button_contract_matches_navigation_and_guide_modifier() -> None:
    assert BUTTON_NAMES[0:7] == ("a", "b", "x", "y", "back", "guide", "start")
    assert BUTTON_NAMES[-4:] == ("dpad up", "dpad down", "dpad left", "dpad right")
    assert GamepadSample(False).pressed == frozenset()


def test_controller_shortcuts_use_the_individually_assigned_button() -> None:
    manager = SimpleNamespace(
        project=SimpleNamespace(controller_hotkeys={
            "floating_menu": "guide",
            "heal_party": "x",
        })
    )
    assert RoleRunManager._controller_action_for_button(manager, "guide") == "floating_menu"
    assert RoleRunManager._controller_action_for_button(manager, "x") == "heal_party"


def test_controller_ui_does_not_expose_a_hidden_guide_chord() -> None:
    import inspect

    capture = inspect.getsource(RoleRunManager.begin_controller_capture)
    settings = inspect.getsource(RoleRunManager._render_settings_page)
    assert "GUIDE +" not in capture
    assert "GUIDE +" not in settings


def test_menu_navigation_controls_are_separate_from_global_shortcuts() -> None:
    import inspect

    source = inspect.getsource(RoleRunManager._poll_gamepad)
    bindings = inspect.getsource(RoleRunManager._bind_floating_menu_keyboard)
    assert "controller_menu_buttons" in source
    assert "menu_keys" in bindings
    assert "_hotkey_action" not in bindings


def test_same_controller_accept_and_back_are_routed_in_main_and_overlay() -> None:
    import inspect

    source = inspect.getsource(RoleRunManager._poll_gamepad)
    assert source.count('menu_buttons.get("accept", "a")') == 2
    assert source.count('menu_buttons.get("back", "b")') == 2
    assert "_clear_active_view_selection" in source


def test_controller_dpad_routes_home_by_grid_and_page_to_visible_view() -> None:
    painted: list[int] = []
    moved: list[str] = []
    manager = SimpleNamespace(
        _floating_menu_level="home",
        _floating_menu_buttons=[object()] * 5,
        _floating_menu_index=0,
        _paint_floating_menu_selection=lambda: painted.append(manager._floating_menu_index),
        _dispatch_game_overlay_key=lambda _event, direction: moved.append(direction),
    )
    RoleRunManager._dispatch_controller_direction(manager, "right")
    RoleRunManager._dispatch_controller_direction(manager, "down")
    assert painted == [1, 3]

    manager._floating_menu_level = "page"
    RoleRunManager._dispatch_controller_direction(manager, "left")
    assert moved == ["left"]


def test_controller_navigation_uses_modal_owner_instead_of_hidden_page() -> None:
    moved: list[tuple[str, str]] = []

    class View:
        def __init__(self, name: str) -> None:
            self.name = name

        def _move_keyboard(self, _event, direction: str) -> None:
            moved.append((self.name, direction))

    hidden_team = View("hidden-team")
    tm_modal = View("tm-modal")
    manager = SimpleNamespace(
        active_page="team",
        _navigation_owner=tm_modal,
        _team_pc_view=hidden_team,
        _global_tm_view=None,
        _draft_view=None,
    )
    manager._active_navigation_view = lambda: RoleRunManager._active_navigation_view(manager)

    assert RoleRunManager._dispatch_game_overlay_key(manager, None, "down") == "break"
    assert moved == [("tm-modal", "down")]


def test_main_controller_navigation_keeps_controlled_repeat_after_single_owner_fix() -> None:
    import inspect

    source = inspect.getsource(RoleRunManager._poll_gamepad)
    foreground_branch = source.split("if role_run_foreground:", 1)[1]
    foreground_branch = foreground_branch.split("if self._foreground_is_supported_emulator():", 1)[0]
    assert 'if button in pressed:' in foreground_branch
    assert 'menu_buttons.get("accept", "a") in pressed' in foreground_branch
    assert 'menu_buttons.get("back", "b") in pressed' in foreground_branch


def test_bdsp_foreground_gate_is_idempotent_and_releases_on_focus_loss() -> None:
    import app.ui as ui

    class Gate:
        def __init__(self) -> None:
            self.active = False
            self.acquires = 0
            self.releases = 0

        def acquire(self) -> bool:
            self.acquires += 1
            self.active = True
            return True

        def release(self, *, all_levels: bool = False) -> bool:
            assert all_levels is True
            self.releases += 1
            self.active = False
            return True

    gate = Gate()
    manager = SimpleNamespace(
        save_engine=SimpleNamespace(key="bdsp"),
        current_game=object(),
        _ryujinx_input_gate=gate,
        _role_run_foreground_gate_held=False,
        _gamepad_reserved_buttons=set(),
        _floating_launcher=None,
        # Con un mando enchufado: sin el no hay ningun flanco que pueda
        # alcanzar al emulador y retenerlo seria coste puro.
        _hay_mando=True,
        _foreground=True,
        _foreground_belongs_to_this_process=lambda: manager._foreground,
        _widget_alive=lambda _widget: False,
    )

    # La retencion tambien depende de si el emulador se protege solo, y eso se
    # lee del `Config.json` real de quien ejecute las pruebas. Sin fijarlo aqui,
    # esta prueba pasaba o fallaba segun como tuviera el usuario Ryujinx: la
    # cambio a mano y la suite se puso roja sin que nadie tocara el codigo.
    anterior = ui.ryujinx_ignora_el_mando_sin_foco
    ui.ryujinx_ignora_el_mando_sin_foco = lambda: False
    try:
        assert RoleRunManager._sync_role_run_foreground_input_gate(manager) is True
        assert RoleRunManager._sync_role_run_foreground_input_gate(manager) is True
        assert gate.acquires == 1

        manager._foreground = False
        assert RoleRunManager._sync_role_run_foreground_input_gate(manager) is False
        assert gate.releases == 1
        assert manager._role_run_foreground_gate_held is False
    finally:
        ui.ryujinx_ignora_el_mando_sin_foco = anterior


def test_gamepad_poll_reserves_ryujinx_before_sampling_and_dispatch() -> None:
    import inspect

    source = inspect.getsource(RoleRunManager._poll_gamepad)
    sync_index = source.index("_sync_role_run_foreground_input_gate")
    sample_index = source.index(".sample()")
    dispatch_index = source.index("_dispatch_game_overlay_key")
    assert sync_index < sample_index < dispatch_index


def test_short_gamepad_tap_never_becomes_synthetic_repeat() -> None:
    button = frozenset({"dpad down"})
    pressed, repeat_at = RoleRunManager._update_gamepad_navigation_repeat(
        current=button, previous=frozenset(), repeat_at={}, now=10.0,
    )
    assert pressed == button
    assert repeat_at["dpad down"] == 10.45

    # Sigue siendo el mismo toque físico: antes de 450 ms no nace otro input.
    pressed, repeat_at = RoleRunManager._update_gamepad_navigation_repeat(
        current=button, previous=button, repeat_at=repeat_at, now=10.30,
    )
    assert pressed == frozenset()

    # Soltar limpia el estado y el siguiente tap vuelve a ser un único flanco.
    pressed, repeat_at = RoleRunManager._update_gamepad_navigation_repeat(
        current=frozenset(), previous=button, repeat_at=repeat_at, now=10.31,
    )
    assert pressed == frozenset()
    assert "dpad down" not in repeat_at


def test_deliberate_gamepad_hold_repeats_only_after_450_ms() -> None:
    button = frozenset({"dpad right"})
    _pressed, repeat_at = RoleRunManager._update_gamepad_navigation_repeat(
        current=button, previous=frozenset(), repeat_at={}, now=20.0,
    )
    pressed, repeat_at = RoleRunManager._update_gamepad_navigation_repeat(
        current=button, previous=button, repeat_at=repeat_at, now=20.449,
    )
    assert pressed == frozenset()
    pressed, repeat_at = RoleRunManager._update_gamepad_navigation_repeat(
        current=button, previous=button, repeat_at=repeat_at, now=20.45,
    )
    assert pressed == button
    assert repeat_at["dpad right"] == 20.52


def test_sin_mando_conectado_no_se_retiene_el_emulador() -> None:
    """Retener a Ryujinx lo para entero: 0,0% de CPU, reloj parado, sin musica.

    Medido en la maquina del usuario, era lo que le cortaba el sonido del juego
    cada vez que pinchaba en RoleRun. La retencion existe por una razon buena
    -Ryujinx acepta mando sin foco, asi que el flanco que navega RoleRun moveria
    tambien al personaje- pero esa razon solo existe si hay un mando enchufado.
    """
    class Gate:
        def __init__(self) -> None:
            self.active = False
            self.acquires = 0

        def acquire(self) -> bool:
            self.acquires += 1
            self.active = True
            return True

        def release(self, *, all_levels: bool = False) -> bool:
            self.active = False
            return True

    gate = Gate()
    manager = SimpleNamespace(
        save_engine=SimpleNamespace(key="bdsp"),
        current_game=object(),
        _ryujinx_input_gate=gate,
        _role_run_foreground_gate_held=False,
        _gamepad_reserved_buttons=set(),
        _floating_launcher=None,
        _hay_mando=False,
        _foreground_belongs_to_this_process=lambda: True,
        _widget_alive=lambda _widget: False,
    )

    RoleRunManager._sync_role_run_foreground_input_gate(manager)

    assert gate.acquires == 0, "se paro el juego sin que hubiera nada que proteger"
    assert gate.active is False


def test_si_el_emulador_se_protege_solo_no_se_le_para() -> None:
    """Ryujinx tiene `disable_input_when_out_of_focus`, y es la solucion buena.

    Con esa opcion puesta, el emulador no lee el mando sin el foco: RoleRun puede
    navegar sus menus con el mando sin que el flanco llegue al personaje, y el
    juego sigue corriendo -con su musica- mientras tanto. Suspenderlo ademas
    seria pararlo por nada.
    """
    import app.ui as ui

    class Gate:
        def __init__(self) -> None:
            self.active = False
            self.acquires = 0

        def acquire(self) -> bool:
            self.acquires += 1
            self.active = True
            return True

        def release(self, *, all_levels: bool = False) -> bool:
            self.active = False
            return True

    gate = Gate()
    manager = SimpleNamespace(
        save_engine=SimpleNamespace(key="bdsp"),
        current_game=object(),
        _ryujinx_input_gate=gate,
        _role_run_foreground_gate_held=False,
        _gamepad_reserved_buttons=set(),
        _floating_launcher=None,
        _hay_mando=True,
        _foreground_belongs_to_this_process=lambda: True,
        _widget_alive=lambda _widget: False,
    )

    anterior = ui.ryujinx_ignora_el_mando_sin_foco
    try:
        ui.ryujinx_ignora_el_mando_sin_foco = lambda: True
        RoleRunManager._sync_role_run_foreground_input_gate(manager)
        assert gate.acquires == 0, "se paro el juego pudiendo no pararlo"

        ui.ryujinx_ignora_el_mando_sin_foco = lambda: False
        RoleRunManager._sync_role_run_foreground_input_gate(manager)
        assert gate.acquires == 1, "sin esa opcion la proteccion si hace falta"
    finally:
        ui.ryujinx_ignora_el_mando_sin_foco = anterior


def test_ante_la_duda_se_protege() -> None:
    """Dar por hecho que el emulador se protege dejaria colarse los botones."""
    import json

    from app.sdl_gamepad import ryujinx_ignora_el_mando_sin_foco
    import app.sdl_gamepad as sdl

    sdl._config_en_cache = None
    assert ryujinx_ignora_el_mando_sin_foco() in (True, False)

    # Sin APPDATA no hay config que leer, y la respuesta conservadora es False.
    import os
    previo = os.environ.pop("APPDATA", None)
    try:
        sdl._config_en_cache = None
        assert ryujinx_ignora_el_mando_sin_foco() is False
    finally:
        if previo is not None:
            os.environ["APPDATA"] = previo
        sdl._config_en_cache = None
