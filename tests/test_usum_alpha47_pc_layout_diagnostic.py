from __future__ import annotations

import struct
from pathlib import Path

from app.azahar_rpc import AzaharProcess
from app.oras_live import encrypt_pk6_stored
from app.usum_live import (
    PK7_STORED_SIZE,
    USUM_PC_BOX_BASE_REFERENCE,
    USUM_PC_BOX_COUNT,
    USUM_PC_BOX_SLOT_COUNT,
    USUM_PC_CURRENT_BOX_REFERENCE,
    USUM_SAVE_BOX_LAYOUT_BLOCK_OFFSET,
    USUM_SAVE_BOX_LAYOUT_CURRENT_BOX_OFFSET,
    USUM_SAVE_BOX_LAYOUT_UNLOCKED_OFFSET,
    USUM_SAVE_PC_BLOCK_OFFSET,
    USUM_SAVE_PC_BLOCK_SIZE,
    USUMLiveReader,
    USUMLiveWriter,
)


def _blank() -> bytes:
    return encrypt_pk6_stored(bytes(PK7_STORED_SIZE))


def _valid_matrix() -> bytes:
    return _blank() * (USUM_PC_BOX_COUNT * USUM_PC_BOX_SLOT_COUNT)


class _RPC:
    def __init__(self, matrix: bytes, current_box: int = 0):
        self.matrix = bytes(matrix)
        self.current_box = int(current_box)
        self.process = AzaharProcess(91, 0x00040000001B5000, "momiji")

    def __enter__(self): return self
    def __exit__(self, *_args): return None
    def process_list(self): return [self.process]
    def set_process(self, _process_id: int): return None
    def read_memory(self, address: int, size: int) -> bytes:
        if int(address) == USUM_PC_BOX_BASE_REFERENCE:
            return self.matrix[:int(size)]
        if int(address) == USUM_PC_CURRENT_BOX_REFERENCE and int(size) == 1:
            return bytes([self.current_box & 0xFF])
        raise AssertionError(f"unexpected RPC read 0x{int(address):X}+{int(size)}")


def _writer(tmp_path: Path, rpc: _RPC) -> USUMLiveWriter:
    reader = USUMLiveReader(Path("missing.json"), client_factory=lambda: rpc, stable_delay=0, snapshot_attempts=1)
    return USUMLiveWriter(reader, diagnostic_dir=tmp_path / "diag")


def test_alpha47_bounded_diagnostic_records_boxlayout_and_first_invalid_without_scan(tmp_path: Path) -> None:
    saved_matrix = _valid_matrix()
    live = bytearray(saved_matrix)
    first_invalid_index = 7 * USUM_PC_BOX_SLOT_COUNT  # Caja 8 · slot 1
    start = first_invalid_index * PK7_STORED_SIZE
    live[start:start + PK7_STORED_SIZE] = bytes([0xA7]) * PK7_STORED_SIZE

    save = bytearray(USUM_SAVE_PC_BLOCK_OFFSET + USUM_SAVE_PC_BLOCK_SIZE)
    layout = USUM_SAVE_BOX_LAYOUT_BLOCK_OFFSET
    save[layout + USUM_SAVE_BOX_LAYOUT_UNLOCKED_OFFSET] = 8
    save[layout + USUM_SAVE_BOX_LAYOUT_CURRENT_BOX_OFFSET] = 2
    save[USUM_SAVE_PC_BLOCK_OFFSET:USUM_SAVE_PC_BLOCK_OFFSET + len(saved_matrix)] = saved_matrix
    save_path = tmp_path / "main"
    save_path.write_bytes(save)

    rpc = _RPC(bytes(live), current_box=2)
    writer = _writer(tmp_path, rpc)
    payload = writer._build_pc_layout_diagnostic(
        client=rpc,
        live_raw=bytes(live),
        save_path=save_path,
        guest_base=USUM_PC_BOX_BASE_REFERENCE,
        box_count=USUM_PC_BOX_COUNT,
        box_slot_count=USUM_PC_BOX_SLOT_COUNT,
        party_base=0x33F7FA44,
    )

    assert payload["fcram_scan_attempted"] is False
    assert payload["saved_boxlayout"]["boxes_unlocked_raw"] == 8
    assert payload["saved_boxlayout"]["current_box_raw"] == 2
    assert payload["guest_current_box_reference"]["value"] == 2
    assert payload["contiguous_valid_slot_prefix"] == 7 * 30
    assert payload["contiguous_fully_valid_boxes"] == 7
    first = payload["first_invalid_examples"][0]
    assert (first["box"], first["slot"]) == (8, 1)
    assert first["state"] == "invalid"
    assert first["saved_state"] == "valid-empty"
    assert first["matches_saved_exactly"] is False
    assert payload["per_box"][6]["invalid"] == 0
    assert payload["per_box"][7]["invalid"] == 1


def test_alpha47_diagnostic_does_not_treat_invalid_live_record_as_empty(tmp_path: Path) -> None:
    saved_matrix = _valid_matrix()
    live = bytearray(saved_matrix)
    live[0:PK7_STORED_SIZE] = b"\x55" * PK7_STORED_SIZE
    save = bytearray(USUM_SAVE_PC_BLOCK_OFFSET + USUM_SAVE_PC_BLOCK_SIZE)
    save[USUM_SAVE_PC_BLOCK_OFFSET:USUM_SAVE_PC_BLOCK_OFFSET + len(saved_matrix)] = saved_matrix
    path = tmp_path / "main"
    path.write_bytes(save)

    rpc = _RPC(bytes(live))
    payload = _writer(tmp_path, rpc)._build_pc_layout_diagnostic(
        client=rpc, live_raw=bytes(live), save_path=path,
        guest_base=USUM_PC_BOX_BASE_REFERENCE,
        box_count=USUM_PC_BOX_COUNT, box_slot_count=USUM_PC_BOX_SLOT_COUNT,
        party_base=0x33F7FA44,
    )
    assert payload["per_box"][0]["invalid"] == 1
    assert payload["first_invalid_examples"][0]["state"] == "invalid"
    assert payload["first_invalid_examples"][0]["raw_hex"] == ("55" * PK7_STORED_SIZE)
