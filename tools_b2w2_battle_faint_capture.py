from __future__ import annotations

"""Traza manual de solo lectura de una baja DURANTE el combate en B2/W2.

Responde a dos preguntas que ninguna captura anterior contesta y que no se pueden
suponer:

1. ¿El **bloque de party** (0x0221E3AC) refleja el daño mientras dura el combate,
   o solo se actualiza al terminar? RoleRun lee la party para detectar bajas, así
   que si el juego no la toca hasta el final, la baja no puede verse antes.

2. ¿Qué hace la **lane de presentación** en el momento exacto de la muerte? En
   particular el byte de estado de 0x0225B1C4: ``parse_battle_copies`` rechaza
   cualquier valor que no sea 0 o 1, y un rechazo deja la lane sin confirmar.

No escribe un solo byte en la partida ni activa ninguna capacidad. Ejecuta además
el **parser de producción** en cada muestra y anota si acepta o rechaza, y por
qué: así el diagnóstico dice lo que RoleRun ve de verdad, no lo que deberíamos
suponer que ve.
"""

import json
import struct
import time
from datetime import datetime
from pathlib import Path

from app.b2w2_live import (
    BATTLE_IMMEDIATE_BASE,
    BATTLE_MIRROR_BASE,
    BATTLE_READ_SIZE,
    BATTLE_ROW_SIZE,
    BATTLE_STATUS_OFFSET,
    DS_RAM_BASE,
    PARTY_BASE,
    PARTY_COUNT,
    PK5_PARTY_SIZE,
    B2W2LiveError,
    B2W2MelonDSReader,
    _KERNEL32,
    parse_pk5_party,
)

DURACION_SEGUNDOS = 180.0
INTERVALO_SEGUNDOS = 0.10
SALIDA = Path("diagnostics/manual/b2w2_battle_faint_latest.json")


def _abrir(pid: int):
    handle = _KERNEL32.OpenProcess(0x0400 | 0x0010, False, int(pid))
    if not handle:
        raise OSError("No se pudo abrir melonDS en modo lectura.")
    return handle


def _leer(handle, direccion: int, tamano: int) -> bytes:
    import ctypes

    buffer = ctypes.create_string_buffer(tamano)
    recibido = ctypes.c_size_t()
    ok = _KERNEL32.ReadProcessMemory(
        handle, ctypes.c_void_p(direccion), buffer, tamano, ctypes.byref(recibido),
    )
    if not ok or recibido.value != tamano:
        raise OSError("Lectura incompleta durante la traza.")
    return buffer.raw


def _party_hp(handle, base: int) -> tuple[int, list[dict]]:
    """PS de cada miembro leídos del bloque de party, con el parser real."""
    cuenta = _leer(handle, base + (PARTY_COUNT - DS_RAM_BASE), 1)[0]
    cuenta = max(0, min(6, int(cuenta)))
    if cuenta == 0:
        return 0, []
    crudo = _leer(handle, base + (PARTY_BASE - DS_RAM_BASE), cuenta * PK5_PARTY_SIZE)
    miembros = []
    for indice in range(cuenta):
        bloque = crudo[indice * PK5_PARTY_SIZE:(indice + 1) * PK5_PARTY_SIZE]
        try:
            pokemon = parse_pk5_party(bloque, indice)
        except B2W2LiveError as exc:
            miembros.append({"slot": indice, "error": str(exc)})
            continue
        miembros.append({
            "slot": indice,
            "species": pokemon.species_id,
            "hp": pokemon.current_hp,
            "max_hp": pokemon.max_hp,
            "status": pokemon.status_condition,
        })
    return cuenta, miembros


