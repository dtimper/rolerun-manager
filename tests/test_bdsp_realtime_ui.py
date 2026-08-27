from __future__ import annotations

import inspect
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from unittest.mock import patch

from app.models import (
    PendingChange,
    PendingInventoryChange,
    PendingPartyHeal,
    PendingRoleChange,
    PendingTMTeach,
    PendingTeamChange,
)
from app.save_engine_client import SaveBox, SaveGameData, SavePCData, SavePokemon
from app.ui import RoleRunManager


def _pokemon(hp: int) -> SavePokemon:
    return SavePokemon(
        slot=1, species_id=300, species="Skitty", nickname="Skibidi", level=12,
        held_item="Ninguno", ability="Gran Encanto", moves=["Destructor"], move_ids=[1],
        is_egg=False, markings=[True, False, False, False, False, False],
        role="Líbero", role_symbol="●", pid=10, tid=20, sid=30,
        current_hp=hp, max_hp=21,
    )


def _game(hp: int) -> SaveGameData:
    return SaveGameData(
        game="SP", save_type="SAV8BS", generation=8, trainer="Lucía",
        party=[_pokemon(hp)], raw={},
    )


class _ImmediateThread:
    def __init__(self, *, target, **_kwargs) -> None:
        self.target = target

    def start(self) -> None:
        self.target()


def _pc_data() -> SavePCData:
    return SavePCData(
        game="SP", box_count=40, box_slot_count=30, current_box=1,
        boxes=[SaveBox(index, f"Caja {index}", []) for index in range(1, 41)],
        next_open_box=1, next_open_box_slot=1,
        open_slots=[
            (box, slot) for box in range(1, 41) for slot in range(1, 31)
        ],
        raw={},
    )


def test_bdsp_live_swap_waits_for_readback_before_projecting_either_lane() -> None:
    """A stale PC sample must never be combined with an optimistic live party."""
    change = PendingTeamChange(
        operation="swap-party-box", party_slot=1, box=1, box_slot=2,
        incoming_identity="300:10:20:30", outgoing_identity="17:40:50:60",
    )
    manager = SimpleNamespace(
        _pending_team_changes=lambda: [change],
        _active_azahar_realtime_key=lambda: "bdsp",
        _oras_live_auto_apply_available=lambda: True,
    )

    assert RoleRunManager._projectable_team_changes(manager) == []


def test_bdsp_uses_the_instant_ui_and_automatic_party_writer() -> None:
    manager = SimpleNamespace(
        save_engine=SimpleNamespace(key="bdsp"),
        project=object(), current_save=object(), current_game=_game(21),
        _oras_live_active=True,
    )

    assert RoleRunManager._active_azahar_realtime_key(manager) == "bdsp"
    assert RoleRunManager._uses_instant_realtime_ui(manager) is True
    assert RoleRunManager._oras_live_auto_apply_available(manager) is True


def test_live_health_merge_updates_hp_and_status_without_moving_party() -> None:
    target = _game(21)
    sample = _game(9)
    sample.party[0].status_condition = 64

    changed = RoleRunManager._merge_live_health_fields(target, sample)

    assert changed is True
    assert [(p.slot, p.nickname) for p in target.party] == [(1, "Skibidi")]
    assert target.party[0].current_hp == 9
    assert target.party[0].max_hp == 21
    assert target.party[0].status_condition == 64


def test_live_health_merge_rejects_a_different_identity() -> None:
    target = _game(21)
    sample = _game(9)
    sample.party[0].pid = 999

    assert RoleRunManager._merge_live_health_fields(target, sample) is False
    assert target.party[0].current_hp == 21


@pytest.mark.parametrize(
    ("status", "expected"),
    [(1, "DOR"), (7, "DOR"), (8, "ENV"), (128, "ENV"),
     (16, "QUE"), (32, "CON"), (64, "PAR")],
)
def test_floating_status_uses_pkhex_status_condition_values(status: int, expected: str) -> None:
    assert RoleRunManager._floating_status_style(status)[1] == expected
    assert RoleRunManager._floating_status_style(0) is None


def test_all_hotkey_actions_require_emulator_foreground() -> None:
    calls: list[str] = []
    manager = SimpleNamespace(
        _foreground_is_supported_emulator=lambda: False,
        after=lambda _delay, callback: callback(),
        _heal_bdsp_party=lambda: calls.append("heal"),
        _toggle_floating_launcher=lambda: calls.append("menu"),
        _counter_is_automatic=lambda _counter: False,
        project=SimpleNamespace(hotkeys={"vidas_mas": "num 7"}),
        adjust_run_counter=lambda counter, amount, **_kwargs: calls.append(f"{counter}:{amount}"),
    )

    RoleRunManager._hotkey_action(manager, "heal_party")
    RoleRunManager._hotkey_action(manager, "floating_menu")
    RoleRunManager._hotkey_action(manager, "vidas_mas")
    assert calls == []

    manager._foreground_is_supported_emulator = lambda: True
    RoleRunManager._hotkey_action(manager, "heal_party")
    RoleRunManager._hotkey_action(manager, "floating_menu")
    RoleRunManager._hotkey_action(manager, "vidas_mas")
    assert calls == ["heal", "menu", "vidas:1"]


def test_enabling_floating_preference_opens_the_bar_immediately() -> None:
    calls: list[str] = []
    labels: list[str] = []
    manager = SimpleNamespace(
        _floating_enabled=False,
        project=object(),
        current_game=_game(21),
        _save_floating_enabled=lambda: calls.append("saved"),
        _floating_bar_is_visible=lambda: False,
        after=lambda _delay, callback: (calls.append("scheduled"), callback()),
        open_floating_bar=lambda: calls.append("opened"),
        floating_bar_button=None,
        _widget_alive=lambda _widget: False,
        _floating_button_text=SimpleNamespace(set=lambda value: labels.append(value)),
        update_idletasks=lambda: calls.append("painted"),
    )

    RoleRunManager._toggle_floating_enabled(manager)

    assert manager._floating_enabled is True
    assert labels == ["BARRA FLOTANTE · ON"]
    assert "painted" in calls
    assert calls == ["saved", "scheduled", "opened", "painted"]


def test_floating_preference_real_persistence_does_not_abort_before_repaint(tmp_path) -> None:
    path = tmp_path / "floating_bar.json"
    manager = SimpleNamespace(_floating_enabled=False, _floating_bar_config_path=path)

    RoleRunManager._save_floating_enabled(manager)

    assert json.loads(path.read_text(encoding="utf-8")) == {"enabled": False}


def test_floating_launcher_never_changes_ryujinx_state_or_sends_pause() -> None:
    source = inspect.getsource(RoleRunManager._toggle_floating_launcher)
    assert "ShowWindow" not in source
    assert "SendInput" not in source
    assert "pause" not in source.casefold()
    assert "grab_set" in source


def test_overlay_x_returns_one_level_before_closing_the_launcher() -> None:
    calls: list[str] = []
    launcher = object()
    manager = SimpleNamespace(
        _floating_menu_level="page",
        _floating_launcher=launcher,
        _return_to_floating_menu=lambda: calls.append("home"),
        _show_floating_menu_home=lambda value: calls.append(
            "bag-home" if value is launcher else "wrong"
        ),
        _close_floating_launcher=lambda: calls.append("closed"),
    )

    assert RoleRunManager._back_floating_overlay_key(manager) == "break"
    manager._floating_menu_level = "bag"
    assert RoleRunManager._back_floating_overlay_key(manager) == "break"
    manager._floating_menu_level = "home"
    assert RoleRunManager._back_floating_overlay_key(manager) == "break"

    assert calls == ["home", "bag-home", "closed"]


def test_overlay_home_exposes_settings_and_bag_reports_each_action() -> None:
    home = inspect.getsource(RoleRunManager._show_floating_menu_home)
    bag = inspect.getsource(RoleRunManager._show_overlay_bag)

    assert 'text="⚙"' in home
    assert "command=self._open_settings_from_floating_launcher" in home
    assert "Aplicando {name}" in bag
    assert "enviado a la Bolsa" in bag


def test_floating_counter_forces_an_immediate_deferred_repaint() -> None:
    scheduled: list[tuple[int, object]] = []
    manager = SimpleNamespace(
        project=SimpleNamespace(counters={"vidas": 1}),
        project_service=SimpleNamespace(
            adjust_counter=lambda project, counter, delta, source: project.counters.__setitem__(
                counter, project.counters[counter] + delta
            ),
            load=lambda _slug: None,
        ),
        current_game=None,
        active_page="other",
        _shell_built=False,
        _floating_bar_last_signature=(1,),
        _counter_is_automatic=lambda _counter: False,
        _active_azahar_realtime_label=lambda: "Ryujinx",
        _sync_obs_state=lambda _game: None,
        _set_operation_status=lambda *args: None,
        _record_edit_transition=lambda: None,
        after=lambda delay, callback: scheduled.append((delay, callback)),
        _render_floating_bar=lambda force=False: scheduled.append((-1, force)),
    )
    manager.project.slug = "run"

    RoleRunManager.adjust_run_counter(
        manager, "vidas", 1, source="barra flotante"
    )

    assert manager.project.counters["vidas"] == 2
    assert manager._floating_bar_last_signature is None
    assert scheduled[0][0] == 0
    scheduled[0][1]()
    assert scheduled[-1] == (-1, True)


