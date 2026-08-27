from __future__ import annotations

import struct
import hashlib
from types import SimpleNamespace

import pytest

from app.b2w2_live import (
    B2W2LiveError,
    B2W2PCRead,
    B2W2BattleRead,
    B2W2MelonDSReader,
    B2W2PartyRead,
    B2W2Pokemon,
    DS_RAM_BASE,
    PARTY_COUNT,
    PC_BASE,
    PC_BOX_COUNT,
    PC_BOX_DATA_SIZE,
    PC_BOX_STRIDE,
    PC_MATRIX_SIZE,
    PK5_PARTY_SIZE,
    PK5_STORED_SIZE,
    _PERMUTATIONS,
    _crypt,
    empty_pk5_party,
    parse_pk5_boxed,
    parse_pk5_party,
)
from app.models import PendingPartyHeal, PendingTeamChange
from app.realtime.b2w2_adapter import B2W2RealTimeAdapter
from app.save_engine_client import SaveGameData, SavePokemon
from app.ui import RoleRunManager


def _pk5_fixture(
    *, pid: int = 0x89E50000, current_hp: int = 13, max_hp: int = 26,
    runtime_status: int = 0,
) -> bytes:
    canonical = bytearray(136)
    struct.pack_into("<I", canonical, 0, pid)
    struct.pack_into("<H", canonical, 0x08, 498)
    struct.pack_into("<HH", canonical, 0x0C, 1234, 5678)
    canonical[0x15] = 66
    canonical[0x16] = 1
    canonical[0x18:0x1E] = bytes((4, 8, 12, 24, 20, 16))
    struct.pack_into("<4H", canonical, 0x28, 33, 39, 52, 0)
    canonical[0x30:0x34] = bytes((35, 30, 25, 0))
    canonical[0x34:0x38] = bytes((1, 0, 2, 0))
    ivs = (31, 30, 29, 28, 27, 26)
    iv32 = sum(value << shift for value, shift in zip(ivs, (0, 5, 10, 20, 25, 15)))
    struct.pack_into("<I", canonical, 0x38, iv32)
    canonical[0x41] = 3
    nickname = "Tepig".encode("utf-16-le") + b"\xff\xff"
    canonical[0x48:0x48 + len(nickname)] = nickname
    checksum = sum(struct.unpack("<64H", canonical[8:136])) & 0xFFFF
    struct.pack_into("<H", canonical, 6, checksum)
    blocks = [
        bytes(canonical[8 + index * 32:8 + (index + 1) * 32])
        for index in range(4)
    ]
    order = _PERMUTATIONS[((pid >> 13) & 31) % 24]
    stored_blocks = [b""] * 4
    for canonical_index, stored_index in enumerate(order):
        stored_blocks[stored_index] = blocks[canonical_index]
    shuffled = b"".join(stored_blocks)
    extension = bytearray(PK5_PARTY_SIZE - 136)
    struct.pack_into("<I", extension, 0, runtime_status)
    extension[4] = 7
    struct.pack_into("<HH", extension, 6, current_hp, max_hp)
    struct.pack_into("<5H", extension, 10, 14, 12, 11, 13, 10)
    return bytes(canonical[:8]) + _crypt(shuffled, checksum) + _crypt(bytes(extension), pid)


def _current_game() -> SaveGameData:
    pokemon = SavePokemon(
        slot=0, species_id=498, species="Tepig", nickname="Tepig", level=6,
        held_item="Ninguno", ability="Mar Llamas", moves=["Placaje"],
        move_ids=[33], is_egg=False,
        markings=[True, False, False, False, False, False],
        role="Líbero", role_symbol="•", pid=0x89E50000, tid=1234, sid=5678,
    )
    return SaveGameData("B2W2", "SAV5B2W2", 5, "Tester", [pokemon], {})


