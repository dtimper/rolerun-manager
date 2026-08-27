from __future__ import annotations

"""Diagnóstico read-only para localizar la matriz PC B2/W2 en melonDS.

La party llena permite que una captura nueva vaya directamente a la primera
casilla libre. Se comparan dos snapshots de los únicos 4 MiB de RAM DS ya
identificados y solo se conservan candidatos PK5 checksum-válidos; no se
guardan dumps ni se escribe memoria.
"""

import ctypes
import json
import struct
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

from app.b2w2_live import (
    B2W2MelonDSReader, DS_RAM_BASE, _PERMUTATIONS, _crypt,
)


RAM_SIZE = 0x400000
PK5_STORED_SIZE = 136
OUTPUT = Path("diagnostics/manual/b2w2_pc_capture_latest.json")


def _read_ram(pid: int, allocation: int) -> bytes:
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(0x0400 | 0x0010, False, int(pid))
    if not handle:
        raise OSError("No se pudo abrir melonDS en modo lectura.")
    try:
        data = ctypes.create_string_buffer(RAM_SIZE)
        received = ctypes.c_size_t()
        if not kernel32.ReadProcessMemory(
            handle, ctypes.c_void_p(int(allocation)), data, RAM_SIZE,
            ctypes.byref(received),
        ) or received.value != RAM_SIZE:
            raise OSError("No se pudieron leer completos los 4 MiB de RAM DS.")
        return data.raw
    finally:
        kernel32.CloseHandle(handle)


def _parse_stored(data: bytes) -> dict[str, object] | None:
    if len(data) != PK5_STORED_SIZE or not any(data):
        return None
    pid = struct.unpack_from("<I", data, 0)[0]
    checksum = struct.unpack_from("<H", data, 6)[0]
    body = _crypt(data[8:], checksum)
    if sum(struct.unpack("<64H", body)) & 0xFFFF != checksum:
        return None
    shuffled = [body[i * 32:(i + 1) * 32] for i in range(4)]
    order = _PERMUTATIONS[((pid >> 13) & 31) % 24]
    canonical = data[:8] + b"".join(shuffled[index] for index in order)
    species = struct.unpack_from("<H", canonical, 0x08)[0]
    if not 1 <= species <= 649:
        return None
    nickname = canonical[0x48:0x60].decode("utf-16le", errors="ignore")
    nickname = nickname.split("\uffff", 1)[0].split("\0", 1)[0]
    return {"species_id": species, "nickname": nickname}


def _new_candidates(before: bytes, after: bytes) -> list[dict[str, object]]:
    result = []
    # Las estructuras DS observadas están alineadas a 4 bytes. Se busca solo
    # una entidad nueva completa y checksum-válida dentro de la RAM justificada.
    for offset in range(0, RAM_SIZE - PK5_STORED_SIZE + 1, 4):
        post = after[offset:offset + PK5_STORED_SIZE]
        if post == before[offset:offset + PK5_STORED_SIZE]:
            continue
        parsed = _parse_stored(post)
        if parsed is None:
            continue
        result.append({
            "guest_address": f"0x{DS_RAM_BASE + offset:08X}",
            **parsed,
        })
    return result


def main() -> None:
    reader = B2W2MelonDSReader()
    party = reader.read_party()
    if party.count != 6:
        raise RuntimeError(
            f"Esta captura exige un equipo lleno; ahora hay {party.count}/6 miembros."
        )
    print("Diagnóstico PC B2/W2 preparado (solo lectura).")
    print("Deja el juego fuera de menús y pulsa INTRO para tomar el estado inicial.")
    input()
    before = _read_ram(party.process_id, party.allocation_base)
    print("Captura ahora otro Pokémon. Con el equipo lleno, el juego lo enviará al PC.")
    print("Cuando termine todo el diálogo y puedas moverte otra vez, vuelve aquí y pulsa INTRO.")
    input()
    after = _read_ram(party.process_id, party.allocation_base)
    candidates = _new_candidates(before, after)
    payload = {
        "format": "rolerun-b2w2-pc-candidates-v1",
        "captured_at": datetime.now().astimezone().isoformat(),
        "environment": "Pokémon Negro 2 España · melonDS 1.1",
        "party_count_before": party.count,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "note": "Diagnóstico de solo lectura; no activa writers.",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Captura terminada: {OUTPUT.resolve()}")
    print(f"Candidatos PK5 nuevos: {len(candidates)}. Ya puedes avisar a Codex.")
    input()


if __name__ == "__main__":
    main()
