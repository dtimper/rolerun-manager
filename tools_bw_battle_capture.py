from __future__ import annotations

"""Localización del carril de combate de Pokémon Blanco/Negro.

QUÉ ES ESTE CARRIL Y POR QUÉ NO SALE DEL CÁLCULO

Durante un combate, quinta generación **no actualiza el bloque del equipo**: lo
demostró la traza de Negro 2 del 27-08-2026, donde la ficha del equipo seguía
diciendo 16/16 con el Pokémon ya a 3 PS y solo se puso al día al terminar. Los
PS que se ven en pantalla salen de otra copia, que es estado de ejecución y no
vive en el bloque del guardado. Por eso no se deriva del ancla y hay que
medirla.

CÓMO SE LOCALIZA SIN INVENTAR NADA

En Negro 2 la fila son siete valores de 16 bits: especie, PS máximos, PS
actuales, dos auxiliares, habilidad y nivel. Eso permite una firma de **cuatro
campos** contra un miembro del equipo que RoleRun ya sabe leer: si en una
posición coinciden a la vez la especie, los PS máximos, la habilidad y el nivel
del Pokémon que está luchando, no es casualidad.

Se buscan dos: la copia de **presentación**, que es la que marca la barra
visible, y la **lógica**, que se adelanta a la animación. Se distinguen por los
PS: la presentación coincide con lo que se ve en pantalla.

No escribe un solo byte en la partida ni activa ninguna capacidad.
"""

import ctypes
import json
import struct
from datetime import datetime
from pathlib import Path

from app.b2w2_live import (
    BATTLE_READ_SIZE,
    BATTLE_STATUS_OFFSET,
    DS_RAM_BASE,
    B2W2LiveError,
    B2W2MelonDSReader,
    _KERNEL32,
)
from app.gen5_memory import GEN5_MEMORY

TAMANO_RAM = 0x00400000
SALIDA = Path("diagnostics/manual/bw_battle_latest.json")


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


def _filas(ram: bytes, equipo) -> list[dict]:
    """Posiciones donde cuatro campos coinciden con un miembro del equipo."""
    porFirma = {
        (int(p.species_id), int(p.max_hp), int(p.ability_id), int(p.level)): p
        for p in equipo
    }
    salida: list[dict] = []
    palabras = len(ram) // 2
    valores = struct.unpack_from(f"<{palabras}H", ram, 0)
    for indice in range(palabras - 7):
        firma = (
            valores[indice], valores[indice + 1],
            valores[indice + 5], valores[indice + 6],
        )
        miembro = porFirma.get(firma)
        if miembro is None:
            continue
        offset = indice * 2
        ps = valores[indice + 2]
        if ps > miembro.max_hp:
            continue
        salida.append({
            "direccion": f"0x{DS_RAM_BASE + offset:08X}",
            "offset": offset,
            "mote": miembro.nickname,
            "especie": int(miembro.species_id),
            "nivel": int(miembro.level),
            "ps": f"{ps}/{miembro.max_hp}",
            "ps_valor": int(ps),
            "estado": ram[offset + BATTLE_STATUS_OFFSET]
            if offset + BATTLE_READ_SIZE <= len(ram) else None,
        })
    return salida


def _numero(mensaje: str) -> int | None:
    respuesta = input(mensaje).strip()
    if not respuesta:
        return None
    try:
        return max(0, int(respuesta))
    except ValueError:
        print("  No era un numero.")
        return None


def main() -> None:
    memoria = GEN5_MEMORY["bw"]
    lector = B2W2MelonDSReader(memoria)
    party = lector.read_party()
    pid, base = party.process_id, party.allocation_base
    print(f"melonDS PID {pid} - {memoria.label}")
    print(f"Equipo: {party.count} miembros")
    for p in party.pokemon:
        print(f"   {p.nickname:12} Nv.{p.level:3}  PS {p.current_hp}/{p.max_hp}")
    print()
    print("=== ENTRA EN UN COMBATE ===")
    print("Metete en una pelea y deja a tu Pokemon con los PS a la vista,")
    print("mejor si ha recibido algun golpe: cuanto mas raro sea el numero,")
    print("mejor se distinguen las dos copias.")
    print()
    input("Cuando estes en combate y veas la barra de PS, pulsa INTRO...")
    print()
    visibles = _numero("  Cuantos PS le quedan AHORA en pantalla? ")

    print()
    print("Leyendo... no toques el juego.")
    ram = _leer_ram(pid, base)
    candidatos = _filas(ram, party.pokemon)

    # La party sigue siendo la party: se descartan las posiciones que caen
    # dentro del bloque del equipo, que no son el carril de combate.
    inicio_party = memoria.party_data - DS_RAM_BASE
    fin_party = inicio_party + party.count * 220
    fuera = [c for c in candidatos if not inicio_party <= c["offset"] < fin_party]

    coinciden = [c for c in fuera if visibles is not None and c["ps_valor"] == visibles]

    print()
    print(f"Filas con la firma del equipo: {len(candidatos)} "
          f"({len(fuera)} fuera del bloque de equipo)")
    for c in fuera[:16]:
        marca = "  <-- coincide con la pantalla" if c in coinciden else ""
        print(f"  {c['direccion']}  {c['mote']:11} Nv.{c['nivel']:3} "
              f"PS {c['ps']:8} estado={c['estado']}{marca}")
    print()
    if len(fuera) >= 2:
        distancias = sorted({
            abs(a["offset"] - b["offset"])
            for a in fuera for b in fuera if a is not b
        })
        print(f"Distancias entre filas: {[hex(d) for d in distancias[:6]]}")
        print("(en Negro 2 las dos copias estan a 0x448 una de otra)")

    payload = {
        "format": "rolerun-bw-battle-v1",
        "captured_at": datetime.now().astimezone().isoformat(),
        "environment": f"{memoria.label} Espana - melonDS 1.1",
        "metodo": (
            "Firma de cuatro campos contra un miembro del equipo -especie, PS "
            "maximos, habilidad y nivel- sobre filas de siete valores de 16 "
            "bits. Se descartan las posiciones que caen dentro del bloque de "
            "equipo, que no son el carril de combate."
        ),
        "ps_en_pantalla": visibles,
        "equipo": [
            {
                "mote": p.nickname, "especie": int(p.species_id),
                "nivel": int(p.level), "ps": f"{p.current_hp}/{p.max_hp}",
                "habilidad": int(p.ability_id),
            }
            for p in party.pokemon
        ],
        "candidatos": fuera,
        "coinciden_con_pantalla": [c["direccion"] for c in coinciden],
        "note": (
            "Diagnostico de solo lectura. Una fila aqui no pasa a produccion "
            "mientras no se distingan presentacion y logica con los PS."
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
