from __future__ import annotations

"""Localiza el equipo de HeartGold dentro de la RAM de melonDS.

QUE BUSCA Y POR QUE ASI

Cada Pokemon lleva un PID de cuatro bytes que no esta cifrado: abre el bloque.
La partida guardada del usuario dice cuales son los PID de su equipo, asi que
esta herramienta no supone nada sobre donde vive el equipo ni sobre el formato
de la fila: busca esos numeros concretos y se queda con los sitios donde
aparecen VARIOS, separados exactamente 236 bytes, que es lo que mide un PK4 de
combate.

Encontrado el sitio, lo confirma leyendo de verdad: pasa los 236 bytes por el
mismo parser que usaria RoleRun. Si el checksum no cuadra o la especie no tiene
sentido, el candidato se descarta.

Y ADEMAS COMPRUEBA LA REGLA DEL ESPEJO

En quinta generacion el bloque vivo resulto ser una copia contigua del
guardado, y eso abarato cada juego nuevo: con un ancla salian el PC, la
mochila, el dinero y las medallas. Aqui se comprueba si cuarta hace lo mismo,
comparando byte a byte un tramo grande de la RAM con el archivo de la partida.
La respuesta sale medida, no supuesta.

No escribe un solo byte en la partida, ni en la RAM, ni activa ninguna
capacidad. Solo lee.
"""

import ctypes
import json
import struct
import sys
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.b2w2_live import DS_RAM_BASE, _KERNEL32, _PROCESSENTRY32W  # noqa: E402
from app.pk4 import PK4_PARTY_SIZE, Pk4Error, parse_pk4_party  # noqa: E402

GUARDADO = Path(
    "D:/Users/diego/Diego/Juegos/POKEMON ROLERUN/Pokémon HeartGold/"
    "4832 - Pokemon - Edicion Oro HeartGold (Spain) [b].sav"
)
# Medidos recorriendo el guardado entero el 27-08-2026: cinco bloques con
# checksum PK4 valido, seguidos y separados 236 bytes, con el contador delante.
SAVE_PARTY_COUNT = 0x94
SAVE_PARTY_DATA = 0x98
MITADES = (0x00000, 0x40000)

TAMANO_RAM_DS = 0x00400000
TROZO = 0x00100000
COMPARACION = 0x00020000        # cuanto se compara con el guardado
SALIDA = Path("diagnostics/manual/hgss_anchor_latest.json")


class MBI(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD), ("PartitionId", wintypes.WORD),
        ("RegionSize", ctypes.c_size_t), ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD), ("Type", wintypes.DWORD),
    ]


def _procesos_melonds() -> list[tuple[int, str]]:
    snapshot = _KERNEL32.CreateToolhelp32Snapshot(0x00000002, 0)
    if ctypes.cast(snapshot, ctypes.c_void_p).value == ctypes.c_void_p(-1).value:
        raise OSError("No se pudieron enumerar los procesos de Windows.")
    salida: list[tuple[int, str]] = []
    try:
        entrada = _PROCESSENTRY32W()
        entrada.dwSize = ctypes.sizeof(entrada)
        ok = bool(_KERNEL32.Process32FirstW(snapshot, ctypes.byref(entrada)))
        while ok:
            if str(entrada.szExeFile).casefold() == "melonds.exe":
                salida.append((int(entrada.th32ProcessID), str(entrada.szExeFile)))
            ok = bool(_KERNEL32.Process32NextW(snapshot, ctypes.byref(entrada)))
    finally:
        _KERNEL32.CloseHandle(snapshot)
    return salida


def _equipo_guardado() -> tuple[int, list[dict], int]:
    """Contador, miembros y la mitad del archivo donde estaban."""
    if not GUARDADO.exists():
        raise SystemExit(f"No encuentro la partida:\n  {GUARDADO}")
    crudo = GUARDADO.read_bytes()
    for base in MITADES:
        cuantos = struct.unpack_from("<I", crudo, base + SAVE_PARTY_COUNT)[0]
        if not 1 <= cuantos <= 6:
            continue
        miembros = []
        try:
            for indice in range(cuantos):
                inicio = base + SAVE_PARTY_DATA + indice * PK4_PARTY_SIZE
                leido = parse_pk4_party(crudo[inicio:inicio + PK4_PARTY_SIZE], indice)
                if not 1 <= leido.species_id <= 493:
                    raise Pk4Error("Especie fuera de rango.")
                miembros.append({
                    "slot": indice, "pid": leido.pid, "especie": leido.species_id,
                    "mote": leido.nickname, "nivel": leido.level,
                    "ps": f"{leido.current_hp}/{leido.max_hp}",
                })
        except Pk4Error:
            continue
        return cuantos, miembros, base
    raise SystemExit(
        "La partida guardada no tiene equipo legible. Guarda dentro del juego\n"
        "y vuelve a ejecutar esto."
    )


