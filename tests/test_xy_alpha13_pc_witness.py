from __future__ import annotations

import struct
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

from app.azahar_rpc import AzaharProcess
from app.oras_live import PK6_PARTY_SIZE, PK6_STORED_SIZE, _checksum, encrypt_pk6
from app.save_engine_client import SaveBox, SaveGameData, SavePCData, SavePokemon
from app.ui import RoleRunManager
from app.xy_live import XYLiveReader, XY_PC_KNOWN_ADDRESS, XY_PC_SIZE, XY_TITLE_IDS


def _pk6(*, species=25, pid=0x11223344, tid=1, sid=2, nickname="Pika") -> bytes:
    data = bytearray(PK6_PARTY_SIZE)
    struct.pack_into("<I", data, 0, 0x12345678)
    struct.pack_into("<H", data, 8, species)
    struct.pack_into("<H", data, 0x0C, tid)
    struct.pack_into("<H", data, 0x0E, sid)
    struct.pack_into("<I", data, 0x18, pid)
    encoded = nickname.encode("utf-16le")
    data[0x40:0x40 + len(encoded)] = encoded
    struct.pack_into("<4H", data, 0x5A, 33, 45, 0, 0)
    struct.pack_into("<I", data, 0x74, 0x3FFFFFFF)
    struct.pack_into("<H", data, 6, _checksum(data))
    return encrypt_pk6(bytes(data))


class _MemoryClient:
    def __init__(self, regions: dict[int, bytes | bytearray]):
        self.regions = {int(k): bytearray(v) for k, v in regions.items()}
        self.process = AzaharProcess(1, next(iter(XY_TITLE_IDS)), "kujira-1")

    def __enter__(self): return self
    def __exit__(self, *_): return None
    def process_list(self): return [self.process]
    def set_process(self, _pid): return None

    def read_memory(self, address: int, size: int) -> bytes:
        out = bytearray(size)
        end = address + size
        for base, data in self.regions.items():
            a = max(address, base)
            b = min(end, base + len(data))
            if a < b:
                out[a-address:b-address] = data[a-base:b-base]
        return bytes(out)


def _mon(slot: int, species: int, *, pid: int, box=None, box_slot=None) -> SavePokemon:
    return SavePokemon(
        slot=slot, species_id=species, species=f"Species {species}", nickname=f"Mon {species}",
        level=3, held_item="Ninguno", ability="Ability", moves=["A", "B", "—", "—"],
        move_ids=[1, 2, 0, 0], is_egg=False, markings=[False] * 6,
        role="SIN ROL", role_symbol="", box=box, box_slot=box_slot,
        pid=pid, tid=1, sid=2, current_hp=15, max_hp=15,
    )


def _empty_pc() -> SavePCData:
    boxes = [SaveBox(index, f"Caja {index}", []) for index in range(1, 32)]
    return SavePCData(
        game="X", box_count=31, box_slot_count=30, current_box=1, boxes=boxes,
        next_open_box=1, next_open_box_slot=1,
        open_slots=[(b, s) for b in range(1, 32) for s in range(1, 31)], raw={},
    )


class _ImmediateThread:
    def __init__(self, *, target, **_kwargs): self.target = target
    def start(self): self.target()


def test_xy_alpha13_witness_calibrates_shifted_pc_base_and_real_slot() -> None:
    actual_base = XY_PC_KNOWN_ADDRESS - 0x10
    box, slot = 3, 7
    index = (box - 1) * 30 + (slot - 1)
    matrix = bytearray(XY_PC_SIZE)
    matrix[index * PK6_STORED_SIZE:(index + 1) * PK6_STORED_SIZE] = _pk6(
        species=664, pid=0xA1B2C3D4, nickname="Scatterbug",
    )[:PK6_STORED_SIZE]
    fake = _MemoryClient({actual_base: matrix})
    reader = XYLiveReader(Path("missing.json"), client_factory=lambda: fake, stable_delay=0)
    witness = _mon(1, 664, pid=0xA1B2C3D4)

    _process, base, slots = reader.read_pc([witness])

    assert base == actual_base
    assert slots[(box, slot)] is not None
    assert slots[(box, slot)].species_id == 664
    assert slots[(box, slot)].pid == 0xA1B2C3D4


def test_xy_alpha13_external_deposit_passes_outgoing_party_mon_as_unlocated_witness(tmp_path: Path) -> None:
    save = tmp_path / "main"
    save.write_bytes(b"save")
    pc = _empty_pc()
    scatterbug = _mon(1, 664, pid=0xA1B2C3D4)
    other = _mon(2, 6, pid=0x10101010)
    before = SaveGameData("X", "SAV6XY", 6, "Timper", [scatterbug, other], {})
    after = SaveGameData("X", "SAV6XY", 6, "Timper", [other], {})
    captured: list[list[SavePokemon]] = []

    def read_pc(anchors):
        captured.append(list(anchors))
        return SimpleNamespace(), XY_PC_KNOWN_ADDRESS, {(1, 1): None}

    manager = SimpleNamespace(
        project=SimpleNamespace(slug="run"), current_save=SimpleNamespace(path=save),
        _session_generation=1, _oras_pc_reconcile_last_key=None,
        _oras_pc_reconcile_in_progress=False, _oras_pc_reconcile_token=0,
        _pc_cache=pc, _pc_cache_signature=RoleRunManager._save_file_signature(save),
        _oras_live_pc_overrides={}, _oras_live_pc_empty_overrides=set(),
        _pokemon_identity=lambda p: "" if p is None else f"{p.species_id}:{p.pid}",
        _pending_team_changes=lambda: [],
        _project_pc_box_pokemon=lambda data, box, solo_confirmado=False: RoleRunManager._project_pc_box_pokemon(manager, data, box, solo_confirmado=solo_confirmado),
        _save_file_signature=RoleRunManager._save_file_signature,
        _floating_bar_is_visible=lambda: False,
        _main_ui_dirty_while_floating=False, active_page="pc",
        _smooth_render_page=lambda **_kwargs: None,
        _active_azahar_realtime_key=lambda: "xy",
        save_engine=SimpleNamespace(read_boxes=lambda _path: pc),
        realtime_core=SimpleNamespace(read_pc=read_pc),
        after=lambda _delay, callback: callback(),
    )

    with patch("app.ui.threading.Thread", _ImmediateThread):
        RoleRunManager._schedule_oras_external_pc_reconcile(manager, before, after)

    assert captured
    witnesses = [p for p in captured[0] if p.box is None and p.box_slot is None]
    assert len(witnesses) == 1
    assert witnesses[0].species_id == 664
    assert witnesses[0].pid == 0xA1B2C3D4
