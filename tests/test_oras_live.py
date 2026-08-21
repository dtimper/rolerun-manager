from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.azahar_rpc import AzaharProcess

# ``app.config`` resuelve Documentos al importar, como corresponde en Windows.
# El runner Linux no permite escribir en /root, por lo que el test le proporciona
# una carpeta temporal sin modificar la configuración de producción.
with patch("pathlib.Path.home", return_value=Path(tempfile.gettempdir()) / "rolerun-tests"):
    from app.oras_live import (
        ORAS_PARTY_ADDRESS,
        ORAS_BATTLE_WILD_PLAYER_ADDRESS,
        ORAS_BATTLE_TRAINER_PLAYER_ADDRESS,
        ORAS_BATTLE_PARTY_SPAN,
        ORAS_BATTLE_WILD_OPPONENT_ADDRESS,
        ORAS_BATTLE_TRAINER_OPPONENT_ADDRESS,
        ORAS_BATTLE_WILD_PP_ADDRESS,
        ORAS_BATTLE_TRAINER_PP_ADDRESS,
        ORASLiveMemoryBlock,
        ORASLiveSnapshot,
        ORAS_PARTY_STATS_OFFSET,
        ORAS_PARTY_STATS_SIZE,
        ORAS_PARTY_STRIDE,
        ORASLiveError,
        ORASLiveReader,
        PK6_PARTY_SIZE,
        PK6_STORED_SIZE,
        _crypt_array,
        _shuffle67,
        parse_oras_badges,
        parse_oras_battle_state,
        parse_pk6_party,
    )
    from app.save_engine_client import SaveGameData


_BLOCK_POSITION_INVERT = (
    0, 1, 2, 4, 3, 5, 6, 7, 12, 18, 13, 19,
    8, 10, 14, 20, 16, 22, 9, 11, 15, 21, 17, 23,
    0, 1, 2, 4, 3, 5, 6, 7,
)


def make_encrypted_pk6(*, current_hp: int = 23, max_hp: int = 47) -> bytes:
    data = bytearray(PK6_PARTY_SIZE)
    ec = 0x12345678
    struct.pack_into("<I", data, 0, ec)
    struct.pack_into("<H", data, 4, 0)
    struct.pack_into("<H", data, 8, 261)  # Poochyena
    struct.pack_into("<H", data, 0x0A, 1)
    struct.pack_into("<H", data, 0x0C, 12345)
    struct.pack_into("<H", data, 0x0E, 54321)
    data[0x14] = 50
    struct.pack_into("<I", data, 0x18, 0x89ABCDEF)
    data[0x2A] = 1
    nickname = "Poochyena".encode("utf-16le")
    data[0x40:0x40 + len(nickname)] = nickname
    struct.pack_into("<4H", data, 0x5A, 33, 44, 0, 0)
    struct.pack_into("<I", data, 0x74, 0x001FFFFF)
    data[0xEC] = 18
    struct.pack_into("<H", data, 0xF0, int(current_hp))
    struct.pack_into("<H", data, 0xF2, int(max_hp))
    checksum = sum(struct.unpack_from("<112H", data, 8)) & 0xFFFF
    struct.pack_into("<H", data, 6, checksum)

    sv = (ec >> 13) & 31
    _shuffle67(data, _BLOCK_POSITION_INVERT[sv])
    _crypt_array(data, 8, 0xE8, ec)
    _crypt_array(data, 0xE8, 0x104, ec)
    return bytes(data)


def make_encrypted_empty_pk6() -> bytes:
    data = bytearray(PK6_PARTY_SIZE)
    ec = 0xCAFEBABE
    struct.pack_into("<I", data, 0, ec)
    sv = (ec >> 13) & 31
    _shuffle67(data, _BLOCK_POSITION_INVERT[sv])
    _crypt_array(data, 8, 0xE8, ec)
    _crypt_array(data, 0xE8, 0x104, ec)
    return bytes(data)


