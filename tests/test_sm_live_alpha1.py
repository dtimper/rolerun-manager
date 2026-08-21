from __future__ import annotations

import struct
from pathlib import Path

import pytest

from app.azahar_rpc import AzaharProcess
from app.oras_live import encrypt_pk6
from app.realtime.sm_adapter import SMRealTimeAdapter
from app.models import PendingInventoryChange, PendingRoleChange
from app.save_engine_client import SaveGameData, SavePokemon
from app.win_process_memory import HostPartyTarget, WindowsProcessMemory
from app.sm_live import (
    PK7_PARTY_SIZE,
    PK7_STORED_SIZE,
    SM_PARTY_REFERENCE_ADDRESS,
    SM_PARTY_SCAN_RADIUS,
    SM_PARTY_SPAN,
    SM_PARTY_STATS_OFFSET,
    SM_PARTY_STATS_SIZE,
    SM_PARTY_STRIDE,
    SM_TITLE_IDS,
    SM_SAVE_ITEM_BLOCK_SIZE,
    SMLiveError,
    SMLiveReader,
    SMLiveWriter,
    parse_pk7_party,
)


DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _checksum(data: bytes) -> int:
    return sum(struct.unpack_from("<112H", data, 8)) & 0xFFFF


def _encrypted_pk7(
    *,
    species: int,
    pid: int,
    tid: int,
    sid: int,
    level: int = 25,
    moves: tuple[int, int, int, int] = (33, 45, 0, 0),
    hp: tuple[int, int] = (50, 60),
    marking_value: int = 0,
) -> bytes:
    data = bytearray(PK7_PARTY_SIZE)
    struct.pack_into("<I", data, 0x00, 0x1234ABCD ^ pid)
    struct.pack_into("<H", data, 0x04, 0)
    struct.pack_into("<H", data, 0x08, species)
    struct.pack_into("<H", data, 0x0C, tid)
    struct.pack_into("<H", data, 0x0E, sid)
    data[0x14] = 65
    struct.pack_into("<H", data, 0x16, int(marking_value) & 0xFFFF)
    struct.pack_into("<I", data, 0x18, pid)
    name = "TEST".encode("utf-16le") + b"\0\0"
    data[0x40:0x40 + len(name)] = name
    for offset, move in zip((0x5A, 0x5C, 0x5E, 0x60), moves):
        struct.pack_into("<H", data, offset, move)
    struct.pack_into("<I", data, 0x74, 31 | (31 << 5))
    data[0xEC] = level
    struct.pack_into("<H", data, 0xF0, hp[0])
    struct.pack_into("<H", data, 0xF2, hp[1])
    struct.pack_into("<H", data, 0x06, _checksum(data))
    # PKHeX documenta que PK7 usa el mismo Encrypt/Decrypt67 que PK6.
    return encrypt_pk6(bytes(data))


def _saved_mon(slot: int, species: int, pid: int, tid: int, sid: int, role: str = "Mago") -> SavePokemon:
    return SavePokemon(
        slot=slot,
        species_id=species,
        species=f"Species {species}",
        nickname=f"Nick {species}",
        level=25,
        held_item="Ninguno",
        ability="Ability",
        moves=["Placaje", "Gruñido", "—", "—"],
        move_ids=[33, 45, 0, 0],
        is_egg=False,
        markings=[False, False, True, False, False, False],
        role=role,
        role_symbol="♥",
        pid=pid,
        tid=tid,
        sid=sid,
    )


def _game(*mons: SavePokemon) -> SaveGameData:
    return SaveGameData(
        game="Pokémon Sol",
        save_type="SAV7SM",
        generation=7,
        trainer="Tester",
        party=list(mons),
        raw={},
    )


