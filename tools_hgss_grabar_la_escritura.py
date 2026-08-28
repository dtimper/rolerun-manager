"""Graba, byte a byte, qué le pasa a una ficha cuando RoleRun la escribe.

POR QUÉ HACE FALTA

Tres «Huevo malo» seguidos, y todo lo comprobable leyendo sale bien:

- la dirección de escritura es la correcta, verificada seis de seis;
- el contenido escrito es un PK4 válido que se vuelve a leer perfecto;
- el codificador da la vuelta byte a byte idéntico, sobre el `.sav` y sobre la
  RAM;
- el orden de los bloques es el inverso exacto al de la lectura;
- el JIT de melonDS está apagado y no hay emulación de caché.

Así que el fallo no se ve leyendo antes ni leyendo después: pasa **entre medias**.
Esto graba ese hueco.

CÓMO

Muestrea las seis fichas a unas 2000 veces por segundo y apunta **cada cambio de
contenido** con su hora, si cuadra el checksum, y si la marca de huevo está
puesta. Mientras tanto, el jugador pulsa CURAR en RoleRun.

Al terminar deja un archivo con todos los contenidos distintos, en crudo, para
poder comparar exactamente qué escribió RoleRun y qué se lo comió después.

NO ESCRIBE NADA. La única escritura la hace RoleRun cuando el jugador pulsa.
"""

from __future__ import annotations

import ctypes
import json
import struct
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

from app.hgss_live import (  # noqa: E402
    DS_RAM_BASE, SAVE_PARTY_COUNT, SAVE_PARTY_DATA, _KERNEL32,
    HgssMelonDSReader, bloques_del_guardado,
)
from app.pk4 import (  # noqa: E402
    PK4_PARTY_SIZE, PK4_STORED_SIZE, Pk4Error, _crypt, parse_pk4_party,
    unshuffle_pk4,
)

CONFIG = Path.home() / "Documents" / "RoleRun Manager" / "Config" / "game_sources.json"
SEGUNDOS = 40
SALIDA = RAIZ / "Logs" / "grabacion_escritura_hgss.bin"

# En el bloque canónico, la marca de huevo es el bit 30 de la palabra de IV.
PK4_IV32 = 0x38
BIT_HUEVO = 1 << 30


def _firma() -> bytes:
    datos = json.loads(CONFIG.read_text(encoding="utf-8"))
    return Path(datos["games"]["hgss"]["save_path"]).read_bytes()[0x64:0x64 + 0x14]


def _cuadra(registro: bytes) -> bool:
    """Si esos 136 bytes son un PK4 coherente, en cualquiera de los dos estados.

    Una lectura pillada a medias casi nunca lo consigue: el checksum es la suma
    de los 128 bytes del cuerpo, y media ficha de otro instante no la cuadra.
    """
    checksum = struct.unpack_from("<H", registro, 6)[0]
    claro = registro[8:PK4_STORED_SIZE]
    if sum(struct.unpack("<64H", claro)) & 0xFFFF == checksum:
        return True
    descifrado = _crypt(claro, checksum)
    return sum(struct.unpack("<64H", descifrado)) & 0xFFFF == checksum


def _retrato(registro: bytes) -> str:
    """Una línea que describe en qué estado está esa ficha."""
    pid = struct.unpack_from("<I", registro, 0)[0]
    sanity, checksum = struct.unpack_from("<2H", registro, 4)
    claro = registro[8:PK4_STORED_SIZE]
    suma_claro = sum(struct.unpack("<64H", claro)) & 0xFFFF
    descifrado = _crypt(claro, checksum)
    suma_cifrado = sum(struct.unpack("<64H", descifrado)) & 0xFFFF

    if suma_claro == checksum:
        estado, cuerpo = "en claro", claro
    elif suma_cifrado == checksum:
        estado, cuerpo = "cifrado", descifrado
    else:
        return (f"NO CUADRA  pid=0x{pid:08X} sanity=0x{sanity:04X} "
                f"chk=0x{checksum:04X} suma_claro=0x{suma_claro:04X} "
                f"suma_desc=0x{suma_cifrado:04X}")

    try:
        pokemon = parse_pk4_party(registro, 0)
        quien = f"{pokemon.nickname} Nv{pokemon.level} {pokemon.current_hp}/{pokemon.max_hp}"
        pps = f"PP{pokemon.move_pp}"
    except Pk4Error as exc:
        quien, pps = f"ilegible ({exc})", ""

    try:
        _pid, orden, canonico, _cif = unshuffle_pk4(registro[:PK4_STORED_SIZE])
        palabra = struct.unpack_from("<I", canonico, PK4_IV32)[0]
        huevo = " HUEVO" if palabra & BIT_HUEVO else ""
        disposicion = "".join(str(indice) for indice in orden)
    except Pk4Error:
        huevo, disposicion = "", "????"
    return (f"{estado:9} chk=0x{checksum:04X} orden={disposicion}{huevo}  "
            f"{quien} {pps}")


