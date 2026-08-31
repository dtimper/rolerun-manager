"""Captura de solo lectura para el hueco de un slot de party vaciado por RoleRun.

Al mover un Pokémon del equipo al PC desde RoleRun, el escritor
(``ORASLiveWriter._apply_party_resize``) solo pone a cero DOS regiones del
slot de party vaciado: el bloque almacenado (0xE8 bytes) y el espejo de
estadísticas (0x16 bytes en el offset 0x158). Su propio comentario admite que
hay una franja intermedia — offset 0xE8 a 0x158, 112 bytes — y una cola tras
el espejo que nunca se leen ni se escriben: "territorio que nadie ha
demostrado que sea seguro tocar".

Un Quagsire movido hoy al PC dejó un "Huevo" en ese slot, tanto en RoleRun
como en el menú del propio juego. Este script NO escribe nada: captura el
slot completo (0x1E4 bytes, el `ORAS_PARTY_STRIDE` real, no solo los 260 que
RoleRun lee) en tres momentos —

  1. ANTES del movimiento.
  2. justo DESPUÉS de que RoleRun confirme la escritura (detectado solo, por
     el contador de equipo).
  3. DESPUÉS de que abras el menú del propio juego y mires el equipo o el PC
     (aquí no hay forma de detectarlo solo: pulsas Intro cuando lo hayas
     hecho).

Así se ve exactamente qué bytes tocó RoleRun, qué bytes quedaron intactos de
Quagsire en la franja sin tocar, y si algo CAMBIA solo entre el paso 2 y el
paso 3 — que es la prueba de que el propio juego repara ese slot al mirarlo.

Procedimiento:
  1. Abre ORAS en Azahar con el equipo con al menos dos miembros.
  2. Ejecuta: ``python tools_oras_egg_bug_capture.py``.
  3. Cuando el script imprima CAPTURE_READY, mueve UN Pokémon del equipo al
     PC usando RoleRun (arrástralo normalmente).
  4. Cuando el script imprima STEP2_READY, ve al juego y abre el menú de
     equipo o de PC — lo que quieras comprobar — y mira si aparece el huevo.
  5. Vuelve a la terminal y pulsa Intro.
  6. Comparte el archivo que el script guarda en ``diagnostics/manual/``.
"""
from __future__ import annotations

import json
import struct
import time
from datetime import datetime
from pathlib import Path

from app.azahar_rpc import AzaharRPCClient, AzaharRPCError
from app.oras_live import (
    ORAS_PARTY_ADDRESS,
    ORAS_PARTY_COUNT_ADDRESS,
    ORAS_PARTY_STATS_OFFSET,
    ORAS_PARTY_STATS_SIZE,
    ORAS_PARTY_STRIDE,
    ORAS_TITLE_IDS,
    PK6_STORED_SIZE,
    _checksum,
    decrypt_pk6,
)


def _stable(client: AzaharRPCClient, address: int, size: int) -> bytes:
    first = client.read_memory(int(address), int(size))
    second = client.read_memory(int(address), int(size))
    if first != second:
        raise RuntimeError(f"0x{int(address):X}+{int(size)} cambió durante la doble lectura")
    return second


def _stored_checksum_valid(data: bytes) -> bool:
    if len(data) < PK6_STORED_SIZE:
        return False
    sentinel = struct.unpack_from("<H", data, 4)[0]
    checksum_field = struct.unpack_from("<H", data, 6)[0]
    species = struct.unpack_from("<H", data, 8)[0]
    return sentinel == 0 and checksum_field == _checksum(data) and 1 <= species <= 721


