"""Lee la mochila viva de Perla Reluciente. No escribe ni un byte.

Al enseñar una MT, RoleRun toca dos sitios: el core PB8 del Pokémon y **un
registro de 12 bytes de la mochila**. Curar y cambiar roles escriben el core y
nunca han congelado el juego; la mochila es lo único nuevo.

Un registro de `PlayerWork.SaveData.saveItem` es:

===========  ==================================================
0..3         cantidad (int32)
4            vanish_new     5  favorito     6  mostrar movimiento
7..9         relleno (tiene que ser 0)
10..11       orden en la mochila (uint16)
===========  ==================================================

Y RoleRun **solo escribe la cantidad**. Cuando una MT baja de 1 a 0, el registro
queda con cantidad 0 **conservando su orden en la mochila**.

La pregunta que responde esta herramienta, leyendo y sin suponer nada: ¿produce
el juego alguna vez ese estado? Si en tu partida no hay ni un solo objeto con
cantidad 0 y orden distinto de 0, entonces RoleRun está dejando la mochila en una
forma que el juego nunca crea, y eso es un sospechoso con nombre.

Si los hay, la hipótesis se cae y hay que buscar en otro sitio.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

from app.bdsp_live import (  # noqa: E402
    BDSP_INVENTORY_BLOCK_SIZE,
    BDSP_INVENTORY_ITEM_COUNT,
    BDSP_INVENTORY_RECORD_SIZE,
    BDSP_SP_130_HOST_PROFILE,
    BDSPInventoryReader,
    BDSPLiveError,
)
from app.ryujinx_host_memory import RyujinxHostMappedClient  # noqa: E402


def leer_bloque():
    cliente = RyujinxHostMappedClient(BDSP_SP_130_HOST_PROFILE)
    cliente.connect()
    lector = BDSPInventoryReader(cliente)
    lectura = lector.read()
    crudo = cliente.read_memory(
        int(lectura.data_pointer), BDSP_INVENTORY_BLOCK_SIZE,
    )
    return lectura, crudo


def describir(crudo: bytes, item_id: int) -> dict:
    offset = item_id * BDSP_INVENTORY_RECORD_SIZE
    return {
        "id": item_id,
        "cantidad": int(struct.unpack_from("<i", crudo, offset)[0]),
        "vanish_new": crudo[offset + 4],
        "favorito": crudo[offset + 5],
        "mostrar_mov": crudo[offset + 6],
        "relleno": crudo[offset + 7:offset + 10].hex(),
        "orden": int(struct.unpack_from("<H", crudo, offset + 10)[0]),
        "bytes": crudo[offset:offset + BDSP_INVENTORY_RECORD_SIZE].hex(" "),
    }


def main() -> int:
    print()
    print("  Leyendo la mochila de Perla Reluciente. No se escribe nada.")
    print()
    try:
        lectura, crudo = leer_bloque()
    except (BDSPLiveError, OSError, RuntimeError, ValueError) as error:
        print(f"  No se pudo leer: {error}")
        print()
        print("  Hace falta Ryujinx abierto con Perla Reluciente 1.3.0 cargada.")
        return 1

    con_cantidad = [
        describir(crudo, item.item_id) for item in lectura.items
    ]
    fantasmas = [
        describir(crudo, item_id)
        for item_id in range(BDSP_INVENTORY_ITEM_COUNT)
        if int(struct.unpack_from(
            "<i", crudo, item_id * BDSP_INVENTORY_RECORD_SIZE,
        )[0]) == 0
        and int(struct.unpack_from(
            "<H", crudo, item_id * BDSP_INVENTORY_RECORD_SIZE + 10,
        )[0]) != 0
    ]

    print(f"  objetos con cantidad ......... {len(con_cantidad)}")
    print(f"  CANTIDAD 0 CON ORDEN ......... {len(fantasmas)}")
    print()

    if fantasmas:
        print("  El juego SI deja registros asi. La hipotesis se cae:")
        for fila in fantasmas[:20]:
            print(f"     id {fila['id']:<5} orden {fila['orden']:<5} "
                  f"flags {fila['vanish_new']}{fila['favorito']}"
                  f"{fila['mostrar_mov']}   {fila['bytes']}")
        if len(fantasmas) > 20:
            print(f"     ... y {len(fantasmas) - 20} mas")
    else:
        print("  NO hay ni uno. Cuando el juego gasta el ultimo objeto de una")
        print("  clase, deja el registro entero a cero, no solo la cantidad.")
        print()
        print("  RoleRun solo escribe la cantidad, asi que al gastar la ultima")
        print("  MT deja la mochila en una forma que el juego nunca crea.")

    print()
    print("  Los diez primeros objetos que tienes, tal cual estan en memoria:")
    for fila in con_cantidad[:10]:
        print(f"     id {fila['id']:<5} x{fila['cantidad']:<4} orden {fila['orden']:<5} "
              f"relleno {fila['relleno']}   {fila['bytes']}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
