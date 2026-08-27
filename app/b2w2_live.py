from __future__ import annotations

import ctypes
import os
import struct
from dataclasses import dataclass
from ctypes import wintypes

from . import perf


DS_RAM_BASE = 0x02000000
# Pokémon Negro 2 (España), melonDS 1.1. La dirección invitada se demostró
# mediante una muestra real y se vuelve a validar en cada captura.
PARTY_COUNT = 0x0221E3A8
PARTY_BASE = 0x0221E3AC
PK5_PARTY_SIZE = 220
PK5_STORED_SIZE = 136
MAX_PARTY = 6
# Negro 2 España / melonDS 1.1. Captura controlada del 26-08-2026: con la
# party 6/6, Azurill, Lillipup y el Sewaddle recién capturado ocuparon Caja 1
# slots 1..3. La matriz completa dio 3 PK5 y 717 vacíos checksum-válidos en
# dos lecturas idénticas. Cada caja contiene 30*136 bytes y 16 bytes auxiliares.
PC_BASE = 0x022059A4
PC_BOX_COUNT = 24
PC_BOX_SLOT_COUNT = 30
PC_BOX_STRIDE = 0x1000
PC_BOX_DATA_SIZE = PC_BOX_SLOT_COUNT * PK5_STORED_SIZE
PC_MATRIX_SIZE = PC_BOX_COUNT * PC_BOX_STRIDE
# Negro 2 España / melonDS 1.1. La captura física del 26-08-2026 demostró
# dos filas con el mismo Tepig. La segunda publicó el KO 3,36 s antes y es la
# fuente inmediata; la primera se conserva como testigo de convergencia.
BATTLE_MIRROR_BASE = 0x0225B1B0
BATTLE_IMMEDIATE_BASE = 0x0225B5F8
BATTLE_ROW_SIZE = 14
# Captura controlada del 26-08-2026: el byte situado a +0x14 de la copia de
# presentación pasó 0 -> 1 al mostrarse PAR y volvió a 0 fuera del combate.
# Se lee junto a la fila, pero solo se publica el valor observado (1 = PAR).
BATTLE_STATUS_OFFSET = 0x14
BATTLE_READ_SIZE = BATTLE_STATUS_OFFSET + 1


class B2W2LiveError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class B2W2Pokemon:
    slot: int
    pid: int
    species_id: int
    nickname: str
    level: int
    held_item_id: int
    ability_id: int
    move_ids: tuple[int, int, int, int]
    move_pp: tuple[int, int, int, int]
    move_pp_ups: tuple[int, int, int, int]
    markings: tuple[bool, bool, bool, bool, bool, bool]
    tid: int
    sid: int
    form: int
    nature_id: int
    is_egg: bool
    status_condition: int
    stats: tuple[int, int, int, int, int, int]
    ivs: tuple[int, int, int, int, int, int]
    evs: tuple[int, int, int, int, int, int]
    current_hp: int
    max_hp: int


@dataclass(frozen=True, slots=True)
class B2W2PartyRead:
    process_id: int
    process_name: str
    allocation_base: int
    count: int
    raw: bytes
    pokemon: tuple[B2W2Pokemon, ...]


@dataclass(frozen=True, slots=True)
class B2W2BoxPokemon:
    box: int
    slot: int
    pid: int
    species_id: int
    nickname: str
    experience: int
    held_item_id: int
    ability_id: int
    move_ids: tuple[int, int, int, int]
    markings: tuple[bool, bool, bool, bool, bool, bool]
    tid: int
    sid: int
    form: int
    nature_id: int
    is_egg: bool
    ivs: tuple[int, int, int, int, int, int]
    evs: tuple[int, int, int, int, int, int]


@dataclass(frozen=True, slots=True)
class B2W2PCRead:
    process_id: int
    process_name: str
    allocation_base: int
    guest_base: int
    raw: bytes
    empty_slots: int
    pokemon: tuple[B2W2BoxPokemon, ...]


@dataclass(frozen=True, slots=True)
class B2W2PCMovePlan:
    source_offset: int
    destination_offset: int
    source: bytes
    destination: bytes
    expected: bytes
    pokemon: B2W2BoxPokemon


@dataclass(frozen=True, slots=True)
class B2W2BattleRead:
    active: bool
    party_slot: int | None = None
    current_hp: int = 0
    max_hp: int = 0
    mirror_hp: int = 0
    immediate_hp: int = 0
    converged: bool = False
    status_condition: int = 0


def _crypt(data: bytes, seed: int) -> bytes:
    out = bytearray(data)
    for offset in range(0, len(out), 2):
        seed = (0x41C64E6D * seed + 0x6073) & 0xFFFFFFFF
        value = struct.unpack_from("<H", out, offset)[0] ^ (seed >> 16)
        struct.pack_into("<H", out, offset, value)
    return bytes(out)