def _decode_stored(stored: bytes, extension: bytes) -> dict[str, object]:
    """Igual que ``parse_pk6_boxed``, pero devuelve un resumen legible.

    ``extension`` son los 0x1C bytes REALES que siguen al bloque almacenado
    dentro de la ventana de party (offset 0xE8 a 0x104, el principio de la
    franja sin tocar) — no un relleno de ceros. El descifrado Gen6 procesa
    los 0x104 bytes juntos; rellenar con ceros ahí produce un descifrado
    incorrecto y puede ocultar que el bloque SÍ era un PK6 válido.

    Se guarda SIEMPRE el hex crudo, valide o no: la vez anterior, el caso
    "no valida" se descartó sin guardar los bytes y hubo que releerlos a
    mano en directo. No se repite ese error.
    """
    resultado: dict[str, object] = {
        "empty_zero": not any(stored),
        "stored_hex": stored.hex(),
        "cabecera": {
            "ec": stored[0:4].hex(),
            "centinela": int(struct.unpack_from("<H", stored, 4)[0]),
            "checksum_campo": int(struct.unpack_from("<H", stored, 6)[0]),
        },
    }
    if not any(stored):
        return resultado
    for label, candidate in (
        ("crudo", stored + extension),
        ("descifrado", decrypt_pk6(stored + extension)),
    ):
        if _stored_checksum_valid(candidate):
            species = struct.unpack_from("<H", candidate, 8)[0]
            iv32 = struct.unpack_from("<I", candidate, 0x74)[0]
            resultado.update({
                "valida": True,
                "interpretacion": label,
                "species_id": int(species),
                "is_egg_bit_0x74": bool(iv32 & 0x40000000),
                "pid": int(struct.unpack_from("<I", candidate, 0x18)[0]),
            })
            return resultado
    resultado.update({"valida": False, "interpretacion": "no valida ni en crudo ni descifrado"})
    return resultado


def _party_count(client: AzaharRPCClient) -> int:
    raw = _stable(client, ORAS_PARTY_COUNT_ADDRESS, 4)
    return int(struct.unpack("<I", raw)[0])


def _full_slot(client: AzaharRPCClient, index: int) -> dict[str, object]:
    """Captura el slot COMPLETO: los ``ORAS_PARTY_STRIDE`` bytes reales, no
    solo los 254 que ``ORASLiveReader._read_party`` reconstruye.
    """
    address = ORAS_PARTY_ADDRESS + index * ORAS_PARTY_STRIDE
    raw = _stable(client, address, ORAS_PARTY_STRIDE)
    stored = raw[:PK6_STORED_SIZE]
    gap = raw[PK6_STORED_SIZE:ORAS_PARTY_STATS_OFFSET]
    stats = raw[ORAS_PARTY_STATS_OFFSET:ORAS_PARTY_STATS_OFFSET + ORAS_PARTY_STATS_SIZE]
    tail = raw[ORAS_PARTY_STATS_OFFSET + ORAS_PARTY_STATS_SIZE:]
    return {
        "slot": index + 1,
        "address": f"0x{address:08X}",
        "stored": _decode_stored(stored, gap[:0x1C]),
        # Esta es la franja que ningún código validado toca. Si algo cambia
        # aquí solo, sin que RoleRun lo haya escrito, es el juego reparando
        # el slot por su cuenta.
        "gap_0xE8_a_0x158_hex": gap.hex(),
        "gap_es_cero": not any(gap),
        "stats_mirror_hex": stats.hex(),
        "stats_mirror_es_cero": not any(stats),
        "tail_hex": tail.hex(),
        "tail_es_cero": not any(tail),
        "raw_sha256_no_incluido": None,  # el hex ya es la evidencia completa
    }


def _party_snapshot(client: AzaharRPCClient) -> dict[str, object]:
    return {
        "timestamp": time.time(),
        "party_count": _party_count(client),
        "slots": [_full_slot(client, index) for index in range(6)],
    }


def _party_fingerprint(snapshot: dict[str, object]) -> tuple[object, ...]:
    slots = snapshot["slots"]
    assert isinstance(slots, list)
    return (
        int(snapshot["party_count"]),
        tuple(
            (
                bool(row["stored"].get("empty_zero", False)),
                str(row["stored"].get("species_id", "")),
                row["gap_es_cero"],
                row["stats_mirror_es_cero"],
            )
            for row in slots
        ),
    )


def _diff_slot(before: dict[str, object], after: dict[str, object]) -> dict[str, object] | None:
    """Compara un slot entre dos capturas y devuelve solo lo que cambió."""
    changes: dict[str, object] = {}
    if before["stored"] != after["stored"]:
        changes["stored"] = {"antes": before["stored"], "despues": after["stored"]}
    if before["gap_0xE8_a_0x158_hex"] != after["gap_0xE8_a_0x158_hex"]:
        changes["gap_0xE8_a_0x158"] = {
            "antes": before["gap_0xE8_a_0x158_hex"],
            "despues": after["gap_0xE8_a_0x158_hex"],
        }
    if before["stats_mirror_hex"] != after["stats_mirror_hex"]:
        changes["stats_mirror"] = {
            "antes": before["stats_mirror_hex"],
            "despues": after["stats_mirror_hex"],
        }
    if before["tail_hex"] != after["tail_hex"]:
        changes["tail"] = {"antes": before["tail_hex"], "despues": after["tail_hex"]}
    if not changes:
        return None
    return {"slot": before["slot"], "address": before["address"], **changes}


