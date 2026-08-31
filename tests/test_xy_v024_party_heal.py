from __future__ import annotations

import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.azahar_rpc import AzaharProcess
from app.models import PendingPartyHeal, PendingRoleChange, PendingTeamChange, PendingTMTeach
from app.oras_live import (
    ORASLiveError,
    PK6_PARTY_SIZE,
    PK6_STORED_SIZE,
    _plain_pk6,
    encrypt_pk6,
    parse_pk6_boxed,
    parse_pk6_party,
)
from app.save_engine_client import SaveGameData, SavePokemon
from app.oras_tm_service import ORASPersonalStats, oras_tm_item_id
from app.ui import RoleRunManager
from app.win_process_memory import HostPartyTarget
from app.xy_live import (
    XYLiveError,
    XYLiveReader,
    XYLiveWriter,
    XY_PARTY_ADDRESS,
    XY_PARTY_COUNT_ADDRESS,
    XY_PARTY_STATS_OFFSET,
    XY_PARTY_STATS_SIZE,
    XY_PARTY_STRIDE,
    XY_PARTY_SPAN,
    XY_PARTY_RUNTIME_SPAN,
    XY_PC_KNOWN_ADDRESS,
    XY_PC_SIZE,
)


def _encrypted_party_member(
    *, current_hp: int = 7, max_hp: int = 47, status: int = 0x40,
) -> bytes:
    data = bytearray(PK6_PARTY_SIZE)
    struct.pack_into("<I", data, 0, 0x12345678)
    struct.pack_into("<H", data, 8, 261)
    struct.pack_into("<H", data, 0x0C, 12345)
    struct.pack_into("<H", data, 0x0E, 54321)
    data[0x14] = 50
    struct.pack_into("<I", data, 0x18, 0x89ABCDEF)
    nickname = "Poochyena".encode("utf-16le")
    data[0x40:0x40 + len(nickname)] = nickname
    struct.pack_into("<4H", data, 0x5A, 33, 44, 0, 0)
    data[0x62:0x66] = bytes((1, 2, 0, 0))
    data[0x66:0x6A] = bytes((1, 2, 0, 0))
    struct.pack_into("<I", data, 0x74, 0x001FFFFF)
    struct.pack_into("<I", data, 0xE8, int(status))
    data[0xEC] = 18
    struct.pack_into("<H", data, 0xF0, int(current_hp))
    struct.pack_into("<6H", data, 0xF2, int(max_hp), 31, 29, 27, 25, 23)
    checksum = sum(struct.unpack_from("<112H", data, 8)) & 0xFFFF
    struct.pack_into("<H", data, 6, checksum)
    return encrypt_pk6(bytes(data))


_POOCHYENA_PERSONAL = ORASPersonalStats(
    base_stats=(35, 55, 35, 35, 30, 30),
    exp_growth=0,
)


def _coherent_role_member(
    *,
    role: str = "Líbero",
    canonical_evs: tuple[int, int, int, int, int, int] = (4, 8, 12, 20, 24, 16),
    missing_hp: int = 5,
    status: int = 0x40,
    pid: int = 0x12345678,
    nickname: str = "Poochyena",
) -> bytes:
    data = bytearray(PK6_PARTY_SIZE)
    struct.pack_into("<I", data, 0, 0x12345678)
    struct.pack_into("<H", data, 8, 261)
    struct.pack_into("<H", data, 0x0C, 12345)
    struct.pack_into("<H", data, 0x0E, 54321)
    struct.pack_into("<I", data, 0x10, 18 ** 3)
    data[0x14] = 50
    # La identidad estable que usa el writer incluye el PID de 0x18. Mantener
    # este campo fijo hacía que todos los miembros del fixture pareciesen el
    # mismo Pokémon y el propio validador rechazase correctamente el cambio.
    struct.pack_into("<I", data, 0x18, int(pid))
    data[0x1C] = 0
    native_evs = (
        canonical_evs[0], canonical_evs[1], canonical_evs[2],
        canonical_evs[5], canonical_evs[3], canonical_evs[4],
    )
    data[0x1E:0x24] = bytes(native_evs)
    encoded_nickname = str(nickname).encode("utf-16le")
    data[0x40:0x40 + len(encoded_nickname)] = encoded_nickname
    struct.pack_into("<4H", data, 0x5A, 33, 44, 0, 0)
    data[0x62:0x66] = bytes((35, 25, 0, 0))
    struct.pack_into("<I", data, 0x74, sum(20 << (5 * index) for index in range(6)))
    XYLiveWriter._set_role(data, role)
    extension = XYLiveWriter._party_extension(bytes(data[:PK6_STORED_SIZE]), _POOCHYENA_PERSONAL)
    data[PK6_STORED_SIZE:] = extension
    maximum_hp = int(struct.unpack_from("<H", data, 0xF2)[0])
    struct.pack_into("<I", data, 0xE8, int(status))
    struct.pack_into("<H", data, 0xF0, maximum_hp - int(missing_hp))
    checksum = sum(struct.unpack_from("<112H", data, 8)) & 0xFFFF
    struct.pack_into("<H", data, 6, checksum)
    return encrypt_pk6(bytes(data))


