"""La lectura viva del PC de ORAS reintenta antes de dar un error rojo.

La matriz de cajas no se deja localizar mientras el juego la reconstruye —justo
después de una escritura, por ejemplo—. Pulsar REINTENTAR funcionaba, así que el
aviso estaba pidiendo al usuario que hiciera a mano lo que RoleRun puede hacer
sola. Solo se avisa cuando el reintento tampoco lo consigue.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.save_engine_client import SaveBox, SaveGameData, SavePCData, SavePokemon
from app.ui import LIVE_PC_READ_RETRY_DELAYS_MS, RoleRunManager


class _ImmediateThread:
    def __init__(self, *, target, **_kwargs):
        self.target = target

    def start(self) -> None:
        self.target()


def _mon(slot: int, species: int, *, pid: int, box=None, box_slot=None) -> SavePokemon:
    return SavePokemon(
        slot=slot, species_id=species, species=f"Species {species}", nickname=f"Mon {species}",
        level=50, held_item="Ninguno", ability="Ability", moves=["A", "B", "C", "D"],
        move_ids=[1, 2, 3, 4], is_egg=False, markings=[False] * 6,
        role="SIN ROL", role_symbol="", box=box, box_slot=box_slot,
        pid=pid, tid=1, sid=2, current_hp=100, max_hp=100,
    )


def _pc() -> SavePCData:
    boxes = [SaveBox(index, f"Caja {index}", []) for index in range(1, 32)]
    return SavePCData(
        game="Zafiro Alfa", box_count=31, box_slot_count=30, current_box=1, boxes=boxes,
        next_open_box=1, next_open_box_slot=1, open_slots=[], raw={},
    )


def _manager(save: Path, read_pc, *, toasts: list, events: list) -> SimpleNamespace:
    party = [_mon(1, 261, pid=100)]
    game = SaveGameData("ZA", "SAV6AO", 6, "Timper", party, {})
    pc = _pc()
    manager = SimpleNamespace(
        project=SimpleNamespace(slug="run"),
        current_save=SimpleNamespace(path=save), current_game=game,
        _session_generation=1, _oras_pc_reconcile_last_key=None,
        _oras_pc_reconcile_in_progress=False, _oras_pc_reconcile_token=0,
        _oras_pc_read_retries=0,
        _pc_cache=pc, _pc_cache_signature=RoleRunManager._save_file_signature(save),
        _oras_live_pc_overrides={}, _oras_live_pc_empty_overrides=set(),
        _pokemon_identity=lambda pokemon: "" if pokemon is None else (
            f"{pokemon.species_id}:{pokemon.pid}:{pokemon.tid}:{pokemon.sid}"
        ),
        _pending_team_changes=lambda: [],
        _project_pc_box_pokemon=lambda _data, _box, solo_confirmado=False: [],
        _save_file_signature=RoleRunManager._save_file_signature,
        _floating_bar_is_visible=lambda: False,
        _main_ui_dirty_while_floating=False, active_page="pc",
        _smooth_render_page=lambda **_kwargs: None,
        _active_azahar_realtime_key=lambda: "oras",
        _active_azahar_realtime_label=lambda: "Zafiro Alfa",
        _record_bdsp_ui_event=lambda event, **fields: events.append((event, fields)),
        _update_top_status=lambda: None,
        _show_live_sync_toast=lambda title, detail, ok: toasts.append(title),
        save_engine=SimpleNamespace(read_boxes=lambda _path: pc),
        realtime_core=SimpleNamespace(read_pc=read_pc),
        after=lambda _delay, callback: callback(),
        sync_status="",
    )
    manager._schedule_oras_external_pc_reconcile = (
        lambda before, after, force=False: RoleRunManager._schedule_oras_external_pc_reconcile(
            manager, before, after, force=force,
        )
    )
    return manager


def test_a_failed_live_pc_read_retries_before_showing_the_red_error(tmp_path: Path) -> None:
    save = tmp_path / "main"
    save.write_bytes(b"save")
    toasts: list[str] = []
    events: list[tuple[str, object]] = []
    attempts: list[int] = []

    def read_pc(_anchors, **_kwargs):
        attempts.append(1)
        raise RuntimeError(
            "No se pudo localizar de forma segura la matriz viva del PC de ORAS para leerla."
        )

    manager = _manager(save, read_pc, toasts=toasts, events=events)

    with patch("app.ui.threading.Thread", _ImmediateThread):
        RoleRunManager._schedule_oras_external_pc_reconcile(
            manager, manager.current_game, manager.current_game, force=True,
        )

    # Un intento inicial más un reintento por cada retardo declarado.
    assert len(attempts) == 1 + len(LIVE_PC_READ_RETRY_DELAYS_MS)
    # El aviso rojo aparece una sola vez, y solo al final.
    assert toasts == ["NO SE PUDO LEER EL PC DE Zafiro Alfa"]
    assert [event for event, _fields in events].count("pc-reconcile-reread") == len(
        LIVE_PC_READ_RETRY_DELAYS_MS
    )
    # El contador queda limpio para la siguiente lectura.
    assert manager._oras_pc_read_retries == 0


def test_a_live_pc_read_that_recovers_never_shows_the_red_error(tmp_path: Path) -> None:
    save = tmp_path / "main"
    save.write_bytes(b"save")
    toasts: list[str] = []
    events: list[tuple[str, object]] = []
    attempts: list[int] = []

    def read_pc(_anchors, **_kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError(
                "No se pudo localizar de forma segura la matriz viva del PC de ORAS para leerla."
            )
        return SimpleNamespace(), 0x08CA2124, {}

    manager = _manager(save, read_pc, toasts=toasts, events=events)

    with patch("app.ui.threading.Thread", _ImmediateThread):
        RoleRunManager._schedule_oras_external_pc_reconcile(
            manager, manager.current_game, manager.current_game, force=True,
        )

    assert len(attempts) == 2
    assert toasts == []
    assert manager._oras_pc_read_retries == 0
