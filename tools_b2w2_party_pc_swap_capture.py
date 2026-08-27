from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.b2w2_live import B2W2MelonDSReader, PK5_PARTY_SIZE, PK5_STORED_SIZE


OUTPUT = Path("diagnostics/manual/b2w2_party_pc_swap_latest.json")


def _party_blocks(read) -> list[dict[str, object]]:
    result = []
    for pokemon in read.pokemon:
        start = int(pokemon.slot) * PK5_PARTY_SIZE
        block = read.raw[start:start + PK5_PARTY_SIZE]
        result.append({
            "slot": pokemon.slot + 1,
            "species": pokemon.species_id,
            "nickname": pokemon.nickname,
            "pid": pokemon.pid,
            "tid": pokemon.tid,
            "sid": pokemon.sid,
            "stored_hex": block[:PK5_STORED_SIZE].hex(),
            "party_extension_hex": block[PK5_STORED_SIZE:].hex(),
            "level": pokemon.level,
            "status": pokemon.status_condition,
            "stats": list(pokemon.stats),
            "ivs": list(pokemon.ivs),
            "evs": list(pokemon.evs),
            "hp": [pokemon.current_hp, pokemon.max_hp],
        })
    return result


def _pc_blocks(read) -> list[dict[str, object]]:
    result = []
    for pokemon in read.pokemon:
        offset = (pokemon.box - 1) * 0x1000 + (pokemon.slot - 1) * PK5_STORED_SIZE
        result.append({
            "box": pokemon.box,
            "slot": pokemon.slot,
            "species": pokemon.species_id,
            "nickname": pokemon.nickname,
            "pid": pokemon.pid,
            "tid": pokemon.tid,
            "sid": pokemon.sid,
            "stored_hex": read.raw[offset:offset + PK5_STORED_SIZE].hex(),
        })
    return result


def capture(reader: B2W2MelonDSReader) -> dict[str, object]:
    party = reader.read_party()
    pc = reader.read_pc(party)
    return {
        "process_id": party.process_id,
        "allocation_base": party.allocation_base,
        "party": _party_blocks(party),
        "pc": _pc_blocks(pc),
        "pc_empty": pc.empty_slots,
    }


def main() -> None:
    reader = B2W2MelonDSReader()
    print("Captura Equipo↔PC B2/W2 preparada (solo lectura).")
    print("Deja el juego fuera de menús y pulsa INTRO.")
    input()
    before = capture(reader)
    print("Ahora, DESDE EL PC DEL JUEGO, intercambia Lillipup de Caja 1/slot 2 con Tepig del primer slot.")
    print("Sal completamente del PC, espera a ver al personaje y pulsa INTRO.")
    input()
    swapped = capture(reader)
    print("Vuelve al PC DEL JUEGO, deshaz el intercambio para restaurar Tepig al equipo y Lillipup a Caja 1/slot 2.")
    print("Sal otra vez del PC, espera a ver al personaje y pulsa INTRO.")
    input()
    restored = capture(reader)
    payload = {
        "format": "rolerun-b2w2-party-pc-swap-v1",
        "captured_at": datetime.now().astimezone().isoformat(),
        "environment": "Pokémon Negro 2 España · melonDS 1.1",
        "before": before,
        "swapped": swapped,
        "restored": restored,
        "restored_matches_identity": (
            [(p["pid"], p["tid"], p["sid"]) for p in before["party"]]
            == [(p["pid"], p["tid"], p["sid"]) for p in restored["party"]]
        ),
        "note": "Diagnóstico local de solo lectura; no habilita escrituras por sí solo.",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Captura guardada en {OUTPUT}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}")
    input("Pulsa INTRO para cerrar.")