class _FakeClient:
    def __init__(self, slots: tuple[bytes, ...]) -> None:
        self.slots = slots
        self.selected = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def process_list(self):
        return [AzaharProcess(77, 0x000400000011C500, "sango-2")]

    def set_process(self, process_id: int):
        self.selected = process_id

    def read_memory(self, address: int, size: int):
        index = (address - ORAS_PARTY_ADDRESS) // ORAS_PARTY_STRIDE
        relative = address - (ORAS_PARTY_ADDRESS + index * ORAS_PARTY_STRIDE)
        raw = self.slots[index]
        if relative == 0:
            self.assert_stored_read(size)
            return raw[:size]
        if relative == ORAS_PARTY_STATS_OFFSET:
            self.assert_stats_read(size)
            return raw[PK6_STORED_SIZE:PK6_STORED_SIZE + size]
        raise AssertionError(f"Lectura de RAM ORAS inesperada: +0x{relative:X}, {size} bytes")

    @staticmethod
    def assert_stored_read(size: int) -> None:
        if size != PK6_STORED_SIZE:
            raise AssertionError(f"El PK6 almacenado debe leer {PK6_STORED_SIZE} bytes, no {size}.")

    @staticmethod
    def assert_stats_read(size: int) -> None:
        if size != ORAS_PARTY_STATS_SIZE:
            raise AssertionError(f"Las estadísticas ORAS deben leer {ORAS_PARTY_STATS_SIZE} bytes, no {size}.")


def make_compact_party_region(slots: tuple[bytes, ...]) -> bytes:
    region = bytearray(ORAS_BATTLE_PARTY_SPAN)
    for index, raw in enumerate(slots):
        base = index * ORAS_PARTY_STRIDE
        region[base:base + PK6_STORED_SIZE] = raw[:PK6_STORED_SIZE]
        stats_start = base + ORAS_PARTY_STATS_OFFSET
        region[stats_start:stats_start + ORAS_PARTY_STATS_SIZE] = raw[
            PK6_STORED_SIZE:PK6_STORED_SIZE + ORAS_PARTY_STATS_SIZE
        ]
    return bytes(region)


