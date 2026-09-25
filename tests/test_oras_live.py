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
        ORAS_BATTLE_DYNAMIC_HP_OFFSET,
        ORAS_BATTLE_MON_STRIDE,
        ORAS_BATTLE_OPPONENT_TEAM_STRIDE,
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


def make_encrypted_pk6(
    *, current_hp: int = 23, max_hp: int = 47, status_condition: int = 0,
) -> bytes:
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
    data[0x1C] = 3  # Firme: sube Ataque y baja Ataque Especial.
    data[0x1E:0x24] = bytes((4, 8, 12, 16, 20, 24))
    data[0x2A] = 1
    nickname = "Poochyena".encode("utf-16le")
    data[0x40:0x40 + len(nickname)] = nickname
    struct.pack_into("<4H", data, 0x5A, 33, 44, 0, 0)
    struct.pack_into("<I", data, 0x74, 0x001FFFFF)
    data[0xEC] = 18
    struct.pack_into("<I", data, 0xE8, int(status_condition))
    struct.pack_into("<H", data, 0xF0, int(current_hp))
    struct.pack_into("<H", data, 0xF2, int(max_hp))
    struct.pack_into("<5H", data, 0xF4, 31, 29, 27, 25, 23)
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
        self.assertEqual(pokemon.status_condition, 0)
        self.assertEqual(pokemon.nature, "Firme")
        self.assertEqual(pokemon.nature_increased, "attack")
        self.assertEqual(pokemon.nature_decreased, "sp_attack")
        self.assertEqual(
            pokemon.stats,
            {"hp": 47, "attack": 31, "defense": 29, "sp_attack": 25, "sp_defense": 23, "speed": 27},
        )
        self.assertEqual(
            pokemon.evs,
            {"hp": 4, "attack": 8, "defense": 12, "sp_attack": 20, "sp_defense": 24, "speed": 16},
        )

    def test_party_parser_exposes_runtime_status_condition(self) -> None:
        pokemon = parse_pk6_party(
            make_encrypted_pk6(status_condition=0x40), 1, {33: "Placaje", 44: "Mordisco"},
        )
        assert pokemon is not None
        self.assertEqual(pokemon.status_condition, 0x40)

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

    def test_a_hole_left_by_the_game_itself_does_not_break_the_whole_read(self) -> None:
        """El bug real del 30-08-2026: un solo hueco roto bastaba para tirar
        CUALQUIER lectura de la party completa — el monitor normal, F5, una
        reconexión — no solo las operaciones nuevas de cambio de tamaño.
        Depositar desde el propio menú del juego (no desde RoleRun) solo pone
        a cero la cabecera del slot; `parse_pk6_party` lo rechaza levantando
        `ORASLiveError` en vez de devolver `None`, y antes nada en `read()`
        atrapaba esa excepción.
        """
        broken = bytearray(make_encrypted_pk6())
        broken[0:10] = bytes(10)  # cabecera a cero; el resto, basura sin limpiar
        slots = (make_encrypted_pk6(), bytes(broken)) + (bytes(PK6_PARTY_SIZE),) * 4
        current = SaveGameData("AS", "SAV6AO", 6, "Diego", [], {})
        reader = ORASLiveReader(
            Path("does-not-exist.json"),
            client_factory=lambda: _FakeClient(slots),
            stable_delay=0,
        )

        snapshot = reader.read(current)

        self.assertEqual(len(snapshot.game.party), 1)

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
    def __init__(
        self, *, current_hp: int = 0, max_hp: int = 47, battle: str = "wild",
        opponent_roster_size: int = 6,
    ) -> None:
        self.current_hp = current_hp
        self.max_hp = max_hp
        self.battle = battle
        # Cuántos de los seis huecos del roster rival simulan un PK6 válido;
        # el resto se sirve vacío. Ver `ORAS_BATTLE_OPPONENT_TEAM_STRIDE`.
        self.opponent_roster_size = opponent_roster_size
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
        if size == PK6_STORED_SIZE and self.battle == "trainer":
            offset = address - ORAS_BATTLE_TRAINER_OPPONENT_ADDRESS
            if offset > 0 and offset % ORAS_BATTLE_OPPONENT_TEAM_STRIDE == 0:
                slot = offset // ORAS_BATTLE_OPPONENT_TEAM_STRIDE
                if 1 <= slot < 6:
                    return opponent if slot < self.opponent_roster_size else bytes(PK6_STORED_SIZE)
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
        self.assertIsNone(probe.opponent_team_size)

    def test_battle_probe_counts_the_full_trainer_opponent_roster_but_not_wild(self) -> None:
        # Regla de "combate de seis" (dictada 09-09-2026): solo un combate de
        # ENTRENADOR debe exponer el tamaño del roster rival. Descubierto en
        # vivo el 14-09-2026 que ``ORAS_BATTLE_TRAINER_OPPONENT_ADDRESS`` es el
        # slot 0 de un roster de seis estático -no "el rival activo"-, ver
        # memoria `six-mon-battle-auto-reward`.
        normal = parse_pk6_party(make_encrypted_pk6(current_hp=23, max_hp=47), 1, {})
        assert normal is not None
        current = SaveGameData("AS", "SAV6AO", 6, "Diego", [normal], {})
        trainer_client = _BattleProbeFakeClient(
            current_hp=23, max_hp=47, battle="trainer", opponent_roster_size=6,
        )
        trainer_reader = ORASLiveReader(
            Path("does-not-exist.json"), client_factory=lambda: trainer_client, stable_delay=0,
        )
        trainer_probe = trainer_reader.read_battle_probe(current)
        assert trainer_probe is not None
        self.assertEqual(trainer_probe.state, "trainer")
        self.assertEqual(trainer_probe.opponent_team_size, 6)

        wild_client = _BattleProbeFakeClient(current_hp=23, max_hp=47, battle="wild")
        wild_reader = ORASLiveReader(
            Path("does-not-exist.json"), client_factory=lambda: wild_client, stable_delay=0,
        )
        wild_probe = wild_reader.read_battle_probe(current)
        assert wild_probe is not None
        self.assertEqual(wild_probe.state, "wild")
        self.assertIsNone(wild_probe.opponent_team_size)

    def test_battle_probe_counts_fewer_than_six_opponents_correctly(self) -> None:
        normal = parse_pk6_party(make_encrypted_pk6(current_hp=23, max_hp=47), 1, {})
        assert normal is not None
        current = SaveGameData("AS", "SAV6AO", 6, "Diego", [normal], {})
        client = _BattleProbeFakeClient(
            current_hp=23, max_hp=47, battle="trainer", opponent_roster_size=3,
        )
        reader = ORASLiveReader(
            Path("does-not-exist.json"), client_factory=lambda: client, stable_delay=0,
        )
        probe = reader.read_battle_probe(current)
        assert probe is not None
        self.assertEqual(probe.state, "trainer")
        self.assertEqual(probe.opponent_team_size, 3)

    def test_battle_probe_abstains_when_the_table_is_mis_indexed(self) -> None:
        """Reproduce el incidente real del 31-08-2026.

        Torkoal (slot 1, PS máx. 112) y Breloom (slot 4, PS máx. 14) en el
        mismo equipo. La tabla de batalla, emparejada ciegamente por
        posición, pintó los PS bajos de Breloom sobre Torkoal — y al caer
        Breloom se registró una baja falsa de Torkoal. El PS máximo de Gen 6
        nunca cambia en combate, así que un máximo que no cuadra con el de
        esa posición es la señal de que la tabla no va en el orden asumido:
        la sonda entera se abstiene en vez de publicar una salud mal indexada.
        """
        torkoal = parse_pk6_party(
            make_encrypted_pk6(current_hp=112, max_hp=112), 1, {},
        )
        breloom = parse_pk6_party(
            make_encrypted_pk6(current_hp=14, max_hp=14), 4, {},
        )
        assert torkoal is not None and breloom is not None
        current = SaveGameData("AS", "SAV6AO", 6, "Diego", [torkoal, breloom], {})

        class _MesaMalIndexada:
            def __init__(self) -> None:
                self.selected = 0

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def process_list(self):
                return [AzaharProcess(77, 0x000400000011C500, "sango-2")]

            def set_process(self, process_id: int) -> None:
                self.selected = process_id

            def read_memory(self, address: int, size: int):
                if address == ORAS_BATTLE_WILD_OPPONENT_ADDRESS and size == PK6_STORED_SIZE:
                    return make_encrypted_pk6()[:PK6_STORED_SIZE]
                if address == ORAS_BATTLE_TRAINER_OPPONENT_ADDRESS and size == PK6_STORED_SIZE:
                    return bytes(PK6_STORED_SIZE)
                if address == ORAS_BATTLE_WILD_PP_ADDRESS and size == 1:
                    return b"\x10"
                if address == ORAS_BATTLE_TRAINER_PP_ADDRESS and size == 1:
                    return b"\xff"
                start = ORAS_BATTLE_WILD_PP_ADDRESS + ORAS_BATTLE_DYNAMIC_HP_OFFSET
                if address == start:
                    # El motor puso a Breloom (PS 4/14) en la posición de la
                    # tabla que la sonda esperaba para Torkoal (slot 1).
                    tabla = bytearray(size)
                    struct.pack_into("<HH", tabla, 0, 14, 4)
                    return bytes(tabla)
                raise AssertionError(f"Lectura de sonda inesperada: 0x{address:X} + {size}")

        reader = ORASLiveReader(
            Path("does-not-exist.json"), client_factory=lambda: _MesaMalIndexada(), stable_delay=0,
        )
        probe = reader.read_battle_probe(current)

        self.assertIsNotNone(probe)
        assert probe is not None
        self.assertEqual(probe.state, "wild")
        # Se abstiene: NO publica los PS de Breloom pintados sobre Torkoal.
        self.assertIsNone(probe.health_game)

    def test_battle_probe_resolves_the_active_battler_swap(self) -> None:
        """El arreglo real, con los bytes capturados en vivo el 31-08-2026.

        Equipo de seis: Torkoal(112) Houndoom(15) Quagsire(33) Breloom(14)
        Scyther(15) Gardevoir(15). Con Scyther como combatiente activo y
        recién debilitado, la tabla real leída fue:
            [0]=(15,0) [1]=(15,15) [2]=(33,33) [3]=(14,14) [4]=(112,112) [5]=(15,15)
        Scyther (slot 5, índice 4) se intercambió con el índice 0 —el hueco
        "de reposo" de Torkoal (slot 1)—. Los otros cuatro miembros se
        quedaron exactamente donde ya se esperaba. No es una reordenación
        completa: es un intercambio de dos entradas.
        """
        maximos = (112, 15, 33, 14, 15, 15)
        party = []
        for slot, maximo in enumerate(maximos, start=1):
            mon = parse_pk6_party(make_encrypted_pk6(current_hp=maximo, max_hp=maximo), slot, {})
            assert mon is not None
            party.append(mon)
        current = SaveGameData("AS", "SAV6AO", 6, "Diego", party, {})

        tabla_real = ((15, 0), (15, 15), (33, 33), (14, 14), (112, 112), (15, 15))

        class _MesaConIntercambio:
            def __init__(self) -> None:
                self.selected = 0

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def process_list(self):
                return [AzaharProcess(77, 0x000400000011C500, "sango-2")]

            def set_process(self, process_id: int) -> None:
                self.selected = process_id

            def read_memory(self, address: int, size: int):
                if address == ORAS_BATTLE_WILD_OPPONENT_ADDRESS and size == PK6_STORED_SIZE:
                    return make_encrypted_pk6()[:PK6_STORED_SIZE]
                if address == ORAS_BATTLE_TRAINER_OPPONENT_ADDRESS and size == PK6_STORED_SIZE:
                    return bytes(PK6_STORED_SIZE)
                if address == ORAS_BATTLE_WILD_PP_ADDRESS and size == 1:
                    return b"\x10"
                if address == ORAS_BATTLE_TRAINER_PP_ADDRESS and size == 1:
                    return b"\xff"
                start = ORAS_BATTLE_WILD_PP_ADDRESS + ORAS_BATTLE_DYNAMIC_HP_OFFSET
                if address == start:
                    tabla = bytearray(size)
                    for index, (maximo, actual) in enumerate(tabla_real):
                        struct.pack_into("<HH", tabla, index * ORAS_BATTLE_MON_STRIDE, maximo, actual)
                    return bytes(tabla)
                raise AssertionError(f"Lectura de sonda inesperada: 0x{address:X} + {size}")

        reader = ORASLiveReader(
            Path("does-not-exist.json"), client_factory=lambda: _MesaConIntercambio(), stable_delay=0,
        )
        probe = reader.read_battle_probe(current)

        self.assertIsNotNone(probe)
        assert probe is not None
        self.assertIsNotNone(probe.health_game)
        assert probe.health_game is not None
        publicado = {int(p.slot): (p.current_hp, p.max_hp) for p in probe.health_game.party}
        self.assertEqual(publicado[1], (112, 112))  # Torkoal, ajeno al intercambio
        self.assertEqual(publicado[2], (15, 15))    # Houndoom, ajeno
        self.assertEqual(publicado[3], (33, 33))    # Quagsire, ajeno
        self.assertEqual(publicado[4], (14, 14))    # Breloom, ajeno
        self.assertEqual(publicado[5], (0, 15))     # Scyther: el combatiente, debilitado
        self.assertEqual(publicado[6], (15, 15))    # Gardevoir, ajeno
