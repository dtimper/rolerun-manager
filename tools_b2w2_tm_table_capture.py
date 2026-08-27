from __future__ import annotations

"""Localización de solo lectura de la tabla MT/MO dentro de la RAM de B2/W2.

POR QUÉ NO VALE LA TABLA DE PKHeX

RoleRun está pensado para jugarse en **randomizers**. Un randomizer puede
cambiar qué movimiento enseña cada MT, así que una tabla extraída una sola vez
de PKHeX describe la quinta generación original y no necesariamente la partida
que hay delante. La tabla buena es la que el juego tiene cargada ahora mismo.

CÓMO SE LOCALIZA SIN INVENTAR NADA

La lista MT/MO de quinta generación son 101 movimientos consecutivos de 16 bits
dentro del binario del juego, que melonDS mantiene en la RAM principal. Esa
forma es una firma muy fuerte: 101 valores seguidos, todos entre 1 y 559 (el
último movimiento de quinta) y **todos distintos**. En 4 MiB de memoria, el
azar no produce eso.

Y en una partida NO randomizada hay una segunda comprobación independiente: la
lista encontrada tiene que coincidir **movimiento a movimiento** con la que
`tools_extract_gen5_tm` derivó de PKHeX. Si coincide, la dirección queda
demostrada por dos caminos que no dependen el uno del otro, y a partir de ahí
sirve también para partidas randomizadas, donde el contenido cambiará pero la
posición no.

No escribe un solo byte en la partida ni activa ninguna capacidad.
"""

import ctypes
import json
import struct
from datetime import datetime
from pathlib import Path

from app.b2w2_live import (
    DS_RAM_BASE,
    B2W2LiveError,
    B2W2MelonDSReader,
    _KERNEL32,
)
from app.gen5_memory import GEN5_MEMORY
from app.b2w2_tm_service import reference_move_ids

# RAM principal de la DS: 4 MiB a partir de 0x02000000.
TAMANO_RAM = 0x00400000
TOTAL_MT = 101
MOVIMIENTO_MAXIMO = 559
def _salida(clave: str) -> Path:
    return Path(f"diagnostics/manual/{clave}_tm_table_latest.json")


def _texto(valor: str) -> str:
    import sys

    try:
        valor.encode(sys.stdout.encoding or "utf-8")
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


def _candidatos(ram: bytes) -> list[dict]:
    """Toda posición donde arrancan 101 movimientos válidos y distintos.

    Una sola pasada: primero se aíslan los tramos donde **todos** los valores
    caben en el rango de movimientos, y solo dentro de esos tramos —que son
    pocos y cortos— se comprueba que no haya repetidos. Recorrer 4 MiB
    comprobando 101 valores en cada posición sería mil veces más lento sin
    encontrar nada distinto.
    """
    palabras = len(ram) // 2
    valores = struct.unpack_from(f"<{palabras}H", ram, 0)

    salida: list[dict] = []

    def revisar(inicio: int, fin: int) -> None:
        for arranque in range(inicio, fin - TOTAL_MT + 1):
            tramo = valores[arranque:arranque + TOTAL_MT]
            if len(set(tramo)) != TOTAL_MT:
                continue
            salida.append({
                "direccion": f"0x{DS_RAM_BASE + arranque * 2:08X}",
                "movimientos": list(tramo),
            })

    inicio = 0
    for indice in range(palabras + 1):
        if indice < palabras and 1 <= valores[indice] <= MOVIMIENTO_MAXIMO:
            continue
        if indice - inicio >= TOTAL_MT:
            revisar(inicio, indice)
        inicio = indice + 1
    return salida


