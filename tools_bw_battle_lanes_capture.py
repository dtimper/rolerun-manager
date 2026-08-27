from __future__ import annotations

"""Descubre y ordena las copias de combate de Blanco/Negro, en una sola pasada.

QUE SE APRENDIO DEL INTENTO ANTERIOR

La busqueda por firma del 27-08-2026 dio dos filas, pero la segunda no era una
copia del Pokemon del jugador: al volver a mirarla tenia un Pansear a nivel
3342. Coincidio una vez por azar y ya no.

La traza de Negro 2 muestra como son de verdad las dos copias buenas: LAS DOS
describen al mismo Pokemon, y la logica baja los PS unos SEGUNDOS antes que la
de presentacion. En aquella captura fueron 3,4 s de diferencia.

QUE HACE ESTA HERRAMIENTA

Las dos cosas de golpe, sin suponer ninguna distancia entre ellas:

1. Busca en la RAM TODAS las filas que describen al Pokemon que esta luchando
   -misma especie, mismos PS maximos, misma habilidad y mismo nivel-.
2. Las vigila todas a la vez cada 10 ms durante un turno y apunta cuando cambia
   cada una.

La que baje los PS antes es la logica; la que lo haga despues, al ritmo de la
barra, es la de presentacion. Importa cual es cual: con la logica como
autoridad, RoleRun cantaria una baja que el jugador todavia no ha visto.

No escribe un solo byte en la partida ni activa ninguna capacidad.
"""

import ctypes
import json
import struct
import time
from datetime import datetime
from pathlib import Path

from app.b2w2_live import (
    BATTLE_ROW_SIZE,
    BATTLE_STATUS_OFFSET,
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


def _buscar_filas(ram: bytes, equipo, memoria) -> list[dict]:
    """Todas las posiciones que describen a un miembro del equipo."""
    por_firma = {
        (int(p.species_id), int(p.max_hp), int(p.ability_id), int(p.level)): p
        for p in equipo
    }
    inicio_party = memoria.party_data - DS_RAM_BASE
    fin_party = inicio_party + len(equipo) * PK5_PARTY_SIZE

    salida: list[dict] = []
    palabras = len(ram) // 2
    valores = struct.unpack_from(f"<{palabras}H", ram, 0)
    for indice in range(palabras - 7):
        miembro = por_firma.get((
            valores[indice], valores[indice + 1],
            valores[indice + 5], valores[indice + 6],
        ))
        if miembro is None:
            continue
        offset = indice * 2
        if inicio_party <= offset < fin_party:
            continue        # el bloque de equipo no es el carril de combate
        if valores[indice + 2] > miembro.max_hp:
            continue
        salida.append({
            "direccion": f"0x{DS_RAM_BASE + offset:08X}",
            "offset": offset,
            "mote": miembro.nickname,
            "ps_inicial": int(valores[indice + 2]),
            "max_hp": int(miembro.max_hp),
        })
    return salida


def main() -> None:
    memoria = GEN5_MEMORY["bw"]
    lector = B2W2MelonDSReader(memoria)
    party = lector.read_party()
    print(f"melonDS PID {party.process_id} - {memoria.label}")
    for p in party.pokemon:
        print(f"   {p.nickname:12} Nv.{p.level:3}  PS {p.current_hp}/{p.max_hp}")
    print()
    print("=== PASO 1: entra en combate ===")
    print("Mejor si tu Pokemon ya ha recibido algun golpe: con la vida llena")
    print("hay mas filas que coinciden por casualidad.")
    print()
    input("Cuando estes en combate, pulsa INTRO...")

    handle = _abrir(party.process_id)
    try:
        print("Buscando las copias... no toques el juego.")
        ram = _leer(handle, party.allocation_base, TAMANO_RAM)
        filas = _buscar_filas(ram, party.pokemon, memoria)
        print()
        print(f"Filas encontradas: {len(filas)}")
        for f in filas:
            print(f"   {f['direccion']}  {f['mote']:11} PS {f['ps_inicial']}/{f['max_hp']}")
        if not filas:
            print()
            print("Ninguna. Puede que el combate no haya empezado del todo.")
            input()
            return

        print()
        print("=== PASO 2: recibe un golpe ===")
        print("Prepara un turno en el que TU Pokemon vaya a recibir dano.")
        print("No lo ejecutes todavia.")
        print()
        input("Pulsa INTRO y ejecuta el turno...")
        print("Vigilando las filas...")

        direcciones = [party.allocation_base + f["offset"] for f in filas]
        inicio = time.perf_counter()
        anterior = None
        primer_cambio = None
        transiciones = []
        muestras = 0
        while time.perf_counter() - inicio < ESPERA_MAXIMA:
            ms = round((time.perf_counter() - inicio) * 1000, 1)
            actual = tuple(
                struct.unpack_from("<7H", _leer(handle, d, BATTLE_ROW_SIZE))
                for d in direcciones
            )
            muestras += 1
            if actual != anterior:
                transiciones.append({
                    "ms": ms,
                    "ps": [int(v[2]) for v in actual],
                    "filas": [list(v) for v in actual],
                })
                if anterior is not None and primer_cambio is None:
                    primer_cambio = time.perf_counter()
                    print(f"  cambio a los {ms:.0f} ms: PS {[int(v[2]) for v in actual]}")
                anterior = actual
            if primer_cambio is not None and time.perf_counter() - primer_cambio >= COLA:
                break
            time.sleep(0.01)
    finally:
        _KERNEL32.CloseHandle(handle)

    # Cuando cambio por primera vez cada fila.
    primeros: dict[int, float] = {}
    base = transiciones[0]["ps"] if transiciones else []
    for tr in transiciones[1:]:
        for i, ps in enumerate(tr["ps"]):
            if i not in primeros and i < len(base) and ps != base[i]:
                primeros[i] = tr["ms"]

    print()
    print("Orden en que bajaron los PS:")
    for i in sorted(primeros, key=lambda k: primeros[k]):
        print(f"   {filas[i]['direccion']}  a los {primeros[i]:.0f} ms")
    if len(primeros) >= 2:
        orden = sorted(primeros, key=lambda k: primeros[k])
        print()
        print(f"   LOGICA (se adelanta):      {filas[orden[0]]['direccion']}")
        print(f"   PRESENTACION (la barra):   {filas[orden[-1]]['direccion']}")
    elif len(primeros) == 1:
        print()
        print("Solo cambio una. Puede que solo haya una copia, o que la otra")
        print("no estuviera entre las encontradas.")

    payload = {
        "format": "rolerun-bw-battle-lanes-v1",
        "captured_at": datetime.now().astimezone().isoformat(),
        "environment": f"{memoria.label} Espana - melonDS 1.1",
        "metodo": (
            "Se buscan todas las filas que describen al Pokemon en combate y se "
            "vigilan a la vez cada 10 ms. La que baja los PS antes es la logica; "
            "la que lo hace despues, al ritmo de la barra, la de presentacion."
        ),
        "equipo": [
            {"mote": p.nickname, "especie": int(p.species_id), "nivel": int(p.level),
             "ps": f"{p.current_hp}/{p.max_hp}", "habilidad": int(p.ability_id)}
            for p in party.pokemon
        ],
        "filas": filas,
        "muestras": muestras,
        "transiciones": transiciones,
        "primer_cambio_ms": {filas[i]["direccion"]: primeros[i] for i in primeros},
        "note": (
            "Diagnostico de solo lectura. Sin dos filas que cambien no se puede "
            "decidir cual manda en pantalla."
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
