from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.b2w2_live import B2W2MelonDSReader, PK5_PARTY_SIZE, PK5_STORED_SIZE


OUTPUT = Path("diagnostics/manual/b2w2_party_resize_latest.json")


def capture(reader: B2W2MelonDSReader) -> dict[str, object]:
    party = reader.read_party()
    pc = reader.read_pc(party)
    return {
        "count": party.count,
        "party_raw_hex": party.raw.hex(),
        "party": [
            {
                "slot": p.slot + 1, "species": p.species_id, "nickname": p.nickname,
                "pid": p.pid, "tid": p.tid, "sid": p.sid,
                "stored_hex": party.raw[
                    p.slot * PK5_PARTY_SIZE:p.slot * PK5_PARTY_SIZE + PK5_STORED_SIZE
                ].hex(),
                "extension_hex": party.raw[
                    p.slot * PK5_PARTY_SIZE + PK5_STORED_SIZE:(p.slot + 1) * PK5_PARTY_SIZE
                ].hex(),
            }
            for p in party.pokemon
        ],
        "pc_empty": pc.empty_slots,
        "pc": [
            {
                "box": p.box, "slot": p.slot, "species": p.species_id,
                "nickname": p.nickname, "pid": p.pid, "tid": p.tid, "sid": p.sid,
            }
            for p in pc.pokemon
        ],
    }


def main() -> None:
    reader = B2W2MelonDSReader()
    print("Captura de tamaño/compactación B2/W2 preparada (solo lectura).")
    print("Deja al personaje fuera de menús y pulsa INTRO.")
    input()
    before = capture(reader)
    if before["count"] != 6:
        raise RuntimeError("La captura exige empezar con seis miembros.")
    print("DESDE EL PC DEL JUEGO, deposita el Pokémon del TERCER puesto en Caja 1/slot 4.")
    print("Sal completamente del PC, espera a ver al personaje y pulsa INTRO.")
    input()
    deposited = capture(reader)
    print("Vuelve al PC DEL JUEGO y retira ese mismo Pokémon de Caja 1/slot 4.")
    print("Sal completamente del PC, espera a ver al personaje y pulsa INTRO.")
    input()
    withdrawn = capture(reader)
    payload = {
        "format": "rolerun-b2w2-party-resize-v1",
        "captured_at": datetime.now().astimezone().isoformat(),
        "environment": "Pokémon Negro 2 España · melonDS 1.1",
        "before": before,
        "deposited": deposited,
        "withdrawn": withdrawn,
        "identity_sets_match": sorted(p["pid"] for p in before["party"])
        == sorted(p["pid"] for p in withdrawn["party"]),
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
