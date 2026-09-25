from __future__ import annotations

import struct
import unittest
from pathlib import Path

from app.azahar_rpc import AzaharProcess
from app.sm_live import (
    PK7_STORED_SIZE,
    SM_BATTLE_OPPONENT_IDENTITY_BASE,
    SM_BATTLE_IDENTITY_STRIDE,
    SM_TITLE_IDS,
    SMLiveReader,
)


def _plain_pk7(species_id: int) -> bytes:
    """Bloque PK7 almacenado PLANO (sin cifrar) y con checksum válido.

    ``parse_pk7_boxed`` acepta un bloque plano directamente, así que no hace
    falta reproducir el cifrado real, solo un checksum de suma consistente.
    """
    data = bytearray(PK7_STORED_SIZE)
    struct.pack_into("<H", data, 8, species_id)
    checksum = sum(struct.unpack_from("<112H", data, 8)) & 0xFFFF
    struct.pack_into("<H", data, 6, checksum)
    return bytes(data)


class _OpponentRosterRPC:
    def __init__(self, species: tuple[int, ...]) -> None:
        self.process = AzaharProcess(11, next(iter(SM_TITLE_IDS)), "niji_loc")
        self.species = species

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def process_list(self):
        return [self.process]

    def set_process(self, process_id: int) -> None:
        assert int(process_id) == self.process.process_id

    def read_memory(self, address: int, size: int) -> bytes:
        address = int(address)
        offset = address - SM_BATTLE_OPPONENT_IDENTITY_BASE
        if 0 <= offset and offset % SM_BATTLE_IDENTITY_STRIDE == 0:
            slot = offset // SM_BATTLE_IDENTITY_STRIDE
            if slot < len(self.species) and size == PK7_STORED_SIZE:
                species = self.species[slot]
                return _plain_pk7(species) if species else bytes(PK7_STORED_SIZE)
        return b"\0" * int(size)


def _reader(rpc: _OpponentRosterRPC) -> SMLiveReader:
    return SMLiveReader(
        Path("does-not-exist.json"), client_factory=lambda: rpc, stable_delay=0,
    )


class SMBattleOpponentTeamSizeTests(unittest.TestCase):
    def test_counts_a_full_six_member_roster(self) -> None:
        # Regla de "combate de seis" (dictada 09-09-2026): mismas direcciones
        # que USUM -confirmadas en vivo el 14-09-2026 contra un combate real
        # de Sol/Luna (Mankey, Makuhita, Combusken, Lucario, Terrakion,
        # Crabrawler)-. Ver memoria `six-mon-battle-auto-reward`.
        rpc = _OpponentRosterRPC((56, 296, 256, 448, 639, 739))
        reader = _reader(rpc)
        self.assertEqual(reader.read_battle_opponent_team_size(), 6)

    def test_counts_fewer_than_six_correctly(self) -> None:
        rpc = _OpponentRosterRPC((56, 296, 0, 0, 0, 0))
        reader = _reader(rpc)
        self.assertEqual(reader.read_battle_opponent_team_size(), 2)

    def test_empty_roster_counts_zero(self) -> None:
        rpc = _OpponentRosterRPC((0, 0, 0, 0, 0, 0))
        reader = _reader(rpc)
        self.assertEqual(reader.read_battle_opponent_team_size(), 0)


if __name__ == "__main__":
    unittest.main()
