from __future__ import annotations

import struct
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

try:
    import customtkinter  # noqa: F401
except ModuleNotFoundError:
    customtkinter = types.ModuleType("customtkinter")
    customtkinter.CTk = object
    sys.modules["customtkinter"] = customtkinter

from app.models import PendingTeamChange
from app.oras_live import encrypt_pk6
from app.save_engine_client import SaveBox, SaveGameData, SavePCData, SavePokemon
from app.sm_live import (
    PK7_PARTY_SIZE,
    PK7_STORED_SIZE,
    SMLiveError,
    _pc_exact_witnesses_from_saved_matrix,
    _saved_pc_matrix_candidates,
    parse_pk7_boxed,
)
from app.ui import RoleRunManager
from app.win_process_memory import WindowsProcessMemory


def _checksum(data: bytes) -> int:
    return sum(struct.unpack_from("<112H", data, 8)) & 0xFFFF


def _stored_pk7(
    species: int, pid: int, *, tid: int = 11, sid: int = 22,
    moves: tuple[int, int, int, int] = (33, 45, 0, 0),
    marking_value: int = 0,
) -> bytes:
    data = bytearray(PK7_PARTY_SIZE)
    struct.pack_into("<I", data, 0x00, 0xA5A50000 ^ int(pid))
    struct.pack_into("<H", data, 0x04, 0)
    struct.pack_into("<H", data, 0x08, int(species))
    struct.pack_into("<H", data, 0x0C, int(tid))
    struct.pack_into("<H", data, 0x0E, int(sid))
    data[0x14] = 65
    struct.pack_into("<H", data, 0x16, int(marking_value) & 0xFFFF)
    struct.pack_into("<I", data, 0x18, int(pid))
    name = f"M{species}".encode("utf-16le") + b"\0\0"
    data[0x40:0x40 + len(name)] = name
    for offset, move in zip((0x5A, 0x5C, 0x5E, 0x60), moves):
        struct.pack_into("<H", data, offset, int(move))
    struct.pack_into("<I", data, 0x74, 31 | (31 << 5))
    data[0xEC] = 25
    struct.pack_into("<H", data, 0x06, _checksum(data))
    return encrypt_pk6(bytes(data))[:PK7_STORED_SIZE]


def _mon(species: int, pid: int, *, box: int, box_slot: int) -> SavePokemon:
    return SavePokemon(
        slot=box_slot, species_id=species, species=f"Species {species}", nickname=f"Mon {species}",
        level=25, held_item="Ninguno", ability="Ability", moves=["Placaje", "Gruñido", "—", "—"],
        move_ids=[33, 45, 0, 0], is_egg=False, markings=[False] * 6,
        role="SIN ROL", role_symbol="", box=box, box_slot=box_slot,
        pid=pid, tid=11, sid=22,
    )


def _matrix(box_count: int = 2, slot_count: int = 3) -> tuple[bytes, list[SavePokemon]]:
    raw = bytearray(box_count * slot_count * PK7_STORED_SIZE)
    mons = [
        _mon(25, 0x11112222, box=1, box_slot=2),
        _mon(133, 0x33334444, box=2, box_slot=3),
    ]
    for mon in mons:
        index = (mon.box - 1) * slot_count + (mon.box_slot - 1)
        start = index * PK7_STORED_SIZE
        raw[start:start + PK7_STORED_SIZE] = _stored_pk7(mon.species_id, mon.pid)
    return bytes(raw), mons


def test_alpha20_parse_boxed_pk7_reads_identity_moves_and_gen7_markings() -> None:
    # Segundo símbolo activo con color 2: RoleRun debe tratar cualquier color Gen7 como marca presente.
    raw = _stored_pk7(25, 0x12345678, marking_value=(2 << 2))
    pokemon = parse_pk7_boxed(raw, 4, 7, {33: "Placaje", 45: "Gruñido"})
    assert pokemon is not None
    assert pokemon.species_id == 25
    assert pokemon.pid == 0x12345678
    assert pokemon.box == 4 and pokemon.box_slot == 7
    assert pokemon.move_ids == [33, 45, 0, 0]
    assert pokemon.markings[1] is True


