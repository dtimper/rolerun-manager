from __future__ import annotations

import ctypes
from ctypes import wintypes

from app.b2w2_live import (
    B2W2LiveError, B2W2MelonDSReader, DS_RAM_BASE, PC_BASE,
    PC_BOX_SLOT_COUNT, PC_BOX_STRIDE, PK5_STORED_SIZE, parse_pk5_boxed,
)


def _number(prompt: str, default: int, minimum: int, maximum: int) -> int:
    raw = input(f"{prompt} [{default}]: ").strip()
    value = default if not raw else int(raw)
    if not minimum <= value <= maximum:
        raise ValueError(f"El valor debe estar entre {minimum} y {maximum}.")
    return value


def _offset(box: int, slot: int) -> int:
    return (box - 1) * PC_BOX_STRIDE + (slot - 1) * PK5_STORED_SIZE


def _write_exact(process_id: int, host_address: int, payload: bytes) -> None:
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
        raise B2W2LiveError("Windows no permitió abrir melonDS para la prueba.")
    try:
        buffer = ctypes.create_string_buffer(payload)
        written = ctypes.c_size_t()
        ok = kernel32.WriteProcessMemory(
            handle, ctypes.c_void_p(host_address), buffer, len(payload),
            ctypes.byref(written),
        )
        if not ok or written.value != len(payload):
            raise B2W2LiveError("Escritura incompleta; se iniciará rollback.")
    finally:
        kernel32.CloseHandle(handle)


def main() -> None:
    print("Prueba B2/W2 PC→PC preparada (escritura transaccional).")
    print("Solo admite un origen ocupado y un destino vacío; cualquier fallo restaura ambos slots.")
    reader = B2W2MelonDSReader()
    party = reader.read_party()
    before = reader.read_pc(party)
    source_box = _number("Caja de origen", 1, 1, 24)
    source_slot = _number("Slot de origen", 2, 1, PC_BOX_SLOT_COUNT)
    destination_box = _number("Caja de destino", 1, 1, 24)
    destination_slot = _number("Slot de destino", 4, 1, PC_BOX_SLOT_COUNT)
    if (source_box, source_slot) == (destination_box, destination_slot):
        raise B2W2LiveError("Origen y destino son el mismo slot.")
    source_offset = _offset(source_box, source_slot)
    destination_offset = _offset(destination_box, destination_slot)
    source = before.raw[source_offset:source_offset + PK5_STORED_SIZE]
    destination = before.raw[destination_offset:destination_offset + PK5_STORED_SIZE]
    pokemon = parse_pk5_boxed(source, source_box, source_slot)
    if pokemon is None:
        raise B2W2LiveError("El origen está vacío.")
    if parse_pk5_boxed(destination, destination_box, destination_slot) is not None:
        raise B2W2LiveError("El destino no está vacío; esta primera prueba no intercambia ocupados.")
    answer = input(
        f"Mover {pokemon.nickname or pokemon.species_id} de Caja {source_box}/slot {source_slot} "
        f"a Caja {destination_box}/slot {destination_slot}? [S/N]: "
    ).strip().casefold()
    if answer not in {"s", "si", "sí"}:
        print("Cancelado sin escribir.")
        return
    matrix_host = party.allocation_base + (PC_BASE - DS_RAM_BASE)

    def restore() -> None:
        _write_exact(party.process_id, matrix_host + source_offset, source)
        _write_exact(party.process_id, matrix_host + destination_offset, destination)
        restored = reader.read_pc(party)
        if restored.raw != before.raw:
            raise B2W2LiveError("ROLLBACK NO CONFIRMADO. Deja el juego quieto y no guardes.")

    try:
        _write_exact(party.process_id, matrix_host + destination_offset, source)
        _write_exact(party.process_id, matrix_host + source_offset, destination)
        after = reader.read_pc(party)
        expected = bytearray(before.raw)
        expected[source_offset:source_offset + PK5_STORED_SIZE] = destination
        expected[destination_offset:destination_offset + PK5_STORED_SIZE] = source
        if after.raw != bytes(expected):
            raise B2W2LiveError("El readback completo no coincide.")
        moved = parse_pk5_boxed(
            after.raw[destination_offset:destination_offset + PK5_STORED_SIZE],
            destination_box, destination_slot,
        )
        if moved is None or (moved.pid, moved.tid, moved.sid) != (pokemon.pid, pokemon.tid, pokemon.sid):
            raise B2W2LiveError("La identidad del destino no coincide.")
    except Exception:
        restore()
        raise
    print("Readback de los 720 slots correcto. Abre el PC en el juego y en RoleRun.")
    keep = input("¿El Pokémon aparece solo en el destino correcto? [S/N]: ").strip().casefold()
    if keep not in {"s", "si", "sí"}:
        restore()
        print("Rollback confirmado; se restauró el estado anterior.")
        return
    final = reader.read_pc(party)
    if final.raw != after.raw:
        restore()
        raise B2W2LiveError("melonDS cambió la matriz antes de confirmar; rollback aplicado.")
    print("PRUEBA CONFIRMADA. Puedes cerrar esta ventana.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}")
    input("Pulsa INTRO para cerrar.")