def _diff_snapshots(before: dict[str, object], after: dict[str, object]) -> list[dict[str, object]]:
    result = []
    for before_slot, after_slot in zip(before["slots"], after["slots"]):
        diff = _diff_slot(before_slot, after_slot)
        if diff is not None:
            result.append(diff)
    return result


def _find_process(client: AzaharRPCClient):
    for process in client.process_list():
        if int(process.title_id) in ORAS_TITLE_IDS:
            return process
    raise AzaharRPCError(
        "No se encontró ningún proceso ORAS en la lista de Azahar. "
        "Asegúrate de haber entrado en la partida."
    )


def capture(*, timeout_seconds: float) -> Path:
    output = Path(__file__).resolve().parent / "diagnostics" / "manual" / (
        "oras_egg_bug_AUTO_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)

    with AzaharRPCClient() as client:
        process = _find_process(client)
        client.set_process(process.process_id)

        before = _party_snapshot(client)
        before_fp = _party_fingerprint(before)
        print(
            f"CAPTURE_READY equipo={before['party_count']} proceso={process.name}",
            flush=True,
        )
        print("Mueve ahora UN Pokémon del equipo al PC desde RoleRun...", flush=True)

        deadline = time.monotonic() + max(30.0, float(timeout_seconds))
        after_write: dict[str, object] | None = None
        while time.monotonic() < deadline:
            current = _party_snapshot(client)
            if _party_fingerprint(current) != before_fp:
                time.sleep(0.35)
                confirmed = _party_snapshot(client)
                if _party_fingerprint(current) == _party_fingerprint(confirmed):
                    after_write = confirmed
                    break
            time.sleep(0.15)
        if after_write is None:
            raise TimeoutError(
                f"No se observó un cambio del equipo ({before['party_count']} "
                "miembros) antes del timeout."
            )

        print("STEP2_READY — escritura de RoleRun confirmada.", flush=True)
        print(
            "Ahora ve al JUEGO y abre el menú de equipo o de PC (lo que quieras "
            "comprobar). Cuando ya lo hayas mirado, vuelve aquí y pulsa Intro.",
            flush=True,
        )
        input()

        after_viewed = _party_snapshot(client)

        payload = {
            "purpose": "ORAS egg bug — franja sin tocar de un slot de party vaciado",
            "read_only": True,
            "process": {
                "pid": int(process.process_id),
                "name": str(process.name),
                "title_id": f"{int(process.title_id):016X}",
            },
            "before": before,
            "after_roleRun_write": after_write,
            "after_game_viewed": after_viewed,
            "diff_write_vs_before": _diff_snapshots(before, after_write),
            "diff_viewed_vs_write": _diff_snapshots(after_write, after_viewed),
        }
        output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
        )

    print(f"CAPTURE_COMPLETE {output}", flush=True)
    escritura = payload["diff_write_vs_before"]
    visto = payload["diff_viewed_vs_write"]
    print(f"Slots que cambió la escritura de RoleRun: {len(escritura)}", flush=True)
    for entry in escritura:
        print(f"  slot {entry['slot']} ({entry['address']}): {sorted(k for k in entry if k not in ('slot','address'))}", flush=True)
    print(f"Slots que cambiaron SOLOS entre la escritura y mirar el juego: {len(visto)}", flush=True)
    for entry in visto:
        print(f"  slot {entry['slot']} ({entry['address']}): {sorted(k for k in entry if k not in ('slot','address'))}", flush=True)
    if visto:
        print(
            "Esto es la prueba: el juego cambió algo por su cuenta después de la "
            "escritura, sin que RoleRun tocara nada más.",
            flush=True,
        )
    return output


if __name__ == "__main__":
    capture(timeout_seconds=180.0)
