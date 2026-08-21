from __future__ import annotations

import struct
from pathlib import Path

from app.azahar_rpc import AzaharProcess
from app.xy_live import (
    XYLiveReader,
    XYLiveWriter,
    XY_MISC_BADGES_OFFSET,
    XY_SAVE_MISC_OFFSET,
    XY_SAVE_MISC_SIZE,
    XY_SAVE_SUBEVENT_OFFSET,
    XY_SAVE_SUBEVENT_SIZE,
    XY_SUBEVENT_BADGE_SLOT_COUNT,
    XY_SUBEVENT_BADGE_VICTORY_OFFSET,
    XY_SUBEVENT_MAGIC,
    XY_SUBEVENT_MAGIC_OFFSETS,
    XY_TITLE_IDS,
    count_xy_badge_victories,
    parse_xy_badges,
    parse_xy_saved_badges,
    parse_xy_saved_badge_victories,
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


def real_layout_sube(*, gym_teams: tuple[tuple[int, ...], ...] = ()) -> bytearray:
    raw = bytearray(XY_SAVE_SUBEVENT_SIZE)
    # main real: u32 conceptual SUBE -> bytes little-endian EBUS.
    for offset in XY_SUBEVENT_MAGIC_OFFSETS:
        raw[offset:offset + 4] = b"EBUS"
    for badge, team in enumerate(gym_teams):
        start = XY_SUBEVENT_BADGE_VICTORY_OFFSET + badge * XY_SUBEVENT_BADGE_SLOT_COUNT * 2
        for slot, species in enumerate(team[:XY_SUBEVENT_BADGE_SLOT_COUNT]):
            struct.pack_into("<H", raw, start + slot * 2, int(species))
    return raw


def make_main(path: Path, *, badges: int, gym_teams: tuple[tuple[int, ...], ...]) -> Path:
    blob = bytearray(XY_SAVE_SUBEVENT_OFFSET + XY_SAVE_SUBEVENT_SIZE)
    misc = bytearray(XY_SAVE_MISC_SIZE)
    misc[XY_MISC_BADGES_OFFSET] = int(badges)
    blob[XY_SAVE_MISC_OFFSET:XY_SAVE_MISC_OFFSET + XY_SAVE_MISC_SIZE] = misc
    blob[XY_SAVE_SUBEVENT_OFFSET:XY_SAVE_SUBEVENT_OFFSET + XY_SAVE_SUBEVENT_SIZE] = real_layout_sube(
        gym_teams=gym_teams,
    )
    path.write_bytes(blob)
    return path


def test_alpha16_misc_badges_are_decimal_counter_not_bitmask() -> None:
    assert parse_xy_badges(b"\x00") == 0
    assert parse_xy_badges(b"\x01") == 1
    assert parse_xy_badges(b"\x02") == 2
    assert parse_xy_badges(b"\x03") == 3
    assert parse_xy_badges(b"\x08") == 8
    assert parse_xy_badges(b"\x09") is None


def test_alpha16_real_sube_magic_is_little_endian_ebus() -> None:
    assert XY_SUBEVENT_MAGIC == b"EBUS"
    raw = real_layout_sube(gym_teams=((655, 16, 664, 263, 664, 664),))
    for offset in XY_SUBEVENT_MAGIC_OFFSETS:
        assert raw[offset:offset + 4] == b"EBUS"
    assert count_xy_badge_victories(raw) == 1


def test_alpha16_pre_post_gym_save_semantics(tmp_path: Path) -> None:
    pre = make_main(tmp_path / "pre", badges=0, gym_teams=())
    post = make_main(
        tmp_path / "post",
        badges=1,
        gym_teams=((655, 16, 664, 263, 664, 664),),
    )
    assert parse_xy_saved_badges(pre) == 0
    assert parse_xy_saved_badges(post) == 1
    assert parse_xy_saved_badge_victories(pre) == 0
    assert parse_xy_saved_badge_victories(post) == 1


def test_alpha16_live_sube_locator_finds_real_ebus_block(tmp_path: Path) -> None:
    # El main puede seguir pre-gimnasio: la lectura viva debe ganar igualmente.
    main = make_main(tmp_path / "main", badges=0, gym_teams=())
    live_base = 0x08C40000
    live = real_layout_sube(gym_teams=((655, 16, 664, 263, 664, 664),))
    fake = MemoryClient({live_base: live})
    reader = XYLiveReader(Path("missing.json"), client_factory=lambda: fake, stable_delay=0)
    writer = XYLiveWriter(reader, move_pp_for=lambda _m: 10)

    assert writer.read_badges(main) == 1
    assert writer.last_badge_source == "SUBE vivo X/Y · equipos de gimnasio"
