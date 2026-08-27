from __future__ import annotations

"""Traza read-only para localizar el estado visible durante combate B2/W2."""

import ctypes
import json
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

from app.b2w2_live import B2W2MelonDSReader, DS_RAM_BASE


RAM_SIZE = 0x400000
OUTPUT = Path("diagnostics/manual/b2w2_battle_status_latest.json")


def _read_ram(pid: int, allocation: int) -> bytes:
    kernel32 = ctypes.windll.kernel32
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
            raise OSError("Lectura incompleta de la RAM DS.")
        return data.raw
    finally:
        kernel32.CloseHandle(handle)


def _pair(pid: int, allocation: int) -> tuple[bytes, bytes]:
    """Conserva ambas lecturas; la estabilidad se exige por candidato."""
    return _read_ram(pid, allocation), _read_ram(pid, allocation)


def _candidates(clear_outside, clear_battle, status_battle, status_outside):
    result = []
    battle_bases = (0x0225B1B0, 0x0225B5F8)
    for offset, values in enumerate(zip(
        *clear_outside, *clear_battle, *status_battle, *status_outside,
    )):
        a1, a2, b1, b2, c1, c2, d1, d2 = values
        if a1 != a2 or b1 != b2 or c1 != c2 or d1 != d2:
            continue
        a, b, c, d = a1, b1, c1, d1
        if a != 0 or b != 0 or c == 0:
            continue
        guest = DS_RAM_BASE + offset
        distance = min(abs(guest - base) for base in battle_bases)
        # El estado puede usar una codificación distinta al volver al overworld.
        # Se conservan ambos valores y se prioriza cercanía a las filas ya
        # demostradas, sin convertirla en requisito ni en offset de producción.
        result.append({
            "guest_address": f"0x{guest:08X}",
            "battle_value": int(c),
            "outside_value": int(d),
            "distance_to_known_battle_row": int(distance),
            "window_hex": status_battle[0][max(0, offset - 12):offset + 13].hex(),
        })
    result.sort(key=lambda item: (
        item["distance_to_known_battle_row"],
        0 if item["outside_value"] else 1,
        item["battle_value"],
    ))
    return result[:1000]


def main() -> None:
    party = B2W2MelonDSReader().read_party()
    print("Traza de estado B2/W2 preparada (solo lectura).")
    print("Cura primero el equipo y elimina cualquier estado. Fuera de menús, pulsa INTRO.")
    input()
    outside_clear = _pair(party.process_id, party.allocation_base)
    print("Entra en combate con el Pokémon sano. Antes de sufrir un estado, deja el combate quieto y pulsa INTRO.")
    input()
    battle_clear = _pair(party.process_id, party.allocation_base)
    print("Haz que el Pokémon activo quede paralizado. Cuando el juego ya muestre PAR, pulsa INTRO.")
    input()
    battle_status = _pair(party.process_id, party.allocation_base)
    print("Termina o huye. Ya fuera del combate, con PAR todavía activo, pulsa INTRO.")
    input()
    outside_status = _pair(party.process_id, party.allocation_base)
    candidates = _candidates(outside_clear, battle_clear, battle_status, outside_status)
    payload = {
        "format": "rolerun-b2w2-battle-status-v1",
        "captured_at": datetime.now().astimezone().isoformat(),
        "environment": "Pokémon Negro 2 España · melonDS 1.1",
        "candidate_count_saved": len(candidates),
        "candidates": candidates,
        "note": "Candidatos diagnósticos de solo lectura; no son offsets de producción.",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Traza terminada: {OUTPUT.resolve()}")
    print(f"Candidatos guardados: {len(candidates)}. Ya puedes avisar a Codex.")
    input()


if __name__ == "__main__":
    main()
