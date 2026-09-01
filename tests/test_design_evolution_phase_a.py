from __future__ import annotations

import json
import inspect
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.role_content import ROLE_GUIDE
from app.bdsp_tm_service import BDSPTMProfile, _move_descriptions_from_objects, _personal_base_stats
from app.run_service import RunProject, RunProjectService
from app.ui_state.operation_status import OperationMessage, OperationStatusStore
from app.ui_state.spatial_navigation import SpatialSelection, SpatialTarget
from app.ui_state.path_actions import resolve_explorer_target
from app.ui_state.navigation import (
    DEFAULT_PAGE, PRIMARY_NAVIGATION, normalize_navigation_target, primary_page_for,
)
from app.models import PendingRoleChange, PendingTeamChange
from app.save_engine_client import SaveGameData, SavePokemon
from app.ui import RoleRunManager
from app.ui_views.draft_flow import IntegratedDraftFlow, _draft_result_layout
from app.ui_views.global_tm_view import GlobalTMView
from app.ui_views.team_pc_view import (
    DRAG_BOX_HOVER_DELAY_MS,
    DRAG_BOX_HOVER_REPEAT_MS,
    UnifiedTeamPCView,
    _move_issue_map,
)
from app.ui_views.tm_teach_flow import IntegratedTMTeachFlow
from app.ui_components.loading_indicator import CenteredLoadingIndicator
from app.ui_components.operation_bar import OperationStatusBar
from app.ui_components.role_icons import ROLE_ICON_FILES, RoleIconProvider
from app.ui_state.team_pc_state import (
    TMTeachFlowState,
    TeamPCSelectionState,
    build_fixed_team_slots,
    resolve_team_pc_drop,
)
from app.ui_state.spatial_navigation import SpatialSelection, SpatialTarget



def _preparar_barrera(manager) -> None:
    """Monta en el doble lo que la barrera necesita para soltar lo aplazado.

    Durante el arranque los repintados se guardan en vez de hacerse (seis
    reconstrucciones medidas que nadie llegaba a ver). Quien las suelta es esta
    misma barrera, asi que se le monta el metodo **real** y sin nada guardado:
    estas pruebas siguen midiendo la barrera de verdad y no un doble que podria
    diverger de ella.
    """
    manager._arranque_repintado_aplazado = None
    manager._soltando_repintado_de_arranque = False
    manager._soltar_el_repintado_aplazado = lambda: (
        RoleRunManager._soltar_el_repintado_aplazado(manager)
    )

def test_oras_role_ev_change_requires_personal_profile_before_live_write() -> None:
    role_change = PendingRoleChange(
        2, "Houndoom", "Houndoom", "Asesino", "Mago",
        old_evs=(0, 252, 0, 0, 0, 252),
        new_evs=(0, 0, 0, 252, 0, 252),
    )

    assert RoleRunManager._oras_changes_require_personal([role_change]) is True


def test_oras_marker_only_role_change_does_not_require_personal_profile() -> None:
    role_change = PendingRoleChange(2, "Houndoom", "Houndoom", "Asesino", "Mago")

    assert RoleRunManager._oras_changes_require_personal([role_change]) is False


def test_oras_personal_profile_is_pinned_to_writer_for_transaction() -> None:
    expected = object()
    profile = SimpleNamespace(personal_for=lambda species_id, form: expected)
    writer = SimpleNamespace(personal_for=lambda species_id, form: None)

    RoleRunManager._pin_oras_personal_profile(writer, profile)
    del profile

    assert writer.personal_for(195, 0) is expected


def _training_test_pokemon(**overrides) -> SavePokemon:
    values = {
        "slot": 1, "species_id": 303, "species": "Mawile",
        "nickname": "Farigiraf", "level": 24, "held_item": "Ninguno",
        "ability": "Absorbe Agua", "moves": ["Protección"],
        "move_ids": [182], "is_egg": False, "markings": [True] + [False] * 5,
        "role": "Líbero", "role_symbol": "●", "pid": 1, "tid": 2, "sid": 3,
    }
    values.update(overrides)
    return SavePokemon(**values)


def test_team_cards_and_inspector_share_the_same_move_incompatibility_map() -> None:
    pokemon = _training_test_pokemon(moves=["Lluevehojas", "Cuchilla Solar"])
    calls: list[tuple[SavePokemon, str]] = []

    def issues_for(member: SavePokemon, role: str) -> list[dict[str, object]]:
        calls.append((member, role))
        return [{"move_slot": 2, "move_name": "Cuchilla Solar"}]

    expected = {2: {"move_slot": 2, "move_name": "Cuchilla Solar"}}
    assert _move_issue_map(pokemon, "Mago", issues_for, context="team") == expected
    assert _move_issue_map(pokemon, "Mago", issues_for, context="pc") == {}
    assert calls == [(pokemon, "Mago")]


def test_bdsp_live_training_presentation_is_not_discarded_when_identity_matches() -> None:
    disk = SaveGameData("SP", "SAV8BS", 8, "Timper", [_training_test_pokemon()], {})
    live = SaveGameData(
        "SP", "SAV8BS", 8, "Timper",
        [_training_test_pokemon(
            nature_id=3, stat_nature_id=3, nature="Activa", stat_nature="Activa",
            stats={"hp": 74, "attack": 50},
            base_stats={"hp": 50, "attack": 85},
            ivs={"hp": 5, "attack": 19}, evs={"hp": 252, "attack": 0},
        )], {},
    )

    assert RoleRunManager._party_training_presentation_changed(disk, live) is True
    assert RoleRunManager._party_training_presentation_changed(live, live) is False


def _legacy_project(save_path: Path) -> RunProject:
    return RunProject(
        slug="sp-timper",
        name="SP · Timper",
        game="SP",
        trainer="Timper",
        save_path=str(save_path),
        created_at="2026-08-23T10:00:00",
        updated_at="2026-08-23T10:00:00",
        role_overrides={"slot-1": "Líbero"},
        managed_pokemon_roles={"300:10:20:30": "Mago"},
        hidden_roles={"support": "79:1:2:3"},
        role_marker_layout=2,
        role_rules_active=False,
        counters={"vidas": 4, "pociones": 2, "medallas": 3, "drafteos": 7},
    )


def test_navigation_owner_prevents_hidden_view_from_consuming_same_arrow() -> None:
    calls: list[str] = []
    hidden = SimpleNamespace(
        navigation_guard=lambda: False,
        navigation_intercept=None,
        _keyboard_inspector_action=None,
        selection=SimpleNamespace(
            context="team", selected_identity="a", selected_box_slot=None,
            move_direction=lambda *_args, **_kwargs: calls.append("hidden") or "b",
        ),
    )
    visible = SimpleNamespace(
        navigation_guard=lambda: True,
        navigation_intercept=None,
        pc_columns=3,
        _keyboard_inspector_action=None,
        selection=SimpleNamespace(
            context="team", selected_identity="a", selected_box_slot=None,
            move_direction=lambda *_args, **_kwargs: calls.append("visible") or "b",
        ),
        _inspector_action_buttons={},
        _apply_selection_styles=lambda: None,
        _schedule_inspector_render=lambda: None,
    )

    assert UnifiedTeamPCView._move_direction_key(hidden, None, "down") is None
    assert UnifiedTeamPCView._move_direction_key(visible, None, "down") == "break"
    assert calls == ["visible"]


def test_sidebar_navigation_has_exclusive_focus_and_moves_one_entry() -> None:
    configured: list[dict[str, object]] = []

    class Button:
        def configure(self, **kwargs):
            configured.append(kwargs)

    owner_focus: list[bool] = []
    manager = SimpleNamespace(
        sidebar_expanded=True,
        _sidebar_keyboard_entries=(("team", Button()), ("tms", Button()), ("drafts", Button())),
        _sidebar_keyboard_index=0,
        active_page="team",
        _navigation_owner=SimpleNamespace(
            set_external_navigation_focus=lambda active: owner_focus.append(active),
        ),
    )
    manager._paint_sidebar_keyboard_selection = lambda: RoleRunManager._paint_sidebar_keyboard_selection(manager)

    assert RoleRunManager._handle_sidebar_navigation(manager, "down") is True
    assert manager._sidebar_keyboard_index == 1
    assert configured


def test_draft_focus_uses_shared_gold_and_libero_has_no_false_selection() -> None:
    source = inspect.getsource(IntegratedDraftFlow._apply_keyboard_selection)
    pokemon_step = inspect.getsource(IntegratedDraftFlow._render_pokemon_step)
    assert 'border_color="#F2C45E"' in source
    assert "border_width=4" in source
    assert 'border_color=GOLD if role == "Líbero"' not in pokemon_step


def test_sidebar_down_past_the_last_entry_reaches_the_close_arrow() -> None:
    """Hallazgo del usuario 31-08-2026: no había forma de llegar a la flecha
    "‹" de cerrar navegando con flechas/mando, solo con el botón de "back"
    configurado. Bajar una vez más allá de la última página debe seleccionar
    la flecha, resaltarla, y aceptar ahí debe cerrar el drawer en vez de
    navegar."""
    configured: list[dict[str, object]] = []
    toggle_configured: list[dict[str, object]] = []
    navigated: list[str] = []
    closed: list[bool] = []

    class Button:
        def configure(self, **kwargs):
            configured.append(kwargs)

    class Toggle:
        def configure(self, **kwargs):
            toggle_configured.append(kwargs)

    manager = SimpleNamespace(
        sidebar_expanded=True,
        _sidebar_keyboard_entries=(("team", Button()), ("tms", Button())),
        _sidebar_keyboard_index=0,
        active_page="team",
        sidebar_drawer_toggle=Toggle(),
        navigate=navigated.append,
        _navigation_owner=SimpleNamespace(
            set_external_navigation_focus=lambda active: None,
        ),
    )
    manager._paint_sidebar_keyboard_selection = lambda: RoleRunManager._paint_sidebar_keyboard_selection(manager)
    manager._set_sidebar_expanded = lambda expanded: closed.append(expanded)

    assert RoleRunManager._handle_sidebar_navigation(manager, "down") is True
    assert RoleRunManager._handle_sidebar_navigation(manager, "down") is True
    assert manager._sidebar_keyboard_index == 2
    assert toggle_configured[-1]["fg_color"] == "#2A2417"

    assert RoleRunManager._accept_sidebar_from_content(manager) is True
    assert navigated == []
    assert closed == [False]


def test_accepting_the_collapsed_chevron_clears_its_own_gold_border() -> None:
    """Hallazgo del usuario 01-09-2026: seleccionar el chevrón "›" colapsado
    con "izquierda" y luego ACEPTAR (en vez de "derecha"/"back") abría el
    drawer sin apagar el borde dorado del chevrón — al navegar después a una
    página, quedaban dos cosas marcadas como seleccionadas a la vez."""
    configured: list[dict[str, object]] = []

    class Toggle:
        def configure(self, **kwargs):
            configured.append(kwargs)

    expanded: list[bool] = []
    manager = SimpleNamespace(
        sidebar_expanded=False,
        _sidebar_navigation_selected=True,
        sidebar_toggle=Toggle(),
        _sidebar_keyboard_entries=(),
    )
    manager._set_sidebar_expanded = lambda value: expanded.append(value)

    assert RoleRunManager._accept_sidebar_from_content(manager) is True
    assert manager._sidebar_navigation_selected is False
    assert expanded == [True]
    assert configured[-1] == {"fg_color": "transparent", "border_width": 0}


def test_sidebar_right_selects_the_close_arrow_then_the_first_content_item() -> None:
    """Pedido del usuario 01-09-2026: con el menú lateral abierto, "derecha"
    debe poner el cursor sobre la flecha "‹"; "derecha" otra vez (ya sobre
    ella) debe cerrar el drawer y seleccionar el primer botón de la pestaña
    activa, sin importar qué estuviera seleccionado antes de abrir el menú."""
    toggle_configured: list[dict[str, object]] = []
    moved: list[tuple[object, str]] = []
    focus_events: list[bool] = []

    class Toggle:
        def configure(self, **kwargs):
            toggle_configured.append(kwargs)

    class Button:
        def configure(self, **kwargs):
            pass

    view = SimpleNamespace(
        selection=SimpleNamespace(active=True),
        set_external_navigation_focus=lambda active: focus_events.append(active),
        _move_direction_key=lambda event, direction: moved.append((event, direction)),
    )
    manager = SimpleNamespace(
        sidebar_expanded=True,
        _sidebar_keyboard_entries=(("team", Button()), ("tms", Button())),
        _sidebar_keyboard_index=0,
        active_page="team",
        sidebar_drawer_toggle=Toggle(),
        _navigation_owner=view,
    )
    manager._set_sidebar_expanded = lambda expanded: setattr(manager, "sidebar_expanded", expanded)
    manager._paint_sidebar_keyboard_selection = lambda: RoleRunManager._paint_sidebar_keyboard_selection(manager)
    manager._focus_first_content_item = lambda: RoleRunManager._focus_first_content_item(manager)
    manager._set_content_navigation_focus = lambda active: RoleRunManager._set_content_navigation_focus(manager, active)

    assert RoleRunManager._handle_sidebar_navigation(manager, "right") is True
    assert manager._sidebar_keyboard_index == 2
    assert toggle_configured[-1]["fg_color"] == "#2A2417"

    assert RoleRunManager._handle_sidebar_navigation(manager, "right") is True
    assert manager.sidebar_expanded is False
    assert view.selection.active is False
    assert moved == [(None, "down")]
    # `_set_content_navigation_focus(True)` invierte el booleano al llamar al
    # setter (`active` de la vista = "el foco externo manda", ver docstring
    # de `_set_content_navigation_focus`): la última llamada real debe
    # devolverle su propio cursor a la vista, o sea `False`.
    assert focus_events[-1] is False