class _XYPartyClient:
    def __init__(
        self,
        first_slot: bytes,
        *,
        corrupt_first_stats_write: bool = False,
        corrupt_first_stored_write: bool = False,
        party_slots: list[bytes] | None = None,
        party_count: int | None = None,
        corrupt_first_count_write: bool = False,
    ) -> None:
        supplied = list(party_slots or [first_slot])
        self.slots = []
        for index, raw in enumerate(supplied[:6]):
            runtime = bytearray([0x40 + index] * XY_PARTY_STRIDE)
            runtime[:PK6_STORED_SIZE] = raw[:PK6_STORED_SIZE]
            runtime[XY_PARTY_STATS_OFFSET:XY_PARTY_STATS_OFFSET + XY_PARTY_STATS_SIZE] = (
                raw[PK6_STORED_SIZE:PK6_STORED_SIZE + XY_PARTY_STATS_SIZE]
            )
            self.slots.append(runtime)
        for index in range(len(self.slots), 6):
            runtime = bytearray([0x70 + index] * XY_PARTY_STRIDE)
            runtime[:PK6_STORED_SIZE] = encrypt_pk6(bytes(PK6_PARTY_SIZE))[:PK6_STORED_SIZE]
            runtime[XY_PARTY_STATS_OFFSET:XY_PARTY_STATS_OFFSET + XY_PARTY_STATS_SIZE] = bytes(
                XY_PARTY_STATS_SIZE
            )
            self.slots.append(runtime)
        self.party_count = int(party_count if party_count is not None else len(supplied))
        self.selected = 0
        self.corrupt_first_stats_write = bool(corrupt_first_stats_write)
        self.corrupt_first_stored_write = bool(corrupt_first_stored_write)
        self.corrupt_first_count_write = bool(corrupt_first_count_write)
        self.writes: list[tuple[int, bytes]] = []
        self.full_span_reads = 0
        self.restore_runtime_on_span_read: int | None = None
        self.restore_runtime_snapshot: tuple[tuple[bytes, ...], int] | None = None

    def arm_runtime_restore(self, read_number: int) -> None:
        self.restore_runtime_on_span_read = int(read_number)
        self.restore_runtime_snapshot = (
            tuple(bytes(slot) for slot in self.slots),
            int(self.party_count),
        )

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def process_list(self):
        return [AzaharProcess(77, 0x0004000000055D00, "kujira-1")]

    def set_process(self, process_id: int):
        self.selected = int(process_id)

    @staticmethod
    def _position(address: int) -> tuple[int, int]:
        index = (int(address) - XY_PARTY_ADDRESS) // XY_PARTY_STRIDE
        relative = int(address) - (XY_PARTY_ADDRESS + index * XY_PARTY_STRIDE)
        if not 0 <= index < 6:
            raise AssertionError(f"Dirección X/Y fuera de la party: 0x{address:08X}")
        return index, relative

    def read_memory(self, address: int, size: int):
        if int(address) == XY_PARTY_COUNT_ADDRESS and int(size) == 4:
            return struct.pack("<I", self.party_count)
        if int(address) == XY_PARTY_ADDRESS and int(size) == XY_PARTY_RUNTIME_SPAN:
            self.full_span_reads += 1
            if (
                self.restore_runtime_on_span_read == self.full_span_reads
                and self.restore_runtime_snapshot is not None
            ):
                slots, count = self.restore_runtime_snapshot
                self.slots = [bytearray(slot) for slot in slots]
                self.party_count = int(count)
            return b"".join(bytes(slot) for slot in self.slots)
        index, relative = self._position(address)
        if relative == 0 and size == PK6_STORED_SIZE:
            return bytes(self.slots[index][:PK6_STORED_SIZE])
        if relative == XY_PARTY_STATS_OFFSET and size == XY_PARTY_STATS_SIZE:
            return bytes(self.slots[index][relative:relative + XY_PARTY_STATS_SIZE])
        if relative == 0 and size == XY_PARTY_STRIDE:
            return bytes(self.slots[index])
        raise AssertionError(f"Lectura X/Y inesperada: +0x{relative:X}, {size} bytes")

    def write_memory(self, address: int, data: bytes):
        payload = bytes(data)
        if int(address) == XY_PARTY_COUNT_ADDRESS and len(payload) == 4:
            self.writes.append((int(address), payload))
            value = int(struct.unpack("<I", payload)[0])
            if self.corrupt_first_count_write:
                self.corrupt_first_count_write = False
                value = max(1, value - 1)
            self.party_count = value
            return
        index, relative = self._position(address)
        if relative == 0 and len(payload) == PK6_STORED_SIZE:
            self.writes.append((int(address), payload))
            if self.corrupt_first_stored_write:
                self.corrupt_first_stored_write = False
                payload = bytes((payload[0] ^ 1,)) + payload[1:]
            self.slots[index][:PK6_STORED_SIZE] = payload
            return
        if relative == XY_PARTY_STATS_OFFSET and len(payload) == XY_PARTY_STATS_SIZE:
            self.writes.append((int(address), payload))
            if self.corrupt_first_stats_write:
                self.corrupt_first_stats_write = False
                payload = bytes((payload[0] ^ 1,)) + payload[1:]
            self.slots[index][relative:relative + XY_PARTY_STATS_SIZE] = payload
            return
        if relative == 0 and len(payload) == XY_PARTY_STRIDE:
            self.writes.append((int(address), payload))
            self.slots[index][:] = payload
            return
        raise AssertionError(f"Escritura X/Y inesperada: +0x{relative:X}, {len(payload)} bytes")


def _logical_party_slot(client: _XYPartyClient, index: int) -> bytes:
    runtime = client.slots[index]
    return bytes(
        runtime[:PK6_STORED_SIZE]
        + runtime[XY_PARTY_STATS_OFFSET:XY_PARTY_STATS_OFFSET + XY_PARTY_STATS_SIZE]
        + bytes(PK6_PARTY_SIZE - PK6_STORED_SIZE - XY_PARTY_STATS_SIZE)
    )


class _XYPartyPCClient(_XYPartyClient):
    def __init__(
        self,
        first_slot: bytes,
        pc: bytes,
        *,
        corrupt_source_empty_at: int | None = None,
        party_slots: list[bytes] | None = None,
        party_count: int | None = None,
        corrupt_first_count_write: bool = False,
    ) -> None:
        super().__init__(
            first_slot,
            party_slots=party_slots,
            party_count=party_count,
            corrupt_first_count_write=corrupt_first_count_write,
        )
        self.pc = bytearray(pc)
        self.corrupt_source_empty_at = corrupt_source_empty_at
        self.pc_reads_after_last_write = 0
        self.restore_pc_on_read_after_write: int | None = None
        self.restore_pc_snapshot: bytes | None = None
        self.pc_write_seen = False

    def arm_pc_restore_after_write(self, read_number: int) -> None:
        self.restore_pc_on_read_after_write = int(read_number)
        self.restore_pc_snapshot = bytes(self.pc)
        self.pc_write_seen = False

    def read_memory(self, address: int, size: int):
        relative = int(address) - XY_PC_KNOWN_ADDRESS
        if 0 <= relative and relative + int(size) <= len(self.pc):
            if self.restore_pc_on_read_after_write is not None and self.pc_write_seen:
                self.pc_reads_after_last_write += 1
                if self.pc_reads_after_last_write == self.restore_pc_on_read_after_write:
                    assert self.restore_pc_snapshot is not None
                    self.pc[:] = self.restore_pc_snapshot
                    self.restore_pc_on_read_after_write = None
            return bytes(self.pc[relative:relative + int(size)])
        return super().read_memory(address, size)

    def write_memory(self, address: int, data: bytes):
        relative = int(address) - XY_PC_KNOWN_ADDRESS
        payload = bytes(data)
        if 0 <= relative and relative + len(payload) <= len(self.pc):
            self.pc_reads_after_last_write = 0
            self.pc_write_seen = True
            if self.corrupt_source_empty_at == int(address) and payload == _EMPTY_XY_PC_SLOT:
                self.corrupt_source_empty_at = None
                payload = bytes((1,)) + payload[1:]
            self.pc[relative:relative + len(payload)] = payload
            return
        return super().write_memory(address, payload)


