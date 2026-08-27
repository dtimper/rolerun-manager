from __future__ import annotations

import json
import struct
from pathlib import Path

from app.azahar_rpc import AzaharProcess
from app.live_party_watch import detect_fainted_transitions
from app.save_engine_client import SaveGameData, SavePokemon
from app.usum_live import (
    USUM_BATTLE_ACTUAL_FROM_MAX,
    USUM_BATTLE_DISPLAY_FROM_MAX,
    USUM_BATTLE_PHASE_ACTIVE_VALUE,
    USUM_BATTLE_PHASE_ADDRESS,
    USUM_BATTLE_PHASE_IDLE_VALUE,
    USUM_BATTLE_PHASE_TERMINAL_VALUE,
    USUM_BATTLE_PLAYER_MAX_HP_BASE,
    USUM_BATTLE_PLAYER_STRIDE,
    USUM_BATTLE_STATE_ACTIVE_VALUE,
    USUM_BATTLE_STATE_ADDRESS,
    USUM_BATTLE_STATE_IDLE_VALUE,
    USUM_BATTLE_STATE_TERMINAL_VALUE,
    USUMLiveReader,
)
from app.usum_rom_service import USUM_ULTRA_SUN_TITLE_ID


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
PARTY_MAXES = (18, 19, 149, 19, 101, 17)


def _lane(values: tuple[int, ...]) -> bytes:
    size = ((len(values) - 1) * USUM_BATTLE_PLAYER_STRIDE) + 2
    raw = bytearray(size)
    for index, value in enumerate(values):
        struct.pack_into("<H", raw, index * USUM_BATTLE_PLAYER_STRIDE, int(value))
    return bytes(raw)


def _game(hp: tuple[int, ...]) -> SaveGameData:
    species = (379, 133, 115, 137, 763, 455)
    names = ("Registeel", "Eevee", "Kangaskhan", "Porygon", "Tsareena", "Carnivine")
    party = [
        SavePokemon(
            slot=index + 1,
            species_id=species[index],
            species=names[index],
            nickname=names[index],
            level=30,
            held_item="Ninguno",
            ability="",
            moves=["Placaje", "—", "—", "—"],
            move_ids=[33, 0, 0, 0],
            is_egg=False,
            markings=[False] * 6,
            role="SIN ROL",
            role_symbol="",
            pid=0xA0000000 + index,
            tid=835,
            sid=6011,
            current_hp=hp[index],
            max_hp=PARTY_MAXES[index],
        )
        for index in range(6)
    ]
    return SaveGameData(
        game="Pokémon UltraSol",
        save_type="SAV7USUM + Azahar RPC (USUM en vivo)",
        generation=7,
        trainer="Tester",
        party=party,
        raw={"liveSync": True},
    )


class _NominalBattleRPC:
    def __init__(self) -> None:
        self.process = AzaharProcess(11, USUM_ULTRA_SUN_TITLE_ID, "momiji")
        self.state = USUM_BATTLE_STATE_ACTIVE_VALUE
        self.phase = USUM_BATTLE_PHASE_ACTIVE_VALUE
        self.max_hp = PARTY_MAXES
        self.displayed = PARTY_MAXES
        self.actual = PARTY_MAXES

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def process_list(self):
        return [self.process]

    def set_process(self, process_id: int):
        assert int(process_id) == self.process.process_id

    def read_memory(self, address: int, size: int) -> bytes:
        address = int(address)
        if address == USUM_BATTLE_STATE_ADDRESS:
            return struct.pack("<I", int(self.state))
        if address == USUM_BATTLE_PHASE_ADDRESS:
            return struct.pack("<I", int(self.phase))
        if address == USUM_BATTLE_PLAYER_MAX_HP_BASE:
            return _lane(tuple(self.max_hp))[: int(size)]
        if address == USUM_BATTLE_PLAYER_MAX_HP_BASE + USUM_BATTLE_DISPLAY_FROM_MAX:
            return _lane(tuple(self.displayed))[: int(size)]
        if address == USUM_BATTLE_PLAYER_MAX_HP_BASE + USUM_BATTLE_ACTUAL_FROM_MAX:
            return _lane(tuple(self.actual))[: int(size)]
        return b"\0" * int(size)


def _reader(rpc: _NominalBattleRPC) -> USUMLiveReader:
    return USUMLiveReader(
        DATA_DIR / "move_catalog.json",
        client_factory=lambda: rpc,
        stable_delay=0,
        snapshot_attempts=1,
    )


