from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.ui import RoleRunManager
from app.oras_live import load_oras_move_metadata


class _ImmediateThread:
    def __init__(self, *, target, daemon, **_kwargs):
        self._target = target

    def start(self) -> None:
        self._target()


def _manager(tmp_path: Path, *, reader):
    save = tmp_path / "main"
    save.write_bytes(b"save")
    loaded: list[tuple[object, dict[int, int], str]] = []
    failed: list[bool] = []
    errors: list[tuple[str, str]] = []
    reads: list[tuple[dict[int, int], Path | None]] = []

    def read_tm_inventory(saved, save_path=None):
        reads.append((dict(saved), save_path))
        return reader(saved, save_path)

    manager = SimpleNamespace(
        save_engine=SimpleNamespace(
            key="oras", read_inventory=lambda _path: {328: 1},
        ),
        realtime_core=SimpleNamespace(read_tm_inventory=read_tm_inventory),
        current_save=SimpleNamespace(path=save),
        project=SimpleNamespace(slug="run"),
        run=SimpleNamespace(pending_changes=[]),
        _session_generation=4,
        _sm_tm_inventory_load_in_progress=False,
        _sm_tm_inventory_load_token=0,
        _live_write_in_progress=False,
        _live_sync_in_progress=False,
        _oras_live_monitor_in_progress=False,
        _oras_live_active=True,
        sync_status="✓ Omega Rubí enlazado",
        _pending_adjusted_tm_inventory=lambda inventory: dict(inventory),
        _update_top_status=lambda: None,
        _show_live_sync_toast=lambda *_args: None,
        _show_busy_indicator=lambda *_args, **_kwargs: None,
        _hide_busy_indicator=lambda *_args: None,
        _dialog_parent=lambda: None,
        after=lambda _delay, callback: callback(),
    )
    return manager, save, loaded, failed, errors, reads


def test_oras_tm_selector_rejects_stale_save_inventory_when_live_read_fails(
    tmp_path,
) -> None:
    def fail_live_read(_saved, _save_path):
        raise RuntimeError("la mochila RAM no superó la doble lectura")

    manager, save, loaded, failed, errors, reads = _manager(
        tmp_path, reader=fail_live_read,
    )
    profile = SimpleNamespace(source="rom-oras")

    with (
        patch("app.ui.threading.Thread", _ImmediateThread),
        patch(
            "app.ui.messagebox.showerror",
            side_effect=lambda title, message, **_kwargs: errors.append((title, message)),
        ),
    ):
        RoleRunManager._start_live_tm_inventory_load(
            manager,
            None,
            -1,
            replace_existing=False,
            profile=profile,
            on_loaded=lambda selected, inventory, source: loaded.append(
                (selected, inventory, source)
            ),
            on_failed=lambda: failed.append(True),
        )

    assert reads == [({328: 1}, save)]
    assert loaded == []
    assert failed == [True]
    assert manager._sm_tm_inventory_load_in_progress is False
    assert len(errors) == 1
    assert "no usará el último guardado" in errors[0][1]
    assert "doble lectura" in errors[0][1]


def test_oras_tm_selector_uses_only_validated_live_inventory(tmp_path) -> None:
    def return_live_inventory(_saved, _save_path):
        return {328: 1, 618: 1}, object(), 1

    manager, save, loaded, failed, errors, reads = _manager(
        tmp_path, reader=return_live_inventory,
    )
    profile = SimpleNamespace(source="rom-oras")

    with (
        patch("app.ui.threading.Thread", _ImmediateThread),
        patch(
            "app.ui.messagebox.showerror",
            side_effect=lambda title, message, **_kwargs: errors.append((title, message)),
        ),
    ):
        RoleRunManager._start_live_tm_inventory_load(
            manager,
            None,
            -1,
            replace_existing=False,
            profile=profile,
            on_loaded=lambda selected, inventory, source: loaded.append(
                (selected, inventory, source)
            ),
            on_failed=lambda: failed.append(True),
        )

    assert reads == [({328: 1}, save)]
    assert failed == []
    assert errors == []
    assert loaded == [(profile, {328: 1, 618: 1}, "RAM viva validada")]


def test_oras_move_metadata_is_pinned_to_oras_and_exposes_water_gun() -> None:
    metadata = load_oras_move_metadata(Path("data/oras_move_metadata.json"))

    assert metadata[55] == {
        "power": 40,
        "accuracy": 100,
        "pp": 25,
        "description_es": "Ataca disparando agua con gran potencia.",
        "type_id": 10,
    }
    assert metadata[379]["power"] is None
    assert metadata[379]["accuracy"] is None
    assert metadata[379]["pp"] == 10


def test_oras_move_metadata_rejects_an_xy_table(tmp_path: Path) -> None:
    wrong = tmp_path / "xy.json"
    wrong.write_text(
        '{"generation": 6, "target_version_group": "x-y", '
        '"moves": {"55": {"power": 40, "accuracy": 100, "pp": 25}}}',
        encoding="utf-8",
    )

    assert load_oras_move_metadata(wrong) == {}


def test_oras_ui_uses_oras_metadata_for_the_owned_tm() -> None:
    manager = SimpleNamespace(
        save_engine=SimpleNamespace(key="oras"),
        oras_move_metadata=load_oras_move_metadata(
            Path("data/oras_move_metadata.json")
        ),
        oras_live_move_pp={},
        _damage_class_for_move=lambda _move_id: "special",
    )

    assert RoleRunManager._draft_move_metadata(manager, 55) == {
        "category": "special",
        "pp": 25,
        "power": 40,
        "accuracy": 100,
        "type_id": 10,
        "description": "Ataca disparando agua con gran potencia.",
    }
