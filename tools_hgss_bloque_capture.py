from __future__ import annotations

"""Averigua CUAL de los bloques del guardado manda en HeartGold.

EL PROBLEMA

En HeartGold hay **varios bloques del guardado a la vez** dentro de la RAM, y
ademas cambian de sitio. El 28-08-2026 se midieron cuatro, dos de ellos con el
equipo al dia y coincidiendo con el archivo de la partida al 99 % y al 97 %.

Localizarlos ya no es problema: el nombre del entrenador y sus identificadores
no cambian jugando, asi que sirven de firma y aparecen justo al principio de
cada bloque. Lo que no se puede deducir mirando es **cual de ellos usa el juego
de verdad**, y escribir en el que no manda fue lo que dejo un «Huevo malo».

COMO SE AVERIGUA

Con el mismo metodo de dos estados que ya funciono para las filas de combate de
Blanco: se apuntan todos los bloques, se pide un cambio pequeno dentro del juego
-recibir dano o usar una pocion- y se mira **cual de los bloques lo refleja**.
El que cambie es el que manda.

No escribe un solo byte en la partida, ni en la RAM, ni activa ninguna
capacidad. Solo lee.
"""

import ctypes
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.hgss_live import (  # noqa: E402
    DS_RAM_BASE, _KERNEL32, _MBI, HgssLiveError, parse_party_block,
)
from app.pk4 import PK4_PARTY_SIZE  # noqa: E402

# El nombre del entrenador y sus identificadores, que no cambian jugando.
FIRMA_OFFSET = 0x64
FIRMA_LARGO = 0x14
CONTADOR = 0x94
EQUIPO = 0x98
TAMANO_RAM = 0x00400000
SALIDA = Path("diagnostics/manual/hgss_bloque_latest.json")


def _guardado() -> bytes:
    config = Path.home() / "Documents" / "RoleRun Manager" / "Config" / "game_sources.json"
    datos = json.loads(config.read_text(encoding="utf-8"))
    ruta = Path(datos["games"]["hgss"]["save_path"])
    if not ruta.exists():
        raise SystemExit(f"No encuentro la partida:\n  {ruta}")
    return ruta.read_bytes()


def _melonds() -> int:
    from app.hgss_live import HgssMelonDSReader

    procesos = HgssMelonDSReader._list_melonds_processes()
    if not procesos:
        raise SystemExit("melonDS no esta abierto. Abrelo con HeartGold y repite.")
    return procesos[0][0]


def _leer_ram(handle, base: int) -> bytes | None:
    buffer = ctypes.create_string_buffer(TAMANO_RAM)
    recibido = ctypes.c_size_t()
    ok = _KERNEL32.ReadProcessMemory(
        handle, ctypes.c_void_p(base), buffer, TAMANO_RAM, ctypes.byref(recibido),
    )
    return buffer.raw if ok and recibido.value == TAMANO_RAM else None


def _reserva_del_ds(handle, firma: bytes):
    direccion, vistas = 0, {}
    while direccion < 0x7FFFFFFFFFFF:
        mbi = _MBI()
        if not _KERNEL32.VirtualQueryEx(
            handle, ctypes.c_void_p(direccion), ctypes.byref(mbi), ctypes.sizeof(mbi),
        ):
            break
        base = int(mbi.BaseAddress or 0)
        tamano = int(mbi.RegionSize or 0)
        reserva = int(mbi.AllocationBase or 0)
        if mbi.State == 0x1000 and reserva:
            vistas[reserva] = vistas.get(reserva, 0) + tamano
        direccion = base + max(tamano, 0x1000)
    for reserva, tamano in sorted(vistas.items()):
        if not TAMANO_RAM <= tamano <= 0x40000000:
            continue
        ram = _leer_ram(handle, reserva)
        if ram is not None and firma in ram:
            return reserva, ram
    return None, None


def _bloques(ram: bytes, firma: bytes) -> list[int]:
    salida, desde = [], 0
    while True:
        indice = ram.find(firma, desde)
        if indice < 0:
            return salida
        desde = indice + 1
        principio = indice - FIRMA_OFFSET
        if principio >= 0 and principio % 4 == 0:
            salida.append(principio)


