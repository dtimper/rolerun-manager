from __future__ import annotations

import struct
from pathlib import Path

from app.azahar_rpc import AzaharProcess
from app.oras_live import PK6_PARTY_SIZE, PK6_STORED_SIZE, _checksum, encrypt_pk6, parse_pk6_boxed
from app.oras_tm_service import oras_tm_item_id
from app.save_engine_client import SaveGameData
from app.xy_live import (
    XYLiveReader, XYLiveWriter, XY_PC_SCAN_START, XY_PC_SIZE,
    XY_TM_POUCH_SIZE, XY_INVENTORY_SCAN_START, XY_TITLE_IDS,
    XY_PARTY_ADDRESS, XY_PARTY_COUNT_ADDRESS, XY_PARTY_STRIDE,
    XY_PARTY_STATS_OFFSET, XY_PARTY_STATS_SIZE,
    load_xy_move_metadata,
)


def _pk6(*, species=25, pid=0x11223344, tid=123, sid=456, nickname="Pika", marking=0, level=50) -> bytes:
    data = bytearray(PK6_PARTY_SIZE)
    struct.pack_into("<I", data, 0, 0x12345678)
    struct.pack_into("<H", data, 8, species)
    struct.pack_into("<H", data, 0x0C, tid)
    struct.pack_into("<H", data, 0x0E, sid)
    struct.pack_into("<I", data, 0x18, pid)
    data[0x2A] = 1 << marking
    encoded = nickname.encode("utf-16le")
    data[0x40:0x40 + len(encoded)] = encoded
    struct.pack_into("<4H", data, 0x5A, 33, 45, 0, 0)
    struct.pack_into("<I", data, 0x74, 0x3FFFFFFF)
    data[0xEC] = int(level)
    struct.pack_into("<H", data, 6, _checksum(data))
    return encrypt_pk6(bytes(data))


class _MemoryClient:
    def __init__(self, regions: dict[int, bytes | bytearray]):
        self.regions = {int(k): bytearray(v) for k, v in regions.items()}
        self.process = AzaharProcess(1, next(iter(XY_TITLE_IDS)), "kujira-1")
        self.reads = 0

    def __enter__(self): return self
    def __exit__(self, *_): return None
    def process_list(self): return [self.process]
    def set_process(self, _pid): return None

    def read_memory(self, address: int, size: int) -> bytes:
        self.reads += 1
        out = bytearray(size)
        end = address + size
        for base, data in self.regions.items():
            a = max(address, base); b = min(end, base + len(data))
            if a < b:
                out[a-address:b-address] = data[a-base:b-base]
        return bytes(out)

    def write_memory(self, address: int, data: bytes) -> None:
        for base, region in self.regions.items():
            if base <= address and address + len(data) <= base + len(region):
                region[address-base:address-base+len(data)] = data
                return
        self.regions[address] = bytearray(data)


def test_xy_move_metadata_is_pinned_to_the_xy_version_group() -> None:
    metadata = load_xy_move_metadata(Path("data/xy_move_metadata.json"))

    assert len(metadata) == 621
    assert metadata[33] == {
        "power": 50,
        "accuracy": 100,
        "pp": 35,
        "description_es": "Embiste con todo el cuerpo.",
        "type_id": 0,
    }
    assert metadata[611] == {
        "power": 20,
        "accuracy": 100,
        "pp": 20,
        "description_es": (
            "Hostiga al Pokémon objetivo durante cuatro o cinco turnos e impide "
            "que pueda huir mientras tanto."
        ),
        "type_id": 6,
    }


def test_xy_move_metadata_rejects_a_table_from_another_game(tmp_path: Path) -> None:
    wrong = tmp_path / "wrong.json"
    wrong.write_text(
        '{"generation": 7, "target_version_group": "sun-moon", '
        '"moves": {"33": {"power": 40, "accuracy": 100, "pp": 35}}}',
        encoding="utf-8",
    )

    assert load_xy_move_metadata(wrong) == {}


def test_xy_alpha6_locates_and_reads_live_pc_matrix_then_reuses_cache() -> None:
    base = XY_PC_SCAN_START + 0x20000
    pc = bytearray(XY_PC_SIZE)
    first = _pk6(species=25, pid=111, nickname="Uno")[:PK6_STORED_SIZE]
    second = _pk6(species=133, pid=222, nickname="Dos")[:PK6_STORED_SIZE]
    pc[0:PK6_STORED_SIZE] = first
    pc[PK6_STORED_SIZE:2*PK6_STORED_SIZE] = second
    fake = _MemoryClient({base: pc})
    reader = XYLiveReader(Path("missing.json"), client_factory=lambda: fake, stable_delay=0)
    a1 = parse_pk6_boxed(first, 1, 1, reader.move_names)
    a2 = parse_pk6_boxed(second, 1, 2, reader.move_names)
    assert a1 is not None and a2 is not None
    process, found, slots = reader.read_pc([a1, a2])
    assert found == base
    assert process.name == "kujira-1"
    assert slots[(1, 1)] is not None and slots[(1, 1)].pid == 111
    assert slots[(1, 2)] is not None and slots[(1, 2)].pid == 222
    reads_after_first = fake.reads
    _process, found2, _slots = reader.read_pc([a1, a2])
    assert found2 == base
    # La segunda lectura valida caché; no necesita repetir el barrido completo.
    assert fake.reads - reads_after_first < 20