def test_left_on_the_selected_collapsed_chevron_opens_the_sidebar() -> None:
    """Pedido del usuario 01-09-2026: con el chevrón "›" colapsado ya
    seleccionado (tras pulsar "izquierda" desde el contenido), pulsar
    "izquierda" otra vez debe abrir el menú — lo mismo que aceptar sobre él."""
    toggle_configured: list[dict[str, object]] = []

    class Toggle:
        def configure(self, **kwargs):
            toggle_configured.append(kwargs)

    expanded: list[bool] = []
    manager = SimpleNamespace(
        sidebar_expanded=False,
        _sidebar_navigation_selected=True,
        sidebar_toggle=Toggle(),
        _sidebar_keyboard_entries=(),
    )
    manager._set_sidebar_expanded = lambda value: expanded.append(value)
    manager._accept_sidebar_from_content = lambda: RoleRunManager._accept_sidebar_from_content(manager)

    assert RoleRunManager._handle_sidebar_navigation(manager, "left") is True
    assert manager._sidebar_navigation_selected is False
    assert expanded == [True]
    assert toggle_configured[-1] == {"fg_color": "transparent", "border_width": 0}


def test_open_sidebar_consumes_horizontal_arrows_without_restoring_content_focus() -> None:
    focus: list[bool] = []
    manager = SimpleNamespace(
        sidebar_expanded=True,
        _sidebar_keyboard_entries=(("team", object()),),
        _sidebar_keyboard_index=0,
        _navigation_owner=SimpleNamespace(
            set_external_navigation_focus=lambda active: focus.append(active),
        ),
        _paint_sidebar_keyboard_selection=lambda: None,
    )

    assert RoleRunManager._handle_sidebar_navigation(manager, "left") is True
    assert manager.sidebar_expanded is True
    assert RoleRunManager._handle_sidebar_navigation(manager, "right") is True
    assert manager.sidebar_expanded is True
    assert focus == [True, True]


def test_legacy_free_mode_migrates_only_the_obsolete_project_flag(tmp_path: Path) -> None:
    save_path = tmp_path / "main"
    save_bytes = b"the game save must remain untouched"
    save_path.write_bytes(save_bytes)
    service = RunProjectService(tmp_path / "Runs", tmp_path / "OBS")
    project = _legacy_project(save_path)
    folder = service.folder(project)
    folder.mkdir(parents=True)
    (folder / "config.json").write_text(
        json.dumps(asdict(project), ensure_ascii=False), encoding="utf-8"
    )

    loaded = service.load(project.slug)

    assert loaded is not None
    assert loaded.role_rules_active is True
    assert loaded.role_overrides == project.role_overrides
    assert loaded.managed_pokemon_roles == project.managed_pokemon_roles
    assert loaded.hidden_roles == project.hidden_roles
    assert loaded.counters == project.counters
    assert save_path.read_bytes() == save_bytes


def test_new_runs_start_with_role_rules_active(tmp_path: Path) -> None:
    save_path = tmp_path / "main"
    save_path.write_bytes(b"save")
    service = RunProjectService(tmp_path / "Runs", tmp_path / "OBS")

    project = service.open_or_create("SP", "Timper", save_path)

    assert project.role_rules_active is True


def test_operation_failure_is_persistent_and_cannot_be_collapsed() -> None:
    store = OperationStatusStore()
    message = store.publish("failed", "NO SE PUDO APLICAR", "El juego no confirmó el cambio.")

    assert message.stays_visible is True
    assert store.collapse_if_current(message.revision) is False
    assert store.message == message


def test_confirmed_operation_collapses_only_if_no_newer_message_exists() -> None:
    store = OperationStatusStore()
    confirmed = store.publish("confirmed", "CAMBIO REALIZADO", "El juego confirmó el cambio.")
    store.publish("pending", "CAMBIO PENDIENTE", "Hay otra operación preparada.")

    assert store.collapse_if_current(confirmed.revision) is False
    assert store.message.kind == "pending"


def test_operation_store_notifies_each_real_state_transition() -> None:
    observed: list[OperationMessage] = []
    store = OperationStatusStore()
    store.subscribe(observed.append)

    store.publish("prepared", "CAMBIO PREPARADO", "Farigiraf será intercambiado.")
    store.publish("applying", "APLICANDO CAMBIO", "RoleRun está enviando la operación.")
    store.publish("verifying", "VERIFICANDO EN EL JUEGO", "Esperando confirmación independiente.")
    store.publish("confirmed", "CAMBIO REALIZADO", "El juego confirmó el intercambio.")

    assert [message.kind for message in observed] == [
        "neutral", "prepared", "applying", "verifying", "confirmed"
    ]


def test_primary_navigation_removes_dashboard_history_and_moves() -> None:
    assert DEFAULT_PAGE == "team"
    assert [key for key, _label in PRIMARY_NAVIGATION] == [
        "team", "tms", "drafts", "settings", "help"
    ]
    labels = " ".join(label for _key, label in PRIMARY_NAVIGATION)
    assert "EQUIPO Y PC" in labels
    assert "DASHBOARD" not in labels
    assert "HISTORIAL" not in labels
    # Antes esto miraba el rotulo, buscando que "MOVIMIENTOS" no apareciera: era
    # la forma de comprobar que la consulta de movimientos habia dejado de ser
    # destino principal. Ya no vale, porque la pestana de MT se llama asi. Lo
    # que importa es la clave, y esa sigue fuera.
    assert "moves" not in {key for key, _label in PRIMARY_NAVIGATION}


def test_legacy_navigation_targets_land_in_the_new_information_architecture() -> None:
    assert normalize_navigation_target("dashboard") == "team"
    assert primary_page_for("pc") == "team"
    assert primary_page_for("history") == "settings"
    assert primary_page_for("moves") == "help"


def test_fixed_team_projection_never_creates_a_seventh_position() -> None:
    class Pokemon:
        def __init__(self, slot: int, identity: str, role: str) -> None:
            self.slot = slot
            self.identity = identity
            self.role = role

    party = [
        Pokemon(1, "a", "Líbero"), Pokemon(2, "b", "Mago"),
        Pokemon(3, "c", "Mago"), Pokemon(4, "d", "SIN ROL"),
        Pokemon(5, "e", "Tanque"), Pokemon(6, "f", "Support"),
    ]

    slots = build_fixed_team_slots(party, lambda item: item.role, lambda item: item.identity)

    assert len(slots) == 6
    assert {slot["pokemon"].identity for slot in slots if slot["pokemon"]} == {
        "a", "b", "c", "d", "e", "f"
    }
    assert any(slot["state"] == "preparation" for slot in slots)


def test_inspector_arrows_skip_empty_pc_positions_and_wrap() -> None:
    state = TeamPCSelectionState(context="pc", selected_box_slot=4)
    state.set_pc_box(2, [1, 4, 11])

    assert state.move(1) == ("pc", 11)
    assert state.move(1) == ("pc", 1)
    assert state.move(-1) == ("pc", 11)


def test_box_change_preserves_equivalent_position_or_nearest_occupied() -> None:
    state = TeamPCSelectionState(context="pc", selected_box_slot=9)
    state.set_pc_box(1, [2, 9, 12])
    state.set_pc_box(2, [3, 8, 14])

    assert state.selected_box_slot == 8


def test_drag_routes_to_the_same_existing_team_pc_operations() -> None:
    assert resolve_team_pc_drop(
        "team", "pc", target_occupied=False, team_count=6,
    ).operation == "party-to-box"
    assert resolve_team_pc_drop(
        "team", "pc", target_occupied=True, team_count=6,
    ).operation == "swap-party-box"
    assert resolve_team_pc_drop(
        "pc", "team", target_occupied=False, team_count=5,
    ).operation == "box-to-party"
    assert resolve_team_pc_drop(
        "pc", "team", target_occupied=True, team_count=6,
    ).operation == "swap-party-box"


def test_pc_move_to_empty_slot_is_distinct_from_pc_swap() -> None:
    """Dos operaciones distintas, no una permitida y otra prohibida.

    Llevar a un hueco libre conserva un solo PK6; intercambiar dos casillas
    ocupadas conserva dos y no dispone de ninguna casilla vacía donde apoyar la
    calibración. Qué backend sabe escribir cada una lo decide la interfaz
    (`PC_A_PC_GAME_KEYS` y `PC_SWAP_GAME_KEYS`), no este resolutor.
    """
    assert resolve_team_pc_drop(
        "pc", "pc", target_occupied=False, team_count=4,
    ).operation == "move-box-slot"
    assert resolve_team_pc_drop(
        "pc", "pc", target_occupied=True, team_count=4,
    ).operation == "swap-box-slots"
    assert resolve_team_pc_drop(
        "team", "team", target_occupied=True, team_count=6,
    ).operation is None


def test_drag_hover_repeats_box_changes_at_a_fixed_cadence() -> None:
    class _Widget:
        def __init__(self, left: int, top: int, width: int, height: int) -> None:
            self.bounds = (left, top, width, height)

        def winfo_exists(self) -> bool:
            return True

        def winfo_rootx(self) -> int:
            return self.bounds[0]

        def winfo_rooty(self) -> int:
            return self.bounds[1]

        def winfo_width(self) -> int:
            return self.bounds[2]

        def winfo_height(self) -> int:
            return self.bounds[3]

    class _Frame:
        def __init__(self) -> None:
            self.callback = None
            self.pointer = (125, 20)
            self.delays: list[int] = []

        def after(self, delay: int, callback):
            self.delays.append(int(delay))
            self.callback = callback
            return "hover"

        def after_cancel(self, after_id: str) -> None:
            if after_id == "hover":
                self.callback = None

        def winfo_pointerxy(self) -> tuple[int, int]:
            return self.pointer

        def run_after(self) -> None:
            callback = self.callback
            self.callback = None
            assert callback is not None
            callback()

    view = UnifiedTeamPCView.__new__(UnifiedTeamPCView)
    view.frame = _Frame()
    view._previous_box_button = _Widget(0, 0, 40, 40)
    view._next_box_button = _Widget(100, 0, 40, 40)
    view._drag_box_hover_after_id = None
    view._drag_box_hover_direction = None
    view._drag_started = True
    view._drag_source = ("pc", object())
    changed: list[int] = []
    view._change_box = changed.append
    view._highlight_drop_target = lambda *_args: None

    view._update_drag_box_hover(125, 20)
    assert view.frame.callback is not None
    view.frame.run_after()
    assert changed == [1]

    # Con 31 cajas, un salto por cada entrada en la flecha obligaba a entrar y
    # salir una vez por caja. Se repite solo, a cadencia fija, mientras el
    # puntero siga encima: el movimiento del ratón no reinicia el temporizador.
    assert view.frame.delays == [DRAG_BOX_HOVER_DELAY_MS, DRAG_BOX_HOVER_REPEAT_MS]
    view._update_drag_box_hover(125, 20)
    assert view.frame.delays == [DRAG_BOX_HOVER_DELAY_MS, DRAG_BOX_HOVER_REPEAT_MS]
    view.frame.run_after()
    assert changed == [1, 1]

    # Sacar el puntero de la flecha corta la repetición en seco.
    view._update_drag_box_hover(70, 70)
    assert view.frame.callback is None
    assert changed == [1, 1]

    # Soltar el Pokémon (o cancelar) tampoco deja el temporizador vivo.
    view._update_drag_box_hover(125, 20)
    view._drag_source = None
    view.frame.run_after()
    assert changed == [1, 1]
    assert view.frame.callback is None