def _equipo(ram: bytes, principio: int) -> tuple[int, str, bytes]:
    cuantos = ram[principio + CONTADOR]
    if not 1 <= cuantos <= 6:
        return cuantos, "(contador imposible)", b""
    crudo = ram[principio + EQUIPO:principio + EQUIPO + cuantos * PK4_PARTY_SIZE]
    try:
        equipo = parse_party_block(crudo, cuantos)
    except HgssLiveError as exc:
        return cuantos, f"(no parsea: {str(exc)[:40]})", crudo
    return cuantos, " · ".join(
        f"{p.nickname} {p.current_hp}/{p.max_hp}" for p in equipo
    ), crudo


def main() -> None:
    archivo = _guardado()
    firma = archivo[FIRMA_OFFSET:FIRMA_OFFSET + FIRMA_LARGO]
    pid_proceso = _melonds()
    handle = _KERNEL32.OpenProcess(0x0400 | 0x0010, False, pid_proceso)
    if not handle:
        raise SystemExit("No se pudo abrir melonDS en modo lectura.")

    try:
        reserva, ram = _reserva_del_ds(handle, firma)
        if reserva is None:
            raise SystemExit(
                "No se encontro la RAM del DS. Comprueba que melonDS tiene\n"
                "HeartGold cargado y que la partida guardada es la de este juego."
            )
        principios = _bloques(ram, firma)
        print(f"melonDS PID {pid_proceso} - reserva 0x{reserva:012X}")
        print(f"Bloques del guardado encontrados: {len(principios)}")
        print()
        antes = {}
        for principio in principios:
            cuantos, resumen, crudo = _equipo(ram, principio)
            antes[principio] = crudo
            print(f"  0x{DS_RAM_BASE + principio:08X}  contador={cuantos:3}  {resumen}")

        print()
        print("=" * 62)
        print("  AHORA CAMBIA ALGO DENTRO DEL JUEGO")
        print("=" * 62)
        print()
        print("  Lo mas facil: entra en un combate y deja que te quiten PS,")
        print("  o usa una Pocion en alguien. Vale cualquier cosa que cambie")
        print("  los PS de un Pokemon de tu equipo.")
        print()
        input("  Cuando lo hayas hecho, pulsa INTRO...")

        ram2 = _leer_ram(handle, reserva)
        if ram2 is None:
            raise SystemExit("No se pudo releer la RAM.")
        print()
        cambiados = []
        despues = {}
        for principio in principios:
            cuantos, resumen, crudo = _equipo(ram2, principio)
            despues[principio] = crudo
            cambio = crudo != antes.get(principio, b"")
            if cambio:
                cambiados.append(principio)
            marca = "  <-- HA CAMBIADO" if cambio else ""
            print(f"  0x{DS_RAM_BASE + principio:08X}  contador={cuantos:3}  {resumen}{marca}")

        print()
        if len(cambiados) == 1:
            print(f"El bloque que manda es 0x{DS_RAM_BASE + cambiados[0]:08X}.")
        elif cambiados:
            print(f"Han cambiado {len(cambiados)}. Habra que mirar cual va primero.")
        else:
            print("No ha cambiado ninguno. ¿Seguro que cambiaron los PS?")
    finally:
        _KERNEL32.CloseHandle(handle)

    payload = {
        "format": "rolerun-hgss-bloque-v1",
        "captured_at": datetime.now().astimezone().isoformat(),
        "environment": "Oro HeartGold Espana - melonDS",
        "metodo": (
            "Se localizan todos los bloques del guardado por la firma del nombre "
            "del entrenador, se pide un cambio dentro del juego y se mira cual "
            "de ellos lo refleja."
        ),
        "reserva": f"0x{reserva:012X}",
        "bloques": [
            {
                "direccion": f"0x{DS_RAM_BASE + p:08X}",
                "cambio": p in cambiados,
                "antes": antes.get(p, b"").hex()[:472],
                "despues": despues.get(p, b"").hex()[:472],
            }
            for p in principios
        ],
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
    except SystemExit as exc:
        print(f"\n{exc}")
        input()
    except OSError as exc:
        print(f"\nNo se pudo leer melonDS: {exc}")
        input()