class ORASLiveTests(unittest.TestCase):
    def test_encrypted_pk6_is_decrypted_and_validated(self) -> None:
        pokemon = parse_pk6_party(make_encrypted_pk6(), 1, {33: "Placaje", 44: "Mordisco"})
        self.assertIsNotNone(pokemon)
        assert pokemon is not None
        self.assertEqual(pokemon.species_id, 261)
        self.assertEqual(pokemon.nickname, "Poochyena")
        self.assertEqual(pokemon.level, 18)
        self.assertEqual(pokemon.moves[:2], ["Placaje", "Mordisco"])
        self.assertEqual(pokemon.role, "Líbero")
        self.assertEqual((pokemon.tid, pokemon.sid, pokemon.pid), (12345, 54321, 0x89ABCDEF))
        self.assertEqual((pokemon.current_hp, pokemon.max_hp), (23, 47))

    def test_corrupt_pk6_is_rejected(self) -> None:
        corrupt = bytearray(make_encrypted_pk6())
        corrupt[100] ^= 0x40
        with self.assertRaises(ORASLiveError):
            parse_pk6_party(bytes(corrupt), 1, {})

    def test_encrypted_empty_slot_is_accepted_as_empty(self) -> None:
        self.assertIsNone(parse_pk6_party(make_encrypted_empty_pk6(), 2, {}))

    def test_stable_snapshot_builds_live_game(self) -> None:
        slots = (make_encrypted_pk6(),) + (bytes(PK6_PARTY_SIZE),) * 5
        current = SaveGameData("AS", "SAV6AO", 6, "Diego", [], {})
        reader = ORASLiveReader(
            Path("does-not-exist.json"),
            client_factory=lambda: _FakeClient(slots),
            stable_delay=0,
        )
        snapshot = reader.read(current)
        self.assertEqual(snapshot.process.name, "sango-2")
        self.assertEqual(snapshot.game.trainer, "Diego")
        self.assertEqual(len(snapshot.game.party), 1)
        self.assertTrue(snapshot.game.raw["liveSync"])

    def test_process_detection_prefers_official_title_id_even_if_codeset_name_changes(self) -> None:
        process = ORASLiveReader._find_oras_process([
            AzaharProcess(77, 0x000400000011C500, "randommod"),
        ])
        self.assertEqual(process.process_id, 77)
        self.assertEqual(process.title_id, 0x000400000011C500)

    def test_process_detection_uses_legacy_sango_name_as_fallback(self) -> None:
        process = ORASLiveReader._find_oras_process([
            AzaharProcess(88, 0x0004000000ABCDEF, "sango-1"),
        ])
        self.assertEqual(process.process_id, 88)
        self.assertEqual(process.name, "sango-1")

    def test_process_detection_title_id_wins_over_unrelated_sango_name(self) -> None:
        process = ORASLiveReader._find_oras_process([
            AzaharProcess(10, 0x0004000000ABCDEF, "sango-1"),
            AzaharProcess(11, 0x000400000011C400, "patched"),
        ])
        self.assertEqual(process.process_id, 11)

    def test_process_detection_error_includes_visible_title_ids(self) -> None:
        with self.assertRaises(ORASLiveError) as caught:
            ORASLiveReader._find_oras_process([
                AzaharProcess(21, 0x0004000000055D00, "kujira-1"),
            ])
        self.assertIn("kujira-1[0004000000055D00]", str(caught.exception))

    def test_live_reader_uses_oras_sparse_party_layout(self) -> None:
        slots = (make_encrypted_pk6(),) + (bytes(PK6_PARTY_SIZE),) * 5
        current = SaveGameData("AS", "SAV6AO", 6, "Diego", [], {})
        reader = ORASLiveReader(
            Path("does-not-exist.json"),
            client_factory=lambda: _FakeClient(slots),
            stable_delay=0,
        )
        snapshot = reader.read(current)
        self.assertEqual(snapshot.game.party[0].level, 18)

    def test_oras_badge_counter_accepts_only_zero_to_eight(self) -> None:
        self.assertEqual(parse_oras_badges(b"\x00"), 0)
        self.assertEqual(parse_oras_badges(b"\x08"), 8)
        self.assertIsNone(parse_oras_badges(b"\x09"))
        self.assertIsNone(parse_oras_badges(b""))

    def test_battle_state_detects_wild_trainer_and_overworld(self) -> None:
        opponent = make_encrypted_pk6()[:PK6_STORED_SIZE]
        wild = (
            ORASLiveMemoryBlock(ORAS_BATTLE_WILD_OPPONENT_ADDRESS, opponent),
            ORASLiveMemoryBlock(ORAS_BATTLE_WILD_PP_ADDRESS, b"\x10"),
            ORASLiveMemoryBlock(ORAS_BATTLE_TRAINER_OPPONENT_ADDRESS, bytes(PK6_STORED_SIZE)),
            ORASLiveMemoryBlock(ORAS_BATTLE_TRAINER_PP_ADDRESS, b"\xff"),
        )
        trainer = (
            ORASLiveMemoryBlock(ORAS_BATTLE_WILD_OPPONENT_ADDRESS, bytes(PK6_STORED_SIZE)),
            ORASLiveMemoryBlock(ORAS_BATTLE_WILD_PP_ADDRESS, b"\xff"),
            ORASLiveMemoryBlock(ORAS_BATTLE_TRAINER_OPPONENT_ADDRESS, opponent),
            ORASLiveMemoryBlock(ORAS_BATTLE_TRAINER_PP_ADDRESS, b"\x10"),
        )
        none = (
            ORASLiveMemoryBlock(ORAS_BATTLE_WILD_OPPONENT_ADDRESS, bytes(PK6_STORED_SIZE)),
            ORASLiveMemoryBlock(ORAS_BATTLE_WILD_PP_ADDRESS, b"\xff"),
            ORASLiveMemoryBlock(ORAS_BATTLE_TRAINER_OPPONENT_ADDRESS, bytes(PK6_STORED_SIZE)),
            ORASLiveMemoryBlock(ORAS_BATTLE_TRAINER_PP_ADDRESS, b"\xff"),
        )
        self.assertEqual(parse_oras_battle_state(wild), "wild")
        self.assertEqual(parse_oras_battle_state(trainer), "trainer")
        self.assertEqual(parse_oras_battle_state(none), "none")


    def test_battle_health_game_reads_player_hp_from_wild_battle_party(self) -> None:
        normal = parse_pk6_party(make_encrypted_pk6(current_hp=23), 1, {})
        assert normal is not None
        current = SaveGameData("AS", "SAV6AO", 6, "Diego", [normal], {})
        battle_slots = (make_encrypted_pk6(current_hp=0),) + (bytes(PK6_PARTY_SIZE),) * 5
        opponent = make_encrypted_pk6()[:PK6_STORED_SIZE]
        snapshot = ORASLiveSnapshot(
            game=current,
            process=AzaharProcess(77, 0x000400000011C500, "sango-2"),
            attempts=1,
            memory_blocks=(
                ORASLiveMemoryBlock(ORAS_BATTLE_WILD_PLAYER_ADDRESS, make_compact_party_region(battle_slots)),
                ORASLiveMemoryBlock(ORAS_BATTLE_TRAINER_PLAYER_ADDRESS, bytes(ORAS_BATTLE_PARTY_SPAN)),
                ORASLiveMemoryBlock(ORAS_BATTLE_WILD_OPPONENT_ADDRESS, opponent),
                ORASLiveMemoryBlock(ORAS_BATTLE_WILD_PP_ADDRESS, b"\x10"),
                ORASLiveMemoryBlock(ORAS_BATTLE_TRAINER_OPPONENT_ADDRESS, bytes(PK6_STORED_SIZE)),
                ORASLiveMemoryBlock(ORAS_BATTLE_TRAINER_PP_ADDRESS, b"\xff"),
            ),
        )
        reader = ORASLiveReader(Path("does-not-exist.json"), stable_delay=0)
        health = reader.battle_health_game(snapshot, current)
        self.assertIsNotNone(health)
        assert health is not None
        self.assertEqual(health.raw["liveBattleState"], "wild")
        self.assertEqual(health.party[0].current_hp, 0)
        self.assertEqual(health.party[0].max_hp, 47)

    def test_battle_health_game_ignores_stale_regions_in_overworld(self) -> None:
        normal = parse_pk6_party(make_encrypted_pk6(current_hp=23), 1, {})
        assert normal is not None
        current = SaveGameData("AS", "SAV6AO", 6, "Diego", [normal], {})
        stale_slots = (make_encrypted_pk6(current_hp=0),) + (bytes(PK6_PARTY_SIZE),) * 5
        snapshot = ORASLiveSnapshot(
            game=current,
            process=AzaharProcess(77, 0x000400000011C500, "sango-2"),
            attempts=1,
            memory_blocks=(
                ORASLiveMemoryBlock(ORAS_BATTLE_WILD_PLAYER_ADDRESS, make_compact_party_region(stale_slots)),
                ORASLiveMemoryBlock(ORAS_BATTLE_WILD_OPPONENT_ADDRESS, bytes(PK6_STORED_SIZE)),
                ORASLiveMemoryBlock(ORAS_BATTLE_WILD_PP_ADDRESS, b"\xff"),
                ORASLiveMemoryBlock(ORAS_BATTLE_TRAINER_OPPONENT_ADDRESS, bytes(PK6_STORED_SIZE)),
                ORASLiveMemoryBlock(ORAS_BATTLE_TRAINER_PP_ADDRESS, b"\xff"),
            ),
        )
        reader = ORASLiveReader(Path("does-not-exist.json"), stable_delay=0)
        self.assertIsNone(reader.battle_health_game(snapshot, current))



