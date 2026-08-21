from __future__ import annotations

from pathlib import Path

from app.azahar_rpc import AzaharProcess
from app.xy_live import (
    XYLiveReader,
    XYLiveWriter,
    XY_MISC_BADGES_OFFSET,
    XY_MISC_KNOWN_ADDRESS_V10,
    XY_MISC_KNOWN_ADDRESS_V15,
    XY_SAVE_MISC_OFFSET,
    XY_SAVE_MISC_SIZE,
    XY_TITLE_IDS,
    parse_xy_badges,
)


class MemoryClient:
    def __init__(self, regions: dict[int, bytes | bytearray]):
        self.regions = {int(k): bytearray(v) for k, v in regions.items()}
        self.process = AzaharProcess(1, next(iter(XY_TITLE_IDS)), "kujira-1")

    def __enter__(self): return self
    def __exit__(self, *_): return None
    def process_list(self): return [self.process]
    def set_process(self, _pid): return None

    def read_memory(self, address: int, size: int) -> bytes:
        out = bytearray(size)
        end = address + size
        for base, data in self.regions.items():
            a = max(address, base)
            b = min(end, base + len(data))
            if a < b:
                out[a-address:b-address] = data[a-base:b-base]
        return bytes(out)


def misc_with_badges(count: int) -> bytearray:
    raw = bytearray(XY_SAVE_MISC_SIZE)
    # Huella no dinámica con suficiente entropía para discriminar un corrimiento 0x10.
    for i in range(0x50, 0xB0):
        raw[i] = ((i * 37) % 251) + 1
    raw[XY_MISC_BADGES_OFFSET] = count
    return raw


def write_main(path: Path, misc: bytes | bytearray) -> Path:
    blob = bytearray(XY_SAVE_MISC_OFFSET + XY_SAVE_MISC_SIZE)
    blob[XY_SAVE_MISC_OFFSET:XY_SAVE_MISC_OFFSET + XY_SAVE_MISC_SIZE] = misc
    path.write_bytes(blob)
    return path


def test_alpha15_badge_parser_regression_is_superseded_by_alpha16_counter_format() -> None:
    # Conservamos este archivo por trazabilidad histórica, pero alpha.16 corrige
    # la interpretación: X/Y guarda un contador decimal 0..8, no una bitmask.
    assert parse_xy_badges(bytes([0x00])) == 0
    assert parse_xy_badges(bytes([0x01])) == 1
    assert parse_xy_badges(bytes([0x03])) == 3
    assert parse_xy_badges(bytes([0x07])) == 7
    assert parse_xy_badges(bytes([0x08])) == 8
    assert parse_xy_badges(bytes([0xFF])) is None


def test_alpha15_selects_v10_misc_when_v15_address_is_same_region_shifted(tmp_path: Path) -> None:
    saved = misc_with_badges(0)
    live_v10 = misc_with_badges(1)

    # Reproduce el fallo real: en v1.0 el bloque empieza 0x10 antes. Leer desde
    # la base v1.5 equivale a leer la misma región desplazada, por lo que el byte
    # de +0x0C ya no es el de medallas.
    region = bytearray(XY_SAVE_MISC_SIZE + 0x10)
    region[:XY_SAVE_MISC_SIZE] = live_v10
    fake = MemoryClient({XY_MISC_KNOWN_ADDRESS_V10: region})

    main = write_main(tmp_path / "main", saved)
    reader = XYLiveReader(Path("missing.json"), client_factory=lambda: fake, stable_delay=0)
    writer = XYLiveWriter(reader, move_pp_for=lambda _m: 10)
    writer._locate_subevent_base = lambda *_args, **_kwargs: None
    writer._discover_misc = lambda *_args, **_kwargs: ()

    assert writer.read_badges(main) == 1
    key = (int(fake.process.title_id), fake.process.name)
    assert writer.block_resolver.cached_address(key, "xy.misc") == XY_MISC_KNOWN_ADDRESS_V10
    assert writer.last_badge_source == "Misc vivo X/Y"


def test_alpha15_still_accepts_v15_misc(tmp_path: Path) -> None:
    saved = misc_with_badges(1)
    live = misc_with_badges(2)
    main = write_main(tmp_path / "main", saved)
    fake = MemoryClient({XY_MISC_KNOWN_ADDRESS_V15: live})
    reader = XYLiveReader(Path("missing.json"), client_factory=lambda: fake, stable_delay=0)
    writer = XYLiveWriter(reader, move_pp_for=lambda _m: 10)
    writer._locate_subevent_base = lambda *_args, **_kwargs: None
    writer._discover_misc = lambda *_args, **_kwargs: ()

    assert writer.read_badges(main) == 2
    key = (int(fake.process.title_id), fake.process.name)
    assert writer.block_resolver.cached_address(key, "xy.misc") == XY_MISC_KNOWN_ADDRESS_V15
