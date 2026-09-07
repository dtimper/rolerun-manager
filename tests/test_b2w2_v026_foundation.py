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
    MAX_PARTY,
    PARTY_BASE,
    PARTY_COUNT,
    PC_BASE,
    PC_BOX_COUNT,
    PC_BOX_DATA_SIZE,
    PC_BOX_SLOT_COUNT,
    PC_BOX_STRIDE,
    PC_MATRIX_SIZE,
    PK5_PARTY_SIZE,
    PK5_STORED_SIZE,
    _PERMUTATIONS,
    _crypt,
    empty_pk5_party,
    empty_pk5_stored,
    parse_pk5_boxed,
    parse_pk5_party,
)
from app.models import PendingChange, PendingPCRoleChange, PendingPartyHeal, PendingTeamChange
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

    # Desde alpha.57 el lector lleva el descriptor del juego, así que este
    # método deja de ser estático: la dirección del contador sale de ahí.
    candidate = B2W2MelonDSReader()._capture_nominal_candidate(read, allocation)
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


def _pc_matrix_con_dos_ocupados() -> tuple[bytes, int, int]:
    """La misma matriz, con un segundo PK5 distinto en Caja 1 · 2.

    Devuelve (matriz, pid_origen, pid_destino). Los dos `pid` llevan el mismo
    orden de bloques (`(pid >> 13) & 31`) para no depender de la permutación.
    """
    matrix = bytearray(_pc_matrix_fixture())
    pid_origen = 3 << 13
    pid_destino = (3 << 13) | 0x40000
    matrix[PK5_STORED_SIZE:2 * PK5_STORED_SIZE] = _pk5_fixture(
        pid=pid_destino,
    )[:PK5_STORED_SIZE]
    return bytes(matrix), pid_origen, pid_destino


def test_pc_swap_plan_cruza_los_dos_pk5_y_conserva_el_resto_de_la_matriz() -> None:
    """05-09-2026, pedido del usuario: intercambiar dos huecos OCUPADOS.

    Misma aritmética que `prepare_pc_move` -que ya cruza los dos bloques-, pero
    exigiendo el destino ocupado y devolviendo las dos criaturas para poder
    verificar las dos identidades después de escribir.
    """
    matrix, pid_origen, pid_destino = _pc_matrix_con_dos_ocupados()

    plan = B2W2MelonDSReader.prepare_pc_swap(matrix, 1, 1, 1, 2)

    assert plan.source_pokemon.pid == pid_origen
    assert plan.destination_pokemon.pid == pid_destino
    # Cruzados: ninguno de los dos huecos queda vacío.
    quedo = parse_pk5_boxed(plan.expected[:PK5_STORED_SIZE], 1, 1)
    llego = parse_pk5_boxed(plan.expected[PK5_STORED_SIZE:2 * PK5_STORED_SIZE], 1, 2)
    assert quedo is not None and quedo.pid == pid_destino
    assert llego is not None and llego.pid == pid_origen
    # Ni un byte más de la matriz se mueve.
    assert plan.expected[2 * PK5_STORED_SIZE:] == matrix[2 * PK5_STORED_SIZE:]


def test_pc_swap_plan_rechaza_un_destino_vacio() -> None:
    """Un destino libre es un traslado (`prepare_pc_move`), no un intercambio."""
    with pytest.raises(B2W2LiveError, match="destino.*vacío"):
        B2W2MelonDSReader.prepare_pc_swap(_pc_matrix_fixture(), 1, 1, 1, 2)


def test_pc_swap_plan_rechaza_un_origen_vacio() -> None:
    matrix, _origen, _destino = _pc_matrix_con_dos_ocupados()
    with pytest.raises(B2W2LiveError, match="origen.*vacío"):
        B2W2MelonDSReader.prepare_pc_swap(matrix, 1, 3, 1, 2)


def test_adapter_applies_only_validated_b2w2_pc_swap() -> None:
    matrix, pid_origen, pid_destino = _pc_matrix_con_dos_ocupados()
    empty, pokemon = B2W2MelonDSReader.parse_pc_matrix(matrix)
    origen = next(p for p in pokemon if p.pid == pid_origen)
    destino = next(p for p in pokemon if p.pid == pid_destino)

    class Reader:
        swapped = None

        def read_party(self):
            return _party_read()

        def read_pc(self, party):
            return B2W2PCRead(
                party.process_id, party.process_name, party.allocation_base,
                PC_BASE, matrix, empty, pokemon,
            )

        prepare_pc_swap = staticmethod(B2W2MelonDSReader.prepare_pc_swap)

        def swap_pc_slots(
            self, _party, *coordinates, source_identity=None, destination_identity=None,
        ):
            self.swapped = (coordinates, source_identity, destination_identity)

    reader = Reader()
    change = PendingTeamChange(
        operation="swap-box-slots", party_slot=0, box=1, box_slot=1,
        destination_box=1, destination_box_slot=2,
        incoming_snapshot={"pid": origen.pid, "tid": origen.tid, "sid": origen.sid},
        outgoing_snapshot={"pid": destino.pid, "tid": destino.tid, "sid": destino.sid},
    )
    result = B2W2RealTimeAdapter(reader=reader).apply_changes(_current_game(), [change])

    assert reader.swapped == (
        (1, 1, 1, 2),
        (origen.pid, origen.tid, origen.sid),
        (destino.pid, destino.tid, destino.sid),
    )
    assert result.applied_count == 1