if __name__ == "__main__":
    unittest.main()


class _CompactFakeClient:
    def __init__(self, slots: tuple[bytes, ...]) -> None:
        span = (5 * ORAS_PARTY_STRIDE) + ORAS_PARTY_STATS_OFFSET + ORAS_PARTY_STATS_SIZE
        region = bytearray(span)
        for index, raw in enumerate(slots):
            base = index * ORAS_PARTY_STRIDE
            region[base:base + PK6_STORED_SIZE] = raw[:PK6_STORED_SIZE]
            stats_start = base + ORAS_PARTY_STATS_OFFSET
            region[stats_start:stats_start + ORAS_PARTY_STATS_SIZE] = raw[
                PK6_STORED_SIZE:PK6_STORED_SIZE + ORAS_PARTY_STATS_SIZE
            ]
        self.region = bytes(region)
        self.selected = 0
        self.read_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def process_list(self):
        return [AzaharProcess(77, 0x000400000011C500, "sango-2")]

    def set_process(self, process_id: int):
        self.selected = process_id

    def read_memory(self, address: int, size: int):
        self.read_calls += 1
        relative = address - ORAS_PARTY_ADDRESS
        if relative < 0 or relative + size > len(self.region):
            raise AssertionError(f"Lectura compacta inesperada: 0x{address:X} + {size}")
        return self.region[relative:relative + size]


