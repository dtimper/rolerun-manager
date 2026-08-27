from __future__ import annotations

"""Búsqueda manual de solo lectura de la mochila y el dinero en B2/W2.

Todas las capacidades que le quedan a B2/W2 —mochila, MT, utilidades y
medallas— dependen de direcciones de RAM que **no están demostradas**. Inventar
una sería exactamente lo que AGENTS.md prohíbe, así que primero se busca la
evidencia.

El método no es un escaneo a ciegas. En quinta generación cada hueco de la
mochila son dos enteros de 16 bits consecutivos: identificador del objeto y
cantidad. Si el jugador dice cuántas unidades tiene de dos objetos concretos, se
puede buscar exactamente ese par en la RAM y quedarse solo con las zonas donde
aparecen **los dos**, que es una coincidencia mucho más difícil de fabricar por
azar que un número suelto.

Se lee dos veces con una pausa: cualquier candidato que no sobreviva a las dos
lecturas era un buffer transitorio, no la mochila.

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
PAUSA_ENTRE_LECTURAS = 1.5
# Objetos por los que se pregunta. El identificador sale de la misma tabla de
# PKHeX que ya usa RoleRun, no de una lista escrita a mano.
OBJETOS = (
    (4, "Poke Ball"),
    (17, "Pocion"),
    (50, "Caramelo Raro"),
)
DISTANCIA_MAXIMA = 0x400  # dos objetos del mismo bolsillo caen muy cerca
SALIDA = Path("diagnostics/manual/b2w2_bag_latest.json")


def _texto(valor: str) -> str:
    """Evita que un acento tumbe la consola de Windows."""
    try:
        valor.encode(__import__("sys").stdout.encoding or "utf-8")
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


def _buscar_par(ram: bytes, item_id: int, cantidad: int) -> list[int]:
    """Desplazamientos donde hay ``item_id`` seguido de ``cantidad``."""
    patron = struct.pack("<HH", int(item_id), int(cantidad))
    encontrados: list[int] = []
    desde = 0
    while True:
        indice = ram.find(patron, desde)
        if indice < 0:
            break
        if indice % 2 == 0:      # la mochila está alineada a 16 bits
            encontrados.append(indice)
        desde = indice + 1
    return encontrados


def _buscar_u32(ram: bytes, valor: int) -> list[int]:
    patron = struct.pack("<I", int(valor))
    encontrados: list[int] = []
    desde = 0
    while True:
        indice = ram.find(patron, desde)
        if indice < 0:
            break
        if indice % 4 == 0:
            encontrados.append(indice)
        desde = indice + 1
    return encontrados


def _preguntar(mensaje: str) -> int | None:
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
    print(f"melonDS PID {party.process_id} - base 0x{party.allocation_base:X}")
    print()
    print("Abre la MOCHILA dentro del juego y mira las cantidades exactas.")
    print("Si no tienes alguno de estos objetos, deja la respuesta vacia.")
    print()

    peticiones: list[tuple[int, str, int]] = []
    for item_id, etiqueta in OBJETOS:
        nombre = _texto(item_name(item_id)) or etiqueta
        cantidad = _preguntar(f"  Cuantos/as {nombre} tienes? ")
        if cantidad:
            peticiones.append((item_id, nombre, cantidad))

    dinero = _preguntar("  Cuanto dinero tienes exactamente? (vacio para omitir) ")

    if not peticiones and dinero is None:
        print()
        print("Sin ningun dato con el que buscar. Vuelve a ejecutarlo cuando")
        print("tengas al menos un objeto o el dinero a mano.")
        input()
        return

    print()
    print("Leyendo la memoria... no toques el juego durante unos segundos.")
    base = party.allocation_base
    primera = _leer_ram(party.process_id, base)
    time.sleep(PAUSA_ENTRE_LECTURAS)
    segunda = _leer_ram(party.process_id, base)

    resultados = []
    for item_id, nombre, cantidad in peticiones:
        uno = set(_buscar_par(primera, item_id, cantidad))
        dos = set(_buscar_par(segunda, item_id, cantidad))
        estables = sorted(uno & dos)
        resultados.append({
            "item_id": item_id,
            "nombre": nombre,
            "cantidad": cantidad,
            "coincidencias_primera": len(uno),
            "coincidencias_estables": len(estables),
            "direcciones": [f"0x{DS_RAM_BASE + off:08X}" for off in estables[:60]],
            "_offsets": estables,
        })
        print(f"  {nombre}: {len(estables)} coincidencias estables.")

    # Zonas donde coinciden varios objetos distintos: casi con seguridad, un
    # bolsillo de la mochila.
    zonas = []
    if len(resultados) >= 2:
        principal = resultados[0]["_offsets"]
        for offset in principal:
            juntos = [resultados[0]["nombre"]]
            detalles = {resultados[0]["nombre"]: f"0x{DS_RAM_BASE + offset:08X}"}
            for otro in resultados[1:]:
                cercano = next(
                    (o for o in otro["_offsets"] if abs(o - offset) <= DISTANCIA_MAXIMA),
                    None,
                )
                if cercano is not None:
                    juntos.append(otro["nombre"])
                    detalles[otro["nombre"]] = f"0x{DS_RAM_BASE + cercano:08X}"
            if len(juntos) >= 2:
                zonas.append({
                    "objetos_encontrados": juntos,
                    "direcciones": detalles,
                    "ventana_hex": primera[
                        max(0, offset - 16):offset + 48
                    ].hex(),
                })
    print(f"  Zonas con dos o mas objetos juntos: {len(zonas)}")

    dinero_resultado = None
    if dinero is not None:
        uno = set(_buscar_u32(primera, dinero))
        dos = set(_buscar_u32(segunda, dinero))
        estables = sorted(uno & dos)
        dinero_resultado = {
            "valor": dinero,
            "coincidencias_estables": len(estables),
            "direcciones": [f"0x{DS_RAM_BASE + off:08X}" for off in estables[:60]],
        }
        print(f"  Dinero: {len(estables)} coincidencias estables.")

    for resultado in resultados:
        resultado.pop("_offsets", None)

    payload = {
        "format": "rolerun-b2w2-bag-candidates-v1",
        "captured_at": datetime.now().astimezone().isoformat(),
        "environment": "Pokemon Negro 2 Espana - melonDS 1.1",
        "metodo": (
            "Par (item_id, cantidad) de 16 bits alineado, confirmado en dos "
            "lecturas separadas para descartar buffers transitorios."
        ),
        "objetos": resultados,
        "zonas_con_varios_objetos": zonas[:40],
        "dinero": dinero_resultado,
        "note": (
            "Candidatos diagnosticos de solo lectura. Ninguna direccion de aqui "
            "es de produccion mientras no se confirme con un segundo estado."
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
        print()
        print(f"No se pudo leer melonDS: {exc}")
        input()