class _XYHostMemory:
    """Memoria anfitriona coherente con el fake RPC, pero con transporte propio."""

    delta = 0x100000000

    def __init__(self, client: _XYPartyPCClient) -> None:
        self.client = client
        self.writes: list[tuple[int, bytes]] = []
        self.closed = False

    def find_party_targets(self, **_kwargs):
        return [HostPartyTarget(991, "azahar.exe", XY_PARTY_ADDRESS + self.delta)]

    @staticmethod
    def open_process(pid: int):
        assert int(pid) == 991
        return object()

    def close_process(self, _handle) -> None:
        self.closed = True

    def read(self, _handle, address: int, size: int) -> bytes:
        guest_address = int(address) - self.delta
        if guest_address == XY_PARTY_ADDRESS and int(size) == XY_PARTY_RUNTIME_SPAN:
            return b"".join(bytes(slot) for slot in self.client.slots)
        if guest_address == XY_PARTY_COUNT_ADDRESS and int(size) == 4:
            return struct.pack("<I", self.client.party_count)
        relative = guest_address - XY_PC_KNOWN_ADDRESS
        if 0 <= relative and relative + int(size) <= len(self.client.pc):
            return bytes(self.client.pc[relative:relative + int(size)])
        return bytes(self.client.read_memory(guest_address, int(size)))

    def write(self, _handle, address: int, payload: bytes) -> None:
        guest_address = int(address) - self.delta
        data = bytes(payload)
        self.writes.append((guest_address, data))
        self.client.write_memory(guest_address, data)


# Captura anonimizada de un slot PC vacío válido de Pokémon X v1.5. Solo se
# usa como fixture; producción deriva la plantilla repetida de la matriz viva.
_EMPTY_XY_PC_SLOT = bytes.fromhex(
    "0000000000003a0900007ee97152b031428ecce2c5afdb6733fc2cef5efcc5ca"
    "d6eb3d99bc7aa7cbd65d7891a6278d619216b8cf5d3780307c40fb481332e7fe"
    "ebdf1c3dfb635f1de2ea9662689297a3491c036eaa3189aac5d3eac3d982c6e0"
    "5c943b4e5f5a2824b3fbe1bf8e7b7f00c44048c8d1bfb6383b9023fb237d34b"
    "e00da6a70c5df84ba14e4a1602b2b388fa0b66041361609f04bb50e26a8b643"
    "7bcbf9ef68d4af5f74bec361e09598f184ba11622480ccc4a7a2b755a85c1c42"
    "a23a8605add21119b0fd57e94e60ba1b452e17a934932d66092d11e0a17442c4"
    "733a2b21f5432854a6"
)


