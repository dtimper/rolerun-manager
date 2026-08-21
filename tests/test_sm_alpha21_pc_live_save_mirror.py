from __future__ import annotations

import struct
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

try:
    import customtkinter  # noqa: F401
except ModuleNotFoundError:
    customtkinter = types.ModuleType("customtkinter")
    customtkinter.CTk = object
    sys.modules["customtkinter"] = customtkinter

from app.oras_live import encrypt_pk6
from app.save_engine_client import SaveGameData, SavePokemon
from app.sm_live import (
    PK7_PARTY_SIZE,
    PK7_STORED_SIZE,
    SM_SAVE_BOX_LAYOUT_BLOCK_OFFSET,
    SM_SAVE_BOX_LAYOUT_BLOCK_SIZE,
    SM_SAVE_ITEM_BLOCK_SIZE,
    SM_SAVE_MISC_BLOCK_OFFSET,
    SM_SAVE_MISC_BLOCK_SIZE,
    SM_SAVE_PC_BLOCK_OFFSET,
    SM_SAVE_PC_BLOCK_SIZE,
    SMLiveError,
    SMLiveWriter,
)
from app.win_process_memory import HostPartyTarget


def _checksum(data: bytes) -> int:
    return sum(struct.unpack_from("<112H", data, 8)) & 0xFFFF


def _stored_pk7(species: int, pid: int) -> bytes:
    data = bytearray(PK7_PARTY_SIZE)
    struct.pack_into("<I", data, 0x00, 0xACED0000 ^ int(pid))
    struct.pack_into("<H", data, 0x04, 0)
    struct.pack_into("<H", data, 0x08, int(species))
    struct.pack_into("<H", data, 0x0C, 11)
    struct.pack_into("<H", data, 0x0E, 22)
    data[0x14] = 65
    struct.pack_into("<I", data, 0x18, int(pid))
    name = f"M{species}".encode("utf-16le") + b"\0\0"
    data[0x40:0x40 + len(name)] = name
    struct.pack_into("<H", data, 0x5A, 33)
    struct.pack_into("<H", data, 0x5C, 45)
    struct.pack_into("<I", data, 0x74, 31 | (31 << 5))
    struct.pack_into("<H", data, 0x06, _checksum(data))
    return encrypt_pk6(bytes(data))[:PK7_STORED_SIZE]


def _party_mon(species: int = 6, pid: int = 0x99887766) -> SavePokemon:
    return SavePokemon(
        slot=1, species_id=species, species=f"Species {species}", nickname=f"Party {species}",
        level=30, held_item="Ninguno", ability="Ability", moves=["A", "B", "—", "—"],
        move_ids=[1, 2, 0, 0], is_egg=False, markings=[False] * 6,
        role="SIN ROL", role_symbol="", pid=pid, tid=11, sid=22,
    )


def _saved_and_live_images() -> tuple[bytes, bytes]:
    # 0x3B400 cubre exactamente Items..BoxPokemon de SAV7SM.
    saved = bytearray(SM_SAVE_PC_BLOCK_OFFSET + SM_SAVE_PC_BLOCK_SIZE)
    # Bloques con entropía determinista para que las ventanas estructurales sean
    # fuertes y distribuidas; no son direcciones ni contenido inventado de RAM.
    for i in range(SM_SAVE_ITEM_BLOCK_SIZE):
        saved[i] = (i * 29 + 17) & 0xFF
    for i in range(SM_SAVE_MISC_BLOCK_SIZE):
        saved[SM_SAVE_MISC_BLOCK_OFFSET + i] = (i * 37 + 11) & 0xFF
    struct.pack_into("<I", saved, SM_SAVE_MISC_BLOCK_OFFSET + 4, 123456)
    for i in range(SM_SAVE_BOX_LAYOUT_BLOCK_SIZE):
        saved[SM_SAVE_BOX_LAYOUT_BLOCK_OFFSET + i] = (i * 43 + 7) & 0xFF

    live = bytearray(saved)
    # El estado vivo puede divergir del main: dinero distinto y PC recién usado.
    struct.pack_into("<I", live, SM_SAVE_MISC_BLOCK_OFFSET + 4, 654321)
    pc = bytearray(SM_SAVE_PC_BLOCK_SIZE)
    index = (4 - 1) * 30 + (8 - 1)
    start = index * PK7_STORED_SIZE
    pc[start:start + PK7_STORED_SIZE] = _stored_pk7(25, 0x1234ABCD)
    live[SM_SAVE_PC_BLOCK_OFFSET:SM_SAVE_PC_BLOCK_OFFSET + SM_SAVE_PC_BLOCK_SIZE] = pc
    return bytes(saved), bytes(live)