def main() -> int:
    print()
    print("  GRABAR LO QUE LE PASA A LA FICHA AL ESCRIBIRLA")
    print("  " + "-" * 62)
    print()
    print("  Esta herramienta NO escribe nada. Graba.")
    print()
    print("  AVISO: es de esperar que salga otro «Huevo malo». Cuando termine,")
    print("  resetea melonDS SIN GUARDAR y no pierdes nada.")
    print()

    if _KERNEL32 is None:
        print("  Esto solo funciona en Windows con melonDS.")
        return 1
    try:
        firma = _firma()
    except Exception as exc:                                   # noqa: BLE001
        print(f"  No se pudo leer la partida configurada: {exc}")
        return 1

    lector = HgssMelonDSReader(firma_getter=lambda: firma)
    procesos = lector._list_melonds_processes()
    if not procesos:
        print("  No hay ningun melonDS abierto.")
        return 1

    handle = _KERNEL32.OpenProcess(0x0400 | 0x0010, False, procesos[0][0])
    if not handle:
        print("  Windows no dejo abrir melonDS para lectura.")
        return 1

    try:
        candidatos = []
        for reserva in lector._reservas(handle):
            ram = lector._volcar_reserva(handle, reserva)
            if ram is None or firma not in ram:
                continue
            for principio in bloques_del_guardado(ram, firma):
                candidatos.append((reserva, principio))
        if not candidatos:
            print("  No se encontro el bloque del guardado.")
            return 1
        reserva, principio = min(candidatos, key=lambda par: par[1])
        print(f"  Bloque: 0x{DS_RAM_BASE + principio:08X}")

        def leer(desplazamiento: int, tamano: int) -> bytes:
            buffer = ctypes.create_string_buffer(tamano)
            recibido = ctypes.c_size_t()
            _KERNEL32.ReadProcessMemory(
                handle, ctypes.c_void_p(reserva + principio + desplazamiento),
                buffer, tamano, ctypes.byref(recibido),
            )
            return buffer.raw

        cuantos = leer(SAVE_PARTY_COUNT, 1)[0]
        if not 1 <= cuantos <= 6:
            print(f"  El contador del equipo dice {cuantos}. No se sigue.")
            return 1

        print()
        print("  1) Ten RoleRun abierto y con el equipo de HeartGold a la vista.")
        print("  2) Cuando esto diga GRABANDO, pulsa CURAR EQUIPO en RoleRun.")
        print(f"  3) Deja que pasen los {SEGUNDOS} segundos y luego mira el juego.")
        print()
        for queda in range(8, 0, -1):
            print(f"    empiezo en {queda}... ", end="", flush=True)
            time.sleep(1)
        print()
        print("  >>> GRABANDO. PULSA CURAR EQUIPO EN ROLERUN AHORA. <<<", flush=True)

        # Solo se apuntan los CAMBIOS, que es lo que importa y lo que cabe.
        #
        # Una lectura pillada a medias casi nunca cuadra el checksum, así que un
        # contenido **coherente** se apunta aunque se vea una sola vez: si el
        # juego se come la escritura de RoleRun en menos de un milisegundo, esa
        # única muestra es justo la prueba que hace falta. Lo que no cuadra tiene
        # que salir dos veces seguidas para no llenar el diario de basura.
        anteriores: list[bytes | None] = [None] * cuantos
        candidato: list[bytes | None] = [None] * cuantos
        diario: list[tuple[float, int, bytes]] = []
        muestras = 0
        TOPE = 6000
        arranque = time.perf_counter()
        final = arranque + SEGUNDOS
        while time.perf_counter() < final:
            bloque = leer(SAVE_PARTY_DATA, cuantos * PK4_PARTY_SIZE)
            ahora = time.perf_counter() - arranque
            for indice in range(cuantos):
                registro = bloque[
                    indice * PK4_PARTY_SIZE:(indice + 1) * PK4_PARTY_SIZE
                ]
                if registro == anteriores[indice]:
                    continue
                if not _cuadra(registro) and registro != candidato[indice]:
                    candidato[indice] = registro
                    continue
                anteriores[indice] = registro
                if len(diario) < TOPE:
                    diario.append((ahora, indice, registro))
            muestras += 1

        print(f"  Hecho: {muestras} muestras, {len(diario)} cambios apuntados.")
        print()

        SALIDA.parent.mkdir(parents=True, exist_ok=True)
        with SALIDA.open("wb") as archivo:
            archivo.write(struct.pack("<II", DS_RAM_BASE + principio, cuantos))
            for cuando, indice, registro in diario:
                archivo.write(struct.pack("<dI", cuando, indice) + registro)
        print(f"  Grabacion completa en: {SALIDA}")
        print()

        print("  " + "=" * 62)
        print("  LINEA DE TIEMPO")
        print("  " + "=" * 62)
        for cuando, indice, registro in diario:
            print(f"  {cuando:7.3f}s  hueco {indice + 1}: {_retrato(registro)}")
        if not diario:
            print("  Ningun cambio. Si no llegaste a pulsar CURAR, repitelo.")
        print()
    finally:
        _KERNEL32.CloseHandle(handle)

    print("  Copia TODO este texto y pegaselo a Claude.")
    print("  Y luego resetea melonDS SIN GUARDAR.")
    print()
    return 0


if __name__ == "__main__":
    try:
        codigo = main()
    except Exception as exc:                                   # noqa: BLE001
        print(f"\n  Fallo inesperado: {exc}\n")
        codigo = 1
    input("  Pulsa Intro para cerrar...")
    raise SystemExit(codigo)