def test_drag_continuation_uses_toplevel_bindtag_without_retargeting_pointer() -> None:
    class _EventSurface:
        def __init__(self) -> None:
            self.bindings: list[tuple[str, object, str]] = []
            self.unbindings: list[tuple[str, str]] = []

        def bind(self, sequence: str, callback, add: str):
            binding_id = f"binding-{len(self.bindings)}"
            self.bindings.append((sequence, callback, add))
            return binding_id

        def unbind(self, sequence: str, binding_id: str) -> None:
            self.unbindings.append((sequence, binding_id))

    class _Frame:
        def __init__(self, toplevel: _EventSurface) -> None:
            self.toplevel = toplevel
            self.grab_was_requested = False

        def winfo_toplevel(self) -> _EventSurface:
            return self.toplevel

        def grab_set(self) -> None:
            self.grab_was_requested = True
            raise AssertionError("el arrastre no debe retargetear el puntero")

    surface = _EventSurface()
    frame = _Frame(surface)
    view = UnifiedTeamPCView.__new__(UnifiedTeamPCView)
    view.frame = frame
    view._drag_capture_bindings = []
    view._drag_box_hover_after_id = None
    view._drag_box_hover_direction = None

    view._capture_drag_events()

    assert [entry[0] for entry in surface.bindings] == [
        "<B1-Motion>", "<ButtonRelease-1>",
    ]
    assert all(entry[2] == "+" for entry in surface.bindings)
    assert frame.grab_was_requested is False

    view._release_drag_capture()
    assert surface.unbindings == [
        ("<B1-Motion>", "binding-0"),
        ("<ButtonRelease-1>", "binding-1"),
    ]


def test_tm_flow_accepts_four_full_slots_and_validates_each_replacement() -> None:
    state = TMTeachFlowState(candidates=({
        "move_id": 94,
        "move_name": "Psíquico",
        "valid_slots": (2, 4),
    },))

    state.select_tm(94)
    assert state.step == 2
    try:
        state.select_slot(1)
    except ValueError:
        pass
    else:
        raise AssertionError("Un slot incompatible no puede pasar a previsualización")
    state.select_slot(4)
    assert state.step == 3
    assert state.selected_slot == 4


def test_tm_entry_point_no_longer_constructs_a_ctk_toplevel() -> None:
    assert "CTkToplevel" not in inspect.getsource(RoleRunManager._open_tm_selector)


def test_drag_and_button_route_share_the_existing_pc_team_executor() -> None:
    calls: list[tuple[object, object]] = []
    source = SimpleNamespace(nickname="PC", species="Aipom")
    target = SimpleNamespace(nickname="Equipo", species="Mawile")
    manager = SimpleNamespace(
        _projected_party=lambda: [object()] * 6,
        _team_pc_execute_change=lambda incoming, outgoing, **_kwargs: calls.append((incoming, outgoing)),
        send_pokemon_to_pc=lambda *_args, **_kwargs: None,
        _set_operation_status=lambda *_args, **_kwargs: None,
    )

    RoleRunManager._team_pc_drop(
        manager, "pc", source, "team", {"pokemon": target, "slot_role": "Líbero"},
    )

    assert calls == [(source, target)]


def test_usum_party_drag_preserves_the_exact_pc_drop_destination() -> None:
    calls: list[tuple[object, bool, tuple[int, int] | None]] = []
    source = SimpleNamespace(nickname="Equipo", species="Eevee")
    manager = SimpleNamespace(
        _projected_party=lambda: [object()] * 6,
        _active_azahar_realtime_key=lambda: "usum",
        send_pokemon_to_pc=lambda pokemon, ask=False, destination=None: calls.append(
            (pokemon, ask, destination)
        ),
        _set_operation_status=lambda *_args, **_kwargs: None,
    )

    RoleRunManager._team_pc_drop(
        manager, "team", source, "pc",
        {"pokemon": None, "box": 3, "slot": 4},
    )

    assert calls == [(source, False, (3, 4))]


def test_gen7_compatible_runtime_alias_never_discards_the_exact_pc_drop_destination() -> None:
    calls: list[tuple[object, bool, tuple[int, int] | None]] = []
    source = SimpleNamespace(nickname="Equipo", species="Eevee")
    manager = SimpleNamespace(
        _projected_party=lambda: [object()] * 6,
        # Algunas sesiones Gen 7 compatibles comparten la clave de transporte
        # ``sm``; la capacidad del writer, no el rótulo de la edición, gobierna
        # si el destino exacto puede conservarse.
        _active_azahar_realtime_key=lambda: "sm",
        send_pokemon_to_pc=lambda pokemon, ask=False, destination=None: calls.append(
            (pokemon, ask, destination)
        ),
        _set_operation_status=lambda *_args, **_kwargs: None,
    )

    RoleRunManager._team_pc_drop(
        manager, "team", source, "pc",
        {"pokemon": None, "box": 3, "slot": 4},
    )

    assert calls == [(source, False, (3, 4))]


def test_faint_replacement_uses_only_the_bottom_status_banner() -> None:
    source = inspect.getsource(RoleRunManager._render_team_pc_unified_page)
    assert 'mode_banner = None' in source
    assert '"title": f"SUSTITUCIÓN DE BAJA' not in source


def test_floating_zero_or_empty_slot_uses_a_neutral_track_without_red_progress_cap() -> None:
    source = inspect.getsource(RoleRunManager._render_floating_bar)
    assert "if pokemon is not None and hp_fraction > 0.0:" in source
    assert 'fg_color="#383838", corner_radius=3' in source


def test_inspector_actions_are_reserved_as_a_fixed_footer() -> None:
    source = inspect.getsource(UnifiedTeamPCView._render_inspector)
    footer = source.index('actions.pack(side="bottom"')
    body = source.index('details.pack(fill="both", expand=True')
    assert footer < body


def test_party_drag_routes_to_role_swap_instead_of_physical_reorder() -> None:
    calls: list[tuple[object, str, str]] = []
    source = SimpleNamespace(nickname="Support", species="Shuppet")
    target = SimpleNamespace(nickname="Mago", species="Barboach")
    manager = SimpleNamespace(
        _move_pokemon_to_role_by_drag=lambda pokemon, role, context="main": calls.append(
            (pokemon, role, context)
        ),
    )

    RoleRunManager._team_pc_drop(
        manager, "team", source, "team",
        {"pokemon": target, "slot_role": "Mago"},
    )

    assert calls == [(source, "Mago", "main")]


def test_tm_union_preserves_per_slot_role_validation() -> None:
    candidate = {
        "number": 29, "item_id": 456, "move_id": 94,
        "move_name": "Psíquico", "quantity": 1, "category": "special",
    }
    manager = SimpleNamespace(
        save_engine=SimpleNamespace(key="bdsp"),
        _build_tm_candidates=lambda _pokemon, slot, _profile, _inventory, _ids: (
            [dict(candidate)] if slot in {2, 4} else []
        ),
        _tm_pp_for_profile=lambda _profile, _move_id: 10,
    )

    result = RoleRunManager._tm_flow_candidates(
        manager, object(), object(), {456: 1}, [1, 2, 3, 4],
    )

    assert len(result) == 1
    assert result[0]["valid_slots"] == (2, 4)
    assert result[0]["pp"] == 10


def test_bdsp_move_profile_exposes_proven_power_accuracy_and_game_description() -> None:
    root = [None] * 9
    root[8] = [[85, 85, "WAZAINFO_085", [], [], [], [
        [7, 1, 0, 0, "A strong electric blast crashes down on the target.", 0],
        [0, 7, 0, 0, "This may also leave the target with paralysis.", 0],
    ]]]
    descriptions = _move_descriptions_from_objects({"english_ss_wazainfo": root})
    profile = BDSPTMProfile(
        source=Path("personal_masterdatas"), tms={}, compatibility={},
        move_damage_types={85: 2}, move_base_pp={85: 15}, valid_moves={85},
        move_power={85: 110}, move_accuracy={85: 70},
        move_descriptions=descriptions, description_language="english",
    )

    assert profile.power(85) == 110
    assert profile.accuracy(85) == 70
    assert profile.description(85) == (
        "A strong electric blast crashes down on the target. "
        "This may also leave the target with paralysis."
    )


def test_bdsp_personal_row_uses_the_demonstrated_sheet_order() -> None:
    # SheetPersonal #1 (Bulbasaur): hp/atk/def/spe/spa/spd.
    row = [1, 1, 1, 0, 1, 3, 1, 45, 49, 49, 45, 65, 65]
    assert _personal_base_stats(row) == (45, 49, 49, 65, 65, 45)


def test_role_ev_targets_zero_every_stat_outside_the_role_pair() -> None:
    expected = {
        "Asesino": (0, 252, 0, 0, 0, 252),
        "Mago": (0, 0, 0, 252, 0, 252),
        "Tanque": (252, 0, 252, 0, 0, 0),
        "Prisma": (252, 0, 0, 0, 252, 0),
        "Support": (0, 0, 252, 0, 252, 0),
    }
    for role, evs in expected.items():
        assert RoleRunManager._bdsp_role_evs(role) == evs
    assert RoleRunManager._bdsp_role_evs(
        "Líbero", ("attack", "sp_defense"),
    ) == (0, 252, 0, 0, 252, 0)
    assert RoleRunManager._bdsp_role_evs("Líbero", ("attack",)) is None


def test_usum_same_libero_evs_reach_writer_reconciliation_instead_of_early_return() -> None:
    manager = object.__new__(RoleRunManager)
    manager.project = object()
    manager.current_game = None
    manager._effective_role = lambda _pokemon: ("Líbero", "")
    manager._active_azahar_realtime_key = lambda: "usum"
    calls: list[tuple[str, tuple[str, ...]]] = []
    manager._apply_role_assignment = (
        lambda _pokemon, role, _window=None, **kwargs:
        calls.append((role, tuple(kwargs.get("libero_stats", ()))))
    )
    pokemon = SimpleNamespace(
        role="Líbero",
        evs={
            "hp": 252, "attack": 252, "defense": 0,
            "sp_attack": 0, "sp_defense": 0, "speed": 0,
        },
    )

    RoleRunManager.assign_role(
        manager, pokemon, "Líbero", None, ("hp", "attack"),
    )

    assert calls == [("Líbero", ("hp", "attack"))]


def test_help_and_role_popover_share_one_canonical_role_source() -> None:
    assert set(ROLE_GUIDE) == {"Líbero", "Asesino", "Mago", "Tanque", "Prisma", "Support"}
    assert "máximo de 2 movimientos de daño" in ROLE_GUIDE["Support"]["allowed"]


def test_visual_draft_generation_does_not_consume_the_counter() -> None:
    pokemon = SimpleNamespace(slot=1, nickname="Farigiraf", species="Mawile")
    run = SimpleNamespace(role=None, pokemon_slot=None, draft=None, move_slot=None, pending_changes=[])
    project = SimpleNamespace(counters={"drafteos": 3})
    manager = SimpleNamespace(
        project=project,
        run=run,
        selected_pokemon=None,
        current_results=[],
        engine=SimpleNamespace(
            role_names=lambda: ["Asesino", "Mago", "Tanque", "Prisma", "Support"],
            generate_role=lambda role: [{
                "title": "Pool", "pool_key": role.casefold(), "move_id": 94, "move": "Psíquico",
            }],
        ),
        _team_change_is_locked=lambda show_warning=True: False,
        _effective_role=lambda _pokemon: ("Líbero", "●"),
        _set_operation_status=lambda *_args, **_kwargs: None,
        _draft_transition=lambda: None,
    )

    RoleRunManager._draft_choose_visual_pokemon(manager, pokemon, "Mago")

    assert project.counters["drafteos"] == 3
    assert run.role == "Líbero"
    assert run.pokemon_slot == 1
    assert run.pending_changes == []
    assert manager.current_results[0]["move"] == "Psíquico"


def test_five_draft_results_use_three_top_cards_and_two_centered_bottom_cards() -> None:
    assert _draft_result_layout(5) == [
        (0, 0, 2), (0, 2, 2), (0, 4, 2),
        (1, 1, 2), (1, 3, 2),
    ]


def test_integrated_draft_flow_does_not_create_a_toplevel() -> None:
    assert "CTkToplevel" not in inspect.getsource(IntegratedDraftFlow)


def test_draft_cards_remove_ready_noise_and_expose_richer_context() -> None:
    source = inspect.getsource(IntegratedDraftFlow._render_pokemon_step)

    assert "LISTO" not in source
    assert "nature" in source
    assert "held_item" in source
    assert "moves_for" in source


def test_team_pc_uses_a_narrow_three_column_scrollable_box() -> None:
    pc_shell = inspect.getsource(UnifiedTeamPCView._render_pc_shell)
    pc_grid = inspect.getsource(UnifiedTeamPCView._render_pc_grid)
    inspector = inspect.getsource(UnifiedTeamPCView._render_inspector)

    assert "self.pc_grid = ctk.CTkScrollableFrame" in pc_shell
    assert "CTkScrollableFrame" not in inspector
    assert "for column in range(self.pc_columns)" in pc_shell
    assert "self.pc_columns = 3" in inspect.getsource(UnifiedTeamPCView.__init__)
    assert "for slot in range(1, self.pc_slot_count + 1)" in pc_grid


