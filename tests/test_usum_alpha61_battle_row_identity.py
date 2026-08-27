from __future__ import annotations

import json
import struct
from pathlib import Path

from app.azahar_rpc import AzaharProcess
from app.live_party_watch import detect_fainted_transitions
from app.oras_live import encrypt_pk6_stored
from app.save_engine_client import SaveGameData, SavePokemon
from app.usum_live import (
    PK7_STORED_SIZE,
    USUM_BATTLE_ACTUAL_FROM_MAX,
    USUM_BATTLE_DISPLAY_FROM_MAX,
    USUM_BATTLE_PHASE_ACTIVE_VALUE,
    USUM_BATTLE_PHASE_ADDRESS,
    USUM_BATTLE_PLAYER_IDENTITY_BASE,
    USUM_BATTLE_PLAYER_IDENTITY_STRIDE,
    USUM_BATTLE_PLAYER_MAX_HP_BASE,
    USUM_BATTLE_PLAYER_STRIDE,
    USUM_BATTLE_STATE_ACTIVE_VALUE,
    USUM_BATTLE_STATE_ADDRESS,
    USUMLiveReader,
)
from app.usum_rom_service import USUM_ULTRA_SUN_TITLE_ID
from app.win_process_memory import WindowsProcessMemory


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
PARTY_SPECIES = (379, 133, 115, 137, 763, 455)
PARTY_PIDS = tuple(0xA0000000 + index for index in range(6))
PARTY_MAXES = (18, 19, 149, 19, 101, 17)
BATTLE_ORDER = (3, 1, 2, 0, 4, 5)  # Porygon, Eevee, Kangaskhan, Registeel, ...

def _lane(values: tuple[int, ...]) -> bytes:
    size = ((len(values) - 1) * USUM_BATTLE_PLAYER_STRIDE) + 2
    raw = bytearray(size)
    for index, value in enumerate(values):
        struct.pack_into("<H", raw, index * USUM_BATTLE_PLAYER_STRIDE, int(value))
    return bytes(raw)


def _stored_pk7(*, species: int, pid: int) -> bytes:
    plain = bytearray(PK7_STORED_SIZE)
    struct.pack_into("<I", plain, 0x00, 0x11000000 | int(species))
    struct.pack_into("<H", plain, 0x08, int(species))
    struct.pack_into("<H", plain, 0x0C, 835)
    struct.pack_into("<H", plain, 0x0E, 6011)
    struct.pack_into("<I", plain, 0x18, int(pid))
    checksum = sum(struct.unpack_from("<112H", plain, 8)) & 0xFFFF
    struct.pack_into("<H", plain, 0x06, checksum)
    return encrypt_pk6_stored(bytes(plain))


def _identity_lane() -> bytes:
    size = ((len(BATTLE_ORDER) - 1) * USUM_BATTLE_PLAYER_IDENTITY_STRIDE) + PK7_STORED_SIZE
    raw = bytearray(size)
    for row, party_index in enumerate(BATTLE_ORDER):
        stored = _stored_pk7(
            species=PARTY_SPECIES[party_index],
            pid=PARTY_PIDS[party_index],
        )
        start = row * USUM_BATTLE_PLAYER_IDENTITY_STRIDE
        raw[start:start + PK7_STORED_SIZE] = stored
    return bytes(raw)


def _game() -> SaveGameData:
    names = ("Registeel", "Eevee", "Kangaskhan", "Porygon", "Tsareena", "Carnivine")
    return SaveGameData(
        game="Pokémon UltraSol",
        save_type="SAV7USUM + Azahar RPC (USUM en vivo)",
        generation=7,
        trainer="Tester",
        party=[
            SavePokemon(
                slot=index + 1,
                species_id=PARTY_SPECIES[index],
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
                pid=PARTY_PIDS[index],
                tid=835,
                sid=6011,
                current_hp=PARTY_MAXES[index],
                max_hp=PARTY_MAXES[index],
            )
            for index in range(6)
        ],
        raw={"liveSync": True},
    )


