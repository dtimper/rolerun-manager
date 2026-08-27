from __future__ import annotations

import json
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.azahar_rpc import AzaharProcess
from app.config import APP_VERSION
from app.models import PendingInventoryChange, PendingPartyHeal
from app.oras_live import encrypt_pk6, encrypt_pk6_stored
from app.oras_tm_service import ORASPersonalStats, ORASTMProfile
from app.save_engine_client import SaveGameData, SavePokemon
from app.usum_live import (
    PK7_PARTY_SIZE,
    PK7_STORED_SIZE,
    USUM_BATTLE_PHASE_ACTIVE_VALUE,
    USUM_BATTLE_PHASE_ADDRESS,
    USUM_BATTLE_PHASE_TERMINAL_VALUE,
    USUM_BATTLE_PLAYER_ACTUAL_HP_BASE,
    USUM_BATTLE_PLAYER_DISPLAY_HP_BASE,
    USUM_BATTLE_PLAYER_MAX_HP_BASE,
    USUM_BATTLE_PLAYER_STRIDE,
    USUM_BATTLE_STATE_ACTIVE_VALUE,
    USUM_BATTLE_STATE_ADDRESS,
    USUM_BATTLE_STATE_TERMINAL_VALUE,
    USUM_KAHUNA_ZCRYSTAL_KEY_IDS,
    USUM_ITEMS_BASE_REFERENCE,
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
    USUMLiveWriter,
    count_usum_kahuna_badges,
    parse_pk7_boxed,
    parse_pk7_party,
    parse_usum_zcrystal_keys,
)
from app.realtime.usum_adapter import USUMRealTimeAdapter
from app.ui import RoleRunManager
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


def test_usum_inspector_reads_personal_stats_through_the_profile_contract() -> None:
    profile = ORASTMProfile(
        source=Path("effective.3ds"), tms={}, compatibility={}, source_kind="rom",
        personal_stats={115: ORASPersonalStats((105, 95, 80, 90, 40, 80), 2)},
    )
    manager = SimpleNamespace(
        save_engine=SimpleNamespace(key="usum"),
        _get_usum_rom_tm_profile=lambda prompt=False: profile,
    )
    pokemon = SimpleNamespace(species_id=115, form=0, base_stats={})

    assert RoleRunManager._team_pc_base_stats(manager, pokemon) == {
        "hp": 105, "attack": 95, "defense": 80,
        "sp_attack": 40, "sp_defense": 80, "speed": 90,
    }


def test_usum_party_heal_crosses_the_gen7_live_dispatch_gate() -> None:
    change = PendingPartyHeal(
        pokemon_slot=1, pokemon="Kangaskhan", species="Kangaskhan",
        pokemon_identity="115:1:2:3",
    )
    scheduled: list[bool] = []
    manager = SimpleNamespace(
        run=SimpleNamespace(pending_changes=[change]),
        _oras_live_auto_apply_available=lambda: True,
        _active_azahar_realtime_key=lambda: "usum",
        _oras_live_auto_apply_ids=set(),
        _schedule_oras_live_auto_apply=lambda: scheduled.append(True),
    )

    RoleRunManager._request_oras_live_auto_apply(manager, [change])

    assert manager._oras_live_auto_apply_ids == {id(change)}
    assert scheduled == [True]


def test_usum_floating_bar_exposes_live_heal_and_menu_actions() -> None:
    manager = SimpleNamespace(_active_azahar_realtime_key=lambda: "usum")
    assert RoleRunManager._floating_live_actions_available(manager) is True


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


def test_usum_restart_accepts_two_managed_replacements_only_with_both_witnesses() -> None:
    reader = USUMLiveReader(DATA_DIR / "moves.json", stable_delay=0)
    expected = [_mon(slot) for slot in range(1, 7)]
    live = [_mon(slot) for slot in range(1, 5)]
    incoming_a = _mon(5)
    incoming_a.species_id = 731
    incoming_a.pid = 0xA001
    incoming_b = _mon(6)
    incoming_b.species_id = 165
    incoming_b.pid = 0xA002
    live.extend((incoming_a, incoming_b))
    current = _game(*expected)

    assert reader._party_continuity_proof(live, current) is None

    reader.set_resume_identity_witnesses((
        f"{incoming_a.species_id}:{incoming_a.pid}:{incoming_a.tid}:{incoming_a.sid}",
        f"{incoming_b.species_id}:{incoming_b.pid}:{incoming_b.tid}:{incoming_b.sid}",
    ))

    assert reader._party_continuity_proof(live, current) == "multiple-managed-replacements"


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