def test_overlay_close_button_is_above_the_embedded_page_header() -> None:
    source = inspect.getsource(RoleRunManager._enter_game_overlay)
    assert 'y=14' in source
    assert 'y=70' not in source[source.index("close.place"):source.index("close.lift")]


def test_overlay_keyboard_routes_directions_and_accept_to_the_visible_view() -> None:
    calls: list[tuple] = []
    view = SimpleNamespace(
        _move_direction_key=lambda event, direction: calls.append(("move", event, direction)),
        _accept_keyboard_selection=lambda event: calls.append(("accept", event)),
    )
    event = object()
    manager = SimpleNamespace(
        active_page="team",
        _team_pc_view=view,
        _global_tm_view=None,
        _draft_view=None,
        _floating_menu_level="page",
    )

    assert RoleRunManager._dispatch_game_overlay_key(manager, event, "down") == "break"
    assert RoleRunManager._accept_floating_overlay_key(manager, event) == "break"
    assert calls == [("move", event, "down"), ("accept", event)]


def test_game_overlay_builds_its_independent_viewport_before_rendering() -> None:
    source = inspect.getsource(RoleRunManager._enter_game_overlay)
    assert source.index("self.body = overlay_body") < source.index("self.render_page()")
    assert "for child in launcher.winfo_children()" in source


def test_bdsp_party_heal_queues_every_live_member_as_one_automatic_batch() -> None:
    first = _pokemon(3)
    second = _pokemon(7)
    second.slot, second.pid = 2, 99
    requested: list[set[int]] = []
    statuses: list[tuple] = []
    manager = SimpleNamespace(
        current_game=SaveGameData(
            game="SP", save_type="SAV8BS", generation=8, trainer="Lucía",
            party=[first, second], raw={},
        ),
        run=SimpleNamespace(pending_changes=[]),
        _active_azahar_realtime_key=lambda: "bdsp",
        _pokemon_identity=lambda pokemon: f"{pokemon.species_id}:{pokemon.pid}:{pokemon.tid}:{pokemon.sid}",
        _set_operation_status=lambda *args, **kwargs: statuses.append((args, kwargs)),
        _request_oras_live_auto_apply_since=lambda ids: requested.append(set(ids)),
    )

    RoleRunManager._heal_bdsp_party(manager)

    assert [type(change) for change in manager.run.pending_changes] == [
        PendingPartyHeal, PendingPartyHeal,
    ]
    assert [change.pokemon_slot for change in manager.run.pending_changes] == [1, 2]
    assert requested == [set()]
    assert statuses[0][0][:2] == ("applying", "CURANDO EL EQUIPO")


def test_bdsp_money_button_uses_the_bdsp_limit_without_changing_3ds() -> None:
    assert RoleRunManager._inventory_money_max_for_engine("bdsp") == 999_999
    assert RoleRunManager._inventory_money_max_for_engine("usum") == 9_999_999


def test_bdsp_tm_is_selected_for_immediate_apply_instead_of_waiting_for_save() -> None:
    change = PendingTMTeach(
        role="Líbero", pokemon_slot=1, pokemon="Skibidi", species="Skitty",
        move_slot=2, old_move="Gruñido", old_move_id=45,
        new_move="Rayo", new_move_id=85,
        pokemon_identity="300:10:20:30", item_id=328, tm_number=1,
        item_name="MT01", quantity_before=2,
    )
    scheduled: list[bool] = []
    manager = SimpleNamespace(
        run=SimpleNamespace(pending_changes=[change]),
        _oras_live_auto_apply_available=lambda: True,
        _active_azahar_realtime_key=lambda: "bdsp",
        _oras_live_auto_apply_ids=set(),
        _schedule_oras_live_auto_apply=lambda: scheduled.append(True),
    )

    RoleRunManager._request_oras_live_auto_apply(manager, [change])

    assert manager._oras_live_auto_apply_ids == {id(change)}
    assert scheduled == [True]


def test_bdsp_proven_party_box_swap_is_selected_for_immediate_apply() -> None:
    change = PendingTeamChange(
        operation="swap-party-box", party_slot=6, box=1, box_slot=1,
        outgoing_pokemon="Chanchy", outgoing_species="Slowpoke",
        incoming_pokemon="Pidgeotto", incoming_species="Pidgeotto",
    )
    scheduled: list[bool] = []
    manager = SimpleNamespace(
        run=SimpleNamespace(pending_changes=[change]),
        _oras_live_auto_apply_available=lambda: True,
        _active_azahar_realtime_key=lambda: "bdsp",
        _oras_live_auto_apply_ids=set(),
        _schedule_oras_live_auto_apply=lambda: scheduled.append(True),
    )

    RoleRunManager._request_oras_live_auto_apply(manager, [change])

    assert manager._oras_live_auto_apply_ids == {id(change)}
    assert scheduled == [True]


def test_bdsp_proven_utility_is_selected_for_immediate_apply() -> None:
    change = PendingInventoryChange("money-max", "Dinero", 999_999)
    scheduled: list[bool] = []
    manager = SimpleNamespace(
        run=SimpleNamespace(pending_changes=[change]),
        _oras_live_auto_apply_available=lambda: True,
        _active_azahar_realtime_key=lambda: "bdsp",
        _oras_live_auto_apply_ids=set(),
        _schedule_oras_live_auto_apply=lambda: scheduled.append(True),
    )

    RoleRunManager._request_oras_live_auto_apply(manager, [change])

    assert manager._oras_live_auto_apply_ids == {id(change)}
    assert scheduled == [True]


def test_bdsp_disconnected_action_is_removed_instead_of_becoming_an_invisible_save_queue() -> None:
    change = PendingChange(
        role="Líbero", pokemon_slot=1, pokemon="Skibidi", species="Skitty",
        move_slot=1, old_move="Destructor", old_move_id=1,
        new_move="—", new_move_id=0, pokemon_identity="300:10:20:30",
    )
    calls: list[tuple[str, object]] = []
    manager = SimpleNamespace(
        save_engine=SimpleNamespace(key="bdsp"),
        run=SimpleNamespace(pending_changes=[change]),
        active_page="team",
        _active_azahar_realtime_key=lambda: "bdsp",
        _oras_live_auto_apply_available=lambda: False,
        _smooth_render_page=lambda **kwargs: calls.append(("render", kwargs)),
        _show_live_sync_toast=lambda title, detail, success: calls.append(
            ("toast", (title, detail, success))
        ),
    )

    RoleRunManager._request_oras_live_auto_apply(manager, [change])

    assert manager.run.pending_changes == []
    assert calls[0] == ("render", {"preserve_scroll": True})
    assert calls[1][0] == "toast"
    assert "no quedó pendiente" in calls[1][1][1]


def test_bdsp_inventory_utility_is_queued_only_for_immediate_live_apply() -> None:
    calls: list[tuple[str, str, bool]] = []
    requested: list[set[int]] = []
    manager = SimpleNamespace(
        save_engine=SimpleNamespace(key="bdsp"),
        _oras_live_active=True,
        run=SimpleNamespace(pending_changes=[]),
        active_page="team",
        _smooth_render_page=lambda **_kwargs: None,
        _request_oras_live_auto_apply_since=lambda previous: requested.append(previous),
        _show_live_sync_toast=lambda title, detail, success: calls.append(
            (title, detail, success)
        ),
    )

    RoleRunManager.queue_inventory_change(manager, "rare-candy", "Caramelo Raro", 999)

    assert len(manager.run.pending_changes) == 1
    change = manager.run.pending_changes[0]
    assert isinstance(change, PendingInventoryChange)
    assert (change.item_key, change.quantity) == ("rare-candy", 999)
    assert requested == [set()]
    assert calls == [("APLICANDO EN PERLA RELUCIENTE", "Caramelo Raro ×999", True)]


def test_bdsp_inventory_utility_is_rejected_when_ryujinx_is_disconnected() -> None:
    calls: list[tuple[str, str, bool]] = []
    manager = SimpleNamespace(
        save_engine=SimpleNamespace(key="bdsp"),
        _oras_live_active=False,
        _show_live_sync_toast=lambda title, detail, success: calls.append(
            (title, detail, success)
        ),
    )

    RoleRunManager.queue_inventory_change(manager, "max-repel", "Repelente Máximo", 999)

    assert len(calls) == 1
    assert "NO ESTÁ SINCRONIZADO" in calls[0][0]
    assert "ningún cambio pendiente" in calls[0][1]
    assert calls[0][2] is False


def test_bdsp_pc_growth_is_rejected_when_live_connection_is_not_ready() -> None:
    manager = SimpleNamespace(
        save_engine=SimpleNamespace(key="bdsp"),
        current_game=_game(21),
        _oras_live_auto_apply_available=lambda: False,
    )

    with pytest.raises(RuntimeError, match="conectada en tiempo real"):
        RoleRunManager._prepare_pc_team_change(manager, _pokemon(21))


