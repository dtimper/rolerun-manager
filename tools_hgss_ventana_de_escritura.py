"""Cuándo se puede escribir en una ficha de HeartGold sin romperla.

QUÉ PREGUNTA RESPONDE

Tres veces se escribió una ficha correcta, en el hueco correcto y en la
dirección correcta, y el juego enseñó un «Huevo malo». El codificador está
probado byte a byte contra la partida real, así que el problema no es lo que se
escribe sino **cuándo**.

La hipótesis: el juego descifra la ficha en su sitio, hace lo suyo y la vuelve a
cifrar. Si la escritura cae en esa ventana, el juego re-cifra unos bytes que ya
estaban cifrados y el checksum deja de cuadrar. Eso es un «Huevo malo», y encaja
con que la verificación saliera bien —lee lo recién escrito— y el huevo
apareciera después, al volver el juego a mirar la ficha.

CÓMO LO MIDE

Muestrea el bloque de equipo miles de veces por fase y clasifica cada ficha:

  reposo      el estado normal, el contenido que sale la inmensa mayoría de
              las veces
  en claro    la misma ficha legible pero sin cifrar: la ventana peligrosa
  partida     ni una cosa ni la otra, la lectura pilló un cambio a medias

Y mide **cuánto duran** esas ventanas, que es lo que decide si se puede escribir
entre dos de ellas o no se puede escribir nunca mientras el juego corre.

NO ESCRIBE NADA. Ni un byte, en ninguna fase.
"""

from __future__ import annotations

import ctypes
import json
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
    PK4_PARTY_SIZE, PK4_STORED_SIZE, Pk4Error, parse_pk4_party, unshuffle_pk4,
)

CONFIG = Path.home() / "Documents" / "RoleRun Manager" / "Config" / "game_sources.json"
SEGUNDOS_POR_FASE = 6

FASES = (
    ("QUIETO", "Deja al personaje parado en el mapa, sin tocar nada."),
    ("ANDANDO", "Muevete por el mapa sin parar durante toda la fase."),
    ("MENU POKEMON", "Abre el menu y entra en POKEMON. Dejalo abierto."),
)


def _firma() -> bytes:
    datos = json.loads(CONFIG.read_text(encoding="utf-8"))
    return Path(datos["games"]["hgss"]["save_path"]).read_bytes()[0x64:0x64 + 0x14]


def _clasificar(registro: bytes) -> str:
    """En qué estado está esa ficha: reposo, en claro, o partida."""
    try:
        parse_pk4_party(registro, 0)
    except Pk4Error:
        return "partida"
    try:
        _pid, _orden, _canonico, cifrado = unshuffle_pk4(registro[:PK4_STORED_SIZE])
    except Pk4Error:
        return "partida"
    return "reposo" if cifrado else "en claro"


def _rachas(estados: list[str]) -> dict[str, tuple[int, int, int]]:
    """Cuántas rachas de cada estado, y cuánto duran la media y la peor."""
    resumen: dict[str, list[int]] = {}
    actual, largo = None, 0
    for estado in estados + [None]:
        if estado == actual:
            largo += 1
            continue
        if actual is not None:
            resumen.setdefault(actual, []).append(largo)
        actual, largo = estado, 1
    return {
        estado: (len(largos), sum(largos) // len(largos), max(largos))
        for estado, largos in resumen.items()
    }


def main() -> int:
    print()
    print("  CUANDO SE PUEDE ESCRIBIR EN UNA FICHA DE HEARTGOLD")
    print("  " + "-" * 62)
    print()
    print("  Esta herramienta NO escribe nada. Solo mira, muy deprisa.")
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
        print(f"  Bloque: 0x{DS_RAM_BASE + principio:08X}"
              f"   (de {len(candidatos)} copias, la de direccion mas baja)")

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
        nombres = []
        for indice in range(cuantos):
            crudo = leer(SAVE_PARTY_DATA + indice * PK4_PARTY_SIZE, PK4_PARTY_SIZE)
            try:
                nombres.append(parse_pk4_party(crudo, indice).nickname)
            except Pk4Error:
                nombres.append(f"hueco {indice + 1}")
        print(f"  Equipo:  {', '.join(nombres)}")
        print()

        for titulo, instruccion in FASES:
            print("  " + "=" * 62)
            print(f"  FASE: {titulo}")
            print(f"  {instruccion}")
            print("  Pon el foco en melonDS. Empieza en 6 segundos.")
            for queda in range(6, 0, -1):
                print(f"    {queda}... ", end="", flush=True)
                time.sleep(1)
            print("  MIDIENDO", flush=True)

            estados: list[list[str]] = [[] for _ in range(cuantos)]
            contenidos: list[dict[bytes, int]] = [{} for _ in range(cuantos)]
            muestras = 0
            final = time.perf_counter() + SEGUNDOS_POR_FASE
            while time.perf_counter() < final:
                bloque = leer(SAVE_PARTY_DATA, cuantos * PK4_PARTY_SIZE)
                for indice in range(cuantos):
                    registro = bloque[
                        indice * PK4_PARTY_SIZE:(indice + 1) * PK4_PARTY_SIZE
                    ]
                    estados[indice].append(_clasificar(registro))
                    contenidos[indice][registro] = (
                        contenidos[indice].get(registro, 0) + 1
                    )
                muestras += 1

            ritmo = muestras / SEGUNDOS_POR_FASE
            print(f"  {muestras} muestras en {SEGUNDOS_POR_FASE}s "
                  f"({ritmo:.0f} por segundo, una cada {1000 / ritmo:.2f} ms)")
            print()
            for indice in range(cuantos):
                cuenta: dict[str, int] = {}
                for estado in estados[indice]:
                    cuenta[estado] = cuenta.get(estado, 0) + 1
                reposo = cuenta.get("reposo", 0)
                claro = cuenta.get("en claro", 0)
                partida = cuenta.get("partida", 0)
                distintos = len(contenidos[indice])
                mayor = max(contenidos[indice].values())
                print(f"    {nombres[indice]:10} reposo {reposo:5}  "
                      f"en claro {claro:5}  partida {partida:5}   "
                      f"contenidos {distintos:3}, el dominante {mayor}")
                rachas = _rachas(estados[indice])
                for estado in ("en claro", "partida"):
                    if estado in rachas:
                        veces, media, peor = rachas[estado]
                        print(f"               ventana '{estado}': {veces} veces, "
                              f"{media * 1000 / ritmo:.1f} ms de media, "
                              f"{peor * 1000 / ritmo:.1f} ms la peor")
            print()
    finally:
        _KERNEL32.CloseHandle(handle)

    print("  " + "=" * 62)
    print("  Copia TODO este texto y pegaselo a Claude.")
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
