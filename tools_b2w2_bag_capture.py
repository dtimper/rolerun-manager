from __future__ import annotations

"""Localización manual de solo lectura de la mochila y el dinero en B2/W2.

Todo lo que le queda a B2/W2 —mochila, MT, utilidades y medallas— depende de
direcciones de RAM que **no están demostradas**. Inventar una sería exactamente
lo que AGENTS.md prohíbe, así que primero se busca la evidencia.

El método es el que pide el propio documento de paridad: **dos estados**.

Una primera versión buscó solo el par (identificador, cantidad) de 16 bits que
usa la mochila de quinta generación. No bastó: la traza del 27-08-2026 devolvió
40 coincidencias para «Poké Ball x3», y al mirarlas resultaron ser un patrón
repetitivo de valores pequeños que coincidía por azar. Un número suelto, por
específico que parezca, aparece muchas veces en 4 MiB.

Con dos estados el filtro es de otra naturaleza: la dirección buena es la que
tenía la cantidad vieja **y en esa misma posición** pasa a tener la nueva después
de que el jugador use o compre una unidad. Eso no lo cumple un patrón casual.

No escribe un solo byte en la partida ni activa ninguna capacidad.
"""

import ctypes
import json
import struct
import time
from datetime import datetime
from pathlib import Path

from app.b2w2_live import (
    DS_RAM_BASE,
    B2W2LiveError,
    B2W2MelonDSReader,
    _KERNEL32,
)
from app.boxed_metadata import item_name

# RAM principal de la DS: 4 MiB a partir de 0x02000000.
TAMANO_RAM = 0x00400000
# Objetos consumibles y fáciles de gastar o comprar. El identificador sale de la
# misma tabla de PKHeX que ya usa RoleRun, no de una lista escrita a mano.
OBJETOS = ((17, "Pocion"), (4, "Poke Ball"))
VENTANA_PARES = 24
SALIDA = Path("diagnostics/manual/b2w2_bag_latest.json")


def _texto(valor: str) -> str:
    """Evita que un acento tumbe la consola de Windows."""
    import sys

    try:
        valor.encode(sys.stdout.encoding or "utf-8")
        return valor
    except Exception:
        return valor.encode("ascii", "replace").decode("ascii")


def _leer_ram(pid: int, base: int) -> bytes:
    handle = _KERNEL32.OpenProcess(0x0400 | 0x0010, False, int(pid))
    if not handle:
        raise OSError("No se pudo abrir melonDS en modo lectura.")
    try:
        buffer = ctypes.create_string_buffer(TAMANO_RAM)
        recibido = ctypes.c_size_t()
        ok = _KERNEL32.ReadProcessMemory(
            handle, ctypes.c_void_p(base), buffer, TAMANO_RAM, ctypes.byref(recibido),
        )
        if not ok or recibido.value != TAMANO_RAM:
            raise OSError("Lectura incompleta de la RAM de melonDS.")
        return buffer.raw
    finally:
        _KERNEL32.CloseHandle(handle)


def _pares(ram: bytes, item_id: int, cantidad: int) -> list[int]:
    patron = struct.pack("<HH", int(item_id), int(cantidad))
    salida, desde = [], 0
    while True:
        indice = ram.find(patron, desde)
        if indice < 0:
            return salida
        if indice % 4 == 0:
            salida.append(indice)
        desde = indice + 1


def _u32(ram: bytes, valor: int) -> list[int]:
    patron = struct.pack("<I", int(valor))
    salida, desde = [], 0
    while True:
        indice = ram.find(patron, desde)
        if indice < 0:
            return salida
        if indice % 4 == 0:
            salida.append(indice)
        desde = indice + 1


def _bolsillo(ram: bytes, offset: int) -> list[dict]:
    """Decodifica la zona como pares (identificador, cantidad)."""
    inicio = max(0, offset - VENTANA_PARES * 4)
    filas = []
    for indice in range(inicio, min(len(ram) - 4, offset + VENTANA_PARES * 4), 4):
        item, cantidad = struct.unpack_from("<HH", ram, indice)
        nombre = _texto(item_name(item)) if 0 < item < 2685 else ""
        filas.append({
            "direccion": f"0x{DS_RAM_BASE + indice:08X}",
            "delta": indice - offset,
            "item_id": item,
            "cantidad": cantidad,
            "nombre": nombre,
        })
    return filas


def _numero(mensaje: str) -> int | None:
    respuesta = input(mensaje).strip()
    if not respuesta:
        return None
    try:
        return max(0, int(respuesta))
    except ValueError:
        print("  No era un numero; se omite.")
        return None


