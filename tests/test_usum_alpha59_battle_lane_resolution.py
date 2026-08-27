from __future__ import annotations

import json
import struct
from pathlib import Path

from app.azahar_rpc import AzaharProcess
from app.live_party_watch import detect_fainted_transitions
from app.save_engine_client import SaveGameData, SavePokemon
from app.usum_live import (
    PK7_STORED_SIZE,
    USUM_BATTLE_ACTUAL_FROM_MAX,
    USUM_BATTLE_DISPLAY_FROM_MAX,
    USUM_BATTLE_PHASE_ACTIVE_VALUE,
    USUM_BATTLE_PHASE_ADDRESS,
    USUM_BATTLE_PHASE_TERMINAL_VALUE,
    USUM_BATTLE_PLAYER_MAX_HP_BASE,
    USUM_BATTLE_PLAYER_STRIDE,
    USUM_BATTLE_STATE_ACTIVE_VALUE,
    USUM_BATTLE_STATE_ADDRESS,
    USUM_BATTLE_STATE_TERMINAL_VALUE,
    USUM_PARTY_REFERENCE_ADDRESS,
    USUMLiveReader,
)
from app.usum_rom_service import USUM_ULTRA_SUN_TITLE_ID
from app.win_process_memory import HostPartyTarget, WindowsProcessMemory


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
PARTY_MAXES = (18, 19, 149, 19, 101, 17)
DYNAMIC_MAX_BASE = 0x30012776
HOST_PARTY_BASE = 0x50000000
HOST_MAX_BASE = HOST_PARTY_BASE + DYNAMIC_MAX_BASE - USUM_PARTY_REFERENCE_ADDRESS


def _lane(values: tuple[int, ...]) -> bytes:
    size = ((len(values) - 1) * USUM_BATTLE_PLAYER_STRIDE) + 2
    raw = bytearray(size)
    for index, value in enumerate(values):
        struct.pack_into("<H", raw, index * USUM_BATTLE_PLAYER_STRIDE, int(value))
    return bytes(raw)


def _game(*, first_hp: int = 18) -> SaveGameData:
    party = []
    for index, max_hp in enumerate(PARTY_MAXES):
        party.append(SavePokemon(
            slot=index + 1, species_id=25 + index, species=f"Species {25 + index}",
            nickname=f"Mon {index + 1}", level=20, held_item="Ninguno", ability="",
            moves=["Placaje", "—", "—", "—"], move_ids=[33, 0, 0, 0],
            is_egg=False, markings=[False] * 6, role="SIN ROL", role_symbol="",
            pid=0x12340000 + index, tid=11, sid=22,
            current_hp=first_hp if index == 0 else max_hp, max_hp=max_hp,
        ))
    return SaveGameData(
        game="Pokémon UltraSol", save_type="SAV7USUM + Azahar RPC (USUM en vivo)",
        generation=7, trainer="Tester", party=party, raw={"liveSync": True},
    )


class _DynamicBattleRPC:
    def __init__(self, dynamic_bases: tuple[int, ...] = (DYNAMIC_MAX_BASE,)) -> None:
        self.process = AzaharProcess(11, USUM_ULTRA_SUN_TITLE_ID, "momiji")
        self.active = True
        self.dynamic_bases = set(int(base) for base in dynamic_bases)
        self.displayed = (0, 19, 149, 19, 101, 17)
        self.actual = self.displayed
        self.read_addresses: list[int] = []

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
        self.read_addresses.append(address)
        if address == USUM_BATTLE_STATE_ADDRESS:
            return struct.pack(
                "<I",
                USUM_BATTLE_STATE_ACTIVE_VALUE if self.active else USUM_BATTLE_STATE_TERMINAL_VALUE,
            )
        if address == USUM_BATTLE_PHASE_ADDRESS:
            return struct.pack(
                "<I",
                USUM_BATTLE_PHASE_ACTIVE_VALUE if self.active else USUM_BATTLE_PHASE_TERMINAL_VALUE,
            )
        if address == USUM_BATTLE_PLAYER_MAX_HP_BASE:
            return _lane((0x8400, 42, 15, 0, 0, 0))[: int(size)]
        if address == USUM_BATTLE_PLAYER_MAX_HP_BASE + USUM_BATTLE_DISPLAY_FROM_MAX:
            return _lane((0xAF82, 0xC2AC, 3340, 25972, 0, 0))[: int(size)]
        if address == USUM_BATTLE_PLAYER_MAX_HP_BASE + USUM_BATTLE_ACTUAL_FROM_MAX:
            return _lane((0, 60395, 60395, 0, 60395, 60395))[: int(size)]
        for base in self.dynamic_bases:
            if address == base:
                return _lane(PARTY_MAXES)[: int(size)]
            if address == base + USUM_BATTLE_DISPLAY_FROM_MAX:
                return _lane(tuple(self.displayed))[: int(size)]
            if address == base + USUM_BATTLE_ACTUAL_FROM_MAX:
                return _lane(tuple(self.actual))[: int(size)]
        return b"\0" * int(size)


