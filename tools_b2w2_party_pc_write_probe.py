from __future__ import annotations

import ctypes
import struct
from ctypes import wintypes

from app.b2w2_live import (
    B2W2LiveError, B2W2MelonDSReader, DS_RAM_BASE, PARTY_BASE, PC_BASE,
    PC_BOX_STRIDE, PK5_PARTY_SIZE, PK5_STORED_SIZE, _crypt,
)
from app.boxed_metadata import base_stats_for, boxed_level
from app.realtime.b2w2_adapter import B2W2RealTimeAdapter


def write_exact(process_id: int, host_address: int, payload: bytes) -> None:
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
        if not kernel32.WriteProcessMemory(
            handle, ctypes.c_void_p(host_address), buffer, len(payload),
            ctypes.byref(written),
        ) or written.value != len(payload):
            raise B2W2LiveError("Escritura incompleta.")
    finally:
        kernel32.CloseHandle(handle)


def main() -> None:
    print("Prueba B2/W2 PC↔Equipo preparada (escritura transaccional).")
    print("Cierra el menú del juego y deja visible al personaje. RoleRun puede permanecer abierto.")
    input("Pulsa INTRO para validar Lillipup Caja 1/slot 2 y Tepig Equipo/slot 1.")
    reader = B2W2MelonDSReader()
    before_party = reader.read_party()
    before_pc = reader.read_pc(before_party)
    if before_party.count != 6:
        raise B2W2LiveError("Esta prueba exige el equipo 6/6 observado.")
    outgoing = before_party.pokemon[0]
    incoming = next((
        p for p in before_pc.pokemon if (p.box, p.slot) == (1, 2)
    ), None)
    if outgoing.nickname != "Tepig" or incoming is None or incoming.nickname != "Lillipup":
        raise B2W2LiveError("No coinciden Tepig en Equipo/1 y Lillipup en Caja 1/2.")
    if incoming.held_item_id != 0:
        raise B2W2LiveError("La primera prueba exige un Pokémon entrante sin objeto.")
    pc_offset = (incoming.box - 1) * PC_BOX_STRIDE + (incoming.slot - 1) * PK5_STORED_SIZE
    incoming_stored = before_pc.raw[pc_offset:pc_offset + PK5_STORED_SIZE]
    outgoing_party = before_party.raw[:PK5_PARTY_SIZE]
    outgoing_stored = outgoing_party[:PK5_STORED_SIZE]
    base = base_stats_for("b2w2", incoming.species_id, incoming.form)
    level = boxed_level("b2w2", incoming.species_id, incoming.form, incoming.experience)
    stats = B2W2RealTimeAdapter._calculated_stats(
        base, incoming.ivs, incoming.evs, level, incoming.nature_id,
    )  # HP/Atk/Def/SpA/SpD/Spe
    extension = bytearray(PK5_PARTY_SIZE - PK5_STORED_SIZE)
    extension[4] = level
    struct.pack_into(
        "<7H", extension, 6,
        stats[0], stats[0], stats[1], stats[2], stats[5], stats[3], stats[4],
    )
    incoming_party = incoming_stored + _crypt(bytes(extension), incoming.pid)
    party_host = before_party.allocation_base + (PARTY_BASE - DS_RAM_BASE)
    pc_host = before_party.allocation_base + (PC_BASE - DS_RAM_BASE) + pc_offset

    def restore() -> None:
        write_exact(before_party.process_id, pc_host, incoming_stored)
        write_exact(before_party.process_id, party_host, outgoing_party)
        party = reader.read_party()
        pc = reader.read_pc(party)
        if party.pokemon[0].pid != outgoing.pid or not any(
            p.pid == incoming.pid and (p.box, p.slot) == (1, 2) for p in pc.pokemon
        ):
            raise B2W2LiveError("ROLLBACK NO CONFIRMADO. No guardes la partida.")

    answer = input("Aplicar el intercambio controlado Lillipup↔Tepig? [S/N]: ").strip().casefold()
    if answer not in {"s", "si", "sí"}:
        print("Cancelado sin escribir.")
        return
    try:
        # El PC recibe primero una copia completa del saliente; después se
        # publica la party construida según PK5.ResetPartyStats.
        write_exact(before_party.process_id, pc_host, outgoing_stored)
        write_exact(before_party.process_id, party_host, incoming_party)
        party = reader.read_party()
        pc = reader.read_pc(party)
        live = party.pokemon[0]
        if (
            (live.pid, live.tid, live.sid) != (incoming.pid, incoming.tid, incoming.sid)
            or live.current_hp != live.max_hp or live.stats != tuple(stats)
            or not any(p.pid == outgoing.pid and (p.box, p.slot) == (1, 2) for p in pc.pokemon)
        ):
            raise B2W2LiveError("El readback semántico Equipo↔PC no coincide.")
    except Exception:
        restore()
        raise
    print("Readback correcto. Abre EQUIPO en el juego: el primer miembro debe ser Lillipup con PS completos.")
    keep = input("¿El juego muestra correctamente a Lillipup y Tepig está en Caja 1/slot 2? [S/N]: ").strip().casefold()
    if keep not in {"s", "si", "sí"}:
        restore()
        print("Rollback confirmado; Tepig vuelve al equipo y Lillipup al PC.")
        return
    print("PRUEBA CONFIRMADA. El intercambio queda aplicado; puedes cerrar esta ventana.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}")
    input("Pulsa INTRO para cerrar.")