def test_xy_alpha6_locates_live_tm_pocket_from_saved_witnesses() -> None:
    base = XY_INVENTORY_SCAN_START + 0x30000
    pouch = bytearray(XY_TM_POUCH_SIZE)
    mt01 = oras_tm_item_id(1); mt24 = oras_tm_item_id(24); mt50 = oras_tm_item_id(50)
    assert mt01 and mt24 and mt50
    for index, item_id in enumerate((mt01, mt24, mt50)):
        struct.pack_into("<HH", pouch, index * 4, item_id, 1)
    fake = _MemoryClient({base: pouch})
    reader = XYLiveReader(Path("missing.json"), client_factory=lambda: fake, stable_delay=0)
    writer = XYLiveWriter(reader, move_pp_for=lambda _m: 10)
    inventory, process, attempt = writer.read_tm_inventory({mt01: 1, mt24: 1})
    assert process.name == "kujira-1"
    assert attempt >= 1
    assert inventory[mt01] == 1 and inventory[mt24] == 1 and inventory[mt50] == 1
    assert writer.block_resolver.cached_address(
        (int(process.title_id), str(process.name), reader.transport_label), "xy.inventory.tm_hm"
    ) == base


def test_xy_read_ignores_a_leftover_valid_pokemon_beyond_the_real_count() -> None:
    """Bug real, 2026-09-05: la lectura pasiva normal (dashboard, equipo,
    barra flotante) decodificaba los seis slots físicos y se quedaba con
    cualquiera que pareciese un Pokémon válido, sin mirar el contador real.
    El slot que el contador excluye no se borra -sigue pasando el checksum
    PK6 como un Pokémon válido, es lo último que hubo ahí-, así que en
    cuanto se liberaba un hueco esta lectura colaba ese sobrante como un
    miembro fantasma: el equipo parecía tener seis aunque solo cinco fuesen
    reales, y RoleRun rechazaba añadir uno nuevo con "el equipo ya tiene
    seis Pokémon".
    """
    def _place(region: bytearray, index: int, raw: bytes) -> None:
        base = index * XY_PARTY_STRIDE
        region[base:base + PK6_STORED_SIZE] = raw[:PK6_STORED_SIZE]
        region[base + XY_PARTY_STATS_OFFSET:base + XY_PARTY_STATS_OFFSET + XY_PARTY_STATS_SIZE] = (
            raw[PK6_STORED_SIZE:PK6_STORED_SIZE + XY_PARTY_STATS_SIZE]
        )

    region = bytearray(6 * XY_PARTY_STRIDE)
    for index, nickname in enumerate(("Uno", "Dos", "Tres", "Cuatro", "Cinco")):
        _place(region, index, _pk6(pid=0x11110000 + index, nickname=nickname))
    # El sexto slot físico conserva un Pokémon válido y distinto -lo último
    # que hubo ahí-, aunque el contador solo declare cinco.
    _place(region, 5, _pk6(pid=0x22220000, nickname="Fantasma"))
    fake = _MemoryClient({
        XY_PARTY_ADDRESS: bytes(region),
        XY_PARTY_COUNT_ADDRESS: struct.pack("<I", 5),
    })
    reader = XYLiveReader(Path("missing.json"), client_factory=lambda: fake, stable_delay=0)
    current = SaveGameData("X", "SAV6XY", 6, "Timper", [], {})

    snapshot = reader.read(current)

    assert [pokemon.nickname for pokemon in snapshot.game.party] == [
        "Uno", "Dos", "Tres", "Cuatro", "Cinco",
    ]


def test_xy_alpha6_runtime_capabilities_are_live_for_pc_and_tm() -> None:
    class R:
        client_factory = staticmethod(lambda: None)
        transport_label = "fake"
        def reset_runtime_state(self): pass
    class W:
        block_resolver = type("B", (), {"last_resolutions": ()})()
        def reset_runtime_state(self): pass
    from app.realtime.xy_adapter import XYRealTimeAdapter
    adapter = XYRealTimeAdapter(R(), W())
    caps = adapter.runtime_state()["capabilities"]
    assert caps["pc"] == "read-live"
    assert caps["tm_inventory"] == "read-live"


def test_xy_v024_writer_allows_validated_pc_swap_and_party_resize_operations() -> None:
    from app.models import PendingTeamChange
    class R:
        client_factory = staticmethod(lambda: None)
        transport_label = "fake"
    writer = XYLiveWriter(R(), move_pp_for=lambda _m: 10)
    swap = PendingTeamChange(
        operation="swap-party-box", party_slot=1, box=2, box_slot=3,
        outgoing_pokemon="A", incoming_pokemon="B",
    )
    deposit = PendingTeamChange(
        operation="party-to-box", party_slot=1, box=2, box_slot=3,
        outgoing_pokemon="A",
    )
    assert writer._unsupported_changes([swap]) == []
    assert writer._unsupported_changes([deposit]) == []


def test_xy_alpha6_can_calibrate_pc_with_one_unique_pokemon() -> None:
    base = XY_PC_SCAN_START + 0x50000
    pc = bytearray(XY_PC_SIZE)
    only = _pk6(species=25, pid=0xABCDEF01, tid=777, sid=888, nickname="Solo")[:PK6_STORED_SIZE]
    pc[0:PK6_STORED_SIZE] = only
    fake = _MemoryClient({base: pc})
    reader = XYLiveReader(Path("missing.json"), client_factory=lambda: fake, stable_delay=0)
    anchor = parse_pk6_boxed(only, 1, 1, reader.move_names)
    assert anchor is not None
    _process, found, slots = reader.read_pc([anchor])
    assert found == base
    assert slots[(1, 1)] is not None and slots[(1, 1)].pid == 0xABCDEF01