class _MappedMemory:
    def __init__(self, base: int, data: bytes):
        self.base = int(base)
        self.data = bytes(data)
        self.closed = 0

    def open_process(self, _pid: int):
        return object()

    def close_process(self, _handle) -> None:
        self.closed += 1

    def read(self, _handle, address: int, size: int) -> bytes:
        offset = int(address) - self.base
        if offset < 0 or offset + int(size) > len(self.data):
            raise RuntimeError("host read outside mapped SAV image")
        return self.data[offset:offset + int(size)]


class _MappedClient:
    def __init__(self, base: int, data: bytes):
        self.base = int(base)
        self.data = bytes(data)

    def read_memory(self, address: int, size: int) -> bytes:
        offset = int(address) - self.base
        if offset < 0 or offset + int(size) > len(self.data):
            raise RuntimeError("guest read outside mapped SAV image")
        return self.data[offset:offset + int(size)]


def test_alpha21_live_save_mirror_reads_new_pc_even_when_main_pc_was_empty() -> None:
    saved, live = _saved_and_live_images()
    host_base = 0x50000000
    guest_base = 0x33000000
    memory = _MappedMemory(host_base, live)
    client = _MappedClient(guest_base, live)
    reader = SimpleNamespace(move_names={33: "Placaje", 45: "Gruñido"})
    writer = SMLiveWriter(reader, host_memory_factory=lambda: memory)

    # Items ya queda demostrado por contenido+host+guest en la ruta real. En esta
    # prueba aislamos la nueva cadena RELATIVA a partir de esa base demostrada.
    writer._resolve_live_utility_block = lambda **_kwargs: (
        object(), host_base, guest_base, live[:SM_SAVE_ITEM_BLOCK_SIZE]
    )
    current = SaveGameData("Pokémon Sol", "SAV7SM", 7, "Timper", [_party_mon()], {})
    target = HostPartyTarget(77, "azahar.exe", host_base + 0x900000)

    pid, host_pc, guest_pc, parsed, evaluated = writer._resolve_pc_from_live_save_mirror(
        client=client, host_memory=memory, party_base=0x34195E10, party_targets=[target],
        saved_bytes=saved, current=current, anchors=[], box_count=32, box_slot_count=30,
    )

    assert pid == 77
    assert host_pc == host_base + SM_SAVE_PC_BLOCK_OFFSET
    assert guest_pc == guest_base + SM_SAVE_PC_BLOCK_OFFSET
    assert parsed[(4, 8)] is not None
    assert parsed[(4, 8)].species_id == 25
    assert parsed[(4, 8)].pid == 0x1234ABCD
    assert parsed[(1, 1)] is None
    assert evaluated[-1]["accepted"] is True


def test_alpha21_live_save_mirror_tries_later_duplicate_party_anchor_after_first_fails() -> None:
    saved, live = _saved_and_live_images()
    host_base = 0x51000000
    guest_base = 0x34000000
    memory = _MappedMemory(host_base, live)
    client = _MappedClient(guest_base, live)
    writer = SMLiveWriter(SimpleNamespace(move_names={33: "Placaje", 45: "Gruñido"}))
    targets = [
        HostPartyTarget(77, "azahar.exe", 0x11110000),
        HostPartyTarget(77, "azahar.exe", 0x22220000),
    ]

    def exact_resolver(**kwargs):
        target = kwargs["host_target"]
        if int(target.host_party_base) == 0x11110000:
            raise SMLiveError("primera copia no enlaza con Items")
        return object(), host_base, guest_base, live[:SM_SAVE_ITEM_BLOCK_SIZE]

    writer._resolve_live_utility_block = exact_resolver
    writer._resolve_live_items_structurally = lambda **kwargs: (_ for _ in ()).throw(
        SMLiveError("primera copia tampoco supera prueba estructural")
    ) if int(kwargs["host_target"].host_party_base) == 0x11110000 else (
        object(), host_base, guest_base, live[:SM_SAVE_ITEM_BLOCK_SIZE]
    )

    result = writer._resolve_pc_from_live_save_mirror(
        client=client, host_memory=memory, party_base=0x34195E10, party_targets=targets,
        saved_bytes=saved, current=SaveGameData("Pokémon Sol", "SAV7SM", 7, "T", [_party_mon()], {}),
        anchors=[], box_count=32, box_slot_count=30,
    )
    assert result[0] == 77
    assert any(entry.get("rejected", "").startswith("items-proof-failed") for entry in result[4])
    assert any(entry.get("accepted") is True for entry in result[4])