class FakeRPC:
    def __init__(self, start: int, memory: bytes, process: AzaharProcess, *, allow_writes: bool = False) -> None:
        self.start = int(start)
        self.memory = bytearray(memory)
        self.process = process
        self.allow_writes = bool(allow_writes)
        self.selected: int | None = None
        self.read_calls: list[tuple[int, int]] = []
        self.write_calls: list[tuple[int, bytes]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def process_list(self):
        return [self.process]

    def set_process(self, process_id: int):
        assert process_id == self.process.process_id
        self.selected = process_id

    def read_memory(self, address: int, size: int) -> bytes:
        self.read_calls.append((int(address), int(size)))
        offset = int(address) - self.start
        if offset < 0 or offset + int(size) > len(self.memory):
            return b"\0" * int(size)
        return self.memory[offset:offset + int(size)]

    def write_memory(self, address: int, contents: bytes):
        self.write_calls.append((int(address), bytes(contents)))
        if not self.allow_writes:
            raise AssertionError("este test no permite escrituras RAM")
        offset = int(address) - self.start
        if offset < 0 or offset + len(contents) > len(self.memory):
            raise AssertionError("escritura fuera de la memoria fake")
        self.memory[offset:offset + len(contents)] = contents


class AzaharAliasRPC(FakeRPC):
    """Replica la restricción real de Azahar 263745c.

    Las lecturas a NEW_LINEAR_HEAP (0x30000000...) funcionan, pero WriteMemory
    las ignora. El alias LINEAR_HEAP (0x14000000 + mismo offset) apunta al mismo
    backing FCRAM y sí es escribible.
    """

    @staticmethod
    def _canonical_address(address: int) -> int:
        address = int(address)
        if 0x14000000 <= address < 0x1C000000:
            return 0x30000000 + (address - 0x14000000)
        return address

    def read_memory(self, address: int, size: int) -> bytes:
        self.read_calls.append((int(address), int(size)))
        canonical = self._canonical_address(address)
        offset = canonical - self.start
        if offset < 0 or offset + int(size) > len(self.memory):
            return b"\0" * int(size)
        return self.memory[offset:offset + int(size)]

    def write_memory(self, address: int, contents: bytes):
        self.write_calls.append((int(address), bytes(contents)))
        if not self.allow_writes:
            raise AssertionError("este test no permite escrituras RAM")
        address = int(address)
        if 0x30000000 <= address < 0x40000000:
            # Azahar responde al RPC pero HandleWriteMemory no entra en ningún
            # rango permitido: no muta memoria.
            return
        canonical = self._canonical_address(address)
        offset = canonical - self.start
        if offset < 0 or offset + len(contents) > len(self.memory):
            raise AssertionError("escritura fuera de la memoria fake")
        self.memory[offset:offset + len(contents)] = contents


def _memory_for_party(base: int, records: dict[int, bytes]) -> tuple[int, bytes]:
    """Materializa el layout sparse documentado para la party runtime de SM."""
    start = SM_PARTY_REFERENCE_ADDRESS - SM_PARTY_SCAN_RADIUS
    end = SM_PARTY_REFERENCE_ADDRESS + SM_PARTY_SCAN_RADIUS + SM_PARTY_SPAN
    memory = bytearray(end - start)
    for slot, raw in records.items():
        assert len(raw) == PK7_PARTY_SIZE
        address = int(base) + (int(slot) - 1) * SM_PARTY_STRIDE
        offset = address - start
        memory[offset:offset + PK7_STORED_SIZE] = raw[:PK7_STORED_SIZE]
        stats_offset = offset + SM_PARTY_STATS_OFFSET
        memory[stats_offset:stats_offset + SM_PARTY_STATS_SIZE] = raw[PK7_STORED_SIZE:PK7_STORED_SIZE + SM_PARTY_STATS_SIZE]
    return start, bytes(memory)


def _reader(fake: FakeRPC) -> SMLiveReader:
    return SMLiveReader(
        DATA_DIR / "move_catalog.json",
        client_factory=lambda: fake,
        stable_delay=0,
        snapshot_attempts=2,
    )


def test_pk7_parser_reads_identity_moves_level_and_hp():
    raw = _encrypted_pk7(species=25, pid=0xAABBCCDD, tid=1234, sid=5678, level=31, hp=(44, 79))
    mon = parse_pk7_party(raw, 1, {33: "Placaje", 45: "Gruñido"})
    assert mon is not None
    assert (mon.species_id, mon.pid, mon.tid, mon.sid) == (25, 0xAABBCCDD, 1234, 5678)
    assert mon.move_ids == [33, 45, 0, 0]
    assert mon.level == 31
    assert (mon.current_hp, mon.max_hp) == (44, 79)
    assert mon.role == "SIN ROL"


def test_reader_accepts_reference_only_after_full_main_witness_match():
    saved = _saved_mon(1, 25, 0x11112222, 100, 200, role="Mago")
    start, memory = _memory_for_party(
        SM_PARTY_REFERENCE_ADDRESS,
        {1: _encrypted_pk7(species=25, pid=saved.pid, tid=saved.tid, sid=saved.sid)},
    )
    fake = FakeRPC(start, memory, AzaharProcess(7, next(iter(SM_TITLE_IDS)), "niji_loc"))
    snapshot = _reader(fake).read(_game(saved))
    assert snapshot.party_base == SM_PARTY_REFERENCE_ADDRESS
    assert len(snapshot.game.party) == 1
    live = snapshot.game.party[0]
    assert live.nickname == saved.nickname
    # Alpha.4 ya toma los marcadores de RAM, no los conserva artificialmente del main.
    assert live.role == "SIN ROL"
    assert live.markings == [False] * 6
    assert fake.write_calls == []


def test_reader_uses_sparse_stored_and_stats_reads_not_contiguous_pk7_party():
    saved = _saved_mon(1, 25, 0x11223344, 321, 654)
    start, memory = _memory_for_party(
        SM_PARTY_REFERENCE_ADDRESS,
        {1: _encrypted_pk7(species=25, pid=saved.pid, tid=saved.tid, sid=saved.sid)},
    )
    fake = FakeRPC(start, memory, AzaharProcess(8, 0x0004000000164800, "niji_loc"))
    snapshot = _reader(fake).read(_game(saved))
    assert snapshot.party_base == SM_PARTY_REFERENCE_ADDRESS
    expected_stored = (SM_PARTY_REFERENCE_ADDRESS, PK7_STORED_SIZE)
    expected_stats = (SM_PARTY_REFERENCE_ADDRESS + SM_PARTY_STATS_OFFSET, SM_PARTY_STATS_SIZE)
    assert expected_stored in fake.read_calls
    assert expected_stats in fake.read_calls
    assert (SM_PARTY_REFERENCE_ADDRESS, PK7_PARTY_SIZE) not in fake.read_calls


def test_reader_can_resolve_unique_readonly_nearby_base_without_alignment_assumption():
    saved = _saved_mon(1, 722, 0x01020304, 321, 654, role="Prisma")
    actual = SM_PARTY_REFERENCE_ADDRESS + 0x23
    start, memory = _memory_for_party(
        actual,
        {1: _encrypted_pk7(species=saved.species_id, pid=saved.pid, tid=saved.tid, sid=saved.sid)},
    )
    fake = FakeRPC(start, memory, AzaharProcess(11, 0x0004000000164800, "niji_loc"))
    reader = _reader(fake)
    snapshot = reader.read(_game(saved))
    assert snapshot.party_base == actual
    state = reader.runtime_state()
    assert state["last_resolution"]["source"] == "ventana de solo lectura + testigo completo"
    assert fake.write_calls == []


def test_reader_rejects_structurally_valid_wrong_party_instead_of_trusting_reference():
    saved = _saved_mon(1, 25, 0x11112222, 100, 200)
    wrong = _encrypted_pk7(species=133, pid=0x99998888, tid=555, sid=777)
    start, memory = _memory_for_party(SM_PARTY_REFERENCE_ADDRESS, {1: wrong})
    fake = FakeRPC(start, memory, AzaharProcess(9, 0x0004000000175E00, "niji_loc"))
    with pytest.raises(SMLiveError, match="No se pudo demostrar la dirección viva"):
        _reader(fake).read(_game(saved))
    assert fake.write_calls == []


def test_reader_rejects_niji_loc_with_wrong_nonzero_title_id():
    saved = _saved_mon(1, 25, 1, 2, 3)
    start, memory = _memory_for_party(
        SM_PARTY_REFERENCE_ADDRESS,
        {1: _encrypted_pk7(species=25, pid=1, tid=2, sid=3)},
    )
    fake = FakeRPC(start, memory, AzaharProcess(5, 0x00040000001B5000, "niji_loc"))
    with pytest.raises(SMLiveError, match="Title ID válido"):
        _reader(fake).read(_game(saved))
    assert fake.write_calls == []


def test_sm_adapter_reports_live_role_capability_and_writes_verified_marker():
    saved = _saved_mon(1, 25, 0x11112222, 100, 200, role="SIN ROL")
    start, memory = _memory_for_party(
        SM_PARTY_REFERENCE_ADDRESS,
        {1: _encrypted_pk7(species=25, pid=saved.pid, tid=saved.tid, sid=saved.sid)},
    )
    fake = AzaharAliasRPC(
        start, memory, AzaharProcess(7, 0x0004000000164800, "niji_loc"),
        allow_writes=True,
    )
    adapter = SMRealTimeAdapter(_reader(fake))
    snapshot = adapter.capture_full(_game(saved), save_path=None)
    assert snapshot.game.party[0].species_id == 25
    assert snapshot.game.party[0].role == "SIN ROL"
    assert snapshot.metadata["readonly"] is False
    assert adapter.runtime_state()["capabilities"]["roles"] == "read-write-alpha.15-content-validated-host-fcram"
    assert adapter.runtime_state()["capabilities"]["moves_write"] == "read-write-alpha.15-content-validated-host-fcram"

    change = PendingRoleChange(
        pokemon_slot=1, pokemon=saved.nickname, species=saved.species,
        old_role="SIN ROL", new_role="Mago",
        pokemon_identity=f"25:{saved.pid}:{saved.tid}:{saved.sid}",
    )
    result = adapter.apply_changes(snapshot.game, [change])
    assert result.game.party[0].role == "Mago"
    assert result.game.party[0].markings == [False, False, True, False, False, False]
    assert fake.write_calls

    reread = adapter.capture_full(result.game, save_path=None)
    assert reread.game.party[0].role == "Mago"


def test_pk7_reader_treats_any_nonzero_gen7_marking_color_as_active():
    # Mago = tercer símbolo. Valor 2 simula el segundo color disponible en Gen7.
    raw = _encrypted_pk7(species=25, pid=77, tid=1, sid=2, marking_value=(0b10 << (2 * 2)))
    mon = parse_pk7_party(raw, 1, {})
    assert mon is not None
    assert mon.markings == [False, False, True, False, False, False]
    assert mon.role == "Mago"


def test_sm_role_writer_rejects_stale_old_role_without_writing():
    saved = _saved_mon(1, 25, 0x11112222, 100, 200, role="Mago")
    # La RAM real ya es Asesino (segundo símbolo), pero el cambio afirma partir de Mago.
    start, memory = _memory_for_party(
        SM_PARTY_REFERENCE_ADDRESS,
        {1: _encrypted_pk7(
            species=25, pid=saved.pid, tid=saved.tid, sid=saved.sid,
            marking_value=(0b01 << (1 * 2)),
        )},
    )
    fake = FakeRPC(
        start, memory, AzaharProcess(31, 0x0004000000164800, "niji_loc"),
        allow_writes=True,
    )
    adapter = SMRealTimeAdapter(_reader(fake))
    snapshot = adapter.capture_full(_game(saved), save_path=None)
    assert snapshot.game.party[0].role == "Asesino"
    change = PendingRoleChange(
        pokemon_slot=1, pokemon=saved.nickname, species=saved.species,
        old_role="Mago", new_role="Prisma",
        pokemon_identity=f"25:{saved.pid}:{saved.tid}:{saved.sid}",
    )
    with pytest.raises(SMLiveError, match="cambió de rol dentro del juego"):
        adapter.apply_changes(snapshot.game, [change])
    assert fake.write_calls == []


def test_cached_base_allows_later_party_change_without_resaving_main():
    saved = _saved_mon(1, 25, 0x11112222, 100, 200, role="Mago")
    start, memory = _memory_for_party(
        SM_PARTY_REFERENCE_ADDRESS,
        {1: _encrypted_pk7(species=25, pid=saved.pid, tid=saved.tid, sid=saved.sid)},
    )
    fake = FakeRPC(start, memory, AzaharProcess(17, next(iter(SM_TITLE_IDS)), "niji_loc"))
    reader = _reader(fake)
    first = reader.read(_game(saved))
    assert first.game.party[0].species_id == 25

    # Después de demostrar la base, el juego puede cambiar el equipo sin que el
    # main se vuelva a guardar. El monitor debe seguir leyendo la RAM real, no
    # volver a exigir que coincida con el testigo inicial.
    newcomer = _encrypted_pk7(species=133, pid=0x99887766, tid=777, sid=888)
    _start, changed_memory = _memory_for_party(SM_PARTY_REFERENCE_ADDRESS, {1: newcomer})
    fake.memory = changed_memory
    second = reader.read(first.game)
    assert (second.game.party[0].species_id, second.game.party[0].pid) == (133, 0x99887766)
    assert fake.write_calls == []


def test_party_cache_is_scoped_to_process_id_so_restart_recalibrates():
    saved = _saved_mon(1, 25, 0x11112222, 100, 200)
    title_id = next(iter(SM_TITLE_IDS))
    start, memory = _memory_for_party(
        SM_PARTY_REFERENCE_ADDRESS,
        {1: _encrypted_pk7(species=25, pid=saved.pid, tid=saved.tid, sid=saved.sid)},
    )
    first_rpc = FakeRPC(start, memory, AzaharProcess(21, title_id, "niji_loc"))
    holder = {"rpc": first_rpc}
    reader = SMLiveReader(
        DATA_DIR / "move_catalog.json",
        client_factory=lambda: holder["rpc"],
        stable_delay=0,
        snapshot_attempts=2,
    )
    assert reader.read(_game(saved)).party_base == SM_PARTY_REFERENCE_ADDRESS

    # Simula que Azahar reinicia el proceso y la base real cambia. Mismo juego y
    # nombre, distinto PID: no se debe reciclar la dirección demostrada del proceso
    # anterior; se calibra de nuevo únicamente por lectura + testigo del main.
    moved_base = SM_PARTY_REFERENCE_ADDRESS + 0x31
    start2, memory2 = _memory_for_party(
        moved_base,
        {1: _encrypted_pk7(species=25, pid=saved.pid, tid=saved.tid, sid=saved.sid)},
    )
    second_rpc = FakeRPC(start2, memory2, AzaharProcess(22, title_id, "niji_loc"))
    holder["rpc"] = second_rpc
    assert reader.read(_game(saved)).party_base == moved_base
    assert second_rpc.write_calls == []


def test_sm_role_writer_rolls_back_if_postwrite_pk7_does_not_validate():
    saved = _saved_mon(1, 25, 0xABCDEF01, 100, 200, role="SIN ROL")
    start, memory = _memory_for_party(
        SM_PARTY_REFERENCE_ADDRESS,
        {1: _encrypted_pk7(species=25, pid=saved.pid, tid=saved.tid, sid=saved.sid)},
    )

    class CorruptFirstWriteRPC(AzaharAliasRPC):
        def __init__(self):
            super().__init__(
                start, memory, AzaharProcess(41, 0x0004000000164800, "niji_loc"),
                allow_writes=True,
            )
            self.corrupt_next = True

        def write_memory(self, address: int, contents: bytes):
            payload = bytearray(contents)
            if self.corrupt_next:
                self.corrupt_next = False
                payload[0x20] ^= 0x5A
            super().write_memory(address, bytes(payload))

    fake = CorruptFirstWriteRPC()
    original_stored = bytes(fake.read_memory(SM_PARTY_REFERENCE_ADDRESS, PK7_STORED_SIZE))
    adapter = SMRealTimeAdapter(_reader(fake))
    snapshot = adapter.capture_full(_game(saved), save_path=None)
    change = PendingRoleChange(
        pokemon_slot=1, pokemon=saved.nickname, species=saved.species,
        old_role="SIN ROL", new_role="Líbero",
        pokemon_identity=f"25:{saved.pid}:{saved.tid}:{saved.sid}",
    )
    with pytest.raises(SMLiveError, match="restauró los PK7 originales"):
        adapter.apply_changes(snapshot.game, [change])
    assert bytes(fake.read_memory(SM_PARTY_REFERENCE_ADDRESS, PK7_STORED_SIZE)) == original_stored
    assert len(fake.write_calls) >= 2  # intento + rollback


def test_sm_alpha13_replaces_move_through_validated_writer() -> None:
    from app.models import PendingChange

    saved = _saved_mon(1, 25, 0x10112222, 100, 200, role="SIN ROL")
    start, memory = _memory_for_party(
        SM_PARTY_REFERENCE_ADDRESS,
        {1: _encrypted_pk7(species=25, pid=saved.pid, tid=saved.tid, sid=saved.sid, moves=(33, 45, 0, 0))},
    )
    fake = AzaharAliasRPC(
        start, memory, AzaharProcess(41, 0x0004000000164800, "niji_loc"), allow_writes=True,
    )
    adapter = SMRealTimeAdapter(
        _reader(fake), move_pp_for=lambda move_id: {55: 25}[int(move_id)],
        move_allowed=lambda move_id: int(move_id) == 55,
    )
    snapshot = adapter.capture_full(_game(saved), save_path=None)
    change = PendingChange(
        role="SIN ROL", pokemon_slot=1, pokemon=saved.nickname, species=saved.species,
        move_slot=1, old_move="Placaje", old_move_id=33,
        new_move="Pistola Agua", new_move_id=55,
        pokemon_identity=f"25:{saved.pid}:{saved.tid}:{saved.sid}",
    )
    result = adapter.apply_changes(snapshot.game, [change])
    assert result.game.party[0].move_ids == [55, 45, 0, 0]


def test_sm_alpha13_deletes_and_compacts_moves() -> None:
    from app.models import PendingChange

    saved = _saved_mon(1, 25, 0x10113333, 100, 200, role="SIN ROL")
    start, memory = _memory_for_party(
        SM_PARTY_REFERENCE_ADDRESS,
        {1: _encrypted_pk7(species=25, pid=saved.pid, tid=saved.tid, sid=saved.sid, moves=(33, 45, 55, 0))},
    )
    fake = AzaharAliasRPC(
        start, memory, AzaharProcess(42, 0x0004000000164800, "niji_loc"), allow_writes=True,
    )
    adapter = SMRealTimeAdapter(_reader(fake), move_pp_for=lambda _move_id: 20, move_allowed=lambda _move_id: True)
    snapshot = adapter.capture_full(_game(saved), save_path=None)
    change = PendingChange(
        role="SIN ROL", pokemon_slot=1, pokemon=saved.nickname, species=saved.species,
        move_slot=1, old_move="Placaje", old_move_id=33,
        new_move="—", new_move_id=0,
        pokemon_identity=f"25:{saved.pid}:{saved.tid}:{saved.sid}",
    )
    result = adapter.apply_changes(snapshot.game, [change])
    assert result.game.party[0].move_ids == [45, 55, 0, 0]


def test_sm_alpha13_rejects_move_not_proven_available_without_write() -> None:
    from app.models import PendingChange

    saved = _saved_mon(1, 25, 0x10114444, 100, 200, role="SIN ROL")
    start, memory = _memory_for_party(
        SM_PARTY_REFERENCE_ADDRESS,
        {1: _encrypted_pk7(species=25, pid=saved.pid, tid=saved.tid, sid=saved.sid, moves=(33, 45, 0, 0))},
    )
    fake = AzaharAliasRPC(
        start, memory, AzaharProcess(43, 0x0004000000164800, "niji_loc"), allow_writes=True,
    )
    adapter = SMRealTimeAdapter(_reader(fake), move_pp_for=lambda _move_id: 20, move_allowed=lambda _move_id: False)
    snapshot = adapter.capture_full(_game(saved), save_path=None)
    change = PendingChange(
        role="SIN ROL", pokemon_slot=1, pokemon=saved.nickname, species=saved.species,
        move_slot=1, old_move="Placaje", old_move_id=33,
        new_move="Movimiento", new_move_id=55,
        pokemon_identity=f"25:{saved.pid}:{saved.tid}:{saved.sid}",
    )
    before = len(fake.write_calls)
    with pytest.raises(SMLiveError, match="no está demostrado como disponible"):
        adapter.apply_changes(snapshot.game, [change])
    assert len(fake.write_calls) == before


def test_sm_role_writer_swaps_two_markers_in_one_verified_batch() -> None:
    first = _saved_mon(1, 722, 0x61112222, 100, 200, role="Líbero")
    second = _saved_mon(2, 731, 0x71112222, 100, 200, role="Asesino")
    start, memory = _memory_for_party(
        SM_PARTY_REFERENCE_ADDRESS,
        {
            1: _encrypted_pk7(
                species=first.species_id, pid=first.pid, tid=first.tid, sid=first.sid,
                marking_value=(0b01 << (0 * 2)),
            ),
            2: _encrypted_pk7(
                species=second.species_id, pid=second.pid, tid=second.tid, sid=second.sid,
                marking_value=(0b01 << (1 * 2)),
            ),
        },
    )
    fake = AzaharAliasRPC(
        start, memory, AzaharProcess(46, 0x0004000000164800, "niji_loc"), allow_writes=True,
    )
    adapter = SMRealTimeAdapter(_reader(fake))
    snapshot = adapter.capture_full(_game(first, second), save_path=None)
    changes = [
        PendingRoleChange(
            pokemon_slot=2, pokemon=second.nickname, species=second.species,
            old_role="Asesino", new_role="Líbero",
            pokemon_identity=f"{second.species_id}:{second.pid}:{second.tid}:{second.sid}",
        ),
        PendingRoleChange(
            pokemon_slot=1, pokemon=first.nickname, species=first.species,
            old_role="Líbero", new_role="Asesino",
            pokemon_identity=f"{first.species_id}:{first.pid}:{first.tid}:{first.sid}",
        ),
    ]
    result = adapter.apply_changes(snapshot.game, changes)
    by_species = {p.species_id: p for p in result.game.party}
    assert by_species[first.species_id].role == "Asesino"
    assert by_species[second.species_id].role == "Líbero"
    assert len(fake.write_calls) >= 2


def test_alpha11_uses_validated_old_linear_heap_alias_for_new_linear_party() -> None:
    saved = _saved_mon(1, 25, 0xABC10001, 100, 200, role="SIN ROL")
    start, memory = _memory_for_party(
        SM_PARTY_REFERENCE_ADDRESS,
        {1: _encrypted_pk7(species=25, pid=saved.pid, tid=saved.tid, sid=saved.sid)},
    )
    fake = AzaharAliasRPC(
        start, memory, AzaharProcess(55, 0x0004000000164800, "niji_loc"), allow_writes=True,
    )
    adapter = SMRealTimeAdapter(_reader(fake))
    snapshot = adapter.capture_full(_game(saved), save_path=None)
    change = PendingRoleChange(
        pokemon_slot=1, pokemon=saved.nickname, species=saved.species,
        old_role="SIN ROL", new_role="Support",
        pokemon_identity=f"25:{saved.pid}:{saved.tid}:{saved.sid}",
    )
    result = adapter.apply_changes(snapshot.game, [change])
    assert result.game.party[0].role == "Support"
    # La escritura real debe ir al alias 0x18..., nunca al canonical 0x34...
    write_addresses = [address for address, _data in fake.write_calls]
    assert 0x18195E10 in write_addresses
    assert 0x34195E10 not in write_addresses


class FakeWindowsHostMemory:
    def __init__(self, fake: FakeRPC, *, targets: int = 1, host_base: int = 0x000001A000000000) -> None:
        self.fake = fake
        self.targets = int(targets)
        self.host_base = int(host_base)
        self.closed = False

    def find_party_targets(self, **_kwargs):
        return [HostPartyTarget(999 + i, "azahar.exe", self.host_base + (i * 0x10000000)) for i in range(self.targets)]

    def find_exact_block_in_anchor_region(self, *, pid: int, anchor_address: int, pattern: bytes, max_matches: int = 8):
        assert int(pid) >= 999
        raw = bytes(pattern)
        matches = []
        pos = 0
        while True:
            hit = bytes(self.fake.memory).find(raw, pos)
            if hit < 0:
                break
            canonical = self.fake.start + hit
            matches.append(self.host_base + (canonical - SM_PARTY_REFERENCE_ADDRESS))
            if len(matches) >= int(max_matches):
                break
            pos = hit + 1
        return matches

    def find_structural_block_candidates_in_anchor_region(
        self, *, pid: int, anchor_address: int, pattern: bytes, excluded_ranges=(),
        window_size: int = 16, windows_per_quartile: int = 4, max_candidates: int = 32,
    ):
        assert int(pid) >= 999
        witnesses = WindowsProcessMemory._structural_windows(
            bytes(pattern), excluded_ranges=excluded_ranges, window_size=window_size,
            windows_per_quartile=windows_per_quartile,
        )
        support: dict[int, set[int]] = {}
        hay = bytes(self.fake.memory)
        for witness_offset, witness in witnesses:
            pos = 0
            while True:
                hit = hay.find(witness, pos)
                if hit < 0:
                    break
                canonical_base = self.fake.start + hit - int(witness_offset)
                host_candidate = self.host_base + (canonical_base - SM_PARTY_REFERENCE_ADDRESS)
                support.setdefault(host_candidate, set()).add(int(witness_offset))
                pos = hit + 1
        ranked = sorted(
            ((base, tuple(sorted(offsets))) for base, offsets in support.items()),
            key=lambda item: (-len(item[1]), item[0]),
        )[:int(max_candidates)]
        return ranked, tuple(offset for offset, _chunk in witnesses)

    def open_process(self, pid: int):
        return int(pid)

    def close_process(self, _handle):
        self.closed = True

    def _canonical(self, address: int) -> int:
        return SM_PARTY_REFERENCE_ADDRESS + (int(address) - self.host_base)

    def read(self, _handle, address: int, size: int) -> bytes:
        canonical = self._canonical(address)
        offset = canonical - self.fake.start
        if offset < 0 or offset + int(size) > len(self.fake.memory):
            return b"\0" * int(size)
        return bytes(self.fake.memory[offset:offset + int(size)])

    def write(self, _handle, address: int, data: bytes) -> None:
        canonical = self._canonical(address)
        offset = canonical - self.fake.start
        if offset < 0 or offset + len(data) > len(self.fake.memory):
            raise AssertionError("host write fuera de memoria fake")
        self.fake.memory[offset:offset + len(data)] = bytes(data)


def test_alpha12_falls_back_to_content_validated_windows_fcram_when_rpc_alias_is_not_mapped() -> None:
    saved = _saved_mon(1, 25, 0xABC10002, 100, 200, role="SIN ROL")
    start, memory = _memory_for_party(
        SM_PARTY_REFERENCE_ADDRESS,
        {1: _encrypted_pk7(species=25, pid=saved.pid, tid=saved.tid, sid=saved.sid)},
    )

    class WrongAliasRPC(AzaharAliasRPC):
        def read_memory(self, address: int, size: int) -> bytes:
            if 0x14000000 <= int(address) < 0x1C000000:
                self.read_calls.append((int(address), int(size)))
                return b"\xA5" * int(size)
            return super().read_memory(address, size)

    fake = WrongAliasRPC(
        start, memory, AzaharProcess(56, 0x0004000000164800, "niji_loc"), allow_writes=True,
    )
    adapter = SMRealTimeAdapter(_reader(fake))
    host = FakeWindowsHostMemory(fake)
    adapter.writer.host_memory_factory = lambda: host
    snapshot = adapter.capture_full(_game(saved), save_path=None)
    change = PendingRoleChange(
        pokemon_slot=1, pokemon=saved.nickname, species=saved.species,
        old_role="SIN ROL", new_role="Líbero",
        pokemon_identity=f"25:{saved.pid}:{saved.tid}:{saved.sid}",
    )
    result = adapter.apply_changes(snapshot.game, [change])
    assert result.game.party[0].role == "Líbero"
    assert fake.write_calls == []  # NEW_LINEAR_HEAP nunca se intenta por RPC.
    assert host.closed is True


def test_alpha12_aborts_if_host_party_is_not_unique() -> None:
    saved = _saved_mon(1, 25, 0xABC10003, 100, 200, role="SIN ROL")
    start, memory = _memory_for_party(
        SM_PARTY_REFERENCE_ADDRESS,
        {1: _encrypted_pk7(species=25, pid=saved.pid, tid=saved.tid, sid=saved.sid)},
    )

    class WrongAliasRPC(AzaharAliasRPC):
        def read_memory(self, address: int, size: int) -> bytes:
            if 0x14000000 <= int(address) < 0x1C000000:
                self.read_calls.append((int(address), int(size)))
                return b"\xA5" * int(size)
            return super().read_memory(address, size)

    fake = WrongAliasRPC(start, memory, AzaharProcess(57, 0x0004000000164800, "niji_loc"), allow_writes=True)
    adapter = SMRealTimeAdapter(_reader(fake))
    adapter.writer.host_memory_factory = lambda: FakeWindowsHostMemory(fake, targets=2)
    snapshot = adapter.capture_full(_game(saved), save_path=None)
    change = PendingRoleChange(
        pokemon_slot=1, pokemon=saved.nickname, species=saved.species,
        old_role="SIN ROL", new_role="Mago",
        pokemon_identity=f"25:{saved.pid}:{saved.tid}:{saved.sid}",
    )
    with pytest.raises(SMLiveError, match="copias host indistinguibles"):
        adapter.apply_changes(snapshot.game, [change])
    assert fake.write_calls == []


def test_sm_gen7_pp_table_is_loaded_and_covers_pkhex_table() -> None:
    from app.sm_live import load_sm_move_pp

    table = load_sm_move_pp(DATA_DIR / "sm_move_pp.json")
    assert table[1] == 35
    assert table[45] == 40
    assert table[728] == 1
    assert len(table) == 728


class IgnoringWriteRPC(AzaharAliasRPC):
    """RPC que expone el alias correcto pero confirma sin mutar RAM."""

    def write_memory(self, address: int, contents: bytes):
        self.write_calls.append((int(address), bytes(contents)))
        if not self.allow_writes:
            raise AssertionError("este test no permite escrituras RAM")
        # Deliberadamente no muta ni siquiera el alias escribible.


def test_alpha11_failed_alias_write_generates_byte_level_diagnostic(tmp_path):
    saved = _saved_mon(1, 25, 0x11112222, 100, 200, role="SIN ROL")
    start, memory = _memory_for_party(
        SM_PARTY_REFERENCE_ADDRESS,
        {1: _encrypted_pk7(species=25, pid=saved.pid, tid=saved.tid, sid=saved.sid)},
    )
    fake = IgnoringWriteRPC(
        start, memory, AzaharProcess(77, 0x0004000000164800, "niji_loc"),
        allow_writes=True,
    )
    reader = _reader(fake)
    snapshot = reader.read(_game(saved))
    writer = SMLiveWriter(reader, diagnostic_dir=tmp_path, diagnostic_delays=(0.0,))
    change = PendingRoleChange(
        pokemon_slot=1, pokemon=saved.nickname, species=saved.species,
        old_role="SIN ROL", new_role="Mago",
        pokemon_identity=f"25:{saved.pid}:{saved.tid}:{saved.sid}",
    )

    with pytest.raises(SMLiveError, match="Diagnóstico guardado"):
        writer.apply(snapshot.game, [change])

    latest = writer.last_diagnostic_path
    assert latest is not None and latest.exists()
    import json
    payload = json.loads(latest.read_text(encoding="utf-8"))
    assert payload["format"] == "rolerun-sm-write-diagnostic-v2"
    assert payload["process"]["process_id"] == 77
    slot = payload["slots"]["1"]
    assert slot["planned_diff_offsets"]
    assert slot["immediate_readback"]["stored_matches_expected"] is False
    assert slot["immediate_readback"]["stored_matches_original"] is True
    assert slot["write_mode"] == "linear-heap-fcram-alias-validated"
    assert slot["write_address"] == "0x18195E10"


def test_alpha13_move_write_uses_validated_windows_fcram_when_rpc_alias_is_not_mapped() -> None:
    from app.models import PendingChange

    saved = _saved_mon(1, 25, 0xABC10013, 100, 200, role="SIN ROL")
    start, memory = _memory_for_party(
        SM_PARTY_REFERENCE_ADDRESS,
        {1: _encrypted_pk7(species=25, pid=saved.pid, tid=saved.tid, sid=saved.sid, moves=(33, 45, 0, 0))},
    )

    class WrongAliasRPC(AzaharAliasRPC):
        def read_memory(self, address: int, size: int) -> bytes:
            if 0x14000000 <= int(address) < 0x1C000000:
                self.read_calls.append((int(address), int(size)))
                return b"\xA5" * int(size)
            return super().read_memory(address, size)

    fake = WrongAliasRPC(
        start, memory, AzaharProcess(58, 0x0004000000164800, "niji_loc"), allow_writes=True,
    )
    adapter = SMRealTimeAdapter(
        _reader(fake), move_pp_for=lambda move_id: {55: 25}[int(move_id)],
        move_allowed=lambda move_id: int(move_id) == 55,
    )
    host = FakeWindowsHostMemory(fake)
    adapter.writer.host_memory_factory = lambda: host
    snapshot = adapter.capture_full(_game(saved), save_path=None)
    change = PendingChange(
        role="SIN ROL", pokemon_slot=1, pokemon=saved.nickname, species=saved.species,
        move_slot=1, old_move="Placaje", old_move_id=33,
        new_move="Pistola Agua", new_move_id=55,
        pokemon_identity=f"25:{saved.pid}:{saved.tid}:{saved.sid}",
    )
    result = adapter.apply_changes(snapshot.game, [change])
    assert result.game.party[0].move_ids == [55, 45, 0, 0]
    assert fake.write_calls == []
    assert host.closed is True


def test_alpha13_role_and_move_can_share_one_verified_transaction() -> None:
    from app.models import PendingChange

    saved = _saved_mon(1, 25, 0xABC10014, 100, 200, role="SIN ROL")
    start, memory = _memory_for_party(
        SM_PARTY_REFERENCE_ADDRESS,
        {1: _encrypted_pk7(species=25, pid=saved.pid, tid=saved.tid, sid=saved.sid, moves=(33, 45, 0, 0))},
    )
    fake = AzaharAliasRPC(
        start, memory, AzaharProcess(59, 0x0004000000164800, "niji_loc"), allow_writes=True,
    )
    adapter = SMRealTimeAdapter(
        _reader(fake), move_pp_for=lambda move_id: {55: 25}[int(move_id)],
        move_allowed=lambda move_id: int(move_id) == 55,
    )
    snapshot = adapter.capture_full(_game(saved), save_path=None)
    role = PendingRoleChange(
        pokemon_slot=1, pokemon=saved.nickname, species=saved.species,
        old_role="SIN ROL", new_role="Líbero",
        pokemon_identity=f"25:{saved.pid}:{saved.tid}:{saved.sid}",
    )
    move = PendingChange(
        role="Líbero", pokemon_slot=1, pokemon=saved.nickname, species=saved.species,
        move_slot=1, old_move="Placaje", old_move_id=33,
        new_move="Pistola Agua", new_move_id=55,
        pokemon_identity=f"25:{saved.pid}:{saved.tid}:{saved.sid}",
    )
    result = adapter.apply_changes(snapshot.game, [role, move])
    assert result.game.party[0].role == "Líbero"
    assert result.game.party[0].move_ids == [55, 45, 0, 0]


def test_alpha14_inventory_rare_candy_uses_pkhex_block_witness_and_host_fcram() -> None:
    saved = _saved_mon(1, 25, 0xABC11414, 100, 200, role="SIN ROL")
    start, party_memory = _memory_for_party(
        SM_PARTY_REFERENCE_ADDRESS,
        {1: _encrypted_pk7(species=25, pid=saved.pid, tid=saved.tid, sid=saved.sid)},
    )
    bag = bytearray(SM_SAVE_ITEM_BLOCK_SIZE)
    record_offset = 0xB48  # comienzo del bolsillo Medicine en SAV7SM
    original_word = 50 | (1 << 10)
    desired_word = 50 | (999 << 10)
    struct.pack_into("<I", bag, record_offset, original_word)
    desired = bytearray(bag)
    struct.pack_into("<I", desired, record_offset, desired_word)

    bag_guest = SM_PARTY_REFERENCE_ADDRESS + 0x3000
    end = max(start + len(party_memory), bag_guest + len(bag))
    memory = bytearray(end - start)
    memory[:len(party_memory)] = party_memory
    memory[bag_guest - start:bag_guest - start + len(bag)] = bag

    class WrongAliasRPC(AzaharAliasRPC):
        def read_memory(self, address: int, size: int) -> bytes:
            if 0x14000000 <= int(address) < 0x1C000000:
                self.read_calls.append((int(address), int(size)))
                return b"\xA5" * int(size)
            return super().read_memory(address, size)

    fake = WrongAliasRPC(start, memory, AzaharProcess(71, 0x0004000000164800, "niji_loc"), allow_writes=True)
    adapter = SMRealTimeAdapter(_reader(fake))
    host = FakeWindowsHostMemory(fake)
    adapter.writer.host_memory_factory = lambda: host
    snapshot = adapter.capture_full(_game(saved), save_path=None)
    change = PendingInventoryChange(
        "rare-candy", "Caramelo Raro", 999,
        save_inventory_witness=bytes(bag),
        desired_inventory_witness=bytes(desired),
    )
    result = adapter.apply_changes(snapshot.game, [change])
    assert result.applied_count == 1
    live_word = struct.unpack_from("<I", fake.memory, bag_guest - start + record_offset)[0]
    assert (live_word & 0x3FF) == 50
    assert ((live_word >> 10) & 0x3FF) == 999


def test_alpha14_inventory_aborts_if_saved_block_is_not_proven_in_live_fcram() -> None:
    saved = _saved_mon(1, 25, 0xABC11415, 100, 200, role="SIN ROL")
    start, memory = _memory_for_party(
        SM_PARTY_REFERENCE_ADDRESS,
        {1: _encrypted_pk7(species=25, pid=saved.pid, tid=saved.tid, sid=saved.sid)},
    )
    fake = AzaharAliasRPC(start, memory, AzaharProcess(72, 0x0004000000164800, "niji_loc"), allow_writes=True)
    adapter = SMRealTimeAdapter(_reader(fake))
    adapter.writer.host_memory_factory = lambda: FakeWindowsHostMemory(fake)
    snapshot = adapter.capture_full(_game(saved), save_path=None)
    original = bytearray(SM_SAVE_ITEM_BLOCK_SIZE)
    desired = bytearray(original)
    struct.pack_into("<I", desired, 0xB48, 50 | (999 << 10))
    change = PendingInventoryChange(
        "rare-candy", "Caramelo Raro", 999,
        save_inventory_witness=bytes(original), desired_inventory_witness=bytes(desired),
    )
    with pytest.raises(SMLiveError, match="no pudo demostrar una única copia viva"):
        adapter.apply_changes(snapshot.game, [change])


def test_alpha14_money_uses_pkhex_misc_witness_and_writes_only_money_field() -> None:
    from app.sm_live import SM_MAX_MONEY, SM_SAVE_MISC_BLOCK_SIZE, SM_MISC_MONEY_OFFSET

    saved = _saved_mon(1, 25, 0xABC11416, 100, 200, role="SIN ROL")
    start, party_memory = _memory_for_party(
        SM_PARTY_REFERENCE_ADDRESS,
        {1: _encrypted_pk7(species=25, pid=saved.pid, tid=saved.tid, sid=saved.sid)},
    )
    misc = bytearray((i * 37 + 11) & 0xFF for i in range(SM_SAVE_MISC_BLOCK_SIZE))
    struct.pack_into("<I", misc, SM_MISC_MONEY_OFFSET, 12345)
    desired = bytearray(misc)
    struct.pack_into("<I", desired, SM_MISC_MONEY_OFFSET, SM_MAX_MONEY)
    misc_guest = SM_PARTY_REFERENCE_ADDRESS + 0x5000
    end = max(start + len(party_memory), misc_guest + len(misc))
    memory = bytearray(end - start)
    memory[:len(party_memory)] = party_memory
    memory[misc_guest - start:misc_guest - start + len(misc)] = misc

    class WrongAliasRPC(AzaharAliasRPC):
        def read_memory(self, address: int, size: int) -> bytes:
            if 0x14000000 <= int(address) < 0x1C000000:
                self.read_calls.append((int(address), int(size)))
                return b"\xA5" * int(size)
            return super().read_memory(address, size)

    fake = WrongAliasRPC(start, memory, AzaharProcess(73, 0x0004000000164800, "niji_loc"), allow_writes=True)
    adapter = SMRealTimeAdapter(_reader(fake))
    host = FakeWindowsHostMemory(fake)
    adapter.writer.host_memory_factory = lambda: host
    snapshot = adapter.capture_full(_game(saved), save_path=None)
    change = PendingInventoryChange(
        "money-max", "Dinero", SM_MAX_MONEY,
        save_misc_witness=bytes(misc), desired_misc_witness=bytes(desired),
    )
    result = adapter.apply_changes(snapshot.game, [change])
    assert result.applied_count == 1
    live_money = struct.unpack_from("<I", fake.memory, misc_guest - start + SM_MISC_MONEY_OFFSET)[0]
    assert live_money == SM_MAX_MONEY


def test_alpha15_windows_structural_scanner_reads_anchor_region_once_per_chunk() -> None:
    from app.win_process_memory import WindowsProcessMemory

    region_base = 0x100000
    pattern = bytes((i * 29 + 17) & 0xFF for i in range(0x200))
    live = bytearray(pattern)
    for offset in range(0x50, 0x68):
        live[offset] ^= 0x44
    target_base = region_base + 0x3000
    memory = bytearray(b"\xCC" * 0x10000)
    memory[target_base - region_base:target_base - region_base + len(live)] = live

    scanner = object.__new__(WindowsProcessMemory)
    scanner.open_process = lambda _pid: 1
    scanner.close_process = lambda _handle: None
    scanner.iter_writable_regions = lambda _handle: [(region_base, len(memory))]
    reads = []
    def fake_read(_handle, address: int, size: int) -> bytes:
        reads.append((int(address), int(size)))
        start = int(address) - region_base
        return bytes(memory[start:start + int(size)])
    scanner.read = fake_read

    candidates, selected = scanner.find_structural_block_candidates_in_anchor_region(
        pid=1, anchor_address=region_base + 0x100, pattern=pattern,
        excluded_ranges=((4, 8),), window_size=16, windows_per_quartile=4,
    )
    assert selected
    assert candidates
    assert candidates[0][0] == target_base
    # La región cabe en un único chunk de 8 MiB: una sola lectura demuestra que
    # el scanner no relee FCRAM una vez por cada fragmento testigo.
    assert len(reads) == 1


def test_alpha15_money_structural_fallback_accepts_unique_live_misc_with_runtime_drift() -> None:
    from app.sm_live import SM_MAX_MONEY, SM_SAVE_MISC_BLOCK_SIZE, SM_MISC_MONEY_OFFSET

    saved = _saved_mon(1, 25, 0xABC11501, 100, 200, role="SIN ROL")
    start, party_memory = _memory_for_party(
        SM_PARTY_REFERENCE_ADDRESS,
        {1: _encrypted_pk7(species=25, pid=saved.pid, tid=saved.tid, sid=saved.sid)},
    )
    misc = bytearray((i * 37 + 11) & 0xFF for i in range(SM_SAVE_MISC_BLOCK_SIZE))
    struct.pack_into("<I", misc, SM_MISC_MONEY_OFFSET, 12345)
    desired = bytearray(misc)
    struct.pack_into("<I", desired, SM_MISC_MONEY_OFFSET, SM_MAX_MONEY)

    # Simula campos runtime ajenos a Money que ya no coinciden con el último main.
    live_misc = bytearray(misc)
    struct.pack_into("<I", live_misc, SM_MISC_MONEY_OFFSET, 54321)
    for offset in range(0x40, 0x60):
        live_misc[offset] ^= 0x5A
    for offset in range(0x120, 0x138):
        live_misc[offset] ^= 0x33

    misc_guest = SM_PARTY_REFERENCE_ADDRESS + 0x5000
    end = max(start + len(party_memory), misc_guest + len(live_misc))
    memory = bytearray(end - start)
    memory[:len(party_memory)] = party_memory
    memory[misc_guest - start:misc_guest - start + len(live_misc)] = live_misc

    class WrongAliasRPC(AzaharAliasRPC):
        def read_memory(self, address: int, size: int) -> bytes:
            if 0x14000000 <= int(address) < 0x1C000000:
                self.read_calls.append((int(address), int(size)))
                return b"\xA5" * int(size)
            return super().read_memory(address, size)

    fake = WrongAliasRPC(start, memory, AzaharProcess(74, 0x0004000000164800, "niji_loc"), allow_writes=True)
    adapter = SMRealTimeAdapter(_reader(fake))
    adapter.writer.host_memory_factory = lambda: FakeWindowsHostMemory(fake)
    snapshot = adapter.capture_full(_game(saved), save_path=None)
    change = PendingInventoryChange(
        "money-max", "Dinero", SM_MAX_MONEY,
        save_misc_witness=bytes(misc), desired_misc_witness=bytes(desired),
    )
    result = adapter.apply_changes(snapshot.game, [change])
    assert result.applied_count == 1
    live_money = struct.unpack_from("<I", fake.memory, misc_guest - start + SM_MISC_MONEY_OFFSET)[0]
    assert live_money == SM_MAX_MONEY


def test_alpha15_money_structural_fallback_rejects_two_equally_proven_misc_blocks() -> None:
    from app.sm_live import SM_MAX_MONEY, SM_SAVE_MISC_BLOCK_SIZE, SM_MISC_MONEY_OFFSET

    saved = _saved_mon(1, 25, 0xABC11503, 100, 200, role="SIN ROL")
    start, party_memory = _memory_for_party(
        SM_PARTY_REFERENCE_ADDRESS,
        {1: _encrypted_pk7(species=25, pid=saved.pid, tid=saved.tid, sid=saved.sid)},
    )
    misc = bytearray((i * 37 + 11) & 0xFF for i in range(SM_SAVE_MISC_BLOCK_SIZE))
    struct.pack_into("<I", misc, SM_MISC_MONEY_OFFSET, 12345)
    desired = bytearray(misc)
    struct.pack_into("<I", desired, SM_MISC_MONEY_OFFSET, SM_MAX_MONEY)
    live_misc = bytearray(misc)
    struct.pack_into("<I", live_misc, SM_MISC_MONEY_OFFSET, 54321)
    for offset in range(0x40, 0x58):
        live_misc[offset] ^= 0x5A

    first_guest = SM_PARTY_REFERENCE_ADDRESS + 0x5000
    second_guest = SM_PARTY_REFERENCE_ADDRESS + 0x7000
    end = max(start + len(party_memory), second_guest + len(live_misc))
    memory = bytearray(end - start)
    memory[:len(party_memory)] = party_memory
    for guest in (first_guest, second_guest):
        memory[guest - start:guest - start + len(live_misc)] = live_misc

    fake = AzaharAliasRPC(start, memory, AzaharProcess(76, 0x0004000000164800, "niji_loc"), allow_writes=True)
    adapter = SMRealTimeAdapter(_reader(fake))
    adapter.writer.host_memory_factory = lambda: FakeWindowsHostMemory(fake)
    snapshot = adapter.capture_full(_game(saved), save_path=None)
    change = PendingInventoryChange(
        "money-max", "Dinero", SM_MAX_MONEY,
        save_misc_witness=bytes(misc), desired_misc_witness=bytes(desired),
    )
    with pytest.raises(SMLiveError, match="2 estructuras Misc|igualmente demostrables"):
        adapter.apply_changes(snapshot.game, [change])


def test_alpha15_money_structural_fallback_rejects_weak_candidate() -> None:
    from app.sm_live import SM_MAX_MONEY, SM_SAVE_MISC_BLOCK_SIZE, SM_MISC_MONEY_OFFSET

    saved = _saved_mon(1, 25, 0xABC11502, 100, 200, role="SIN ROL")
    start, party_memory = _memory_for_party(
        SM_PARTY_REFERENCE_ADDRESS,
        {1: _encrypted_pk7(species=25, pid=saved.pid, tid=saved.tid, sid=saved.sid)},
    )
    misc = bytearray((i * 37 + 11) & 0xFF for i in range(SM_SAVE_MISC_BLOCK_SIZE))
    struct.pack_into("<I", misc, SM_MISC_MONEY_OFFSET, 12345)
    desired = bytearray(misc)
    struct.pack_into("<I", desired, SM_MISC_MONEY_OFFSET, SM_MAX_MONEY)

    # Conserva solo una zona pequeña: no alcanza los mínimos de prueba estructural.
    live_misc = bytearray(b"\xCC" * SM_SAVE_MISC_BLOCK_SIZE)
    live_misc[0x80:0xA0] = misc[0x80:0xA0]
    struct.pack_into("<I", live_misc, SM_MISC_MONEY_OFFSET, 54321)
    misc_guest = SM_PARTY_REFERENCE_ADDRESS + 0x5000
    end = max(start + len(party_memory), misc_guest + len(live_misc))
    memory = bytearray(end - start)
    memory[:len(party_memory)] = party_memory
    memory[misc_guest - start:misc_guest - start + len(live_misc)] = live_misc
    fake = AzaharAliasRPC(start, memory, AzaharProcess(75, 0x0004000000164800, "niji_loc"), allow_writes=True)
    adapter = SMRealTimeAdapter(_reader(fake))
    adapter.writer.host_memory_factory = lambda: FakeWindowsHostMemory(fake)
    snapshot = adapter.capture_full(_game(saved), save_path=None)
    change = PendingInventoryChange(
        "money-max", "Dinero", SM_MAX_MONEY,
        save_misc_witness=bytes(misc), desired_misc_witness=bytes(desired),
    )
    with pytest.raises(SMLiveError, match="no pudo demostrar|evidencia suficiente|fragmentos"):
        adapter.apply_changes(snapshot.game, [change])


def test_alpha14_max_repel_preview_must_resolve_exact_item_77_record() -> None:
    original = bytearray(SM_SAVE_ITEM_BLOCK_SIZE)
    desired = bytearray(original)
    # Bolsillo Items empieza en 0x000; una inserción PKHeX ocupa un registro de 4 bytes.
    struct.pack_into("<I", desired, 0x20, 77 | (999 << 10))
    change = PendingInventoryChange(
        "max-repel", "Repelente Máximo", 999,
        save_inventory_witness=bytes(original), desired_inventory_witness=bytes(desired),
    )
    kind, _orig, _desired, offset, _old_patch, new_patch = SMLiveWriter._inventory_patch(change)
    assert kind == "items"
    assert offset == 0x20
    word = struct.unpack("<I", new_patch)[0]
    assert (word & 0x3FF) == 77
    assert ((word >> 10) & 0x3FF) == 999


def _alpha16_live_bag_block(*, tm_item_id: int = 328, tm_count: int = 1) -> bytes:
    bag = bytearray(SM_SAVE_ITEM_BLOCK_SIZE)
    # Rellena registros no-MT con datos plausibles para que la estructura no sea
    # un gran bloque de ceros y pueda servir también como testigo distribuido.
    for index, offset in enumerate(range(0, min(0x300, SM_SAVE_ITEM_BLOCK_SIZE), 4), start=1):
        item_id = 1 + (index % 250)
        if item_id in {50, 77}:
            item_id += 2
        struct.pack_into("<I", bag, offset, item_id | ((1 + index % 20) << 10))
    struct.pack_into("<I", bag, 0x500, int(tm_item_id) | (int(tm_count) << 10))
    return bytes(bag)


def test_alpha16_reads_tm_inventory_from_proven_live_bag(tmp_path: Path) -> None:
    saved = _saved_mon(1, 25, 0xABC11601, 100, 200, role="SIN ROL")
    start, party_memory = _memory_for_party(
        SM_PARTY_REFERENCE_ADDRESS,
        {1: _encrypted_pk7(species=25, pid=saved.pid, tid=saved.tid, sid=saved.sid)},
    )
    bag = _alpha16_live_bag_block()
    bag_guest = SM_PARTY_REFERENCE_ADDRESS + 0x3000
    end = max(start + len(party_memory), bag_guest + len(bag))
    memory = bytearray(end - start)
    memory[:len(party_memory)] = party_memory
    memory[bag_guest - start:bag_guest - start + len(bag)] = bag
    fake = AzaharAliasRPC(start, memory, AzaharProcess(81, 0x0004000000164800, "niji_loc"), allow_writes=True)
    adapter = SMRealTimeAdapter(_reader(fake), move_pp_for=lambda _mid: 35, move_allowed=lambda _mid: True)
    adapter.writer.host_memory_factory = lambda: FakeWindowsHostMemory(fake)
    snapshot = adapter.capture_full(_game(saved), save_path=None)
    main = tmp_path / "main"
    main.write_bytes(bag)

    inventory, _process, _attempt = adapter.read_tm_inventory({}, save_path=main)
    assert inventory[328] == 1
    assert snapshot.game.party[0].move_ids[0] == 33


def test_alpha17_tm_inventory_uses_end_to_end_proof_when_party_host_is_duplicated(tmp_path: Path) -> None:
    saved = _saved_mon(1, 25, 0xABC11701, 100, 200, role="SIN ROL")
    start, party_memory = _memory_for_party(
        SM_PARTY_REFERENCE_ADDRESS,
        {1: _encrypted_pk7(species=25, pid=saved.pid, tid=saved.tid, sid=saved.sid)},
    )
    bag = _alpha16_live_bag_block()
    bag_guest = SM_PARTY_REFERENCE_ADDRESS + 0x3000
    end = max(start + len(party_memory), bag_guest + len(bag))
    memory = bytearray(end - start)
    memory[:len(party_memory)] = party_memory
    memory[bag_guest - start:bag_guest - start + len(bag)] = bag
    fake = AzaharAliasRPC(start, memory, AzaharProcess(84, 0x0004000000164800, "niji_loc"), allow_writes=True)
    adapter = SMRealTimeAdapter(_reader(fake), move_pp_for=lambda _mid: 35, move_allowed=lambda _mid: True)
    # La segunda party host es un duplicado/buffer que no conserva el mismo
    # desplazamiento hacia la mochila guest. Alpha.16 abortaba antes de probarlo.
    adapter.writer.host_memory_factory = lambda: FakeWindowsHostMemory(fake, targets=2)
    adapter.capture_full(_game(saved), save_path=None)
    main = tmp_path / "main"
    main.write_bytes(bag)

    inventory, _process, _attempt = adapter.read_tm_inventory({}, save_path=main)
    assert inventory[328] == 1
    assert adapter.writer._utility_block_cache["items"][2] == bag_guest


def test_alpha17_tm_inventory_still_aborts_if_two_complete_host_guest_routes_are_valid(tmp_path: Path) -> None:
    saved = _saved_mon(1, 25, 0xABC11702, 100, 200, role="SIN ROL")
    start, party_memory = _memory_for_party(
        SM_PARTY_REFERENCE_ADDRESS,
        {1: _encrypted_pk7(species=25, pid=saved.pid, tid=saved.tid, sid=saved.sid)},
    )
    bag = _alpha16_live_bag_block()
    bag_guest = SM_PARTY_REFERENCE_ADDRESS + 0x3000
    end = max(start + len(party_memory), bag_guest + len(bag))
    memory = bytearray(end - start)
    memory[:len(party_memory)] = party_memory
    memory[bag_guest - start:bag_guest - start + len(bag)] = bag
    fake = AzaharAliasRPC(start, memory, AzaharProcess(85, 0x0004000000164800, "niji_loc"), allow_writes=True)

    class TwoFullyValidProcesses(FakeWindowsHostMemory):
        def find_party_targets(self, **_kwargs):
            return [
                HostPartyTarget(999, "azahar.exe", self.host_base),
                HostPartyTarget(1000, "azaharplus.exe", self.host_base),
            ]

    adapter = SMRealTimeAdapter(_reader(fake), move_pp_for=lambda _mid: 35, move_allowed=lambda _mid: True)
    adapter.writer.host_memory_factory = lambda: TwoFullyValidProcesses(fake)
    adapter.capture_full(_game(saved), save_path=None)
    main = tmp_path / "main"
    main.write_bytes(bag)

    with pytest.raises(SMLiveError, match="2 rutas host→guest"):
        adapter.read_tm_inventory({}, save_path=main)


def test_alpha16_tm_teach_requires_live_tm_and_does_not_consume_it(tmp_path: Path) -> None:
    from app.models import PendingTMTeach

    saved = _saved_mon(1, 25, 0xABC11602, 100, 200, role="SIN ROL")
    start, party_memory = _memory_for_party(
        SM_PARTY_REFERENCE_ADDRESS,
        {1: _encrypted_pk7(species=25, pid=saved.pid, tid=saved.tid, sid=saved.sid)},
    )
    bag = _alpha16_live_bag_block()
    bag_guest = SM_PARTY_REFERENCE_ADDRESS + 0x3000
    end = max(start + len(party_memory), bag_guest + len(bag))
    memory = bytearray(end - start)
    memory[:len(party_memory)] = party_memory
    memory[bag_guest - start:bag_guest - start + len(bag)] = bag
    fake = AzaharAliasRPC(start, memory, AzaharProcess(82, 0x0004000000164800, "niji_loc"), allow_writes=True)
    adapter = SMRealTimeAdapter(_reader(fake), move_pp_for=lambda _mid: 35, move_allowed=lambda _mid: True)
    adapter.writer.host_memory_factory = lambda: FakeWindowsHostMemory(fake)
    snapshot = adapter.capture_full(_game(saved), save_path=None)
    main = tmp_path / "main"
    main.write_bytes(bag)
    adapter.read_tm_inventory({}, save_path=main)

    change = PendingTMTeach(
        role="SIN ROL", pokemon_slot=1, pokemon=saved.nickname, species=saved.species,
        move_slot=1, old_move="Placaje", old_move_id=33,
        new_move="Pistola Agua", new_move_id=55,
        pokemon_identity=f"25:{saved.pid}:{saved.tid}:{saved.sid}",
        item_id=328, tm_number=1, item_name="MT01", quantity_before=1,
    )
    result = adapter.apply_changes(snapshot.game, [change])
    assert result.game.party[0].move_ids[0] == 55
    live_bag = bytes(fake.memory[bag_guest - start:bag_guest - start + len(bag)])
    assert live_bag == bag


def test_alpha16_tm_teach_aborts_if_tm_disappeared_after_selector(tmp_path: Path) -> None:
    from app.models import PendingTMTeach

    saved = _saved_mon(1, 25, 0xABC11603, 100, 200, role="SIN ROL")
    start, party_memory = _memory_for_party(
        SM_PARTY_REFERENCE_ADDRESS,
        {1: _encrypted_pk7(species=25, pid=saved.pid, tid=saved.tid, sid=saved.sid)},
    )
    bag = _alpha16_live_bag_block()
    bag_guest = SM_PARTY_REFERENCE_ADDRESS + 0x3000
    end = max(start + len(party_memory), bag_guest + len(bag))
    memory = bytearray(end - start)
    memory[:len(party_memory)] = party_memory
    memory[bag_guest - start:bag_guest - start + len(bag)] = bag
    fake = AzaharAliasRPC(start, memory, AzaharProcess(83, 0x0004000000164800, "niji_loc"), allow_writes=True)
    adapter = SMRealTimeAdapter(_reader(fake), move_pp_for=lambda _mid: 35, move_allowed=lambda _mid: True)
    adapter.writer.host_memory_factory = lambda: FakeWindowsHostMemory(fake)
    snapshot = adapter.capture_full(_game(saved), save_path=None)
    main = tmp_path / "main"
    main.write_bytes(bag)
    adapter.read_tm_inventory({}, save_path=main)

    # Simula que la MT deja de estar disponible entre abrir el selector y pulsar enseñar.
    struct.pack_into("<I", fake.memory, bag_guest - start + 0x500, 0)
    change = PendingTMTeach(
        role="SIN ROL", pokemon_slot=1, pokemon=saved.nickname, species=saved.species,
        move_slot=1, old_move="Placaje", old_move_id=33,
        new_move="Pistola Agua", new_move_id=55,
        pokemon_identity=f"25:{saved.pid}:{saved.tid}:{saved.sid}",
        item_id=328, tm_number=1, item_name="MT01", quantity_before=1,
    )
    with pytest.raises(SMLiveError, match="ya no está en la mochila viva"):
        adapter.apply_changes(snapshot.game, [change])
    # El PK7 original sigue intacto.
    live = _reader(fake).read(_game(saved))
    assert live.game.party[0].move_ids[0] == 33


def test_alpha18_tm_inventory_reuses_proven_session_without_rescanning_fcram(tmp_path: Path) -> None:
    saved = _saved_mon(1, 25, 0xABC11801, 100, 200, role="SIN ROL")
    start, party_memory = _memory_for_party(
        SM_PARTY_REFERENCE_ADDRESS,
        {1: _encrypted_pk7(species=25, pid=saved.pid, tid=saved.tid, sid=saved.sid)},
    )
    bag = _alpha16_live_bag_block(tm_count=1)
    bag_guest = SM_PARTY_REFERENCE_ADDRESS + 0x3000
    end = max(start + len(party_memory), bag_guest + len(bag))
    memory = bytearray(end - start)
    memory[:len(party_memory)] = party_memory
    memory[bag_guest - start:bag_guest - start + len(bag)] = bag
    fake = AzaharAliasRPC(start, memory, AzaharProcess(86, 0x0004000000164800, "niji_loc"), allow_writes=True)

    class CountingHost(FakeWindowsHostMemory):
        def __init__(self, rpc):
            super().__init__(rpc)
            self.party_searches = 0
            self.exact_searches = 0
            self.structural_searches = 0

        def find_party_targets(self, **kwargs):
            self.party_searches += 1
            return super().find_party_targets(**kwargs)

        def find_exact_block_in_anchor_region(self, **kwargs):
            self.exact_searches += 1
            return super().find_exact_block_in_anchor_region(**kwargs)

        def find_structural_block_candidates_in_anchor_region(self, **kwargs):
            self.structural_searches += 1
            return super().find_structural_block_candidates_in_anchor_region(**kwargs)

    host = CountingHost(fake)
    adapter = SMRealTimeAdapter(_reader(fake), move_pp_for=lambda _mid: 35, move_allowed=lambda _mid: True)
    adapter.writer.host_memory_factory = lambda: host
    adapter.capture_full(_game(saved), save_path=None)
    main = tmp_path / "main"
    main.write_bytes(bag)

    first, _process, _attempt = adapter.read_tm_inventory({}, save_path=main)
    assert first[328] == 1
    first_party_searches = host.party_searches
    first_exact_searches = host.exact_searches
    first_structural_searches = host.structural_searches
    assert first_party_searches >= 1
    assert first_exact_searches + first_structural_searches >= 1

    # La mochila cambia legítimamente durante la misma sesión. El cache no
    # confía en los bytes antiguos: relee host+guest y acepta el nuevo contenido
    # solo si ambos lados siguen siendo idénticos en la dirección ya demostrada.
    struct.pack_into("<I", fake.memory, bag_guest - start + 0x500, 328 | (2 << 10))
    second, _process, _attempt = adapter.read_tm_inventory({}, save_path=main)
    assert second[328] == 2
    assert host.party_searches == first_party_searches
    assert host.exact_searches == first_exact_searches
    assert host.structural_searches == first_structural_searches


def test_alpha19_tm_teach_reuses_end_to_end_party_anchor_when_host_party_is_duplicated(tmp_path: Path) -> None:
    """La MT debe poder escribirse aunque Azahar conserve 3 parties idénticas.

    La ancla usada no se elige por orden: read_tm_inventory ya demostró cuál de
    las copies de party conduce a la mochila guest real. El writer la relee
    completa antes de tocar el PK7 y no vuelve a exigir unicidad global.
    """
    from app.models import PendingTMTeach

    saved = _saved_mon(1, 25, 0xABC11901, 100, 200, role="SIN ROL")
    start, party_memory = _memory_for_party(
        SM_PARTY_REFERENCE_ADDRESS,
        {1: _encrypted_pk7(species=25, pid=saved.pid, tid=saved.tid, sid=saved.sid)},
    )
    bag = _alpha16_live_bag_block()
    bag_guest = SM_PARTY_REFERENCE_ADDRESS + 0x3000
    end = max(start + len(party_memory), bag_guest + len(bag))
    memory = bytearray(end - start)
    memory[:len(party_memory)] = party_memory
    memory[bag_guest - start:bag_guest - start + len(bag)] = bag

    class WrongAliasRPC(AzaharAliasRPC):
        def read_memory(self, address: int, size: int) -> bytes:
            if 0x14000000 <= int(address) < 0x1C000000:
                self.read_calls.append((int(address), int(size)))
                return b"\xA5" * int(size)
            return super().read_memory(address, size)

    fake = WrongAliasRPC(
        start, memory, AzaharProcess(89, 0x0004000000164800, "niji_loc"), allow_writes=True,
    )

    class CountingDuplicatedHost(FakeWindowsHostMemory):
        def __init__(self, rpc):
            super().__init__(rpc, targets=3)
            self.party_searches = 0

        def find_party_targets(self, **kwargs):
            self.party_searches += 1
            return super().find_party_targets(**kwargs)

    host = CountingDuplicatedHost(fake)
    adapter = SMRealTimeAdapter(_reader(fake), move_pp_for=lambda _mid: 35, move_allowed=lambda _mid: True)
    adapter.writer.host_memory_factory = lambda: host
    snapshot = adapter.capture_full(_game(saved), save_path=None)
    main = tmp_path / "main"
    main.write_bytes(bag)

    inventory, _process, _attempt = adapter.read_tm_inventory({}, save_path=main)
    assert inventory[328] == 1
    assert host.party_searches == 1
    assert adapter.writer._tm_party_anchor is not None
    assert adapter.writer._tm_party_anchor[1].pid == 999

    change = PendingTMTeach(
        role="SIN ROL", pokemon_slot=1, pokemon=saved.nickname, species=saved.species,
        move_slot=1, old_move="Placaje", old_move_id=33,
        new_move="Pistola Agua", new_move_id=55,
        pokemon_identity=f"25:{saved.pid}:{saved.tid}:{saved.sid}",
        item_id=328, tm_number=1, item_name="MT01", quantity_before=1,
    )
    result = adapter.apply_changes(snapshot.game, [change])
    assert result.game.party[0].move_ids[0] == 55
    # No hubo un segundo escaneo global de parties durante la escritura.
    assert host.party_searches == 1
    # El alias RPC era falso, así que el cambio tuvo que entrar por host FCRAM.
    assert fake.write_calls == []
    live_bag = bytes(fake.memory[bag_guest - start:bag_guest - start + len(bag)])
    assert live_bag == bag


def test_alpha19_tm_party_anchor_aborts_if_the_proven_host_party_stops_matching(tmp_path: Path) -> None:
    from app.models import PendingTMTeach

    saved = _saved_mon(1, 25, 0xABC11902, 100, 200, role="SIN ROL")
    start, party_memory = _memory_for_party(
        SM_PARTY_REFERENCE_ADDRESS,
        {1: _encrypted_pk7(species=25, pid=saved.pid, tid=saved.tid, sid=saved.sid)},
    )
    bag = _alpha16_live_bag_block()
    bag_guest = SM_PARTY_REFERENCE_ADDRESS + 0x3000
    end = max(start + len(party_memory), bag_guest + len(bag))
    memory = bytearray(end - start)
    memory[:len(party_memory)] = party_memory
    memory[bag_guest - start:bag_guest - start + len(bag)] = bag
    fake = AzaharAliasRPC(start, memory, AzaharProcess(90, 0x0004000000164800, "niji_loc"), allow_writes=True)
    host = FakeWindowsHostMemory(fake, targets=3)
    adapter = SMRealTimeAdapter(_reader(fake), move_pp_for=lambda _mid: 35, move_allowed=lambda _mid: True)
    adapter.writer.host_memory_factory = lambda: host
    snapshot = adapter.capture_full(_game(saved), save_path=None)
    main = tmp_path / "main"
    main.write_bytes(bag)
    adapter.read_tm_inventory({}, save_path=main)

    # Conservamos mochila host+guest válida, pero corrompemos solo la ancla de
    # party host simulando que ese buffer dejó de representar la party viva.
    anchor = adapter.writer._tm_party_anchor
    assert anchor is not None
    original_read = host.read

    def corrupt_party_read(handle, address: int, size: int):
        if int(address) == int(anchor[1].host_party_base) and int(size) == PK7_STORED_SIZE:
            return b"\xEE" * int(size)
        return original_read(handle, address, size)

    host.read = corrupt_party_read
    change = PendingTMTeach(
        role="SIN ROL", pokemon_slot=1, pokemon=saved.nickname, species=saved.species,
        move_slot=1, old_move="Placaje", old_move_id=33,
        new_move="Pistola Agua", new_move_id=55,
        pokemon_identity=f"25:{saved.pid}:{saved.tid}:{saved.sid}",
        item_id=328, tm_number=1, item_name="MT01", quantity_before=1,
    )
    with pytest.raises(SMLiveError, match="party host ligada a la mochila"):
        adapter.writer._validated_tm_party_target(
            process=fake.process, party_base=SM_PARTY_REFERENCE_ADDRESS,
            original_capture=_reader(fake)._capture(snapshot.game, memory_blocks=None)[0] if False else [
                bytes(fake.memory[SM_PARTY_REFERENCE_ADDRESS - start + i * SM_PARTY_STRIDE:
                                  SM_PARTY_REFERENCE_ADDRESS - start + i * SM_PARTY_STRIDE + PK7_PARTY_SIZE])
                for i in range(6)
            ],
            host_memory=host,
        )


def test_alpha27_initial_calibration_accepts_party_shrink_without_resaving_main():
    saved = [
        _saved_mon(i, 20 + i, 0x10000000 + i, 100 + i, 200 + i)
        for i in range(1, 7)
    ]
    # El último estado conocido tiene 6 miembros. En el juego se deposita el 3º;
    # la party se compacta a cinco sin que el main se vuelva a guardar.
    remaining = [saved[0], saved[1], saved[3], saved[4], saved[5]]
    records = {
        index: _encrypted_pk7(
            species=mon.species_id, pid=mon.pid, tid=mon.tid, sid=mon.sid,
        )
        for index, mon in enumerate(remaining, start=1)
    }
    start, memory = _memory_for_party(SM_PARTY_REFERENCE_ADDRESS, records)
    fake = FakeRPC(start, memory, AzaharProcess(107, next(iter(SM_TITLE_IDS)), "niji_loc"))
    reader = _reader(fake)

    snapshot = reader.read(_game(*saved))

    assert snapshot.party_base == SM_PARTY_REFERENCE_ADDRESS
    assert [mon.pid for mon in snapshot.game.party] == [mon.pid for mon in remaining]
    assert reader.runtime_state()["last_resolution"]["continuity_proof"] == "party-shrank-known-subsequence"


def test_alpha27_initial_calibration_accepts_single_replacement_with_five_strong_witnesses():
    saved = [
        _saved_mon(i, 30 + i, 0x20000000 + i, 300 + i, 400 + i)
        for i in range(1, 7)
    ]
    incoming = _saved_mon(6, 133, 0x99887766, 777, 888)
    live = [*saved[:5], incoming]
    records = {
        index: _encrypted_pk7(
            species=mon.species_id, pid=mon.pid, tid=mon.tid, sid=mon.sid,
        )
        for index, mon in enumerate(live, start=1)
    }
    start, memory = _memory_for_party(SM_PARTY_REFERENCE_ADDRESS, records)
    fake = FakeRPC(start, memory, AzaharProcess(108, next(iter(SM_TITLE_IDS)), "niji_loc"))
    reader = _reader(fake)

    snapshot = reader.read(_game(*saved))

    assert [mon.pid for mon in snapshot.game.party] == [mon.pid for mon in live]
    assert reader.runtime_state()["last_resolution"]["continuity_proof"] == "single-replacement-known-members"


def test_alpha27_initial_calibration_rejects_unrelated_structurally_valid_party():
    saved = [
        _saved_mon(i, 40 + i, 0x30000000 + i, 500 + i, 600 + i)
        for i in range(1, 7)
    ]
    unrelated = [
        _saved_mon(i, 100 + i, 0x40000000 + i, 700 + i, 800 + i)
        for i in range(1, 7)
    ]
    records = {
        index: _encrypted_pk7(
            species=mon.species_id, pid=mon.pid, tid=mon.tid, sid=mon.sid,
        )
        for index, mon in enumerate(unrelated, start=1)
    }
    start, memory = _memory_for_party(SM_PARTY_REFERENCE_ADDRESS, records)
    fake = FakeRPC(start, memory, AzaharProcess(109, next(iter(SM_TITLE_IDS)), "niji_loc"))

    with pytest.raises(SMLiveError, match="vincularse por identidades fuertes"):
        _reader(fake).read(_game(*saved))


def test_alpha27_pc_proven_party_anchor_disambiguates_duplicate_host_buffers_for_role_write() -> None:
    saved = _saved_mon(1, 25, 0xABC12701, 100, 200, role="SIN ROL")
    start, memory = _memory_for_party(
        SM_PARTY_REFERENCE_ADDRESS,
        {1: _encrypted_pk7(species=25, pid=saved.pid, tid=saved.tid, sid=saved.sid)},
    )

    class WrongAliasRPC(AzaharAliasRPC):
        def read_memory(self, address: int, size: int) -> bytes:
            if 0x14000000 <= int(address) < 0x1C000000:
                self.read_calls.append((int(address), int(size)))
                return b"\xA5" * int(size)
            return super().read_memory(address, size)

    fake = WrongAliasRPC(
        start, memory, AzaharProcess(127, 0x0004000000164800, "niji_loc"), allow_writes=True,
    )
    adapter = SMRealTimeAdapter(_reader(fake))
    host = FakeWindowsHostMemory(fake, targets=2)
    adapter.writer.host_memory_factory = lambda: host
    snapshot = adapter.capture_full(_game(saved), save_path=None)

    session = (
        int(fake.process.title_id), int(fake.process.process_id), str(fake.process.name),
        int(SM_PARTY_REFERENCE_ADDRESS),
    )
    adapter.writer._pc_party_anchor = (
        session, HostPartyTarget(999, "azahar.exe", host.host_base),
    )
    change = PendingRoleChange(
        pokemon_slot=1, pokemon=saved.nickname, species=saved.species,
        old_role="SIN ROL", new_role="Mago",
        pokemon_identity=f"25:{saved.pid}:{saved.tid}:{saved.sid}",
    )

    result = adapter.apply_changes(snapshot.game, [change])

    assert result.game.party[0].role == "Mago"
    assert fake.write_calls == []


def test_alpha27_nearby_scan_prefers_shrink_candidate_with_most_strong_identities() -> None:
    saved = [
        _saved_mon(i, 60 + i, 0x50000000 + i, 900 + i, 1000 + i)
        for i in range(1, 7)
    ]
    remaining = [saved[0], saved[1], saved[3], saved[4], saved[5]]
    moved_base = SM_PARTY_REFERENCE_ADDRESS + 0x23
    records = {
        index: _encrypted_pk7(
            species=mon.species_id, pid=mon.pid, tid=mon.tid, sid=mon.sid,
        )
        for index, mon in enumerate(remaining, start=1)
    }
    start, memory = _memory_for_party(moved_base, records)
    fake = FakeRPC(start, memory, AzaharProcess(110, next(iter(SM_TITLE_IDS)), "niji_loc"))
    reader = _reader(fake)

    snapshot = reader.read(_game(*saved))

    assert snapshot.party_base == moved_base
    assert [mon.pid for mon in snapshot.game.party] == [mon.pid for mon in remaining]


def test_alpha29_pc_cache_translation_rederives_current_party_target_without_stale_anchor() -> None:
    from app.sm_live import PK7_PARTY_SIZE

    saved = _saved_mon(1, 165, 0xABC12901, 100, 200, role="SIN ROL")
    raw = _encrypted_pk7(species=165, pid=saved.pid, tid=saved.tid, sid=saved.sid)
    assert len(raw) == PK7_PARTY_SIZE

    guest_party = 0x34195E10
    guest_pc = 0x330D9838
    host_pc = 0x000001A010000000
    host_party = host_pc + (guest_party - guest_pc)
    host_pid = 4242
    matrix = bytes(0xE8)  # una matriz 1x1 vacía basta para revalidar la traducción

    class Client:
        def read_memory(self, address: int, size: int) -> bytes:
            if int(address) == guest_pc and int(size) == len(matrix):
                return matrix
            raise AssertionError((hex(int(address)), int(size)))

    class Host:
        def open_process(self, pid: int):
            assert int(pid) == host_pid
            return pid

        def close_process(self, _handle):
            pass

        def read(self, _handle, address: int, size: int) -> bytes:
            address = int(address)
            size = int(size)
            if address == host_pc and size == len(matrix):
                return matrix
            if address == host_party and size == PK7_STORED_SIZE:
                return raw[:PK7_STORED_SIZE]
            if address == host_party + SM_PARTY_STATS_OFFSET and size == SM_PARTY_STATS_SIZE:
                return raw[PK7_STORED_SIZE:PK7_STORED_SIZE + SM_PARTY_STATS_SIZE]
            raise AssertionError((hex(address), size))

    fake_process = AzaharProcess(129, 0x0004000000164800, "niji_loc")
    adapter = SMRealTimeAdapter(_reader(FakeRPC(*_memory_for_party(guest_party, {1: raw}), fake_process)))
    session = (int(fake_process.title_id), int(fake_process.process_id), str(fake_process.name), guest_party)
    adapter.writer._pc_party_anchor = None
    adapter.writer._pc_live_cache = (session, host_pid, host_pc, guest_pc, 1, 1)

    target = adapter.writer._validated_pc_party_target(
        client=Client(), process=fake_process, party_base=guest_party,
        original_capture=[raw], host_memory=Host(),
    )
    assert target.pid == host_pid
    assert target.host_party_base == host_party
    assert adapter.writer._pc_party_anchor is not None
    assert adapter.writer._pc_party_anchor[1].host_party_base == host_party