def test_parse_pk5_party_decodes_observed_shape() -> None:
    pokemon = parse_pk5_party(_pk5_fixture(), 0)
    assert (pokemon.species_id, pokemon.nickname, pokemon.level) == (498, "Tepig", 7)
    assert (pokemon.current_hp, pokemon.max_hp) == (13, 26)
    assert pokemon.move_ids == (33, 39, 52, 0)
    assert pokemon.move_pp == (35, 30, 25, 0)
    assert pokemon.move_pp_ups == (1, 0, 2, 0)
    assert pokemon.markings == (True, False, False, False, False, False)
    assert pokemon.nature_id == 3
    assert pokemon.stats == (26, 14, 12, 13, 10, 11)
    assert pokemon.ivs == (31, 30, 29, 28, 27, 26)
    assert pokemon.evs == (4, 8, 12, 20, 16, 24)
    assert (pokemon.tid, pokemon.sid) == (1234, 5678)


def test_parse_pk5_party_unshuffles_non_involutive_pid_layout() -> None:
    """Regresión: los layouts cíclicos 0,3,1,2 no usan su propia inversa."""
    pokemon = parse_pk5_party(_pk5_fixture(pid=3 << 13), 2)
    assert (pokemon.species_id, pokemon.nickname) == (498, "Tepig")
    assert pokemon.move_ids == (33, 39, 52, 0)
    assert pokemon.move_pp_ups == (1, 0, 2, 0)


def _pc_matrix_fixture() -> bytes:
    empty = bytes(8) + _crypt(bytes(128), 0)
    matrix = bytearray(PC_MATRIX_SIZE)
    for box in range(PC_BOX_COUNT):
        start = box * PC_BOX_STRIDE
        for slot in range(30):
            offset = start + slot * PK5_STORED_SIZE
            matrix[offset:offset + PK5_STORED_SIZE] = empty
        matrix[start + PC_BOX_DATA_SIZE:start + PC_BOX_STRIDE] = bytes([box + 1]) * 16
    matrix[0:PK5_STORED_SIZE] = _pk5_fixture(pid=3 << 13)[:PK5_STORED_SIZE]
    return bytes(matrix)


def test_pc_matrix_keeps_0x1000_box_stride_and_validates_all_720_slots() -> None:
    empty, pokemon = B2W2MelonDSReader.parse_pc_matrix(_pc_matrix_fixture())
    assert empty == 719
    assert [(p.box, p.slot, p.species_id, p.nickname) for p in pokemon] == [
        (1, 1, 498, "Tepig"),
    ]


def test_pc_matrix_rejects_a_corrupted_empty_slot() -> None:
    matrix = bytearray(_pc_matrix_fixture())
    matrix[PC_BOX_STRIDE + PK5_STORED_SIZE + 10] ^= 0x80
    with pytest.raises(B2W2LiveError, match="Checksum"):
        B2W2MelonDSReader.parse_pc_matrix(bytes(matrix))


def test_b2w2_runtime_status_one_is_the_physically_observed_paralysis() -> None:
    assert parse_pk5_party(_pk5_fixture(runtime_status=1), 0).status_condition == 64


@pytest.mark.parametrize(
    "payload",
    [
        lambda data: data[:-1],
        lambda data: data[:6] + b"\x00\x00" + data[8:],
        lambda data: _pk5_fixture(current_hp=27, max_hp=26),
    ],
)
def test_parse_pk5_party_rejects_incoherent_blocks(payload) -> None:
    with pytest.raises(B2W2LiveError):
        parse_pk5_party(payload(_pk5_fixture()), 0)


def test_reader_uses_two_stable_nominal_reads_without_refuted_mirror() -> None:
    allocation = 0x1B26C190000
    count_address = allocation + (PARTY_COUNT - DS_RAM_BASE)
    fixture = _pk5_fixture()
    reads = []

    def read(address: int, size: int) -> bytes:
        reads.append((address, size))
        if address == count_address:
            return b"\x01"
        if address == count_address + 4:
            return fixture
        raise OSError("No existe una segunda dirección de party en la regresión.")

    candidate = B2W2MelonDSReader._capture_nominal_candidate(read, allocation)
    assert candidate is not None
    count, raw, pokemon = candidate
    assert count == 1 and raw == fixture
    assert (pokemon[0].species_id, pokemon[0].current_hp) == (498, 13)
    assert reads == [
        (count_address, 1), (count_address + 4, PK5_PARTY_SIZE),
        (count_address, 1), (count_address + 4, PK5_PARTY_SIZE),
    ]


