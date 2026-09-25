from __future__ import annotations

import struct

from app.bdsp_live import (
    BDSP_SP_130_BATTLE_CLIENT_ARRAY_ELEMENT_OFFSET,
    BDSP_SP_130_BATTLE_OPPONENT_CLIENT_INDEX,
    BDSP_SP_130_BATTLE_CLIENT_STRIDE,
    BDSPBattleReader,
)
from tests.test_bdsp_live_foundation import FakeGuestClient


def _opponent_battle_memory(*species: int) -> FakeGuestClient:
    """Construye la misma forma de BTL_PARTY que el jugador, pero en el
    "cliente 1" del array de participantes -ver
    `BDSP_SP_130_BATTLE_CLIENT_ARRAY_POINTER`-. ``species`` puede tener menos
    de 6 elementos: el resto de huecos quedan sin poblar (member_count los
    excluye igual que en un combate real de menos de seis).
    """
    array_holder = 0x10000
    array_ptr = 0x20000
    opponent_client = 0x40000
    member_array = 0x50000
    battle_params = [0x60000 + index * 0x200 for index in range(6)]
    cores = [0x70000 + index * 0x200 for index in range(6)]

    member_count = len(species)
    segments: dict[int, bytes] = {
        array_holder: struct.pack("<Q", array_ptr),
        array_ptr
        + BDSP_SP_130_BATTLE_CLIENT_ARRAY_ELEMENT_OFFSET
        + BDSP_SP_130_BATTLE_OPPONENT_CLIENT_INDEX * BDSP_SP_130_BATTLE_CLIENT_STRIDE:
            struct.pack("<Q", opponent_client),
        opponent_client + 0x10: struct.pack("<QB", member_array, member_count),
    }
    if member_count:
        segments[member_array + 0x18] = struct.pack("<Q", 6)
        segments[member_array + 0x20] = struct.pack(
            "<6Q", *(battle_params[:member_count] + [0] * (6 - member_count)),
        )
        for index, species_id in enumerate(species):
            segments[battle_params[index] + 0x10] = struct.pack("<Q", cores[index])
            segments[cores[index] + 0x18] = struct.pack(
                "<IIHHHHHHHBB", 0, 1234, species_id, 0, 40, 40, 0, 0, 65, 20, 12 + index,
            )
    return FakeGuestClient(segments, array_holder)


class TestBDSPBattleOpponentTeamSize:
    def test_counts_a_full_six_member_roster(self) -> None:
        # Regla de "combate de seis" (dictada 09-09-2026): "cliente 1" del
        # array de participantes de combate, confirmado en vivo el
        # 14-09-2026 contra un combate real de Perla Reluciente (Delcatty,
        # Kadabra, Vigoroth, Nidorino, Makuhita, Beedrill). Ver memoria
        # `six-mon-battle-auto-reward`.
        client = _opponent_battle_memory(301, 64, 288, 33, 296, 15)
        assert BDSPBattleReader(client).read_opponent_team_size() == 6

    def test_counts_fewer_than_six_correctly(self) -> None:
        client = _opponent_battle_memory(301, 64)
        assert BDSPBattleReader(client).read_opponent_team_size() == 2

    def test_empty_roster_counts_zero(self) -> None:
        client = _opponent_battle_memory()
        assert BDSPBattleReader(client).read_opponent_team_size() == 0

    def test_invalid_array_length_returns_none(self) -> None:
        client = _opponent_battle_memory(301, 64, 288, 33, 296, 15)
        # El array declara una longitud distinta de 6: no es el BTL_PARTY
        # esperado, así que la regla no debe evaluarse con datos dudosos.
        client.segments[0x50000 + 0x18] = struct.pack("<Q", 5)
        assert BDSPBattleReader(client).read_opponent_team_size() is None

    def test_a_broken_reader_never_raises(self) -> None:
        # Ningún fallo de esta lectura aislada puede propagarse -ver el
        # comentario del método-. Un cliente completamente vacío no debe
        # lanzar, solo devolver ``None``.
        client = FakeGuestClient({}, 0x10000)
        assert BDSPBattleReader(client).read_opponent_team_size() is None
