from __future__ import annotations

"""Traza manual de solo lectura de las dos copias de batalla de quinta.

QUE SEPARA ESTA HERRAMIENTA

Encontrar las dos filas es facil: comparten especie, PS maximos, habilidad y
nivel con el Pokemon que esta luchando. Lo dificil es saber CUAL ES CUAL, porque
fuera de la animacion las dos dicen lo mismo.

Se distinguen por el tiempo. La copia LOGICA baja los PS en cuanto el golpe se
resuelve; la de PRESENTACION los baja al ritmo de la barra, unas decimas
despues. Esta traza muestrea las dos cada 10 ms durante un turno y apunta cuando
cambia cada una: la que cambia mas tarde es la que manda en pantalla.

Importa cual es cual: con la logica como autoridad, RoleRun adelantaria el KO a
la animacion y cantaria una baja que el jugador todavia no ha visto.

No escribe un solo byte en la partida ni activa ninguna capacidad.
"""

import ctypes
import json
import struct
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

from app.b2w2_live import B2W2MelonDSReader, DS_RAM_BASE
from app.gen5_memory import GEN5_MEMORY


# Las dos filas candidatas de cada juego. En Negro 2 ya estan demostradas y
# ordenadas -presentacion primero-; en Blanco salieron de la busqueda por firma
# del 27-08-2026 y esta traza es justo lo que decide su orden.
CANDIDATAS = {
    "b2w2": (0x0225B1B0, 0x0225B5F8),
    "bw": (0x0226D670, 0x0226E348),
}
SAMPLE_SIZE = 14  # especie, max HP, HP, dos words auxiliares, habilidad, nivel
WAIT_SECONDS = 60.0
TAIL_SECONDS = 5.0


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


def main(clave: str = "b2w2") -> None:
    memoria = GEN5_MEMORY[clave]
    bases = CANDIDATAS[clave]
    party = B2W2MelonDSReader(memoria).read_party()
    print(f"Traza temporal de combate · {memoria.label} · solo lectura.")
    print(f"Filas vigiladas: {', '.join(f'0x{b:08X}' for b in bases)}")
    print()
    print("Entra en combate y prepara un turno en el que TU Pokémon reciba daño.")
    print("Pulsa INTRO justo antes de ejecutar el turno y vuelve a melonDS.")
    input()
    COPY_GUEST_BASES = bases
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
        "format": "rolerun-gen5-battle-timing-v1",
        "juego": memoria.key,
        "captured_at": datetime.now().astimezone().isoformat(),
        "environment": f"{memoria.label} España · melonDS 1.1",
        "guest_bases": [f"0x{value:08X}" for value in COPY_GUEST_BASES],
        "field_order": ["species", "max_hp", "current_hp", "aux_1", "aux_2", "ability", "level"],
        "wait_seconds": WAIT_SECONDS,
        "tail_seconds": TAIL_SECONDS,
        "hp_change_detected": changed_at is not None,
        "sample_count": samples,
        "transitions": transitions,
        "note": "Diagnóstico temporal; no constituye aún una dirección de producción.",
    }
    OUTPUT = Path(f"diagnostics/manual/{clave}_battle_timing_latest.json")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Traza terminada: {OUTPUT.resolve()}")
    print("Avisame y seguimos.")
    input()


if __name__ == "__main__":
    import sys

    main(sys.argv[1] if len(sys.argv) > 1 else "b2w2")
