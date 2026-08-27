from __future__ import annotations

import ctypes
import json
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

from app.b2w2_live import B2W2MelonDSReader, DS_RAM_BASE, PARTY_BASE, PK5_PARTY_SIZE


OUTPUT = Path("diagnostics/manual/b2w2_party_tail_latest.json")


def read_span(party) -> bytes:
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.ReadProcessMemory.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel32.ReadProcessMemory.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(0x0400 | 0x0010, False, party.process_id)
    if not handle:
        raise RuntimeError("No se pudo abrir melonDS.")
    try:
        size = 6 * PK5_PARTY_SIZE
        buffer = ctypes.create_string_buffer(size)
        received = ctypes.c_size_t()
        address = party.allocation_base + (PARTY_BASE - DS_RAM_BASE)
        if not kernel32.ReadProcessMemory(
            handle, ctypes.c_void_p(address), buffer, size, ctypes.byref(received),
        ) or received.value != size:
            raise RuntimeError("Lectura incompleta del span party 6/6.")
        return buffer.raw
    finally:
        kernel32.CloseHandle(handle)


def snap(reader) -> dict[str, object]:
    party = reader.read_party()
    first = read_span(party)
    second = read_span(party)
    if first != second:
        raise RuntimeError("La party cambió durante la doble lectura.")
    return {
        "count": party.count,
        "identities": [p.pid for p in party.pokemon],
        "slots_hex": [
            first[i * PK5_PARTY_SIZE:(i + 1) * PK5_PARTY_SIZE].hex()
            for i in range(6)
        ],
    }


def main() -> None:
    reader = B2W2MelonDSReader()
    print("Captura del slot liberado B2/W2 preparada (solo lectura).")
    print("Fuera de menús, pulsa INTRO.")
    input()
    before = snap(reader)
    print("Desde el PC DEL JUEGO deposita el SEXTO miembro en Caja 1/slot 4.")
    print("Sal del PC, espera a ver al personaje y pulsa INTRO.")
    input()
    deposited = snap(reader)
    print("Retira de nuevo ese Pokémon desde Caja 1/slot 4 para volver a seis miembros.")
    print("Sal del PC y pulsa INTRO.")
    input()
    restored = snap(reader)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({
        "format": "rolerun-b2w2-party-tail-v1",
        "captured_at": datetime.now().astimezone().isoformat(),
        "before": before, "deposited": deposited, "restored": restored,
    }, indent=2), encoding="utf-8")
    print(f"Captura guardada en {OUTPUT}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}")
    input("Pulsa INTRO para cerrar.")