def _pc_move_setup(*, occupied_destination: bool = False, corrupt_source: bool = False):
    party_raw = _coherent_role_member()
    pc = bytearray(_EMPTY_XY_PC_SLOT * (XY_PC_SIZE // PK6_STORED_SIZE))
    source_box, source_slot = 4, 1
    destination_box, destination_slot = 3, 5
    source_index = (source_box - 1) * 30 + source_slot - 1
    destination_index = (destination_box - 1) * 30 + destination_slot - 1
    source_address = XY_PC_KNOWN_ADDRESS + source_index * PK6_STORED_SIZE
    destination_address = XY_PC_KNOWN_ADDRESS + destination_index * PK6_STORED_SIZE
    source_raw = party_raw[:PK6_STORED_SIZE]
    pc[source_index * PK6_STORED_SIZE:(source_index + 1) * PK6_STORED_SIZE] = source_raw
    if occupied_destination:
        pc[destination_index * PK6_STORED_SIZE:(destination_index + 1) * PK6_STORED_SIZE] = source_raw
    client = _XYPartyPCClient(
        party_raw,
        pc,
        corrupt_source_empty_at=source_address if corrupt_source else None,
    )
    reader = XYLiveReader(
        Path("missing.json"), client_factory=lambda: client, stable_delay=0, snapshot_attempts=2,
    )
    writer = XYLiveWriter(reader, move_pp_for=lambda _move_id: 35)
    party = parse_pk6_party(party_raw, 1, reader.move_names)
    source = parse_pk6_boxed(source_raw, source_box, source_slot, reader.move_names)
    assert party is not None and source is not None
    game = SaveGameData("X", "SAV6XY", 6, "Timper", [party], {})
    change = PendingTeamChange(
        operation="move-box-slot",
        party_slot=0,
        box=source_box,
        box_slot=source_slot,
        destination_box=destination_box,
        destination_box_slot=destination_slot,
        incoming_pokemon=source.nickname,
        incoming_species=source.species,
        incoming_identity=writer._pokemon_identity(source),
    )
    return writer, client, game, change, source_address, destination_address, source_raw


def _writer_and_game(client: _XYPartyClient):
    reader = XYLiveReader(
        Path("missing.json"), client_factory=lambda: client, stable_delay=0, snapshot_attempts=2,
    )
    writer = XYLiveWriter(reader, move_pp_for=lambda move_id: {33: 35, 44: 25}.get(int(move_id), 0))
    captured = reader._read_party(client)
    pokemon = parse_pk6_party(captured[0], 1, reader.move_names)
    assert pokemon is not None
    game = SaveGameData("X", "SAV6XY", 6, "Timper", [pokemon], {})
    change = PendingPartyHeal(
        pokemon_slot=1,
        pokemon=pokemon.nickname,
        species=pokemon.species,
        pokemon_identity=writer._pokemon_identity(pokemon),
    )
    return writer, game, change


def _tm_writer_and_game(client: _XYPartyClient):
    reader = XYLiveReader(
        Path("missing.json"), client_factory=lambda: client, stable_delay=0, snapshot_attempts=2,
    )
    host_memory = _XYHostMemory(client)
    client.host_memory = host_memory
    writer = XYLiveWriter(
        reader,
        move_pp_for=lambda move_id: {33: 35, 44: 25, 611: 20}.get(int(move_id), 0),
    )
    captured = reader._read_party(client)
    pokemon = parse_pk6_party(captured[0], 1, reader.move_names)
    assert pokemon is not None
    game = SaveGameData("X", "SAV6XY", 6, "Timper", [pokemon], {})
    item_id = oras_tm_item_id(83)
    assert item_id is not None
    change = PendingTMTeach(
        role=pokemon.role,
        pokemon_slot=1,
        pokemon=pokemon.nickname,
        species=pokemon.species,
        move_slot=3,
        old_move="—",
        old_move_id=0,
        new_move="Acoso",
        new_move_id=611,
        pokemon_identity=writer._pokemon_identity(pokemon),
        item_id=item_id,
        tm_number=83,
        item_name="MT83",
        quantity_before=1,
        inventory_witnesses=(),
    )
    return writer, game, change


def _role_writer_and_game(client: _XYPartyClient):
    reader = XYLiveReader(
        Path("missing.json"), client_factory=lambda: client, stable_delay=0, snapshot_attempts=2,
    )
    writer = XYLiveWriter(
        reader,
        move_pp_for=lambda move_id: {33: 35, 44: 25}.get(int(move_id), 0),
        personal_for=lambda species, form: (
            _POOCHYENA_PERSONAL if (int(species), int(form)) == (261, 0) else None
        ),
    )
    captured = reader._read_party(client)
    pokemon = parse_pk6_party(captured[0], 1, reader.move_names)
    assert pokemon is not None
    game = SaveGameData("X", "SAV6XY", 6, "Timper", [pokemon], {})
    desired = (0, 252, 0, 0, 0, 252)
    change = PendingRoleChange(
        pokemon_slot=1,
        pokemon=pokemon.nickname,
        species=pokemon.species,
        old_role=pokemon.role,
        new_role="Asesino",
        pokemon_identity=writer._pokemon_identity(pokemon),
        old_evs=tuple(int(pokemon.evs.get(key, 0)) for key in (
            "hp", "attack", "defense", "sp_attack", "sp_defense", "speed",
        )),
        new_evs=desired,
    )
    return writer, game, change


def test_xy_party_heal_restores_hp_status_and_pp_with_split_runtime_write() -> None:
    client = _XYPartyClient(_encrypted_party_member())
    writer, game, change = _writer_and_game(client)

    result = writer.apply(game, [change])

    healed = result.game.party[0]
    assert (healed.current_hp, healed.max_hp) == (47, 47)
    assert healed.status_condition == 0
    plain, _encrypted = _plain_pk6(_logical_party_slot(client, 0))
    assert tuple(plain[0x62:0x66]) == (42, 35, 0, 0)
    assert result.applied_count == 1


def test_xy_party_heal_rolls_back_both_regions_when_readback_diverges() -> None:
    original = _encrypted_party_member()
    client = _XYPartyClient(original, corrupt_first_stats_write=True)
    writer, game, change = _writer_and_game(client)

    with pytest.raises(XYLiveError, match="restauró y verificó"):
        writer.apply(game, [change])

    assert bytes(client.slots[0][:PK6_STORED_SIZE]) == original[:PK6_STORED_SIZE]
    assert bytes(client.slots[0][XY_PARTY_STATS_OFFSET:XY_PARTY_STATS_OFFSET + XY_PARTY_STATS_SIZE]) == (
        original[PK6_STORED_SIZE:PK6_STORED_SIZE + XY_PARTY_STATS_SIZE]
    )


def test_xy_teaches_reusable_tm_without_reading_or_writing_the_bag() -> None:
    client = _XYPartyClient(_coherent_role_member())
    writer, game, change = _tm_writer_and_game(client)

    result = writer.apply(game, [change])

    assert result.applied_count == 1
    assert result.game.party[0].move_ids == [33, 44, 611, 0]
    plain, _encrypted = _plain_pk6(_logical_party_slot(client, 0))
    assert list(struct.unpack_from("<4H", plain, 0x5A)) == [33, 44, 611, 0]
    assert tuple(plain[0x62:0x66]) == (35, 25, 20, 0)
    # El fake rechaza cualquier dirección ajena a la party. Llegar hasta aquí
    # demuestra además que la MT83 reutilizable no abrió ni modificó la bolsa.
    assert [address for address, _payload in client.writes] == [XY_PARTY_ADDRESS]
    assert not any(watch.kind.startswith("pocket") for watch in result.memory_watches)


def test_xy_tm_readback_failure_restores_the_original_party_bytes() -> None:
    original = _coherent_role_member()
    client = _XYPartyClient(original, corrupt_first_stored_write=True)
    writer, game, change = _tm_writer_and_game(client)

    with pytest.raises(ORASLiveError, match="restauró los bytes originales"):
        writer.apply(game, [change])

    assert bytes(client.slots[0][:PK6_STORED_SIZE]) == original[:PK6_STORED_SIZE]
    # Primer intento + rollback verificado sobre la misma unidad atómica PK6.
    assert [address for address, _payload in client.writes] == [
        XY_PARTY_ADDRESS,
        XY_PARTY_ADDRESS,
    ]


def test_xy_heal_action_reaches_live_writer_gate() -> None:
    pokemon = parse_pk6_party(_encrypted_party_member(), 1, {})
    assert pokemon is not None
    requested: list[set[int]] = []
    manager = SimpleNamespace(
        current_game=SaveGameData("X", "SAV6XY", 6, "Timper", [pokemon], {}),
        run=SimpleNamespace(pending_changes=[]),
        _active_azahar_realtime_key=lambda: "xy",
        _live_party_heal_available=lambda: True,
        _pokemon_identity=lambda p: f"{p.species_id}:{p.pid}:{p.tid}:{p.sid}",
        _set_operation_status=lambda *_args, **_kwargs: None,
        _request_oras_live_auto_apply_since=lambda previous: requested.append(set(previous)),
    )

    RoleRunManager._heal_bdsp_party(manager)

    assert len(manager.run.pending_changes) == 1
    assert isinstance(manager.run.pending_changes[0], PendingPartyHeal)
    assert requested == [set()]


def test_xy_exposes_heal_in_main_and_floating_surfaces() -> None:
    manager = SimpleNamespace(
        _active_azahar_realtime_key=lambda: "xy",
        _live_party_heal_available=lambda: True,
    )

    assert RoleRunManager._live_party_heal_available(manager) is True
    assert RoleRunManager._floating_live_actions_available(manager) is True


@pytest.mark.parametrize("operation", ["party-to-box", "box-to-party"])
def test_xy_party_resize_reaches_the_live_writer_gate(operation: str) -> None:
    """Una variación de tamaño no puede quedarse solo proyectada en la UI."""
    change = PendingTeamChange(
        operation=operation,
        party_slot=2,
        box=1,
        box_slot=5,
    )
    scheduled: list[bool] = []
    manager = SimpleNamespace(
        run=SimpleNamespace(pending_changes=[change]),
        _active_azahar_realtime_key=lambda: "xy",
        _oras_live_auto_apply_available=lambda: True,
        _oras_live_auto_apply_ids=set(),
        _schedule_oras_live_auto_apply=lambda: scheduled.append(True),
    )

    RoleRunManager._request_oras_live_auto_apply(manager, [change])

    assert manager._oras_live_auto_apply_ids == {id(change)}
    assert scheduled == [True]


@pytest.mark.parametrize("operation", ["party-to-box", "box-to-party"])
def test_oras_party_resize_reaches_the_live_writer_gate(operation: str) -> None:
    """El bug real del 30-08-2026: esta compuerta (independiente de
    _oras_live_unsupported_changes y de ORASLiveWriter._unsupported_changes)
    seguía sin actualizarse para ORAS. El cambio se quedaba proyectado en
    "REVISAR CAMBIOS" como PENDIENTE para siempre — nunca se llegaba siquiera
    a intentar la escritura, así que nunca aparecía ningún error.
    """
    change = PendingTeamChange(
        operation=operation,
        party_slot=2,
        box=1,
        box_slot=5,
    )
    scheduled: list[bool] = []
    manager = SimpleNamespace(
        run=SimpleNamespace(pending_changes=[change]),
        _active_azahar_realtime_key=lambda: "oras",
        _oras_live_auto_apply_available=lambda: True,
        _oras_live_auto_apply_ids=set(),
        _schedule_oras_live_auto_apply=lambda: scheduled.append(True),
    )

    RoleRunManager._request_oras_live_auto_apply(manager, [change])

    assert manager._oras_live_auto_apply_ids == {id(change)}
    assert scheduled == [True]


def test_xy_pc_to_pc_moves_exact_pk6_to_requested_box_and_slot() -> None:
    writer, client, game, change, source_address, destination_address, source_raw = _pc_move_setup()

    result = writer.apply(game, [change])

    source_offset = source_address - XY_PC_KNOWN_ADDRESS
    destination_offset = destination_address - XY_PC_KNOWN_ADDRESS
    cleared = bytes(client.pc[source_offset:source_offset + PK6_STORED_SIZE])
    assert cleared == _EMPTY_XY_PC_SLOT
    assert any(cleared), "X/Y no puede vaciar un BoxPokemon con 0xE8 ceros."
    assert bytes(client.pc[destination_offset:destination_offset + PK6_STORED_SIZE]) == source_raw
    moved = parse_pk6_boxed(
        bytes(client.pc[destination_offset:destination_offset + PK6_STORED_SIZE]), 3, 5, {},
    )
    assert moved is not None and writer._pokemon_identity(moved) == change.incoming_identity
    assert result.applied_count == 1
    assert [pokemon.species_id for pokemon in result.game.party] == [261]


def test_xy_pc_to_pc_rejects_occupied_destination_without_writing() -> None:
    writer, client, game, change, *_rest = _pc_move_setup(occupied_destination=True)
    before = bytes(client.pc)

    with pytest.raises(XYLiveError, match="destino.*ocupada"):
        writer.apply(game, [change])

    assert bytes(client.pc) == before


def test_xy_pc_to_pc_rejects_stale_source_identity_without_writing() -> None:
    writer, client, game, change, *_rest = _pc_move_setup()
    change.incoming_identity = "261:identity-that-is-no-longer-current"
    before = bytes(client.pc)

    with pytest.raises(XYLiveError, match="No se pudo localizar y validar la caja viva"):
        writer.apply(game, [change])

    assert bytes(client.pc) == before


def test_xy_pc_to_pc_rolls_back_both_slots_when_source_clear_readback_diverges() -> None:
    writer, client, game, change, *_rest = _pc_move_setup(corrupt_source=True)
    before = bytes(client.pc)

    with pytest.raises(XYLiveError, match="restauró y verificó ambas casillas"):
        writer.apply(game, [change])

    assert bytes(client.pc) == before


def test_xy_pc_to_pc_rejects_when_azahar_restores_pc_after_immediate_readback() -> None:
    writer, client, game, change, *_rest = _pc_move_setup()
    writer.party_commit_settle_delay = 0
    before = bytes(client.pc)
    # Tras vaciar el origen: readback inmediato (1), doble pareja estable
    # (2..5) y primera lectura del readback asentado (6), que restaura la
    # autoridad original como hizo la copia no consumida observada en Azahar.
    client.arm_pc_restore_after_write(6)

    with pytest.raises(XYLiveError, match="restauró las casillas del PC"):
        writer.apply(game, [change])

    assert bytes(client.pc) == before


def _party_resize_setup(operation: str, *, corrupt_count: bool = False, companion: bool = True):
    raw_a = _coherent_role_member(pid=0x11111111, nickname="Alpha")
    raw_b = _coherent_role_member(pid=0x22222222, nickname="Bravo")
    raw_c = _coherent_role_member(pid=0x33333333, nickname="Charlie")
    companion_raw = _coherent_role_member(pid=0x44444444, nickname="Witness")
    pc = bytearray(_EMPTY_XY_PC_SLOT * (XY_PC_SIZE // PK6_STORED_SIZE))
    target_box, target_slot = 1, 5
    target_index = target_slot - 1
    companion_slot = 2
    companion_index = companion_slot - 1
    if operation == "box-to-party":
        pc[target_index * PK6_STORED_SIZE:(target_index + 1) * PK6_STORED_SIZE] = (
            raw_c[:PK6_STORED_SIZE]
        )
        party_slots = [raw_a, raw_b]
    else:
        party_slots = [raw_a, raw_b, raw_c]
    if companion:
        pc[companion_index * PK6_STORED_SIZE:(companion_index + 1) * PK6_STORED_SIZE] = (
            companion_raw[:PK6_STORED_SIZE]
        )
    client = _XYPartyPCClient(
        party_slots[0],
        pc,
        party_slots=party_slots,
        party_count=len(party_slots),
        corrupt_first_count_write=corrupt_count,
    )
    host_memory = _XYHostMemory(client)
    client.host_memory = host_memory
    reader = XYLiveReader(
        Path("missing.json"), client_factory=lambda: client, stable_delay=0, snapshot_attempts=2,
    )
    writer = XYLiveWriter(
        reader,
        move_pp_for=lambda move_id: {33: 35, 44: 25}.get(int(move_id), 0),
        personal_for=lambda species, form: (
            _POOCHYENA_PERSONAL if (int(species), int(form)) == (261, 0) else None
        ),
        party_commit_settle_delay=0,
        host_memory_factory=lambda: host_memory,
    )
    party = [
        parse_pk6_party(raw, index, reader.move_names)
        for index, raw in enumerate(party_slots, start=1)
    ]
    assert all(pokemon is not None for pokemon in party)
    game = SaveGameData("X", "SAV6XY", 6, "Timper", party, {})
    witness = parse_pk6_boxed(
        companion_raw[:PK6_STORED_SIZE], target_box, companion_slot, reader.move_names,
    )
    assert witness is not None
    witnesses = ((companion_slot, writer._pokemon_identity(witness)),) if companion else ()
    if operation == "party-to-box":
        outgoing = party[1]
        assert outgoing is not None
        change = PendingTeamChange(
            operation=operation,
            party_slot=2,
            box=target_box,
            box_slot=target_slot,
            outgoing_pokemon=outgoing.nickname,
            outgoing_species=outgoing.species,
            outgoing_identity=writer._pokemon_identity(outgoing),
            box_witnesses=witnesses,
        )
    else:
        incoming = parse_pk6_boxed(
            raw_c[:PK6_STORED_SIZE], target_box, target_slot, reader.move_names,
        )
        assert incoming is not None
        change = PendingTeamChange(
            operation=operation,
            party_slot=3,
            box=target_box,
            box_slot=target_slot,
            incoming_pokemon=incoming.nickname,
            incoming_species=incoming.species,
            incoming_role="Mago",
            incoming_identity=writer._pokemon_identity(incoming),
            incoming_snapshot={
                "evs": {
                    "hp": 0, "attack": 0, "defense": 0,
                    "sp_attack": 252, "sp_defense": 0, "speed": 252,
                },
            },
            box_witnesses=((target_slot, writer._pokemon_identity(incoming)),) + witnesses,
        )
    target_address = XY_PC_KNOWN_ADDRESS + target_index * PK6_STORED_SIZE
    return writer, client, game, change, target_address


def test_xy_party_to_box_compacts_party_writes_exact_destination_and_count_last() -> None:
    writer, client, game, change, target_address = _party_resize_setup("party-to-box")
    before_runtime = tuple(bytes(slot) for slot in client.slots)

    result = writer.apply(game, [change])

    assert client.party_count == 2
    assert [pokemon.nickname for pokemon in result.game.party] == ["Alpha", "Charlie"]
    target_offset = target_address - XY_PC_KNOWN_ADDRESS
    moved = parse_pk6_boxed(
        bytes(client.pc[target_offset:target_offset + PK6_STORED_SIZE]), 1, 5, {},
    )
    assert moved is not None and moved.nickname == "Bravo"
    assert bytes(client.slots[0]) == before_runtime[0]
    assert bytes(client.slots[1]) == before_runtime[2]
    assert bytes(client.slots[2]) == before_runtime[3]
    assert client.writes[-1] == (XY_PARTY_COUNT_ADDRESS, struct.pack("<I", 2))
    # Regresión física: una copia anfitriona hallada por contenido aceptaba el
    # readback, pero Pokémon X no la consumía. La autoridad demostrada es la
    # superficie invitada RPC y el writer no debe volver a tocar el host fake.
    assert client.host_memory.writes == []
    assert client.host_memory.closed is False


def test_xy_pc_candidate_matches_native_pokemon_x_deposit_capture() -> None:
    """Budew apareció en caja 1/slot 11 solo desde esta base invitada."""
    assert XY_PC_KNOWN_ADDRESS == 0x08C861B8


def test_xy_party_to_box_rejects_when_azahar_restores_the_live_party_after_commit() -> None:
    writer, client, game, change, _target_address = _party_resize_setup("party-to-box")
    before_party = tuple(bytes(slot) for slot in client.slots)
    before_pc = bytes(client.pc)
    before_count = client.party_count
    # Captura inicial (2), precondición fresca (2), readback inmediato (2) y
    # primera lectura del readback retardado (7): reproduce que Azahar acepte
    # provisionalmente los bytes y restaure después la estructura autoritativa.
    client.arm_runtime_restore(7)

    with pytest.raises(XYLiveError, match="restauró la party"):
        writer.apply(game, [change])

    assert tuple(bytes(slot) for slot in client.slots) == before_party
    assert bytes(client.pc) == before_pc
    assert client.party_count == before_count


def test_xy_box_to_party_appends_member_clears_source_and_writes_count_last() -> None:
    writer, client, game, change, target_address = _party_resize_setup("box-to-party")

    result = writer.apply(game, [change])

    assert client.party_count == 3
    assert [pokemon.nickname for pokemon in result.game.party] == ["Alpha", "Bravo", "Charlie"]
    added = result.game.party[-1]
    assert added.role == "Mago"
    assert added.evs["sp_attack"] == 252 and added.evs["speed"] == 252
    target_offset = target_address - XY_PC_KNOWN_ADDRESS
    assert bytes(client.pc[target_offset:target_offset + PK6_STORED_SIZE]) == _EMPTY_XY_PC_SLOT
    assert client.writes[-1] == (XY_PARTY_COUNT_ADDRESS, struct.pack("<I", 3))


def test_xy_party_resize_rolls_back_party_pc_and_count_when_commit_readback_fails() -> None:
    writer, client, game, change, _target_address = _party_resize_setup(
        "party-to-box", corrupt_count=True,
    )
    before_party = tuple(bytes(slot) for slot in client.slots)
    before_pc = bytes(client.pc)
    before_count = client.party_count

    with pytest.raises(XYLiveError, match="restauró y verificó party, PC y contador"):
        writer.apply(game, [change])

    assert tuple(bytes(slot) for slot in client.slots) == before_party
    assert bytes(client.pc) == before_pc
    assert client.party_count == before_count


def test_xy_party_to_box_rejects_empty_destination_without_box_companion() -> None:
    writer, client, game, change, _target_address = _party_resize_setup(
        "party-to-box", companion=False,
    )
    before_party = tuple(bytes(slot) for slot in client.slots)
    before_pc = bytes(client.pc)

    with pytest.raises(XYLiveError, match="No hay un testigo ocupado"):
        writer.apply(game, [change])

    assert tuple(bytes(slot) for slot in client.slots) == before_party
    assert bytes(client.pc) == before_pc
    assert client.writes == []


def test_xy_ui_accepts_exact_pc_to_pc_drop_only_for_demonstrated_backends() -> None:
    source = SimpleNamespace()
    target = {"pokemon": None, "box": 3, "slot": 5}

    def can_drop(live_key: str) -> bool:
        manager = SimpleNamespace(
            _active_azahar_realtime_key=lambda: live_key,
            _oras_live_auto_apply_available=lambda: True,
            _projected_party=lambda: [SimpleNamespace()],
        )
        return RoleRunManager._team_pc_can_drop(manager, "pc", source, "pc", target)

    assert can_drop("xy") is True
    assert can_drop("usum") is True
    # ORAS se sumó el 30-08-2026 con ORASLiveWriter._apply_pc_move.
    assert can_drop("oras") is True
    assert can_drop("sm") is False


def test_xy_ui_enables_party_resize_and_oras_too() -> None:
    """ORAS dejó de estar cerrado el 30-08-2026: ORASLiveWriter._apply_party_resize
    ya existe y está cubierto por tests sintéticos (ver ORASPartyResizeTests
    en test_oras_live_write.py). Sin validar aún contra una partida real.
    """
    source = SimpleNamespace()

    def can_drop(live_key: str, source_context: str, target_context: str) -> bool:
        manager = SimpleNamespace(
            _active_azahar_realtime_key=lambda: live_key,
            _oras_live_auto_apply_available=lambda: True,
            _projected_party=lambda: [SimpleNamespace(), SimpleNamespace()],
        )
        return RoleRunManager._team_pc_can_drop(
            manager,
            source_context,
            source,
            target_context,
            {"pokemon": None, "box": 1, "slot": 5},
        )

    assert can_drop("xy", "team", "pc") is True
    assert can_drop("xy", "pc", "team") is True
    assert can_drop("oras", "team", "pc") is True
    assert can_drop("oras", "pc", "team") is True


def test_xy_pc_to_pc_drop_queues_exact_coordinates_and_requests_live_apply() -> None:
    source = SimpleNamespace(
        nickname="Poochyena", species="Poochyena", box=4, box_slot=1, slot=1,
    )
    requested: list[set[int]] = []
    statuses: list[tuple[str, str, str]] = []
    manager = SimpleNamespace(
        run=SimpleNamespace(pending_changes=[]),
        _projected_party=lambda: [SimpleNamespace()],
        _active_azahar_realtime_key=lambda: "xy",
        _pokemon_snapshot=lambda pokemon: {"species": pokemon.species},
        _pokemon_identity=lambda _pokemon: "261:2309737967:12345:54321",
        _pc_box_witnesses=lambda box, slot: ((int(box), int(slot) + 1, "companion"),),
        _request_oras_live_auto_apply_since=lambda previous: requested.append(set(previous)),
        _set_operation_status=lambda state, title, detail, **_kwargs: statuses.append(
            (state, title, detail)
        ),
    )

    RoleRunManager._team_pc_drop(
        manager,
        "pc",
        source,
        "pc",
        {"pokemon": None, "box": 3, "slot": 5},
    )

    assert len(manager.run.pending_changes) == 1
    change = manager.run.pending_changes[0]
    assert isinstance(change, PendingTeamChange)
    assert change.operation == "move-box-slot"
    assert (change.box, change.box_slot) == (4, 1)
    assert (change.destination_box, change.destination_box_slot) == (3, 5)
    assert change.incoming_identity == "261:2309737967:12345:54321"
    assert change.box_witnesses == ((4, 2, "companion"),)
    assert requested == [set()]
    # El movimiento se pinta por adelantado en el hueco de destino, así que el
    # aviso tiene que decir exactamente eso: todavía no lo ha confirmado nadie.
    assert statuses == [(
        "applying",
        "MOVIENDO EN EL PC",
        "Caja 4, posición 1 → Caja 3, posición 5. "
        "Mostrado por adelantado; falta la confirmación del juego.",
    )]


def test_xy_party_to_pc_drop_preserves_the_exact_empty_destination() -> None:
    source = SimpleNamespace(nickname="Fennekin", species="Fennekin", slot=2)
    destinations: list[tuple[int, int] | None] = []
    manager = SimpleNamespace(
        _projected_party=lambda: [SimpleNamespace(), source],
        _active_azahar_realtime_key=lambda: "xy",
        _oras_live_auto_apply_available=lambda: True,
        send_pokemon_to_pc=lambda pokemon, *, ask, destination=None: destinations.append(destination),
    )

    RoleRunManager._team_pc_drop(
        manager,
        "team",
        source,
        "pc",
        {"pokemon": None, "box": 3, "slot": 11},
    )

    assert destinations == [(3, 11)]


def test_oras_party_to_pc_drop_preserves_the_exact_empty_destination() -> None:
    """El bug real del 30-08-2026: esta rama del handler de drop —distinta de
    las otras cinco compuertas ya arregladas— también daba por hecho que solo
    X/Y necesitaba el destino exacto. Sin "oras" aquí, arrastrar a un hueco
    concreto del PC siempre acababa en el primer hueco libre, ignorando dónde
    soltó el usuario de verdad.
    """
    source = SimpleNamespace(nickname="Houndoom", species="Houndoom", slot=2)
    destinations: list[tuple[int, int] | None] = []
    manager = SimpleNamespace(
        _projected_party=lambda: [SimpleNamespace(), source],
        _active_azahar_realtime_key=lambda: "oras",
        _oras_live_auto_apply_available=lambda: True,
        send_pokemon_to_pc=lambda pokemon, *, ask, destination=None: destinations.append(destination),
    )

    RoleRunManager._team_pc_drop(
        manager,
        "team",
        source,
        "pc",
        {"pokemon": None, "box": 1, "slot": 5},
    )

    assert destinations == [(1, 5)]


def test_xy_pc_to_free_party_role_is_not_rejected_as_swap_only() -> None:
    incoming = SimpleNamespace(nickname="Budew", species="Budew")
    prepared: list[tuple[object, object, str | None, tuple[str, ...]]] = []
    statuses: list[tuple] = []
    enviados: list[set] = []
    pending = object()
    run = SimpleNamespace(pending_changes=[])

    def prepare(pokemon, outgoing, *, incoming_role_override=None, incoming_libero_stats=()):
        prepared.append((pokemon, outgoing, incoming_role_override, incoming_libero_stats))
        run.pending_changes.append(pending)
        return "CAMBIO PREPARADO"

    manager = SimpleNamespace(
        run=run,
        _active_azahar_realtime_key=lambda: "xy",
        _oras_live_auto_apply_available=lambda: True,
        _projected_party=lambda: [],
        _prepare_pc_team_change=prepare,
        _team_pc_pending_incoming=(1, 5, "budew"),
        _team_pc_pending_outgoing=None,
        _pc_cache=object(),
        _update_top_status=lambda: None,
        _sync_live_layout=lambda: None,
        _smooth_render_page=lambda **_kwargs: None,
        _set_operation_status=lambda *args, **kwargs: statuses.append((*args, kwargs)),
        # Sin esta llamada el cambio se prepara y nadie lo envía nunca: era el
        # fallo que dejaba al Pokémon en el equipo proyectado y ausente del
        # juego. Se comprueba abajo que se hace.
        _request_oras_live_auto_apply_since=lambda previos: enviados.append(previos),
        active_page="team_pc",
    )

    result = RoleRunManager._team_pc_execute_change(
        manager,
        incoming,
        None,
        target_role="Mago",
    )

    assert result is True
    assert prepared == [(incoming, None, "Mago", ())]
    assert run.pending_changes == [pending]
    assert statuses[-1][0:2] == ("applying", "APLICANDO CAMBIO")
    # Y de verdad se envía: decir «APLICANDO CAMBIO» sin enviarlo dejaba al
    # Pokémon en el equipo proyectado y ausente del juego.
    assert len(enviados) == 1


def test_xy_role_change_updates_evs_and_live_stats_preserving_damage_and_status() -> None:
    client = _XYPartyClient(_coherent_role_member())
    writer, game, change = _role_writer_and_game(client)
    before = game.party[0]
    missing_hp = int(before.max_hp or 0) - int(before.current_hp or 0)

    result = writer.apply(game, [change])

    changed = result.game.party[0]
    assert changed.role == "Asesino"
    assert tuple(int(changed.evs.get(key, 0)) for key in (
        "hp", "attack", "defense", "sp_attack", "sp_defense", "speed",
    )) == (0, 252, 0, 0, 0, 252)
    assert int(changed.current_hp or 0) == int(changed.max_hp or 0) - missing_hp
    assert changed.status_condition == 0x40
    assert changed.stats["attack"] > before.stats["attack"]
    assert changed.stats["speed"] > before.stats["speed"]


def test_xy_role_change_rejects_stale_evs_before_any_write() -> None:
    original = _coherent_role_member()
    client = _XYPartyClient(original)
    writer, game, change = _role_writer_and_game(client)
    change.old_evs = (0, 0, 0, 0, 0, 0)

    with pytest.raises(XYLiveError, match="cambió sus EV"):
        writer.apply(game, [change])

    assert bytes(client.slots[0][:PK6_STORED_SIZE]) == original[:PK6_STORED_SIZE]


def test_xy_role_change_rolls_back_stored_and_runtime_regions_on_bad_readback() -> None:
    original = _coherent_role_member()
    client = _XYPartyClient(original, corrupt_first_stats_write=True)
    writer, game, change = _role_writer_and_game(client)

    with pytest.raises(XYLiveError, match="restauró y verificó"):
        writer.apply(game, [change])

    assert bytes(client.slots[0][:PK6_STORED_SIZE]) == original[:PK6_STORED_SIZE]
    assert bytes(client.slots[0][XY_PARTY_STATS_OFFSET:XY_PARTY_STATS_OFFSET + XY_PARTY_STATS_SIZE]) == (
        original[PK6_STORED_SIZE:PK6_STORED_SIZE + XY_PARTY_STATS_SIZE]
    )


def _ui_mon(*, species: int, pid: int, role: str, evs: tuple[int, ...]) -> SavePokemon:
    pokemon = SavePokemon(
        slot=1,
        species_id=int(species),
        species=f"S{species}",
        nickname=f"M{species}",
        level=10,
        held_item="Ninguno",
        ability="A",
        moves=[],
        move_ids=[],
        is_egg=False,
        markings=[False] * 6,
        role=role,
        role_symbol="",
        pid=int(pid),
        tid=1,
        sid=2,
    )
    pokemon.evs = dict(zip(
        ("hp", "attack", "defense", "sp_attack", "sp_defense", "speed"),
        tuple(int(value) for value in evs),
    ))
    return pokemon


def _ui_game(pokemon: SavePokemon) -> SaveGameData:
    return SaveGameData("Pokémon X", "SAV6XY", 6, "Timper", [pokemon], {})


def _ui_identity(pokemon: SavePokemon) -> str:
    return f"{pokemon.species_id}:{pokemon.pid}:{pokemon.tid}:{pokemon.sid}"


def test_xy_in_game_pc_entry_to_fixed_role_prepares_ev_normalization() -> None:
    outgoing = _ui_mon(species=261, pid=10, role="Asesino", evs=(0, 252, 0, 0, 0, 252))
    incoming = _ui_mon(species=263, pid=99, role="SIN ROL", evs=(4, 4, 4, 4, 4, 4))
    manager = SimpleNamespace(
        _active_azahar_realtime_key=lambda: "xy",
        _pokemon_identity=_ui_identity,
    )

    changes = RoleRunManager._incoming_oras_role_changes(
        manager, _ui_game(outgoing), _ui_game(incoming),
    )

    assert len(changes) == 1
    assert changes[0].new_role == "Asesino"
    assert changes[0].old_evs == (4, 4, 4, 4, 4, 4)
    assert changes[0].new_evs == (0, 252, 0, 0, 0, 252)


def test_xy_in_game_pc_entry_to_libero_waits_for_explicit_ev_choice() -> None:
    outgoing = _ui_mon(species=261, pid=10, role="Líbero", evs=(252, 0, 0, 0, 0, 252))
    incoming = _ui_mon(species=263, pid=99, role="SIN ROL", evs=(1, 2, 3, 4, 5, 6))
    after = _ui_game(incoming)
    prompts = []
    writes = []
    manager = SimpleNamespace(
        current_game=after,
        project=SimpleNamespace(slug="xy-run"),
        _session_generation=7,
        _automatic_libero_ev_prompt_key=None,
        _active_azahar_realtime_key=lambda: "xy",
        _pokemon_identity=_ui_identity,
        _floating_bar_is_visible=lambda: True,
        _update_top_status=lambda: None,
        _prompt_libero_ev_stats=lambda pokemon, callback, *, context: prompts.append(
            (pokemon, callback, context)
        ),
        _save_oras_live_changes=lambda batch, **kwargs: writes.append((list(batch), kwargs)) or True,
        sync_status="",
    )
    manager._bdsp_role_evs = RoleRunManager._bdsp_role_evs

    changes = RoleRunManager._incoming_oras_role_changes(
        manager, _ui_game(outgoing), after,
    )
    assert len(changes) == 1
    assert changes[0].new_role == "Líbero"
    assert changes[0].new_evs is None

    assert RoleRunManager._defer_automatic_libero_role_until_ev_choice(
        manager, changes, base_game=after,
    ) is True
    assert len(prompts) == 1
    assert prompts[0][2] == "floating"
    assert writes == []

    prompts[0][1](("hp", "attack"))
    assert len(writes) == 1
    written = writes[0][0][0]
    assert written.old_evs == (1, 2, 3, 4, 5, 6)
    assert written.new_evs == (252, 252, 0, 0, 0, 0)
    assert writes[0][1] == {"automatic": True, "base_game": after}