def test_team_cards_expand_in_six_equal_rows_and_keep_content_inside_border() -> None:
    source = inspect.getsource(UnifiedTeamPCView._render_team)
    card = inspect.getsource(UnifiedTeamPCView._render_team_card)

    assert 'uniform="team_slots"' in source
    assert 'content.grid(row=0, column=0, sticky="nsew", padx=8, pady=5)' in card
    assert "CTkProgressBar" in card
    assert "nature_increased" in card
    assert "nature_decreased" in card
    assert "HABILIDAD" in card
    assert "OBJETO" in card
    assert "pokemon, \"moves\"" in card


def test_draft_party_cards_use_large_portraits_and_structured_move_chips() -> None:
    source = inspect.getsource(IntegratedDraftFlow._render_pokemon_step)

    assert "(112, 112)" in source
    assert "draft_card_moves" in source
    assert "STAT_KEYS" in source
    assert "ivs" in source
    assert "evs" in source
    assert 'text="ELEGIR" if eligible else "EN PREPARACIÓN"' in source


def test_draft_transition_never_fades_the_application_window() -> None:
    source = inspect.getsource(RoleRunManager._draft_transition)

    assert "attributes" not in source
    assert "fade_out" in source
    assert "_draft_fade_in_pending" in source


def test_moves_opened_from_draft_keep_an_explicit_return_route() -> None:
    navigations: list[str] = []
    manager = SimpleNamespace(_moves_return_page=None, navigate=navigations.append)

    RoleRunManager._open_moves_from_draft(manager)

    assert manager._moves_return_page == "drafts"
    assert navigations == ["moves"]


def test_loading_indicator_is_animated_instead_of_a_frozen_message() -> None:
    create = inspect.getsource(RoleRunManager._create_activity_overlay)
    show_busy = inspect.getsource(RoleRunManager._show_busy_indicator)
    show_save = inspect.getsource(RoleRunManager._show_loading_overlay)

    assert "overlay = tk.Toplevel(self)" in create
    assert "if freeze_source:" in create
    assert 'text="ROLERUN\\nMANAGER"' in create
    assert "self._start_navigation_spinner(overlay, snapshot_label)" in create
    assert "CTkProgressBar" not in create
    assert "CenteredLoadingIndicator" not in show_busy
    assert "freeze_source=freeze_source" in show_busy
    assert "content_only=False, independent=True" in show_save


def test_pc_loader_survives_the_body_rebuild_until_the_destination_is_complete() -> None:
    source = inspect.getsource(RoleRunManager._finish_team_pc_load)
    retire = inspect.getsource(RoleRunManager._retire_team_pc_loader_when_ready)

    assert source.index("self._smooth_render_page()") < source.index(
        "self._retire_team_pc_loader_when_ready(data)"
    )
    assert "stable_frames >= 3" in retire
    assert 'getattr(view, "pc_box_count"' in retire


def test_pc_loader_retires_only_after_three_confirmed_final_frames() -> None:
    hidden: list[str] = []
    frame = SimpleNamespace(winfo_width=lambda: 1200, winfo_height=lambda: 700)
    manager = SimpleNamespace(
        _body_swap_in_progress=False,
        _team_pc_view=SimpleNamespace(frame=frame, pc_box_count=40),
        _widget_alive=lambda widget: widget is frame,
        _hide_busy_indicator=hidden.append,
        _finish_initial_shell_reveal=lambda _overlay: hidden.append("initial-shell"),
        _reveal_initial_shell_behind_overlay=lambda _overlay: None,
        _set_operation_status=lambda *_args, **_kwargs: None,
    )
    manager.after = lambda _delay, callback: callback()
    manager._retire_team_pc_loader_when_ready = lambda data, attempt=0, stable_frames=0: (
        RoleRunManager._retire_team_pc_loader_when_ready(
            manager, data, attempt, stable_frames,
        )
    )

    manager._retire_team_pc_loader_when_ready(SimpleNamespace(box_count=40))

    assert hidden == ["pc-load"]


def test_una_escritura_verificada_ya_no_tapa_la_aplicacion() -> None:
    """La escritura viva no levanta la superficie opaca sobre ``content``.

    Esa superficie era literalmente lo que obligaba al usuario a esperar de pie
    los segundos de escritura + verificación. La actividad se comunica ahora por
    la barra inferior y por la cola, que informan sin secuestrar la ventana. El
    ``hide_busy`` del final se conserva solo por compatibilidad: un flujo
    anterior pudo dejar puesta la superficie y no debe quedarse.
    """
    start = inspect.getsource(RoleRunManager._save_oras_live_changes)
    finish = inspect.getsource(RoleRunManager._finish_oras_live_write)

    assert '_show_busy_indicator(' not in start
    assert 'hide_busy("live-write")' in finish


def test_un_cambio_durante_una_escritura_se_encola_en_vez_de_rechazarse() -> None:
    start = inspect.getsource(RoleRunManager._save_oras_live_changes)

    assert "_encolar_cambios_en_vivo(" in start
    assert "_cola_debe_esperar()" in start
    # El bombeo es el ÚNICO punto que saca trabajos de la cola.
    bombeo = inspect.getsource(RoleRunManager._bombear_cola_de_cambios)
    assert "cola.siguiente()" in bombeo
    assert "desde_cola=True" in bombeo


def test_tm_inventory_io_for_every_realtime_game_runs_outside_tk() -> None:
    worker = inspect.getsource(RoleRunManager._start_live_tm_inventory_load)
    selector = inspect.getsource(RoleRunManager._open_tm_selector)

    for key in ("oras", "xy", "sm", "usum", "bdsp"):
        assert f'"{key}"' in worker
    assert "threading.Thread" in worker
    assert 'name=f"RoleRun{engine_key.upper()}TMInventory"' in worker
    assert selector.count("self._start_live_tm_inventory_load(") >= 4


def test_common_header_exposes_all_four_run_counters() -> None:
    source = inspect.getsource(RoleRunManager._build_layout)
    updater = inspect.getsource(RoleRunManager._update_top_status)

    assert "header_run_counters" in source
    assert "header_counter_controls" in source
    for symbol in ("♥", "⚕", "◆", "draft.png"):
        assert symbol in source
    assert 'if key == "medallas"' in source
    assert "self.header_counter_controls[key] = None" in source
    assert "header_counter_labels" in updater
    assert "_counter_is_automatic" in updater


def test_directional_selector_starts_at_first_target_after_clear() -> None:
    selector = SpatialSelection((
        SpatialTarget("second", 0, 1),
        SpatialTarget("first", 0, 0),
    ))

    assert selector.selected_key is None
    assert selector.move("right").key == "first"
    selector.move("right")
    assert selector.selected_key == "second"
    selector.clear()
    assert selector.selected_key is None
    assert selector.move("down").key == "first"


def test_team_pc_directional_selector_crosses_from_team_to_box_and_clears() -> None:
    state = TeamPCSelectionState()
    state.set_team(("libero", "asesino", "mago", "tanque", "prisma", "support"))
    state.set_pc_box(1, range(1, 31))

    assert state.move_direction("down") == ("team", "libero")
    assert state.move_direction("right") == ("pc", 1)
    state.clear()
    assert state.active is False
    assert state.move_direction("left") == ("team", "libero")


def test_integrated_views_bind_arrows_and_configured_accept_back_on_the_toplevel() -> None:
    for view in (UnifiedTeamPCView, IntegratedDraftFlow, IntegratedTMTeachFlow):
        source = inspect.getsource(view._bind_keyboard_navigation)
        for key in ("Left", "Right", "Up", "Down", "keypress_sequences", "navigation_keys"):
            assert key in source
        assert "KeyPress-b" not in source
        assert "winfo_toplevel" in source


def test_team_vertical_navigation_visits_all_six_roles_without_skips() -> None:
    state = TeamPCSelectionState()
    identities = ("libero", "asesino", "mago", "tanque", "prisma", "support")
    state.set_team(identities)
    state.set_pc_box(1, range(1, 31))

    visited = [state.move_direction("down")[1]]
    for _ in range(5):
        visited.append(state.move_direction("down")[1])

    assert tuple(visited) == identities


def test_bdsp_draft_metadata_uses_the_active_waza_and_message_profile() -> None:
    profile = SimpleNamespace(
        base_pp=lambda _move_id: 10,
        power=lambda _move_id: 90,
        accuracy=lambda _move_id: 100,
        description=lambda _move_id: "The target is hit by a strong force.",
        description_language="english",
    )
    manager = SimpleNamespace(
        save_engine=SimpleNamespace(key="bdsp"),
        _get_bdsp_tm_profile=lambda prompt=False: profile,
        _damage_class_for_move=lambda _move_id: "special",
        sm_live_move_pp={}, oras_live_move_pp={},
    )

    metadata = RoleRunManager._draft_move_metadata(manager, 94)

    assert metadata == {
        "category": "special", "pp": 10, "power": 90, "accuracy": 100,
        "description": "EN · The target is hit by a strong force.",
    }


def test_gen7_draft_metadata_publishes_versioned_power_accuracy_and_description() -> None:
    manager = SimpleNamespace(
        save_engine=SimpleNamespace(key="sm"),
        gen7_move_metadata={280: {
            "pp": 15, "power": 75, "accuracy": 100,
            "description_es": "Destruye barreras como Pantalla de Luz.",
        }},
        sm_live_move_pp={280: 15}, oras_live_move_pp={},
        _damage_class_for_move=lambda _move_id: "physical",
    )

    metadata = RoleRunManager._draft_move_metadata(manager, 280)

    assert metadata == {
        "category": "physical", "pp": 15, "power": 75, "accuracy": 100,
        "description": "Destruye barreras como Pantalla de Luz.",
    }


def test_xy_draft_metadata_uses_xy_values_instead_of_the_gen7_table() -> None:
    manager = SimpleNamespace(
        save_engine=SimpleNamespace(key="xy"),
        xy_move_metadata={33: {
            "pp": 35, "power": 50, "accuracy": 100,
            "description_es": "Embiste con todo el cuerpo.",
        }},
        gen7_move_metadata={33: {"pp": 35, "power": 40, "accuracy": 100}},
        sm_live_move_pp={}, oras_live_move_pp={33: 35},
        _damage_class_for_move=lambda _move_id: "physical",
    )

    metadata = RoleRunManager._draft_move_metadata(manager, 33)

    assert metadata == {
        "category": "physical", "pp": 35, "power": 50, "accuracy": 100,
        "description": "Embiste con todo el cuerpo.",
    }


def test_help_discover_format_is_integrated_in_the_main_window() -> None:
    assert "CTkToplevel" not in inspect.getsource(RoleRunManager._open_what_is_rolerun)
    assert "_show_help_section" in inspect.getsource(RoleRunManager._open_what_is_rolerun)


def test_faint_replacement_picker_is_integrated_in_team_and_pc() -> None:
    source = inspect.getsource(RoleRunManager._open_faint_replacement_picker)
    assert "CTkToplevel" not in source
    assert "_faint_replacement_mode" in source
    assert "mark_detected_faint_prompt_shown" in source


def test_closing_integrated_faint_picker_keeps_the_persisted_event() -> None:
    pending = {"identity": "dead-1", "battle_ended": True, "prompt_shown": True}
    scheduled: list[int] = []
    statuses: list[tuple[str, str, tuple[str, ...]]] = []
    manager = SimpleNamespace(
        project=SimpleNamespace(pending_faints=[pending]),
        active_page="team",
        _faint_replacement_mode={"identity": "dead-1"},
        _oras_faint_picker_event_identity="dead-1",
        _set_auto_floating_guard_temporarily=lambda _delay: None,
        _smooth_render_page=lambda **_kwargs: None,
        _set_operation_status=lambda kind, title, _detail, **kwargs: statuses.append(
            (kind, title, tuple(kwargs.get("actions", ())))
        ),
        _schedule_pending_faint_picker=lambda delay: scheduled.append(int(delay)),
    )

    RoleRunManager._dismiss_integrated_faint_picker(manager)

    assert manager.project.pending_faints == [pending]
    assert manager._faint_replacement_mode is None
    assert statuses[-1] == (
        "warning", "BAJA PENDIENTE", ("Elegir sustituto", "No sustituir"),
    )
    assert scheduled == [650]


def test_faint_being_applied_is_not_offered_for_reopening() -> None:
    event = {"identity": "dead-1", "battle_ended": True, "prompt_shown": True}
    manager = SimpleNamespace(
        project=SimpleNamespace(pending_faints=[event]),
        run=SimpleNamespace(pending_changes=[PendingTeamChange(
            operation="replace-fainted",
            party_slot=1,
            box=2,
            box_slot=3,
            outgoing_pokemon="Porygon",
            incoming_pokemon="Eevee",
            outgoing_identity="dead-1",
        )]),
    )

    assert RoleRunManager._pending_faint_for_reopen(manager) is None