def _party_read(
    *, identity=(0x89E50000, 1234, 5678),
    markings=(True, False, False, False, False, False),
) -> B2W2PartyRead:
    live = B2W2Pokemon(
        slot=0, pid=identity[0], tid=identity[1], sid=identity[2],
        species_id=498, form=0, nickname="Tepig", level=7,
        held_item_id=0, ability_id=66, move_ids=(33, 39, 52, 0),
        move_pp=(35, 30, 25, 0), move_pp_ups=(1, 0, 2, 0),
        markings=markings,
        nature_id=3, is_egg=False, status_condition=0,
        stats=(26, 14, 12, 13, 10, 11),
        ivs=(31, 30, 29, 28, 27, 26), evs=(4, 8, 12, 20, 16, 24),
        current_hp=13, max_hp=26,
    )
    return B2W2PartyRead(
        14896, "melonDS.exe", 0x1B26C190000, 1, b"fixture", (live,),
    )


def test_adapter_publishes_hp_and_preserves_role_by_strong_identity() -> None:
    reader = type("Reader", (), {"read_party": lambda self: _party_read()})()
    snapshot = B2W2RealTimeAdapter(reader=reader).capture_full(
        _current_game(), save_path=None, sequence=9,
    )
    result = snapshot.game.party[0]
    assert (result.current_hp, result.max_hp, result.level) == (13, 26, 7)
    assert (result.role, result.role_symbol, result.markings[0]) == ("Líbero", "●", True)
    assert result.nature == "Firme"
    assert result.stats["speed"] == 11
    assert result.ivs["sp_attack"] == 28
    assert result.evs["sp_defense"] == 16
    assert snapshot.process.name == "melonDS.exe"
    assert snapshot.diagnostic("party").level.value == "ok"
    assert snapshot.diagnostic("battle").level.value == "warning"


def test_adapter_rejects_ram_without_saved_identity_anchor() -> None:
    reader = type("Reader", (), {
        "read_party": lambda self: _party_read(identity=(0x11111111, 9, 8)),
    })()
    with pytest.raises(B2W2LiveError, match="identidad fuerte"):
        B2W2RealTimeAdapter(reader=reader).capture_full(
            _current_game(), save_path=None,
        )


def test_adapter_keeps_persisted_role_until_b2w2_markings_can_be_written() -> None:
    reader = type("Reader", (), {
        "read_party": lambda self: _party_read(markings=(False,) * 6),
    })()
    result = B2W2RealTimeAdapter(reader=reader).capture_full(
        _current_game(), save_path=None,
    ).game.party[0]
    assert result.role == "Líbero"
    assert result.markings[0] is True


def test_adapter_publishes_complete_read_only_pc_matrix() -> None:
    matrix = _pc_matrix_fixture()
    empty, pokemon = B2W2MelonDSReader.parse_pc_matrix(matrix)

    class Reader:
        def read_party(self):
            return _party_read()

        def read_pc(self, party):
            assert party.count == 1
            return B2W2PCRead(
                party.process_id, party.process_name, party.allocation_base,
                PC_BASE, matrix, empty, pokemon,
            )

    process, base, slots = B2W2RealTimeAdapter(reader=Reader()).read_pc(
        [], box_count=24, box_slot_count=30,
    )
    assert process.count == 1
    assert base == PC_BASE
    tepig = slots[(1, 1)]
    assert (tepig.species_id, tepig.nickname, tepig.box, tepig.box_slot) == (
        498, "Tepig", 1, 1,
    )
    assert tepig.ivs["sp_attack"] == 28
    assert tepig.evs["speed"] == 24
    assert tepig.base_stats["hp"] == 65