def test_adapter_rechaza_un_intercambio_con_identidad_desfasada() -> None:
    """Las dos casillas son ancla: si una cambió, no se escribe nada."""
    matrix, pid_origen, _pid_destino = _pc_matrix_con_dos_ocupados()
    empty, pokemon = B2W2MelonDSReader.parse_pc_matrix(matrix)
    origen = next(p for p in pokemon if p.pid == pid_origen)

    class Reader:
        def read_party(self):
            return _party_read()

        def read_pc(self, party):
            return B2W2PCRead(
                party.process_id, party.process_name, party.allocation_base,
                PC_BASE, matrix, empty, pokemon,
            )

        prepare_pc_swap = staticmethod(B2W2MelonDSReader.prepare_pc_swap)

        def swap_pc_slots(self, *_args, **_kwargs):
            raise AssertionError("no debería llegar a escribir")

    change = PendingTeamChange(
        operation="swap-box-slots", party_slot=0, box=1, box_slot=1,
        destination_box=1, destination_box_slot=2,
        incoming_snapshot={"pid": origen.pid, "tid": origen.tid, "sid": origen.sid},
        outgoing_snapshot={"pid": 12345, "tid": 1, "sid": 2},
    )
    with pytest.raises(B2W2LiveError, match="destino.*ha cambiado"):
        B2W2RealTimeAdapter(reader=Reader()).apply_changes(_current_game(), [change])


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

        def read_battle_party(self, _raw):
            # 06-09-2026: Negro 2 ya tiene `battle_stride` medido, así que el
            # adaptador prefiere esta vía sobre `read_battle`.
            return (self.read_battle(_raw),)

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

    # El fallo fisico del 27-08-2026 (Azurill movido dentro del juego que
    # RoleRun seguia mostrando en su slot antiguo) venia de aqui: la vista
    # unificada es "team", de modo que exigir "pc" dejaba el sondeo inalcanzable.
    manager.active_page = "team"
    RoleRunManager._schedule_bdsp_pc_poll(manager, 200)
    assert manager._bdsp_pc_poll_after_id == "b2w2-poll"

    manager.active_page = "tms"
    RoleRunManager._schedule_bdsp_pc_poll(manager, 200)
    assert manager._bdsp_pc_poll_after_id is None


def _ui_double(*, current_game: SaveGameData):
    published = []
    scheduled = []
    toasts = []
    salud = []
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
        # Desde alpha.23 B2/W2 publica la salud viva por el camino comun, tambien
        # cuando la lane de presentacion no se pudo validar.
        _process_oras_health_snapshot=lambda game, source="overworld": salud.append(
            (game, source),
        ),
        _live_metadata_is_missing=lambda current, live: False,
        _process_oras_battle_state=lambda state: None,
        _reconcile_pending_faints_against_party=lambda game: None,
        # 06-09-2026: la reconciliación de quinta ajusta también la
        # tabla de aprendizajes por rol en la RAM de melonDS.
        _sync_gen5_levelup_moves=lambda game: None,
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


def test_only_capabilities_with_a_writer_pass_the_live_ui_gate() -> None:
    """Una capacidad solo atraviesa la compuerta cuando tiene writer propio.

    La curación se abrió en alpha.26, los movimientos sueltos en alpha.46. Lo
    que esta prueba protege es la regla, no la lista: el rol de un Pokémon que
    se queda en el PC sigue sin writer en B2/W2 y no debe pasar.
    """
    ui = SimpleNamespace(_active_azahar_realtime_key=lambda: "b2w2")
    change = PendingPCRoleChange(
        box=0, box_slot=0, pokemon="Tepig", species="Tepig",
        pokemon_identity="1:2:3:4", old_role="SIN ROL", new_role="Mago",
    )
    assert RoleRunManager._oras_live_unsupported_changes(ui, [change]) == [
        "roles del PC",
    ]