def test_integrated_faint_flow_builds_the_existing_verified_change_model() -> None:
    event = {"identity": "dead-1", "pokemon": "Porygon", "role": "Support"}
    dead = SimpleNamespace(
        slot=2, nickname="Porygon", species="Porygon",
        evs={
            "hp": 0, "attack": 0, "defense": 252,
            "sp_attack": 0, "sp_defense": 252, "speed": 0,
        },
    )
    incoming = SimpleNamespace(
        box=3, box_slot=7, slot=7, nickname="Eevee", species="Eevee",
    )
    requested: list[set[int]] = []
    manager = SimpleNamespace(
        project=object(),
        save_engine=SimpleNamespace(key="usum"),
        current_game=object(),
        run=SimpleNamespace(pending_changes=[]),
        _faint_replacement_mode={
            "identity": "dead-1", "event": event, "dead": dead,
            "pc_data": object(), "role": "Support", "symbol": "◆",
        },
        _oras_faint_picker_event_identity="dead-1",
        _oras_live_death_replacement_ids=set(),
        _pending_faint_party_member=lambda _event: dead,
        _projected_open_pc_slots=lambda _data: [(4, 5), (6, 1)],
        _effective_role=lambda _pokemon: ("Support", "◆"),
        _role_symbol=lambda _role: "◆",
        _incoming_snapshot_for_role=lambda _pokemon, role, _slots: {"role": role},
        _bdsp_role_evs=RoleRunManager._bdsp_role_evs,
        _pokemon_snapshot=lambda _pokemon: {"species": "Porygon"},
        _pokemon_identity=lambda pokemon: "incoming-1" if pokemon is incoming else "dead-1",
        _pc_role_witnesses=lambda _pokemon: [{"box": 3, "slot": 7}],
        _set_operation_status=lambda *_args, **_kwargs: None,
        _update_top_status=lambda: None,
        active_page="team",
        _smooth_render_page=lambda **_kwargs: None,
        _request_oras_live_auto_apply_since=lambda before: requested.append(set(before)),
        sync_status="",
    )
    assert RoleRunManager._prepare_faint_replacement(manager, incoming) is True

    change = manager.run.pending_changes[0]
    assert isinstance(change, PendingTeamChange)
    assert change.operation == "replace-fainted"
    assert (change.box, change.box_slot) == (3, 7)
    assert (change.graveyard_box, change.graveyard_box_slot) == (4, 5)
    assert change.incoming_role == "Support"
    assert change.incoming_snapshot["evs"] == {
        "hp": 0, "attack": 0, "defense": 252,
        "sp_attack": 0, "sp_defense": 252, "speed": 0,
    }
    assert change.outgoing_identity == "dead-1"
    assert manager._faint_replacement_mode is None
    assert requested == [set()]


def test_sm_integrated_faint_flow_prepares_inherited_role_evs() -> None:
    event = {"identity": "dead-sm", "pokemon": "Yungoos", "role": "Tanque"}
    dead = SimpleNamespace(
        slot=4, nickname="Yungoos", species="Yungoos",
        evs={
            "hp": 252, "attack": 0, "defense": 252,
            "sp_attack": 0, "sp_defense": 0, "speed": 0,
        },
    )
    incoming = SimpleNamespace(
        box=2, box_slot=3, slot=3, nickname="Pikipek", species="Pikipek",
    )
    manager = SimpleNamespace(
        project=object(), save_engine=SimpleNamespace(key="sm"), current_game=object(),
        run=SimpleNamespace(pending_changes=[]),
        _faint_replacement_mode={
            "identity": "dead-sm", "event": event, "dead": dead,
            "pc_data": object(), "role": "Tanque", "symbol": "♥",
        },
        _oras_faint_picker_event_identity="dead-sm",
        _oras_live_death_replacement_ids=set(),
        _pending_faint_party_member=lambda _event: dead,
        _projected_open_pc_slots=lambda _data: [(4, 2)],
        _effective_role=lambda _pokemon: ("Tanque", "♥"),
        _role_symbol=lambda _role: "♥",
        _incoming_snapshot_for_role=lambda _pokemon, role, _slots: {"role": role},
        _bdsp_role_evs=RoleRunManager._bdsp_role_evs,
        _pokemon_snapshot=lambda _pokemon: {"species": "Yungoos"},
        _pokemon_identity=lambda pokemon: "incoming-sm" if pokemon is incoming else "dead-sm",
        _pc_role_witnesses=lambda _pokemon: [{"box": 2, "slot": 3}],
        _set_operation_status=lambda *_args, **_kwargs: None,
        _update_top_status=lambda: None,
        active_page="team", _smooth_render_page=lambda **_kwargs: None,
        _request_oras_live_auto_apply_since=lambda _before: None, sync_status="",
    )

    assert RoleRunManager._prepare_faint_replacement(manager, incoming) is True
    assert manager.run.pending_changes[0].incoming_snapshot["evs"] == {
        "hp": 252, "attack": 0, "defense": 252,
        "sp_attack": 0, "sp_defense": 0, "speed": 0,
    }


@pytest.mark.parametrize("backend_key", ["bdsp", "sm", "usum"])
def test_realtime_faint_libero_waits_for_a_fresh_ev_choice(backend_key: str) -> None:
    event = {"identity": "dead-libero", "pokemon": "Decidueye", "role": "Líbero"}
    dead = SimpleNamespace(
        slot=0, nickname="Decidueye", species="Decidueye",
        evs={
            "hp": 252, "attack": 0, "defense": 0,
            "sp_attack": 0, "sp_defense": 0, "speed": 252,
        },
    )
    incoming = SimpleNamespace(
        box=1, box_slot=2, slot=2, nickname="Pikipek", species="Pikipek",
    )
    prompts: list[tuple[object, object, str]] = []
    requested: list[set[int]] = []
    manager = SimpleNamespace(
        project=object(), save_engine=SimpleNamespace(key=backend_key), current_game=object(),
        run=SimpleNamespace(pending_changes=[]),
        _faint_replacement_mode={
            "identity": "dead-libero", "event": event, "dead": dead,
            "pc_data": object(), "role": "Líbero", "symbol": "●",
        },
        _oras_faint_picker_event_identity="dead-libero",
        _oras_live_death_replacement_ids=set(),
        _pending_faint_party_member=lambda _event: dead,
        _projected_open_pc_slots=lambda _data: [(4, 1)],
        _effective_role=lambda _pokemon: ("Líbero", "●"),
        _role_symbol=lambda _role: "●",
        _floating_bar_is_visible=lambda: True,
        _prompt_libero_ev_stats=lambda pokemon, callback, context="main": prompts.append(
            (pokemon, callback, context)
        ),
        _incoming_snapshot_for_role=lambda _pokemon, role, _slots: {"role": role},
        _bdsp_role_evs=RoleRunManager._bdsp_role_evs,
        _pokemon_snapshot=lambda _pokemon: {"species": "Decidueye"},
        _pokemon_identity=lambda pokemon: "incoming-libero" if pokemon is incoming else "dead-libero",
        _pc_role_witnesses=lambda _pokemon: [{"box": 1, "slot": 2}],
        _set_operation_status=lambda *_args, **_kwargs: None,
        _update_top_status=lambda: None,
        active_page="team", _smooth_render_page=lambda **_kwargs: None,
        _request_oras_live_auto_apply_since=lambda before: requested.append(set(before)),
        sync_status="",
    )
    manager._prepare_faint_replacement = lambda pokemon, **kwargs: (
        RoleRunManager._prepare_faint_replacement(manager, pokemon, **kwargs)
    )

    assert RoleRunManager._prepare_faint_replacement(manager, incoming) is True
    assert manager.run.pending_changes == []
    assert manager._faint_replacement_mode is not None
    assert requested == []
    assert len(prompts) == 1
    assert prompts[0][0] is incoming
    assert prompts[0][2] == "floating"

    prompts[0][1](("attack", "sp_attack"))

    change = manager.run.pending_changes[0]
    assert change.incoming_snapshot["evs"] == {
        "hp": 0, "attack": 252, "defense": 0,
        "sp_attack": 252, "sp_defense": 0, "speed": 0,
    }
    assert manager._faint_replacement_mode is None
    assert requested == [set()]


def test_only_floating_surfaces_and_technical_drag_create_system_toplevels() -> None:
    constructors = [
        line.strip() for line in inspect.getsource(RoleRunManager).splitlines()
        if "= ctk.CTkToplevel(" in line
    ]
    assert constructors == [
        "ghost = ctk.CTkToplevel(self)",
        "bar = ctk.CTkToplevel(self)",
        "launcher = ctk.CTkToplevel(bar)",
        "window = ctk.CTkToplevel(bar)",
    ]


def test_explorer_target_selects_files_and_opens_directories(tmp_path: Path) -> None:
    folder = tmp_path / "Runs"
    folder.mkdir()
    save = folder / "main"
    save.write_bytes(b"save")

    file_target = resolve_explorer_target(save)
    folder_target = resolve_explorer_target(folder)

    assert file_target.exists is True
    assert file_target.select_file is True
    assert file_target.open_path == folder
    assert folder_target.exists is True
    assert folder_target.select_file is False
    assert folder_target.open_path == folder


def test_explorer_target_rejects_missing_paths(tmp_path: Path) -> None:
    target = resolve_explorer_target(tmp_path / "missing")
    assert target.exists is False
    assert target.open_path is None


def test_role_icons_preserve_supplied_alpha_and_apply_only_the_gold_tint() -> None:
    folder = Path(__file__).resolve().parents[1] / "resources" / "role_icons"
    provider = RoleIconProvider(folder, "#C9A45C")

    assert set(ROLE_ICON_FILES) == {
        "Líbero", "Asesino", "Mago", "Tanque", "Prisma", "Support",
    }
    for role, filename in ROLE_ICON_FILES.items():
        assert (folder / filename).is_file()
        rendered = provider.pil_image(role, 32)
        assert rendered is not None
        assert rendered.size == (32, 32)
        assert rendered.getchannel("A").getbbox() is not None
        visible_rgb = {
            pixel[:3] for pixel in rendered.get_flattened_data() if pixel[3] > 0
        }
        assert visible_rgb == {(201, 164, 92)}


def test_minimizing_role_run_switches_to_floating_mode() -> None:
    """La barra flotante solo tiene sentido con el emulador en primer plano:
    sin él (cerrado, o minimizando hacia otra ventana) no hay nada del juego
    sobre lo que superponerse.
    """
    actions: list[str] = []
    manager = SimpleNamespace(
        _unmap_after_id="pending",
        state=lambda: "iconic",
        current_game=object(),
        _faint_picker_blocks_floating=lambda: False,
        _foreground_is_supported_emulator=lambda: True,
        # No es la minimizacion que hace el sondeo al esconder la barra porque
        # algo tapa el juego: esa no debe reabrirla.
        _barra_oculta_por_tapado=False,
        open_floating_bar=lambda: actions.append("floating"),
        _restore_main_window_maximized=lambda: actions.append("maximized"),
    )

    RoleRunManager._auto_float_if_minimized(manager)

    assert manager._unmap_after_id is None
    assert actions == ["floating"]


def test_minimizing_role_run_without_the_emulator_in_foreground_does_not_float() -> None:
    """El caso reportado: minimizar sin el emulador abierto entraba en modo
    barra flotante igual, aunque no hubiera nada sobre lo que superponerse.

    Reportado de nuevo tras el primer arreglo: forzar la ventana de vuelta en
    este caso la reabría al instante, justo tras pulsar minimizar. Sin
    emulador en primer plano, minimizar se deja como un minimizado normal —
    ni barra flotante ni ventana principal forzadas.
    """
    actions: list[str] = []
    manager = SimpleNamespace(
        _unmap_after_id="pending",
        state=lambda: "iconic",
        current_game=object(),
        _faint_picker_blocks_floating=lambda: False,
        _foreground_is_supported_emulator=lambda: False,
        _barra_oculta_por_tapado=False,
        open_floating_bar=lambda: actions.append("floating"),
        _restore_main_window_maximized=lambda: actions.append("maximized"),
    )

    RoleRunManager._auto_float_if_minimized(manager)

    assert manager._unmap_after_id is None
    assert actions == []


def test_minimizing_role_run_without_an_active_run_still_restores() -> None:
    """Sin Run activa no hay nada que gestionar en segundo plano: dejar
    RoleRun escondido en la barra de tareas sigue sin tener sentido.
    """
    actions: list[str] = []
    manager = SimpleNamespace(
        _unmap_after_id="pending",
        state=lambda: "iconic",
        current_game=None,
        _faint_picker_blocks_floating=lambda: False,
        _foreground_is_supported_emulator=lambda: False,
        _barra_oculta_por_tapado=False,
        open_floating_bar=lambda: actions.append("floating"),
        _restore_main_window_maximized=lambda: actions.append("maximized"),
    )

    RoleRunManager._auto_float_if_minimized(manager)

    assert actions == ["maximized"]


def test_team_card_click_binding_recurses_through_nested_content() -> None:
    source = inspect.getsource(UnifiedTeamPCView._bind_click_tree)

    assert "for child in widget.winfo_children()" in source
    assert "UnifiedTeamPCView._bind_click_tree(child" in source


