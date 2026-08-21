from __future__ import annotations

import struct
import sys
import types
from pathlib import Path

try:
    import customtkinter  # noqa: F401
except ModuleNotFoundError:
    customtkinter = types.ModuleType("customtkinter")
    customtkinter.CTk = object
    sys.modules["customtkinter"] = customtkinter

from app.azahar_rpc import AzaharProcess
from app.ui import RoleRunManager
from app.xy_live import (
    XYLiveReader,
    XYLiveWriter,
    XY_BAG_POUCH_LAYOUT,
    XY_MISC_BADGES_OFFSET,
    XY_MISC_BP_OFFSET,
    XY_MISC_MONEY_OFFSET,
    XY_SAVE_ITEMS_SIZE,
    XY_SAVE_MISC_SIZE,
    XY_TITLE_IDS,
)


class MemoryClient:
    def __init__(self, base: int, raw: bytes | bytearray):
        self.base = int(base)
        self.raw = bytearray(raw)
        self.process = AzaharProcess(1, next(iter(XY_TITLE_IDS)), "kujira-1")

    def read_memory(self, address: int, size: int) -> bytes:
        address = int(address)
        size = int(size)
        start = address - self.base
        if start < 0 or start + size > len(self.raw):
            return b"\0" * size
        return bytes(self.raw[start:start + size])


def put_record(block: bytearray, label: str, slot: int, item_id: int, quantity: int) -> None:
    offset, _size = XY_BAG_POUCH_LAYOUT[label]
    struct.pack_into("<HH", block, offset + slot * 4, int(item_id), int(quantity))


def test_alpha19_bag_identity_survives_quantity_changes_since_last_save() -> None:
    bag = bytearray(XY_SAVE_ITEMS_SIZE)
    put_record(bag, "items", 0, 4, 19)       # guardado decía 21
    put_record(bag, "items", 1, 77, 998)     # guardado decía 999
    put_record(bag, "medicine", 0, 50, 906)  # objetivo: cantidad volátil
    put_record(bag, "medicine", 1, 17, 1)
    put_record(bag, "medicine", 2, 22, 1)
    put_record(bag, "tms", 0, 410, 1)
    witnesses = {
        "items": {0: (4, 21), 1: (77, 999)},
        "medicine": {0: (50, 907), 1: (17, 1), 2: (22, 1)},
        "tms": {0: (410, 1)},
    }

    score = XYLiveWriter._bag_candidate_score(bytes(bag), witnesses, volatile_item_ids=(50,))
    assert score is not None
    # Coinciden por identidad/slot aunque cantidades de objetos no objetivo hayan cambiado.
    assert score[0] >= 3


def test_alpha19_bag_base_can_be_proved_from_live_tm_anchor() -> None:
    bag = bytearray(XY_SAVE_ITEMS_SIZE)
    put_record(bag, "items", 0, 4, 2)
    put_record(bag, "medicine", 0, 50, 6)
    put_record(bag, "tms", 0, 410, 1)
    bag_base = 0x08C32140
    client = MemoryClient(bag_base, bag)
    reader = XYLiveReader(Path("missing.json"), client_factory=lambda: client, stable_delay=0)
    writer = XYLiveWriter(reader, move_pp_for=lambda _move: 10)
    tm_offset = XY_BAG_POUCH_LAYOUT["tms"][0]
    writer._locate_tm_inventory_base = lambda _client, _process, _saved: bag_base + tm_offset  # type: ignore[method-assign]

    witnesses = {
        "items": {0: (4, 99)},       # cantidad deliberadamente obsoleta
        "medicine": {0: (50, 907)}, # objetivo deliberadamente obsoleto
        "tms": {0: (410, 1)},
    }
    located = writer._locate_bag_base(
        client, client.process, witnesses, volatile_item_ids=(50,),
    )
    assert located == bag_base


def test_alpha19_money_local_validation_tolerates_unrelated_misc_changes() -> None:
    saved = bytearray(XY_SAVE_MISC_SIZE)
    live = bytearray(XY_SAVE_MISC_SIZE)
    struct.pack_into("<I", saved, XY_MISC_MONEY_OFFSET, 123456)
    saved[XY_MISC_BADGES_OFFSET] = 1
    struct.pack_into("<H", saved, XY_MISC_BP_OFFSET, 7)
    name = "Serena".encode("utf-16le")
    saved[0x10:0x10 + len(name)] = name
    live[:] = saved
    # Cambios ajenos a dinero/medallas/nombre/BP que hacían frágil la huella global.
    for i in range(0x60, 0xC0):
        live[i] = (i * 17) & 0xFF

    assert XYLiveWriter._misc_write_local_score(bytes(live), bytes(saved)) is not None


def test_alpha19_floating_bar_preserves_existing_exstyles_when_noactivate_is_added() -> None:
    style = 0x00000080 | 0x00080000
    result = RoleRunManager._floating_noactivate_exstyle(style)
    assert result & 0x08000000
    assert result & style == style
