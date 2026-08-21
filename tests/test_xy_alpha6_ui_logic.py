from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

try:
    import customtkinter  # noqa: F401
except ModuleNotFoundError:
    customtkinter = types.ModuleType("customtkinter")
    customtkinter.CTk = object
    sys.modules["customtkinter"] = customtkinter

from app.ui import RoleRunManager


def test_xy_tm_replacement_context_uses_live_core_inventory_and_xy_rom_profile(tmp_path: Path) -> None:
    profile = object()
    core_calls = []
    core = SimpleNamespace(
        read_tm_inventory=lambda saved: core_calls.append(dict(saved)) or ({328: 1, 350: 1}, object(), 1)
    )
    manager = SimpleNamespace(
        save_engine=SimpleNamespace(
            key="xy",
            read_inventory=lambda _path: {328: 1},
        ),
        current_save=SimpleNamespace(path=tmp_path / "main"),
        _oras_live_active=True,
        _get_xy_rom_tm_profile=lambda prompt=False: profile,
        realtime_core=core,
    )
    result = RoleRunManager._tm_replacement_context(manager)
    assert result == (profile, {328: 1, 350: 1})
    assert core_calls == [{328: 1}]
