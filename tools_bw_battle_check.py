from __future__ import annotations

"""Comprueba qué ve RoleRun en las seis filas de combate de Blanco.

Alpha.66 conectó la lectura por miembro, pero en la primera prueba física el
equipo salió entero con dos Pokémon debilitados en el juego. Puede fallar en
cuatro sitios distintos y adivinar ya ha salido mal tres veces, así que esto
enseña exactamente lo que hay:

  * qué contiene la fila de cada miembro,
  * si `parse_battle_copies` la acepta o la rechaza, y por qué,
  * y qué acabaría publicando el adaptador.

Se ejecuta **con el combate en pantalla**, mejor con alguien debilitado.

No escribe un solo byte en la partida ni activa ninguna capacidad.
"""

import ctypes
import json
import struct
from datetime import datetime
from pathlib import Path

from app.b2w2_live import (
    BATTLE_READ_SIZE,
    BATTLE_STATUS_OFFSET,
    DS_RAM_BASE,
    B2W2LiveError,
    B2W2MelonDSReader,
    _KERNEL32,
)
from app.gen5_memory import GEN5_MEMORY

SALIDA = Path("diagnostics/manual/bw_battle_check_latest.json")


def main() -> None:
    memoria = GEN5_MEMORY["bw"]
    lector = B2W2MelonDSReader(memoria)
    party = lector.read_party()
    print(f"melonDS PID {party.process_id} - {memoria.label}")
    print()
    print("Equipo segun el bloque de equipo (en quinta NO se actualiza en combate):")
    for p in party.pokemon:
        print(f"   {p.slot + 1}. {p.nickname:12} Nv.{p.level:3} PS {p.current_hp}/{p.max_hp}"
              f"  esp={p.species_id} hab={p.ability_id}")

    handle = _KERNEL32.OpenProcess(0x0400 | 0x0010, False, party.process_id)
    if not handle:
        raise OSError("No se pudo abrir melonDS en modo lectura.")

    def leer(guest: int) -> bytes:
        direccion = party.allocation_base + (guest - DS_RAM_BASE)
        buffer = ctypes.create_string_buffer(BATTLE_READ_SIZE)
        recibido = ctypes.c_size_t()
        if not _KERNEL32.ReadProcessMemory(
            handle, ctypes.c_void_p(direccion), buffer, BATTLE_READ_SIZE,
            ctypes.byref(recibido),
        ) or recibido.value != BATTLE_READ_SIZE:
            raise OSError("Lectura incompleta.")
        return buffer.raw

    filas = []
    try:
        print()
        print("Filas de combate, una por miembro:")
        for indice, miembro in enumerate(party.pokemon):
            desplazamiento = indice * memoria.battle_stride
            pres = leer(memoria.battle_presentation + desplazamiento)
            logi = leer(memoria.battle_logical + desplazamiento)
            p7 = struct.unpack("<7H", pres[:14])
            l7 = struct.unpack("<7H", logi[:14])
            estado = pres[BATTLE_STATUS_OFFSET]

            motivo = None
            try:
                lectura = B2W2MelonDSReader.parse_battle_copies(pres, logi, (miembro,))
                veredicto = "aceptada" if lectura.active else "vacia"
                ps = lectura.current_hp if lectura.active else None
            except B2W2LiveError as exc:
                veredicto, ps, motivo = "RECHAZADA", None, str(exc)

            print(f"   {indice + 1}. {miembro.nickname:12} "
                  f"pres esp={p7[0]:4} PS {p7[2]:3}/{p7[1]:3} hab={p7[5]:3} Nv{p7[6]:5} "
                  f"est={estado:3}  -> {veredicto}"
                  + (f" ({motivo[:44]})" if motivo else ""))
            filas.append({
                "slot": indice,
                "mote": miembro.nickname,
                "equipo": {
                    "especie": int(miembro.species_id), "max_hp": int(miembro.max_hp),
                    "habilidad": int(miembro.ability_id), "nivel": int(miembro.level),
                    "ps": int(miembro.current_hp),
                },
                "presentacion": {
                    "direccion": f"0x{memoria.battle_presentation + desplazamiento:08X}",
                    "campos": list(p7), "estado": int(estado),
                },
                "logica": {
                    "direccion": f"0x{memoria.battle_logical + desplazamiento:08X}",
                    "campos": list(l7),
                },
                "veredicto": veredicto,
                "ps_publicados": ps,
                "motivo": motivo,
            })
    finally:
        _KERNEL32.CloseHandle(handle)

    aceptadas = [f for f in filas if f["veredicto"] == "aceptada"]
    print()
    print(f"Filas que RoleRun aceptaria: {len(aceptadas)} de {len(filas)}")
    if not aceptadas:
        print("Ninguna. Por eso el equipo sale entero: sin fila valida se cae al")
        print("bloque de equipo, que en quinta no se actualiza durante el combate.")

    payload = {
        "format": "rolerun-bw-battle-check-v1",
        "captured_at": datetime.now().astimezone().isoformat(),
        "environment": f"{memoria.label} Espana - melonDS 1.1",
        "direcciones": {
            "presentacion": f"0x{memoria.battle_presentation:08X}",
            "logica": f"0x{memoria.battle_logical:08X}",
            "paso": f"0x{memoria.battle_stride:X}",
        },
        "orden_campos": ["especie", "max_hp", "ps", "aux1", "aux2", "habilidad", "nivel"],
        "filas": filas,
        "note": "Diagnostico de solo lectura.",
    }
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(f"Guardado en: {SALIDA.resolve()}")
    print("Avisame y seguimos.")
    input()


if __name__ == "__main__":
    try:
        main()
    except B2W2LiveError as exc:
        print(f"\nNo se pudo leer melonDS: {exc}")
        input()