def test_pc_move_plan_moves_one_pk5_and_preserves_every_other_byte() -> None:
    matrix = _pc_matrix_fixture()
    plan = B2W2MelonDSReader.prepare_pc_move(matrix, 1, 1, 1, 2)
    assert plan.pokemon.species_id == 498
    assert parse_pk5_boxed(
        plan.expected[:PK5_STORED_SIZE], 1, 1,
    ) is None
    moved = parse_pk5_boxed(
        plan.expected[PK5_STORED_SIZE:2 * PK5_STORED_SIZE], 1, 2,
    )
    assert moved is not None and moved.pid == plan.pokemon.pid
    assert plan.expected[2 * PK5_STORED_SIZE:] == matrix[2 * PK5_STORED_SIZE:]


def test_empty_party_pk5_matches_the_physically_observed_freed_tail() -> None:
    empty = empty_pk5_party()
    assert len(empty) == PK5_PARTY_SIZE
    assert empty[:8] == bytes(8)
    assert hashlib.sha256(empty).hexdigest() == (
        "0a62191da8ce98e0dc9e3e353fa5525eca74e67095bdd752348b90b26a3a2856"
    )


def test_adapter_applies_only_validated_b2w2_pc_move() -> None:
    matrix = _pc_matrix_fixture()
    empty, pokemon = B2W2MelonDSReader.parse_pc_matrix(matrix)
    source = pokemon[0]

    class Reader:
        moved = None

        def read_party(self):
            return _party_read()

        def read_pc(self, party):
            return B2W2PCRead(
                party.process_id, party.process_name, party.allocation_base,
                PC_BASE, matrix, empty, pokemon,
            )

        prepare_pc_move = staticmethod(B2W2MelonDSReader.prepare_pc_move)

        def move_pc_slot(self, _party, *coordinates, expected_identity=None):
            self.moved = (coordinates, expected_identity)

    reader = Reader()
    change = PendingTeamChange(
        operation="move-box-slot", party_slot=0, box=1, box_slot=1,
        destination_box=1, destination_box_slot=2,
        incoming_snapshot={"pid": source.pid, "tid": source.tid, "sid": source.sid},
    )
    result = B2W2RealTimeAdapter(reader=reader).apply_changes(_current_game(), [change])
    assert reader.moved == ((1, 1, 1, 2), (source.pid, source.tid, source.sid))
    assert result.applied_count == 1


def test_b2w2_deposit_keeps_the_exact_live_slot_instead_of_reopening_the_save_pc() -> None:
    game = _current_game()
    pokemon = game.party[0]
    companion = SavePokemon(
        slot=1, species_id=506, species="Lillipup", nickname="Lillipup",
        level=4, held_item="Ninguno", ability="Recogida", moves=["Placaje"],
        move_ids=[33], is_egg=False, markings=[False] * 6,
        role="", role_symbol="", pid=99, tid=1234, sid=5678,
    )
    game.party.append(companion)
    requested = []
    manager = SimpleNamespace(
        current_game=game,
        save_engine=SimpleNamespace(key="b2w2"),
        run=SimpleNamespace(pending_changes=[]),
        _pc_cache=object(), active_page="team",
        _active_azahar_realtime_key=lambda: "b2w2",
        _active_azahar_realtime_label=lambda: "B2/W2",
        _oras_live_auto_apply_available=lambda: True,
        _projected_party=lambda: [pokemon, companion],
        _pokemon_snapshot=lambda mon: {"pid": mon.pid, "tid": mon.tid, "sid": mon.sid},
        _effective_role=lambda _mon: ("Líbero", "•"),
        _pokemon_identity=lambda mon: f"{mon.species_id}:{mon.pid}:{mon.tid}:{mon.sid}",
        _request_oras_live_auto_apply_since=lambda ids: requested.append(set(ids)),
        _update_top_status=lambda: None, _sync_live_layout=lambda: None,
        _smooth_render_page=lambda **_kwargs: None,
        _read_pc_data=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("B2/W2 no debe decidir el destino desde el save")
        ),
    )

    RoleRunManager.send_pokemon_to_pc(
        manager, pokemon, ask=False, destination=(1, 4),
    )

    change = manager.run.pending_changes[0]
    assert change.operation == "party-to-box"
    assert (change.box, change.box_slot) == (1, 4)
    assert requested == [set()]


