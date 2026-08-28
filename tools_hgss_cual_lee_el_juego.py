"""Cuál de las copias del bloque del guardado lee HeartGold de verdad.

POR QUÉ HACE FALTA ESTO

En la RAM de melonDS conviven **tres copias** del bloque del guardado -medido:
0x0227C2DC, 0x02376864 y 0x02399884, las tres con los mismos seis Pokémon-. Las
tres se interpretan igual, así que por contenido no se distinguen.

Hasta ahora se elegía «la que cambia». Eso no demuestra nada: puede cambiar una
copia de trabajo que el juego no usa para el equipo, y con el emulador pausado no
cambia ninguna. Escribir en la copia equivocada es lo que dejó dos «Huevo malo».

CÓMO LO DEMUESTRA, SIN ESCRIBIR NI UN BYTE

Le pide al jugador que **cambie de sitio dos Pokémon del equipo** dentro del
juego. Eso lo hace el juego, no RoleRun. Luego mira las tres copias: la que
refleje el cambio es la que el juego usa. Las demás, no.

Primero comprueba que el emulador está corriendo -si está pausado, la medida no
valdría y lo dice- y no escribe absolutamente nada en ningún momento.
"""

from __future__ import annotations

import ctypes
import json
import struct
import sys
import time
from ctypes import wintypes
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

from app.hgss_live import (  # noqa: E402
    DS_RAM_BASE, MARCA, MARCA_OFFSET, SAVE_PARTY_COUNT, SAVE_PARTY_DATA,
    TAMANO_BLOQUE, _KERNEL32, HgssMelonDSReader, bloques_del_guardado,
)
from app.pk4 import PK4_PARTY_SIZE, Pk4Error, parse_pk4_party  # noqa: E402

CONFIG = Path.home() / "Documents" / "RoleRun Manager" / "Config" / "game_sources.json"
SEGUNDOS_PARA_CAMBIAR = 45


def _firma() -> bytes:
    datos = json.loads(CONFIG.read_text(encoding="utf-8"))
    ruta = datos["games"]["hgss"]["save_path"]
    return Path(ruta).read_bytes()[0x64:0x64 + 0x14]


def _equipo(ram: bytes, principio: int) -> tuple[str, ...] | None:
    cuantos = ram[principio + SAVE_PARTY_COUNT]
    if not 1 <= cuantos <= 6:
        return None
    nombres = []
    for indice in range(cuantos):
        desde = principio + SAVE_PARTY_DATA + indice * PK4_PARTY_SIZE
        try:
            miembro = parse_pk4_party(ram[desde:desde + PK4_PARTY_SIZE], indice)
        except Pk4Error:
            nombres.append("?")
            continue
        nombres.append(f"{miembro.nickname}")
    return tuple(nombres)


