from __future__ import annotations

"""Comprobación de solo lectura de la dirección de medallas en B2/W2.

POR QUÉ HACE FALTA

La dirección se dedujo sin captura: PKHeX dice que en el guardado las medallas
caen cuatro bytes detrás del dinero, y el dinero en RAM ya estaba demostrado con
una traza de dos estados. El razonamiento es sólido, pero da por hecho que el
bloque vivo respeta el mismo reparto que el guardado más allá del propio dinero,
y eso **no está demostrado**.

Con una medalla ya conseguida en la partida, comprobarlo es inmediato: en el
byte de medallas tiene que haber tantos bits encendidos como medallas se tengan.
Esta herramienta vuelca la zona alrededor del dinero y dice qué posiciones
encajan, para no fiarse de una sola.

No escribe un solo byte en la partida ni activa ninguna capacidad.
"""

import ctypes
import json
from datetime import datetime
from pathlib import Path

from app.b2w2_live import (
    BADGES_ADDRESS,
    DS_RAM_BASE,
    MONEY_ADDRESS,
    MONEY_SIZE,
    B2W2LiveError,
    B2W2MelonDSReader,
    _KERNEL32,
)

MARGEN = 0x20
SALIDA = Path("diagnostics/manual/b2w2_badges_latest.json")


def _leer(pid: int, direccion: int, tamano: int) -> bytes:
    handle = _KERNEL32.OpenProcess(0x0400 | 0x0010, False, int(pid))
    if not handle:
        raise OSError("No se pudo abrir melonDS en modo lectura.")
    try:
        buffer = ctypes.create_string_buffer(tamano)
        recibido = ctypes.c_size_t()
        ok = _KERNEL32.ReadProcessMemory(
            handle, ctypes.c_void_p(direccion), buffer, tamano, ctypes.byref(recibido),
        )
        if not ok or recibido.value != tamano:
            raise OSError("Lectura incompleta de la RAM de melonDS.")
        return buffer.raw
    finally:
        _KERNEL32.CloseHandle(handle)


def _numero(mensaje: str) -> int | None:
    respuesta = input(mensaje).strip()
    if not respuesta:
        return None
    try:
        return max(0, min(8, int(respuesta)))
    except ValueError:
        print("  No era un numero.")
        return None


def main() -> None:
    lector = B2W2MelonDSReader()
    party = lector.read_party()
    pid, base = party.process_id, party.allocation_base
    print(f"melonDS PID {pid} - base 0x{base:X}")
    print(f"Equipo: {party.count} miembros (ancla ya demostrada).")
    print()
    print("=== CUANTAS MEDALLAS TIENES AHORA ===")
    print("Mirala en la mochila del juego o en la tarjeta de entrenador.")
    print()
    esperadas = _numero("  Numero de medallas conseguidas: ")
    if esperadas is None:
        print("\nSin ese dato no se puede comprobar nada.")
        input()
        return

    print()
    print("Leyendo... no toques el juego.")
    inicio = MONEY_ADDRESS - MARGEN
    tamano = MARGEN * 2
    crudo = _leer(pid, base + (inicio - DS_RAM_BASE), tamano)

    dinero = int.from_bytes(
        _leer(pid, base + (MONEY_ADDRESS - DS_RAM_BASE), MONEY_SIZE), "little",
    )

    candidatos = []
    for indice in range(tamano):
        valor = crudo[indice]
        if bin(valor).count("1") != esperadas:
            continue
        candidatos.append({
            "direccion": f"0x{inicio + indice:08X}",
            "valor": f"0x{valor:02X}",
            "bits": bin(valor),
            "distancia_al_dinero": (inicio + indice) - MONEY_ADDRESS,
        })

    esperada = f"0x{BADGES_ADDRESS:08X}"
    acierta = any(c["direccion"] == esperada for c in candidatos)

    print()
    print(f"Dinero leido: {dinero}")
    print(f"Direccion que usa RoleRun: {esperada}")
    print(f"  valor ahi: 0x{crudo[BADGES_ADDRESS - inicio]:02X} -> "
          f"{bin(crudo[BADGES_ADDRESS - inicio]).count('1')} medalla(s)")
    print()
    print(f"{'CUADRA' if acierta else 'NO CUADRA'} con las {esperadas} que has dicho.")
    print()
    print(f"Otros bytes de la zona con {esperadas} bit(s) encendido(s): {len(candidatos)}")
    for candidato in candidatos[:12]:
        marca = "  <-- la que usa RoleRun" if candidato["direccion"] == esperada else ""
        print(f"  {candidato['direccion']}  {candidato['valor']}  "
              f"dinero{candidato['distancia_al_dinero']:+d}{marca}")

    payload = {
        "format": "rolerun-b2w2-badges-v1",
        "captured_at": datetime.now().astimezone().isoformat(),
        "environment": "Pokemon Negro 2 Espana - melonDS 1.1",
        "metodo": (
            "Con N medallas conseguidas, el byte de medallas tiene N bits "
            "encendidos. Se vuelca la zona alrededor del dinero -ya demostrado- "
            "y se listan todas las posiciones que encajan, para no fiarse de una."
        ),
        "medallas_declaradas": esperadas,
        "dinero_leido": dinero,
        "direccion_en_produccion": esperada,
        "direccion_en_produccion_cuadra": acierta,
        "valor_en_produccion": f"0x{crudo[BADGES_ADDRESS - inicio]:02X}",
        "rango_volcado": [f"0x{inicio:08X}", f"0x{inicio + tamano:08X}"],
        "volcado": " ".join(f"{b:02X}" for b in crudo),
        "candidatos": candidatos,
        "note": (
            "Diagnostico de solo lectura. Un byte que coincida una vez no "
            "demuestra nada por si solo; lo que decide es que la direccion en "
            "produccion cuadre y que siga cuadrando con la siguiente medalla."
        ),
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
