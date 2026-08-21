from __future__ import annotations

from types import SimpleNamespace

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


def test_non_oras_badges_remain_manual_for_future_engines() -> None:
    manager = SimpleNamespace(save_engine=SimpleNamespace(key="bdsp"))
    assert RoleRunManager._counter_is_automatic(manager, "medallas") is False


def test_sm_kahuna_badges_are_marked_as_automatic_counter() -> None:
    manager = SimpleNamespace(save_engine=SimpleNamespace(key="sm"))
    assert RoleRunManager._counter_is_automatic(manager, "medallas") is True
    assert RoleRunManager._counter_is_automatic(manager, "vidas") is False
