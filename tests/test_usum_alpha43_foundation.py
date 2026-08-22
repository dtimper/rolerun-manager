from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from app.azahar_rpc import AzaharProcess
from app.config import APP_VERSION
from app.save_engine_client import SaveGameData, SavePokemon
from app.usum_live import (
    USUM_BATTLE_PLAYER_ACTUAL_HP_BASE,
    USUM_BATTLE_PLAYER_DISPLAY_HP_BASE,
    USUM_BATTLE_PLAYER_MAX_HP_BASE,
    USUM_BATTLE_PLAYER_STRIDE,
    USUM_BATTLE_STATE_ACTIVE_VALUE,
    USUM_BATTLE_STATE_ADDRESS,
    USUM_KAHUNA_ZCRYSTAL_KEY_IDS,
    USUM_PC_BOX_COUNT,
    USUM_PC_BOX_SLOT_COUNT,
    USUM_PC_BOX_BASE_REFERENCE,
    USUM_PC_CURRENT_BOX_REFERENCE,
    USUM_SAVE_BOX_LAYOUT_BLOCK_OFFSET,
    USUM_SAVE_BOX_LAYOUT_BLOCK_SIZE,
    USUM_SAVE_ITEM_BLOCK_OFFSET,
    USUM_SAVE_ITEM_BLOCK_SIZE,
    USUM_SAVE_MISC_BLOCK_OFFSET,
    USUM_SAVE_MISC_BLOCK_SIZE,
    USUM_SAVE_PC_BLOCK_OFFSET,
    USUM_SAVE_PC_BLOCK_SIZE,
    USUM_ZCRYSTAL_KEY_IDS,
    USUM_ZCRYSTAL_POCKET_OFFSET,
    USUM_ZCRYSTAL_POCKET_SLOT_COUNT,
    USUMLiveError,
    USUMLiveReader,
    count_usum_kahuna_badges,
    parse_usum_zcrystal_keys,
)
from app.realtime.usum_adapter import USUMRealTimeAdapter
from app.usum_rom_service import (
    USUM_ULTRA_MOON_TITLE_ID,
    USUM_ULTRA_SUN_TITLE_ID,
    _USUM_TM_DISPLACEMENT,
    _USUM_TM_SIGNATURE,
    _USUM_TM_SEARCH_START,
    _tm_table_from_code,
)


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
SM_SUN_TITLE_ID = 0x0004000000164800


def _mon(slot: int, *, max_hp: int = 60, current_hp: int = 50) -> SavePokemon:
    return SavePokemon(
        slot=slot, species_id=25, species="Pikachu", nickname="Pikachu", level=25,
        held_item="Ninguno", ability="Static", moves=["Placaje", "—", "—", "—"],
        move_ids=[33, 0, 0, 0], is_egg=False, markings=[False] * 6,
        role="SIN ROL", role_symbol="", pid=0x1000 + slot, tid=11, sid=22,
        current_hp=current_hp, max_hp=max_hp,
    )


def _game(*party: SavePokemon) -> SaveGameData:
    return SaveGameData(
        game="Pokémon UltraSol", save_type="SAV7USUM + Azahar RPC (USUM en vivo)",
        generation=7, trainer="Tester", party=list(party), raw={"liveSync": True},
    )


def _items_block(crystals: tuple[int, ...] = ()) -> bytes:
    raw = bytearray(USUM_SAVE_ITEM_BLOCK_SIZE)
    raw[0x120:0x130] = bytes(range(1, 17))
    raw[0xA20:0xA30] = bytes(range(17, 33))
    for index, item_id in enumerate(crystals):
        struct.pack_into(
            "<I", raw, USUM_ZCRYSTAL_POCKET_OFFSET + index * 4,
            int(item_id) | (1 << 10),
        )
    return bytes(raw)


def _lane(values: tuple[int, ...]) -> bytes:
    size = ((len(values) - 1) * USUM_BATTLE_PLAYER_STRIDE) + 2
    raw = bytearray(size)
    for index, value in enumerate(values):
        struct.pack_into("<H", raw, index * USUM_BATTLE_PLAYER_STRIDE, int(value))
    return bytes(raw)


class _BattleRPC:
    def __init__(self, *, title_id: int, active: bool, max_hp=(60,), displayed=(50,), actual=(50,)):
        self.process = AzaharProcess(91, int(title_id), "niji_loc")
        self.active = active
        self.max_raw = _lane(tuple(max_hp))
        self.displayed_raw = _lane(tuple(displayed))
        self.actual_raw = _lane(tuple(actual))

    def __enter__(self): return self
    def __exit__(self, *_args): return None
    def process_list(self): return [self.process]
    def set_process(self, process_id: int): assert int(process_id) == self.process.process_id

    def read_memory(self, address: int, size: int) -> bytes:
        if int(address) == USUM_BATTLE_STATE_ADDRESS:
            return struct.pack("<I", USUM_BATTLE_STATE_ACTIVE_VALUE if self.active else 0)
        if int(address) == USUM_BATTLE_PLAYER_MAX_HP_BASE:
            return self.max_raw[: int(size)]
        if int(address) == USUM_BATTLE_PLAYER_DISPLAY_HP_BASE:
            return self.displayed_raw[: int(size)]
        if int(address) == USUM_BATTLE_PLAYER_ACTUAL_HP_BASE:
            return self.actual_raw[: int(size)]
        return b"\0" * int(size)