def test_bdsp_live_supports_proven_resize_and_faint_replacement() -> None:
    manager = SimpleNamespace(_active_azahar_realtime_key=lambda: "bdsp")
    swap = PendingTeamChange(
        operation="swap-party-box", party_slot=1, box=1, box_slot=1,
    )
    growth = PendingTeamChange(
        operation="box-to-party", party_slot=2, box=1, box_slot=2,
    )
    deposit = PendingTeamChange(
        operation="party-to-box", party_slot=1,
    )
    faint = PendingTeamChange(
        operation="replace-fainted", party_slot=1, box=1, box_slot=3,
    )

    assert RoleRunManager._oras_live_unsupported_changes(
        manager, [swap, growth, deposit, faint],
    ) == []


def test_bdsp_live_supports_utilities_but_not_pc_resident_role_changes() -> None:
    manager = SimpleNamespace(_active_azahar_realtime_key=lambda: "bdsp")
    utility = PendingInventoryChange("rare-candy", "Caramelo Raro", 999)

    assert RoleRunManager._oras_live_unsupported_changes(manager, [utility]) == []


def test_bdsp_tail_resize_changes_are_selected_for_immediate_apply() -> None:
    deposit = PendingTeamChange(operation="party-to-box", party_slot=5)
    growth = PendingTeamChange(
        operation="box-to-party", party_slot=6, box=1, box_slot=3,
    )
    scheduled: list[bool] = []
    manager = SimpleNamespace(
        run=SimpleNamespace(pending_changes=[deposit, growth]),
        _oras_live_auto_apply_available=lambda: True,
        _active_azahar_realtime_key=lambda: "bdsp",
        _oras_live_auto_apply_ids=set(),
        _schedule_oras_live_auto_apply=lambda: scheduled.append(True),
    )

    RoleRunManager._request_oras_live_auto_apply(manager, [deposit, growth])

    assert manager._oras_live_auto_apply_ids == {id(deposit), id(growth)}
    assert scheduled == [True]


def test_bdsp_faint_replacement_is_selected_for_immediate_apply() -> None:
    change = PendingTeamChange(
        operation="replace-fainted", party_slot=2,
        box=1, box_slot=3, graveyard_box=4, graveyard_box_slot=1,
    )
    scheduled: list[bool] = []
    manager = SimpleNamespace(
        run=SimpleNamespace(pending_changes=[change]),
        _oras_live_auto_apply_available=lambda: True,
        _active_azahar_realtime_key=lambda: "bdsp",
        _oras_live_auto_apply_ids=set(),
        _schedule_oras_live_auto_apply=lambda: scheduled.append(True),
    )

    RoleRunManager._request_oras_live_auto_apply(manager, [change])

    assert manager._oras_live_auto_apply_ids == {id(change)}
    assert scheduled == [True]


def test_live_pc_matrix_replaces_stale_save_occupancy_before_selector() -> None:
    stale = _pokemon(21)
    stale.species_id, stale.species, stale.nickname = 79, "Slowpoke", "Chanchy"
    stale.box, stale.box_slot, stale.slot = 1, 1, 1
    live = _pokemon(30)
    live.species_id, live.species, live.nickname = 17, "Pidgeotto", "Pajarraco"
    live.box, live.box_slot, live.slot = 1, 1, 1
    base = _pc_data()
    base.boxes[0].pokemon = [stale]

    result = RoleRunManager._pc_data_from_live_slots(base, {(1, 1): live})

    assert [(p.species_id, p.nickname) for p in result.boxes[0].pokemon] == [
        (17, "Pajarraco")
    ]
    assert result.raw["live_matrix"] is True
    assert (1, 1) not in result.open_slots


def test_bdsp_contextual_pc_selector_waits_for_live_matrix() -> None:
    calls: list[tuple[object, object, object]] = []
    outgoing = _pokemon(21)
    manager = SimpleNamespace(
        current_game=_game(21),
        current_save=SimpleNamespace(path=object()),
        _oras_live_active=True,
        _cancel_role_drag=lambda: None,
        _active_azahar_realtime_key=lambda: "bdsp",
        _oras_live_auto_apply_available=lambda: True,
        _open_pc_selector_from_live_matrix=lambda **kwargs: calls.append((
            kwargs["replace_pokemon"], kwargs["forced_role"], kwargs["browse_only"],
        )),
        _read_pc_data=lambda: (_ for _ in ()).throw(
            AssertionError("el selector no debe leer primero el save obsoleto")
        ),
    )

    RoleRunManager.open_pc_selector(
        manager, replace_pokemon=outgoing, forced_role="Asesino",
    )

    assert calls == [(outgoing, "Asesino", False)]


def test_bdsp_change_with_pc_button_waits_for_live_matrix_before_building_modal() -> None:
    calls: list[dict[str, object]] = []
    outgoing = _pokemon(21)
    manager = SimpleNamespace(
        current_game=_game(21),
        current_save=SimpleNamespace(path=object()),
        _oras_live_active=True,
        _cancel_role_drag=lambda: None,
        _active_azahar_realtime_key=lambda: "bdsp",
        _oras_live_auto_apply_available=lambda: True,
        _open_pc_selector_from_live_matrix=lambda **kwargs: calls.append(kwargs),
        _read_pc_data=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("CAMBIAR CON PC no debe forzar primero el save obsoleto")
        ),
    )

    RoleRunManager._open_team_to_pc_swap_picker(
        manager, outgoing, target_role="Asesino",
    )

    assert len(calls) == 1
    assert calls[0]["replace_pokemon"] is outgoing
    assert calls[0]["forced_role"] == "Asesino"
    assert callable(calls[0]["on_loaded"])


def test_bdsp_initial_sync_arms_battle_baseline_without_writing() -> None:
    baseline = _game(7)
    snapshot = SimpleNamespace(
        game=_game(21),
        battle=SimpleNamespace(state="battle", health_game=baseline),
    )
    calls: list[tuple[str, object]] = []
    manager = SimpleNamespace(
        _live_sync_in_progress=True,
        _session_generation=4,
        project=SimpleNamespace(slug="run"),
        current_game=_game(21),
        _active_azahar_realtime_key=lambda: "bdsp",
        _cancel_oras_initial_auto_sync=lambda: calls.append(("cancel", None)),
        _oras_live_monitor_failures=9,
        _oras_battle_probe_last_state="unknown",
        _oras_live_health_snapshot=None,
        _reconcile_pending_faints_against_party=lambda game: calls.append(("reconcile", game)),
        _incoming_oras_role_changes=lambda _old, _new: [],
        _publish_oras_live_snapshot=lambda value: calls.append(("publish", value)),
        _record_bdsp_ui_event=lambda event, **fields: calls.append(
            ("trace", (event, fields))
        ),
        _schedule_gen6_live_pc_refresh=lambda: calls.append(("pc-refresh", None)),
        _update_top_status=lambda: calls.append(("status", None)),
        _schedule_oras_live_reconciliation=lambda delay: calls.append(("schedule", delay)),
        _show_live_sync_toast=lambda title, detail, success: calls.append(("toast", success)),
        _save_oras_live_changes=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("BDSP no debe entrar en el writer")
        ),
        sync_status="",
    )

    RoleRunManager._finish_oras_live_sync(
        manager, 4, "run", snapshot, None, automatic=True,
    )

    assert manager._oras_live_health_snapshot is baseline
    assert manager._oras_battle_probe_last_state == "battle"
    assert ("publish", snapshot) in calls
    assert ("pc-refresh", None) in calls
    assert ("schedule", 250) in calls
    assert "party/MT transaccional" in manager.sync_status