def test_alpha21_live_save_mirror_rejects_wrong_relative_boxlayout() -> None:
    saved, live = _saved_and_live_images()
    live = bytearray(live)
    # Rompe por completo BoxLayout en host+guest: ya no existe evidencia de que
    # Items y BoxPokemon pertenezcan a la misma imagen SAV7SM.
    live[SM_SAVE_BOX_LAYOUT_BLOCK_OFFSET:SM_SAVE_BOX_LAYOUT_BLOCK_OFFSET + SM_SAVE_BOX_LAYOUT_BLOCK_SIZE] = b"\0" * SM_SAVE_BOX_LAYOUT_BLOCK_SIZE
    live = bytes(live)
    host_base = 0x52000000
    guest_base = 0x35000000
    memory = _MappedMemory(host_base, live)
    client = _MappedClient(guest_base, live)
    writer = SMLiveWriter(SimpleNamespace(move_names={33: "Placaje", 45: "Gruñido"}))
    writer._resolve_live_utility_block = lambda **_kwargs: (
        object(), host_base, guest_base, live[:SM_SAVE_ITEM_BLOCK_SIZE]
    )

    with pytest.raises(SMLiveError, match=r"Items \+ Misc \+ BoxLayout \+ BoxPokemon"):
        writer._resolve_pc_from_live_save_mirror(
            client=client, host_memory=memory, party_base=0x34195E10,
            party_targets=[HostPartyTarget(77, "azahar.exe", 0x11110000)], saved_bytes=saved,
            current=SaveGameData("Pokémon Sol", "SAV7SM", 7, "T", [_party_mon()], {}),
            anchors=[], box_count=32, box_slot_count=30,
        )


class _ReadPCClient:
    def __init__(self, process):
        self.process = process

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def process_list(self):
        return [self.process]

    def set_process(self, _pid):
        return None


class _ReadPCHost:
    def find_party_targets(self, **_kwargs):
        return [HostPartyTarget(91, "azahar.exe", 0x60000000)]


def test_alpha21_read_pc_falls_back_to_live_save_mirror_when_main_has_no_positioned_pc_mon(tmp_path: Path) -> None:
    saved, _live = _saved_and_live_images()
    save = tmp_path / "main"
    save.write_bytes(saved)
    process = SimpleNamespace(title_id=0x0004000000164800, process_id=22, name="main")
    reader = SimpleNamespace(
        move_names={33: "Placaje", 45: "Gruñido"},
        client_factory=lambda: _ReadPCClient(process),
        _find_sm_process=lambda _processes: process,
        _locate_party_base=lambda _client, _process, _current: 0x34195E10,
    )
    host = _ReadPCHost()
    writer = SMLiveWriter(reader, host_memory_factory=lambda: host)
    writer._capture_stable_party = lambda _client, _base: ([b"P" * PK7_PARTY_SIZE], 1)
    live_mon = SavePokemon(
        slot=8, species_id=25, species="Pikachu", nickname="Pikachu", level=0,
        held_item="Ninguno", ability="Ability", moves=["Placaje", "Gruñido", "—", "—"],
        move_ids=[33, 45, 0, 0], is_egg=False, markings=[False] * 6,
        role="SIN ROL", role_symbol="", box=4, box_slot=8, pid=0x1234ABCD, tid=11, sid=22,
    )
    writer._resolve_pc_from_livehex_reference = lambda **_kwargs: (
        91, 0x60004E00, 0x330D9838, {(4, 8): live_mon}, [{"accepted": True}],
    )

    current = SaveGameData("Pokémon Sol", "SAV7SM", 7, "T", [_party_mon()], {})
    _proc, base, parsed = writer.read_pc_for_game(
        current, save, [], box_count=32, box_slot_count=30,
    )
    assert base == 0x330D9838
    assert parsed[(4, 8)].pid == 0x1234ABCD
    assert writer._pc_last_resolution["source"].startswith("LiveHeX SM_v120 reference")
