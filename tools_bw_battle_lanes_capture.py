from __future__ import annotations

"""Localiza y ordena las copias de combate de Blanco/Negro por DOS ESTADOS.

POR QUE SE CAMBIO DE METODO

El primer intento buscaba filas que encajaran con una firma de cuatro campos
-especie, PS maximos, habilidad y nivel- suponiendo que Blanco coloca esos
campos igual que Negro 2. Fallo dos veces:

  1. Encontro una fila con un Pansear a nivel 3342: coincidio por azar.
  2. Con el Purrloin debilitado y el Serperior luchando, solo encontro las dos
     copias viejas del Purrloin a 0/27. La fila del que estaba peleando no
     aparecio, porque la suposicion sobre el formato no se cumple.

Este metodo no supone nada del formato. Se apoya en lo unico que es seguro: si
un Pokemon pasa de X a Y puntos de salud, en la memoria hay posiciones que
contenian X y ahora contienen Y. Es el mismo procedimiento con el que se
demostraron la mochila y el dinero, y el que el documento de paridad exige.

COMO SE ORDENAN DESPUES

Encontradas las posiciones, la tercera parte las vigila durante otro golpe. En
Negro 2 la copia logica baja los PS unos segundos antes que la de presentacion
-3,4 s en su traza-, y esa diferencia es lo que dice cual manda en pantalla.
Importa: con la logica como autoridad, RoleRun cantaria una baja que el jugador
todavia no ha visto.

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
    PK5_PARTY_SIZE,
    B2W2LiveError,
    B2W2MelonDSReader,
    _KERNEL32,
)
from app.gen5_memory import GEN5_MEMORY

TAMANO_RAM = 0x00400000
ESPERA_MAXIMA = 90.0
COLA = 6.0
CONTEXTO = 16          # bytes a cada lado que se guardan de cada candidata
SALIDA = Path("diagnostics/manual/bw_battle_lanes_latest.json")


def _abrir(pid: int):
    handle = _KERNEL32.OpenProcess(0x0400 | 0x0010, False, int(pid))
    if not handle:
        raise OSError("No se pudo abrir melonDS en modo lectura.")
    return handle


def _leer(handle, direccion: int, tamano: int) -> bytes:
    buffer = ctypes.create_string_buffer(tamano)
    recibido = ctypes.c_size_t()
    ok = _KERNEL32.ReadProcessMemory(
        handle, ctypes.c_void_p(direccion), buffer, tamano, ctypes.byref(recibido),
    )
    if not ok or recibido.value != tamano:
        raise OSError("Lectura incompleta de la RAM de melonDS.")
    return buffer.raw


def _numero(mensaje: str) -> int | None:
    respuesta = input(mensaje).strip()
    if not respuesta:
        return None
    try:
        return max(0, int(respuesta))
    except ValueError:
        print("  No era un numero.")
        return None


def _cambiaron(antes: bytes, despues: bytes, viejo: int, nuevo: int) -> list[int]:
    """Posiciones que contenian el valor viejo y ahora contienen el nuevo.

    Un numero suelto aparece muchas veces en 4 MiB; lo que no aparece por azar
    es que en la MISMA posicion cambie exactamente de uno al otro.
    """
    patron_viejo = struct.pack("<H", viejo)
    patron_nuevo = struct.pack("<H", nuevo)
    salida: list[int] = []
    desde = 0
    while True:
        indice = antes.find(patron_viejo, desde)
        if indice < 0:
            return salida
        desde = indice + 1
        if indice % 2:
            continue
        if despues[indice:indice + 2] == patron_nuevo:
            salida.append(indice)


def main() -> None:
    memoria = GEN5_MEMORY["bw"]
    lector = B2W2MelonDSReader(memoria)
    party = lector.read_party()
    print(f"melonDS PID {party.process_id} - {memoria.label}")
    for indice, p in enumerate(party.pokemon):
        print(f"   {indice + 1}. {p.nickname:12} Nv.{p.level:3}  PS {p.current_hp}/{p.max_hp}")
    print()
    print("=== PASO 1 de 3: quien esta luchando ===")
    print("Entra en combate y mira los PS del Pokemon que tienes en el campo.")
    print()
    antes_ps = _numero("  Cuantos PS le quedan AHORA? ")
    if antes_ps is None:
        print("\nSin ese dato no se puede buscar nada.")
        input()
        return

    handle = _abrir(party.process_id)
    try:
        print("Leyendo... no toques el juego.")
        antes = _leer(handle, party.allocation_base, TAMANO_RAM)

        print()
        print("=== PASO 2 de 3: recibe un golpe ===")
        print("Ejecuta un turno en el que TU Pokemon reciba dano y espera a que")
        print("la barra termine de bajar del todo.")
        print()
        input("Cuando la barra se haya quedado quieta, pulsa INTRO...")
        despues_ps = _numero("  Cuantos PS le quedan AHORA? ")
        if despues_ps is None or despues_ps == antes_ps:
            print("\nHace falta que los PS hayan cambiado.")
            input()
            return
        print("Leyendo otra vez... no toques el juego.")
        despues = _leer(handle, party.allocation_base, TAMANO_RAM)

        candidatas = _cambiaron(antes, despues, antes_ps, despues_ps)
        inicio_party = memoria.party_data - DS_RAM_BASE
        fin_party = inicio_party + len(party.pokemon) * PK5_PARTY_SIZE
        fuera = [c for c in candidatas if not inicio_party <= c < fin_party]

        detalle = []
        for offset in fuera:
            desde = max(0, offset - CONTEXTO)
            detalle.append({
                "direccion": f"0x{DS_RAM_BASE + offset:08X}",
                "offset": offset,
                "contexto_antes": antes[desde:offset + CONTEXTO].hex(),
                "contexto_despues": despues[desde:offset + CONTEXTO].hex(),
            })

        print()
        print(f"Posiciones que pasaron de {antes_ps} a {despues_ps}: {len(candidatas)}")
        print(f"  fuera del bloque de equipo: {len(fuera)}")
        for d in detalle[:16]:
            print(f"   {d['direccion']}")
        if not fuera:
            print()
            print("Ninguna fuera del equipo. Eso querria decir que Blanco no")
            print("mantiene una copia aparte, cosa que Negro 2 si hace.")
            payload_vacio = True
        else:
            payload_vacio = False

        primeros: dict[int, float] = {}
        transiciones = []
        muestras = 0
        if fuera:
            print()
            print("=== PASO 3 de 3: otro golpe, para ver cual va primero ===")
            print("Prepara otro turno en el que recibas dano. No lo ejecutes.")
            print()
            input("Pulsa INTRO y ejecuta el turno...")
            print("Vigilando...")
            direcciones = [party.allocation_base + o for o in fuera]
            base = [
                struct.unpack("<H", _leer(handle, d, 2))[0] for d in direcciones
            ]
            arranque = time.perf_counter()
            primer_cambio = None
            while time.perf_counter() - arranque < ESPERA_MAXIMA:
                ms = round((time.perf_counter() - arranque) * 1000, 1)
                actual = [
                    struct.unpack("<H", _leer(handle, d, 2))[0] for d in direcciones
                ]
                muestras += 1
                for i, valor in enumerate(actual):
                    if i not in primeros and valor != base[i]:
                        primeros[i] = ms
                        if primer_cambio is None:
                            primer_cambio = time.perf_counter()
                        print(f"   {detalle[i]['direccion']} cambio a los {ms:.0f} ms "
                              f"({base[i]} -> {valor})")
                if actual != (transiciones[-1]["ps"] if transiciones else None):
                    transiciones.append({"ms": ms, "ps": actual})
                if primer_cambio is not None and time.perf_counter() - primer_cambio >= COLA:
                    break
                time.sleep(0.01)
    finally:
        _KERNEL32.CloseHandle(handle)

    print()
    if len(primeros) >= 2:
        orden = sorted(primeros, key=lambda k: primeros[k])
        print(f"   LOGICA (se adelanta):    {detalle[orden[0]]['direccion']}")
        print(f"   PRESENTACION (la barra): {detalle[orden[-1]]['direccion']}")
        print(f"   diferencia: {primeros[orden[-1]] - primeros[orden[0]]:.0f} ms")
    elif len(primeros) == 1:
        print("Solo cambio una. Puede que Blanco tenga una sola copia aparte.")
    elif not payload_vacio:
        print("Ninguna cambio en el segundo golpe. Puede que el turno no llegara")
        print("a resolverse dentro del tiempo de espera.")

    payload = {
        "format": "rolerun-bw-battle-lanes-v2",
        "captured_at": datetime.now().astimezone().isoformat(),
        "environment": f"{memoria.label} Espana - melonDS 1.1",
        "metodo": (
            "Dos estados: se guardan las posiciones que contenian los PS viejos "
            "y se conservan solo las que, en esa misma posicion, pasan a "
            "contener los nuevos. No supone nada sobre el formato de la fila. "
            "Despues se vigilan durante otro golpe para ver cual cambia antes."
        ),
        "ps_antes": antes_ps,
        "ps_despues": despues_ps,
        "equipo": [
            {"mote": p.nickname, "especie": int(p.species_id), "nivel": int(p.level),
             "ps": f"{p.current_hp}/{p.max_hp}", "habilidad": int(p.ability_id)}
            for p in party.pokemon
        ],
        "candidatas": detalle,
        "muestras": muestras,
        "transiciones": transiciones,
        "primer_cambio_ms": {
            detalle[i]["direccion"]: primeros[i] for i in primeros
        },
        "note": (
            "Diagnostico de solo lectura. Una direccion aqui no pasa a "
            "produccion mientras no se sepa cual manda en pantalla."
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