@pytest.mark.parametrize("writer_started", [True, False])
def test_bdsp_initial_sync_never_publishes_a_pc_swap_before_role_inheritance(
    writer_started: bool,
) -> None:
    outgoing = _pokemon(21)
    outgoing.role = "Asesino"
    outgoing.role_symbol = "▲"
    incoming = _pokemon(21)
    incoming.species_id = 79
    incoming.species = "Slowpoke"
    incoming.nickname = "Chanchy"
    incoming.pid = 99
    incoming.role = "Mago"
    incoming.role_symbol = "■"
    before = SaveGameData("SP", "SAV8BS", 8, "Lucía", [outgoing], {})
    after = SaveGameData("SP", "SAV8BS", 8, "Lucía", [incoming], {})
    snapshot = SimpleNamespace(
        game=after, battle=SimpleNamespace(state="none", health_game=None),
    )
    calls: list[tuple[str, object]] = []
    manager = SimpleNamespace(
        _live_sync_in_progress=True,
        _session_generation=4,
        project=SimpleNamespace(slug="run"),
        run=SimpleNamespace(pending_changes=[]),
        current_game=before,
        _active_azahar_realtime_key=lambda: "bdsp",
        _cancel_oras_initial_auto_sync=lambda: calls.append(("cancel", None)),
        _oras_live_monitor_failures=0,
        _oras_battle_probe_last_state="unknown",
        _oras_live_health_snapshot=None,
        _bdsp_marker_migration_change_ids=set(),
        _oras_live_role_marker_migration_ids=set(),
        _oras_live_system_role_assignment_ids=set(),
        _pokemon_identity=lambda pokemon: (
            f"{pokemon.species_id}:{pokemon.pid}:{pokemon.tid}:{pokemon.sid}"
        ),
        _incoming_oras_role_changes=lambda old, new: (
            RoleRunManager._incoming_oras_role_changes(manager, old, new)
        ),
        _reconcile_pending_faints_against_party=lambda game: calls.append(("reconcile", game)),
        _save_oras_live_changes=lambda changes, automatic, base_game: (
            calls.append(("write", (list(changes), automatic, base_game))) or writer_started
        ),
        _schedule_oras_external_pc_reconcile=lambda old, new: calls.append(("pc", (old, new))),
        _publish_oras_live_snapshot=lambda value: calls.append(("publish", value)),
        _record_bdsp_ui_event=lambda event, **fields: calls.append(("trace", (event, fields))),
        _update_top_status=lambda: calls.append(("status", None)),
        _schedule_oras_live_reconciliation=lambda delay: calls.append(("schedule", delay)),
        _schedule_oras_initial_auto_sync=lambda delay: calls.append(("initial", delay)),
        _show_live_sync_toast=lambda title, detail, success: calls.append(("toast", success)),
        sync_status="",
    )

    RoleRunManager._finish_oras_live_sync(
        manager, 4, "run", snapshot, None, automatic=True,
    )

    write = next(value for name, value in calls if name == "write")
    changes, automatic, base_game = write
    assert len(changes) == 1
    assert (changes[0].old_role, changes[0].new_role) == ("Mago", "Asesino")
    assert automatic is True and base_game is after
    assert not any(name == "publish" for name, _value in calls)
    assert ("pc", (before, after)) in calls
    assert len(manager._oras_live_system_role_assignment_ids) == (1 if writer_started else 0)
    if not writer_started:
        assert ("initial", 250) in calls


def test_team_grid_never_turns_a_six_member_role_conflict_into_a_seventh_position() -> None:
    roles = ["Líbero", "Tanque", "Prisma", "Support", "Mago", "Mago"]
    party: list[SavePokemon] = []
    for index, role in enumerate(roles, start=1):
        pokemon = _pokemon(21)
        pokemon.slot = index
        pokemon.species_id += index
        pokemon.pid += index
        pokemon.nickname = f"P{index}"
        pokemon.role = role
        party.append(pokemon)
    manager = SimpleNamespace(
        _effective_role=lambda pokemon: (pokemon.role, pokemon.role_symbol),
        _pokemon_identity=lambda pokemon: (
            f"{pokemon.species_id}:{pokemon.pid}:{pokemon.tid}:{pokemon.sid}"
        ),
        _role_slot_occupants=lambda members: RoleRunManager._role_slot_occupants(
            manager, members,
        ),
    )

    occupants, extras, positions, extra_indices = RoleRunManager._team_role_grid_layout(
        manager, party,
    )

    assert len(occupants) == 5
    assert [pokemon.nickname for pokemon in extras] == ["P6"]
    assert sorted(positions.values()) == [0, 1, 2, 3, 4, 5]
    assert extra_indices == {1}  # La casilla Asesino estaba libre.


def test_bdsp_pc_tab_schedules_a_read_even_though_writes_are_disabled() -> None:
    calls: list[tuple[SaveGameData, SaveGameData, bool]] = []
    game = _game(21)
    manager = SimpleNamespace(
        current_game=game,
        _oras_live_active=True,
        _active_azahar_realtime_key=lambda: "bdsp",
        _oras_live_auto_apply_available=lambda: False,
        _schedule_oras_external_pc_reconcile=lambda before, after, force=False: calls.append(
            (before, after, force)
        ),
    )

    RoleRunManager._schedule_gen6_live_pc_refresh(manager)

    assert calls == [(game, game, True)]


def test_bdsp_passive_tm_context_never_reads_ram_or_stale_save() -> None:
    class _Bomb:
        def __getattr__(self, name):
            raise AssertionError(f"La tarjeta pasiva no debe consultar {name}")

    manager = SimpleNamespace(
        save_engine=SimpleNamespace(key="bdsp"),
        current_save=SimpleNamespace(path="SaveData.bin"),
        realtime_core=_Bomb(),
    )

    assert RoleRunManager._tm_replacement_context(manager) is None


def test_bdsp_replacement_button_defers_inventory_validation_until_click() -> None:
    manager = SimpleNamespace(
        save_engine=SimpleNamespace(key="bdsp"),
        _oras_live_active=True,
    )

    assert RoleRunManager._tm_replacement_can_load_on_click(manager) is True


def test_bdsp_live_refresh_preserves_pending_move_deletion_without_mutating_snapshot() -> None:
    pokemon = _pokemon(21)
    pokemon.moves = ["Uno", "Dos", "Tres", "Cuatro"]
    pokemon.move_ids = [1, 2, 3, 4]
    identity = "300:10:20:30"
    deletion = PendingChange(
        role="Líbero", pokemon_slot=1, pokemon="Skibidi", species="Skitty",
        move_slot=2, old_move="Dos", old_move_id=2,
        new_move="—", new_move_id=0, pokemon_identity=identity,
    )
    manager = SimpleNamespace(
        run=SimpleNamespace(pending_changes=[deletion]),
        _pokemon_identity=lambda _pokemon: identity,
    )

    names, move_ids = RoleRunManager._effective_moves_for_review(manager, pokemon)

    assert names == ["Uno", "Tres", "Cuatro", "—"]
    assert move_ids == [1, 3, 4, 0]
    assert pokemon.moves == ["Uno", "Dos", "Tres", "Cuatro"]
    assert pokemon.move_ids == [1, 2, 3, 4]


def test_bdsp_save_swap_inherits_the_outgoing_role_even_with_an_override() -> None:
    outgoing = _pokemon(21)
    outgoing.role = "Tanque"
    outgoing.role_symbol = "♥"
    incoming = _pokemon(21)
    incoming.slot = 5
    incoming.box = 1
    incoming.box_slot = 5
    incoming.pid = 99
    incoming.role = "Mago"
    incoming.role_symbol = "■"
    manager = SimpleNamespace(
        current_game=_game(21),
        run=SimpleNamespace(pending_changes=[]),
        _pc_effective_role=lambda _pokemon: ("Mago", "■"),
        _incoming_snapshot_for_role=lambda _pokemon, role, _slots: {"role": role},
        _pending_pc_role_change=lambda _pokemon: None,
        _projected_party=lambda: [outgoing],
        _pokemon_snapshot=lambda pokemon: {
            "role": pokemon.role, "role_symbol": pokemon.role_symbol,
        },
        _effective_role=lambda pokemon: (pokemon.role, pokemon.role_symbol),
        _pokemon_identity=lambda pokemon: f"{pokemon.species_id}:{pokemon.pid}:{pokemon.tid}:{pokemon.sid}",
        _pc_role_witnesses=lambda _pokemon: (),
        _request_oras_live_auto_apply_since=lambda _ids: None,
        _sync_live_layout=lambda: None,
    )

    RoleRunManager._prepare_pc_team_change(
        manager, incoming, outgoing, incoming_role_override="Mago",
    )

    change = manager.run.pending_changes[0]
    assert change.incoming_role == "Tanque"
    assert change.incoming_snapshot["role"] == "Tanque"


def test_bdsp_send_to_pc_queues_only_the_live_tail_without_save_coordinates() -> None:
    first = _pokemon(21)
    tail = _pokemon(21)
    tail.slot = 2
    tail.species_id, tail.species, tail.nickname, tail.pid = 17, "Pidgeotto", "Pidgeotto", 99
    requested: list[set[int]] = []
    manager = SimpleNamespace(
        current_game=_game(21),
        save_engine=SimpleNamespace(key="bdsp"),
        run=SimpleNamespace(pending_changes=[]),
        _pc_cache=object(),
        active_page="team",
        _active_azahar_realtime_key=lambda: "bdsp",
        _active_azahar_realtime_label=lambda: "Perla Reluciente",
        _oras_live_auto_apply_available=lambda: True,
        _projected_party=lambda: [first, tail],
        _pokemon_snapshot=lambda pokemon: {"species_id": pokemon.species_id},
        _effective_role=lambda _pokemon: ("Asesino", "▲"),
        _pokemon_identity=lambda pokemon: f"{pokemon.species_id}:{pokemon.pid}:{pokemon.tid}:{pokemon.sid}",
        _request_oras_live_auto_apply_since=lambda before: requested.append(set(before)),
        _update_top_status=lambda: None,
        _sync_live_layout=lambda: None,
        _smooth_render_page=lambda **_kwargs: None,
    )

    RoleRunManager.send_pokemon_to_pc(manager, tail, ask=False)

    assert len(manager.run.pending_changes) == 1
    change = manager.run.pending_changes[0]
    assert change.operation == "party-to-box"
    assert change.party_slot == 2
    assert (change.box, change.box_slot) == (None, None)
    assert change.outgoing_identity == "17:99:20:30"
    assert requested == [set()]


