from __future__ import annotations

import struct
from types import SimpleNamespace

import pytest

from app.oras_live import encrypt_pk6
from app.save_engine_client import SaveGameData, SavePokemon
from app.sm_live import (
    PK7_PARTY_SIZE,
    PK7_STORED_SIZE,
    SM_PC_LIVEHEX_B1S1_REFERENCE,
    SMLiveError,
    SMLiveWriter,
)
from app.win_process_memory import HostPartyTarget


def _checksum(data: bytes) -> int:
    return sum(struct.unpack_from('<112H', data, 8)) & 0xFFFF


def _stored_pk7(species: int, pid: int) -> bytes:
    data = bytearray(PK7_PARTY_SIZE)
    struct.pack_into('<I', data, 0x00, 0xA5C30000 ^ int(pid))
    struct.pack_into('<H', data, 0x04, 0)
    struct.pack_into('<H', data, 0x08, int(species))
    struct.pack_into('<H', data, 0x0C, 11)
    struct.pack_into('<H', data, 0x0E, 22)
    data[0x14] = 65
    struct.pack_into('<I', data, 0x18, int(pid))
    struct.pack_into('<H', data, 0x5A, 33)
    struct.pack_into('<I', data, 0x74, 31)
    struct.pack_into('<H', data, 0x06, _checksum(data))
    return encrypt_pk6(bytes(data))[:PK7_STORED_SIZE]


def _party_mon() -> SavePokemon:
    return SavePokemon(
        slot=1, species_id=6, species='Charizard', nickname='Party', level=30,
        held_item='Ninguno', ability='Ability', moves=['A', '—', '—', '—'],
        move_ids=[1, 0, 0, 0], is_egg=False, markings=[False] * 6,
        role='SIN ROL', role_symbol='', pid=0x99887766, tid=11, sid=22,
    )


class _Memory:
    def __init__(self, *, host_base: int, matrix: bytes, region_base: int, region_size: int):
        self.host_base = int(host_base)
        self.matrix = bytes(matrix)
        self.region_base = int(region_base)
        self.region_size = int(region_size)

    def writable_region_for_address(self, *, pid: int, address: int):
        assert self.region_base <= int(address) < self.region_base + self.region_size
        return self.region_base, self.region_size

    def open_process(self, _pid: int):
        return object()

    def close_process(self, _handle):
        return None

    def read(self, _handle, address: int, size: int) -> bytes:
        assert int(address) == self.host_base
        assert int(size) == len(self.matrix)
        return self.matrix


class _Client:
    def __init__(self, matrix: bytes):
        self.matrix = bytes(matrix)

    def read_memory(self, address: int, size: int) -> bytes:
        assert int(address) == SM_PC_LIVEHEX_B1S1_REFERENCE
        assert int(size) == len(self.matrix)
        return self.matrix


def test_alpha25_livehex_reference_is_candidate_but_requires_full_host_guest_proof() -> None:
    slots = 32 * 30
    matrix = bytearray(slots * PK7_STORED_SIZE)
    matrix[2 * PK7_STORED_SIZE:3 * PK7_STORED_SIZE] = _stored_pk7(25, 0x11112222)

    party_guest = 0x34195E10
    host_pc = 0x50010000
    host_party = host_pc + (party_guest - SM_PC_LIVEHEX_B1S1_REFERENCE)
    region_base = 0x50000000
    region_size = 0x02000000
    target = HostPartyTarget(77, 'azahar.exe', host_party)

    writer = SMLiveWriter(SimpleNamespace(move_names={33: 'Placaje'}))
    current = SaveGameData('Pokémon Sol', 'SAV7SM', 7, 'T', [_party_mon()], {})
    pid, resolved_host, resolved_guest, parsed, evaluated = writer._resolve_pc_from_livehex_reference(
        client=_Client(bytes(matrix)),
        host_memory=_Memory(host_base=host_pc, matrix=bytes(matrix), region_base=region_base, region_size=region_size),
        party_base=party_guest,
        party_targets=[target],
        current=current,
        anchors=[],
        box_count=32,
        box_slot_count=30,
    )
    assert pid == 77
    assert resolved_host == host_pc
    assert resolved_guest == SM_PC_LIVEHEX_B1S1_REFERENCE
    assert parsed[(1, 3)] is not None and parsed[(1, 3)].species_id == 25
    assert any(x.get('accepted') is True for x in evaluated)


