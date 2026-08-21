from __future__ import annotations

import struct
from pathlib import Path

from app.azahar_rpc import AzaharProcess
from app.xy_live import (
    XYLiveReader,
    XYLiveWriter,
    XY_MISC_BADGES_OFFSET,
    XY_MISC_KNOWN_ADDRESS,
    XY_SAVE_MISC_OFFSET,
    XY_SAVE_MISC_SIZE,
    XY_SAVE_SUBEVENT_OFFSET,
    XY_SAVE_SUBEVENT_SIZE,
    XY_SUBEVENT_BADGE_COUNT,
    XY_SUBEVENT_BADGE_SLOT_COUNT,
    XY_SUBEVENT_BADGE_VICTORY_OFFSET,
    XY_SUBEVENT_MAGIC,
    XY_SUBEVENT_MAGIC_OFFSETS,
    XY_TITLE_IDS,
    count_xy_badge_victories,
    parse_xy_saved_badge_victories,
)


class MemoryClient:
    def __init__(self, regions: dict[int, bytes | bytearray]):
        self.regions = {int(k): bytearray(v) for k, v in regions.items()}
        self.process = AzaharProcess(1, next(iter(XY_TITLE_IDS)), "kujira-1")
        self.reads: list[tuple[int, int]] = []

    def __enter__(self): return self
    def __exit__(self, *_): return None
    def process_list(self): return [self.process]
    def set_process(self, _pid): return None

    def read_memory(self, address: int, size: int) -> bytes:
        self.reads.append((int(address), int(size)))
        out = bytearray(size)
        end = address + size
        for base, data in self.regions.items():
            a = max(address, base)
            b = min(end, base + len(data))
            if a < b:
                out[a-address:b-address] = data[a-base:b-base]
        return bytes(out)


def sube_with_badges(count: int) -> bytearray:
    raw = bytearray(XY_SAVE_SUBEVENT_SIZE)
    for offset in XY_SUBEVENT_MAGIC_OFFSETS:
        raw[offset:offset + 4] = XY_SUBEVENT_MAGIC
    for badge in range(count):
        start = XY_SUBEVENT_BADGE_VICTORY_OFFSET + badge * XY_SUBEVENT_BADGE_SLOT_COUNT * 2
        # Un equipo mínimo pero estructuralmente válido: una especie por medalla.
        struct.pack_into("<H", raw, start, 10 + badge)
    return raw


def make_main(path: Path, *, saved_badges: int = 0) -> Path:
    blob = bytearray(XY_SAVE_SUBEVENT_OFFSET + XY_SAVE_SUBEVENT_SIZE)
    misc = bytearray(XY_SAVE_MISC_SIZE)
    for i in range(0x20, 0x70):
        misc[i] = (i * 7) & 0xFF
    misc[XY_MISC_BADGES_OFFSET] = saved_badges
    blob[XY_SAVE_MISC_OFFSET:XY_SAVE_MISC_OFFSET + XY_SAVE_MISC_SIZE] = misc
    blob[XY_SAVE_SUBEVENT_OFFSET:XY_SAVE_SUBEVENT_OFFSET + XY_SAVE_SUBEVENT_SIZE] = sube_with_badges(saved_badges)
    path.write_bytes(blob)
    return path


def test_alpha14_saved_sube_counts_zero_three_and_eight(tmp_path: Path) -> None:
    for count in (0, 3, 8):
        main = make_main(tmp_path / f"main-{count}", saved_badges=count)
        assert parse_xy_saved_badge_victories(main) == count


def test_alpha14_sube_rejects_non_prefix_and_invalid_species() -> None:
    raw = sube_with_badges(1)
    # Medalla 3 presente dejando la 2 vacía: no es una progresión válida.
    third = XY_SUBEVENT_BADGE_VICTORY_OFFSET + 2 * XY_SUBEVENT_BADGE_SLOT_COUNT * 2
    struct.pack_into("<H", raw, third, 25)
    assert count_xy_badge_victories(raw) is None

    raw = sube_with_badges(1)
    struct.pack_into("<H", raw, XY_SUBEVENT_BADGE_VICTORY_OFFSET, 999)
    assert count_xy_badge_victories(raw) is None


def test_alpha14_badges_prefer_live_sube_over_stale_misc(tmp_path: Path) -> None:
    main = make_main(tmp_path / "main", saved_badges=0)
    live_base = 0x08C40000
    live_sube = sube_with_badges(1)

    # La dirección Misc histórica sigue representando 0; reproduce exactamente
    # el fallo real que motivó alpha.14.
    saved_misc = bytearray(main.read_bytes()[XY_SAVE_MISC_OFFSET:XY_SAVE_MISC_OFFSET + XY_SAVE_MISC_SIZE])
    stale_misc = bytearray(saved_misc)
    stale_misc[XY_MISC_BADGES_OFFSET] = 0

    fake = MemoryClient({live_base: live_sube, XY_MISC_KNOWN_ADDRESS: stale_misc})
    reader = XYLiveReader(Path("missing.json"), client_factory=lambda: fake, stable_delay=0)
    writer = XYLiveWriter(reader, move_pp_for=lambda _m: 10)

    assert writer.read_badges(main) == 1
    assert writer.last_badge_source == "SUBE vivo X/Y · equipos de gimnasio"
    key = (int(fake.process.title_id), fake.process.name)
    assert writer._subevent_bases_by_process[key] == live_base
    assert (live_base, XY_SAVE_SUBEVENT_SIZE) in writer.runtime_memory_requests()


def test_alpha14_cached_live_sube_can_regress_after_state_load(tmp_path: Path) -> None:
    main = make_main(tmp_path / "main", saved_badges=0)
    live_base = 0x08C50000
    live = sube_with_badges(8)
    fake = MemoryClient({live_base: live})
    reader = XYLiveReader(Path("missing.json"), client_factory=lambda: fake, stable_delay=0)
    writer = XYLiveWriter(reader, move_pp_for=lambda _m: 10)

    assert writer.read_badges(main) == 8
    key = (int(fake.process.title_id), fake.process.name)
    assert writer._subevent_bases_by_process[key] == live_base

    fake.regions[live_base][:] = sube_with_badges(5)
    assert writer.read_badges(main) == 5
    assert writer._subevent_bases_by_process[key] == live_base