def main() -> int:
    print()
    print("  QUE COPIA DEL GUARDADO LEE HEARTGOLD")
    print("  " + "-" * 60)
    print()
    print("  Esta herramienta NO escribe nada. Solo mira.")
    print()

    if _KERNEL32 is None:
        print("  Esto solo funciona en Windows con melonDS.")
        return 1

    try:
        firma = _firma()
    except Exception as exc:                       # noqa: BLE001
        print(f"  No se pudo leer la partida configurada: {exc}")
        return 1

    lector = HgssMelonDSReader(firma_getter=lambda: firma)
    procesos = lector._list_melonds_processes()
    if not procesos:
        print("  No hay ningun melonDS abierto.")
        return 1
    process_id = procesos[0][0]

    print("  1) Pon el foco en melonDS y deja el juego CORRIENDO.")
    print("     No lo pauses. Tienes 10 segundos.")
    for queda in range(10, 0, -1):
        print(f"     {queda}... ", end="", flush=True)
        time.sleep(1)
    print()
    print()

    handle = _KERNEL32.OpenProcess(0x0400 | 0x0010, False, process_id)
    if not handle:
        print("  Windows no dejo abrir melonDS para lectura.")
        return 1

    try:
        reservas = list(lector._reservas(handle))
        copias: list[tuple[int, int]] = []          # (reserva, principio)
        for reserva in reservas:
            ram = lector._volcar_reserva(handle, reserva)
            if ram is None or firma not in ram:
                continue
            for principio in bloques_del_guardado(ram, firma):
                copias.append((reserva, principio))

        if not copias:
            print("  No se encontro ningun bloque del guardado.")
            return 1

        print(f"  Copias del bloque encontradas: {len(copias)}")
        for reserva, principio in copias:
            print(f"     0x{DS_RAM_BASE + principio:08X}")
        print()

        # ¿Esta el juego corriendo? Si no, la medida no vale.
        def volcar(reserva: int, principio: int, tam: int = TAMANO_BLOQUE) -> bytes:
            buf = ctypes.create_string_buffer(tam)
            leidos = ctypes.c_size_t()
            _KERNEL32.ReadProcessMemory(
                handle, ctypes.c_void_p(reserva + principio), buf, tam,
                ctypes.byref(leidos),
            )
            return buf.raw

        muestra = [volcar(r, p) for r, p in copias]
        time.sleep(0.5)
        muestra2 = [volcar(r, p) for r, p in copias]
        se_mueve = [a != b for a, b in zip(muestra, muestra2)]
        print("  Se mueve el bloque mientras el juego corre:")
        for (reserva, principio), cambia in zip(copias, se_mueve):
            print(f"     0x{DS_RAM_BASE + principio:08X}  "
                  + ("SI cambia" if cambia else "no cambia"))
        print()

        antes = [_equipo(volcar(r, p), 0) for r, p in copias]
        print("  Equipo que ve cada copia AHORA:")
        for (reserva, principio), equipo in zip(copias, antes):
            print(f"     0x{DS_RAM_BASE + principio:08X}  {equipo}")
        print()

        print("  2) AHORA, dentro del juego: abre el equipo y CAMBIA DE SITIO")
        print("     dos Pokemon (por ejemplo el 1 y el 3).")
        print(f"     Tienes {SEGUNDOS_PARA_CAMBIAR} segundos. Cierra el menu al terminar.")
        print()
        for queda in range(SEGUNDOS_PARA_CAMBIAR, 0, -1):
            if queda % 5 == 0 or queda <= 5:
                print(f"     {queda}s ", end="", flush=True)
            time.sleep(1)
        print()
        print()

        despues = [_equipo(volcar(r, p), 0) for r, p in copias]
        print("  " + "=" * 60)
        print("  RESULTADO")
        print("  " + "=" * 60)
        vivas = []
        for (reserva, principio), viejo, nuevo in zip(copias, antes, despues):
            direccion = f"0x{DS_RAM_BASE + principio:08X}"
            if viejo != nuevo:
                vivas.append(direccion)
                print(f"     {direccion}  <-- SIGUE AL JUEGO")
                print(f"        antes:   {viejo}")
                print(f"        despues: {nuevo}")
            else:
                print(f"     {direccion}      se quedo igual: {nuevo}")
        print()
        if len(vivas) == 1:
            print(f"  La copia que el juego usa es {vivas[0]}.")
        elif not vivas:
            print("  Ninguna copia cambio. O no se movio nada en el equipo,")
            print("  o el juego no vuelca el equipo aqui mientras juegas.")
        else:
            print(f"  Cambiaron {len(vivas)}: {', '.join(vivas)}.")
        print()
    finally:
        _KERNEL32.CloseHandle(handle)

    print("  Copia todo este texto y pegaselo a Claude.")
    print()
    return 0


if __name__ == "__main__":
    try:
        codigo = main()
    except Exception as exc:                       # noqa: BLE001
        print(f"\n  Fallo inesperado: {exc}\n")
        codigo = 1
    input("  Pulsa Intro para cerrar...")
    raise SystemExit(codigo)