def main(clave: str = "b2w2") -> None:
    memoria = GEN5_MEMORY[clave]
    print(f"Juego: {memoria.label}")
    lector = B2W2MelonDSReader(memoria)
    party = lector.read_party()
    pid, base = party.process_id, party.allocation_base
    print(f"melonDS PID {pid} - base 0x{base:X}")
    print(f"Equipo: {party.count} miembros (ancla ya demostrada).")
    print()
    print("No hace falta que hagas nada en el juego. Solo no lo cierres.")
    print("Buscando la tabla de MT... esto tarda unos segundos.")

    ram = _leer_ram(pid, base)
    candidatos = _candidatos(ram)

    # En ORDEN DE OBJETO, que es como el juego la guarda: MT01-92, MO01-06 y
    # MT93-95. La primera version de esta herramienta la pedia en orden de
    # numero de MT y por eso la captura del 27-08-2026 dio 92/101 en vez de
    # 101/101: los mismos movimientos, colocados de otra manera.
    referencia = list(reference_move_ids())

    exactos = [c for c in candidatos if c["movimientos"] == referencia]
    for candidato in candidatos:
        coincidencias = sum(
            1 for a, b in zip(candidato["movimientos"], referencia) if a == b
        )
        candidato["coincidencias_con_pkhex"] = coincidencias
        candidato["identica_a_pkhex"] = coincidencias == TOTAL_MT

    print()
    print(f"Tramos con la forma de una tabla de MT: {len(candidatos)}")
    for candidato in candidatos[:12]:
        marca = "  <-- IDENTICA A PKHEX" if candidato["identica_a_pkhex"] else ""
        print(
            f"  {candidato['direccion']}  "
            f"{candidato['coincidencias_con_pkhex']:3}/101 coinciden{marca}"
        )
    if len(candidatos) > 12:
        print(f"  ... y {len(candidatos) - 12} mas (todas en el archivo).")

    esperada = (
        f"0x{memoria.tm_table:08X}" if memoria.tm_table is not None else None
    )
    conocida = next(
        (c for c in candidatos if c["direccion"] == esperada), None,
    ) if esperada else None

    print()
    if esperada is None:
        print(f"{memoria.label} todavia no tiene direccion de MT demostrada.")
    else:
        print(
            f"Direccion ya demostrada ({esperada}): "
            + ("presente" if conocida else "NO APARECE")
        )
        if conocida:
            print(f"  {conocida['coincidencias_con_pkhex']}/101 coinciden con la referencia.")
    print()
    if len(exactos) == 1:
        print(f"DEMOSTRADA: {exactos[0]['direccion']}")
        print("Un unico tramo con la forma correcta Y el contenido correcto.")
    elif not exactos:
        print("Ningun tramo coincide con PKHeX.")
        print("Si esta partida ESTA randomizada, es lo esperable: hara falta")
        print("otra comprobacion. Si NO lo esta, es que la tabla no esta ahi.")
    else:
        print(f"{len(exactos)} tramos identicos: probablemente copias del mismo dato.")
        print("Habra que quedarse con el que el juego use de verdad.")

    payload = {
        "format": "rolerun-b2w2-tm-table-v1",
        "captured_at": datetime.now().astimezone().isoformat(),
        "environment": f"{memoria.label} Espana - melonDS 1.1",
        "metodo": (
            "Se buscan 101 movimientos consecutivos de 16 bits, todos entre 1 y "
            f"{MOVIMIENTO_MAXIMO} y todos distintos. En una partida no randomizada "
            "la tabla buena es ademas identica a la derivada de PKHeX, lo que "
            "demuestra la direccion por dos caminos independientes."
        ),
        "total_mt": TOTAL_MT,
        "referencia_pkhex": referencia,
        "candidatos": candidatos,
        "identicas_a_pkhex": [c["direccion"] for c in exactos],
        "juego": memoria.key,
        "direccion_en_produccion": esperada,
        "direccion_en_produccion_presente": conocida is not None,
        "note": (
            "Diagnostico de solo lectura. Un tramo aqui no pasa a produccion "
            "mientras no sea el unico que cumple forma y contenido."
        ),
    }
    SALIDA = _salida(clave)
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(f"Guardado en: {SALIDA.resolve()}")
    print("Avisame y seguimos.")
    input()


if __name__ == "__main__":
    import sys

    try:
        main(sys.argv[1] if len(sys.argv) > 1 else "b2w2")
    except B2W2LiveError as exc:
        print(f"\nNo se pudo leer melonDS: {_texto(str(exc))}")
        input()