def main() -> None:
    lector = B2W2MelonDSReader()
    party = lector.read_party()
    pid, base = party.process_id, party.allocation_base
    print(f"melonDS PID {pid} - base 0x{base:X}")
    print()
    print("=== PASO 1 de 2: como esta tu mochila AHORA ===")
    print("Abre la mochila en el juego y mira las cantidades exactas.")
    print("Lo que no tengas, dejalo vacio y pulsa INTRO.")
    print()

    antes: list[tuple[int, str, int]] = []
    for item_id, etiqueta in OBJETOS:
        nombre = _texto(item_name(item_id)) or etiqueta
        cantidad = _numero(f"  Cuantos/as {nombre} tienes? ")
        if cantidad:
            antes.append((item_id, nombre, cantidad))
    dinero_antes = _numero("  Cuanto dinero tienes exactamente? ")

    if not antes and dinero_antes is None:
        print("\nSin ningun dato con el que buscar.")
        input()
        return

    print("\nLeyendo la memoria... no toques el juego.")
    ram_antes = _leer_ram(pid, base)
    candidatos = {
        item_id: _pares(ram_antes, item_id, cantidad)
        for item_id, _nombre, cantidad in antes
    }
    for item_id, nombre, cantidad in antes:
        print(f"  {nombre} x{cantidad}: {len(candidatos[item_id])} posiciones posibles.")
    candidatos_dinero = _u32(ram_antes, dinero_antes) if dinero_antes else []
    if dinero_antes:
        print(f"  Dinero {dinero_antes}: {len(candidatos_dinero)} posiciones posibles.")

    print()
    print("=== PASO 2 de 2: cambia algo y vuelve ===")
    print("Ahora, DENTRO DEL JUEGO, haz que cambien esas cantidades:")
    print("  - usa una Pocion, o compra/tira alguna,")
    print("  - y si vas a mirar el dinero, compra o vende algo.")
    print("No hace falta que cambien todas: con una basta.")
    print()
    input("Cuando lo hayas hecho, vuelve aqui y pulsa INTRO...")
    print()

    despues: dict[int, int] = {}
    for item_id, nombre, _cantidad in antes:
        nueva = _numero(f"  Cuantos/as {nombre} tienes AHORA? ")
        if nueva is not None:
            despues[item_id] = nueva
    dinero_despues = _numero("  Cuanto dinero tienes AHORA? ") if dinero_antes else None

    print("\nLeyendo otra vez... no toques el juego.")
    ram_despues = _leer_ram(pid, base)

    resultados = []
    for item_id, nombre, cantidad in antes:
        nueva = despues.get(item_id)
        confirmadas = []
        if nueva is not None and nueva != cantidad:
            for offset in candidatos[item_id]:
                identificador, actual = struct.unpack_from("<HH", ram_despues, offset)
                if identificador == item_id and actual == nueva:
                    confirmadas.append(offset)
        resultados.append({
            "item_id": item_id,
            "nombre": nombre,
            "cantidad_antes": cantidad,
            "cantidad_despues": nueva,
            "posiciones_iniciales": len(candidatos[item_id]),
            "confirmadas": [f"0x{DS_RAM_BASE + o:08X}" for o in confirmadas],
            "bolsillo": [
                {"direccion_base": f"0x{DS_RAM_BASE + o:08X}", "filas": _bolsillo(ram_despues, o)}
                for o in confirmadas[:4]
            ],
        })
        if nueva is None or nueva == cantidad:
            print(f"  {nombre}: sin cambio declarado, no se puede confirmar.")
        else:
            print(f"  {nombre}: {len(confirmadas)} direccion(es) CONFIRMADAS.")

    dinero_resultado = None
    if dinero_antes and dinero_despues is not None and dinero_despues != dinero_antes:
        confirmadas = [
            o for o in candidatos_dinero
            if struct.unpack_from("<I", ram_despues, o)[0] == dinero_despues
        ]
        dinero_resultado = {
            "antes": dinero_antes,
            "despues": dinero_despues,
            "posiciones_iniciales": len(candidatos_dinero),
            "confirmadas": [f"0x{DS_RAM_BASE + o:08X}" for o in confirmadas],
        }
        print(f"  Dinero: {len(confirmadas)} direccion(es) CONFIRMADAS.")

    payload = {
        "format": "rolerun-b2w2-bag-two-state-v1",
        "captured_at": datetime.now().astimezone().isoformat(),
        "environment": "Pokemon Negro 2 Espana - melonDS 1.1",
        "metodo": (
            "Dos estados. Se guardan las posiciones que contenian el par "
            "(item_id, cantidad_antes) y se conservan solo las que, en esa misma "
            "posicion, pasan a contener la cantidad nueva. Un patron casual no "
            "sobrevive a ese filtro."
        ),
        "objetos": resultados,
        "dinero": dinero_resultado,
        "note": (
            "Candidatos diagnosticos de solo lectura. Una direccion aqui solo pasa "
            "a produccion tras confirmarse tambien con el contenido del bolsillo."
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
