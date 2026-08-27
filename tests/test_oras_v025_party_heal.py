from __future__ import annotations

import struct
from pathlib import Path

import pytest

from app.azahar_rpc import AzaharProcess
from app.models import PendingPartyHeal
from app.oras_live import (
    ORAS_PARTY_ADDRESS,
    ORAS_PARTY_STATS_OFFSET,
    ORAS_PARTY_STATS_SIZE,
    ORAS_PARTY_STRIDE,
    ORASLiveError,
    ORASLiveReader,
    ORASLiveWriter,
    PK6_PARTY_SIZE,
    PK6_STORED_SIZE,
    _plain_pk6,
    encrypt_pk6,
    parse_pk6_party,
)
from app.save_engine_client import SaveGameData


def _party_member(*, current_hp: int = 7, max_hp: int = 47, status: int = 0x40) -> bytes:
    data = bytearray(PK6_PARTY_SIZE)
    struct.pack_into("<I", data, 0, 0x12345678)
    struct.pack_into("<H", data, 8, 261)
    struct.pack_into("<H", data, 0x0C, 12345)
    struct.pack_into("<H", data, 0x0E, 54321)
    data[0x14] = 50
    struct.pack_into("<I", data, 0x18, 0x89ABCDEF)
    nickname = "Poochyena".encode("utf-16le")
    data[0x40:0x40 + len(nickname)] = nickname
    struct.pack_into("<4H", data, 0x5A, 33, 44, 0, 0)
    data[0x62:0x66] = bytes((1, 2, 0, 0))
    data[0x66:0x6A] = bytes((1, 2, 0, 0))
    struct.pack_into("<I", data, 0x74, 0x001FFFFF)
    struct.pack_into("<I", data, 0xE8, status)
    data[0xEC] = 18
    struct.pack_into("<H", data, 0xF0, current_hp)
    struct.pack_into("<6H", data, 0xF2, max_hp, 31, 29, 27, 25, 23)
    checksum = sum(struct.unpack_from("<112H", data, 8)) & 0xFFFF
    struct.pack_into("<H", data, 6, checksum)
    return encrypt_pk6(bytes(data))


class _PartyClient:
    def __init__(self, first: bytes, *, corrupt_stats_once: bool = False) -> None:
        self.slots: list[bytearray] = []
        for index in range(6):
            runtime = bytearray(ORAS_PARTY_STRIDE)
            raw = first if index == 0 else encrypt_pk6(bytes(PK6_PARTY_SIZE))
            runtime[:PK6_STORED_SIZE] = raw[:PK6_STORED_SIZE]
            runtime[ORAS_PARTY_STATS_OFFSET:ORAS_PARTY_STATS_OFFSET + ORAS_PARTY_STATS_SIZE] = (
                raw[PK6_STORED_SIZE:PK6_STORED_SIZE + ORAS_PARTY_STATS_SIZE]
            )
            self.slots.append(runtime)
        self.corrupt_stats_once = corrupt_stats_once
        self.writes: list[tuple[int, bytes]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def process_list(self):
        return [AzaharProcess(77, 0x000400000011C500, "sango-2")]

    def set_process(self, _process_id: int):
        return None

    @staticmethod
    def _position(address: int) -> tuple[int, int]:
        index = (address - ORAS_PARTY_ADDRESS) // ORAS_PARTY_STRIDE
        relative = address - (ORAS_PARTY_ADDRESS + index * ORAS_PARTY_STRIDE)
        assert 0 <= index < 6
        return index, relative

    def read_memory(self, address: int, size: int):
        index, relative = self._position(address)
        return bytes(self.slots[index][relative:relative + size])

    def write_memory(self, address: int, data: bytes):
        index, relative = self._position(address)
        replacement = bytes(data)
        self.writes.append((address, replacement))
        self.slots[index][relative:relative + len(replacement)] = replacement
        if self.corrupt_stats_once and relative == ORAS_PARTY_STATS_OFFSET:
            self.corrupt_stats_once = False
            self.slots[index][relative] ^= 0x01


def _writer_game_change(client: _PartyClient):
    reader = ORASLiveReader(
        Path("missing.json"), client_factory=lambda: client, stable_delay=0, snapshot_attempts=2,
    )
    writer = ORASLiveWriter(reader, move_pp_for=lambda move_id: {33: 35, 44: 25}.get(move_id, 0))
    captured = reader._read_party(client)
    pokemon = parse_pk6_party(captured[0], 1, reader.move_names)
    assert pokemon is not None
    game = SaveGameData("AS", "SAV6AO", 6, "Timper", [pokemon], {})
    change = PendingPartyHeal(
        pokemon_slot=1,
        pokemon=pokemon.nickname,
        species=pokemon.species,
        pokemon_identity=writer._pokemon_identity(pokemon),
    )
    return writer, game, change


def test_oras_party_heal_restores_hp_status_and_pp_with_readback():
    client = _PartyClient(_party_member())
    writer, game, change = _writer_game_change(client)

    result = writer.apply(game, [change])

    healed = result.game.party[0]
    assert healed.current_hp == healed.max_hp == 47
    assert healed.status_condition == 0
    captured = writer.reader._read_party(client)
    plain, _encrypted = _plain_pk6(captured[0])
    assert list(plain[0x62:0x66]) == [42, 35, 0, 0]
    assert result.applied_count == 1
    assert client.writes


def test_oras_party_heal_rolls_back_every_written_region_when_readback_fails():
    client = _PartyClient(_party_member(), corrupt_stats_once=True)
    before = tuple(bytes(slot) for slot in client.slots)
    writer, game, change = _writer_game_change(client)

    with pytest.raises(ORASLiveError, match="restauró y verificó"):
        writer.apply(game, [change])

    assert tuple(bytes(slot) for slot in client.slots) == before