def _reader(fake=None) -> USUMLiveReader:
    return USUMLiveReader(
        DATA_DIR / "move_catalog.json",
        client_factory=(lambda: fake) if fake is not None else None,
        stable_delay=0, snapshot_attempts=1,
    )


def test_alpha43_version_and_official_usum_save_layout() -> None:
    assert APP_VERSION == "0.2.2-alpha.58"
    assert (USUM_SAVE_ITEM_BLOCK_OFFSET, USUM_SAVE_ITEM_BLOCK_SIZE) == (0x00000, 0x0E28)
    assert (USUM_SAVE_MISC_BLOCK_OFFSET, USUM_SAVE_MISC_BLOCK_SIZE) == (0x04400, 0x01FC)
    assert (USUM_SAVE_BOX_LAYOUT_BLOCK_OFFSET, USUM_SAVE_BOX_LAYOUT_BLOCK_SIZE) == (0x04C00, 0x05E6)
    assert (USUM_SAVE_PC_BLOCK_OFFSET, USUM_SAVE_PC_BLOCK_SIZE) == (0x05200, 0x36600)
    assert (USUM_PC_BOX_COUNT, USUM_PC_BOX_SLOT_COUNT) == (32, 30)
    assert (USUM_ZCRYSTAL_POCKET_OFFSET, USUM_ZCRYSTAL_POCKET_SLOT_COUNT) == (0x0D70, 35)


def test_alpha46_pkmn_ntr_usum_box_offsets_are_explicit_references() -> None:
    # PKMN-NTR LookupTable: US/UM BoxOffset y CurrentboxOffset. RoleRun aún
    # exige validación runtime antes de publicar/escribir.
    assert USUM_PC_BOX_BASE_REFERENCE == 0x33015AB0
    assert USUM_PC_CURRENT_BOX_REFERENCE == 0x33015AA7


@pytest.mark.parametrize("count", range(5))
def test_alpha43_kahuna_medals_are_exact_prefix(count: int) -> None:
    raw = _items_block(USUM_KAHUNA_ZCRYSTAL_KEY_IDS[:count])
    assert parse_usum_zcrystal_keys(raw) is not None
    assert count_usum_kahuna_badges(raw) == count


def test_alpha43_accepts_usum_only_zcrystal_ids_but_rejects_kahuna_gaps() -> None:
    # 927..932 son cristales añadidos por USUM y deben ser estructuralmente válidos.
    assert 927 in USUM_ZCRYSTAL_KEY_IDS and 932 in USUM_ZCRYSTAL_KEY_IDS
    raw = _items_block((927, 932))
    assert parse_usum_zcrystal_keys(raw) == frozenset({927, 932})
    gap = _items_block((USUM_KAHUNA_ZCRYSTAL_KEY_IDS[0], USUM_KAHUNA_ZCRYSTAL_KEY_IDS[2]))
    assert count_usum_kahuna_badges(gap) is None


@pytest.mark.parametrize("title_id", [USUM_ULTRA_SUN_TITLE_ID, USUM_ULTRA_MOON_TITLE_ID])
def test_alpha43_process_selection_requires_exact_usum_title_id(title_id: int) -> None:
    process = AzaharProcess(9, title_id, "niji_loc")
    assert USUMLiveReader._find_usum_process([process]) is process


def test_alpha43_process_selection_rejects_sm_and_titleless_niji_loc() -> None:
    with pytest.raises(USUMLiveError, match="Title ID válido"):
        USUMLiveReader._find_usum_process([AzaharProcess(9, SM_SUN_TITLE_ID, "niji_loc")])
    # El nombre interno es compartido con SM; sin Title ID no hay evidencia suficiente.
    with pytest.raises(USUMLiveError, match="Title ID válido"):
        USUMLiveReader._find_usum_process([AzaharProcess(9, 0, "niji_loc")])