def empty_pk5_stored() -> bytes:
    """Representación vacía de un slot PC (136 B) en Negro 2.

    Un slot PC liberado **no** queda a ceros: el juego deja un PK5 almacenado
    cifrado con semilla 0. La captura física ``b2w2_party_resize_latest.json``
    lo demuestra: tras retirar un Pokémon desde el propio juego, el parser de
    producción leyó ``pc_empty: 717`` sin lanzar, y ese parser rechaza 136 ceros
    por checksum inválido. Es además el mismo prefijo que la cola de party ya
    validada físicamente en alpha.13.
    """
    return bytes(8) + _crypt(bytes(128), 0)


def empty_pk5_party() -> bytes:
    """Representación vacía observada al compactar party en Negro 2."""
    return empty_pk5_stored() + _crypt(bytes(84), 0)


_PERMUTATIONS = (
    (0,1,2,3),(0,1,3,2),(0,2,1,3),(0,3,1,2),(0,2,3,1),(0,3,2,1),
    (1,0,2,3),(1,0,3,2),(2,0,1,3),(3,0,1,2),(2,0,3,1),(3,0,2,1),
    (1,2,0,3),(1,3,0,2),(2,1,0,3),(3,1,0,2),(2,3,0,1),(3,2,0,1),
    (1,2,3,0),(1,3,2,0),(2,1,3,0),(3,1,2,0),(2,3,1,0),(3,2,1,0),
)


def parse_pk5_party(data: bytes, slot: int) -> B2W2Pokemon:
    if len(data) != PK5_PARTY_SIZE:
        raise B2W2LiveError("El bloque PK5 no mide 220 bytes.")
    pid = struct.unpack_from("<I", data, 0)[0]
    checksum = struct.unpack_from("<H", data, 6)[0]
    body = _crypt(data[8:136], checksum)
    if sum(struct.unpack("<64H", body)) & 0xFFFF != checksum:
        raise B2W2LiveError("Checksum PK5 inválido.")
    shuffled = [body[index * 32:(index + 1) * 32] for index in range(4)]
    order = _PERMUTATIONS[((pid >> 13) & 31) % 24]
    # PokeCrypto.Shuffle45 coloca en cada posición canónica el bloque cuyo
    # índice declara BlockPosition. Usar la permutación inversa parecía válido
    # para los PID cuyas disposiciones son autoinversas, pero corrompía otras
    # disposiciones (captura real: Lillipup y Patrat) aun con checksum correcto.
    blocks = [shuffled[index] for index in order]
    canonical = data[:8] + b"".join(blocks)
    extension = _crypt(data[136:], pid)
    species = struct.unpack_from("<H", canonical, 0x08)[0]
    if not 1 <= species <= 649:
        raise B2W2LiveError(f"Especie PK5 fuera de rango: {species}.")
    nickname = canonical[0x48:0x60].decode(
        "utf-16le", errors="ignore",
    ).split("\uffff", 1)[0].split("\0", 1)[0]
    level = extension[0x8C - 0x88]
    runtime_status = struct.unpack_from("<I", extension, 0)[0]
    # La prueba física de alpha.5 demostró que el runtime nominal usa 1 para
    # parálisis, no el bitmask PKHeX persistente (64). Los demás valores no se
    # etiquetan hasta observarlos de forma controlada.
    status_condition = 64 if runtime_status == 1 else 0
    current_hp, max_hp, attack, defense, speed, sp_attack, sp_defense = (
        struct.unpack_from("<7H", extension, 0x8E - 0x88)
    )
    iv32 = struct.unpack_from("<I", canonical, 0x38)[0]
    ivs = tuple((iv32 >> shift) & 0x1F for shift in (0, 5, 10, 20, 25, 15))
    evs = tuple(canonical[offset] for offset in (0x18, 0x19, 0x1A, 0x1C, 0x1D, 0x1B))
    move_ids = struct.unpack_from("<4H", canonical, 0x28)
    move_pp = tuple(canonical[0x30:0x34])
    move_pp_ups = tuple(canonical[0x34:0x38])
    marking_value = canonical[0x16]
    if (
        not 1 <= level <= 100 or max_hp <= 0 or current_hp > max_hp
        or any(move_id > 559 for move_id in move_ids)
        or any(pp_up > 3 for pp_up in move_pp_ups)
        or runtime_status > 0xFF
    ):
        raise B2W2LiveError("Estadísticas anexas PK5 incoherentes.")
    return B2W2Pokemon(
        slot=slot,
        pid=pid,
        species_id=species,
        nickname=nickname,
        level=level,
        held_item_id=struct.unpack_from("<H", canonical, 0x0A)[0],
        ability_id=canonical[0x15],
        move_ids=move_ids,
        move_pp=move_pp,
        move_pp_ups=move_pp_ups,
        markings=tuple(bool(marking_value & (1 << index)) for index in range(6)),
        tid=struct.unpack_from("<H", canonical, 0x0C)[0],
        sid=struct.unpack_from("<H", canonical, 0x0E)[0],
        form=(canonical[0x40] >> 3) & 0x1F,
        nature_id=canonical[0x41],
        is_egg=bool(iv32 & (1 << 30)),
        status_condition=status_condition,
        stats=(max_hp, attack, defense, sp_attack, sp_defense, speed),
        ivs=ivs,
        evs=evs,
        current_hp=current_hp,
        max_hp=max_hp,
    )