def test_sidebar_uses_a_timed_slide_and_keeps_a_dedicated_toggle_rail() -> None:
    animation = inspect.getsource(RoleRunManager._animate_sidebar_drawer)
    expansion = inspect.getsource(RoleRunManager._set_sidebar_expanded)
    layout = inspect.getsource(RoleRunManager._build_layout)

    # Se exige que el deslizamiento esté cronometrado y que se anime por
    # fotogramas, no un número concreto. El 260 original no era solo animación:
    # al elegir destino desde el menú, la navegación no arranca hasta que el
    # drawer termina de cerrarse, así que se sumaba entero al camino más usado.
    import re

    duracion = re.search(r"duration_ms = (\d+)", animation)
    assert duracion is not None, "el deslizamiento dejó de estar cronometrado"
    assert 90 <= int(duracion.group(1)) <= 300, (
        f"duración fuera de rango legible: {duracion.group(1)} ms"
    )
    fotograma = re.search(r"self\.after\((\d+), frame\)", animation)
    assert fotograma is not None, "el deslizamiento dejó de animarse por fotogramas"
    assert 4 <= int(fotograma.group(1)) <= 20
    assert "drawer.place_configure(x=x)" in animation
    assert "drawer.place_forget()" in animation
    assert "drawer.lift()" not in animation
    assert 'self.sidebar_drawer = ctk.CTkFrame' in layout
    assert 'self.sidebar_drawer.place(x=-285' in layout
    assert 'self.sidebar_expanded_content.pack(fill="both", expand=True, padx=(0, 30))' in layout
    assert "ImageTk.PhotoImage(capture)" in expansion
    assert "self.sidebar_source_capture = capture.copy()" in expansion
    assert "scrim.place(x=content_x, y=content_y, width=width, height=height)" in expansion
    assert "relwidth=1.0" not in expansion
    assert "sidebar.pack_propagate(False)" in layout


def test_sidebar_navigation_waits_until_the_close_animation_finishes() -> None:
    source = inspect.getsource(RoleRunManager.navigate)
    animation = inspect.getsource(RoleRunManager._animate_sidebar_drawer)

    assert "if sidebar_expanded or sidebar_closing" in source
    assert "self._pending_sidebar_navigation = page" in source
    assert "self.after(235" not in source
    assert 'pending_page = getattr(self, "_pending_sidebar_navigation", None)' in animation
    assert "self._navigation_source_capture = self.sidebar_source_capture" in animation
    assert "self.navigate(pending_page)" in animation
    assert source.index("return") < source.index("previous_page = self.active_page")


def test_selecting_the_visible_page_does_not_rebuild_it() -> None:
    transitions: list[tuple[str, str]] = []
    close_requests: list[bool] = []
    manager = SimpleNamespace(
        _cancel_help_animations=lambda: None,
        sidebar_expanded=False,
        sidebar_animation_id=None,
        _pending_sidebar_navigation=None,
        _set_sidebar_expanded=lambda expanded: close_requests.append(bool(expanded)),
        _moves_return_page="drafts",
        active_page="team",
        _begin_page_navigation=lambda page, previous: transitions.append((page, previous)),
    )

    RoleRunManager.navigate(manager, "team")

    assert close_requests == [False]
    assert transitions == []
    assert manager.active_page == "team"
    assert manager._navigation_source_capture is None


def test_navigation_uses_an_independent_composited_surface() -> None:
    create = inspect.getsource(RoleRunManager._create_navigation_transition)
    begin = inspect.getsource(RoleRunManager._begin_page_navigation)
    fade = inspect.getsource(RoleRunManager._fade_navigation_transition)

    assert "overlay = tk.Toplevel(self)" in create
    assert "overlay.overrideredirect(True)" in create
    assert "ImageGrab.grab" in create
    assert 'getattr(self, "_navigation_source_capture", None)' in create
    assert "capture = cached_capture.copy().convert(\"RGB\")" in create
    assert "ImageEnhance.Brightness(capture).enhance(0.42)" in create
    assert "self._start_navigation_spinner(overlay, snapshot_label)" in create
    assert "self.after(" in begin and "34" in begin
    assert 'overlay.attributes("-alpha", alpha)' in fade
    assert "self.after(16, frame)" in fade


def test_navigation_spinner_keeps_moving_while_tk_builds_the_destination() -> None:
    source = inspect.getsource(RoleRunManager._start_navigation_spinner)
    destroy = inspect.getsource(RoleRunManager._destroy_navigation_transition)
    fade = inspect.getsource(RoleRunManager._fade_navigation_transition)

    assert "threading.Thread(" in source
    assert 'name="RoleRunNavigationSpinner"' in source
    assert "daemon=True" in source
    assert "stop_event.wait(0.055)" in source
    assert "self.after(" not in source
    assert "self._stop_navigation_spinner(target)" in destroy
    assert "self._stop_navigation_spinner(overlay)" in fade


def test_page_swap_keeps_the_previous_surface_until_the_new_one_is_ready() -> None:
    source = inspect.getsource(RoleRunManager._smooth_render_page)
    overlay = inspect.getsource(RoleRunManager._create_page_transition_overlay)

    assert "for view in (old_draft_view, old_team_pc_view)" in source
    assert "suspend = getattr(view, \"suspend_interaction\", None)" in source
    assert source.index("suspend()") < source.index("self.render_page()")
    assert "transition_overlay = self._create_page_transition_overlay()" in source
    assert "self.after(" in source and "140" in source
    assert "ImageGrab.grab" in overlay
    assert "ImageTk.PhotoImage(capture)" in overlay
    assert "self.update()" not in overlay
    assert source.index("self.render_page()") < source.index("_retire_page_transition_overlay")


def test_hidden_initial_shell_commits_its_composed_team_view() -> None:
    source = inspect.getsource(RoleRunManager._smooth_render_page)

    assert "if new_body is None:" in source
    assert "self._presented_team_pc_view = self._team_pc_view" in source
    assert "if new_body is None and not self._initial_shell_waiting" not in source
    assert "if self._initial_shell_waiting:" in source
    assert "self._retire_initial_shell_when_ready()" in source


def test_inspector_integrates_iv_and_ev_beneath_each_stat() -> None:
    source = inspect.getsource(UnifiedTeamPCView._render_inspector)

    assert 'text=str(move)' in source
    assert 'f"{index + 1}. {move}"' not in source
    assert 'text=f"IV {ivs.get(key, \'—\')}"' in source
    assert 'text=f"EV {evs.get(key, \'—\')}"' in source
    assert "pokemon_training" not in source
    assert "for index, key in enumerate(STAT_KEYS)" in source


def test_team_cards_place_all_four_moves_on_one_row() -> None:
    source = inspect.getsource(UnifiedTeamPCView._render_team_card)

    assert "grid_columnconfigure((0, 1, 2, 3)" in source
    assert ".grid(row=0, column=index" in source


def test_role_tooltip_is_anchored_to_its_button() -> None:
    source = inspect.getsource(UnifiedTeamPCView._show_role_tooltip)

    assert 'tooltip.place(in_=button, relx=0.5, y=-5, anchor="s")' in source
    assert "winfo_rootx" not in source


def test_first_draft_step_has_no_close_control_and_later_steps_return_home() -> None:
    source = inspect.getsource(IntegratedDraftFlow._render_header)

    assert 'if self.step > 1:' in source
    assert 'text="←"' in source
    assert 'command=self.on_cancel' in source
    assert 'text="×"' not in source


def test_team_pc_drag_ghost_uses_an_independent_native_window() -> None:
    source = inspect.getsource(UnifiedTeamPCView._move_drag)

    assert "tk.Toplevel(self.frame)" in source
    assert "overrideredirect(True)" in source
    assert "self._drag_ghost.geometry(" in source
    assert "self._drag_ghost.place(" not in source


def test_save_open_keeps_its_barrier_until_the_first_pc_read_finishes() -> None:
    select = inspect.getsource(RoleRunManager.select_save)
    source = inspect.getsource(RoleRunManager._finish_save_load)

    assert "pc_data = self.save_engine.read_boxes(info.path)" in select
    assert source.index("self._pc_cache = pc_data") < source.index("self._enter_app_shell()")
    assert "self._busy_indicator = loading_overlay" in source
    assert "self._sync_activity_overlay_geometry(loading_overlay)" in source
    assert source.index("self._enter_app_shell()") < source.index("self.render_page()")
    assert source.index("self.render_page()") < source.index(
        "self._busy_indicator = loading_overlay"
    )


def test_activity_overlay_tracks_the_final_shell_geometry() -> None:
    geometries: list[str] = []
    lifts: list[bool] = []
    surface = SimpleNamespace(
        winfo_width=lambda: 1376,
        winfo_height=lambda: 899,
        winfo_rootx=lambda: 78,
        winfo_rooty=lambda: 78,
    )
    overlay = SimpleNamespace(
        _rolerun_surface=surface,
        geometry=geometries.append,
        lift=lambda: lifts.append(True),
    )
    manager = SimpleNamespace(
        _widget_alive=lambda widget: widget in (overlay, surface),
        update_idletasks=lambda: None,
        _foreground_belongs_to_this_process=lambda: True,
    )

    assert RoleRunManager._sync_activity_overlay_geometry(manager, overlay) is True
    assert geometries == ["1376x899+78+78"]
    assert lifts == [True]
    assert overlay._rolerun_surface_geometry == "1376x899+78+78"


def test_activity_overlay_does_not_lift_when_the_user_left_to_another_window() -> None:
    """Hallazgo del usuario 31-08-2026: la barrera de carga es "-topmost", así
    que un `lift()` la trae por delante de CUALQUIER ventana, incluso de otro
    proceso. Si el usuario ya se fue al emulador mientras carga, no debe
    "reaparecer" sobre lo que esté mirando."""
    geometries: list[str] = []
    lifts: list[bool] = []
    surface = SimpleNamespace(
        winfo_width=lambda: 1376,
        winfo_height=lambda: 899,
        winfo_rootx=lambda: 78,
        winfo_rooty=lambda: 78,
    )
    overlay = SimpleNamespace(
        _rolerun_surface=surface,
        geometry=geometries.append,
        lift=lambda: lifts.append(True),
    )
    manager = SimpleNamespace(
        _widget_alive=lambda widget: widget in (overlay, surface),
        update_idletasks=lambda: None,
        _foreground_belongs_to_this_process=lambda: False,
    )

    assert RoleRunManager._sync_activity_overlay_geometry(manager, overlay) is True
    assert geometries == ["1376x899+78+78"]
    assert lifts == []


def test_initial_shell_barrier_requires_pc_layout_and_first_live_probe() -> None:
    hidden: list[str] = []
    callbacks: list[object] = []
    health = SimpleNamespace(party=[SimpleNamespace(current_hp=59, max_hp=59)])
    signature = RoleRunManager._party_health_signature(health)
    view = SimpleNamespace(
        is_fully_composed=lambda boxes: boxes == 40,
        _source_health_signature=signature,
        rendered_team_health_signature=signature,
        frame=SimpleNamespace(winfo_width=lambda: 1760, winfo_height=lambda: 760),
        team_panel=SimpleNamespace(winfo_width=lambda: 780),
        pc_panel=SimpleNamespace(winfo_width=lambda: 340),
        inspector_panel=SimpleNamespace(winfo_width=lambda: 560),
    )
    manager = SimpleNamespace(
        _initial_shell_waiting=True,
        _initial_shell_live_probe_complete=False,
        _initial_shell_pc_data=SimpleNamespace(box_count=40),
        _body_swap_in_progress=False,
        _team_pc_view=view,
        _presented_team_pc_view=view,
        current_game=health,
        _party_health_signature=RoleRunManager._party_health_signature,
        _hide_busy_indicator=hidden.append,
        _finish_initial_shell_reveal=lambda _overlay: hidden.append("initial-shell"),
        _reveal_initial_shell_behind_overlay=lambda _overlay: None,
        _widget_alive=lambda _widget: False,
        _sync_activity_overlay_geometry=lambda _widget: False,
        _record_bdsp_ui_event=lambda *_args, **_kwargs: None,
        _publish_initial_shell=lambda _overlay: hidden.append("initial-shell"),
        winfo_width=lambda: 1920,
        winfo_height=lambda: 1040,
        after=lambda _delay, callback: callbacks.append(callback),
    )
    manager._retire_initial_shell_when_ready = lambda attempt=0: (
        RoleRunManager._retire_initial_shell_when_ready(manager, attempt)
    )

    _preparar_barrera(manager)
    RoleRunManager._retire_initial_shell_when_ready(manager)
    assert hidden == []
    assert callbacks

    manager._initial_shell_live_probe_complete = True
    RoleRunManager._retire_initial_shell_when_ready(manager)
    assert hidden == []
    assert manager._initial_shell_reveal_phase == "mapping"
    for _index in range(4):
        callbacks[-1]()
    assert hidden == ["initial-shell"]
    assert manager._initial_shell_waiting is False


