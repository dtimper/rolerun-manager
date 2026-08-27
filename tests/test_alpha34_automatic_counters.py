from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.save_engine_client import SavePokemon
from app.ui import RoleRunManager


def _pokemon() -> SavePokemon:
    return SavePokemon(
        slot=1, species_id=398, species="Staraptor", nickname="Ornita", level=70,
        held_item="Ninguno", ability="Intimidación", moves=["A"], move_ids=[1],
        is_egg=False, markings=[True, False, False, False, False, False],
        role="Líbero", role_symbol="", pid=10, tid=1, sid=2, current_hp=0, max_hp=200,
    )


def test_battle_faint_is_scheduled_with_one_second_visual_delay() -> None:
    calls: list[tuple[int, object]] = []
    manager = SimpleNamespace(
        _oras_delayed_faint_after_ids={},
        _oras_delayed_faint_payloads={},
        _pokemon_identity=lambda _pokemon: "dead-1",
        after=lambda delay, callback: calls.append((delay, callback)) or "after-1",
    )

    RoleRunManager._schedule_delayed_faint(manager, _pokemon(), source="battle")

    assert [delay for delay, _callback in calls] == [1000]
    assert manager._oras_delayed_faint_after_ids == {"dead-1": "after-1"}


def test_oras_badges_are_marked_as_automatic_counter() -> None:
    manager = SimpleNamespace(save_engine=SimpleNamespace(key="oras"))
    assert RoleRunManager._counter_is_automatic(manager, "medallas") is True
    assert RoleRunManager._counter_is_automatic(manager, "vidas") is False


def test_bdsp_badges_are_marked_as_automatic_counter() -> None:
    manager = SimpleNamespace(
        save_engine=SimpleNamespace(key="bdsp"),
        current_game=SimpleNamespace(game="SP"),
    )
    assert RoleRunManager._counter_is_automatic(manager, "medallas") is True


def test_brilliant_diamond_badges_are_not_enabled_from_shining_pearl_evidence() -> None:
    manager = SimpleNamespace(
        save_engine=SimpleNamespace(key="bdsp"),
        current_game=SimpleNamespace(game="BD"),
    )
    assert RoleRunManager._counter_is_automatic(manager, "medallas") is False


def test_sm_kahuna_badges_are_marked_as_automatic_counter() -> None:
    manager = SimpleNamespace(save_engine=SimpleNamespace(key="sm"))
    assert RoleRunManager._counter_is_automatic(manager, "medallas") is True
    assert RoleRunManager._counter_is_automatic(manager, "vidas") is False


def _badge_manager(*, game_key: str, badges: int):
    project = SimpleNamespace(slug="run", counters={"medallas": int(badges)})

    def adjust_counter(current, counter, delta, *, source):
        assert current is project
        assert counter == "medallas"
        assert source
        current.counters[counter] += int(delta)

    return SimpleNamespace(
        project=project,
        save_engine=SimpleNamespace(key=game_key),
        project_service=SimpleNamespace(
            adjust_counter=adjust_counter,
            load=lambda _slug: project,
            history=lambda _project: [],
        ),
        run=SimpleNamespace(history=[]),
        current_game=object(),
        active_page="team",
        _active_azahar_realtime_key=lambda: game_key,
        _active_azahar_realtime_label=lambda: {
            "oras": "ORAS", "xy": "X/Y", "sm": "Sol/Luna", "usum": "UltraSol/UltraLuna",
            "bdsp": "Perla Reluciente",
        }[game_key],
        _sync_obs_state=lambda _game: None,
        _refresh_dashboard_counter=lambda _counter: None,
        _floating_bar_last_signature=None,
        _floating_bar_is_visible=lambda: False,
        _render_floating_bar=lambda **_kwargs: None,
    )


def test_unknown_badge_source_cannot_roll_back_newer_live_progress() -> None:
    """Un tick sin evidencia RAM no puede sustituir 1 Kahuna por el main stale=0."""
    manager = _badge_manager(game_key="usum", badges=1)

    changed = RoleRunManager._process_oras_badge_value(manager, 0)

    assert changed is False
    assert manager.project.counters["medallas"] == 1


@pytest.mark.parametrize(("game_key", "fallback"), [
    ("oras", "main · equipos de gimnasio"),
    ("xy", "main X/Y · SUBE (fallback)"),
    ("sm", "main · Z-Crystals (fallback)"),
    ("usum", "main · Z-Crystals (fallback)"),
])
def test_saved_badge_fallback_never_rolls_back_live_progress(game_key: str, fallback: str) -> None:
    manager = _badge_manager(game_key=game_key, badges=2)

    changed = RoleRunManager._process_oras_badge_value(manager, 1, source=fallback)

    assert changed is False
    assert manager.project.counters["medallas"] == 2


@pytest.mark.parametrize(("game_key", "live_source"), [
    ("oras", "Premios líderes · MT/MO"),
    ("xy", "SUBE vivo X/Y · equipos de gimnasio"),
    ("sm", "Z-Crystals vivos · mochila MT validada"),
    ("usum", "Z-Crystals vivos · mochila calibrada estructuralmente"),
    ("bdsp", "SystemFlags vivos · PlayerWork.SaveData"),
])
def test_validated_live_badges_can_roll_back_after_state_load(game_key: str, live_source: str) -> None:
    manager = _badge_manager(game_key=game_key, badges=2)

    changed = RoleRunManager._process_oras_badge_value(manager, 1, source=live_source)

    assert changed is True
    assert manager.project.counters["medallas"] == 1


def test_saved_badges_can_recover_progress_upwards_without_ram() -> None:
    manager = _badge_manager(game_key="usum", badges=0)

    changed = RoleRunManager._process_oras_badge_value(
        manager, 1, source="main · Z-Crystals (fallback)",
    )

    assert changed is True
    assert manager.project.counters["medallas"] == 1


@pytest.mark.parametrize(("game_key", "expected"), [
    ("oras", "medallas"),
    ("xy", "Azahar o Citra"),
    ("sm", "progreso de Kahunas"),
    ("usum", "pendiente de su última prueba física"),
    ("bdsp", "SystemFlags"),
])
def test_realtime_help_describes_current_capabilities(game_key: str, expected: str) -> None:
    text = RoleRunManager._live_runtime_help_text(game_key)
    assert expected in text
    assert "Solo los cambios de rol están habilitados" not in text
    assert "siguen bloqueados" not in text
