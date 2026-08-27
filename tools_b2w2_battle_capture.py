from __future__ import annotations

"""Captura manual y de solo lectura para localizar el carril de batalla B2/W2.

No forma parte del backend de producción. Lee únicamente los 4 MiB de RAM DS
del mapeo de melonDS que ya contiene la party nominal validada y conserva un
informe compacto de transiciones; nunca escribe memoria ni guarda dumps.
"""

import ctypes
import json
import struct
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

from app.b2w2_live import B2W2MelonDSReader, DS_RAM_BASE


RAM_SIZE = 0x400000
OUTPUT = Path("diagnostics/manual/b2w2_battle_capture_latest.json")


def _read_ram(pid: int, allocation: int) -> bytes:
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.ReadProcessMemory.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel32.ReadProcessMemory.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(0x0400 | 0x0010, False, int(pid))
    if not handle:
        raise OSError("No se pudo abrir melonDS en modo lectura.")
    try:
        buffer = ctypes.create_string_buffer(RAM_SIZE)
        received = ctypes.c_size_t()
        ok = kernel32.ReadProcessMemory(
            handle, ctypes.c_void_p(int(allocation)), buffer, RAM_SIZE,
            ctypes.byref(received),
        )
        if not ok or received.value != RAM_SIZE:
            raise OSError(f"Lectura RAM DS incompleta: {received.value}/{RAM_SIZE}.")
        return buffer.raw
    finally:
        kernel32.CloseHandle(handle)


def _capture_pair(pid: int, allocation: int) -> tuple[bytes, bytes]:
    """Dos muestras; la estabilidad se exige después, campo por campo."""
    return _read_ram(pid, allocation), _read_ram(pid, allocation)


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def _candidate_rows(states: list[tuple[bytes, bytes]]) -> list[dict[str, object]]:
    rows = []
    # Se examinan words alineadas dentro de la única FCRAM invitada justificada.
    # Un candidato debe permanecer estable al entrar, descender tras daño y
    # cambiar o converger al salir; no se acepta por una coincidencia aislada.
    for offset in range(0, RAM_SIZE - 10, 2):
        pairs = tuple((_u16(a, offset), _u16(b, offset)) for a, b in states)
        if any(a != b for a, b in pairs):
            continue
        values = tuple(a for a, _b in pairs)
        if not (0 < values[1] <= 999 and 0 <= values[2] < values[1]):
            continue
        if values[0] == values[1] == values[2] == values[3]:
            continue
        window = []
        for delta in range(-8, 10, 2):
            at = offset + delta
            window.append(tuple(_u16(state[0], at) for state in states))
        rows.append({
            "guest_address": f"0x{DS_RAM_BASE + offset:08X}",
            "values": values,
            "u16_window_outside_battle_damaged_after": window,
        })
    return rows[:500]


def main() -> None:
    party = B2W2MelonDSReader().read_party()
    print("Captura B2/W2 de solo lectura preparada.")
    print(f"melonDS PID {party.process_id}; party {party.count}/6 validada.")
    print("Deja el juego quieto fuera de combate y pulsa INTRO.")
    input()
    outside = _capture_pair(party.process_id, party.allocation_base)
    print("Entra en un combate salvaje. Antes de recibir daño, deja el juego quieto y pulsa INTRO.")
    input()
    battle = _capture_pair(party.process_id, party.allocation_base)
    print("Haz que uno de tus Pokémon reciba daño. Cuando termine la animación, pulsa INTRO.")
    input()
    damaged = _capture_pair(party.process_id, party.allocation_base)
    print("Termina o huye del combate. Ya fuera y con el juego quieto, pulsa INTRO.")
    input()
    after = _capture_pair(party.process_id, party.allocation_base)
    rows = _candidate_rows([outside, battle, damaged, after])
    payload = {
        "format": "rolerun-b2w2-battle-candidates-v1",
        "captured_at": datetime.now().astimezone().isoformat(),
        "environment": "Pokémon Negro 2 España · melonDS 1.1",
        "process_id": party.process_id,
        "party_identity": [
            [p.species_id, p.pid, p.tid, p.sid, p.current_hp, p.max_hp]
            for p in party.pokemon
        ],
        "candidate_count_saved": len(rows),
        "candidates": rows,
        "note": "Candidatos diagnósticos; ninguno es dirección aceptada para producción.",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Captura terminada: {OUTPUT.resolve()}")
    print(f"Candidatos compactos: {len(rows)}. Ya puedes cerrar esta ventana.")
    input()


if __name__ == "__main__":
    main()