def test_initial_shell_keeps_the_loader_until_dwm_presents_the_final_root() -> None:
    source = inspect.getsource(RoleRunManager._retire_initial_shell_when_ready)
    publish = inspect.getsource(RoleRunManager._publish_initial_shell)

    reveal = source.index("self._reveal_initial_shell_behind_overlay(indicator)")
    stable = source.index("self._initial_shell_stable_polls < 4")
    final_publish = source.index("self._publish_initial_shell(indicator)")
    assert reveal < stable < final_publish
    assert "self.after(" in publish and "260" in publish
    assert "self._finish_initial_shell_reveal(barrier)" in publish


def test_initial_loader_stays_windowed_and_does_not_monopolize_desktop() -> None:
    create = inspect.getsource(RoleRunManager._create_activity_overlay)
    reveal = inspect.getsource(RoleRunManager._reveal_initial_shell_behind_overlay)

    assert 'overlay.state("zoomed")' not in create
    assert 'overlay.attributes("-topmost", False)' in create
    assert 'self.state("zoomed")' in reveal
    assert "self._force_native_main_maximize(" in reveal
    assert "steal_foreground=self._foreground_belongs_to_this_process()" in reveal
    assert 'self.attributes("-fullscreen", True)' not in reveal
    assert 'overlay.attributes("-topmost", True)' not in reveal


def test_main_and_initial_loader_start_centered_on_windows_screen() -> None:
    manager = SimpleNamespace(
        winfo_screenwidth=lambda: 1920,
        winfo_screenheight=lambda: 1080,
    )
    assert RoleRunManager._centered_geometry(manager, 1360, 860) == (
        "1360x860+280+110"
    )
    init = inspect.getsource(RoleRunManager.__init__)
    assert "self.geometry(self._centered_geometry(1360, 860))" in init


def test_initial_shell_rejects_a_composed_view_with_stale_health() -> None:
    hidden: list[str] = []
    callbacks: list[object] = []
    disk = SimpleNamespace(party=[SimpleNamespace(current_hp=0, max_hp=0)])
    live = SimpleNamespace(party=[SimpleNamespace(current_hp=59, max_hp=59)])
    view = SimpleNamespace(
        is_fully_composed=lambda _boxes: True,
        # El modelo entregado puede ser live aunque las tarjetas hayan
        # materializado todavía la proyección provisional del save.
        _source_health_signature=RoleRunManager._party_health_signature(live),
        rendered_team_health_signature=RoleRunManager._party_health_signature(disk),
    )
    manager = SimpleNamespace(
        _initial_shell_waiting=True,
        _initial_shell_live_probe_complete=True,
        _initial_shell_pc_data=SimpleNamespace(box_count=40),
        _body_swap_in_progress=False,
        _team_pc_view=view,
        _presented_team_pc_view=view,
        current_game=live,
        _party_health_signature=RoleRunManager._party_health_signature,
        _hide_busy_indicator=hidden.append,
        _reveal_initial_shell_behind_overlay=lambda _overlay: None,
        _widget_alive=lambda _widget: False,
        _sync_activity_overlay_geometry=lambda _widget: False,
        _record_bdsp_ui_event=lambda *_args, **_kwargs: None,
        after=lambda _delay, callback: callbacks.append(callback),
    )

    _preparar_barrera(manager)
    RoleRunManager._retire_initial_shell_when_ready(manager)

    assert hidden == []
    assert callbacks


def test_initial_shell_compares_the_projected_party_after_pending_faints() -> None:
    callbacks: list[object] = []
    physical = [
        SimpleNamespace(species_id=655, current_hp=285, max_hp=286),
        SimpleNamespace(species_id=664, current_hp=0, max_hp=16),
        SimpleNamespace(species_id=664, current_hp=1, max_hp=13),
        SimpleNamespace(species_id=664, current_hp=0, max_hp=18),
        SimpleNamespace(species_id=664, current_hp=15, max_hp=15),
        SimpleNamespace(species_id=664, current_hp=13, max_hp=13),
    ]
    projected = [physical[index] for index in (0, 2, 4, 5)]
    signature = RoleRunManager._party_health_signature(projected)
    view = SimpleNamespace(
        is_fully_composed=lambda _boxes: True,
        rendered_team_health_signature=signature,
    )
    manager = SimpleNamespace(
        _initial_shell_waiting=True,
        _initial_shell_live_probe_complete=True,
        _initial_shell_pc_data=SimpleNamespace(box_count=31),
        _initial_shell_reveal_phase="hidden",
        _body_swap_in_progress=False,
        _team_pc_view=view,
        _presented_team_pc_view=view,
        current_game=SimpleNamespace(party=physical),
        _projected_party=lambda: projected,
        sprite_pil_cache={655: object(), 664: object()},
        _sprite_refresh_scheduled=False,
        _party_health_signature=RoleRunManager._party_health_signature,
        _widget_alive=lambda _widget: False,
        _sync_activity_overlay_geometry=lambda _widget: False,
        _record_bdsp_ui_event=lambda *_args, **_kwargs: None,
        _reveal_initial_shell_behind_overlay=lambda _overlay: None,
        after=lambda _delay, callback: callbacks.append(callback),
    )

    _preparar_barrera(manager)
    RoleRunManager._retire_initial_shell_when_ready(manager)

    assert manager._initial_shell_reveal_phase == "mapping"
    assert callbacks


def test_sm_initial_shell_waits_for_the_proven_live_pc_matrix() -> None:
    callbacks: list[object] = []
    live = SimpleNamespace(
        party=[SimpleNamespace(species_id=731, current_hp=15, max_hp=15)],
    )
    signature = RoleRunManager._party_health_signature(live)
    view = SimpleNamespace(
        is_fully_composed=lambda _boxes: True,
        rendered_team_health_signature=signature,
    )
    manager = SimpleNamespace(
        _initial_shell_waiting=True,
        _initial_shell_live_probe_complete=True,
        _initial_shell_pc_data=SimpleNamespace(box_count=32, raw={}),
        _initial_shell_reveal_phase="hidden",
        _body_swap_in_progress=False,
        _team_pc_view=view,
        _presented_team_pc_view=view,
        current_game=live,
        sprite_pil_cache={731: object()},
        _sprite_refresh_scheduled=False,
        _party_health_signature=RoleRunManager._party_health_signature,
        _active_azahar_realtime_key=lambda: "sm",
        _widget_alive=lambda _widget: False,
        _sync_activity_overlay_geometry=lambda _widget: False,
        _record_bdsp_ui_event=lambda *_args, **_kwargs: None,
        after=lambda _delay, callback: callbacks.append(callback),
    )

    _preparar_barrera(manager)
    RoleRunManager._retire_initial_shell_when_ready(manager)

    assert manager._initial_shell_reveal_phase == "hidden"
    assert callbacks

    manager._initial_shell_pc_data = SimpleNamespace(
        box_count=32, raw={"live_matrix": True},
    )
    manager._reveal_initial_shell_behind_overlay = lambda _overlay: None
    RoleRunManager._retire_initial_shell_when_ready(manager)
    assert manager._initial_shell_reveal_phase == "mapping"


def test_initial_shell_rejects_a_composed_live_view_not_yet_presented() -> None:
    hidden: list[str] = []
    callbacks: list[object] = []
    live = SimpleNamespace(party=[SimpleNamespace(current_hp=59, max_hp=59)])
    view = SimpleNamespace(
        is_fully_composed=lambda _boxes: True,
        _source_health_signature=RoleRunManager._party_health_signature(live),
        rendered_team_health_signature=RoleRunManager._party_health_signature(live),
    )
    manager = SimpleNamespace(
        _initial_shell_waiting=True,
        _initial_shell_live_probe_complete=True,
        _initial_shell_pc_data=SimpleNamespace(box_count=40),
        _body_swap_in_progress=False,
        _team_pc_view=view,
        _presented_team_pc_view=None,
        current_game=live,
        _party_health_signature=RoleRunManager._party_health_signature,
        _hide_busy_indicator=hidden.append,
        _widget_alive=lambda _widget: False,
        _sync_activity_overlay_geometry=lambda _widget: False,
        _record_bdsp_ui_event=lambda *_args, **_kwargs: None,
        after=lambda _delay, callback: callbacks.append(callback),
    )

    _preparar_barrera(manager)
    RoleRunManager._retire_initial_shell_when_ready(manager)

    assert hidden == []
    assert callbacks


def test_initial_shell_waits_for_party_sprites_and_their_final_refresh() -> None:
    callbacks: list[object] = []
    live = SimpleNamespace(
        party=[SimpleNamespace(species_id=731, current_hp=15, max_hp=15)],
    )
    signature = RoleRunManager._party_health_signature(live)
    view = SimpleNamespace(
        is_fully_composed=lambda _boxes: True,
        rendered_team_health_signature=signature,
    )
    manager = SimpleNamespace(
        _initial_shell_waiting=True,
        _initial_shell_live_probe_complete=True,
        _initial_shell_pc_data=SimpleNamespace(box_count=32),
        _initial_shell_reveal_phase="hidden",
        _body_swap_in_progress=False,
        _team_pc_view=view,
        _presented_team_pc_view=view,
        current_game=live,
        sprite_pil_cache={},
        _sprite_refresh_scheduled=False,
        _party_health_signature=RoleRunManager._party_health_signature,
        _widget_alive=lambda _widget: False,
        _sync_activity_overlay_geometry=lambda _widget: False,
        _record_bdsp_ui_event=lambda *_args, **_kwargs: None,
        after=lambda _delay, callback: callbacks.append(callback),
    )

    _preparar_barrera(manager)
    RoleRunManager._retire_initial_shell_when_ready(manager)

    assert manager._initial_shell_reveal_phase == "hidden"
    assert callbacks

    manager.sprite_pil_cache[731] = object()
    manager._sprite_refresh_scheduled = True
    RoleRunManager._retire_initial_shell_when_ready(manager)
    assert manager._initial_shell_reveal_phase == "hidden"

    manager._sprite_refresh_scheduled = False
    manager._reveal_initial_shell_behind_overlay = lambda _overlay: None
    RoleRunManager._retire_initial_shell_when_ready(manager)
    assert manager._initial_shell_reveal_phase == "mapping"


def test_bdsp_initial_transport_error_keeps_shell_hidden_until_live_health() -> None:
    busy: list[tuple[str, str]] = []
    retries: list[int] = []
    callbacks: list[object] = []
    manager = SimpleNamespace(
        _oras_auto_sync_in_progress=True,
        _oras_auto_sync_token=7,
        _session_generation=3,
        project=SimpleNamespace(slug="sp-test"),
        current_game=object(),
        save_engine=SimpleNamespace(key="bdsp"),
        _oras_live_active=False,
        _initial_shell_waiting=True,
        _initial_shell_live_probe_complete=False,
        _active_azahar_realtime_key=lambda: "bdsp",
        _active_azahar_realtime_label=lambda: "Perla Reluciente",
        _update_top_status=lambda: None,
        _show_busy_indicator=lambda reason, message: busy.append((reason, message)),
        _schedule_oras_initial_auto_sync=retries.append,
        after=lambda _delay, callback: callbacks.append(callback),
    )

    RoleRunManager._finish_oras_initial_auto_sync(
        manager, 3, "sp-test", 7, None, "Ryujinx todavía no está listo",
    )

    assert manager._initial_shell_live_probe_complete is False
    assert busy and busy[-1][0] == "initial-shell"
    assert retries == [1600]
    assert callbacks == []


def test_sm_initial_transport_error_keeps_shell_hidden_until_live_health() -> None:
    busy: list[tuple[str, str]] = []
    retries: list[int] = []
    callbacks: list[object] = []
    manager = SimpleNamespace(
        _oras_auto_sync_in_progress=True,
        _oras_auto_sync_token=7,
        _session_generation=3,
        project=SimpleNamespace(slug="sun-test"),
        current_game=object(),
        save_engine=SimpleNamespace(key="sm"),
        _oras_live_active=False,
        _initial_shell_waiting=True,
        _initial_shell_live_probe_complete=False,
        _active_azahar_realtime_key=lambda: "sm",
        _active_azahar_realtime_label=lambda: "Sol/Luna",
        _update_top_status=lambda: None,
        _show_busy_indicator=lambda reason, message: busy.append((reason, message)),
        _schedule_oras_initial_auto_sync=retries.append,
        after=lambda _delay, callback: callbacks.append(callback),
    )

    RoleRunManager._finish_oras_initial_auto_sync(
        manager, 3, "sun-test", 7, None, "Azahar todavía no está listo",
    )

    assert manager._initial_shell_live_probe_complete is False
    assert busy and busy[-1][0] == "initial-shell"
    assert "Sol/Luna" in busy[-1][1]
    assert retries == [1600]
    assert callbacks == []


def test_initial_health_readiness_rejects_placeholders_and_accepts_valid_faints() -> None:
    unresolved = SaveGameData(
        "SP", "SAV8BS", 8, "Test",
        [_training_test_pokemon(current_hp=0, max_hp=0)], {},
    )
    assert RoleRunManager._party_has_resolved_health(unresolved) is False

    resolved = SaveGameData(
        "SP", "SAV8BS", 8, "Test",
        [_training_test_pokemon(current_hp=0, max_hp=59)], {},
    )
    assert RoleRunManager._party_has_resolved_health(resolved) is True