def _training_pk7(*, party: bool) -> bytes:
    size = PK7_PARTY_SIZE if party else PK7_STORED_SIZE
    data = bytearray(size)
    struct.pack_into("<I", data, 0, 0x12345678)
    struct.pack_into("<H", data, 4, 0)
    struct.pack_into("<H", data, 8, 25)
    struct.pack_into("<I", data, 0x18, 0xAABBCCDD)
    data[0x1C] = 3  # Firme: +Ataque, -Ataque Especial.
    data[0x1E:0x24] = bytes((1, 2, 3, 4, 5, 6))
    iv_binary = (7, 8, 9, 10, 11, 12)
    iv32 = sum(value << (index * 5) for index, value in enumerate(iv_binary))
    struct.pack_into("<I", data, 0x74, iv32)
    struct.pack_into("<H", data, 6, sum(struct.unpack_from("<112H", data, 8)) & 0xFFFF)
    if party:
        struct.pack_into("<I", data, 0xE8, 4)
        data[0xEC] = 25
        struct.pack_into("<H", data, 0xF0, 90)
        # Orden PartyData: HP, Atk, Def, Spe, SpA, SpD.
        struct.pack_into("<6H", data, 0xF2, 100, 101, 102, 103, 104, 105)
        return encrypt_pk6(bytes(data))
    return encrypt_pk6_stored(bytes(data))


def test_usum_pk7_training_fields_use_canonical_ui_order() -> None:
    mon = parse_pk7_party(_training_pk7(party=True), 1, {})
    assert mon is not None
    assert mon.nature == "Firme"
    assert mon.nature_increased == "attack"
    assert mon.nature_decreased == "sp_attack"
    assert mon.status_condition == 4
    assert mon.stats == {
        "hp": 100, "attack": 101, "defense": 102,
        "sp_attack": 104, "sp_defense": 105, "speed": 103,
    }
    assert mon.ivs == {
        "hp": 7, "attack": 8, "defense": 9,
        "sp_attack": 11, "sp_defense": 12, "speed": 10,
    }
    assert mon.evs == {
        "hp": 1, "attack": 2, "defense": 3,
        "sp_attack": 5, "sp_defense": 6, "speed": 4,
    }


def test_usum_role_ev_writer_uses_canonical_order_and_exact_precondition() -> None:
    from app.usum_live import _plain_pk7_with_state

    plain = bytearray(_plain_pk7_with_state(_training_pk7(party=True))[0])
    USUMLiveWriter._set_evs(
        plain,
        expected=(1, 2, 3, 5, 6, 4),
        desired=(0, 252, 0, 0, 0, 252),
    )

    assert tuple(plain[0x1E:0x24]) == (0, 252, 0, 252, 0, 0)
    with pytest.raises(USUMLiveError, match="cambiaron dentro del juego"):
        USUMLiveWriter._set_evs(
            plain,
            expected=(1, 2, 3, 5, 6, 4),
            desired=(252, 0, 252, 0, 0, 0),
        )


def test_usum_role_ev_writer_recalculates_party_stats_and_preserves_missing_hp() -> None:
    from app.usum_live import _plain_pk7_with_state

    personal = ORASPersonalStats(
        # Orden Personal Gen 7: HP, Atk, Def, Spe, SpA, SpD.
        base_stats=(35, 55, 40, 90, 50, 50),
        exp_growth=0,
    )
    writer = USUMLiveWriter(_reader(), personal_for=lambda _species, _form: personal)
    stored = bytearray(PK7_STORED_SIZE)
    struct.pack_into("<I", stored, 0, 0x12345678)
    struct.pack_into("<H", stored, 8, 25)
    stored[0x1C] = 3  # Firme: +Atk, -SpA.
    struct.pack_into("<I", stored, 0x74, sum(20 << (5 * index) for index in range(6)))
    writer._refresh_checksum(stored)
    full = bytes(stored) + writer._party_extension(stored, personal)
    plain = bytearray(_plain_pk7_with_state(full)[0])
    plain[0xEC] = 50
    old_stats = writer._calculate_party_stats(
        personal.base_stats, (20, 20, 20, 20, 20, 20), (0, 0, 0, 0, 0, 0), 50, 3,
    )
    struct.pack_into("<H", plain, 0xF0, old_stats[0])
    struct.pack_into("<6H", plain, 0xF2, *old_stats)
    before = parse_pk7_party(bytes(plain), 1, {})
    assert before is not None
    struct.pack_into("<H", plain, 0xF0, before.max_hp - 3)

    writer._set_party_evs_and_stats(
        plain,
        pokemon=before,
        expected=(0, 0, 0, 0, 0, 0),
        desired=(252, 252, 0, 0, 0, 0),
    )
    writer._refresh_checksum(plain)
    after = parse_pk7_party(bytes(plain), 1, {})
    assert after is not None
    assert after.evs == {
        "hp": 252, "attack": 252, "defense": 0,
        "sp_attack": 0, "sp_defense": 0, "speed": 0,
    }
    assert after.max_hp > before.max_hp
    assert after.stats["attack"] > before.stats["attack"]
    assert after.current_hp == after.max_hp - 3
    assert after.stats["defense"] == before.stats["defense"]