def _abrir(pid: int):
    handle = _KERNEL32.OpenProcess(0x0400 | 0x0010, False, int(pid))
    if not handle:
        raise OSError("No se pudo abrir melonDS en modo lectura.")
    return handle


def _leer(handle, direccion: int, tamano: int) -> bytes | None:
    buffer = ctypes.create_string_buffer(tamano)
    recibido = ctypes.c_size_t()
    ok = _KERNEL32.ReadProcessMemory(
        handle, ctypes.c_void_p(direccion), buffer, tamano, ctypes.byref(recibido),
    )
    if not ok or recibido.value != tamano:
        return None
    return buffer.raw


def _allocations(handle) -> list[tuple[int, int]]:
    """Cada reserva comprometida y su tamano total."""
    tamanos: dict[int, int] = {}
    direccion = 0
    while direccion < 0x7FFFFFFFFFFF:
        mbi = MBI()
        if not _KERNEL32.VirtualQueryEx(
            handle, ctypes.c_void_p(direccion), ctypes.byref(mbi), ctypes.sizeof(mbi),
        ):
            break
        base = int(mbi.BaseAddress or 0)
        tamano = int(mbi.RegionSize or 0)
        reserva = int(mbi.AllocationBase or 0)
        if mbi.State == 0x1000 and reserva:
            tamanos[reserva] = tamanos.get(reserva, 0) + tamano
        direccion = base + max(tamano, 0x1000)
    return sorted(tamanos.items())


def _buscar_pids(bloque: bytes, pids: list[int]) -> dict[int, list[int]]:
    """Donde aparece cada PID dentro del bloque."""
    encontrados: dict[int, list[int]] = {}
    for pid in pids:
        patron = struct.pack("<I", pid)
        posiciones: list[int] = []
        desde = 0
        while True:
            indice = bloque.find(patron, desde)
            if indice < 0:
                break
            if indice % 4 == 0:
                posiciones.append(indice)
            desde = indice + 1
        if posiciones:
            encontrados[pid] = posiciones
    return encontrados


def _candidatos(encontrados: dict[int, list[int]], pids: list[int]) -> list[int]:
    """Inicios donde varios miembros caen separados 236 bytes.

    Un PID suelto puede aparecer por azar en cuatro megas; que dos o mas caigan
    a la distancia exacta que separa a dos PK4 de combate, no.
    """
    if not encontrados:
        return []
    inicios: list[int] = []
    for posicion in encontrados.get(pids[0], []):
        aciertos = 1
        for indice, pid in enumerate(pids[1:], start=1):
            esperado = posicion + indice * PK4_PARTY_SIZE
            if esperado in encontrados.get(pid, ()):  # noqa: PLR6201
                aciertos += 1
        if aciertos >= min(2, len(pids)):
            inicios.append(posicion)
    return inicios


