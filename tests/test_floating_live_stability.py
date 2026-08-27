from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app.ui import ORAS_GRAVEYARD_BOX, RoleRunManager


def _difference(*, party=False, order=False, roles=False, moves=False, levels=False):
    return SimpleNamespace(
        party_changed=party,
        order_changed=order,
        roles_changed=roles,
        moves_changed=moves,
        levels_changed=levels,
    )


def _manager_for_publish(difference):
    calls: list[tuple[str, object]] = []
    game = SimpleNamespace(party=[])
    manager = SimpleNamespace(
        current_game=game,
        _oras_live_active=False,
        _oras_live_process_name="azahar.exe",
        _clear_oras_rom_tm_runtime_profile=lambda: calls.append(("clear-rom", None)),
        _register_party_roles=lambda value: calls.append(("roles", value)),
        _pc_cache=object(),
        _pc_cache_signature=object(),
        sprite_pil_cache={},
        _load_sprite_async=lambda pokemon: None,
        _oras_live_health_snapshot=None,
        _floating_bar_is_visible=lambda: True,
        _sync_live_layout=lambda refresh_floating=True: calls.append(("sync", refresh_floating)),
        _smooth_render_page=lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("the hidden main window must not be rendered while floating")
        ),
        _schedule_team_integrity_check=lambda: calls.append(("integrity", None)),
        _main_ui_dirty_while_floating=False,
        active_page="team",
    )
    snapshot = SimpleNamespace(game=game, process=SimpleNamespace(name="Azahar.exe"))
    RoleRunManager._publish_oras_live_snapshot(manager, snapshot, difference=difference)
    return manager, calls


def test_level_update_does_not_touch_hidden_main_window_while_floating() -> None:
    manager, calls = _manager_for_publish(_difference(levels=True))
    assert manager._main_ui_dirty_while_floating is True
    assert ("sync", False) in calls  # level is not represented by the bar itself


def test_party_swap_updates_bar_but_not_hidden_main_window() -> None:
    manager, calls = _manager_for_publish(_difference(party=True))
    assert manager._main_ui_dirty_while_floating is True
    assert ("sync", True) in calls


def test_spurious_main_map_cannot_close_bar_while_another_process_is_foreground() -> None:
    calls: list[str] = []
    bar = SimpleNamespace(
        winfo_exists=lambda: True,
        state=lambda: "normal",
        deiconify=lambda: calls.append("bar-deiconify"),
        lift=lambda: calls.append("bar-lift"),
        attributes=lambda *args: calls.append("bar-topmost"),
        withdraw=lambda: calls.append("bar-withdraw"),
    )
    manager = SimpleNamespace(
        floating_bar=bar,
        _floating_bar_is_visible=lambda: True,
        _foreground_belongs_to_this_process=lambda: False,
        withdraw=lambda: calls.append("main-withdraw"),
        _floating_suspended_modal=None,
        _schedule_pending_faint_picker=lambda delay: calls.append(f"picker:{delay}"),
    )
    with patch("app.ui.os.name", "nt"):
        RoleRunManager._on_main_map(manager)
    assert "main-withdraw" in calls
    assert "bar-withdraw" not in calls
    assert "bar-deiconify" in calls


def test_oras_graveyard_is_box_four() -> None:
    assert ORAS_GRAVEYARD_BOX == 4


def test_floating_signature_hides_pending_fainted_pokemon() -> None:
    dead = SimpleNamespace(species_id=398, nickname="Ornita", species="Staraptor")
    project = SimpleNamespace(
        counters={"vidas": 3, "pociones": 0, "medallas": 0, "drafteos": 0},
        pending_faints=[{"identity": "dead"}], hidden_roles={},
    )
    manager = SimpleNamespace(
        project=project,
        _projected_party=lambda: [dead],
        _pokemon_identity=lambda pokemon: "dead",
        _team_role_grid_layout=lambda party: (
            {"Líbero": party[0]} if party else {}, [],
            ({"dead": 0} if party else {}), set(),
        ),
        _pokemon_visibility_identity=lambda pokemon: "visible",
        _sprite_source=lambda pokemon: None,
        _floating_health_values=lambda pokemon: (0, 0, 0),
    )
    counters, roles = RoleRunManager._floating_bar_signature(manager)
    # Contadores y seis casillas; la casilla Líbero queda vacía tras la baja.
    assert counters == (3, 0, 0, 0)
    assert len(roles) == 6
    assert roles[0][1] is None


def test_floating_signature_places_a_roleless_party_member_in_a_free_slot() -> None:
    tepig = SimpleNamespace(species_id=498, role="SIN ROL")
    project = SimpleNamespace(
        counters={"vidas": 0, "pociones": 0, "medallas": 0, "drafteos": 0},
        pending_faints=[], hidden_roles={},
    )
    manager = SimpleNamespace(
        project=project,
        _projected_party=lambda: [tepig],
        _pokemon_identity=lambda pokemon: "tepig",
        _team_role_grid_layout=lambda party: ({}, party, {"tepig": 0}, {0}),
        _effective_role=lambda pokemon: ("SIN ROL", ""),
        _pokemon_visibility_identity=lambda pokemon: "visible-tepig",
        _sprite_source=lambda pokemon: object(),
        _floating_health_values=lambda pokemon: (24, 24, 0) if pokemon else (0, 0, 0),
    )

    _counters, roles = RoleRunManager._floating_bar_signature(manager)
    assert roles[0][1] == "visible-tepig"
    # Los tres últimos campos de cada casilla son la salud: PS, máximo y estado.
    assert roles[0][4:7] == (24, 24, 0)


