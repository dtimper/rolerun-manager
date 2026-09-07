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
from app.models import PendingTeamChange
from app.ui import RoleRunManager
from app.xy_live import XYLiveReader, XY_PC_KNOWN_ADDRESS, XY_PC_SIZE, XY_TITLE_IDS


def _pk6(*, species=25, pid=0x11223344, tid=123, sid=456, nickname="Pika") -> bytes:
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
        self.reads: list[tuple[int, int]] = []

    def __enter__(self): return self
    def __exit__(self, *_): return None
    def process_list(self): return [self.process]
    def set_process(self, _pid): return None

    def read_memory(self, address: int, size: int) -> bytes:
        self.reads.append((int(address), int(size)))
        out = bytearray(size)
        end = address + size
        for base, data in self.regions.items():
            a = max(address, base)
            b = min(end, base + len(data))
            if a < b:
                out[a-address:b-address] = data[a-base:b-base]
        return bytes(out)


def _mon(slot: int, species: int, *, pid: int, box=None, box_slot=None, role="SIN ROL") -> SavePokemon:
    return SavePokemon(
        slot=slot, species_id=species, species=f"Species {species}", nickname=f"Mon {species}",
        level=50, held_item="Ninguno", ability="Ability", moves=["A", "B", "C", "D"],
        move_ids=[1, 2, 3, 4], is_egg=False, markings=[False] * 6,
        role=role, role_symbol="", box=box, box_slot=box_slot,
        pid=pid, tid=1, sid=2, current_hp=100, max_hp=100,
    )


def _game(*party: SavePokemon) -> SaveGameData:
    return SaveGameData("X", "SAV6XY", 6, "Timper", list(party), {})


def _empty_pc() -> SavePCData:
    boxes = [SaveBox(index, f"Caja {index}", []) for index in range(1, 32)]
    open_slots = [(box, slot) for box in range(1, 32) for slot in range(1, 31)]
    return SavePCData(
        game="X", box_count=31, box_slot_count=30, current_box=1, boxes=boxes,
        next_open_box=1, next_open_box_slot=1, open_slots=open_slots, raw={},
    )


class _ImmediateThread:
    def __init__(self, *, target, **_kwargs): self.target = target
    def start(self) -> None: self.target()


def test_xy_alpha12_reads_first_live_deposit_even_when_saved_pc_has_no_anchors() -> None:
    pc = bytearray(XY_PC_SIZE)
    deposited = _pk6(species=133, pid=0xABCDEF01, nickname="Eevee")[:PK6_STORED_SIZE]
    # Simula que el usuario dejó su primer Pokémon en Caja 1 / hueco 1 después
    # del último guardado, por lo que RoleRun no dispone de anchors del main.
    pc[:PK6_STORED_SIZE] = deposited
    fake = _MemoryClient({XY_PC_KNOWN_ADDRESS: pc})
    reader = XYLiveReader(Path("missing.json"), client_factory=lambda: fake, stable_delay=0)

    process, base, slots = reader.read_pc([])

    assert process.name == "kujira-1"
    assert base == XY_PC_KNOWN_ADDRESS
    assert slots[(1, 1)] is not None
    assert slots[(1, 1)].species_id == 133
    assert slots[(1, 1)].pid == 0xABCDEF01
    assert any(address == XY_PC_KNOWN_ADDRESS and size == XY_PC_SIZE for address, size in fake.reads)


def test_xy_alpha12_external_deposit_populates_pc_when_last_main_was_empty(tmp_path: Path) -> None:
    save = tmp_path / "main"
    save.write_bytes(b"save")
    pc = _empty_pc()
    outgoing = _mon(1, 133, pid=200, role="Mago")
    live_boxed = _mon(1, 133, pid=200, box=1, box_slot=1, role="Mago")
    after = _game(_mon(1, 6, pid=300, role="Líbero"))
    before = _game(outgoing, _mon(2, 6, pid=300, role="Líbero"))

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
        realtime_core=SimpleNamespace(read_pc=lambda anchors: (SimpleNamespace(), XY_PC_KNOWN_ADDRESS, {(1, 1): live_boxed})),
        after=lambda _delay, callback: callback(),
    )

    with patch("app.ui.threading.Thread", _ImmediateThread):
        RoleRunManager._schedule_oras_external_pc_reconcile(manager, before, after)

    assert manager._oras_live_pc_overrides[(1, 1)].species_id == 133
    assert manager._oras_live_pc_overrides[(1, 1)].pid == 200


