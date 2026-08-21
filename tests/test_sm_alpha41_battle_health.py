from __future__ import annotations

import struct
from pathlib import Path

from app.azahar_rpc import AzaharProcess
from app.save_engine_client import SaveGameData, SavePokemon
from app.sm_live import (
    SM_BATTLE_PLAYER_ACTUAL_HP_BASE,
    SM_BATTLE_PLAYER_DISPLAY_HP_BASE,
    SM_BATTLE_PLAYER_MAX_HP_BASE,
    SM_BATTLE_PLAYER_STRIDE,
    SM_BATTLE_STATE_ACTIVE_VALUE,
    SM_BATTLE_STATE_ADDRESS,
    SMLiveReader,
)


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
TITLE_ID_SUN = 0x0004000000164800


def mon(slot: int, species: int, *, current_hp: int, max_hp: int) -> SavePokemon:
    return SavePokemon(
        slot=slot,
        species_id=species,
        species=f"Species {species}",
        nickname=f"Mon {species}",
        level=25,
        held_item="Ninguno",
        ability="Ability",
        moves=["Placaje", "—", "—", "—"],
        move_ids=[33, 0, 0, 0],
        is_egg=False,
        markings=[False] * 6,
        role="SIN ROL",
        role_symbol="",
        pid=0x10000000 + slot,
        tid=100,
        sid=200,
        current_hp=current_hp,
        max_hp=max_hp,
    )


def game(*party: SavePokemon) -> SaveGameData:
    return SaveGameData(
        game="Pokémon Sol",
        save_type="SAV7SM + Azahar RPC (SM en vivo)",
        generation=7,
        trainer="Tester",
        party=list(party),
        raw={"liveSync": True},
    )


def lane(values: list[int]) -> bytes:
    size = ((len(values) - 1) * SM_BATTLE_PLAYER_STRIDE) + 2
    raw = bytearray(size)
    for index, value in enumerate(values):
        struct.pack_into("<H", raw, index * SM_BATTLE_PLAYER_STRIDE, int(value))
    return bytes(raw)


class BattleRPC:
    def __init__(self, *, active: bool, max_hp=(60, 80), displayed_hp=(50, 40), actual_hp=(50, 40)):
        self.process = AzaharProcess(41, TITLE_ID_SUN, "niji_loc")
        self.active = bool(active)
        self.max_raw = lane(list(max_hp))
        self.displayed_raw = lane(list(displayed_hp))
        self.actual_raw = lane(list(actual_hp))
        self.read_calls: list[tuple[int, int]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def process_list(self):
        return [self.process]

    def set_process(self, process_id: int):
        assert process_id == self.process.process_id

    def read_memory(self, address: int, size: int) -> bytes:
        self.read_calls.append((int(address), int(size)))
        if int(address) == SM_BATTLE_STATE_ADDRESS:
            value = SM_BATTLE_STATE_ACTIVE_VALUE if self.active else 0
            return struct.pack("<I", value)
        if int(address) == SM_BATTLE_PLAYER_MAX_HP_BASE:
            return self.max_raw[: int(size)]
        if int(address) == SM_BATTLE_PLAYER_DISPLAY_HP_BASE:
            return self.displayed_raw[: int(size)]
        if int(address) == SM_BATTLE_PLAYER_ACTUAL_HP_BASE:
            return self.actual_raw[: int(size)]
        return b"\0" * int(size)


def reader(fake: BattleRPC) -> SMLiveReader:
    return SMLiveReader(
        DATA_DIR / "move_catalog.json",
        client_factory=lambda: fake,
        stable_delay=0,
        snapshot_attempts=1,
    )


def test_alpha41_reports_none_from_evidence_backed_battle_flag() -> None:
    fake = BattleRPC(active=False)
    probe = reader(fake).read_battle_probe(game(mon(1, 25, current_hp=50, max_hp=60)))
    assert probe is not None
    assert probe.state == "none"
    assert probe.validated is True
    assert probe.health_game is None
    # Fuera de combate no se leen carriles HP innecesariamente.
    assert all(address not in {
        SM_BATTLE_PLAYER_MAX_HP_BASE,
        SM_BATTLE_PLAYER_DISPLAY_HP_BASE,
        SM_BATTLE_PLAYER_ACTUAL_HP_BASE,
    } for address, _size in fake.read_calls)


def test_alpha41_uses_displayed_hp_when_battle_lane_matches_live_party() -> None:
    current = game(
        mon(1, 25, current_hp=50, max_hp=60),
        mon(2, 722, current_hp=40, max_hp=80),
    )
    fake = BattleRPC(
        active=True,
        max_hp=(60, 80),
        displayed_hp=(0, 37),
        actual_hp=(0, 35),
    )
    probe = reader(fake).read_battle_probe(current)
    assert probe is not None
    assert probe.state == "battle"
    assert probe.validated is True
    assert probe.reason.startswith("flag activo")
    assert probe.hp_pairs == ((0, 60), (37, 80))
    assert probe.actual_hp_pairs == ((0, 60), (35, 80))
    assert probe.health_game is not None
    assert [(p.current_hp, p.max_hp) for p in probe.health_game.party] == [(0, 60), (37, 80)]
    # La identidad/rol no se reconstruye desde una tabla de batalla: se clona
    # exclusivamente de la party PK7 ya demostrada.
    assert [p.pid for p in probe.health_game.party] == [p.pid for p in current.party]


def test_alpha41_rejects_hp_lane_if_max_hp_does_not_prove_same_party() -> None:
    current = game(
        mon(1, 25, current_hp=50, max_hp=60),
        mon(2, 722, current_hp=40, max_hp=80),
    )
    fake = BattleRPC(
        active=True,
        max_hp=(61, 80),  # dirección/familia equivocada -> jamás publicar HP
        displayed_hp=(0, 37),
        actual_hp=(0, 35),
    )
    probe = reader(fake).read_battle_probe(current)
    assert probe is not None
    assert probe.state == "battle"
    assert probe.validated is False
    assert probe.health_game is None
    assert "PK7 max=60" in probe.reason


def test_alpha41_requires_battle_flag_to_remain_active_across_hp_read() -> None:
    current = game(mon(1, 25, current_hp=50, max_hp=60))

    class EndsDuringRead(BattleRPC):
        def __init__(self):
            super().__init__(active=True, max_hp=(60,), displayed_hp=(0,), actual_hp=(0,))
            self.state_reads = 0

        def read_memory(self, address: int, size: int) -> bytes:
            if int(address) == SM_BATTLE_STATE_ADDRESS:
                self.state_reads += 1
                value = SM_BATTLE_STATE_ACTIVE_VALUE if self.state_reads == 1 else 0
                return struct.pack("<I", value)
            return super().read_memory(address, size)

    probe = reader(EndsDuringRead()).read_battle_probe(current)
    assert probe is None
