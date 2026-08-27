from __future__ import annotations

"""Ensena lo que RoleRun va a leer de HeartGold, para compararlo con la pantalla.

Todo lo que sale de aqui viene de UNA sola direccion medida -la del equipo- y de
los desplazamientos que el propio guardado declara. Si el equipo, el dinero, las
medallas y la caja 1 coinciden con lo que se ve en el juego, la regla del espejo
esta confirmada en cuarta generacion.

No escribe un solo byte en la partida, ni en la RAM, ni activa ninguna
capacidad. Solo lee.
"""

import ctypes
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.b2w2_live import DS_RAM_BASE, _KERNEL32  # noqa: E402
from app.gen4_memory import GEN4_MEMORY, SAVE_MONEY_SIZE  # noqa: E402
from app.pk4 import (  # noqa: E402
    PK4_PARTY_SIZE,
    PK4_STORED_SIZE,
    Pk4Error,
    parse_pk4_boxed,
    parse_pk4_party,
)
from tools_hgss_anchor_capture import (  # noqa: E402
    MBI,
    _abrir,
    _allocations,
    _leer,
    _procesos_melonds,
    TAMANO_RAM_DS,
)

CAJAS = 18
HUECOS = 30
SALIDA = Path("diagnostics/manual/hgss_read_check_latest.json")


def _base_del_juego(handle, memoria) -> int | None:
    """Que reserva contiene la RAM del DS, comprobandolo con el contador."""
    for base, tamano in _allocations(handle):
        if not TAMANO_RAM_DS <= tamano <= 0x40000000:
            continue
        contador = _leer(handle, base + (memoria.party_count - DS_RAM_BASE), 1)
        if contador is None or not 1 <= contador[0] <= 6:
            continue
        crudo = _leer(handle, base + (memoria.party_data - DS_RAM_BASE), PK4_PARTY_SIZE)
        if crudo is None:
            continue
        try:
            primero = parse_pk4_party(crudo, 0)
        except Pk4Error:
            continue
        if 1 <= primero.species_id <= 493:
            return base
    return None


def main() -> None:
    memoria = GEN4_MEMORY["hgss"]
    procesos = _procesos_melonds()
    if not procesos:
        print("melonDS no esta abierto. Abrelo con HeartGold cargado y repite.")
        input()
        return

    for pid_proceso, _nombre in procesos:
        handle = _abrir(pid_proceso)
        try:
            base = _base_del_juego(handle, memoria)
            if base is None:
                print(f"  PID {pid_proceso}: no se reconocio la RAM de HeartGold.")
                continue

            def leer(invitado: int, tamano: int) -> bytes:
                crudo = _leer(handle, base + (invitado - DS_RAM_BASE), tamano)
                if crudo is None:
                    raise OSError(f"Lectura incompleta en 0x{invitado:08X}.")
                return crudo

            cuantos = leer(memoria.party_count, 1)[0]
            dinero = int.from_bytes(leer(memoria.money, SAVE_MONEY_SIZE), "little")
            medallas_byte = leer(memoria.badges, 1)[0]
            medallas = bin(medallas_byte).count("1")

            print("=" * 58)
            print(f"  melonDS PID {pid_proceso} - {memoria.label}")
            print("=" * 58)
            print()
            print(f"  DINERO:   {dinero}")
            print(f"  MEDALLAS: {medallas}   (byte 0b{medallas_byte:08b})")
            print()
            print(f"  EQUIPO ({cuantos}):")
            equipo = []
            for indice in range(cuantos):
                crudo = leer(memoria.party_data + indice * PK4_PARTY_SIZE, PK4_PARTY_SIZE)
                try:
                    p = parse_pk4_party(crudo, indice)
                except Pk4Error as exc:
                    print(f"     {indice + 1}. ilegible ({exc})")
                    continue
                estado = "DEBILITADO" if p.current_hp == 0 else ""
                print(f"     {indice + 1}. {p.nickname:12} Nv.{p.level:3}  "
                      f"PS {p.current_hp:3}/{p.max_hp:3}  {estado}")
                equipo.append({
                    "slot": indice, "especie": p.species_id, "mote": p.nickname,
                    "nivel": p.level, "ps": f"{p.current_hp}/{p.max_hp}",
                    "movimientos": list(p.move_ids),
                    "iv": list(p.ivs), "ev": list(p.evs),
                    "naturaleza": p.nature_id, "habilidad": p.ability_id,
                })

            print()
            print("  PC (solo lo que tiene algo):")
            cajas = []
            for caja in range(CAJAS):
                crudo = leer(
                    memoria.pc + caja * HUECOS * PK4_STORED_SIZE,
                    HUECOS * PK4_STORED_SIZE,
                )
                dentro = []
                for hueco in range(HUECOS):
                    trozo = crudo[hueco * PK4_STORED_SIZE:(hueco + 1) * PK4_STORED_SIZE]
                    try:
                        p = parse_pk4_boxed(trozo, hueco)
                    except Pk4Error:
                        continue
                    if p is None or not 1 <= p.species_id <= 493:
                        continue
                    dentro.append({
                        "hueco": hueco + 1, "especie": p.species_id, "mote": p.nickname,
                    })
                if dentro:
                    motes = ", ".join(f"{d['mote']}" for d in dentro)
                    print(f"     Caja {caja + 1}: {len(dentro)} -> {motes}")
                    cajas.append({"caja": caja + 1, "pokemon": dentro})
            if not cajas:
                print("     (todas vacias)")

            payload = {
                "format": "rolerun-hgss-read-check-v1",
                "captured_at": datetime.now().astimezone().isoformat(),
                "environment": f"{memoria.label} - melonDS",
                "ancla": f"0x{memoria.party_data:08X}",
                "derivadas": {
                    "inicio_bloque": f"0x{memoria.block_base:08X}",
                    "contador": f"0x{memoria.party_count:08X}",
                    "dinero": f"0x{memoria.money:08X}",
                    "medallas": f"0x{memoria.badges:08X}",
                    "pc": f"0x{memoria.pc:08X}",
                },
                "dinero": dinero,
                "medallas": medallas,
                "medallas_byte": medallas_byte,
                "equipo": equipo,
                "cajas": cajas,
                "note": "Diagnostico de solo lectura.",
            }
            SALIDA.parent.mkdir(parents=True, exist_ok=True)
            SALIDA.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
            )
            print()
            print(f"Guardado en: {SALIDA.resolve()}")
            print()
            print("Comparalo con lo que ves en el juego y avisame.")
            input()
            return
        finally:
            _KERNEL32.CloseHandle(handle)

    print("No se pudo leer HeartGold en ningun melonDS abierto.")
    input()


if __name__ == "__main__":
    try:
        main()
    except OSError as exc:
        print(f"\nNo se pudo leer melonDS: {exc}")
        input()