def test_team_pc_composition_signal_retires_tm_only_for_the_current_view() -> None:
    current = object()
    manager = SimpleNamespace(
        _team_pc_view=current,
        _initial_shell_waiting=False,
    )

    RoleRunManager._team_pc_view_composed(manager, object())
    RoleRunManager._team_pc_view_composed(manager, current)


def test_activity_message_has_a_fixed_erasable_surface() -> None:
    create = inspect.getsource(RoleRunManager._create_activity_overlay)
    update = inspect.getsource(RoleRunManager._update_activity_overlay_message)

    assert "width=54" in create
    assert 'anchor="center"' in create
    assert "label.update_idletasks()" in update
    assert "if freeze_source:" in create
    assert 'background="#151515"' in create


def test_opening_shell_preserves_the_original_loading_toplevel() -> None:
    source = inspect.getsource(RoleRunManager._clear_root)

    assert 'protected_overlay = getattr(self, "_loading_overlay", None)' in source
    assert "if child is protected_overlay" in source
    assert source.index("if child is protected_overlay") < source.index("child.destroy()")


def test_closing_tm_destroys_its_bindings_behind_an_independent_barrier() -> None:
    source = inspect.getsource(RoleRunManager._open_integrated_tm_flow)

    assert '"Volviendo a Movimientos…" if return_page == "tms" else "Volviendo a Equipo y PC…"' in source
    assert "freeze_source=True" in source
    assert '"tm-flow", "Abriendo el selector de MT…", freeze_source=True' in source
    assert "flow.destroy()" in source
    assert "self._smooth_render_page()" not in source
    assert "self.after_idle(self._retire_tm_close_when_ready)" in source
    assert "self._retire_tm_open_when_ready(self._tm_teach_flow)" in source


def test_tm_close_keeps_the_complete_flow_alive_until_controller_captures_it() -> None:
    events: list[str] = []
    flow = SimpleNamespace(
        frame=SimpleNamespace(winfo_exists=lambda: True),
        on_close=lambda: events.append("controller-captured"),
        destroy=lambda: events.append("destroyed-too-early"),
    )

    result = IntegratedTMTeachFlow._close(flow)

    assert result == "break"
    assert events == ["controller-captured"]


def test_tm_close_no_hace_nada_si_su_frame_ya_no_esta() -> None:
    """`<Escape>` está enganchado al toplevel, no al frame del selector.

    Al navegar a otra página el flujo no se destruye, así que su Escape seguía
    vivo: pulsarlo en otra sección levantaba la barrera de «Volviendo a…» sobre
    una página que nunca había abierto ningún selector, y esa barrera podía
    quedarse para siempre.
    """
    events: list[str] = []
    flow = SimpleNamespace(
        frame=SimpleNamespace(winfo_exists=lambda: False),
        on_close=lambda: events.append("no-deberia"),
        destroy=lambda: events.append("no-deberia"),
    )

    assert IntegratedTMTeachFlow._close(flow) == "break"
    assert events == []


def test_tm_destroy_releases_bindings_and_removes_its_frame() -> None:
    events: list[str] = []
    top = SimpleNamespace(unbind=lambda *_args: events.append("escape-unbound"))
    frame = SimpleNamespace(
        winfo_toplevel=lambda: top,
        winfo_exists=lambda: True,
        destroy=lambda: events.append("frame-destroyed"),
    )
    flow = SimpleNamespace(
        _release_keyboard_navigation=lambda: events.append("keys-released"),
        _escape_binding="escape-id",
        frame=frame,
    )

    IntegratedTMTeachFlow.destroy(flow)

    assert events == ["keys-released", "escape-unbound", "frame-destroyed"]


def test_busy_operation_does_not_stack_a_second_page_transition_capture() -> None:
    source = inspect.getsource(RoleRunManager._smooth_render_page)

    assert "not self._widget_alive(self._busy_indicator)" in source


def test_pc_keyboard_can_reach_and_accept_the_inspector_action() -> None:
    move = inspect.getsource(UnifiedTeamPCView._move_direction_key)
    accept = inspect.getsource(UnifiedTeamPCView._accept_keyboard_selection)

    assert "before == after" in move
    assert "self._keyboard_inspector_action" in move
    assert "actions[index + 1]" in move
    assert "self._keyboard_inspector_action = (action, pokemon)" in accept
    assert "self.on_action(action, pokemon)" in accept


def test_right_arrow_moves_from_change_role_to_teach_tm_after_z() -> None:
    pokemon = object()
    applied: list[str] = []
    view = SimpleNamespace(
        _keyboard_inspector_action=("change_role", pokemon),
        _inspector_action_buttons={"change_role": object(), "teach_tm": object()},
        _apply_selection_styles=lambda: applied.append("styled"),
    )

    result = UnifiedTeamPCView._move_direction_key(view, None, "right")

    assert result == "break"
    assert view._keyboard_inspector_action == ("teach_tm", pokemon)
    assert applied == ["styled"]


def test_operation_bar_types_larger_messages_progressively() -> None:
    source = inspect.getsource(OperationStatusBar.show_message)
    init = inspect.getsource(OperationStatusBar.__init__)

    assert "detail[:index]" in source
    assert "self.after(14" in source
    assert 'ctk.CTkFont("Segoe UI", 15)' in init


def test_global_tm_is_a_real_primary_destination() -> None:
    assert normalize_navigation_target("tms") == "tms"
    assert primary_page_for("tms") == "tms"
    # El reparto por página vive en `_render_page_body`, que salió de
    # `render_page` para poder cronometrarse aparte.
    render = inspect.getsource(RoleRunManager.render_page)
    assert "self._render_page_body()" in render
    cuerpo = inspect.getsource(RoleRunManager._render_page_body)
    assert 'elif self.active_page == "tms"' in cuerpo
    assert "self._render_global_tm_page()" in cuerpo


def test_global_tm_matrix_reuses_per_pokemon_validated_candidates() -> None:
    first = SimpleNamespace(identity="first")
    second = SimpleNamespace(identity="second")
    tm = SimpleNamespace(number=29, item_id=456, move_id=94)
    profile = SimpleNamespace(tms={29: tm}, tm=lambda number: tm if int(number) == 29 else None)
    manager = SimpleNamespace(
        _projected_party=lambda: [first, second],
        _effective_moves_for_review=lambda _pokemon: (["A", "B", "C", "D"], [1, 2, 3, 4]),
        _tm_flow_candidates=lambda pokemon, _profile, _inventory, _ids: (
            ({"move_id": 94},) if pokemon is first else ()
        ),
        _pokemon_identity=lambda pokemon: pokemon.identity,
        _draft_move_metadata=lambda _move_id: {
            "power": 90, "accuracy": 100, "description": "Control",
        },
        engine=SimpleNamespace(move=lambda _move_id: {"name_es": "Psíquico"}),
        _damage_class_for_move=lambda _move_id: "special",
        _tm_pp_for_profile=lambda _profile, _move_id: 10,
    )

    entries = RoleRunManager._global_tm_entries(manager, profile, {456: 2})

    assert len(entries) == 1
    assert entries[0]["move_name"] == "Psíquico"
    assert entries[0]["quantity"] == 2
    assert entries[0]["compatible"] == ("first",)


def test_global_tm_choice_enters_existing_flow_with_preselected_move() -> None:
    calls: list[tuple] = []
    manager = SimpleNamespace(
        _open_integrated_tm_flow=lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    profile = object()
    pokemon = object()

    RoleRunManager._open_global_tm_choice(
        manager, profile, {456: 1}, "RAM viva", {"move_id": 94}, pokemon,
    )

    assert calls == [
        ((pokemon, profile, {456: 1}, "RAM viva"), {"initial_move_id": 94, "return_page": "tms"})
    ]


def test_global_tm_catalog_only_exposes_tms_confirmed_in_inventory() -> None:
    pokemon = SimpleNamespace(identity="first")
    tm = SimpleNamespace(number=30, item_id=457, move_id=95)
    profile = SimpleNamespace(tms={30: tm}, tm=lambda _number: tm)
    manager = SimpleNamespace(
        _projected_party=lambda: [pokemon],
        _effective_moves_for_review=lambda _pokemon: (["A"], [1]),
        _tm_flow_candidates=lambda *_args: (),
        _pokemon_identity=lambda value: value.identity,
        _draft_move_metadata=lambda _move_id: {},
        engine=SimpleNamespace(move=lambda _move_id: {"name_es": "Hipnosis"}),
        _damage_class_for_move=lambda _move_id: "status",
        _tm_pp_for_profile=lambda _profile, _move_id: 20,
    )

    entries = RoleRunManager._global_tm_entries(manager, profile, {})

    assert entries == ()


def test_global_tm_distinguishes_already_known_from_incompatible() -> None:
    pokemon = SimpleNamespace(identity="first")
    tm = SimpleNamespace(number=30, item_id=457, move_id=95)
    profile = SimpleNamespace(tms={30: tm}, tm=lambda _number: tm)
    manager = SimpleNamespace(
        _projected_party=lambda: [pokemon],
        _effective_moves_for_review=lambda _pokemon: (["Hipnosis"], [95]),
        _tm_flow_candidates=lambda *_args: (),
        _pokemon_identity=lambda value: value.identity,
        _draft_move_metadata=lambda _move_id: {},
        engine=SimpleNamespace(move=lambda _move_id: {"name_es": "Hipnosis"}),
        _damage_class_for_move=lambda _move_id: "status",
        _tm_pp_for_profile=lambda _profile, _move_id: 20,
    )

    entry = RoleRunManager._global_tm_entries(manager, profile, {457: 1})[0]

    assert entry["known"] == ("first",)
    assert entry["compatible"] == ()


def test_global_tm_selection_does_not_rebuild_the_scroll_surface() -> None:
    """Elegir o previsualizar no puede rehacer la lista.

    Rehacerla movería el scroll y perdería la posición del teclado. Los métodos
    cambiaron de nombre al llegar las pestañas —`_preview_tm` es `_preview` y
    `_select_tm` es `_select`, porque ahora también hay drafteos— pero la
    garantía es la misma y sigue haciendo falta.
    """
    source = inspect.getsource(GlobalTMView._select)
    preview = inspect.getsource(GlobalTMView._preview)

    assert "_render_list" not in source
    assert "_render_list" not in preview
    assert "_render_team" not in preview
    assert "_update_team_compatibility" in preview


def test_global_tm_z_advances_from_the_move_to_first_compatible_pokemon() -> None:
    first = SpatialTarget(("tm", 10), 0, 0)
    second = SpatialTarget(("pokemon", "party-2"), 0, 2)
    keyboard = SpatialSelection((first, second))
    keyboard.selected_key = first.key
    painted: list[object] = []
    view = SimpleNamespace(
        selected_key=None,
        preview_key=first.key,
        _preview=lambda _clave: None,
        _update_highlight=lambda: None,
        _keyboard=keyboard,
        _apply_keyboard=lambda: painted.append(keyboard.selected_key),
    )

    GlobalTMView._select(view, ("tm", 10))

    assert view.selected_key == ("tm", 10)
    assert keyboard.selected_key == second.key
    assert painted == [second.key]


def test_draft_results_expose_choose_and_reroll_as_separate_targets() -> None:
    source = inspect.getsource(IntegratedDraftFlow._render_results_step)

    assert '("result-choose", index)' in source
    assert '("result-reroll", index)' in source
    assert "reroll, lambda i=index: self.on_reroll(i)" in source


def test_global_tm_apply_keeps_page_until_confirmed_readback() -> None:
    source = inspect.getsource(RoleRunManager._open_integrated_tm_flow)
    queue = inspect.getsource(RoleRunManager._queue_tm_teach)

    assert 'preserve_page=(return_page == "tms")' in source
    assert "if not preserve_page" in queue
def test_back_from_team_inspector_action_preserves_pokemon_cursor() -> None:
    view = UnifiedTeamPCView.__new__(UnifiedTeamPCView)
    view.selection = TeamPCSelectionState(
        context="team", selected_identity="poke-2",
        team_identities=("poke-1", "poke-2"), active=True,
    )
    view._keyboard_inspector_action = ("teach-tm", object())
    view._apply_selection_styles = lambda: None

    assert view._clear_keyboard_selection() == "break"
    assert view._keyboard_inspector_action is None
    assert view.selection.active is True
    assert view.selection.selected_identity == "poke-2"


def test_back_from_draft_result_returns_to_step_one() -> None:
    called: list[str] = []
    view = IntegratedDraftFlow.__new__(IntegratedDraftFlow)
    view.selected_pokemon = object()
    view.selected_draft = None
    view.on_back = lambda: called.append("back")

    assert view._clear_keyboard() == "break"
    assert called == ["back"]