def main() -> None:
    cuantos, miembros, mitad = _equipo_guardado()
    print("=== Equipo segun la partida guardada ===")
    print(f"  (leido de la mitad 0x{mitad:05X} del archivo)")
    for m in miembros:
        print(f"   {m['slot'] + 1}. {m['mote']:12} esp={m['especie']:3} Nv.{m['nivel']:3} "
              f"PS {m['ps']:8} PID 0x{m['pid']:08X}")
    print()
    print("IMPORTANTE: esto compara la partida GUARDADA con lo que hay en memoria.")
    print("Si has jugado despues de guardar, guarda otra vez dentro del juego.")
    print()

    procesos = _procesos_melonds()
    if not procesos:
        print("melonDS no esta abierto. Abrelo con HeartGold cargado y repite.")
        input()
        return
    print(f"melonDS encontrado: {[p for p, _ in procesos]}")

    pids = [m["pid"] for m in miembros]
    hallazgos = []
    espejo = None

    for pid_proceso, _nombre in procesos:
        try:
            handle = _abrir(pid_proceso)
        except OSError as exc:
            print(f"  PID {pid_proceso}: {exc}")
            continue
        try:
            reservas = [
                (base, tamano) for base, tamano in _allocations(handle)
                if TAMANO_RAM_DS <= tamano <= 0x40000000
            ]
            print(f"  PID {pid_proceso}: {len(reservas)} reservas de tamano plausible")
            for base, tamano in reservas:
                leido = 0
                while leido < min(tamano, 0x08000000):
                    trozo = _leer(handle, base + leido, min(TROZO, tamano - leido))
                    if trozo is None:
                        leido += TROZO
                        continue
                    encontrados = _buscar_pids(trozo, pids)
                    for inicio in _candidatos(encontrados, pids):
                        absoluto = base + leido + inicio
                        crudo = _leer(handle, absoluto, PK4_PARTY_SIZE)
                        if crudo is None:
                            continue
                        try:
                            leido_pk4 = parse_pk4_party(crudo, 0)
                        except Pk4Error as exc:
                            print(f"     0x{absoluto:012X}: descartado ({exc})")
                            continue
                        if leido_pk4.species_id != miembros[0]["especie"]:
                            continue
                        contador = _leer(handle, absoluto - 4, 4)
                        invitado = DS_RAM_BASE + (absoluto - base)
                        hallazgos.append({
                            "proceso": pid_proceso,
                            "reserva": f"0x{base:012X}",
                            "direccion_host": f"0x{absoluto:012X}",
                            "direccion_invitado": f"0x{invitado:08X}",
                            "contador_delante": (
                                struct.unpack("<I", contador)[0] if contador else None
                            ),
                            "leido": {
                                "especie": leido_pk4.species_id,
                                "mote": leido_pk4.nickname,
                                "nivel": leido_pk4.level,
                                "ps": f"{leido_pk4.current_hp}/{leido_pk4.max_hp}",
                                "pid": f"0x{leido_pk4.pid:08X}",
                            },
                        })
                        print(f"     ENCONTRADO en invitado 0x{invitado:08X}: "
                              f"{leido_pk4.nickname} Nv.{leido_pk4.level} "
                              f"PS {leido_pk4.current_hp}/{leido_pk4.max_hp}, "
                              f"contador delante = {hallazgos[-1]['contador_delante']}")

                        # La regla del espejo: si cuarta copia el guardado tal
                        # cual, restando el desplazamiento del equipo cae el
                        # principio del bloque, y de ahi en adelante los bytes
                        # tienen que ser los mismos.
                        if espejo is None:
                            inicio_bloque = absoluto - SAVE_PARTY_DATA
                            vivo = _leer(handle, inicio_bloque, COMPARACION)
                            if vivo is not None:
                                guardado = GUARDADO.read_bytes()[mitad:mitad + COMPARACION]
                                iguales = sum(
                                    1 for a, b in zip(vivo, guardado) if a == b
                                )
                                espejo = {
                                    "inicio_bloque_invitado":
                                        f"0x{DS_RAM_BASE + (inicio_bloque - base):08X}",
                                    "bytes_comparados": COMPARACION,
                                    "bytes_iguales": iguales,
                                    "porcentaje": round(100 * iguales / COMPARACION, 2),
                                }
                                print(f"     Espejo del guardado: {espejo['porcentaje']}% "
                                      f"de {COMPARACION} bytes coinciden")
                    leido += TROZO
        finally:
            _KERNEL32.CloseHandle(handle)

    print()
    if not hallazgos:
        print("No aparecio el equipo. Comprueba que la partida esta guardada")
        print("dentro del juego y que melonDS tiene HeartGold cargado.")
    else:
        print(f"Candidatos: {len(hallazgos)}")

    payload = {
        "format": "rolerun-hgss-anchor-v1",
        "captured_at": datetime.now().astimezone().isoformat(),
        "environment": "Oro HeartGold Espana - melonDS",
        "metodo": (
            "Se buscan en la RAM de melonDS los PID concretos del equipo que "
            "declara la partida guardada, y se conservan los sitios donde varios "
            "caen separados 236 bytes. Cada candidato se confirma leyendolo con "
            "el parser PK4 de produccion."
        ),
        "guardado": str(GUARDADO),
        "mitad_activa": f"0x{mitad:05X}",
        "equipo_guardado": miembros,
        "contador_guardado": cuantos,
        "hallazgos": hallazgos,
        "espejo_del_guardado": espejo,
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
