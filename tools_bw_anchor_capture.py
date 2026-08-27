from __future__ import annotations

"""Localización del ancla de Pokémon Blanco/Negro en la RAM de melonDS.

QUÉ HACE FALTA ENCONTRAR, Y POR QUÉ SOLO UNA COSA

El 27-08-2026 se demostró que el bloque vivo de quinta generación es un
**espejo contiguo del guardado**: partiendo solo de la dirección del dinero de
Negro 2 aparecen, en el archivo, el contador del equipo y sus seis Pokémon en
las posiciones que predice PKHeX. Así que con **un solo ancla** salen las demás
direcciones restando y sumando desplazamientos ya conocidos.

Blanco no puede heredar las de Negro 2 —su dinero está en `0x21200` del
guardado y el de Negro 2 en `0x21100`—, pero sí puede heredar el método.

CÓMO SE LOCALIZA SIN INVENTAR NADA

Blanco y Negro 2 comparten el formato PK5, así que un miembro del equipo tiene
una firma comprobable: 220 bytes cuyo **checksum cuadra** tras descifrarlos, con
una especie, un nivel y unos PS posibles. Eso no lo produce el azar.

Encontrado el equipo, la herramienta comprueba además que en las direcciones
que **predice** el desplazamiento del guardado haya un dinero y unas medallas
coherentes. Si las tres cosas encajan, el espejo también vale para Blanco.

No escribe un solo byte en la partida ni activa ninguna capacidad.
"""

import ctypes
import json
import struct
from datetime import datetime
from pathlib import Path

from app.b2w2_live import (
    DS_RAM_BASE,
    MAX_PARTY,
    PK5_PARTY_SIZE,
    B2W2LiveError,
    B2W2MelonDSReader,
    _KERNEL32,
    parse_pk5_party,
)

TAMANO_RAM = 0x00400000

# Desplazamientos dentro del guardado, extraidos de PKHeX y no supuestos.
# El bloque de equipo arranca igual en los dos juegos; el dinero no.
SAVE_PARTY_BLOCK = 0x18E00
SAVE_PARTY_COUNT = SAVE_PARTY_BLOCK + 4
SAVE_PARTY_DATA = SAVE_PARTY_BLOCK + 8
SAVE_MONEY_BW = 0x21200
SAVE_BADGES_BW = 0x21204

SALIDA = Path("diagnostics/manual/bw_anchor_latest.json")


def _procesos() -> list[tuple[int, str]]:
    return B2W2MelonDSReader._list_melonds_processes()