def test_sm_boxed_parser_publishes_nature_ivs_and_evs() -> None:
    from app.oras_live import decrypt_pk6_stored, encrypt_pk6_stored
    raw = _stored_pk7(25, 0x12345678)
    plain = bytearray(decrypt_pk6_stored(raw))
    plain[0x1C] = 3
    plain[0x1E:0x24] = bytes((1, 2, 3, 4, 5, 6))
    struct.pack_into("<I", plain, 0x74, sum(value << (index * 5) for index, value in enumerate((7, 8, 9, 10, 11, 12))))
    struct.pack_into("<H", plain, 0x06, _checksum(plain))
    pokemon = parse_pk7_boxed(encrypt_pk6_stored(bytes(plain)), 1, 1, {})
    assert pokemon is not None
    assert pokemon.nature_id == 3 and pokemon.nature
    assert pokemon.ivs["speed"] == 10 and pokemon.ivs["sp_attack"] == 11
    assert pokemon.evs["speed"] == 4 and pokemon.evs["sp_defense"] == 6


def test_alpha20_discovers_pc_matrix_inside_real_main_only_from_positioned_identities() -> None:
    matrix, anchors = _matrix()
    prefix = b"\xA5" * 173
    save = prefix + matrix + (b"\x5A" * 91)
    base, found, parsed = _saved_pc_matrix_candidates(
        save, anchors, box_count=2, box_slot_count=3,
        move_names={33: "Placaje", 45: "Gruñido"},
    )
    assert base == len(prefix)
    assert found == matrix
    assert parsed[(1, 2)] is not None and parsed[(1, 2)].pid == 0x11112222
    assert parsed[(2, 3)] is not None and parsed[(2, 3)].pid == 0x33334444
    assert parsed[(1, 1)] is None


def test_alpha20_refuses_two_equally_valid_pc_matrices_inside_main() -> None:
    matrix, anchors = _matrix()
    save = (b"\xA5" * 31) + matrix + (b"\x7C" * 57) + matrix + (b"\x5A" * 19)
    with pytest.raises(SMLiveError, match="única matriz"):
        _saved_pc_matrix_candidates(
            save, anchors, box_count=2, box_slot_count=3,
            move_names={33: "Placaje", 45: "Gruñido"},
        )


def test_alpha20_indexed_pc_witness_scan_reconstructs_matrix_base_from_multiple_exact_pk7() -> None:
    matrix, anchors = _matrix()
    _base, _found, parsed = _saved_pc_matrix_candidates(
        (b"\xA5" * 9) + matrix, anchors, box_count=2, box_slot_count=3,
        move_names={33: "Placaje", 45: "Gruñido"},
    )
    witnesses = _pc_exact_witnesses_from_saved_matrix(matrix, parsed, box_slot_count=3)
    assert len(witnesses) == 2

    region_base = 0x10000000
    prefix = b"Q" * 4096
    region = prefix + matrix + (b"R" * 1024)
    expected_base = region_base + len(prefix)

    memory = WindowsProcessMemory.__new__(WindowsProcessMemory)
    memory.open_process = lambda _pid: object()
    memory.close_process = lambda _handle: None
    memory.iter_writable_regions = lambda _handle: iter([(region_base, len(region))])
    memory.read = lambda _handle, address, size: region[
        int(address) - region_base:int(address) - region_base + int(size)
    ]

    candidates = memory.find_indexed_patterns_in_anchor_region(
        pid=1, anchor_address=region_base + 32, patterns=witnesses,
    )
    assert candidates[0][0] == expected_base
    assert len(candidates[0][1]) == 2


class _ImmediateThread:
    def __init__(self, *, target, **_kwargs):
        self.target = target

    def start(self) -> None:
        self.target()


