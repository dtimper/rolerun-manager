from __future__ import annotations

import struct
from pathlib import Path

import pytest

from app.azahar_rpc import AzaharProcess
from app.models import PendingInventoryChange
from app.save_engine_client import SaveGameData
from app.xy_live import (
    XYLiveError,
    XYLiveReader,
    XYLiveWriter,
    XY_BAG_KNOWN_BASE_V10,
    XY_BAG_KNOWN_BASE_V15,
    XY_MAX_MONEY,
    XY_MONEY_KNOWN_ADDRESS_V10,
    XY_MONEY_KNOWN_ADDRESS_V15,
    XY_TITLE_IDS,
)


class MemoryClient:
    def __init__(self, regions: dict[int, bytes | bytearray]):
        self.regions = {int(base): bytearray(raw) for base, raw in regions.items()}
        self.process = AzaharProcess(1, next(iter(XY_TITLE_IDS)), "kujira-1")
        self.writes: list[tuple[int, bytes]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def process_list(self):
        return [self.process]

    def set_process(self, _pid: int):
        return None

    def read_memory(self, address: int, size: int) -> bytes:
        address = int(address)
        size = int(size)
        out = bytearray(size)
        end = address + size
        for base, data in self.regions.items():
            a = max(address, base)
            b = min(end, base + len(data))
            if a < b:
                out[a - address:b - address] = data[a - base:b - base]
        return bytes(out)

    def write_memory(self, address: int, raw: bytes):
        address = int(address)
        raw = bytes(raw)
        for base, data in self.regions.items():
            offset = address - base
            if 0 <= offset and offset + len(raw) <= len(data):
                data[offset:offset + len(raw)] = raw
                self.writes.append((address, raw))
                return None
        raise AssertionError(f"write outside regions: 0x{address:08X}")


def _writer(client: MemoryClient) -> XYLiveWriter:
    reader = XYLiveReader(Path("missing.json"), client_factory=lambda: client, stable_delay=0)
    return XYLiveWriter(reader, move_pp_for=lambda _move: 10)


def _dummy_game() -> SaveGameData:
    return SaveGameData(game="X", save_type="main", generation=6, trainer="Test", party=[], raw={})


def _patch_capture_and_game(writer: XYLiveWriter) -> None:
    def capture(client, extras):
        extra = {key: client.read_memory(address, size) for key, address, size in extras}
        return (b"\x01",), extra, 1

    writer._capture_stable_state = capture  # type: ignore[method-assign]
    writer._build_game = lambda _slots, current, _process, live_write: current  # type: ignore[method-assign]


@pytest.mark.parametrize(
    ("bag_base", "money_address"),
    [
        (XY_BAG_KNOWN_BASE_V10, XY_MONEY_KNOWN_ADDRESS_V10),
        (XY_BAG_KNOWN_BASE_V15, XY_MONEY_KNOWN_ADDRESS_V15),
    ],
)
def test_alpha20_money_address_is_derived_only_from_validated_known_bag_layout(
    bag_base: int, money_address: int,
) -> None:
    client = MemoryClient({money_address: struct.pack("<I", 54321)})
    writer = _writer(client)
    writer._locate_bag_base = lambda *_args, **_kwargs: bag_base  # type: ignore[method-assign]

    assert writer._locate_money_address_from_live_bag(client, client.process) == money_address


def test_alpha20_money_anchor_rejects_unknown_bag_layout() -> None:
    client = MemoryClient({XY_MONEY_KNOWN_ADDRESS_V10: struct.pack("<I", 54321)})
    writer = _writer(client)
    writer._locate_bag_base = lambda *_args, **_kwargs: 0x08C12340  # type: ignore[method-assign]

    with pytest.raises(XYLiveError, match="no corresponde"):
        writer._locate_money_address_from_live_bag(client, client.process)


def test_alpha20_money_write_does_not_need_saved_misc_when_live_bag_proves_layout() -> None:
    money_address = XY_MONEY_KNOWN_ADDRESS_V10
    client = MemoryClient({money_address: struct.pack("<I", 123456)})
    writer = _writer(client)
    writer._locate_money_address_from_live_bag = lambda *_args, **_kwargs: money_address  # type: ignore[method-assign]
    _patch_capture_and_game(writer)

    result = writer.apply(
        _dummy_game(),
        [PendingInventoryChange("money-max", "Dinero", XY_MAX_MONEY)],
    )

    assert struct.unpack("<I", client.regions[money_address])[0] == XY_MAX_MONEY
    assert client.writes == [(money_address, struct.pack("<I", XY_MAX_MONEY))]
    assert result.applied_count == 1