def test_usum_same_evs_can_repair_alpha122_stale_party_stats() -> None:
    from app.usum_live import _plain_pk7_with_state

    personal = ORASPersonalStats((35, 55, 40, 90, 50, 50), 0)
    writer = USUMLiveWriter(_reader(), personal_for=lambda _species, _form: personal)
    stored = bytearray(PK7_STORED_SIZE)
    struct.pack_into("<I", stored, 0, 0x12345678)
    struct.pack_into("<H", stored, 8, 25)
    stored[0x1E:0x24] = bytes((252, 252, 0, 0, 0, 0))
    struct.pack_into("<I", stored, 0x74, sum(20 << (5 * index) for index in range(6)))
    writer._refresh_checksum(stored)
    full = bytearray(bytes(stored) + writer._party_extension(stored, personal))
    struct.pack_into("<6H", full, 0xF2, 1, 1, 1, 1, 1, 1)  # estado dejado por alpha.122
    stale = parse_pk7_party(bytes(full), 1, {})
    assert stale is not None

    writer._set_party_evs_and_stats(
        full,
        pokemon=stale,
        expected=(252, 252, 0, 0, 0, 0),
        desired=(252, 252, 0, 0, 0, 0),
    )
    repaired = parse_pk7_party(bytes(full), 1, {})
    assert repaired is not None
    assert repaired.max_hp > 1
    assert repaired.stats["attack"] > 1


def test_usum_box_to_party_prepares_role_evs_for_the_followup_transaction() -> None:
    current = _mon(1)
    current.role, current.role_symbol = "Líbero", "●"
    incoming = _mon(1)
    incoming.box, incoming.box_slot, incoming.pid = 1, 3, 99
    incoming.role, incoming.role_symbol = "Mago", "■"
    manager = SimpleNamespace(
        save_engine=SimpleNamespace(key="usum"), current_game=_game(current),
        run=SimpleNamespace(pending_changes=[]),
        _oras_live_auto_apply_available=lambda: True,
        _active_azahar_realtime_key=lambda: "usum",
        _pc_effective_role=lambda _pokemon: ("Mago", "■"),
        _incoming_snapshot_for_role=lambda _pokemon, role, _slots: {"role": role},
        _pending_pc_role_change=lambda _pokemon: None,
        _projected_party=lambda: [current],
        _effective_role=lambda pokemon: (pokemon.role, pokemon.role_symbol),
        _pokemon_identity=lambda pokemon: f"{pokemon.species_id}:{pokemon.pid}:{pokemon.tid}:{pokemon.sid}",
        _pc_role_witnesses=lambda _pokemon: (),
        _request_oras_live_auto_apply_since=lambda _ids: None,
        _sync_live_layout=lambda: None,
    )

    RoleRunManager._prepare_pc_team_change(manager, incoming, replacement=None)

    change = manager.run.pending_changes[0]
    assert change.incoming_role == "Asesino"
    assert change.incoming_snapshot["evs"] == {
        "hp": 0, "attack": 252, "defense": 0,
        "sp_attack": 0, "sp_defense": 0, "speed": 252,
    }


def test_usum_boxed_pk7_exposes_nature_ivs_and_evs_without_inventing_stats() -> None:
    mon = parse_pk7_boxed(_training_pk7(party=False), 2, 3, {})
    assert mon is not None
    assert mon.nature == "Firme"
    assert mon.ivs["speed"] == 10
    assert mon.evs["sp_attack"] == 5
    assert mon.stats == {}