def test_battle_parser_uses_immediate_copy_while_mirror_lags() -> None:
    pokemon = _party_read().pokemon
    mirror = struct.pack("<7H", 498, 26, 8, 0, 0, 66, 7) + bytes(6) + b"\x01"
    immediate = struct.pack("<7H", 498, 26, 0, 0, 0, 66, 7) + bytes(7)
    result = B2W2MelonDSReader.parse_battle_copies(mirror, immediate, pokemon)
    assert result == B2W2BattleRead(
        active=True, party_slot=0, current_hp=8, max_hp=26,
        mirror_hp=8, immediate_hp=0, converged=False, status_condition=64,
    )


def test_battle_parser_rejects_ambiguous_party_identity() -> None:
    pokemon = _party_read().pokemon[0]
    row = struct.pack("<7H", 498, 26, 13, 0, 0, 66, 7) + bytes(7)
    with pytest.raises(B2W2LiveError, match="forma única"):
        B2W2MelonDSReader.parse_battle_copies(row, row, (pokemon, pokemon))


def test_adapter_publishes_battle_health_from_validated_lane() -> None:
    class Reader:
        def read_party(self):
            return _party_read()

        def read_battle(self, _raw):
            return B2W2BattleRead(
                active=True, party_slot=0, current_hp=8, max_hp=26,
                mirror_hp=8, immediate_hp=0, converged=False,
                status_condition=64,
            )

    snapshot = B2W2RealTimeAdapter(reader=Reader()).capture_monitor(
        _current_game(), save_path=None,
    )
    assert snapshot.battle.state == "battle"
    assert snapshot.battle.health_game.party[0].current_hp == 8
    assert snapshot.battle.health_game.party[0].status_condition == 64
    assert snapshot.game.party[0].base_stats == {
        "hp": 65, "attack": 63, "defense": 45,
        "sp_attack": 45, "sp_defense": 45, "speed": 45,
    }
    assert "esperando animación" in snapshot.diagnostic("battle").message


def test_b2w2_team_pc_resize_never_creates_a_ghost_pending_change() -> None:
    statuses = []
    manager = SimpleNamespace(
        _active_azahar_realtime_key=lambda: "b2w2",
        _discard_b2w2_ghost_team_changes=lambda: 0,
        _team_pc_pending_incoming=(1, 2, "incoming"),
        _team_pc_pending_outgoing="outgoing",
        _projected_party=lambda: [object()] * 6,
        _set_operation_status=lambda *args, **kwargs: statuses.append((args, kwargs)),
    )
    result = RoleRunManager._team_pc_execute_change(
        manager, _current_game().party[0], None,
    )
    assert result is False
    assert manager._team_pc_pending_incoming is None
    assert manager._team_pc_pending_outgoing is None
    assert statuses[0][0][1] == "ESCRITURA B2/W2 AÚN CERRADA"


def test_b2w2_sync_discards_only_legacy_ghost_team_changes() -> None:
    ghost = PendingTeamChange(operation="swap-party-box", party_slot=0)
    survivor = PendingPartyHeal(
        pokemon_slot=0, pokemon="Tepig", species="Tepig", pokemon_identity="tepig",
    )
    saved = []
    manager = SimpleNamespace(
        project=object(), run=SimpleNamespace(pending_changes=[ghost, survivor]),
        project_service=SimpleNamespace(save=lambda project: saved.append(project)),
        _active_azahar_realtime_key=lambda: "b2w2",
    )
    removed = RoleRunManager._discard_b2w2_ghost_team_changes(manager)
    assert removed == 1
    assert manager.run.pending_changes == [survivor]
    assert saved == [manager.project]