@pytest.mark.parametrize("title_id", [USUM_ULTRA_SUN_TITLE_ID, USUM_ULTRA_MOON_TITLE_ID])
def test_alpha43_battle_hp_lane_is_accepted_only_after_maxhp_matches_party(title_id: int) -> None:
    current = _game(_mon(1, max_hp=60, current_hp=50))
    fake = _BattleRPC(title_id=title_id, active=True, max_hp=(60,), displayed=(0,), actual=(0,))
    probe = _reader(fake).read_battle_probe(current)
    assert probe is not None and probe.state == "battle" and probe.validated is True
    assert probe.health_game is not None
    assert probe.health_game.party[0].current_hp == 0

    wrong = _BattleRPC(title_id=title_id, active=True, max_hp=(61,), displayed=(0,), actual=(0,))
    rejected = _reader(wrong).read_battle_probe(current)
    assert rejected is not None and rejected.state == "battle" and rejected.validated is False
    assert rejected.health_game is None


def test_alpha43_usum_tm_table_applies_pk3ds_0x22_displacement() -> None:
    values = list(range(1, 101))
    start = _USUM_TM_SEARCH_START + 0x100
    code = bytearray(start + len(_USUM_TM_SIGNATURE) + _USUM_TM_DISPLACEMENT + 200 + 16)
    code[start:start + len(_USUM_TM_SIGNATURE)] = _USUM_TM_SIGNATURE
    table = start + len(_USUM_TM_SIGNATURE) + _USUM_TM_DISPLACEMENT
    for index, move_id in enumerate(values):
        struct.pack_into("<H", code, table + index * 2, move_id)
    profile = _tm_table_from_code(bytes(code), set(values))
    assert len(profile) == 100
    assert [profile[i].move_id for i in range(1, 101)] == values


def test_alpha43_adapter_is_dedicated_usum_backend() -> None:
    adapter = USUMRealTimeAdapter(_reader())
    state = adapter.runtime_state()
    assert adapter.game_key == "usum"
    assert adapter.key == "usum-azahar-rpc-roles"
    assert "candidate-usum" in state["capabilities"]["party"]
    assert "candidate-usum" in state["capabilities"]["pc"]


def test_alpha56_battle_lane_validates_slots_independently() -> None:
    current = _game(
        _mon(1, max_hp=60, current_hp=50),
        _mon(2, max_hp=80, current_hp=40),
    )
    # Slot 1 is fully demonstrated and reaches 0. Slot 2 deliberately has a
    # mismatched Max HP. Alpha.55 rejected the entire lane; alpha.56 must keep
    # slot 1 live while leaving slot 2 on the safe party snapshot.
    fake = _BattleRPC(
        title_id=USUM_ULTRA_SUN_TITLE_ID, active=True,
        max_hp=(60, 81), displayed=(0, 37), actual=(0, 35),
    )
    probe = _reader(fake).read_battle_probe(current)
    assert probe is not None and probe.state == "battle" and probe.validated is True
    assert probe.health_game is not None
    assert probe.health_game.party[0].current_hp == 0
    assert probe.health_game.party[0].max_hp == 60
    assert probe.health_game.party[1].current_hp == 40
    assert probe.health_game.party[1].max_hp == 80
    assert "1/2" in probe.reason
    assert "2:81/37/35 vs PK7 80" in probe.reason


def test_alpha56_battle_lane_still_rejects_when_no_slot_is_proven(
    isolated_role_run_log_dir: Path,
) -> None:
    current = _game(
        _mon(1, max_hp=60, current_hp=50),
        _mon(2, max_hp=80, current_hp=40),
    )
    fake = _BattleRPC(
        title_id=USUM_ULTRA_SUN_TITLE_ID, active=True,
        max_hp=(61, 81), displayed=(0, 37), actual=(0, 35),
    )
    reader = _reader(fake)
    assert reader._battle_trace_path.parent == isolated_role_run_log_dir
    probe = reader.read_battle_probe(current)
    assert probe is not None and probe.state == "battle" and probe.validated is False
    assert probe.health_game is None
    assert "ningún slot" in probe.reason
    assert (isolated_role_run_log_dir / "usum_battle_health_trace_latest.jsonl").is_file()


def test_alpha58_battle_trace_records_actual_displayed_and_mapping(tmp_path: Path, monkeypatch) -> None:
    import app.usum_live as module

    monkeypatch.setattr(module, "LOG_DIR", tmp_path)
    current = _game(
        _mon(1, max_hp=60, current_hp=50),
        _mon(2, max_hp=80, current_hp=40),
    )
    fake = _BattleRPC(
        title_id=USUM_ULTRA_SUN_TITLE_ID, active=True,
        max_hp=(60, 80), displayed=(12, 40), actual=(0, 40),
    )
    reader = _reader(fake)
    probe = reader.read_battle_probe(current)
    assert probe is not None and probe.validated is True

    trace = tmp_path / "usum_battle_health_trace_latest.jsonl"
    assert trace.is_file()
    rows = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    sample = next(item for item in rows if item.get("event") == "battle-sample")
    assert sample["rows"][0]["displayed_hp"] == 12
    assert sample["rows"][0]["actual_hp"] == 0
    assert sample["rows"][0]["max_hp_candidate_party_slots"] == [1]
    assert sample["validated_slots"] == [1, 2]