def test_bdsp_send_to_pc_queues_a_physically_demonstrated_middle_compaction() -> None:
    first = _pokemon(21)
    tail = _pokemon(21)
    tail.slot = 2
    requested: list[set[int]] = []
    manager = SimpleNamespace(
        current_game=_game(21),
        save_engine=SimpleNamespace(key="bdsp"),
        run=SimpleNamespace(pending_changes=[]),
        _pc_cache=object(),
        active_page="team",
        _active_azahar_realtime_key=lambda: "bdsp",
        _active_azahar_realtime_label=lambda: "Perla Reluciente",
        _oras_live_auto_apply_available=lambda: True,
        _projected_party=lambda: [first, tail],
        _pokemon_snapshot=lambda pokemon: {"species_id": pokemon.species_id},
        _effective_role=lambda _pokemon: ("Líbero", "●"),
        _pokemon_identity=lambda pokemon: f"{pokemon.species_id}:{pokemon.pid}:{pokemon.tid}:{pokemon.sid}",
        _request_oras_live_auto_apply_since=lambda before: requested.append(set(before)),
        _update_top_status=lambda: None,
        _sync_live_layout=lambda: None,
        _smooth_render_page=lambda **_kwargs: None,
    )

    RoleRunManager.send_pokemon_to_pc(manager, first, ask=False)

    assert len(manager.run.pending_changes) == 1
    change = manager.run.pending_changes[0]
    assert change.operation == "party-to-box"
    assert change.party_slot == 1
    assert (change.box, change.box_slot) == (None, None)
    assert requested == [set()]


def test_bdsp_box_to_party_appends_with_the_first_free_role() -> None:
    current = _pokemon(21)
    incoming = _pokemon(21)
    incoming.box, incoming.box_slot, incoming.pid = 1, 3, 99
    incoming.role, incoming.role_symbol = "Mago", "■"
    manager = SimpleNamespace(
        save_engine=SimpleNamespace(key="bdsp"),
        current_game=_game(21),
        run=SimpleNamespace(pending_changes=[]),
        _oras_live_auto_apply_available=lambda: True,
        _active_azahar_realtime_key=lambda: "bdsp",
        _pc_effective_role=lambda _pokemon: ("Mago", "■"),
        _incoming_snapshot_for_role=lambda _pokemon, role, _slots: {"role": role},
        _pending_pc_role_change=lambda _pokemon: None,
        _projected_party=lambda: [current],
        _effective_role=lambda pokemon: (pokemon.role, pokemon.role_symbol),
        _pokemon_identity=lambda pokemon: f"{pokemon.species_id}:{pokemon.pid}:{pokemon.tid}:{pokemon.sid}",
        _pc_role_witnesses=lambda _pokemon: (),
        _request_oras_live_auto_apply_since=lambda _ids: None,
        _sync_live_layout=lambda: None,
    )

    RoleRunManager._prepare_pc_team_change(manager, incoming, replacement=None)

    change = manager.run.pending_changes[0]
    assert change.operation == "box-to-party"
    assert change.party_slot == 2
    assert change.incoming_role == "Asesino"
    assert change.incoming_snapshot["role"] == "Asesino"
    assert change.incoming_snapshot["evs"] == {
        "hp": 0, "attack": 252, "defense": 0,
        "sp_attack": 0, "sp_defense": 0, "speed": 252,
    }


def test_bdsp_legacy_marker_migration_is_atomic_and_verified_in_new_layout() -> None:
    pokemon = _pokemon(21)
    pokemon.nickname = "Luto"
    pokemon.markings = [False, True, False, False, False, False]
    identity = "300:10:20:30"
    manager = SimpleNamespace(
        save_engine=SimpleNamespace(key="bdsp"),
        project=SimpleNamespace(role_marker_layout=1),
        run=SimpleNamespace(pending_changes=[]),
        _bdsp_marker_migration_change_ids=set(),
        _bdsp_marker_migration_expected={},
        _pokemon_identity=lambda _pokemon: identity,
        _oras_marker_layout_migration_changes=lambda game: (
            RoleRunManager._oras_marker_layout_migration_changes(manager, game)
        ),
        _complete_role_marker_layout_migration=lambda: (_ for _ in ()).throw(
            AssertionError("Hay un bit físico que migrar")
        ),
    )
    game = SaveGameData("SP", "SAV8BS", 8, "Lucía", [pokemon], {})

    changes = RoleRunManager._prepare_bdsp_marker_layout_migration(manager, game)

    assert len(changes) == 1
    assert isinstance(changes[0], PendingRoleChange)
    assert changes[0].old_role == "Asesino"
    assert changes[0].new_role == "Tanque"
    assert manager._bdsp_marker_migration_expected == {identity: "Tanque"}

    pokemon.markings = [False, False, False, True, False, False]
    RoleRunManager._verify_bdsp_marker_layout_migration(manager, game, changes)


def test_bdsp_open_tm_selector_requires_background_live_inventory() -> None:
    pokemon = _pokemon(21)
    profile = SimpleNamespace(source=SimpleNamespace(name="personal_masterdatas"))
    loads: list[tuple[object, int, bool, object]] = []
    manager = SimpleNamespace(
        save_engine=SimpleNamespace(key="bdsp"),
        current_save=SimpleNamespace(path="SaveData.bin"),
        _oras_live_active=True,
        _effective_moves_for_review=lambda _pokemon: (
            ["Destructor", "—", "—", "—"], [1, 0, 0, 0],
        ),
        _get_bdsp_tm_profile=lambda prompt=False: profile,
        _start_live_tm_inventory_load=lambda mon, slot, **kwargs: loads.append(
            (mon, slot, bool(kwargs["replace_existing"]), kwargs["profile"])
        ),
    )

    RoleRunManager._open_tm_selector(manager, pokemon, 2)

    assert loads == [(pokemon, 2, False, profile)]


def test_bdsp_tm_selector_loads_live_inventory_in_background_and_projects_pending(
    tmp_path,
) -> None:
    save = tmp_path / "SaveData.bin"
    save.write_bytes(b"save")
    pokemon = _pokemon(21)
    pending = PendingTMTeach(
        role="Líbero", pokemon_slot=1, pokemon="Skibidi", species="Skitty",
        move_slot=2, old_move="—", old_move_id=0,
        new_move="Movimiento", new_move_id=99,
        pokemon_identity="300:10:20:30", item_id=337, tm_number=10,
        item_name="MT10", quantity_before=2, consumes_item=True,
    )
    reads: list[tuple[dict[int, int], object]] = []
    opened: list[tuple[object, int, dict[str, object]]] = []
    profile = SimpleNamespace(source=tmp_path / "personal_masterdatas")
    manager = SimpleNamespace(
        save_engine=SimpleNamespace(
            key="bdsp", read_inventory=lambda _path: {22: 10, 337: 2},
        ),
        realtime_core=SimpleNamespace(
            read_tm_inventory=lambda saved, save_path=None: (
                reads.append((dict(saved), save_path)) or ({22: 9, 337: 2}, object(), 1)
            ),
        ),
        current_save=SimpleNamespace(path=save),
        current_game=_game(21),
        project=SimpleNamespace(slug="run"),
        run=SimpleNamespace(pending_changes=[pending]),
        _session_generation=3,
        _sm_tm_inventory_load_in_progress=False,
        _sm_tm_inventory_load_token=0,
        _live_write_in_progress=False,
        _live_sync_in_progress=False,
        _oras_live_monitor_in_progress=False,
        _oras_live_active=True,
        sync_status="✓ Perla Reluciente enlazado",
        _pokemon_identity=lambda item: f"{item.species_id}:{item.pid}:{item.tid}:{item.sid}",
        _projected_party=lambda: [pokemon],
        _pending_adjusted_tm_inventory=lambda inventory: (
            RoleRunManager._pending_adjusted_tm_inventory(manager, inventory)
        ),
        _open_tm_selector=lambda mon, slot, **kwargs: opened.append((mon, slot, kwargs)),
        _update_top_status=lambda: None,
        _show_live_sync_toast=lambda *_args: None,
        _show_busy_indicator=lambda *_args, **_kwargs: None,
        _hide_busy_indicator=lambda *_args: None,
        _dialog_parent=lambda: None,
        after=lambda _delay, callback: callback(),
    )

    with patch("app.ui.threading.Thread", _ImmediateThread):
        RoleRunManager._start_live_tm_inventory_load(
            manager, pokemon, 2, replace_existing=False, profile=profile,
        )

    assert reads == [({22: 10, 337: 2}, save)]
    assert manager._sm_tm_inventory_load_in_progress is False
    assert len(opened) == 1
    assert opened[0][0] is pokemon and opened[0][1] == 2
    assert opened[0][2]["_live_preloaded_profile"] is profile
    assert opened[0][2]["_live_preloaded_inventory"] == {22: 9, 337: 1}


