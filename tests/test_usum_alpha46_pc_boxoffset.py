from __future__ import annotations

import struct
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
    USUMLiveError,
    USUMLiveReader,
    USUMLiveWriter,
)


def _checksum(data: bytes | bytearray) -> int:
    return sum(struct.unpack_from("<112H", data, 8)) & 0xFFFF


def _boxed(species: int, pid: int) -> bytes:
    data = bytearray(PK7_STORED_SIZE)
    struct.pack_into("<I", data, 0x00, 0xA5C30000 ^ int(pid))
    struct.pack_into("<H", data, 0x04, 0)
    struct.pack_into("<H", data, 0x08, int(species))
    struct.pack_into("<H", data, 0x0C, 11)
    struct.pack_into("<H", data, 0x0E, 22)
    struct.pack_into("<I", data, 0x10, 1000)
    data[0x14] = 1
    struct.pack_into("<I", data, 0x18, int(pid))
    struct.pack_into("<H", data, 0x5A, 33)
    struct.pack_into("<I", data, 0x74, sum(31 << (5 * i) for i in range(6)))
    struct.pack_into("<H", data, 0x06, _checksum(data))
    return encrypt_pk6_stored(bytes(data))


def _matrix() -> bytes:
    blank = encrypt_pk6_stored(bytes(PK7_STORED_SIZE))
    raw = bytearray(blank * (USUM_PC_BOX_COUNT * USUM_PC_BOX_SLOT_COUNT))
    raw[:PK7_STORED_SIZE] = _boxed(133, 0x51515151)
    return bytes(raw)


def _current() -> SaveGameData:
    party = [SavePokemon(
        slot=1, species_id=115, species="Kangaskhan", nickname="Kangaskhan", level=40,
        held_item="Ninguno", ability="Madrugar", moves=["Placaje", "—", "—", "—"],
        move_ids=[33, 0, 0, 0], is_egg=False, markings=[False] * 6,
        role="Líbero", role_symbol="●", pid=0x10101010, tid=11, sid=22,
    )]
    return SaveGameData("Pokémon UltraSol", "SAV7USUM", 7, "Tester", party, {})


class _RPC:
    def __init__(self, matrix: bytes, *, unstable: bool = False):
        self.process = AzaharProcess(88, 0x00040000001B5000, "momiji")
        self.matrix = bytes(matrix)
        self.unstable = bool(unstable)
        self.read_count = 0

    def __enter__(self): return self
    def __exit__(self, *_args): return None
    def process_list(self): return [self.process]
    def set_process(self, process_id: int): assert int(process_id) == 88
    def read_memory(self, address: int, size: int) -> bytes:
        assert int(address) == USUM_PC_BOX_BASE_REFERENCE
        self.read_count += 1
        data = self.matrix[:int(size)]
        if self.unstable and self.read_count == 2:
            changed = bytearray(data)
            changed[-1] ^= 1
            return bytes(changed)
        return data


def _writer(tmp_path: Path, rpc: _RPC) -> USUMLiveWriter:
    reader = USUMLiveReader(
        Path("missing.json"), client_factory=lambda: rpc, stable_delay=0, snapshot_attempts=1,
    )
    reader._locate_party_base = lambda _client, _process, _current: 0x33F7FA44
    return USUMLiveWriter(
        reader,
        diagnostic_dir=tmp_path / "diag",
        host_memory_factory=lambda: (_ for _ in ()).throw(
            AssertionError("CAJAS PC alpha.46 no debe abrir ni escanear memoria host")
        ),
    )


def test_alpha46_pc_browser_reads_published_boxoffset_guest_only_without_fcram_scan(tmp_path: Path) -> None:
    rpc = _RPC(_matrix())
    writer = _writer(tmp_path, rpc)
    writer._resolve_pc_from_direct_pk7_matrix = lambda **_kwargs: (_ for _ in ()).throw(
        AssertionError("CAJAS PC no debe ejecutar el resolver estructural pesado")
    )

    process, base, parsed = writer.read_pc_for_game(
        _current(), tmp_path / "main", [],
        box_count=USUM_PC_BOX_COUNT, box_slot_count=USUM_PC_BOX_SLOT_COUNT,
    )

    assert process.process_id == 88
    assert base == 0x33015AB0
    assert parsed[(1, 1)] is not None and parsed[(1, 1)].species_id == 133
    assert sum(p is not None for p in parsed.values()) == 1
    assert rpc.read_count == 2
    assert writer._pc_last_resolution["fcram_scan_attempted"] is False
    assert writer._pc_last_resolution["host_write_proven"] is False


def test_alpha46_pc_browser_rejects_unstable_reference_without_fallback_scan(tmp_path: Path) -> None:
    rpc = _RPC(_matrix(), unstable=True)
    writer = _writer(tmp_path, rpc)
    writer._resolve_pc_from_direct_pk7_matrix = lambda **_kwargs: (_ for _ in ()).throw(
        AssertionError("no debe haber fallback FCRAM")
    )

    with pytest.raises(USUMLiveError, match="no se hizo ningún escaneo FCRAM"):
        writer.read_pc_for_game(
            _current(), tmp_path / "main", [],
            box_count=USUM_PC_BOX_COUNT, box_slot_count=USUM_PC_BOX_SLOT_COUNT,
        )
    assert writer._pc_last_resolution["fcram_scan_attempted"] is False


def test_alpha46_pc_browser_rejects_party_pc_identity_overlap(tmp_path: Path) -> None:
    raw = bytearray(_matrix())
    raw[:PK7_STORED_SIZE] = _boxed(115, 0x10101010)
    rpc = _RPC(bytes(raw))
    writer = _writer(tmp_path, rpc)

    with pytest.raises(USUMLiveError, match="también está en la party viva"):
        writer.read_pc_for_game(
            _current(), tmp_path / "main", [],
            box_count=USUM_PC_BOX_COUNT, box_slot_count=USUM_PC_BOX_SLOT_COUNT,
        )
    assert writer._pc_last_resolution["fcram_scan_attempted"] is False
