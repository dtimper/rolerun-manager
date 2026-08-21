from __future__ import annotations

import struct

from app.boxed_metadata import ability_name, boxed_level, exp_growth_for
from app.oras_live import PK6_PARTY_SIZE, PK6_STORED_SIZE, _checksum, encrypt_pk6, parse_pk6_boxed
from app.sm_live import PK7_PARTY_SIZE, PK7_STORED_SIZE, parse_pk7_boxed


def _stored_pk7(*, species: int, pid: int, experience: int, ability_id: int) -> bytes:
    data = bytearray(PK7_PARTY_SIZE)
    struct.pack_into("<I", data, 0x00, 0xA5A50000 ^ int(pid))
    struct.pack_into("<H", data, 0x04, 0)  # sanity
    struct.pack_into("<H", data, 0x08, int(species))
    struct.pack_into("<H", data, 0x0C, 11)
    struct.pack_into("<H", data, 0x0E, 22)
    struct.pack_into("<I", data, 0x10, int(experience))
    data[0x14] = int(ability_id)
    struct.pack_into("<I", data, 0x18, int(pid))
    name = f"M{species}".encode("utf-16le") + b"\0\0"
    data[0x40:0x40 + len(name)] = name
    struct.pack_into("<H", data, 0x5A, 33)
    struct.pack_into("<H", data, 0x5C, 45)
    struct.pack_into("<I", data, 0x74, 31 | (31 << 5))
    # El byte 0xEC pertenece solo a la extensión party; el stored que vuelve de
    # una caja termina en 0xE8. Dejarlo a 0 demuestra que el nivel no sale de ahí.
    data[0xEC] = 0
    struct.pack_into("<H", data, 0x06, _checksum(data))
    return encrypt_pk6(bytes(data))[:PK7_STORED_SIZE]


def _stored_pk6(*, species: int, pid: int, experience: int, ability_id: int) -> bytes:
    data = bytearray(PK6_PARTY_SIZE)
    struct.pack_into("<I", data, 0x00, 0x12345678)
    struct.pack_into("<H", data, 0x04, 0)
    struct.pack_into("<H", data, 0x08, int(species))
    struct.pack_into("<H", data, 0x0C, 12345)
    struct.pack_into("<H", data, 0x0E, 54321)
    struct.pack_into("<I", data, 0x10, int(experience))
    data[0x14] = int(ability_id)
    struct.pack_into("<I", data, 0x18, int(pid))
    name = b"P\x00o\x00o\x00c\x00h\x00y\x00\0\0"
    data[0x40:0x40 + len(name)] = name
    struct.pack_into("<H", data, 0x5A, 33)
    struct.pack_into("<I", data, 0x74, 0x3FFFFFFF)
    data[0xEC] = 0
    struct.pack_into("<H", data, 0x06, _checksum(data))
    return encrypt_pk6(bytes(data))[:PK6_STORED_SIZE]


def test_alpha26_embedded_pkhex_metadata_resolves_known_sm_values() -> None:
    assert exp_growth_for("sm", 731) == 0  # Pikipek: Medium Fast in personal_sm
    assert boxed_level("sm", 731, 0, 64) == 4
    assert ability_name(92) == "Encadenado"


def test_alpha26_sm_boxed_parser_derives_level_and_localizes_ability() -> None:
    raw = _stored_pk7(species=731, pid=0x12345678, experience=64, ability_id=92)
    pokemon = parse_pk7_boxed(raw, 1, 1, {33: "Placaje", 45: "Gruñido"})
    assert pokemon is not None
    assert pokemon.species_id == 731
    assert pokemon.level == 4
    assert pokemon.ability == "Encadenado"


def test_alpha26_oras_boxed_parser_derives_level_and_localizes_ability() -> None:
    # Poochyena usa Medium Fast: 18^3 = 5832 EXP.
    raw = _stored_pk6(species=261, pid=0x89ABCDEF, experience=5832, ability_id=50)
    pokemon = parse_pk6_boxed(raw, 2, 3, {33: "Placaje"}, family="oras")
    assert pokemon is not None
    assert pokemon.species_id == 261
    assert pokemon.level == 18
    assert pokemon.ability == "Fuga"


def test_alpha26_xy_boxed_parser_uses_xy_personal_table() -> None:
    # Pikachu usa Medium Fast; esto prueba explícitamente la familia X/Y.
    raw = _stored_pk6(species=25, pid=0x10203040, experience=1000, ability_id=9)
    pokemon = parse_pk6_boxed(raw, 1, 4, {33: "Placaje"}, family="xy")
    assert pokemon is not None
    assert pokemon.level == 10
    assert pokemon.ability == ability_name(9)