def parse_pk5_boxed(data: bytes, box: int, slot: int) -> B2W2BoxPokemon | None:
    """Decodifica un PK5 stored; ``None`` representa el vacío PK5 validado."""
    if len(data) != PK5_STORED_SIZE:
        raise B2W2LiveError("El bloque PK5 almacenado no mide 136 bytes.")
    pid, sanity, checksum = struct.unpack_from("<IHH", data, 0)
    body = _crypt(data[8:], checksum)
    if sum(struct.unpack("<64H", body)) & 0xFFFF != checksum:
        raise B2W2LiveError("Checksum PK5 almacenado inválido.")
    shuffled = [body[index * 32:(index + 1) * 32] for index in range(4)]
    order = _PERMUTATIONS[((pid >> 13) & 31) % 24]
    canonical = data[:8] + b"".join(shuffled[index] for index in order)
    species = struct.unpack_from("<H", canonical, 0x08)[0]
    if species == 0:
        if pid or sanity or checksum:
            raise B2W2LiveError("El vacío PK5 no coincide con la representación observada.")
        return None
    if sanity != 0 or not 1 <= species <= 649:
        raise B2W2LiveError("Identidad PK5 almacenada incoherente.")
    move_ids = struct.unpack_from("<4H", canonical, 0x28)
    pp_ups = tuple(canonical[0x34:0x38])
    nature = int(canonical[0x41])
    if any(move > 559 for move in move_ids) or any(value > 3 for value in pp_ups):
        raise B2W2LiveError("Movimientos PK5 almacenados incoherentes.")
    if not 0 <= nature < 25:
        raise B2W2LiveError("Naturaleza PK5 almacenada incoherente.")
    iv32 = struct.unpack_from("<I", canonical, 0x38)[0]
    marking_value = canonical[0x16]
    nickname = canonical[0x48:0x60].decode(
        "utf-16le", errors="ignore",
    ).split("\uffff", 1)[0].split("\0", 1)[0]
    return B2W2BoxPokemon(
        box=int(box), slot=int(slot), pid=pid, species_id=species,
        nickname=nickname,
        experience=struct.unpack_from("<I", canonical, 0x10)[0],
        held_item_id=struct.unpack_from("<H", canonical, 0x0A)[0],
        ability_id=canonical[0x15], move_ids=move_ids,
        markings=tuple(bool(marking_value & (1 << index)) for index in range(6)),
        tid=struct.unpack_from("<H", canonical, 0x0C)[0],
        sid=struct.unpack_from("<H", canonical, 0x0E)[0],
        form=(canonical[0x40] >> 3) & 0x1F, nature_id=nature,
        is_egg=bool(iv32 & (1 << 30)),
        ivs=tuple((iv32 >> shift) & 0x1F for shift in (0, 5, 10, 20, 25, 15)),
        evs=tuple(canonical[offset] for offset in (0x18, 0x19, 0x1A, 0x1C, 0x1D, 0x1B)),
    )


