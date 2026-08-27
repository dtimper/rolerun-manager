from __future__ import annotations

import json
import struct
from pathlib import Path

from app.azahar_rpc import AzaharProcess
from app.save_engine_client import SaveGameData, SavePokemon
from app.usum_live import (
    USUM_BATTLE_ACTUAL_FROM_MAX,
    USUM_BATTLE_DISPLAY_FROM_MAX,
    USUM_BATTLE_PHASE_ACTIVE_VALUE,
    USUM_BATTLE_PHASE_ADDRESS,
    USUM_BATTLE_PHASE_IDLE_VALUE,
    USUM_BATTLE_PLAYER_MAX_HP_BASE,
    USUM_BATTLE_PLAYER_STRIDE,
    USUM_BATTLE_STATE_ACTIVE_VALUE,
    USUM_BATTLE_STATE_ADDRESS,
    USUM_BATTLE_STATE_IDLE_VALUE,
    USUMLiveReader,
)
from app.usum_rom_service import USUM_ULTRA_SUN_TITLE_ID


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
PARTY_MAXES = (18, 19, 149, 20, 101, 17)


def _lane(values: tuple[int, ...]) -> bytes:
    raw = bytearray(((len(values) - 1) * USUM_BATTLE_PLAYER_STRIDE) + 2)
    for index, value in enumerate(values):
        struct.pack_into("<H", raw, index * USUM_BATTLE_PLAYER_STRIDE, int(value))
    return bytes(raw)


def _game(hp: tuple[int, ...]) -> SaveGameData:
    species = (379, 133, 115, 137, 763, 455)
    names = ("Registeel", "Eevee", "Kangaskhan", "Porygon", "Tsareena", "Carnivine")
    return SaveGameData(
        game="Pokémon UltraSol",
        save_type="SAV7USUM + Azahar RPC (USUM en vivo)",
        generation=7,
        trainer="Tester",
        party=[
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
                current_hp=int(hp[index]),
                max_hp=int(PARTY_MAXES[index]),
            )
            for index in range(6)
        ],
        raw={"liveSync": True},
    )


class _BattleRPC:
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


def _reader(rpc: _BattleRPC) -> USUMLiveReader:
    return USUMLiveReader(
        DATA_DIR / "move_catalog.json",
        client_factory=lambda: rpc,
        stable_delay=0,
        snapshot_attempts=1,
    )


def test_alpha62_idle_pair_ends_only_after_observed_ko_converges_to_party(
    isolated_role_run_log_dir: Path,
) -> None:
    """Reproduce la primera divergencia física de alpha.61.

    El mismo par 0x00040005/6 aparece durante la sustitución forzada y ya en
    overworld. Lo que cambia es que PartyData solo converge a los dos HP=0 al
    finalizar realmente el combate.
    """
    rpc = _BattleRPC()
    reader = _reader(rpc)
    full_party = _game(PARTY_MAXES)

    baseline = reader.read_battle_probe(full_party)
    assert baseline is not None and baseline.state == "battle"

    rpc.displayed = (18, 0, 149, 0, 101, 17)
    rpc.actual = rpc.displayed
    fainted = reader.read_battle_probe(full_party)
    assert fainted is not None and fainted.state == "battle"

    rpc.state = USUM_BATTLE_STATE_IDLE_VALUE
    rpc.phase = USUM_BATTLE_PHASE_IDLE_VALUE

    forced_replacement = reader.read_battle_probe(full_party)
    assert forced_replacement is not None and forced_replacement.state == "battle"

    overworld_party = _game((18, 0, 149, 0, 101, 17))
    ended = reader.read_battle_probe(overworld_party)
    assert ended is not None and ended.state == "none"
    assert "PartyData" in ended.reason
    # La UI exige dos muestras consecutivas fuera de combate antes de abrir el
    # selector. Tras limpiar el episodio, el mismo overworld sigue publicando
    # ``none`` y permite completar esa compuerta existente sin tocarla.
    confirmed = reader.read_battle_probe(overworld_party)
    assert confirmed is not None and confirmed.state == "none"

    trace = isolated_role_run_log_dir / "usum_battle_health_trace_latest.jsonl"
    events = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    assert any(event.get("event") == "battle-idle-evidence" for event in events)
    assert any(
        event.get("event") == "battle-end"
        and event.get("reason") == "observed-ko-converged-to-party"
        for event in events
    )


def test_alpha62_preexisting_party_zero_cannot_end_forced_replacement() -> None:
    rpc = _BattleRPC()
    reader = _reader(rpc)
    already_fainted = _game((0, 19, 149, 20, 101, 17))
    rpc.displayed = (0, 19, 149, 20, 101, 17)
    rpc.actual = rpc.displayed

    assert reader.read_battle_probe(already_fainted).state == "battle"

    rpc.state = USUM_BATTLE_STATE_IDLE_VALUE
    rpc.phase = USUM_BATTLE_PHASE_IDLE_VALUE
    suspended = reader.read_battle_probe(already_fainted)

    assert suspended is not None and suspended.state == "battle"