def test_floating_health_prefers_the_unique_validated_live_sample() -> None:
    projected = SimpleNamespace(pid=10, current_hp=0, max_hp=172, status_condition=0)
    validated = SimpleNamespace(pid=10, current_hp=172, max_hp=172, status_condition=64)
    manager = SimpleNamespace(
        _oras_live_health_snapshot=SimpleNamespace(party=[validated]),
        _pokemon_identity=lambda pokemon: str(pokemon.pid),
    )

    assert RoleRunManager._floating_health_values(manager, projected) == (172, 172, 64)


def test_floating_health_does_not_replace_a_real_zero_from_the_validated_lane() -> None:
    projected = SimpleNamespace(pid=10, current_hp=172, max_hp=172, status_condition=0)
    validated = SimpleNamespace(pid=10, current_hp=0, max_hp=172, status_condition=0)
    manager = SimpleNamespace(
        _oras_live_health_snapshot=SimpleNamespace(party=[validated]),
        _pokemon_identity=lambda pokemon: str(pokemon.pid),
    )

    assert RoleRunManager._floating_health_values(manager, projected) == (0, 172, 0)


def test_explicitly_visible_main_window_always_withdraws_the_floating_bar() -> None:
    calls: list[str] = []
    bar = SimpleNamespace(
        winfo_exists=lambda: True,
        state=lambda: "normal",
        withdraw=lambda: calls.append("bar-withdraw"),
    )
    manager = SimpleNamespace(
        floating_bar=bar,
        _floating_bar_is_visible=lambda: True,
        _foreground_belongs_to_this_process=lambda: False,
        state=lambda: "zoomed",
        winfo_viewable=lambda: True,
        _floating_bar_poll_id=None,
        _floating_role_reordered=False,
        _floating_suspended_modal=None,
        _main_ui_dirty_while_floating=False,
        _save_floating_bar_position=lambda: calls.append("save-pos"),
        _set_auto_floating_guard_temporarily=lambda _ms: None,
        _schedule_pending_faint_picker=lambda _delay: None,
    )
    with patch("app.ui.os.name", "nt"):
        RoleRunManager._on_main_map(manager)
    assert "bar-withdraw" in calls


def test_confirmed_role_write_does_not_render_hidden_main_window() -> None:
    calls: list[str] = []
    manager = SimpleNamespace(
        _floating_bar_is_visible=lambda: True,
        _main_ui_dirty_while_floating=False,
        active_page="team",
        _smooth_render_page=lambda **kwargs: calls.append("render-main"),
    )
    rendered = RoleRunManager._refresh_main_after_oras_live_write(manager)
    assert rendered is False
    assert manager._main_ui_dirty_while_floating is True
    assert calls == []


def test_projected_party_hides_pending_faint_in_normal_views_too() -> None:
    from app.save_engine_client import SaveGameData, SavePokemon

    dead = SavePokemon(
        slot=1, species_id=398, species="Staraptor", nickname="Ornita", level=72,
        held_item="Ninguno", ability="Intimidación", moves=["A"], move_ids=[1],
        is_egg=False, markings=[True, False, False, False, False, False],
        role="Líbero", role_symbol="", pid=10, tid=1, sid=2, current_hp=0, max_hp=200,
    )
    alive = SavePokemon(
        slot=2, species_id=609, species="Chandelure", nickname="Velado", level=71,
        held_item="Ninguno", ability="Absorbe Fuego", moves=["B"], move_ids=[2],
        is_egg=False, markings=[False, False, False, True, False, False],
        role="Mago", role_symbol="", pid=20, tid=1, sid=2, current_hp=100, max_hp=174,
    )
    current = SaveGameData("AS", "SAV6AO", 6, "Timper", [dead, alive], {})
    manager = SimpleNamespace(
        current_game=current,
        project=SimpleNamespace(pending_faints=[{"identity": "dead"}]),
        _pending_team_changes=lambda: [],
        _pokemon_identity=lambda pokemon: "dead" if pokemon.pid == 10 else "alive",
    )

    projected = RoleRunManager._projected_party(manager)
    assert [pokemon.nickname for pokemon in projected] == ["Velado"]


def test_success_live_sync_feedback_is_suppressed_in_floating_hud() -> None:
    manager = SimpleNamespace()
    # El método debe salir antes de consultar/crear widgets: mensajes verdes de
    # diagnóstico no pertenecen a la HUD durante el juego.
    RoleRunManager._show_floating_live_sync_feedback(manager, "ESTADO DE ORAS RECUPERADO", "x", True)