class B2W2MelonDSReader:
    """Lector cerrado de la party nominal B2/W2 dentro del mapeo de melonDS."""

    @perf.timed("b2w2.read_party")
    def read_party(self) -> B2W2PartyRead:
        if os.name != "nt":
            raise B2W2LiveError("melonDS en Windows es obligatorio.")
        candidates = self._list_melonds_processes()
        if not candidates:
            raise B2W2LiveError("melonDS no está abierto.")
        last_error = "No se localizó la RAM DS validada de B2/W2."
        for pid, name in sorted(candidates, reverse=True):
            try:
                result = self._read_process(pid, name)
                if result is not None:
                    return result
            except (OSError, B2W2LiveError) as exc:
                last_error = str(exc)
        raise B2W2LiveError(last_error)

    @staticmethod
    def parse_battle_copies(
        mirror: bytes, immediate: bytes, party: tuple[B2W2Pokemon, ...],
    ) -> B2W2BattleRead:
        if len(mirror) != BATTLE_READ_SIZE or len(immediate) != BATTLE_READ_SIZE:
            raise B2W2LiveError("La fila de batalla B2/W2 tiene tamaño inválido.")
        old = struct.unpack("<7H", mirror[:BATTLE_ROW_SIZE])
        live = struct.unpack("<7H", immediate[:BATTLE_ROW_SIZE])
        if old[0] == live[0] == 0:
            return B2W2BattleRead(False)
        # especie, HP máximo, habilidad y nivel deben identificar de forma única
        # al miembro. El HP del mirror puede estar retrasado; sus metadatos no.
        if (old[0], old[1], old[5], old[6]) != (live[0], live[1], live[5], live[6]):
            raise B2W2LiveError("Las dos copias de batalla no coinciden en identidad.")
        matches = [
            pokemon for pokemon in party
            if (
                pokemon.species_id, pokemon.max_hp, pokemon.ability_id, pokemon.level
            ) == (live[0], live[1], live[5], live[6])
        ]
        if len(matches) != 1:
            raise B2W2LiveError(
                "La fila de batalla no identifica de forma única un miembro del equipo."
            )
        if live[1] <= 0 or live[2] > live[1] or old[2] > old[1]:
            raise B2W2LiveError("Los PS de batalla B2/W2 son incoherentes.")
        runtime_status = int(mirror[BATTLE_STATUS_OFFSET])
        if runtime_status not in (0, 1):
            raise B2W2LiveError(
                f"Estado de batalla B2/W2 no demostrado: {runtime_status}."
            )
        # La captura visual demostró que ``live`` adelanta el resultado del
        # golpe. ``old`` converge después de la animación y gobierna la HUD para
        # no revelar daño/KO antes que el juego.
        return B2W2BattleRead(
            active=True,
            party_slot=matches[0].slot,
            current_hp=old[2],
            max_hp=live[1],
            mirror_hp=old[2],
            immediate_hp=live[2],
            converged=old[2] == live[2],
            status_condition=64 if runtime_status == 1 else 0,
        )

    @staticmethod
    def _read_battle_rows(party_read: B2W2PartyRead) -> B2W2BattleRead:
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.ReadProcessMemory.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        kernel32.ReadProcessMemory.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.OpenProcess(0x0400 | 0x0010, False, party_read.process_id)
        if not handle:
            raise B2W2LiveError("melonDS desapareció antes de leer batalla.")

        def read_guest(guest: int) -> bytes:
            address = party_read.allocation_base + (guest - DS_RAM_BASE)
            buffer = ctypes.create_string_buffer(BATTLE_READ_SIZE)
            received = ctypes.c_size_t()
            if (
                not kernel32.ReadProcessMemory(
                    handle, ctypes.c_void_p(address), buffer, BATTLE_READ_SIZE,
                    ctypes.byref(received),
                )
                or received.value != BATTLE_READ_SIZE
            ):
                raise B2W2LiveError("Lectura incompleta de la fila de batalla.")
            return buffer.raw

        try:
            first = (read_guest(BATTLE_MIRROR_BASE), read_guest(BATTLE_IMMEDIATE_BASE))
            second = (read_guest(BATTLE_MIRROR_BASE), read_guest(BATTLE_IMMEDIATE_BASE))
            if first != second:
                raise B2W2LiveError("La fila de batalla cambió durante la doble lectura.")
            return B2W2MelonDSReader.parse_battle_copies(
                first[0], first[1], party_read.pokemon,
            )
        finally:
            kernel32.CloseHandle(handle)

    def read_battle(self, party_read: B2W2PartyRead) -> B2W2BattleRead:
        return self._read_battle_rows(party_read)

    @staticmethod
    def prepare_pc_move(
        raw: bytes, source_box: int, source_slot: int,
        destination_box: int, destination_slot: int,
    ) -> B2W2PCMovePlan:
        if len(raw) != PC_MATRIX_SIZE:
            raise B2W2LiveError("La matriz PC B2/W2 tiene tamaño inválido.")
        for box, slot in ((source_box, source_slot), (destination_box, destination_slot)):
            if not 1 <= int(box) <= PC_BOX_COUNT or not 1 <= int(slot) <= PC_BOX_SLOT_COUNT:
                raise B2W2LiveError("Origen o destino PC B2/W2 fuera de rango.")
        if (source_box, source_slot) == (destination_box, destination_slot):
            raise B2W2LiveError("Origen y destino PC B2/W2 son el mismo slot.")
        source_offset = (source_box - 1) * PC_BOX_STRIDE + (source_slot - 1) * PK5_STORED_SIZE
        destination_offset = (
            (destination_box - 1) * PC_BOX_STRIDE
            + (destination_slot - 1) * PK5_STORED_SIZE
        )
        source = raw[source_offset:source_offset + PK5_STORED_SIZE]
        destination = raw[destination_offset:destination_offset + PK5_STORED_SIZE]
        pokemon = parse_pk5_boxed(source, source_box, source_slot)
        if pokemon is None:
            raise B2W2LiveError("El origen PC B2/W2 está vacío.")
        if parse_pk5_boxed(destination, destination_box, destination_slot) is not None:
            raise B2W2LiveError("El destino PC B2/W2 debe estar vacío.")
        expected = bytearray(raw)
        expected[source_offset:source_offset + PK5_STORED_SIZE] = destination
        expected[destination_offset:destination_offset + PK5_STORED_SIZE] = source
        return B2W2PCMovePlan(
            source_offset, destination_offset, source, destination,
            bytes(expected), pokemon,
        )

    @staticmethod
    def _write_process_bytes(process_id: int, host_address: int, payload: bytes) -> None:
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WriteProcessMemory.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        kernel32.WriteProcessMemory.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.OpenProcess(0x0400 | 0x0008 | 0x0020, False, process_id)
        if not handle:
            raise B2W2LiveError("Windows no permitió abrir melonDS para escritura.")
        try:
            buffer = ctypes.create_string_buffer(payload)
            written = ctypes.c_size_t()
            if (
                not kernel32.WriteProcessMemory(
                    handle, ctypes.c_void_p(host_address), buffer, len(payload),
                    ctypes.byref(written),
                )
                or written.value != len(payload)
            ):
                raise B2W2LiveError("Escritura PC B2/W2 incompleta.")
        finally:
            kernel32.CloseHandle(handle)

    def move_pc_slot(
        self, party_read: B2W2PartyRead, source_box: int, source_slot: int,
        destination_box: int, destination_slot: int,
        *, expected_identity: tuple[int, int, int] | None = None,
    ) -> B2W2PCRead:
        before = self.read_pc(party_read)
        plan = self.prepare_pc_move(
            before.raw, source_box, source_slot, destination_box, destination_slot,
        )
        if expected_identity is not None and expected_identity != (
            plan.pokemon.pid, plan.pokemon.tid, plan.pokemon.sid,
        ):
            raise B2W2LiveError(
                "La identidad del origen PC B2/W2 cambió justo antes de escribir."
            )
        matrix_host = party_read.allocation_base + (PC_BASE - DS_RAM_BASE)

        def restore() -> None:
            self._write_process_bytes(
                party_read.process_id, matrix_host + plan.source_offset, plan.source,
            )
            self._write_process_bytes(
                party_read.process_id, matrix_host + plan.destination_offset, plan.destination,
            )
            if self.read_pc(party_read).raw != before.raw:
                raise B2W2LiveError(
                    "Rollback PC B2/W2 no confirmado; no guardes la partida."
                )

        try:
            # Destino primero: ante interrupción nunca se pierde la única copia.
            self._write_process_bytes(
                party_read.process_id, matrix_host + plan.destination_offset, plan.source,
            )
            self._write_process_bytes(
                party_read.process_id, matrix_host + plan.source_offset, plan.destination,
            )
            after = self.read_pc(party_read)
            if after.raw != plan.expected:
                raise B2W2LiveError("El readback completo PC B2/W2 no coincide.")
            moved = next((
                item for item in after.pokemon
                if (item.box, item.slot) == (destination_box, destination_slot)
            ), None)
            if moved is None or (moved.pid, moved.tid, moved.sid) != (
                plan.pokemon.pid, plan.pokemon.tid, plan.pokemon.sid,
            ):
                raise B2W2LiveError("La identidad escrita en el destino no coincide.")
            return after
        except Exception:
            restore()
            raise

    def swap_party_pc(
        self, party_read: B2W2PartyRead, party_slot: int, box: int, box_slot: int,
        incoming_party: bytes, *, incoming_identity: tuple[int, int, int],
        outgoing_identity: tuple[int, int, int],
    ) -> tuple[B2W2PartyRead, B2W2PCRead]:
        if len(incoming_party) != PK5_PARTY_SIZE:
            raise B2W2LiveError("El PK5 entrante de party no mide 220 bytes.")
        before_party = self.read_party()
        if (
            before_party.process_id != party_read.process_id
            or before_party.allocation_base != party_read.allocation_base
            or not 0 <= party_slot < before_party.count
        ):
            raise B2W2LiveError("La party B2/W2 cambió antes del intercambio.")
        outgoing = before_party.pokemon[party_slot]
        if (outgoing.pid, outgoing.tid, outgoing.sid) != outgoing_identity:
            raise B2W2LiveError("La identidad saliente de party B2/W2 cambió.")
        before_pc = self.read_pc(before_party)
        pc_offset = (box - 1) * PC_BOX_STRIDE + (box_slot - 1) * PK5_STORED_SIZE
        if not 0 <= pc_offset <= len(before_pc.raw) - PK5_STORED_SIZE:
            raise B2W2LiveError("El slot PC B2/W2 está fuera de rango.")
        incoming_stored = before_pc.raw[pc_offset:pc_offset + PK5_STORED_SIZE]
        incoming = parse_pk5_boxed(incoming_stored, box, box_slot)
        if incoming is None or (incoming.pid, incoming.tid, incoming.sid) != incoming_identity:
            raise B2W2LiveError("La identidad entrante del PC B2/W2 cambió.")
        parsed_incoming = parse_pk5_party(incoming_party, party_slot)
        if (parsed_incoming.pid, parsed_incoming.tid, parsed_incoming.sid) != incoming_identity:
            raise B2W2LiveError("El PK5 de party construido no coincide con el entrante.")
        party_offset = party_slot * PK5_PARTY_SIZE
        outgoing_party = before_party.raw[party_offset:party_offset + PK5_PARTY_SIZE]
        outgoing_stored = outgoing_party[:PK5_STORED_SIZE]
        party_host = before_party.allocation_base + (PARTY_BASE - DS_RAM_BASE) + party_offset
        pc_host = before_party.allocation_base + (PC_BASE - DS_RAM_BASE) + pc_offset

        def restore() -> None:
            self._write_process_bytes(before_party.process_id, pc_host, incoming_stored)
            self._write_process_bytes(before_party.process_id, party_host, outgoing_party)
            restored_party = self.read_party()
            restored_pc = self.read_pc(restored_party)
            if (
                restored_party.pokemon[party_slot].pid != outgoing.pid
                or not any(
                    p.pid == incoming.pid and (p.box, p.slot) == (box, box_slot)
                    for p in restored_pc.pokemon
                )
            ):
                raise B2W2LiveError(
                    "Rollback Equipo↔PC B2/W2 no confirmado; no guardes la partida."
                )

        try:
            self._write_process_bytes(before_party.process_id, pc_host, outgoing_stored)
            self._write_process_bytes(before_party.process_id, party_host, incoming_party)
            after_party = self.read_party()
            after_pc = self.read_pc(after_party)
            live = after_party.pokemon[party_slot]
            if (
                (live.pid, live.tid, live.sid) != incoming_identity
                or live.current_hp != live.max_hp
                or not any(
                    (p.pid, p.tid, p.sid) == outgoing_identity
                    and (p.box, p.slot) == (box, box_slot)
                    for p in after_pc.pokemon
                )
            ):
                raise B2W2LiveError("El readback Equipo↔PC B2/W2 no coincide.")
            return after_party, after_pc
        except Exception:
            restore()
            raise

    def resize_party_pc(
        self, party_read: B2W2PartyRead, *, operation: str,
        party_slot: int, box: int, box_slot: int,
        expected_identity: tuple[int, int, int], incoming_party: bytes | None = None,
    ) -> tuple[B2W2PartyRead, B2W2PCRead]:
        before_party = self.read_party()
        before_pc = self.read_pc(before_party)
        if before_party.process_id != party_read.process_id:
            raise B2W2LiveError("melonDS cambió antes de redimensionar la party.")
        pc_offset = (box - 1) * PC_BOX_STRIDE + (box_slot - 1) * PK5_STORED_SIZE
        if not 0 <= pc_offset <= len(before_pc.raw) - PK5_STORED_SIZE:
            raise B2W2LiveError("El slot PC B2/W2 está fuera de rango.")
        pc_before = before_pc.raw[pc_offset:pc_offset + PK5_STORED_SIZE]
        party_host = before_party.allocation_base + (PARTY_BASE - DS_RAM_BASE)
        count_host = before_party.allocation_base + (PARTY_COUNT - DS_RAM_BASE)
        pc_host = before_party.allocation_base + (PC_BASE - DS_RAM_BASE) + pc_offset
        old_count = before_party.count
        old_raw = before_party.raw

        if operation == "party-to-box":
            if old_count <= 1 or not 0 <= party_slot < old_count:
                raise B2W2LiveError("No se puede depositar ese miembro de la party B2/W2.")
            outgoing = before_party.pokemon[party_slot]
            if (outgoing.pid, outgoing.tid, outgoing.sid) != expected_identity:
                raise B2W2LiveError("La identidad saliente B2/W2 cambió.")
            if parse_pk5_boxed(pc_before, box, box_slot) is not None:
                raise B2W2LiveError("El destino PC B2/W2 ya está ocupado.")
            new_count = old_count - 1
            new_raw = (
                old_raw[:party_slot * PK5_PARTY_SIZE]
                + old_raw[(party_slot + 1) * PK5_PARTY_SIZE:]
                + empty_pk5_party()
            )
            pc_after = old_raw[party_slot * PK5_PARTY_SIZE:party_slot * PK5_PARTY_SIZE + PK5_STORED_SIZE]
        elif operation == "box-to-party":
            if old_count >= MAX_PARTY or incoming_party is None:
                raise B2W2LiveError("No hay una casilla libre de party B2/W2.")
            incoming = parse_pk5_boxed(pc_before, box, box_slot)
            if incoming is None or (incoming.pid, incoming.tid, incoming.sid) != expected_identity:
                raise B2W2LiveError("La identidad entrante B2/W2 cambió.")
            parsed = parse_pk5_party(incoming_party, old_count)
            if (parsed.pid, parsed.tid, parsed.sid) != expected_identity:
                raise B2W2LiveError("El PK5 party entrante B2/W2 no coincide.")
            party_slot = old_count
            new_count = old_count + 1
            new_raw = old_raw + incoming_party
            # El slot PC liberado debe quedar como lo deja el juego: un PK5
            # almacenado cifrado con semilla 0. Escribir 136 ceros hacía que el
            # readback de este mismo writer los rechazara por checksum y toda
            # retirada terminase en rollback.
            pc_after = empty_pk5_stored()
        else:
            raise B2W2LiveError("Operación de tamaño B2/W2 no admitida.")

        def restore() -> None:
            self._write_process_bytes(before_party.process_id, party_host, old_raw)
            self._write_process_bytes(before_party.process_id, pc_host, pc_before)
            self._write_process_bytes(before_party.process_id, count_host, bytes((old_count,)))
            restored = self.read_party()
            restored_pc = self.read_pc(restored)
            if restored.raw != old_raw or restored_pc.raw != before_pc.raw:
                raise B2W2LiveError("Rollback de tamaño B2/W2 no confirmado; no guardes.")

        try:
            self._write_process_bytes(before_party.process_id, pc_host, pc_after)
            self._write_process_bytes(before_party.process_id, party_host, new_raw)
            self._write_process_bytes(before_party.process_id, count_host, bytes((new_count,)))
            after_party = self.read_party()
            after_pc = self.read_pc(after_party)
            if after_party.count != new_count or after_party.raw != new_raw[:new_count * PK5_PARTY_SIZE]:
                raise B2W2LiveError("El readback de party redimensionada B2/W2 no coincide.")
            if operation == "party-to-box":
                if not any(
                    (p.pid, p.tid, p.sid) == expected_identity and (p.box, p.slot) == (box, box_slot)
                    for p in after_pc.pokemon
                ):
                    raise B2W2LiveError("El depositado B2/W2 no aparece en destino.")
            elif any((p.box, p.slot) == (box, box_slot) for p in after_pc.pokemon):
                raise B2W2LiveError("El origen PC B2/W2 no quedó vacío.")
            return after_party, after_pc
        except Exception:
            restore()
            raise

    @staticmethod
    def _read_pc_rows(party_read: B2W2PartyRead) -> B2W2PCRead:
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.ReadProcessMemory.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        kernel32.ReadProcessMemory.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.OpenProcess(0x0400 | 0x0010, False, party_read.process_id)
        if not handle:
            raise B2W2LiveError("melonDS desapareció antes de leer el PC.")

        def read_matrix() -> bytes:
            address = party_read.allocation_base + (PC_BASE - DS_RAM_BASE)
            buffer = ctypes.create_string_buffer(PC_MATRIX_SIZE)
            received = ctypes.c_size_t()
            if not kernel32.ReadProcessMemory(
                handle, ctypes.c_void_p(address), buffer, PC_MATRIX_SIZE,
                ctypes.byref(received),
            ) or received.value != PC_MATRIX_SIZE:
                raise B2W2LiveError("Lectura incompleta de la matriz PC B2/W2.")
            return buffer.raw

        try:
            first, second = read_matrix(), read_matrix()
            if first != second:
                raise B2W2LiveError("La matriz PC B2/W2 cambió durante la doble lectura.")
            empty, pokemon = B2W2MelonDSReader.parse_pc_matrix(first)
            return B2W2PCRead(
                party_read.process_id, party_read.process_name,
                party_read.allocation_base, PC_BASE, first, empty, pokemon,
            )
        finally:
            kernel32.CloseHandle(handle)

    @perf.timed("b2w2.read_pc")
    def read_pc(self, party_read: B2W2PartyRead | None = None) -> B2W2PCRead:
        return self._read_pc_rows(party_read or self.read_party())

    @staticmethod
    def parse_pc_matrix(raw: bytes) -> tuple[int, tuple[B2W2BoxPokemon, ...]]:
        if len(raw) != PC_MATRIX_SIZE:
            raise B2W2LiveError("La matriz PC B2/W2 no mide 24 bloques de 0x1000.")
        pokemon: list[B2W2BoxPokemon] = []
        empty = 0
        for box_index in range(PC_BOX_COUNT):
            start = box_index * PC_BOX_STRIDE
            box_data = raw[start:start + PC_BOX_DATA_SIZE]
            for slot_index in range(PC_BOX_SLOT_COUNT):
                offset = slot_index * PK5_STORED_SIZE
                parsed = parse_pk5_boxed(
                    box_data[offset:offset + PK5_STORED_SIZE],
                    box_index + 1, slot_index + 1,
                )
                if parsed is None:
                    empty += 1
                else:
                    pokemon.append(parsed)
        if empty + len(pokemon) != PC_BOX_COUNT * PC_BOX_SLOT_COUNT:
            raise B2W2LiveError("La matriz PC B2/W2 no contiene 720 slots.")
        return empty, tuple(pokemon)

    @staticmethod
    def _list_melonds_processes() -> list[tuple[int, str]]:
        kernel32 = ctypes.windll.kernel32

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
            ]
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
        if ctypes.cast(snapshot, ctypes.c_void_p).value == ctypes.c_void_p(-1).value:
            raise B2W2LiveError("No se pudieron enumerar los procesos de Windows.")
        result: list[tuple[int, str]] = []
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(entry)
            ok = bool(kernel32.Process32FirstW(snapshot, ctypes.byref(entry)))
            while ok:
                name = str(entry.szExeFile)
                if name.casefold() == "melonds.exe":
                    result.append((int(entry.th32ProcessID), name))
                ok = bool(kernel32.Process32NextW(snapshot, ctypes.byref(entry)))
        finally:
            kernel32.CloseHandle(snapshot)
        return result

    @staticmethod
    def _capture_nominal_candidate(read, allocation: int):
        """Valida dos capturas estables de la unidad completa count+party."""
        nominal_count = int(allocation) + (PARTY_COUNT - DS_RAM_BASE)
        count_1 = read(nominal_count, 1)[0]
        if not 1 <= count_1 <= MAX_PARTY:
            return None
        span = count_1 * PK5_PARTY_SIZE
        raw_1 = read(nominal_count + 4, span)
        count_2 = read(nominal_count, 1)[0]
        raw_2 = read(nominal_count + 4, span)
        if count_1 != count_2 or raw_1 != raw_2:
            return None
        pokemon = tuple(
            parse_pk5_party(
                raw_1[index * PK5_PARTY_SIZE:(index + 1) * PK5_PARTY_SIZE],
                index,
            )
            for index in range(count_1)
        )
        return count_1, raw_1, pokemon

    @staticmethod
    def _read_process(pid: int, name: str) -> B2W2PartyRead | None:
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.ReadProcessMemory.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        kernel32.ReadProcessMemory.restype = wintypes.BOOL
        kernel32.VirtualQueryEx.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
        ]
        kernel32.VirtualQueryEx.restype = ctypes.c_size_t
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(0x0400 | 0x0010, False, pid)
        if not handle:
            return None

        class MBI(ctypes.Structure):
            _fields_ = [
                ("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wintypes.DWORD), ("PartitionId", wintypes.WORD),
                ("RegionSize", ctypes.c_size_t), ("State", wintypes.DWORD),
                ("Protect", wintypes.DWORD), ("Type", wintypes.DWORD),
            ]

        def read(address: int, size: int) -> bytes:
            buffer = ctypes.create_string_buffer(size)
            received = ctypes.c_size_t()
            if (
                not kernel32.ReadProcessMemory(
                    handle, ctypes.c_void_p(address), buffer, size,
                    ctypes.byref(received),
                )
                or received.value != size
            ):
                raise OSError("Lectura incompleta de melonDS.")
            return buffer.raw

        try:
            address = 0
            seen: set[int] = set()
            candidates = []
            # Instrumentación: este recorrido visita todo el espacio de
            # direcciones de melonDS en cada ciclo. Se cuentan regiones y
            # allocations sondeadas para dimensionar el coste real antes de
            # sustituirlo por una base cacheada.
            regions = 0
            with perf.span("b2w2.region_walk") as measure:
                while address < 0x7FFFFFFFFFFF:
                    mbi = MBI()
                    if not kernel32.VirtualQueryEx(
                        handle, ctypes.c_void_p(address), ctypes.byref(mbi),
                        ctypes.sizeof(mbi),
                    ):
                        break
                    regions += 1
                    base = int(mbi.BaseAddress or 0)
                    size = int(mbi.RegionSize or 0)
                    allocation = int(mbi.AllocationBase or 0)
                    if mbi.State == 0x1000 and allocation and allocation not in seen:
                        seen.add(allocation)
                        try:
                            candidate = B2W2MelonDSReader._capture_nominal_candidate(
                                read, allocation,
                            )
                            if candidate is not None:
                                candidates.append((allocation, *candidate))
                        except (OSError, B2W2LiveError, IndexError):
                            pass
                    address = base + max(size, 0x1000)
                measure.add(
                    regions=regions,
                    allocations=len(seen),
                    candidates=len(candidates),
                )
            if len(candidates) > 1:
                raise B2W2LiveError(
                    "melonDS expone varias parties B2/W2 válidas; la lectura es ambigua."
                )
            if not candidates:
                return None
            allocation, count, raw, pokemon = candidates[0]
            return B2W2PartyRead(pid, name, allocation, count, raw, pokemon)
        finally:
            kernel32.CloseHandle(handle)
