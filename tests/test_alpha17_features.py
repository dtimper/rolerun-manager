from __future__ import annotations

import json
import struct
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

from app.azahar_rpc import AzaharProcess
from app.models import PendingInventoryChange
from app.role_rules import allowed_status_move_ids
from app.ui import RoleRunManager
from app.xy_live import (
    XYLiveReader,
    XYLiveWriter,
    XY_BAG_POUCH_LAYOUT,
    XY_INVENTORY_TARGETS,
    XY_MAX_MONEY,
    XY_MISC_BADGES_OFFSET,
    XY_MISC_MONEY_OFFSET,
    XY_SAVE_ITEMS_SIZE,
    XY_SAVE_MISC_SIZE,
    XY_TITLE_IDS,
)
from app.realtime_memory import MemoryCandidateHint
from app.save_engine_client import SaveGameData


def test_alpha17_substitute_is_role_exception_not_draft_category() -> None:
    pools = {
        "asesino_bajar_defensa": [],
        "asesino_subir_ataque": [],
        "mago_bajar_defensa_esp": [],
        "mago_subir_ataque_esp": [],
    }
    damage = {164: "status"}
    assert 164 in allowed_status_move_ids("Asesino", pools, damage, set())
    assert 164 in allowed_status_move_ids("Mago", pools, damage, set())

    roles_path = Path(__file__).parents[1] / "data" / "roles.json"
    roles = json.loads(roles_path.read_text(encoding="utf-8-sig"))
    # La excepción vive en role_rules; no se crea una categoría de drafteo.
    assert "164" not in json.dumps(roles, ensure_ascii=False)
    assert "Sustituto" not in json.dumps(roles, ensure_ascii=False)


class MoveBrowserManager:
    _move_browser_role_compatibility = RoleRunManager._move_browser_role_compatibility
    _allowed_move_ids_for_role = RoleRunManager._allowed_move_ids_for_role

    def __init__(self):
        self.engine = SimpleNamespace(
            pools={
                "asesino_bajar_defensa": [], "asesino_subir_ataque": [],
                "mago_bajar_defensa_esp": [], "mago_subir_ataque_esp": [],
                "tanque_proteccion": [], "tanque_subir_defensa_fisica": [],
                "prisma_subir_defensa_especial": [], "problemas_estado": [],
                "defensa_recuperacion_pasiva": [],
                "global_self_boosts": [], "extra_ataque_fisico": [], "extra_ataque_especial": [],
            },
            damage_classes={164: "status", 10: "physical", 94: "special"},
            speed_status_moves=set(),
            self_healing_damage_moves=set(),
        )

    def _damage_class_for_move(self, move_id: int) -> str:
        return self.engine.damage_classes.get(int(move_id), "unknown")


def test_alpha17_move_browser_uses_same_role_rules() -> None:
    manager = MoveBrowserManager()
    assert manager._move_browser_role_compatibility("Asesino", 164)[0] is True
    assert manager._move_browser_role_compatibility("Mago", 164)[0] is True
    assert manager._move_browser_role_compatibility("Asesino", 10)[0] is True
    assert manager._move_browser_role_compatibility("Asesino", 94)[0] is False
    assert manager._move_browser_role_compatibility("Mago", 94)[0] is True
    assert manager._move_browser_role_compatibility("Mago", 10)[0] is False


