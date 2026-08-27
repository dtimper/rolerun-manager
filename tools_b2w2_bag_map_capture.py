from __future__ import annotations

"""Mapa manual de solo lectura de los bolsillos de la mochila de B2/W2.

La traza de dos estados del 27-08-2026 confirmó **una** posición: la Poción del
jugador estaba en ``0x0221E17C`` y pasó de 2 a 3 unidades en esa misma dirección
al usarla. La casilla contigua contenía Antiparalizador ×2, un objeto por el que
la búsqueda **no** preguntaba: corroboración independiente de que aquello es un
bolsillo real y no otra coincidencia.

Falta el mapa: dónde empieza y acaba cada bolsillo (objetos, Poké Balls, MT,
objetos clave). Con un ancla ya demostrada, basta con volcar la zona de alrededor
decodificada como pares (identificador, cantidad) y ver dónde están las tiras de
objetos válidos.

Comprueba además que el contador de party sigue en su dirección conocida dentro
del mismo bloque. Si el ancla ya demostrada de la party cuadra, el bloque es el
espejo del guardado y no una copia temporal.

No escribe un solo byte en la partida ni activa ninguna capacidad.
"""

import ctypes
import json
import struct
from datetime import datetime
from pathlib import Path

from app.b2w2_live import (
    DS_RAM_BASE,
    PARTY_BASE,
    PARTY_COUNT,
    B2W2LiveError,
    B2W2MelonDSReader,
    _KERNEL32,
)
from app.boxed_metadata import item_name

# Ancla demostrada por la traza de dos estados.
ANCLA_MEDICINAS = 0x0221E17C
# Zona a volcar alrededor del ancla. La party está 0x230 más adelante, así que
# este margen cubre holgadamente los bolsillos vecinos.
MARGEN_ANTES = 0x1400
MARGEN_DESPUES = 0x0400
# Rango de identificadores válidos en quinta generación.
ITEM_MAXIMO = 700
CANTIDAD_MAXIMA = 999
SALIDA = Path("diagnostics/manual/b2w2_bag_map_latest.json")


def _texto(valor: str) -> str:
    import sys

    try:
        valor.encode(sys.stdout.encoding or "utf-8")
        return valor
    except Exception:
        return valor.encode("ascii", "replace").decode("ascii")


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


def main() -> None:
    lector = B2W2MelonDSReader()
    party = lector.read_party()
    pid, base = party.process_id, party.allocation_base
    print(f"melonDS PID {pid} - base 0x{base:X}")
    print(f"Equipo: {party.count} miembros (ancla ya demostrada).")
    print()
    print("No hace falta que hagas nada en el juego. Solo no lo cierres.")
    print("Leyendo...")

    inicio_guest = ANCLA_MEDICINAS - MARGEN_ANTES
    tamano = MARGEN_ANTES + MARGEN_DESPUES
    crudo = _leer(pid, base + (inicio_guest - DS_RAM_BASE), tamano)

    # Tiras de pares válidos consecutivos: cada una es candidata a bolsillo.
    tiras: list[dict] = []
    actual: list[dict] = []
    for indice in range(0, tamano - 3, 4):
        item, cantidad = struct.unpack_from("<HH", crudo, indice)
        valido = 0 < item <= ITEM_MAXIMO and 0 < cantidad <= CANTIDAD_MAXIMA
        if valido:
            actual.append({
                "direccion": f"0x{inicio_guest + indice:08X}",
                "item_id": item,
                "cantidad": cantidad,
                "nombre": _texto(item_name(item)),
            })
            continue
        if actual:
            tiras.append({
                "inicio": actual[0]["direccion"],
                "huecos": len(actual),
                "entradas": actual,
            })
            actual = []
    if actual:
        tiras.append({"inicio": actual[0]["direccion"], "huecos": len(actual), "entradas": actual})

    # El ancla de party demuestra que este bloque es el espejo del guardado.
    cuenta = _leer(pid, base + (PARTY_COUNT - DS_RAM_BASE), 1)[0]
    ancla_ok = int(cuenta) == int(party.count)

    print()
    print(f"Tiras de objetos encontradas: {len(tiras)}")
    for tira in tiras:
        primeros = ", ".join(
            f"{e['nombre']} x{e['cantidad']}" for e in tira["entradas"][:4]
        )
        print(f"  {tira['inicio']}  {tira['huecos']:3} huecos  {primeros}")
    print()
    print(f"Ancla de party coherente: {'si' if ancla_ok else 'NO'}")

    payload = {
        "format": "rolerun-b2w2-bag-map-v1",
        "captured_at": datetime.now().astimezone().isoformat(),
        "environment": "Pokemon Negro 2 Espana - melonDS 1.1",
        "ancla_demostrada": f"0x{ANCLA_MEDICINAS:08X}",
        "rango_volcado": [
            f"0x{inicio_guest:08X}", f"0x{inicio_guest + tamano:08X}",
        ],
        "criterio_entrada_valida": (
            f"identificador entre 1 y {ITEM_MAXIMO} y cantidad entre 1 y {CANTIDAD_MAXIMA}"
        ),
        "party_count_leido": int(cuenta),
        "party_count_esperado": int(party.count),
        "ancla_party_coherente": ancla_ok,
        "party_base": f"0x{PARTY_BASE:08X}",
        "tiras": tiras,
        "note": (
            "Diagnostico de solo lectura. Una tira aqui no es un bolsillo de "
            "produccion mientras no se confirme su inicio y su capacidad con un "
            "segundo estado."
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