class ORASLiveMonitorTests(unittest.TestCase):
    def test_compact_monitor_builds_same_party(self) -> None:
        slots = (make_encrypted_pk6(),) + (bytes(PK6_PARTY_SIZE),) * 5
        current = SaveGameData("AS", "SAV6AO", 6, "Diego", [], {})
        client = _CompactFakeClient(slots)
        reader = ORASLiveReader(
            Path("does-not-exist.json"),
            client_factory=lambda: client,
            stable_delay=0,
        )
        snapshot = reader.read_monitor(current)
        self.assertEqual(len(snapshot.game.party), 1)
        self.assertEqual(snapshot.game.party[0].species_id, 261)
        # Doble captura compacta: una lectura de región por captura, no 12
        # lecturas dispersas de stored/stats.
        self.assertEqual(client.read_calls, 2)

class _BattleProbeFakeClient:
    def __init__(self, *, current_hp: int = 0, max_hp: int = 47, battle: str = "wild") -> None:
        self.current_hp = current_hp
        self.max_hp = max_hp
        self.battle = battle
        self.selected = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def process_list(self):
        return [AzaharProcess(77, 0x000400000011C500, "sango-2")]

    def set_process(self, process_id: int):
        self.selected = process_id

    def read_memory(self, address: int, size: int):
        opponent = make_encrypted_pk6()[:PK6_STORED_SIZE]
        from app.oras_live import (
            ORAS_BATTLE_DYNAMIC_HP_OFFSET,
            ORAS_BATTLE_WILD_PP_ADDRESS,
            ORAS_BATTLE_TRAINER_PP_ADDRESS,
        )
        if address == ORAS_BATTLE_WILD_OPPONENT_ADDRESS and size == PK6_STORED_SIZE:
            return opponent if self.battle == "wild" else bytes(PK6_STORED_SIZE)
        if address == ORAS_BATTLE_TRAINER_OPPONENT_ADDRESS and size == PK6_STORED_SIZE:
            return opponent if self.battle == "trainer" else bytes(PK6_STORED_SIZE)
        if address == ORAS_BATTLE_WILD_PP_ADDRESS and size == 1:
            return b"\x10" if self.battle == "wild" else b"\xff"
        if address == ORAS_BATTLE_TRAINER_PP_ADDRESS and size == 1:
            return b"\x10" if self.battle == "trainer" else b"\xff"
        pp = ORAS_BATTLE_WILD_PP_ADDRESS if self.battle == "wild" else ORAS_BATTLE_TRAINER_PP_ADDRESS
        if self.battle in {"wild", "trainer"} and address == pp + ORAS_BATTLE_DYNAMIC_HP_OFFSET and size == 4:
            return struct.pack("<HH", self.max_hp, self.current_hp)
        raise AssertionError(f"Lectura de sonda inesperada: 0x{address:X} + {size}")


class ORASBattleProbeTests(unittest.TestCase):
    def test_battle_probe_reads_zero_hp_without_double_stability_gate(self) -> None:
        normal = parse_pk6_party(make_encrypted_pk6(current_hp=23, max_hp=47), 1, {})
        assert normal is not None
        current = SaveGameData("AS", "SAV6AO", 6, "Diego", [normal], {})
        client = _BattleProbeFakeClient(current_hp=0, max_hp=47, battle="wild")
        reader = ORASLiveReader(
            Path("does-not-exist.json"), client_factory=lambda: client, stable_delay=0,
        )
        probe = reader.read_battle_probe(current)
        self.assertIsNotNone(probe)
        assert probe is not None
        self.assertEqual(probe.state, "wild")
        self.assertIsNotNone(probe.health_game)
        assert probe.health_game is not None
        self.assertEqual(probe.health_game.party[0].current_hp, 0)
        self.assertEqual(probe.health_game.party[0].max_hp, 47)

    def test_battle_probe_reports_overworld_without_health_payload(self) -> None:
        normal = parse_pk6_party(make_encrypted_pk6(current_hp=23, max_hp=47), 1, {})
        assert normal is not None
        current = SaveGameData("AS", "SAV6AO", 6, "Diego", [normal], {})
        client = _BattleProbeFakeClient(battle="none")
        reader = ORASLiveReader(
            Path("does-not-exist.json"), client_factory=lambda: client, stable_delay=0,
        )
        probe = reader.read_battle_probe(current)
        self.assertIsNotNone(probe)
        assert probe is not None
        self.assertEqual(probe.state, "none")
        self.assertIsNone(probe.health_game)
