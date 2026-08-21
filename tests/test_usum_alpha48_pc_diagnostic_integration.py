from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.azahar_rpc import AzaharProcess
from app.oras_live import encrypt_pk6_stored
from app.save_engine_client import SaveGameData, SavePokemon
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
    USUMLiveError,
    USUMLiveReader,
    USUMLiveWriter,
)


def _blank() -> bytes:
    return encrypt_pk6_stored(bytes(PK7_STORED_SIZE))


def _current() -> SaveGameData:
    p = SavePokemon(
        slot=1, species_id=115, species="Kangaskhan", nickname="Kangaskhan", level=40,
        held_item="Ninguno", ability="Madrugar", moves=["Placaje", "—", "—", "—"],
        move_ids=[33, 0, 0, 0], is_egg=False, markings=[False] * 6,
        role="Líbero", role_symbol="●", pid=0x10101010, tid=11, sid=22,
    )
    return SaveGameData("Pokémon UltraSol", "SAV7USUM", 7, "Tester", [p], {})


class _RPC:
    def __init__(self, matrix: bytes):
        self.matrix = bytes(matrix)
        self.process = AzaharProcess(88, 0x00040000001B5000, "momiji")

    def __enter__(self): return self
    def __exit__(self, *_args): return None
    def process_list(self): return [self.process]
    def set_process(self, _process_id: int): return None
    def read_memory(self, address: int, size: int) -> bytes:
        if int(address) == USUM_PC_BOX_BASE_REFERENCE:
            return self.matrix[:int(size)]
        if int(address) == USUM_PC_CURRENT_BOX_REFERENCE and int(size) == 1:
            return b"\x02"
        raise AssertionError(f"unexpected RPC read 0x{int(address):X}+{int(size)}")


def test_alpha48_failed_boxoffset_reaches_main_boxlayout_diagnostic(tmp_path: Path) -> None:
    # Reproduce el caso físico: prefijo válido y Caja 8/slot 1 inválido.
    matrix = bytearray(_blank() * (USUM_PC_BOX_COUNT * USUM_PC_BOX_SLOT_COUNT))
    first_invalid = 7 * USUM_PC_BOX_SLOT_COUNT * PK7_STORED_SIZE
    matrix[first_invalid:first_invalid + PK7_STORED_SIZE] = b"\xA7" * PK7_STORED_SIZE

    saved_matrix = _blank() * (USUM_PC_BOX_COUNT * USUM_PC_BOX_SLOT_COUNT)
    save = bytearray(USUM_SAVE_PC_BLOCK_OFFSET + USUM_SAVE_PC_BLOCK_SIZE)
    layout = USUM_SAVE_BOX_LAYOUT_BLOCK_OFFSET
    save[layout + USUM_SAVE_BOX_LAYOUT_UNLOCKED_OFFSET] = 8
    save[layout + USUM_SAVE_BOX_LAYOUT_CURRENT_BOX_OFFSET] = 2
    save[USUM_SAVE_PC_BLOCK_OFFSET:USUM_SAVE_PC_BLOCK_OFFSET + len(saved_matrix)] = saved_matrix
    save_path = tmp_path / "main"
    save_path.write_bytes(save)

    rpc = _RPC(bytes(matrix))
    reader = USUMLiveReader(Path("missing.json"), client_factory=lambda: rpc, stable_delay=0, snapshot_attempts=1)
    reader._locate_party_base = lambda *_args: 0x33F7FA44
    writer = USUMLiveWriter(reader, diagnostic_dir=tmp_path / "diag")

    captured: dict[str, object] = {}
    def _capture(payload):
        captured.update(payload)
        out = tmp_path / "diag.json"
        out.write_text(json.dumps(payload), encoding="utf-8")
        return out
    writer._save_pc_diagnostic = _capture

    with pytest.raises(USUMLiveError, match="diagnóstico acotado RAM↔main↔BoxLayout"):
        writer.read_pc_for_game(
            _current(), save_path, [],
            box_count=USUM_PC_BOX_COUNT, box_slot_count=USUM_PC_BOX_SLOT_COUNT,
        )

    assert "diagnostic_error" not in captured
    assert captured["stage"] == "alpha48-bounded-pc-layout-diagnostic"
    assert captured["saved_boxlayout"]["boxes_unlocked_raw"] == 8
    assert captured["saved_boxlayout"]["current_box_raw"] == 2
    assert captured["guest_current_box_reference"]["value"] == 2
    assert captured["contiguous_fully_valid_boxes"] == 7
    assert captured["first_invalid_examples"][0]["box"] == 8
    assert captured["first_invalid_examples"][0]["slot"] == 1