def test_xy_alpha8_send_to_pc_queues_exact_live_destination_without_local_projection() -> None:
    pokemon = _mon(1, 25, pid=100, role="Asesino")
    companion = _mon(2, 6, pid=200)
    requested: list[set[int]] = []
    manager = SimpleNamespace(
        current_game=_game(pokemon, companion),
        run=SimpleNamespace(pending_changes=[]),
        _pc_cache=object(),
        active_page="team",
        _active_azahar_realtime_key=lambda: "xy",
        _active_azahar_realtime_label=lambda: "X/Y",
        _oras_live_auto_apply_available=lambda: True,
        _projected_party=lambda: [pokemon, companion],
        _pokemon_snapshot=lambda mon: {"species_id": mon.species_id, "pid": mon.pid},
        _effective_role=lambda _mon: ("Asesino", "▲"),
        _pokemon_identity=lambda mon: f"{mon.species_id}:{mon.pid}:{mon.tid}:{mon.sid}",
        _pc_box_witnesses=lambda box, slot: ((2, "133:300:1:2"),),
        _request_oras_live_auto_apply_since=lambda before: requested.append(set(before)),
        _update_top_status=lambda: None,
        _sync_live_layout=lambda: None,
        _smooth_render_page=lambda **_kwargs: None,
    )

    RoleRunManager.send_pokemon_to_pc(manager, pokemon, ask=False, destination=(1, 5))

    assert len(manager.run.pending_changes) == 1
    change = manager.run.pending_changes[0]
    assert change.operation == "party-to-box"
    assert change.party_slot == 1
    assert (change.box, change.box_slot) == (1, 5)
    assert change.outgoing_identity == "25:100:1:2"
    assert change.box_witnesses == ((2, "133:300:1:2"),)
    assert requested == [set()]
    assert manager._pc_cache is None


def test_xy_all_team_pc_operations_cross_the_live_ui_gate() -> None:
    manager = SimpleNamespace(_active_azahar_realtime_key=lambda: "xy")
    operations = (
        "move-box-slot", "party-to-box", "box-to-party",
        "swap-party-box", "replace-fainted",
        # 2026-09-05: XYLiveWriter._apply_pc_swap añade el intercambio entre
        # dos casillas ocupadas del PC, con el mismo contrato ya validado
        # para ORAS. Sin esta entrada la compuerta lo rechazaba antes de
        # llegar al escritor.
        "swap-box-slots",
    )

    for operation in operations:
        change = PendingTeamChange(operation=operation, party_slot=1)
        assert RoleRunManager._oras_live_unsupported_changes(manager, [change]) == []


def test_oras_party_resize_crosses_the_live_ui_gate() -> None:
    """El bug real del 30-08-2026: ORASLiveWriter._apply_party_resize ya
    existía y estaba testeado, pero esta compuerta de la UI —independiente
    de ORASLiveWriter._unsupported_changes— seguía sin actualizarse. Una
    incorporación se rechazaba aquí, ANTES de llegar al escritor, dejando el
    cambio fantasma en la cola pendiente (Quagsire "incorporado" sin PS,
    aunque la RAM nunca cambiara).
    """
    manager = SimpleNamespace(_active_azahar_realtime_key=lambda: "oras")

    # move-box-slot se sumó el 30-08-2026 con ORASLiveWriter._apply_pc_move.
    for operation in (
        "swap-party-box", "party-to-box", "box-to-party", "replace-fainted", "move-box-slot",
    ):
        change = PendingTeamChange(operation=operation, party_slot=1)
        assert RoleRunManager._oras_live_unsupported_changes(manager, [change]) == []

    change = PendingTeamChange(operation="operacion-inexistente", party_slot=1)
    assert RoleRunManager._oras_live_unsupported_changes(manager, [change]) == [
        "entradas/salidas que cambian el tamaño del equipo",
    ]


def test_xy_pc_witnesses_use_the_live_matrix_shown_by_the_ui() -> None:
    saved = _empty_pc()
    live = _mon(1, 133, pid=200, box=1, box_slot=1)
    manager = SimpleNamespace(
        _pc_cache=saved,
        _oras_live_pc_empty_overrides=set(),
        _oras_live_pc_overrides={(1, 1): live},
        _pending_team_changes=lambda: [],
        _pokemon_identity=lambda pokemon: f"{pokemon.species_id}:{pokemon.pid}",
    )
    manager._project_pc_box_pokemon = lambda data, box, solo_confirmado=False: (
        RoleRunManager._project_pc_box_pokemon(manager, data, box, solo_confirmado=solo_confirmado)
    )

    assert RoleRunManager._pc_box_witnesses(manager, 1, 5) == ((1, "133:200"),)