def test_alpha60_changed_active_row_is_mapped_to_party_identity_before_ko(
    isolated_role_run_log_dir: Path,
) -> None:
    # Captura física alpha.59: slots 1/2 ya estaban debilitados; al elegir el
    # slot 4 como activo, la tabla RAM pasó de orden 1..6 a 4,2,3,1,5,6.
    current = _game((0, 0, 149, 19, 101, 17))
    rpc = _NominalBattleRPC()
    rpc.max_hp = (19, 19, 149, 18, 101, 17)
    rpc.displayed = (19, 0, 149, 0, 101, 17)
    rpc.actual = rpc.displayed
    reader = _reader(rpc)

    baseline = reader.read_battle_probe(current)

    assert baseline is not None and baseline.health_game is not None
    assert [member.current_hp for member in baseline.health_game.party] == [0, 0, 149, 19, 101, 17]

    rpc.displayed = (0, 0, 149, 0, 101, 17)
    rpc.actual = rpc.displayed
    faint = reader.read_battle_probe(current)

    assert faint is not None and faint.health_game is not None
    transitions = detect_fainted_transitions(baseline.health_game, faint.health_game)
    assert [(item.slot, item.pokemon) for item in transitions] == [(4, "Porygon")]

    trace = isolated_role_run_log_dir / "usum_battle_health_trace_latest.jsonl"
    samples = [
        json.loads(line)
        for line in trace.read_text(encoding="utf-8").splitlines()
        if json.loads(line).get("event") == "battle-sample"
    ]
    last_rows = samples[-1]["rows"]
    assert last_rows[0]["mapped_party_slot"] == 4
    assert last_rows[3]["mapped_party_slot"] == 1
    assert samples[-1]["validated_slots"] == [1, 2, 3, 4, 5, 6]


def test_alpha60_ambiguous_equal_hp_rows_are_not_guessed() -> None:
    current = _game((0, 19, 149, 19, 101, 17))
    rpc = _NominalBattleRPC()
    rpc.max_hp = (19, 19, 149, 18, 101, 17)
    rpc.displayed = (0, 0, 149, 0, 101, 17)
    rpc.actual = rpc.displayed
    reader = _reader(rpc)

    probe = reader.read_battle_probe(current)

    assert probe is not None and probe.health_game is not None
    # Las filas de Max=19 podrían ser slot 2 o slot 4; ninguna se publica como KO.
    assert probe.health_game.party[1].current_hp == 19
    assert probe.health_game.party[3].current_hp == 19
    assert [index + 1 for index, member in enumerate(probe.health_game.party) if member.current_hp == 0] == [1]


def test_alpha60_forced_replacement_suspends_same_battle_until_terminal_pair(
    isolated_role_run_log_dir: Path,
) -> None:
    current = _game(PARTY_MAXES)
    rpc = _NominalBattleRPC()
    reader = _reader(rpc)

    active = reader.read_battle_probe(current)
    assert active is not None and active.state == "battle" and active.health_game is not None

    # Secuencia física observada al abrir el selector forzado del propio juego.
    rpc.state = USUM_BATTLE_STATE_IDLE_VALUE
    rpc.phase = USUM_BATTLE_PHASE_IDLE_VALUE
    suspended_1 = reader.read_battle_probe(current)
    suspended_2 = reader.read_battle_probe(current)
    assert suspended_1 is not None and suspended_1.state == "battle"
    assert suspended_2 is not None and suspended_2.state == "battle"
    assert suspended_1.health_game is None and suspended_2.health_game is None

    rpc.state = USUM_BATTLE_STATE_ACTIVE_VALUE
    rpc.phase = USUM_BATTLE_PHASE_ACTIVE_VALUE
    resumed = reader.read_battle_probe(current)
    assert resumed is not None and resumed.state == "battle" and resumed.health_game is not None

    rpc.state = USUM_BATTLE_STATE_TERMINAL_VALUE
    rpc.phase = USUM_BATTLE_PHASE_TERMINAL_VALUE
    ended = reader.read_battle_probe(current)
    assert ended is not None and ended.state == "none"

    rpc.state = USUM_BATTLE_STATE_IDLE_VALUE
    rpc.phase = USUM_BATTLE_PHASE_IDLE_VALUE
    overworld = reader.read_battle_probe(current)
    assert overworld is not None and overworld.state == "none"

    trace = isolated_role_run_log_dir / "usum_battle_health_trace_latest.jsonl"
    events = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    assert len([event for event in events if event.get("event") == "battle-start"]) == 1
    assert len([event for event in events if event.get("event") == "battle-end"]) == 1
    assert len([event for event in events if event.get("event") == "battle-suspend"]) == 1
    assert len([event for event in events if event.get("event") == "battle-resume"]) == 1


def test_alpha60_primary_flag_without_active_phase_is_not_a_battle() -> None:
    current = _game(PARTY_MAXES)
    rpc = _NominalBattleRPC()
    rpc.phase = 0x53
    reader = _reader(rpc)

    assert reader.read_battle_probe(current) is None
    assert reader._battle_lifecycle_processes == set()