def _regiones(pid: int) -> list[int]:
    """Bases de asignación de 4 MiB, que es el tamaño de la RAM de la DS."""
    kernel32 = _KERNEL32
    handle = kernel32.OpenProcess(0x0400 | 0x0010, False, int(pid))
    if not handle:
        raise OSError("No se pudo abrir melonDS en modo lectura.")

    from ctypes import wintypes

    class MBI(ctypes.Structure):
        _fields_ = [
            ("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
            ("AllocationProtect", wintypes.DWORD), ("PartitionId", wintypes.WORD),
            ("RegionSize", ctypes.c_size_t), ("State", wintypes.DWORD),
            ("Protect", wintypes.DWORD), ("Type", wintypes.DWORD),
        ]

    try:
        salida: list[int] = []
        direccion = 0
        info = MBI()
        while direccion < 0x00007FFFFFFF0000:
            if not kernel32.VirtualQueryEx(
                handle, ctypes.c_void_p(direccion), ctypes.byref(info),
                ctypes.sizeof(info),
            ):
                break
            tamano = int(info.RegionSize or 0)
            if tamano <= 0:
                break
            # MEM_COMMIT y con permiso de lectura y escritura.
            if int(info.State) == 0x1000 and int(info.Protect) in (0x04, 0x40):
                if tamano >= TAMANO_RAM:
                    salida.append(int(info.BaseAddress or 0))
            direccion += tamano
        return salida
    finally:
        kernel32.CloseHandle(handle)


def _leer(pid: int, direccion: int, tamano: int) -> bytes:
    kernel32 = _KERNEL32
    handle = kernel32.OpenProcess(0x0400 | 0x0010, False, int(pid))
    if not handle:
        raise OSError("No se pudo abrir melonDS en modo lectura.")
    try:
        buffer = ctypes.create_string_buffer(tamano)
        recibido = ctypes.c_size_t()
        ok = kernel32.ReadProcessMemory(
            handle, ctypes.c_void_p(direccion), buffer, tamano, ctypes.byref(recibido),
        )
        if not ok or recibido.value != tamano:
            return b""
        return buffer.raw
    finally:
        kernel32.CloseHandle(handle)


def _miembros(ram: bytes) -> list[dict]:
    """Toda posición alineada donde arranca un PK5 de party creíble."""
    salida: list[dict] = []
    for offset in range(0, len(ram) - PK5_PARTY_SIZE, 4):
        checksum = struct.unpack_from("<H", ram, offset + 6)[0]
        if checksum in (0, 0xFFFF):
            continue
        try:
            pokemon = parse_pk5_party(ram[offset:offset + PK5_PARTY_SIZE], 0)
        except Exception:
            continue
        if not (1 <= pokemon.species_id <= 649 and 1 <= pokemon.level <= 100):
            continue
        if not (0 < pokemon.max_hp <= 999 and 0 <= pokemon.current_hp <= pokemon.max_hp):
            continue
        salida.append({
            "offset": offset,
            "direccion": f"0x{DS_RAM_BASE + offset:08X}",
            "especie": int(pokemon.species_id),
            "mote": pokemon.nickname,
            "nivel": int(pokemon.level),
            "ps": f"{pokemon.current_hp}/{pokemon.max_hp}",
        })
    return salida


def _numero(mensaje: str, tope: int) -> int | None:
    respuesta = input(mensaje).strip()
    if not respuesta:
        return None
    try:
        return max(0, min(tope, int(respuesta)))
    except ValueError:
        print("  No era un numero.")
        return None


def main() -> None:
    procesos = _procesos()
    if not procesos:
        print("No hay ningun melonDS abierto.")
        input()
        return
    pid, nombre = procesos[0]
    print(f"melonDS PID {pid}")
    print()
    print("=== TU EQUIPO AHORA MISMO ===")
    cuantos = _numero("  Cuantos Pokemon llevas en el equipo? ", MAX_PARTY)
    if not cuantos:
        print("\nHace falta al menos uno para poder reconocer el equipo.")
        input()
        return
    dinero = _numero("  Cuanto dinero tienes exactamente? ", 9_999_999)
    medallas = _numero("  Cuantas medallas tienes? ", 8)

    print()
    print("Buscando... esto tarda un poco. No toques el juego.")

    resultados = []
    for base in _regiones(pid):
        ram = _leer(pid, base, TAMANO_RAM)
        if len(ram) != TAMANO_RAM:
            continue
        miembros = _miembros(ram)
        if not miembros:
            continue
        for miembro in miembros:
            offset = miembro["offset"]
            # Si esto es el equipo, el contador esta CUATRO bytes antes: el
            # bloque empieza ocho antes de los datos y el contador va en +4.
            # La primera version leia -8 y daba el byte de cabecera, que en la
            # captura del 27-08-2026 valia 6 en un equipo de cuatro.
            contador = ram[offset - 4] if offset >= 4 else None
            bloque = (DS_RAM_BASE + offset) - SAVE_PARTY_DATA
            prediccion = {}
            for etiqueta, desplazamiento, ancho in (
                ("dinero", SAVE_MONEY_BW, 3), ("medallas", SAVE_BADGES_BW, 1),
            ):
                pos = (bloque + desplazamiento) - DS_RAM_BASE
                if 0 <= pos + ancho <= len(ram):
                    valor = int.from_bytes(ram[pos:pos + ancho], "little")
                    prediccion[etiqueta] = {
                        "direccion": f"0x{bloque + desplazamiento:08X}",
                        "valor": valor if etiqueta == "dinero" else bin(valor).count("1"),
                    }
            resultados.append({
                **miembro,
                "region": f"0x{base:X}",
                "contador_en_-4": contador,
                "contador_cuadra": contador == cuantos,
                "base_del_bloque": f"0x{bloque:08X}",
                "prediccion": prediccion,
            })

    # El bueno es el que cuadra en las tres cosas a la vez.
    def cuadra(r: dict) -> bool:
        if not r["contador_cuadra"]:
            return False
        p = r.get("prediccion", {})
        if dinero is not None and p.get("dinero", {}).get("valor") != dinero:
            return False
        if medallas is not None and p.get("medallas", {}).get("valor") != medallas:
            return False
        return True

    buenos = [r for r in resultados if cuadra(r)]

    print()
    print(f"Bloques PK5 creibles encontrados: {len(resultados)}")
    for r in resultados[:14]:
        marca = "  <-- CUADRA TODO" if cuadra(r) else ""
        p = r.get("prediccion", {})
        print(f"  {r['direccion']}  {r['mote']:11} #{r['especie']:3} Nv.{r['nivel']:3} "
              f"PS {r['ps']:8} contador={r['contador_en_-4']}"
              f"  dinero={p.get('dinero',{}).get('valor')}"
              f" medallas={p.get('medallas',{}).get('valor')}{marca}")
    print()
    if len(buenos) == 1:
        r = buenos[0]
        print(f"ANCLA ENCONTRADA: equipo en {r['direccion']}")
        print(f"  base del bloque: {r['base_del_bloque']}")
        print(f"  dinero:   {r['prediccion']['dinero']['direccion']}")
        print(f"  medallas: {r['prediccion']['medallas']['direccion']}")
    elif not buenos:
        print("Ninguno cuadra en las tres cosas. Revisa los datos que has dado")
        print("o mandame el archivo: puede que Blanco no coloque el bloque igual.")
    else:
        print(f"{len(buenos)} candidatos cuadran: hara falta un segundo estado.")

    payload = {
        "format": "rolerun-bw-anchor-v1",
        "captured_at": datetime.now().astimezone().isoformat(),
        "environment": "Pokemon Blanco Espana - melonDS 1.1",
        "metodo": (
            "Se busca un PK5 de party valido -checksum, especie, nivel y PS "
            "posibles- y se comprueba que el contador este ocho bytes antes y "
            "que el dinero y las medallas caigan donde los predice el "
            "desplazamiento del guardado que declara PKHeX."
        ),
        "declarado": {"equipo": cuantos, "dinero": dinero, "medallas": medallas},
        "desplazamientos_pkhex": {
            "party_block": f"0x{SAVE_PARTY_BLOCK:X}",
            "money": f"0x{SAVE_MONEY_BW:X}",
            "badges": f"0x{SAVE_BADGES_BW:X}",
        },
        "candidatos": resultados,
        "cuadran_del_todo": [r["direccion"] for r in buenos],
        "note": (
            "Diagnostico de solo lectura. Una direccion aqui no pasa a "
            "produccion mientras no sea la unica que cuadra en las tres cosas."
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