def test_usum_boxed_stats_require_and_use_effective_personal_data() -> None:
    raw = _training_pk7(party=False)
    boxed = parse_pk7_boxed(raw, 1, 1, {})
    assert boxed is not None
    writer = USUMLiveWriter(
        _reader(),
        personal_for=lambda species, form: ORASPersonalStats(
            # Orden Personal Gen 7: HP, Atk, Def, Spe, SpA, SpD.
            base_stats=(35, 55, 40, 90, 50, 50),
            exp_growth=0,
        ),
    )
    enriched = writer._enrich_boxed_training_data(
        raw, {(1, 1): boxed}, box_slot_count=1,
    )[(1, 1)]
    assert enriched is not None
    assert enriched.base_stats == {
        "hp": 35, "attack": 55, "defense": 40,
        "sp_attack": 50, "sp_defense": 50, "speed": 90,
    }
    assert set(enriched.stats) == {
        "hp", "attack", "defense", "sp_attack", "sp_defense", "speed",
    }


def test_usum_party_heal_restores_hp_status_and_pp_without_touching_training() -> None:
    encrypted = _training_pk7(party=True)
    # El fixture se descifra por la misma frontera productiva para preparar
    # PP/PP Ups agotados; IV, EV y stats quedan como testigos colaterales.
    from app.usum_live import _plain_pk7_with_state
    plain = bytearray(_plain_pk7_with_state(encrypted)[0])
    struct.pack_into("<H", plain, 0x5A, 33)
    plain[0x62] = 1
    plain[0x66] = 2
    struct.pack_into("<H", plain, 6, sum(struct.unpack_from("<112H", plain, 8)) & 0xFFFF)
    encrypted = encrypt_pk6(bytes(plain))
    writer = USUMLiveWriter(_reader(), move_pp_for=lambda move_id: 35 if move_id == 33 else 0)

    stored, stats = writer._healed_party_bytes(encrypted)
    healed = parse_pk7_party(stored + stats + (b"\0" * (PK7_PARTY_SIZE - PK7_STORED_SIZE - len(stats))), 1, {})
    assert healed is not None
    assert healed.current_hp == healed.max_hp == 100
    assert healed.status_condition == 0
    healed_plain = _plain_pk7_with_state(stored + stats + (b"\0" * (PK7_PARTY_SIZE - PK7_STORED_SIZE - len(stats))))[0]
    assert healed_plain[0x62] == 49  # 35 * (5 + 2 PP Ups) // 5
    assert healed.ivs == {"hp": 7, "attack": 8, "defense": 9, "sp_attack": 11, "sp_defense": 12, "speed": 10}
    assert healed.evs == {"hp": 1, "attack": 2, "defense": 3, "sp_attack": 5, "sp_defense": 6, "speed": 4}


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
            return struct.pack(
                "<I",
                USUM_BATTLE_STATE_ACTIVE_VALUE if self.active else USUM_BATTLE_STATE_TERMINAL_VALUE,
            )
        if int(address) == USUM_BATTLE_PHASE_ADDRESS:
            return struct.pack(
                "<I",
                USUM_BATTLE_PHASE_ACTIVE_VALUE if self.active else USUM_BATTLE_PHASE_TERMINAL_VALUE,
            )
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
    assert APP_VERSION == "0.2.6-alpha.46"
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
    assert "party 2:sin fila única; row 2=81/37/35 vs PK7 80" in probe.reason


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


def test_alpha64_kahuna_trace_records_only_source_or_progress_transitions(
    isolated_role_run_log_dir: Path,
) -> None:
    adapter = USUMRealTimeAdapter(_reader())
    raw = SimpleNamespace(
        process=AzaharProcess(11, USUM_ULTRA_SUN_TITLE_ID, "momiji"),
        party_base=0x33F7FA44,
    )

    adapter._trace_kahuna_progress(
        raw=raw, badges=0, source="main · Z-Crystals (fallback)", sequence=1,
    )
    adapter._trace_kahuna_progress(
        raw=raw, badges=0, source="main · Z-Crystals (fallback)", sequence=2,
    )
    adapter._trace_kahuna_progress(
        raw=raw, badges=1,
        source="Z-Crystals vivos · mochila calibrada estructuralmente", sequence=3,
    )

    path = isolated_role_run_log_dir / "usum_kahuna_progress_trace_latest.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert rows[0]["kahunas"] == 0 and rows[0]["source_live"] is False
    assert rows[1]["kahunas"] == 1 and rows[1]["source_live"] is True
    assert rows[1]["sequence"] == 3