def test_b2w2_pc_poll_tracks_external_moves_only_while_pc_is_visible() -> None:
    callbacks = []
    reads = []
    game = _current_game()
    manager = SimpleNamespace(
        active_page="pc", _oras_live_active=True, current_game=game,
        _session_generation=7, _oras_pc_reconcile_in_progress=False,
        _bdsp_pc_poll_after_id=None,
        _active_azahar_realtime_key=lambda: "b2w2",
        _floating_bar_is_visible=lambda: False,
        _record_bdsp_ui_event=lambda *_args, **_kwargs: None,
        _schedule_oras_external_pc_reconcile=lambda before, after, force=False: reads.append(
            (before, after, force)
        ),
        after=lambda _delay, callback: callbacks.append(callback) or "b2w2-poll",
        after_cancel=lambda _after_id: None,
    )
    manager._cancel_bdsp_pc_poll = lambda: RoleRunManager._cancel_bdsp_pc_poll(manager)
    manager._bdsp_pc_poll_is_active = lambda: RoleRunManager._bdsp_pc_poll_is_active(manager)
    manager._schedule_bdsp_pc_poll = lambda delay=2500: RoleRunManager._schedule_bdsp_pc_poll(
        manager, delay,
    )

    RoleRunManager._schedule_bdsp_pc_poll(manager, 200)
    assert manager._bdsp_pc_poll_after_id == "b2w2-poll"
    callbacks.pop(0)()
    assert reads == [(game, game, True)]

    manager.active_page = "team"
    RoleRunManager._schedule_bdsp_pc_poll(manager, 200)
    assert manager._bdsp_pc_poll_after_id is None


def _ui_double(*, current_game: SaveGameData):
    published = []
    scheduled = []
    toasts = []
    ui = SimpleNamespace(
        _live_sync_in_progress=True,
        _session_generation=4,
        project=SimpleNamespace(slug="run-b2w2"),
        current_game=current_game,
        _oras_live_monitor_failures=2,
        _oras_battle_probe_last_state="none",
        _oras_live_health_snapshot=None,
        _cancel_oras_initial_auto_sync=lambda: None,
        _active_azahar_realtime_key=lambda: "b2w2",
        _discard_b2w2_ghost_team_changes=lambda: 0,
        _publish_oras_live_snapshot=lambda snapshot, **kwargs: published.append((snapshot, kwargs)),
        _update_top_status=lambda: None,
        _schedule_oras_live_reconciliation=lambda delay: scheduled.append(delay),
        _show_live_sync_toast=lambda *args: toasts.append(args),
        _incoming_oras_role_changes=lambda *_: pytest.fail("B2/W2 no debe calcular writers de rol"),
        _save_oras_live_changes=lambda *_args, **_kwargs: pytest.fail("B2/W2 no debe escribir RAM"),
    )
    return ui, published, scheduled, toasts


def test_initial_sync_publishes_before_any_writer_path() -> None:
    game = _current_game()
    snapshot = SimpleNamespace(game=game)
    ui, published, scheduled, toasts = _ui_double(current_game=game)
    RoleRunManager._finish_oras_live_sync(ui, 4, "run-b2w2", snapshot, None)
    assert [entry[0] for entry in published] == [snapshot]
    assert scheduled == [950]
    assert toasts and "solo lectura" in toasts[0][1]
    assert "melonDS" in ui.sync_status
    assert ui._oras_live_health_snapshot is game


def test_reconciliation_never_falls_through_to_other_writers() -> None:
    before = _current_game()
    after = _current_game()
    after.party[0].level = 7
    snapshot = SimpleNamespace(game=after)
    ui, published, scheduled, _toasts = _ui_double(current_game=before)
    ui._oras_live_monitor_in_progress = True
    ui._oras_live_monitor_token = 11
    ui._oras_live_reconciliation_is_active = lambda: True
    RoleRunManager._finish_oras_live_reconciliation(
        ui, 4, "run-b2w2", 11, None, snapshot, None,
    )
    assert [entry[0] for entry in published] == [snapshot]
    assert scheduled == [950]
    assert "solo lectura" in ui.sync_status


def test_all_b2w2_mutations_are_blocked_by_live_ui_gate() -> None:
    ui = SimpleNamespace(_active_azahar_realtime_key=lambda: "b2w2")
    change = PendingPartyHeal(
        pokemon_slot=0, pokemon="Tepig", species="Tepig",
        pokemon_identity="498:0:1234:5678:89e50000",
    )
    assert RoleRunManager._oras_live_unsupported_changes(ui, [change]) == ["curación"]