def test_bdsp_party_to_pc_reconcile_uses_full_matrix_and_preserves_live_role(
    tmp_path,
) -> None:
    save = tmp_path / "main"
    save.write_bytes(b"save")
    outgoing = _pokemon(21)
    remaining = SavePokemon(
        slot=2, species_id=353, species="Shuppet", nickname="Shuppet", level=25,
        held_item="Ninguno", ability="Insomnio", moves=["Destructor"], move_ids=[1],
        is_egg=False, markings=[False, True, False, False, False, False],
        role="Asesino", role_symbol="", pid=40, tid=20, sid=30,
        current_hp=58, max_hp=58,
    )
    before = SaveGameData("SP", "SAV8BS", 8, "Lucía", [outgoing, remaining], {})
    after = SaveGameData("SP", "SAV8BS", 8, "Lucía", [remaining], {})
    live_boxed = SavePokemon(
        slot=5, species_id=300, species="Skitty", nickname="Skibidi", level=0,
        held_item="Ninguno", ability="Gran Encanto", moves=["Destructor"], move_ids=[1],
        is_egg=False, markings=[True, False, False, False, False, False],
        role="Líbero", role_symbol="●", box=2, box_slot=5,
        pid=10, tid=20, sid=30,
    )
    pc = _pc_data()
    calls: list[tuple[list[SavePokemon], dict[str, int]]] = []
    events: list[tuple[str, dict[str, object]]] = []

    def read_pc(anchors, **kwargs):
        calls.append((list(anchors), dict(kwargs)))
        anchor = next(pokemon for pokemon in anchors if pokemon.pid == outgoing.pid)
        return SimpleNamespace(), 0x440000, {
            (2, 5): replace(live_boxed, level=anchor.level),
        }

    manager = SimpleNamespace(
        project=SimpleNamespace(slug="run"),
        current_save=SimpleNamespace(path=save), current_game=after,
        _session_generation=1, _oras_pc_reconcile_last_key=None,
        _oras_pc_reconcile_in_progress=False, _oras_pc_reconcile_token=0,
        _pc_cache=pc, _pc_cache_signature=RoleRunManager._save_file_signature(save),
        _oras_live_pc_overrides={}, _oras_live_pc_empty_overrides=set(),
        _pokemon_identity=lambda pokemon: "" if pokemon is None else (
            f"{pokemon.species_id}:{pokemon.pid}:{pokemon.tid}:{pokemon.sid}"
        ),
        _pending_team_changes=lambda: [],
        _project_pc_box_pokemon=lambda data, box: [],
        _save_file_signature=RoleRunManager._save_file_signature,
        _floating_bar_is_visible=lambda: False,
        _main_ui_dirty_while_floating=False, active_page="team",
        _smooth_render_page=lambda **_kwargs: None,
        _active_azahar_realtime_key=lambda: "bdsp",
        _active_azahar_realtime_label=lambda: "Perla Reluciente",
        _record_bdsp_ui_event=lambda event, **fields: events.append((event, fields)),
        _update_top_status=lambda: None,
        _show_live_sync_toast=lambda *_args: None,
        save_engine=SimpleNamespace(read_boxes=lambda _path: pc),
        realtime_core=SimpleNamespace(read_pc=read_pc),
        after=lambda _delay, callback: callback(), sync_status="",
    )

    with patch("app.ui.threading.Thread", _ImmediateThread):
        RoleRunManager._schedule_oras_external_pc_reconcile(
            manager, before, after,
        )

    assert len(calls) == 1
    anchors, kwargs = calls[0]
    assert kwargs == {"box_count": 40, "box_slot_count": 30}
    assert any(pokemon.pid == outgoing.pid for pokemon in anchors)
    assert manager._oras_live_pc_overrides == {}
    projected = manager._pc_cache.boxes[1].pokemon[0]
    assert projected.level == 12
    assert projected.role == "Líbero"
    assert events[-1] == ("pc-reconcile-applied", {
        "occupied_slots": 1,
        "override_slots": 0,
        "emptied_slots": 0,
        "before_party": 2,
        "after_party": 1,
        "changed": True,
    })
    assert events[0] == ("pc-reconcile-scheduled", {
        "force": False,
        "incoming_count": 0,
        "outgoing_count": 1,
        "before_party": 2,
        "after_party": 1,
    })


def _reconcile_manager(*, previous_state: str) -> tuple[SimpleNamespace, list[tuple[str, object]]]:
    calls: list[tuple[str, object]] = []
    manager = SimpleNamespace(
        _oras_live_monitor_in_progress=True,
        _oras_live_monitor_token=8,
        _session_generation=4,
        project=SimpleNamespace(slug="run"),
        current_game=_game(21),
        _oras_live_monitor_failures=0,
        _active_azahar_realtime_key=lambda: "bdsp",
        _oras_live_reconciliation_is_active=lambda: True,
        _oras_battle_probe_last_state=previous_state,
        _oras_live_health_snapshot=_game(21),
        _process_oras_health_snapshot=lambda game, source: calls.append(("health", (game, source))),
        _process_oras_battle_state=lambda state: calls.append(("battle", state)),
        _reconcile_pending_faints_against_party=lambda game: calls.append(("reconcile", game)),
        _publish_oras_live_snapshot=lambda snapshot, difference=None: calls.append(("publish", snapshot)),
        _schedule_oras_live_reconciliation=lambda delay: calls.append(("schedule", delay)),
        _update_top_status=lambda: calls.append(("status", None)),
        sync_status="",
    )
    return manager, calls


def test_bdsp_reconciliation_uses_battle_health_for_immediate_ko() -> None:
    manager, calls = _reconcile_manager(previous_state="none")
    health = _game(0)
    snapshot = SimpleNamespace(
        game=_game(21), battle=SimpleNamespace(state="battle", health_game=health),
    )

    RoleRunManager._finish_oras_live_reconciliation(
        manager, 4, "run", 8, None, snapshot, None, snapshot.battle,
    )

    assert ("health", (health, "battle-visible")) in calls
    assert ("battle", "trainer") in calls
    assert ("schedule", 250) in calls


def test_bdsp_unknown_battle_sample_never_substitutes_stale_playerwork_hp() -> None:
    manager, calls = _reconcile_manager(previous_state="battle")
    snapshot = SimpleNamespace(
        game=_game(21), battle=SimpleNamespace(state="unknown", health_game=None),
    )

    RoleRunManager._finish_oras_live_reconciliation(
        manager, 4, "run", 8, None, snapshot, None, snapshot.battle,
    )

    assert not any(name == "health" for name, _value in calls)
    assert ("battle", None) in calls
    assert ("schedule", 750) in calls


def test_alpha77_bdsp_reconciliation_commits_badges_before_party_returns() -> None:
    manager, calls = _reconcile_manager(previous_state="none")
    manager.project.counters = {"medallas": 0}
    manager._oras_badge_live_value = None
    manager._oras_badge_live_source = ""
    manager._process_oras_badge_value = lambda value, source=None: (
        calls.append(("badges", (value, source))) or True
    )
    snapshot = SimpleNamespace(
        game=_game(21), battle=SimpleNamespace(state="none", health_game=None),
    )

    RoleRunManager._finish_oras_live_reconciliation(
        manager, 4, "run", 8, None, snapshot, None, snapshot.battle,
        badge_value=2,
        badge_source="SystemFlags vivos · PlayerWork.SaveData",
    )

    assert calls[0] == (
        "badges", (2, "SystemFlags vivos · PlayerWork.SaveData"),
    )
    assert manager._oras_badge_live_value == 2
    assert manager._oras_badge_live_source.startswith("SystemFlags vivos")
    assert ("schedule", 750) in calls


def test_bdsp_deposit_reconciles_pc_with_the_pre_deposit_party_anchor() -> None:
    outgoing = _pokemon(21)
    remaining = SavePokemon(
        slot=2, species_id=353, species="Shuppet", nickname="Shuppet", level=25,
        held_item="Ninguno", ability="Insomnio", moves=["Destructor"], move_ids=[1],
        is_egg=False, markings=[False, True, False, False, False, False],
        role="Asesino", role_symbol="", pid=40, tid=20, sid=30,
        current_hp=58, max_hp=58,
    )
    before = SaveGameData("SP", "SAV8BS", 8, "Lucía", [outgoing, remaining], {})
    after = SaveGameData("SP", "SAV8BS", 8, "Lucía", [remaining], {})
    snapshot = SimpleNamespace(
        game=after, battle=SimpleNamespace(state="none", health_game=None),
    )
    calls: list[tuple[str, object]] = []
    manager = SimpleNamespace(
        _oras_live_monitor_in_progress=True,
        _oras_live_monitor_token=8,
        _session_generation=4,
        project=SimpleNamespace(slug="run"),
        current_game=before,
        _oras_live_monitor_failures=0,
        _active_azahar_realtime_key=lambda: "bdsp",
        _oras_live_reconciliation_is_active=lambda: True,
        _oras_battle_probe_last_state="none",
        _oras_live_health_snapshot=before,
        _process_oras_health_snapshot=lambda game, source: calls.append(("health", (game, source))),
        _process_oras_battle_state=lambda state: calls.append(("battle", state)),
        _reconcile_pending_faints_against_party=lambda game: calls.append(("reconcile", game)),
        _incoming_oras_role_changes=lambda _old, _new: [],
        _publish_oras_live_snapshot=lambda value, difference=None: (
            setattr(manager, "current_game", value.game),
            calls.append(("publish", value.game)),
        ),
        _schedule_oras_external_pc_reconcile=lambda old, new: calls.append(
            ("pc", (old, new))
        ),
        _schedule_oras_live_reconciliation=lambda delay: calls.append(("schedule", delay)),
        _update_top_status=lambda: calls.append(("status", None)),
        sync_status="",
    )

    RoleRunManager._finish_oras_live_reconciliation(
        manager, 4, "run", 8, None, snapshot, None, snapshot.battle,
    )

    pc_call = next(value for name, value in calls if name == "pc")
    assert pc_call == (before, after)
    assert pc_call[0].party[0].level == 12
    assert manager.current_game is after
    assert calls.index(("publish", after)) < calls.index(("pc", (before, after)))


