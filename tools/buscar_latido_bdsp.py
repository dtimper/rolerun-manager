"""Busca un latido en Perla Reluciente: algo que avance solo. No escribe nada.

Al enseñar una MT el juego se queda congelado. La traza de RoleRun no lo ve:
después de la escritura siguió leyendo con normalidad **68 segundos**, porque un
juego congelado se ve exactamente igual desde fuera —su proceso sigue vivo y su
memoria sigue siendo legible— y con el personaje quieto ni los PS ni el equipo
cambian.

Sin saber **cuándo** se paró el juego no se puede decir si fue la escritura o
algo posterior, y así solo se pueden ir descartando hipótesis a ciegas. Ya han
caído dos: que la mochila quedara con un registro imposible (la partida ya tiene
siete iguales, los hace el juego) y que los PP quedaran mal (`_set_move` escribe
PP Ups 0 y PP base, que es lo que hace `CoreParam.SetWaza`).

Esta herramienta lee tres veces el bloque `PlayerWork._saveData`, con pausas, y
señala qué posiciones avanzan solas. Un contador que suba en las tres lecturas
—el tiempo de juego, por ejemplo— sirve de latido: metiéndolo en cada captura, la
traza dirá el segundo exacto en que el juego dejó de avanzar.

**Hay que estar quieto en el mapa, sin abrir menús ni hablar con nadie.** Lo que
se busca es lo que cambia sin que tú hagas nada.
"""

from __future__ import annotations

import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

from app.bdsp_live import BDSP_SP_130_HOST_PROFILE, BDSPLiveError  # noqa: E402
from app.ryujinx_host_memory import RyujinxHostMappedClient  # noqa: E402

#: `PlayerWork._saveData`, la misma cadena que ya usan la mochila y las medallas
#: pero sin el salto final, para quedarse en la base del objeto.
CADENA_SAVEDATA = (0x4E7BE98, 0xB8, 0x10, 0x0)

#: Cuánto del objeto se mira. De sobra para el encabezado y los primeros campos.
TAMANO = 0x4000

#: Segundos entre lecturas. Un contador por segundo tiene que moverse.
PAUSA = 3.0

#: Cuántas lecturas. Con tres se distingue "sube siempre" de "cambió una vez".
LECTURAS = 3


def _u32(datos: bytes, offset: int) -> int:
    return int(struct.unpack_from("<I", datos, offset)[0])


def _u16(datos: bytes, offset: int) -> int:
    return int(struct.unpack_from("<H", datos, offset)[0])


def candidatos(muestras: list[bytes], leer, ancho: int) -> list[tuple[int, list[int]]]:
    """Posiciones cuyo valor sube en todas las lecturas y por poco cada vez."""
    salida = []
    for offset in range(0, TAMANO - ancho, ancho):
        valores = [leer(muestra, offset) for muestra in muestras]
        saltos = [b - a for a, b in zip(valores, valores[1:])]
        if all(0 < salto <= 600 for salto in saltos):
            salida.append((offset, valores))
    return salida


def main() -> int:
    print()
    print("  BUSCAR UN LATIDO - Pokemon Perla Reluciente")
    print("  Solo lectura. No se escribe ni un byte.")
    print()
    print("  Ponte QUIETO en el mapa, sin menus abiertos, y no toques nada")
    print(f"  durante los proximos {int(PAUSA * (LECTURAS - 1)) + 2} segundos.")
    print()

    try:
        cliente = RyujinxHostMappedClient(BDSP_SP_130_HOST_PROFILE)
        cliente.connect()
        base = cliente.resolve_main_pointer(CADENA_SAVEDATA)
    except (BDSPLiveError, OSError, RuntimeError, ValueError) as error:
        print(f"  No se pudo conectar: {error}")
        print()
        print("  Hace falta Ryujinx abierto con Perla Reluciente 1.3.0 cargada.")
        return 1

    print(f"  PlayerWork._saveData en 0x{base:X}")
    print()
    muestras = []
    for numero in range(LECTURAS):
        if numero:
            time.sleep(PAUSA)
        try:
            muestras.append(cliente.read_memory(int(base), TAMANO))
        except (OSError, RuntimeError, ValueError) as error:
            print(f"  Se corto la lectura {numero + 1}: {error}")
            return 1
        print(f"    lectura {numero + 1} de {LECTURAS}")

    movidos = [
        offset for offset in range(TAMANO)
        if len({muestra[offset] for muestra in muestras}) > 1
    ]
    print()
    print(f"  bytes que cambiaron ............. {len(movidos)} de {TAMANO}")
    print()
    if movidos:
        print("  cada byte que se movio, con sus tres valores:")
        for offset in movidos[:40]:
            valores = [muestra[offset] for muestra in muestras]
            print(f"     +0x{offset:04X}   {valores}")
        if len(movidos) > 40:
            print(f"     ... y {len(movidos) - 40} mas")
        print()

    for nombre, leer, ancho in (("32 bits", _u32, 4), ("16 bits", _u16, 2)):
        filas = candidatos(muestras, leer, ancho)
        print(f"  contadores de {nombre} que suben en las tres lecturas: {len(filas)}")
        for offset, valores in filas[:14]:
            saltos = [b - a for a, b in zip(valores, valores[1:])]
            print(f"     +0x{offset:04X}   {valores}   sube {saltos}")
        print()

    if not movidos:
        print("  NADA cambio. O el juego esta en pausa, o esta ya congelado,")
        print("  o el latido no vive en este bloque.")
    else:
        print("  Un contador que suba ~3 por lectura avanza una vez por segundo:")
        print("  ese es el candidato a latido. Pegale esta salida a Claude.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