def test_pc_selector_anchors_including_the_live_party_do_not_block_a_valid_match() -> None:
    """Reportado por el usuario 04-09-2026: RoleRun no abría CAJAS PC de Sol/Luna
    ni siquiera tras guardar la partida (descartando el archivo desfasado).

    Causa real: `_open_pc_selector_from_live_matrix` (app/ui.py) mete el equipo
    vivo completo entre los anchors -para dar nombre/nivel localizado a testigos
    con caja/slot conocidos, junto a los del guardado y las anclas recordadas-.
    Como un Pokémon de equipo llega con box=None/box_slot=None igual que un
    testigo real "recién salido al PC", sin restar la party viva el testigo
    exigido era EXACTAMENTE lo que `boxpokemon-overlaps-live-party` ya prohíbe
    encontrar en el PC: ninguna dirección, ni siquiera la correcta, podía
    superar la prueba. Aquí se reproduce pasando el propio Charizard de la
    party (`current.party[0]`) como único anchor -tal como hace esa función-, y
    se comprueba que un PC válido, sin ningún solapamiento real, se acepta.
    """
    slots = 32 * 30
    matrix = bytearray(slots * PK7_STORED_SIZE)
    matrix[2 * PK7_STORED_SIZE:3 * PK7_STORED_SIZE] = _stored_pk7(25, 0x11112222)

    party_guest = 0x34195E10
    host_pc = 0x50010000
    host_party = host_pc + (party_guest - SM_PC_LIVEHEX_B1S1_REFERENCE)
    region_base = 0x50000000
    region_size = 0x02000000
    target = HostPartyTarget(77, 'azahar.exe', host_party)

    writer = SMLiveWriter(SimpleNamespace(move_names={33: 'Placaje'}))
    party_member = _party_mon()
    current = SaveGameData('Pokémon Sol', 'SAV7SM', 7, 'T', [party_member], {})

    pid, resolved_host, resolved_guest, parsed, evaluated = writer._resolve_pc_from_livehex_reference(
        client=_Client(bytes(matrix)),
        host_memory=_Memory(host_base=host_pc, matrix=bytes(matrix), region_base=region_base, region_size=region_size),
        party_base=party_guest,
        party_targets=[target],
        current=current,
        # Exactamente lo que `_open_pc_selector_from_live_matrix` añade: el
        # propio equipo vivo, sin caja/slot -no un testigo real de salida-.
        anchors=[party_member],
        box_count=32,
        box_slot_count=30,
    )
    assert pid == 77
    assert resolved_host == host_pc
    assert resolved_guest == SM_PC_LIVEHEX_B1S1_REFERENCE
    assert parsed[(1, 3)] is not None and parsed[(1, 3)].species_id == 25
    assert any(x.get('accepted') is True for x in evaluated)
    assert not any(x.get('rejected') == 'missing-recent-party-to-pc-witness' for x in evaluated)


def test_alpha25_livehex_reference_rejects_host_guest_mismatch() -> None:
    slots = 32 * 30
    guest_matrix = bytearray(slots * PK7_STORED_SIZE)
    guest_matrix[0:PK7_STORED_SIZE] = _stored_pk7(25, 0x11112222)
    host_matrix = bytearray(guest_matrix)
    host_matrix[PK7_STORED_SIZE:2 * PK7_STORED_SIZE] = _stored_pk7(133, 0x33334444)

    party_guest = 0x34195E10
    host_pc = 0x50010000
    host_party = host_pc + (party_guest - SM_PC_LIVEHEX_B1S1_REFERENCE)
    target = HostPartyTarget(77, 'azahar.exe', host_party)
    writer = SMLiveWriter(SimpleNamespace(move_names={33: 'Placaje'}))
    current = SaveGameData('Pokémon Sol', 'SAV7SM', 7, 'T', [_party_mon()], {})

    with pytest.raises(SMLiveError, match='referencia live'):
        writer._resolve_pc_from_livehex_reference(
            client=_Client(bytes(guest_matrix)),
            host_memory=_Memory(host_base=host_pc, matrix=bytes(host_matrix), region_base=0x50000000, region_size=0x02000000),
            party_base=party_guest,
            party_targets=[target],
            current=current,
            anchors=[],
            box_count=32,
            box_slot_count=30,
        )
    assert writer._pc_last_resolution['proofs'] == 0
    assert writer._pc_last_resolution['evaluated'][0]['rejected'].startswith('reference-host-guest-full-matrix-proof-failed')
