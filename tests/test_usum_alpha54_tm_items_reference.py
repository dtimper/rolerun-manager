from __future__ import annotations

import struct
from pathlib import Path

import pytest

from app.azahar_rpc import AzaharProcess
from app.models import PendingTMTeach
from app.save_engine_client import SaveGameData, SavePokemon
from app.usum_live import (
    USUM_ITEMS_BASE_REFERENCE,
    USUM_ITEMS_REFERENCE_READ_SIZE,
    USUM_SAVE_ITEM_BLOCK_SIZE,
    USUMLiveError,
    USUMLiveReader,
    USUMLiveWriter,
)
from app.usum_rom_service import usum_tm_item_id


def _items(tm_number: int = 51) -> bytes:
    raw = bytearray(USUM_SAVE_ITEM_BLOCK_SIZE)
    # Distribuye registros no vacíos por todo el bloque para que el testigo
    # estructural no dependa de grandes zonas a cero.
    generic = (1 | (1 << 10)).to_bytes(4, "little")
    for offset in range(0, len(raw), 4):
        raw[offset:offset + 4] = generic
    item_id = usum_tm_item_id(tm_number)
    assert item_id is not None
    struct.pack_into("<I", raw, 0x40, int(item_id) | (1 << 10))
    return bytes(raw)


def _current(*, held: str = "Ninguno") -> SaveGameData:
    p = SavePokemon(
        slot=1, species_id=115, species="Kangaskhan", nickname="Kangaskhan", level=40,
        held_item=held, ability="Madrugar", moves=["Placaje", "—", "—", "—"],
        move_ids=[33, 0, 0, 0], is_egg=False, markings=[False] * 6,
        role="Líbero", role_symbol="●", pid=0x10101010, tid=11, sid=22,
    )
    return SaveGameData("Pokémon UltraSol", "SAV7USUM", 7, "Tester", [p], {})


class _RPC:
    def __init__(self, live_items: bytes):
        self.live = bytes(live_items) + bytes(USUM_ITEMS_REFERENCE_READ_SIZE - len(live_items))
        self.process = AzaharProcess(88, 0x00040000001B5000, "momiji")
        self.reads: list[tuple[int, int]] = []

    def __enter__(self): return self
    def __exit__(self, *_args): return None
    def process_list(self): return [self.process]
    def set_process(self, process_id: int): assert int(process_id) == 88
    def read_memory(self, address: int, size: int) -> bytes:
        self.reads.append((int(address), int(size)))
        if int(address) == USUM_ITEMS_BASE_REFERENCE:
            return self.live[:int(size)]
        raise AssertionError(f"unexpected RPC read 0x{int(address):X}+{int(size)}")


def _writer(tmp_path: Path, rpc: _RPC) -> USUMLiveWriter:
    reader = USUMLiveReader(Path("missing.json"), client_factory=lambda: rpc, stable_delay=0, snapshot_attempts=1)
    reader._locate_party_base = lambda *_args: 0x33F7FA44
    return USUMLiveWriter(
        reader,
        diagnostic_dir=tmp_path / "diag",
        host_memory_factory=lambda: (_ for _ in ()).throw(
            AssertionError("alpha.54 TM reference proof must not require host/FCRAM")
        ),
    )


def _write_main(tmp_path: Path, items: bytes) -> Path:
    path = tmp_path / "main"
    path.write_bytes(items)
    return path


def test_alpha54_tm_inventory_uses_published_usum_items_offset_without_pc_or_host(tmp_path: Path) -> None:
    saved = _items(1)
    live = bytearray(saved)
    # Simula un cambio vivo no guardado: aparece MT51 en mochila.
    tm51 = usum_tm_item_id(51)
    assert tm51 is not None
    struct.pack_into("<I", live, 0x80, int(tm51) | (1 << 10))
    rpc = _RPC(bytes(live))
    writer = _writer(tmp_path, rpc)

    inventory, process, _attempt = writer.read_tm_inventory_for_game(_current(), _write_main(tmp_path, saved))

    assert inventory[int(tm51)] == 1
    assert process.process_id == 88
    assert writer._tm_guest_inventory_anchor is not None
    assert writer._tm_guest_inventory_anchor[1] == USUM_ITEMS_BASE_REFERENCE
    assert rpc.reads.count((USUM_ITEMS_BASE_REFERENCE, USUM_ITEMS_REFERENCE_READ_SIZE)) == 2


def test_alpha54_tm_teach_revalidates_same_guest_items_reference(tmp_path: Path) -> None:
    items = _items(51)
    rpc = _RPC(items)
    writer = _writer(tmp_path, rpc)
    current = _current()
    writer.read_tm_inventory_for_game(current, _write_main(tmp_path, items))
    tm51 = usum_tm_item_id(51)
    assert tm51 is not None
    change = PendingTMTeach(
        role="Líbero", pokemon="Kangaskhan", species="Kangaskhan", pokemon_slot=1,
        move_slot=0, old_move="Placaje", old_move_id=33, new_move="Puño Certero", new_move_id=264,
        pokemon_identity="115:269488144:11:22", item_id=int(tm51), tm_number=51,
        item_name="MT51", quantity_before=1,
    )
    writer._assert_live_tm_available(rpc, rpc.process, 0x33F7FA44, change)
    # 2 lecturas al demostrar + 2 al revalidar.
    assert rpc.reads.count((USUM_ITEMS_BASE_REFERENCE, USUM_ITEMS_REFERENCE_READ_SIZE)) == 2
    assert rpc.reads.count((USUM_ITEMS_BASE_REFERENCE, USUM_SAVE_ITEM_BLOCK_SIZE)) == 2


def test_alpha54_published_items_reference_rejects_unrelated_memory(tmp_path: Path) -> None:
    saved = _items(1)
    rpc = _RPC(bytes(USUM_SAVE_ITEM_BLOCK_SIZE))
    writer = _writer(tmp_path, rpc)
    with pytest.raises(USUMLiveError):
        writer._prove_tm_guest_inventory_from_reference(
            client=rpc, process=rpc.process, party_base=0x33F7FA44,
            current=_current(), saved_items=saved,
        )


def test_alpha54_live_held_item_is_not_overwritten_by_previous_snapshot(tmp_path: Path) -> None:
    rpc = _RPC(_items(1))
    writer = _writer(tmp_path, rpc)
    incoming = _current(held="Ninguno").party[0]
    previous = _current(held="MT51")

    merged = writer.reader  # reader not involved; use writer helper owner below
    # _preserve_known_labels lives on reader.
    result = merged._preserve_known_labels(incoming, previous)
    assert result.held_item == "Ninguno"