def test_alpha20_sm_pc_refresh_uses_saved_anchors_and_passes_actual_dimensions(tmp_path: Path) -> None:
    save = tmp_path / "main"
    save.write_bytes(b"main")
    saved_boxed = _mon(25, 100, box=1, box_slot=1)
    boxes = [SaveBox(1, "Caja 1", [saved_boxed]), SaveBox(2, "Caja 2", [])]
    pc = SavePCData(
        game="Pokémon Sol", box_count=2, box_slot_count=3, current_box=1, boxes=boxes,
        next_open_box=1, next_open_box_slot=2, open_slots=[], raw={},
    )
    party = SavePokemon(
        slot=1, species_id=6, species="Charizard", nickname="Charizard", level=50,
        held_item="Ninguno", ability="Mar Llamas", moves=["A", "B", "C", "D"],
        move_ids=[1, 2, 3, 4], is_egg=False, markings=[False] * 6,
        role="Mago", role_symbol="", pid=300, tid=11, sid=22,
    )
    game = SaveGameData("Pokémon Sol", "SAV7SM", 7, "Timper", [party], {})
    live_boxed = _mon(133, 200, box=1, box_slot=1)
    calls: list[tuple[list[SavePokemon], dict[str, int]]] = []

    def read_pc(anchors, **kwargs):
        calls.append((list(anchors), dict(kwargs)))
        return SimpleNamespace(), 0x34560000, {(1, 1): live_boxed}

    manager = SimpleNamespace(
        project=SimpleNamespace(slug="run"), current_save=SimpleNamespace(path=save), current_game=game,
        _session_generation=1, _oras_pc_reconcile_last_key=None, _oras_pc_reconcile_in_progress=False,
        _oras_pc_reconcile_token=0, _pc_cache=pc,
        _pc_cache_signature=RoleRunManager._save_file_signature(save),
        _oras_live_pc_overrides={}, _oras_live_pc_empty_overrides=set(),
        _pokemon_identity=lambda p: "" if p is None else f"{p.species_id}:{p.pid}",
        _pending_team_changes=lambda: [],
        _project_pc_box_pokemon=lambda data, box: [],  # si SM usara proyección, perdería el ancla real.
        _save_file_signature=RoleRunManager._save_file_signature,
        _floating_bar_is_visible=lambda: False, _main_ui_dirty_while_floating=False,
        active_page="team", _smooth_render_page=lambda **_kwargs: None,
        _active_azahar_realtime_key=lambda: "sm", _active_azahar_realtime_label=lambda: "Sol/Luna",
        save_engine=SimpleNamespace(read_boxes=lambda _path: pc),
        realtime_core=SimpleNamespace(read_pc=read_pc), after=lambda _delay, callback: callback(),
    )

    with patch("app.ui.threading.Thread", _ImmediateThread):
        RoleRunManager._schedule_oras_external_pc_reconcile(manager, game, game, force=True)

    assert len(calls) == 1
    anchors, kwargs = calls[0]
    assert [p.pid for p in anchors] == [100]
    assert kwargs == {"box_count": 2, "box_slot_count": 3}
    # SM publica ya la matriz live completa; no mezcla un override puntual con
    # la proyección obsoleta del save.
    assert manager._oras_live_pc_overrides == {}
    assert manager._pc_cache.raw["live_matrix"] is True
    assert manager._pc_cache.boxes[0].pokemon[0].pid == 200


def test_alpha36_sm_size_changing_pc_writes_are_supported() -> None:
    manager = SimpleNamespace(_active_azahar_realtime_key=lambda: "sm")
    changes = [
        PendingTeamChange(operation="box-to-party", party_slot=2, box=1, box_slot=1),
        PendingTeamChange(operation="party-to-box", party_slot=1, box=1, box_slot=2),
        PendingTeamChange(operation="swap-party-box", party_slot=1, box=1, box_slot=3),
    ]
    assert RoleRunManager._oras_live_unsupported_changes(manager, changes) == []


def test_alpha20_sm_box_role_write_is_blocked_before_touching_pending_changes() -> None:
    boxed = _mon(25, 100, box=1, box_slot=1)
    manager = SimpleNamespace(
        project=object(),
        _active_azahar_realtime_key=lambda: "sm",
        _oras_live_auto_apply_available=lambda: True,
    )
    with patch("app.ui.messagebox.showinfo") as showinfo:
        RoleRunManager._queue_pc_role_change(manager, boxed, "Mago")
    showinfo.assert_called_once()