def test_alpha64_usum_inventory_reports_unconfirmed_immediate_rollback() -> None:
    """USUM comparte el writer Gen 7 y debe verificar también su restauración."""
    original = _items_block()
    desired = bytearray(original)
    record_offset = 0xB48
    original_word = 50 | (1 << 10)
    desired_word = 50 | (999 << 10)
    original = bytearray(original)
    struct.pack_into("<I", original, record_offset, original_word)
    struct.pack_into("<I", desired, record_offset, desired_word)

    guest_base = 0x33008000
    host_base = 0x000001A000008000
    live = bytearray(original)
    process = AzaharProcess(191, USUM_ULTRA_SUN_TITLE_ID, "momiji")

    class Client:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def process_list(self): return [process]
        def set_process(self, process_id: int): assert int(process_id) == process.process_id
        def read_memory(self, address: int, size: int) -> bytes:
            offset = int(address) - guest_base
            if offset < 0 or offset + int(size) > len(live):
                return b"\0" * int(size)
            return bytes(live[offset:offset + int(size)])

    class Host:
        def __init__(self) -> None:
            self.write_count = 0
        def find_party_targets(self, **_kwargs):
            return [SimpleNamespace(pid=999, exe_name="azahar.exe")]
        def write(self, _handle, address: int, data: bytes) -> None:
            self.write_count += 1
            offset = int(address) - host_base
            if self.write_count == 1:
                corrupted = bytearray(data)
                corrupted[0] ^= 0x01
                live[offset:offset + len(corrupted)] = corrupted
            # El segundo write simula un rollback ignorado por el proceso host.
        def read(self, _handle, address: int, size: int) -> bytes:
            offset = int(address) - host_base
            return bytes(live[offset:offset + int(size)])
        def close_process(self, _handle) -> None:
            return None

    client = Client()
    reader = _reader(client)
    reader._find_usum_process = lambda _processes: process
    reader._locate_party_base = lambda _client, _process, _current: 0x33F7FA44
    reader._build_game = lambda _capture, current, _process, _base: current
    writer = USUMLiveWriter(reader)
    host = Host()
    writer.host_memory_factory = lambda: host
    writer._capture_stable_party = lambda _client, _base: ([b"party"], 1)
    writer._resolve_live_utility_block = lambda **_kwargs: (
        object(), host_base, guest_base, bytes(original),
    )
    change = PendingInventoryChange(
        "rare-candy", "Caramelo Raro", 999,
        save_inventory_witness=bytes(original), desired_inventory_witness=bytes(desired),
    )

    with pytest.raises(USUMLiveError, match="La utilidad USUM falló.*no se pudo confirmar.*rollback"):
        writer.apply(_game(_mon(1)), [change])

    live_word = struct.unpack_from("<I", live, record_offset)[0]
    assert live_word not in {original_word, desired_word}
    assert host.write_count == 2


def test_alpha65_kahuna_reader_consumes_guest_anchor_proven_by_tm_reference(
    tmp_path: Path,
) -> None:
    """La prueba ItemsOffset no puede perderse por consultar otra caché."""
    saved = _items_block((807,))
    live = _items_block((807, USUM_KAHUNA_ZCRYSTAL_KEY_IDS[0]))
    save_path = tmp_path / "main"
    save_path.write_bytes(saved)
    process = AzaharProcess(211, USUM_ULTRA_SUN_TITLE_ID, "momiji")
    party_base = 0x33F7FA44
    session = (process.title_id, process.process_id, process.name, party_base)

    class Client:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def process_list(self): return [process]
        def set_process(self, process_id: int): assert int(process_id) == process.process_id
        def read_memory(self, address: int, size: int) -> bytes:
            assert int(address) == USUM_ITEMS_BASE_REFERENCE
            return bytes(live[:int(size)])

    writer = USUMLiveWriter(_reader(Client()))
    proof_calls = 0

    def prove_items_from_reference(_current, _save_path):
        nonlocal proof_calls
        proof_calls += 1
        # Es exactamente el contrato que read_tm_inventory_for_game publica:
        # ancla guest estable, no _utility_block_cache host+guest.
        writer._tm_inventory_session = session
        writer._tm_guest_inventory_anchor = (
            session, USUM_ITEMS_BASE_REFERENCE, bytes(live),
        )
        return {}, process, 1

    writer.read_tm_inventory_for_game = prove_items_from_reference

    badges = writer.read_kahuna_badges_for_game(
        _game(_mon(1)), save_path, party_base=party_base, allow_full_scan=True,
    )

    assert badges == 1
    assert writer.last_badge_source == "Z-Crystals vivos · referencia ItemsOffset revalidada"

    # La siguiente muestra relee el ancla estable; no repite la calibración ni
    # vuelve al main stale.
    assert writer.read_kahuna_badges_for_game(
        _game(_mon(1)), save_path, party_base=party_base, allow_full_scan=True,
    ) == 1
    assert proof_calls == 1