class _IdentityBattleRPC:
    def __init__(self) -> None:
        self.process = AzaharProcess(11, USUM_ULTRA_SUN_TITLE_ID, "momiji")
        self.max_hp = tuple(PARTY_MAXES[index] for index in BATTLE_ORDER)
        self.displayed = self.max_hp
        self.actual = self.max_hp
        self.identities = _identity_lane()

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
            return struct.pack("<I", USUM_BATTLE_STATE_ACTIVE_VALUE)
        if address == USUM_BATTLE_PHASE_ADDRESS:
            return struct.pack("<I", USUM_BATTLE_PHASE_ACTIVE_VALUE)
        if address == USUM_BATTLE_PLAYER_MAX_HP_BASE:
            return _lane(tuple(self.max_hp))[: int(size)]
        if address == USUM_BATTLE_PLAYER_MAX_HP_BASE + USUM_BATTLE_DISPLAY_FROM_MAX:
            return _lane(tuple(self.displayed))[: int(size)]
        if address == USUM_BATTLE_PLAYER_MAX_HP_BASE + USUM_BATTLE_ACTUAL_FROM_MAX:
            return _lane(tuple(self.actual))[: int(size)]
        if address == USUM_BATTLE_PLAYER_IDENTITY_BASE:
            return self.identities[: int(size)]
        return b"\0" * int(size)


def test_alpha61_equal_full_hp_rows_use_pk7_identity_before_the_ko(
    isolated_role_run_log_dir: Path,
) -> None:
    current = _game()
    rpc = _IdentityBattleRPC()
    reader = USUMLiveReader(
        DATA_DIR / "move_catalog.json",
        client_factory=lambda: rpc,
        stable_delay=0,
        snapshot_attempts=1,
    )

    # Esta es la condición física que alpha.60 no podía resolver: Eevee y
    # Porygon empiezan ambos a 19/19, pero Porygon ocupa la fila 1.
    baseline = reader.read_battle_probe(current)
    assert baseline is not None and baseline.health_game is not None
    assert [member.current_hp for member in baseline.health_game.party] == list(PARTY_MAXES)

    rpc.displayed = (0, 19, 149, 18, 101, 17)
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
    assert samples[-1]["rows"][0]["mapped_party_slot"] == 4
    assert samples[-1]["rows"][0]["identity"]["species_id"] == 137
    assert samples[-1]["validated_slots"] == [1, 2, 3, 4, 5, 6]


def test_alpha61_host_lane_scan_accepts_the_same_max_hp_multiset_in_battle_order() -> None:
    region_base = 0x10000000
    region = bytearray(0x30000)
    lane_base = region_base + 0x7000
    battle_maxes = tuple(PARTY_MAXES[index] for index in BATTLE_ORDER)
    relative = lane_base - region_base
    for row_index, max_hp in enumerate(battle_maxes):
        row = relative + row_index * USUM_BATTLE_PLAYER_STRIDE
        struct.pack_into("<H", region, row, max_hp)
        struct.pack_into("<H", region, row + USUM_BATTLE_DISPLAY_FROM_MAX, max_hp)
        struct.pack_into("<H", region, row + USUM_BATTLE_ACTUAL_FROM_MAX, max_hp)

    memory = WindowsProcessMemory.__new__(WindowsProcessMemory)
    memory.open_process = lambda _pid: object()
    memory.close_process = lambda _handle: None
    memory.iter_writable_regions = lambda _handle: iter([(region_base, len(region))])
    memory.read = lambda _handle, address, size: bytes(region[
        int(address) - region_base:int(address) - region_base + int(size)
    ])

    found = memory.find_strided_u16_lanes_in_anchor_region(
        pid=1,
        anchor_address=region_base + 0x100,
        expected_values=PARTY_MAXES,
        stride=USUM_BATTLE_PLAYER_STRIDE,
        displayed_delta=USUM_BATTLE_DISPLAY_FROM_MAX,
        actual_delta=USUM_BATTLE_ACTUAL_FROM_MAX,
        chunk_size=0x2000,
    )

    assert found == [lane_base]