class _FakeMelonDS(B2W2MelonDSReader):
    """Simula la RAM de melonDS para ejercitar los writers sin proceso real.

    No sustituye a la validación física, pero permite reproducir de forma
    determinista el ciclo completo del writer: escritura, relectura con el
    parser de producción y rollback. Cualquier byte que el juego no aceptaría
    hace fallar aquí el mismo readback que falla en la máquina real.
    """

    ALLOCATION = 0x10000000
    PID = 4242
    NAME = "melonDS.exe"

    def __init__(self, count: int, party_raw: bytes, pc_raw: bytes) -> None:
        # El lector real inicializa aquí su cerrojo y su caché de base; los
        # writers heredados los necesitan aunque las lecturas estén sustituidas.
        super().__init__()
        self.count = int(count)
        self.party_raw = bytearray(MAX_PARTY * PK5_PARTY_SIZE)
        self.party_raw[:len(party_raw)] = party_raw
        self.pc_raw = bytearray(pc_raw)

    def read_party(self) -> B2W2PartyRead:
        raw = bytes(self.party_raw[:self.count * PK5_PARTY_SIZE])
        pokemon = tuple(
            parse_pk5_party(raw[index * PK5_PARTY_SIZE:(index + 1) * PK5_PARTY_SIZE], index)
            for index in range(self.count)
        )
        return B2W2PartyRead(
            self.PID, self.NAME, self.ALLOCATION, self.count, raw, pokemon,
        )

    def read_pc(self, party_read: B2W2PartyRead | None = None) -> B2W2PCRead:
        empty, pokemon = B2W2MelonDSReader.parse_pc_matrix(bytes(self.pc_raw))
        return B2W2PCRead(
            self.PID, self.NAME, self.ALLOCATION, PC_BASE,
            bytes(self.pc_raw), empty, pokemon,
        )

    def _write_process_bytes(self, process_id, host_address, payload) -> None:
        assert process_id == self.PID
        guest = host_address - self.ALLOCATION + DS_RAM_BASE
        if guest == PARTY_COUNT:
            self.count = payload[0]
        elif guest == PARTY_BASE:
            self.party_raw[:len(payload)] = payload
        elif PC_BASE <= guest < PC_BASE + PC_MATRIX_SIZE:
            offset = guest - PC_BASE
            self.pc_raw[offset:offset + len(payload)] = payload
        else:
            raise AssertionError(f"Escritura fuera de las regiones conocidas: {guest:#010x}")


def _withdraw_scenario() -> tuple[_FakeMelonDS, bytes, tuple[int, int, int]]:
    """Party de 1 y un Tepig en Caja 1 slot 1, listo para retirarse."""
    incoming_party = _pk5_fixture(pid=3 << 13)
    fake = _FakeMelonDS(1, _pk5_fixture(), _pc_matrix_fixture())
    return fake, incoming_party, (3 << 13, 1234, 5678)


def test_empty_pk5_stored_is_the_representation_the_production_parser_accepts() -> None:
    """El vacío de un slot PC liberado es un PK5 semilla-0, no 136 ceros.

    Evidencia: la captura física ``b2w2_party_resize_latest.json`` retiró un
    Pokémon desde el propio juego y el parser de producción leyó después
    ``pc_empty: 717`` sin error. Si el juego dejase ceros, ese mismo parser
    habría lanzado, porque los rechaza.
    """
    vacio = empty_pk5_stored()
    assert len(vacio) == PK5_STORED_SIZE
    assert parse_pk5_boxed(vacio, 1, 1) is None

    with pytest.raises(B2W2LiveError, match="Checksum"):
        parse_pk5_boxed(bytes(PK5_STORED_SIZE), 1, 1)

    # El vacío de party ya validado físicamente en alpha.13 empieza exactamente
    # por el vacío almacenado: una sola representación, dos longitudes.
    assert empty_pk5_party()[:PK5_STORED_SIZE] == vacio


def test_box_to_party_writes_an_empty_its_own_readback_accepts() -> None:
    """Regresión de B1: la retirada no podía superar su propio readback.

    ``resize_party_pc`` escribía 136 ceros en el slot PC liberado. La relectura
    valida los 720 slots con ``parse_pk5_boxed``, que rechaza esos ceros, así
    que la operación caía siempre en el rollback y la retirada era imposible.
    """
    fake, incoming_party, identity = _withdraw_scenario()

    after_party, after_pc = fake.resize_party_pc(
        fake.read_party(), operation="box-to-party",
        party_slot=0, box=1, box_slot=1,
        expected_identity=identity, incoming_party=incoming_party,
    )

    assert after_party.count == 2
    assert after_party.pokemon[1].pid == identity[0]
    # El origen queda libre y sigue siendo legible como vacío por el parser.
    assert not any((p.box, p.slot) == (1, 1) for p in after_pc.pokemon)
    assert after_pc.empty_slots == PC_BOX_COUNT * PC_BOX_SLOT_COUNT
    assert bytes(fake.pc_raw[:PK5_STORED_SIZE]) == empty_pk5_stored()


