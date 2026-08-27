from __future__ import annotations

"""Traza manual read-only de las dos copias de batalla observadas en B2/W2."""

import ctypes
import json
import struct
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

from app.b2w2_live import B2W2MelonDSReader, DS_RAM_BASE


COPY_GUEST_BASES = (0x0225B1B0, 0x0225B5F8)
SAMPLE_SIZE = 14  # especie, max HP, HP, dos words auxiliares, habilidad, nivel
WAIT_SECONDS = 60.0
TAIL_SECONDS = 5.0
OUTPUT = Path("diagnostics/manual/b2w2_battle_timing_latest.json")


def _open_read_handle(pid: int):
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(0x0400 | 0x0010, False, int(pid))
    if not handle:
        raise OSError("No se pudo abrir melonDS en modo lectura.")
    return kernel32, handle


def _read(kernel32, handle, address: int) -> bytes:
    kernel32.ReadProcessMemory.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel32.ReadProcessMemory.restype = wintypes.BOOL
    buffer = ctypes.create_string_buffer(SAMPLE_SIZE)
    received = ctypes.c_size_t()
    ok = kernel32.ReadProcessMemory(
        handle, ctypes.c_void_p(address), buffer, SAMPLE_SIZE,
        ctypes.byref(received),
    )
    if not ok or received.value != SAMPLE_SIZE:
        raise OSError("Lectura incompleta durante la traza.")
    return buffer.raw


def _decode(raw: bytes) -> list[int]:
    return list(struct.unpack("<7H", raw))


def main() -> None:
    party = B2W2MelonDSReader().read_party()
    print("Traza temporal de combate B2/W2 preparada (solo lectura).")
    print("Entra en combate y deja listo un turno en el que Tepig vaya a recibir daño.")
    print("Pulsa INTRO justo antes de ejecutar el turno; después vuelve a melonDS.")
    input()
    kernel32, handle = _open_read_handle(party.process_id)
    host_addresses = [
        party.allocation_base + (guest - DS_RAM_BASE) for guest in COPY_GUEST_BASES
    ]
    started = time.perf_counter()
    last = None
    baseline_hp = None
    changed_at = None
    transitions = []
    samples = 0
    try:
        while time.perf_counter() - started < WAIT_SECONDS:
            now_ms = round((time.perf_counter() - started) * 1000, 3)
            values = tuple(_decode(_read(kernel32, handle, address)) for address in host_addresses)
            samples += 1
            hp_pair = (values[0][2], values[1][2])
            if baseline_hp is None:
                baseline_hp = hp_pair
                print(f"Esperando cambio de PS desde {baseline_hp[0]}...")
            elif changed_at is None and hp_pair != baseline_hp:
                changed_at = time.perf_counter()
                print(f"Cambio detectado: {baseline_hp} -> {hp_pair}. Registrando cola...")
            if values != last:
                transitions.append({"ms": now_ms, "copy_1": values[0], "copy_2": values[1]})
                last = values
            if changed_at is not None and time.perf_counter() - changed_at >= TAIL_SECONDS:
                break
            time.sleep(0.01)
    finally:
        kernel32.CloseHandle(handle)
    payload = {
        "format": "rolerun-b2w2-battle-timing-v1",
        "captured_at": datetime.now().astimezone().isoformat(),
        "environment": "Pokémon Negro 2 España · melonDS 1.1",
        "guest_bases": [f"0x{value:08X}" for value in COPY_GUEST_BASES],
        "field_order": ["species", "max_hp", "current_hp", "aux_1", "aux_2", "ability", "level"],
        "wait_seconds": WAIT_SECONDS,
        "tail_seconds": TAIL_SECONDS,
        "hp_change_detected": changed_at is not None,
        "sample_count": samples,
        "transitions": transitions,
        "note": "Diagnóstico temporal; no constituye aún una dirección de producción.",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Traza terminada: {OUTPUT.resolve()}")
    print("Ya puedes avisar a Codex.")
    input()


if __name__ == "__main__":
    main()