class MemoryClient:
    def __init__(self, regions: dict[int, bytes | bytearray]):
        self.regions = {int(base): bytearray(raw) for base, raw in regions.items()}
        self.process = AzaharProcess(1, next(iter(XY_TITLE_IDS)), "kujira-1")
        self.writes: list[tuple[int, bytes]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def process_list(self):
        return [self.process]

    def set_process(self, _pid: int):
        return None

    def read_memory(self, address: int, size: int) -> bytes:
        address = int(address)
        size = int(size)
        out = bytearray(size)
        end = address + size
        for base, data in self.regions.items():
            a = max(address, base)
            b = min(end, base + len(data))
            if a < b:
                out[a - address:b - address] = data[a - base:b - base]
        return bytes(out)

    def write_memory(self, address: int, raw: bytes):
        address = int(address)
        raw = bytes(raw)
        for base, data in self.regions.items():
            offset = address - base
            if 0 <= offset and offset + len(raw) <= len(data):
                data[offset:offset + len(raw)] = raw
                self.writes.append((address, raw))
                return None
        raise AssertionError(f"write outside regions: 0x{address:08X}")


def _put_record(block: bytearray, label: str, slot: int, item_id: int, quantity: int) -> None:
    pocket_offset, _size = XY_BAG_POUCH_LAYOUT[label]
    struct.pack_into("<HH", block, pocket_offset + slot * 4, int(item_id), int(quantity))


def _bag_and_witnesses() -> tuple[bytearray, tuple[tuple[str, int, int, int], ...]]:
    bag = bytearray(XY_SAVE_ITEMS_SIZE)
    # Dos testigos positivos en Items y dos en Medicine; además un par de MTs.
    _put_record(bag, "items", 0, 1, 10)
    _put_record(bag, "items", 1, 77, 2)
    _put_record(bag, "medicine", 0, 17, 3)
    _put_record(bag, "medicine", 1, 50, 1)
    _put_record(bag, "tms", 0, 328, 1)
    _put_record(bag, "tms", 1, 329, 1)
    witnesses = (
        ("items", 0, 1, 10), ("items", 1, 77, 2),
        ("medicine", 0, 17, 3), ("medicine", 1, 50, 1),
        ("tms", 0, 328, 1), ("tms", 1, 329, 1),
    )
    return bag, witnesses


def _dummy_game() -> SaveGameData:
    return SaveGameData(
        game="X", save_type="main", generation=6, trainer="Test", party=[], raw={}
    )


def _patch_capture_and_game(writer: XYLiveWriter) -> None:
    def capture(client, extras):
        extra = {key: client.read_memory(address, size) for key, address, size in extras}
        return (b"\x01",), extra, 1

    writer._capture_stable_state = capture  # type: ignore[method-assign]
    writer._build_game = lambda _slots, current, _process, live_write: current  # type: ignore[method-assign]


def test_alpha17_xy_bag_scanner_finds_arbitrary_base_from_witnesses() -> None:
    bag, raw_witnesses = _bag_and_witnesses()
    bag_base = 0x08C32140
    client = MemoryClient({bag_base: bag})
    reader = XYLiveReader(Path("missing.json"), client_factory=lambda: client, stable_delay=0)
    writer = XYLiveWriter(reader, move_pp_for=lambda _move: 10)
    change = PendingInventoryChange("rare-candy", "Caramelo Raro", 999, raw_witnesses)
    witnesses = writer._xy_inventory_witness_map([change])

    hints = writer._discover_bag(client, witnesses)
    assert any(int(hint.address) == bag_base for hint in hints)
    assert writer._bag_candidate_score(bytes(bag), witnesses) is not None


def test_alpha17_xy_rare_candy_write_changes_only_one_record_and_verifies() -> None:
    bag, raw_witnesses = _bag_and_witnesses()
    bag_base = 0x08C32140
    client = MemoryClient({bag_base: bag})
    reader = XYLiveReader(Path("missing.json"), client_factory=lambda: client, stable_delay=0)
    writer = XYLiveWriter(reader, move_pp_for=lambda _move: 10)
    writer._locate_bag_base = lambda _client, _process, _witnesses: bag_base  # type: ignore[method-assign]
    _patch_capture_and_game(writer)

    change = PendingInventoryChange("rare-candy", "Caramelo Raro", 999, raw_witnesses)
    result = writer.apply(_dummy_game(), [change])

    item_id, label = XY_INVENTORY_TARGETS["rare-candy"]
    pocket_offset, _size = XY_BAG_POUCH_LAYOUT[label]
    # El Caramelo Raro estaba en slot 1 de Medicine.
    assert struct.unpack_from("<HH", client.regions[bag_base], pocket_offset + 4) == (item_id, 999)
    assert len(client.writes) == 1
    assert len(client.writes[0][1]) == 4
    assert result.applied_count == 1


def _saved_misc() -> bytes:
    raw = bytearray(XY_SAVE_MISC_SIZE)
    for index in range(0x50, 0xA0):
        raw[index] = ((index * 41) % 251) + 1
    struct.pack_into("<I", raw, XY_MISC_MONEY_OFFSET, 1234)
    raw[XY_MISC_BADGES_OFFSET] = 1
    return bytes(raw)


def test_alpha17_xy_money_uses_misc_witness_and_writes_exact_four_bytes() -> None:
    misc_base = 0x08C45600
    saved_misc = _saved_misc()
    client = MemoryClient({misc_base: saved_misc})
    reader = XYLiveReader(Path("missing.json"), client_factory=lambda: client, stable_delay=0)
    writer = XYLiveWriter(reader, move_pp_for=lambda _move: 10)
    writer._discover_misc = lambda _client, _saved: (MemoryCandidateHint(misc_base, "test", 0),)  # type: ignore[method-assign]
    _patch_capture_and_game(writer)

    change = PendingInventoryChange(
        "money-max", "Dinero", XY_MAX_MONEY, (), save_misc_witness=saved_misc,
    )
    result = writer.apply(_dummy_game(), [change])

    assert struct.unpack_from("<I", client.regions[misc_base], XY_MISC_MONEY_OFFSET)[0] == XY_MAX_MONEY
    assert client.writes == [(misc_base + XY_MISC_MONEY_OFFSET, struct.pack("<I", XY_MAX_MONEY))]
    assert result.applied_count == 1


def test_alpha18_xy_ui_gate_allows_inventory_changes_to_reach_live_writer() -> None:
    class Gate:
        _oras_live_unsupported_changes = RoleRunManager._oras_live_unsupported_changes

        @staticmethod
        def _active_azahar_realtime_key() -> str:
            return "xy"

    gate = Gate()
    for change in (
        PendingInventoryChange("rare-candy", "Caramelo Raro", 999),
        PendingInventoryChange("max-repel", "Repelente Máximo", 999),
        PendingInventoryChange("money-max", "Dinero", XY_MAX_MONEY),
    ):
        assert gate._oras_live_unsupported_changes([change]) == []