def test_box_to_party_still_rolls_back_when_the_identity_changed() -> None:
    """El arreglo de B1 no debe relajar ninguna validación existente."""
    fake, incoming_party, _ = _withdraw_scenario()
    antes_pc = bytes(fake.pc_raw)
    antes_count = fake.count

    with pytest.raises(B2W2LiveError, match="identidad entrante"):
        fake.resize_party_pc(
            fake.read_party(), operation="box-to-party",
            party_slot=0, box=1, box_slot=1,
            expected_identity=(0xDEADBEEF, 1, 2), incoming_party=incoming_party,
        )

    assert bytes(fake.pc_raw) == antes_pc
    assert fake.count == antes_count


def test_party_to_box_keeps_working_after_the_empty_slot_fix() -> None:
    """El depósito comparte writer con la retirada: no puede regresar."""
    fake = _FakeMelonDS(2, _pk5_fixture() + _pk5_fixture(pid=5 << 13), _pc_matrix_fixture())
    identidad = (5 << 13, 1234, 5678)

    after_party, after_pc = fake.resize_party_pc(
        fake.read_party(), operation="party-to-box",
        party_slot=1, box=1, box_slot=2, expected_identity=identidad,
    )

    assert after_party.count == 1
    depositado = next(p for p in after_pc.pokemon if (p.box, p.slot) == (1, 2))
    assert (depositado.pid, depositado.tid, depositado.sid) == identidad


def _heal_fixture() -> PendingPartyHeal:
    return PendingPartyHeal(
        pokemon_slot=0, pokemon="Tepig", species="Tepig", pokemon_identity="tepig",
    )


def _auto_apply_manager(live_key: str, changes) -> SimpleNamespace:
    return SimpleNamespace(
        _active_azahar_realtime_key=lambda: live_key,
        run=SimpleNamespace(pending_changes=list(changes)),
        _oras_live_auto_apply_available=lambda: True,
        _oras_live_auto_apply_ids=set(),
        _schedule_oras_live_auto_apply=lambda *args, **kwargs: None,
        save_engine=SimpleNamespace(key=live_key),
    )


@pytest.mark.parametrize("live_key", ["b2w2", "bdsp", "sm", "usum", "xy", "oras"])
def test_heal_is_offered_only_where_the_gate_really_applies_it(live_key: str) -> None:
    """Regresión de B2, escrita como invariante para todos los backends.

    Ofrecer CURAR donde la compuerta de auto-aplicación no acepta un
    ``PendingPartyHeal`` deja seis cambios encolados que nadie escribe ni
    retira. Y como ``_oras_live_reconciliation_can_read`` exige la cola vacía,
    el monitor deja de leer la partida viva. El botón y la compuerta tienen que
    decir siempre lo mismo, en cualquier juego.
    """
    heal = _heal_fixture()
    manager = _auto_apply_manager(live_key, [heal])

    RoleRunManager._request_oras_live_auto_apply(manager, [heal])
    la_compuerta_lo_aplica = bool(manager._oras_live_auto_apply_ids)
    se_ofrece_el_boton = RoleRunManager._live_party_heal_available(manager)

    assert se_ofrece_el_boton == la_compuerta_lo_aplica, (
        f"{live_key}: el botón CURAR y la compuerta no coinciden"
    )


def test_b2w2_offers_the_heal_button_now_that_it_has_a_writer() -> None:
    """alpha.26 le dio a B2/W2 su writer de curacion transaccional."""
    manager = SimpleNamespace(_active_azahar_realtime_key=lambda: "b2w2")
    assert RoleRunManager._live_party_heal_available(manager) is True


def test_a_b2w2_heal_reaches_the_writer_instead_of_blocking_the_monitor() -> None:
    """La cola vacia es la condicion que el monitor necesita para leer.

    En alpha.16 la curacion se encolaba sin writer y bloqueaba el monitor para
    siempre; se cerro el boton. Desde alpha.26 el writer existe, asi que la
    curacion atraviesa la compuerta, se aplica y sale de la cola.
    """
    heal = _heal_fixture()
    manager = _auto_apply_manager("b2w2", [heal])
    RoleRunManager._request_oras_live_auto_apply(manager, [heal])

    assert manager._oras_live_auto_apply_ids == {id(heal)}
    assert RoleRunManager._live_party_heal_available(manager) is True