class _BattleHostMemory:
    def __init__(self, host_lanes: tuple[int, ...] = (HOST_MAX_BASE,)) -> None:
        self.host_lanes = host_lanes
        self.party_calls = 0
        self.lane_calls = 0

    def find_party_targets(self, **kwargs):
        self.party_calls += 1
        assert len(kwargs["slot_raws"]) == 6
        assert kwargs["stored_size"] == PK7_STORED_SIZE
        return [HostPartyTarget(4204, "azahar.exe", HOST_PARTY_BASE)]

    def find_strided_u16_lanes_in_anchor_region(self, **kwargs):
        self.lane_calls += 1
        assert tuple(kwargs["expected_values"]) == PARTY_MAXES
        assert kwargs["stride"] == USUM_BATTLE_PLAYER_STRIDE
        assert kwargs["displayed_delta"] == USUM_BATTLE_DISPLAY_FROM_MAX
        assert kwargs["actual_delta"] == USUM_BATTLE_ACTUAL_FROM_MAX
        return list(self.host_lanes)


def _dynamic_reader(rpc: _DynamicBattleRPC, host: _BattleHostMemory, current: SaveGameData) -> USUMLiveReader:
    reader = USUMLiveReader(
        DATA_DIR / "move_catalog.json", client_factory=lambda: rpc,
        stable_delay=0, snapshot_attempts=1, host_memory_factory=lambda: host,
    )
    process_key = reader._battle_process_key(rpc.process)
    reader._battle_party_anchor = (
        process_key, USUM_PARTY_REFERENCE_ADDRESS, tuple(b"X" * 260 for _ in range(6)),
    )
    reader._parse_slots = lambda _raws: list(current.party)  # type: ignore[method-assign]
    reader._party_continuity_proof = (  # type: ignore[method-assign]
        lambda _observed, _current: "exact-slot-identity"
    )
    return reader


def test_alpha59_invalid_nominal_lane_resolves_unique_runtime_lane_and_reaches_faint_detector() -> None:
    current = _game(first_hp=18)
    rpc = _DynamicBattleRPC()
    host = _BattleHostMemory()
    reader = _dynamic_reader(rpc, host, current)

    probe = reader.read_battle_probe(current)

    assert probe is not None and probe.validated is True and probe.health_game is not None
    assert probe.health_game.party[0].current_hp == 0
    assert probe.health_game.raw["liveBattleMaxHpBase"] == f"0x{DYNAMIC_MAX_BASE:08X}"
    transitions = detect_fainted_transitions(current, probe.health_game)
    assert [transition.slot for transition in transitions] == [1]
    assert host.party_calls == 1 and host.lane_calls == 1
    assert USUM_BATTLE_PLAYER_MAX_HP_BASE in rpc.read_addresses
    assert DYNAMIC_MAX_BASE in rpc.read_addresses


def test_alpha59_ambiguous_runtime_lanes_are_rejected_instead_of_guessing() -> None:
    second_guest = DYNAMIC_MAX_BASE + 0x20000
    second_host = HOST_PARTY_BASE + second_guest - USUM_PARTY_REFERENCE_ADDRESS
    current = _game(first_hp=18)
    rpc = _DynamicBattleRPC((DYNAMIC_MAX_BASE, second_guest))
    host = _BattleHostMemory((HOST_MAX_BASE, second_host))
    reader = _dynamic_reader(rpc, host, current)

    probe = reader.read_battle_probe(current)

    assert probe is not None and probe.validated is False
    assert probe.health_game is None
    assert reader._battle_lane_resolution["status"] == "rejected"
    assert "única tabla" in str(reader._battle_lane_resolution["reason"])