def main() -> None:
    lector = B2W2MelonDSReader()
    party = lector.read_party()
    print(f"melonDS PID {party.process_id} · base 0x{party.allocation_base:X}")
    print(f"Equipo detectado: {party.count} miembros.")
    print()
    print("INSTRUCCIONES")
    print("  1. Entra en un combate.")
    print("  2. Deja que uno de tus Pokémon se debilite.")
    print("  3. Sigue hasta que termine el combate y vuelve al mapa.")
    print(f"  4. La traza se detiene sola a los {int(DURACION_SEGUNDOS)} segundos.")
    print()
    input("Cuando estes listo, pulsa INTRO y entra en combate...")

    handle = _abrir(party.process_id)
    base = party.allocation_base
    muestras: list[dict] = []
    anterior: tuple | None = None
    inicio = time.perf_counter()
    try:
        while time.perf_counter() - inicio < DURACION_SEGUNDOS:
            ahora = (time.perf_counter() - inicio) * 1000.0
            try:
                cuenta, miembros = _party_hp(handle, base)
            except (OSError, B2W2LiveError) as exc:
                cuenta, miembros = -1, [{"error": str(exc)}]

            filas = {}
            for etiqueta, guest in (
                ("mirror", BATTLE_MIRROR_BASE), ("immediate", BATTLE_IMMEDIATE_BASE),
            ):
                try:
                    crudo = _leer(handle, base + (guest - DS_RAM_BASE), BATTLE_READ_SIZE)
                except OSError as exc:
                    filas[etiqueta] = {"error": str(exc)}
                    continue
                filas[etiqueta] = {
                    "row": list(struct.unpack("<7H", crudo[:BATTLE_ROW_SIZE])),
                    "status_byte": crudo[BATTLE_STATUS_OFFSET],
                }

            # Lo que el parser de producción concluye con esas mismas filas.
            veredicto: dict
            try:
                lectura = B2W2MelonDSReader.parse_battle_copies(
                    _leer(handle, base + (BATTLE_MIRROR_BASE - DS_RAM_BASE), BATTLE_READ_SIZE),
                    _leer(handle, base + (BATTLE_IMMEDIATE_BASE - DS_RAM_BASE), BATTLE_READ_SIZE),
                    party.pokemon,
                )
                veredicto = {
                    "aceptado": True,
                    "active": lectura.active,
                    "party_slot": lectura.party_slot,
                    "current_hp": lectura.current_hp,
                    "max_hp": lectura.max_hp,
                    "converged": lectura.converged,
                    "status": lectura.status_condition,
                }
            except Exception as exc:
                veredicto = {"aceptado": False, "motivo": str(exc)}

            firma = (
                cuenta,
                tuple((m.get("hp"), m.get("status")) for m in miembros),
                tuple(
                    tuple(filas[k].get("row", ())) + (filas[k].get("status_byte"),)
                    for k in ("mirror", "immediate")
                ),
                veredicto.get("aceptado"), veredicto.get("motivo"),
            )
            if firma != anterior:
                anterior = firma
                muestras.append({
                    "ms": round(ahora, 1),
                    "party_count": cuenta,
                    "party": miembros,
                    "battle_rows": filas,
                    "parser_de_produccion": veredicto,
                })
            time.sleep(INTERVALO_SEGUNDOS)
    finally:
        _KERNEL32.CloseHandle(handle)

    payload = {
        "format": "rolerun-b2w2-battle-faint-v1",
        "captured_at": datetime.now().astimezone().isoformat(),
        "environment": "Pokémon Negro 2 España · melonDS 1.1",
        "pregunta_1": (
            "¿El bloque de party refleja el daño durante el combate o solo al "
            "terminar? Mirar cuándo cambia party[].hp."
        ),
        "pregunta_2": (
            "¿Qué hace la lane de presentación al morir? Mirar status_byte y "
            "parser_de_produccion.motivo cuando el HP llega a 0."
        ),
        "duracion_segundos": DURACION_SEGUNDOS,
        "intervalo_segundos": INTERVALO_SEGUNDOS,
        "cambios_registrados": len(muestras),
        "muestras": muestras,
        "note": "Diagnóstico de solo lectura; no activa ninguna capacidad ni escribe RAM.",
    }
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(f"Traza terminada: {SALIDA.resolve()}")
    print(f"Se registraron {len(muestras)} cambios.")
    print("Avísame y dime que ya está.")
    input()


if __name__ == "__main__":
    main()