@pytest.mark.parametrize("writer_started", [True, False])
def test_bdsp_direct_pc_swap_inherits_and_verifies_role_before_publishing_party(
    writer_started: bool,
) -> None:
    outgoing = _pokemon(21)
    outgoing.role = "Asesino"
    outgoing.role_symbol = "▲"
    incoming = _pokemon(21)
    incoming.species_id = 79
    incoming.species = "Slowpoke"
    incoming.nickname = "Chanchy"
    incoming.pid = 99
    incoming.role = "Mago"
    incoming.role_symbol = "■"
    before = SaveGameData("SP", "SAV8BS", 8, "Lucía", [outgoing], {})
    after = SaveGameData("SP", "SAV8BS", 8, "Lucía", [incoming], {})
    snapshot = SimpleNamespace(
        game=after, battle=SimpleNamespace(state="none", health_game=None),
    )
    calls: list[tuple[str, object]] = []
    manager = SimpleNamespace(
        _oras_live_monitor_in_progress=True,
        _oras_live_monitor_token=8,
        _session_generation=4,
        project=SimpleNamespace(slug="run"),
        current_game=before,
        _oras_live_monitor_failures=0,
        _active_azahar_realtime_key=lambda: "bdsp",
        _oras_live_reconciliation_is_active=lambda: True,
        _oras_battle_probe_last_state="none",
        _oras_live_health_snapshot=before,
        _oras_live_system_role_assignment_ids=set(),
        _pokemon_identity=lambda pokemon: (
            f"{pokemon.species_id}:{pokemon.pid}:{pokemon.tid}:{pokemon.sid}"
        ),
        _incoming_oras_role_changes=lambda old, new: (
            RoleRunManager._incoming_oras_role_changes(manager, old, new)
        ),
        _process_oras_health_snapshot=lambda game, source: calls.append(("health", (game, source))),
        _process_oras_battle_state=lambda state: calls.append(("battle", state)),
        _reconcile_pending_faints_against_party=lambda game: calls.append(("reconcile", game)),
        _save_oras_live_changes=lambda changes, automatic, base_game: (
            calls.append(("write", (list(changes), automatic, base_game))) or writer_started
        ),
        _publish_oras_live_snapshot=lambda value, difference=None: calls.append(("publish", value.game)),
        _schedule_oras_external_pc_reconcile=lambda old, new: calls.append(("pc", (old, new))),
        _schedule_oras_live_reconciliation=lambda delay: calls.append(("schedule", delay)),
        _update_top_status=lambda: calls.append(("status", None)),
        sync_status="",
    )

    RoleRunManager._finish_oras_live_reconciliation(
        manager, 4, "run", 8, None, snapshot, None, snapshot.battle,
    )

    write = next(value for name, value in calls if name == "write")
    changes, automatic, base_game = write
    assert len(changes) == 1
    assert changes[0].pokemon_identity == "79:99:20:30"
    assert (changes[0].old_role, changes[0].new_role) == ("Mago", "Asesino")
    assert automatic is True and base_game is after
    assert not any(name == "publish" for name, _value in calls)
    assert ("pc", (before, after)) in calls
    assert len(manager._oras_live_system_role_assignment_ids) == (1 if writer_started else 0)
    if not writer_started:
        assert ("schedule", 250) in calls


def test_bdsp_pc_poll_only_runs_while_the_pc_page_is_visible() -> None:
    game = _game(21)
    callbacks: list[object] = []
    reads: list[tuple[SaveGameData, SaveGameData, bool]] = []
    events: list[str] = []
    manager = SimpleNamespace(
        active_page="pc", _oras_live_active=True, current_game=game,
        _session_generation=3, _oras_pc_reconcile_in_progress=False,
        _bdsp_pc_poll_after_id=None,
        _active_azahar_realtime_key=lambda: "bdsp",
        _floating_bar_is_visible=lambda: False,
        _record_bdsp_ui_event=lambda event, **_fields: events.append(event),
        _schedule_oras_external_pc_reconcile=lambda before, after, force=False: reads.append(
            (before, after, force)
        ),
        after=lambda _delay, callback: callbacks.append(callback) or "poll-id",
        after_cancel=lambda _after_id: None,
    )
    manager._cancel_bdsp_pc_poll = lambda: RoleRunManager._cancel_bdsp_pc_poll(manager)
    manager._bdsp_pc_poll_is_active = lambda: RoleRunManager._bdsp_pc_poll_is_active(manager)
    manager._schedule_bdsp_pc_poll = lambda delay=2500: RoleRunManager._schedule_bdsp_pc_poll(
        manager, delay,
    )

    RoleRunManager._schedule_bdsp_pc_poll(manager, 200)
    assert manager._bdsp_pc_poll_after_id == "poll-id"
    callbacks.pop(0)()
    assert events == ["pc-poll"]
    assert reads == [(game, game, True)]

    manager._oras_pc_reconcile_in_progress = True
    RoleRunManager._schedule_bdsp_pc_poll(manager, 200)
    callbacks.pop(0)()
    assert reads == [(game, game, True)]
    assert len(callbacks) == 1

    manager.active_page = "team"
    RoleRunManager._schedule_bdsp_pc_poll(manager, 200)
    assert manager._bdsp_pc_poll_after_id is None


def test_bdsp_pc_to_pc_poll_repaints_only_when_the_projection_changes(tmp_path) -> None:
    save = tmp_path / "main"
    save.write_bytes(b"save")
    stored = _pokemon(21)
    stored.box, stored.box_slot, stored.slot = 1, 1, 1
    pc = _pc_data()
    pc.boxes[0].pokemon = [stored]
    moved = SavePokemon(
        slot=2, species_id=stored.species_id, species=stored.species,
        nickname=stored.nickname, level=stored.level, held_item=stored.held_item,
        ability=stored.ability, moves=list(stored.moves), move_ids=list(stored.move_ids),
        is_egg=stored.is_egg, markings=list(stored.markings), role=stored.role,
        role_symbol=stored.role_symbol, box=2, box_slot=2,
        pid=stored.pid, tid=stored.tid, sid=stored.sid,
    )
    renders: list[str] = []
    polls: list[str] = []
    events: list[tuple[str, dict[str, object]]] = []
    manager = SimpleNamespace(
        project=SimpleNamespace(slug="run"),
        current_save=SimpleNamespace(path=save),
        current_game=SaveGameData("SP", "SAV8BS", 8, "Lucía", [], {}),
        _session_generation=1, _oras_pc_reconcile_last_key=None,
        _oras_pc_reconcile_in_progress=False, _oras_pc_reconcile_token=0,
        _pc_cache=pc, _pc_cache_signature=RoleRunManager._save_file_signature(save),
        _oras_live_pc_overrides={}, _oras_live_pc_empty_overrides=set(),
        _pokemon_identity=lambda pokemon: "" if pokemon is None else (
            f"{pokemon.species_id}:{pokemon.pid}:{pokemon.tid}:{pokemon.sid}"
        ),
        _pending_team_changes=lambda: [],
        _project_pc_box_pokemon=lambda data, box: [],
        _save_file_signature=RoleRunManager._save_file_signature,
        _floating_bar_is_visible=lambda: False,
        _main_ui_dirty_while_floating=False, active_page="pc",
        _smooth_render_page=lambda **_kwargs: renders.append("render"),
        _schedule_bdsp_pc_poll=lambda: polls.append("poll"),
        _active_azahar_realtime_key=lambda: "bdsp",
        _active_azahar_realtime_label=lambda: "Perla Reluciente",
        _record_bdsp_ui_event=lambda event, **fields: events.append((event, fields)),
        _update_top_status=lambda: None,
        _show_live_sync_toast=lambda *_args: None,
        save_engine=SimpleNamespace(read_boxes=lambda _path: pc),
        realtime_core=SimpleNamespace(
            read_pc=lambda _anchors, **_kwargs: (
                SimpleNamespace(), 0x440000, {(2, 2): moved},
            )
        ),
        after=lambda _delay, callback: callback(), sync_status="",
    )

    with patch("app.ui.threading.Thread", _ImmediateThread):
        RoleRunManager._schedule_oras_external_pc_reconcile(
            manager, manager.current_game, manager.current_game, force=True,
        )
        RoleRunManager._schedule_oras_external_pc_reconcile(
            manager, manager.current_game, manager.current_game, force=True,
        )

    assert manager._oras_live_pc_empty_overrides == set()
    assert manager._oras_live_pc_overrides == {}
    assert manager._pc_cache.boxes[0].pokemon == []
    assert manager._pc_cache.boxes[1].pokemon[0].level == 12
    assert manager._pc_cache.boxes[1].pokemon[0].box_slot == 2
    assert renders == ["render"]
    assert polls == ["poll", "poll"]
    applied = [fields for event, fields in events if event == "pc-reconcile-applied"]
    assert [fields["changed"] for fields in applied] == [True, False]