def test_alpha65_adapter_publishes_kahuna_value_and_live_source(
    isolated_role_run_log_dir: Path,
) -> None:
    current = _game(_mon(1))
    process = AzaharProcess(212, USUM_ULTRA_SUN_TITLE_ID, "momiji")
    raw = SimpleNamespace(
        game=current, process=process, attempts=1, party_base=0x33F7FA44,
        memory_blocks=(), runtime_party_region=b"",
    )
    reader = _reader()
    reader.read_monitor = lambda _current, memory_blocks=(): raw
    reader.read_battle_probe = lambda _current: SimpleNamespace(
        state="none", validated=True, health_game=None, hp_pairs=(),
    )
    adapter = USUMRealTimeAdapter(reader)

    def read_badges(_current, _save_path, *, party_base, allow_full_scan):
        assert party_base == raw.party_base
        assert allow_full_scan is True
        adapter.writer._last_badge_source = (
            "Z-Crystals vivos · referencia ItemsOffset revalidada"
        )
        return 1

    adapter.writer.read_kahuna_badges_for_game = read_badges

    snapshot = adapter.capture_monitor(current, save_path=Path("main"), sequence=17)

    assert snapshot.badges == 1
    assert snapshot.badge_source == "Z-Crystals vivos · referencia ItemsOffset revalidada"
    trace = isolated_role_run_log_dir / "usum_kahuna_progress_trace_latest.jsonl"
    payload = json.loads(trace.read_text(encoding="utf-8").splitlines()[-1])
    assert payload["kahunas"] == 1 and payload["source_live"] is True


def test_usum_reconcile_publishes_the_complete_live_pk7_matrix() -> None:
    """USUM no debe degradar naturaleza/IV/EV a una diferencia contra el save."""
    assert RoleRunManager._pc_reconcile_publishes_full_matrix("usum") is True
    assert RoleRunManager._pc_reconcile_publishes_full_matrix("bdsp") is True
    assert RoleRunManager._pc_reconcile_publishes_full_matrix("oras") is False


def test_usum_first_valid_snapshot_replaces_save_pc_cache_with_live_matrix() -> None:
    """La activación previa del monitor no puede impedir cargar el PK7 completo."""
    scheduled: list[tuple[int, object]] = []
    manager = SimpleNamespace(
        _oras_live_active=True,
        active_page="team",
        _team_pc_pc_loading=False,
        _pc_selector_live_refresh_in_progress=False,
        _team_pc_cached_data=lambda: SimpleNamespace(raw={"source": "save"}),
        _active_azahar_realtime_key=lambda: "usum",
        _start_team_pc_load=object(),
        after=lambda delay, callback: scheduled.append((delay, callback)),
    )

    assert RoleRunManager._ensure_live_pc_matrix_loaded(manager) is True
    assert scheduled == [(20, manager._start_team_pc_load)]

    manager._team_pc_cached_data = lambda: SimpleNamespace(raw={"live_matrix": True})
    assert RoleRunManager._ensure_live_pc_matrix_loaded(manager) is False
    assert len(scheduled) == 1


def test_usum_pc_load_warms_personal_before_calculating_boxed_stats() -> None:
    """PK7 de caja necesita Personal cargado antes del worker vivo."""
    order: list[str] = []
    manager = SimpleNamespace(
        _team_pc_pc_loading=False,
        current_save=object(),
        current_game=object(),
        project=object(),
        _pc_selector_live_refresh_in_progress=False,
        _show_busy_indicator=lambda *_args: None,
        _set_operation_status=lambda *_args: None,
        _active_azahar_realtime_key=lambda: "usum",
        _oras_live_active=True,
        _get_usum_rom_tm_profile=lambda **_kwargs: order.append("personal"),
        _open_pc_selector_from_live_matrix=lambda **_kwargs: order.append("pc"),
        _finish_team_pc_load=object(),
        _fail_team_pc_load=object(),
    )

    RoleRunManager._start_team_pc_load(manager)

    assert order == ["personal", "pc"]