def test_alpha59_trace_keeps_first_episode_when_flag_reenters(
    isolated_role_run_log_dir: Path,
) -> None:
    current = _game(first_hp=18)
    rpc = _DynamicBattleRPC((USUM_BATTLE_PLAYER_MAX_HP_BASE,))
    rpc.displayed = PARTY_MAXES
    rpc.actual = PARTY_MAXES
    # Para este test la candidata nominal debe ser válida.
    original_read = rpc.read_memory

    def nominal_valid(address: int, size: int) -> bytes:
        if int(address) == USUM_BATTLE_PLAYER_MAX_HP_BASE:
            return _lane(PARTY_MAXES)[: int(size)]
        if int(address) == USUM_BATTLE_PLAYER_MAX_HP_BASE + USUM_BATTLE_DISPLAY_FROM_MAX:
            return _lane(PARTY_MAXES)[: int(size)]
        if int(address) == USUM_BATTLE_PLAYER_MAX_HP_BASE + USUM_BATTLE_ACTUAL_FROM_MAX:
            return _lane(PARTY_MAXES)[: int(size)]
        return original_read(address, size)

    rpc.read_memory = nominal_valid  # type: ignore[method-assign]
    reader = USUMLiveReader(
        DATA_DIR / "move_catalog.json", client_factory=lambda: rpc,
        stable_delay=0, snapshot_attempts=1,
    )

    assert reader.read_battle_probe(current).validated is True
    rpc.active = False
    assert reader.read_battle_probe(current).state == "none"
    rpc.active = True
    assert reader.read_battle_probe(current).validated is True

    trace = isolated_role_run_log_dir / "usum_battle_health_trace_latest.jsonl"
    events = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    starts = [event for event in events if event.get("event") == "battle-start"]
    samples = [event for event in events if event.get("event") == "battle-sample"]
    assert [event["episode"] for event in starts] == [1, 2]
    assert [event["episode"] for event in samples] == [1, 2]
    assert any(event.get("event") == "battle-end" and event["episode"] == 1 for event in events)
    archive_files = list((isolated_role_run_log_dir / "USUM-Battle-Traces").glob("*.jsonl"))
    assert len(archive_files) == 1
    assert archive_files[0].read_bytes() == trace.read_bytes()


def _write_host_lane(region: bytearray, *, region_base: int, lane_base: int) -> None:
    relative = int(lane_base) - int(region_base)
    for index, max_hp in enumerate(PARTY_MAXES):
        row = relative + index * USUM_BATTLE_PLAYER_STRIDE
        struct.pack_into("<H", region, row, max_hp)
        struct.pack_into("<H", region, row + USUM_BATTLE_DISPLAY_FROM_MAX, max_hp)
        struct.pack_into("<H", region, row + USUM_BATTLE_ACTUAL_FROM_MAX, max_hp)


def test_alpha59_host_scan_requires_complete_unique_strided_hp_structure() -> None:
    region_base = 0x10000000
    region = bytearray(0x30000)
    lane_base = region_base + 0x7000
    _write_host_lane(region, region_base=region_base, lane_base=lane_base)
    # Una coincidencia parcial de Max HP no es candidatura.
    struct.pack_into("<H", region, 0x19000 + 2 * USUM_BATTLE_PLAYER_STRIDE, max(PARTY_MAXES))

    memory = WindowsProcessMemory.__new__(WindowsProcessMemory)
    memory.open_process = lambda _pid: object()
    memory.close_process = lambda _handle: None
    memory.iter_writable_regions = lambda _handle: iter([(region_base, len(region))])
    memory.read = lambda _handle, address, size: bytes(region[
        int(address) - region_base:int(address) - region_base + int(size)
    ])

    found = memory.find_strided_u16_lanes_in_anchor_region(
        pid=1, anchor_address=region_base + 0x100,
        expected_values=PARTY_MAXES, stride=USUM_BATTLE_PLAYER_STRIDE,
        displayed_delta=USUM_BATTLE_DISPLAY_FROM_MAX,
        actual_delta=USUM_BATTLE_ACTUAL_FROM_MAX,
        chunk_size=0x2000,
    )
    assert found == [lane_base]