@pytest.mark.parametrize("game_key", ["oras", "xy", "sm", "usum", "bdsp"])
def test_save_watcher_rearms_every_registered_realtime_backend(tmp_path, game_key: str) -> None:
    save_path = tmp_path / "main"
    save_path.write_bytes(b"save")
    game = _game(21)
    scheduled: list[int] = []
    ui_events: list[tuple[str, dict[str, object]]] = []
    manager = SimpleNamespace(
        _session_generation=5,
        _shell_built=True,
        active_page="team",
        current_save=SimpleNamespace(path=save_path),
        current_game=_game(7),
        save_engine=SimpleNamespace(
            key=game_key,
            read=lambda _path: game,
            valid_moves=lambda _path: {1, 2, 3},
        ),
        save_service=SimpleNamespace(inspect=lambda _path: SimpleNamespace(path=save_path)),
        run=SimpleNamespace(pending_changes=[], save_path=save_path),
        engine=SimpleNamespace(set_allowed_moves=lambda _moves: None),
        _oras_live_active=True,
        _oras_live_monitor_after_id="old-monitor",
        _oras_live_monitor_in_progress=False,
        bdsp_realtime_adapter=SimpleNamespace(
            record_ui_event=lambda event, **fields: ui_events.append((event, fields)),
        ),
        _active_azahar_realtime_key=lambda: game_key,
        _record_bdsp_ui_event=RoleRunManager._record_bdsp_ui_event.__get__(
            None, RoleRunManager,
        ),
        _clear_oras_live_auto_apply=lambda: None,
        _clear_oras_live_reconciliation=lambda: None,
        _sync_obs_state=lambda _game: {"status": "ok"},
        sync_status="",
        sprite_pil_cache={300: object()},
        _load_sprite_async=lambda _pokemon: None,
        _retry_placeholder_sprites=lambda: None,
        _pc_cache=object(),
        _pc_cache_signature=object(),
        _smooth_render_page=lambda **_kwargs: None,
        _schedule_team_integrity_check=lambda: None,
        _schedule_oras_live_reconciliation=lambda delay: scheduled.append(delay),
        _update_top_status=lambda: None,
    )
    # SimpleNamespace no aplica automáticamente el descriptor de instancia.
    manager._record_bdsp_ui_event = lambda event, **fields: (
        RoleRunManager._record_bdsp_ui_event(manager, event, **fields)
    )

    RoleRunManager._reload_from_watched_save(manager, save_path, generation=5)

    assert scheduled == [650]
    assert manager.current_game is game
    if game_key == "bdsp":
        assert ui_events == [("save-watcher-reload", {
            "live_active": True,
            "monitor_scheduled": True,
            "monitor_in_progress": False,
        })]
    else:
        assert ui_events == []


def test_bdsp_pc_reconcile_publishes_live_metadata_when_identity_did_not_move(
    tmp_path,
) -> None:
    """La ficha del save no puede ocultar metadatos demostrados por el PB8 vivo."""
    save = tmp_path / "main"
    save.write_bytes(b"save")
    stored = _pokemon(21)
    stored.species_id = 397
    stored.species = "Staravia"
    stored.nickname = "Ornita"
    stored.pid = 0xA001
    stored.box = stored.box_slot = stored.slot = 8
    pc = _pc_data()
    pc.boxes[0].pokemon = [stored]

    live = SavePokemon(
        slot=8, species_id=stored.species_id, species=stored.species,
        nickname=stored.nickname, level=15, held_item=stored.held_item,
        ability=stored.ability, moves=list(stored.moves),
        move_ids=list(stored.move_ids), is_egg=False,
        markings=list(stored.markings), role=stored.role,
        role_symbol=stored.role_symbol, box=1, box_slot=8,
        pid=stored.pid, tid=stored.tid, sid=stored.sid,
        nature="Huraña", stat_nature="Huraña",
        stats={"hp": 44, "attack": 31, "defense": 21, "sp_attack": 19,
               "sp_defense": 18, "speed": 30},
        ivs={"hp": 23, "attack": 13, "defense": 29, "sp_attack": 17,
             "sp_defense": 8, "speed": 8},
        evs={"hp": 0, "attack": 0, "defense": 0, "sp_attack": 0,
             "sp_defense": 0, "speed": 0},
    )
    renders: list[str] = []
    manager = SimpleNamespace(
        project=SimpleNamespace(slug="run"),
        current_save=SimpleNamespace(path=save),
        current_game=SaveGameData("SP", "SAV8BS", 8, "Lucía", [], {}),
        _session_generation=1, _oras_pc_reconcile_last_key=None,
        _oras_pc_reconcile_in_progress=False, _oras_pc_reconcile_token=0,
        _pc_cache=pc, _pc_cache_signature=RoleRunManager._save_file_signature(save),
        _oras_live_pc_overrides={}, _oras_live_pc_empty_overrides=set(),
        _pokemon_identity=lambda pokemon: "" if pokemon is None else (
            f"{pokemon.species_id}:{pokemon.pid}:{pokemon.tid}:{pokemon.sid}"
        ),
        _pending_team_changes=lambda: [],
        _project_pc_box_pokemon=lambda data, box: list(data.boxes[box - 1].pokemon),
        _save_file_signature=RoleRunManager._save_file_signature,
        _floating_bar_is_visible=lambda: False,
        _main_ui_dirty_while_floating=False, active_page="pc",
        _smooth_render_page=lambda **_kwargs: renders.append("render"),
        _schedule_bdsp_pc_poll=lambda: None,
        _active_azahar_realtime_key=lambda: "bdsp",
        _active_azahar_realtime_label=lambda: "Perla Reluciente",
        _record_bdsp_ui_event=lambda *_args, **_kwargs: None,
        _update_top_status=lambda: None,
        _show_live_sync_toast=lambda *_args: None,
        save_engine=SimpleNamespace(read_boxes=lambda _path: pc),
        realtime_core=SimpleNamespace(
            read_pc=lambda _anchors, **_kwargs: (
                SimpleNamespace(), 0x440000, {(1, 8): live},
            )
        ),
        after=lambda _delay, callback: callback(), sync_status="",
    )

    with patch("app.ui.threading.Thread", _ImmediateThread):
        RoleRunManager._schedule_oras_external_pc_reconcile(
            manager, manager.current_game, manager.current_game, force=True,
        )

    published = manager._pc_cache.boxes[0].pokemon[0]
    assert published.nature == "Huraña"
    assert published.stats == live.stats
    assert published.ivs == live.ivs
    assert published.evs == live.evs
    projected = RoleRunManager._project_pc_box_pokemon(manager, manager._pc_cache, 1)[0]
    assert projected.nature == "Huraña"
    assert projected.stats == live.stats
    assert projected.ivs == live.ivs
    assert projected.evs == live.evs
    assert renders == ["render"]


def test_save_watcher_does_not_arm_a_non_realtime_backend(tmp_path) -> None:
    save_path = tmp_path / "main"
    save_path.write_bytes(b"save")
    game = _game(21)
    scheduled: list[int] = []
    manager = SimpleNamespace(
        _session_generation=5,
        _shell_built=True,
        active_page="team",
        current_save=SimpleNamespace(path=save_path),
        current_game=_game(7),
        save_engine=SimpleNamespace(
            key="dp", read=lambda _path: game, valid_moves=lambda _path: {1},
        ),
        save_service=SimpleNamespace(inspect=lambda _path: SimpleNamespace(path=save_path)),
        run=SimpleNamespace(pending_changes=[], save_path=save_path),
        engine=SimpleNamespace(set_allowed_moves=lambda _moves: None),
        _oras_live_active=True,
        _oras_live_monitor_after_id=None,
        _oras_live_monitor_in_progress=False,
        _active_azahar_realtime_key=lambda: "",
        _record_bdsp_ui_event=lambda *_args, **_kwargs: None,
        _clear_oras_live_auto_apply=lambda: None,
        _clear_oras_live_reconciliation=lambda: None,
        _sync_obs_state=lambda _game: {"status": "ok"},
        sync_status="",
        sprite_pil_cache={300: object()},
        _load_sprite_async=lambda _pokemon: None,
        _retry_placeholder_sprites=lambda: None,
        _pc_cache=None,
        _pc_cache_signature=None,
        _smooth_render_page=lambda **_kwargs: None,
        _schedule_team_integrity_check=lambda: None,
        _schedule_oras_live_reconciliation=lambda delay: scheduled.append(delay),
        _update_top_status=lambda: None,
    )

    RoleRunManager._reload_from_watched_save(manager, save_path, generation=5)

    assert scheduled == []
