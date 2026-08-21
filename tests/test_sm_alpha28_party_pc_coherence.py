from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:
    import customtkinter  # noqa: F401
except ModuleNotFoundError:
    customtkinter = types.ModuleType("customtkinter")
    customtkinter.CTk = object
    sys.modules["customtkinter"] = customtkinter

from app.save_engine_client import SaveBox, SaveGameData, SavePCData, SavePokemon
from app.ui import RoleRunManager


def _mon(species: int, pid: int, *, slot: int = 1, box: int | None = None, box_slot: int | None = None) -> SavePokemon:
    return SavePokemon(
        slot=slot, species_id=species, species=f"Species {species}", nickname=f"Mon {species}",
        level=25, held_item="Ninguno", ability="Ability", moves=["A", "B", "C", "D"],
        move_ids=[1, 2, 3, 4], is_egg=False, markings=[False] * 6,
        role="SIN ROL", role_symbol="", box=box, box_slot=box_slot,
        pid=pid, tid=11, sid=22,
    )


class _ImmediateThread:
    def __init__(self, *, target, **_kwargs):
        self.target = target

    def start(self) -> None:
        self.target()


def test_alpha28_sm_publishes_validated_party_before_secondary_role_write() -> None:
    source = (Path(__file__).resolve().parents[1] / "app" / "ui.py").read_text(encoding="utf-8")
    marker = 'if self._active_azahar_realtime_key() == "sm":\n            before_game = self.current_game'
    start = source.index(marker)
    end = source.index('# Alpha.33: la salud de batalla', start)
    branch = source[start:end]

    # La verdad de solo lectura se publica primero. Alpha.29 ya no escribe el rol
    # en esta rama: guarda la intención y espera a la prueba PC host↔guest.
    assert branch.index('_publish_oras_live_snapshot(snapshot') < branch.index('_incoming_oras_role_changes')
    assert '_queue_sm_role_transition' in branch
    assert '_schedule_oras_external_pc_reconcile' in branch
    assert '_save_oras_live_changes(' not in branch


def test_alpha28_pc_reconcile_never_publishes_identity_also_in_current_party(tmp_path: Path) -> None:
    save = tmp_path / "main"
    save.write_bytes(b"main")

    decidueye_party = _mon(724, 0xAABBCCDD, slot=1)
    current = SaveGameData("Pokémon Sol", "SAV7SM", 7, "Timper", [decidueye_party], {})
    pc = SavePCData(
        game="Pokémon Sol", box_count=1, box_slot_count=2, current_box=1,
        boxes=[SaveBox(1, "Caja 1", [])], next_open_box=1, next_open_box_slot=1,
        open_slots=[], raw={},
    )
    # Simula una captura PC individualmente válida pero tomada en el instante
    # anterior: contiene al mismo Decidueye que la party actualmente publicada.
    stale_pc_decidueye = _mon(724, 0xAABBCCDD, slot=1, box=1, box_slot=1)

    delayed: list[tuple[int, object]] = []

    def after(delay: int, callback):
        if int(delay) == 0:
            callback()
        else:
            delayed.append((int(delay), callback))

    manager = SimpleNamespace(
        project=SimpleNamespace(slug="run"), current_save=SimpleNamespace(path=save), current_game=current,
        _session_generation=1, _oras_pc_reconcile_last_key=None, _oras_pc_reconcile_in_progress=False,
        _oras_pc_reconcile_token=0, _pc_cache=pc,
        _pc_cache_signature=RoleRunManager._save_file_signature(save),
        _oras_live_pc_overrides={}, _oras_live_pc_empty_overrides=set(),
        _pokemon_identity=lambda p: "" if p is None else f"{p.species_id}:{p.pid}:{p.tid}:{p.sid}",
        _pending_team_changes=lambda: [],
        _save_file_signature=RoleRunManager._save_file_signature,
        _floating_bar_is_visible=lambda: False, _main_ui_dirty_while_floating=False,
        active_page="pc", _smooth_render_page=lambda **_kwargs: None,
        _active_azahar_realtime_key=lambda: "sm", _active_azahar_realtime_label=lambda: "Sol/Luna",
        _update_top_status=lambda: None, sync_status="",
        save_engine=SimpleNamespace(read_boxes=lambda _path: pc),
        realtime_core=SimpleNamespace(read_pc=lambda _anchors, **_kwargs: (
            SimpleNamespace(), 0x330D9838, {(1, 1): stale_pc_decidueye, (1, 2): None}
        )),
        after=after,
    )

    with patch("app.ui.threading.Thread", _ImmediateThread):
        RoleRunManager._schedule_oras_external_pc_reconcile(manager, current, current, force=True)

    assert manager._oras_live_pc_overrides == {}
    assert manager._oras_live_pc_empty_overrides == set()
    assert "releyendo Equipo/PC" in manager.sync_status
    assert delayed and delayed[0][0] == 220
