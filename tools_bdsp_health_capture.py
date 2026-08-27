from __future__ import annotations

import argparse
import json
import struct
import time
from datetime import datetime
from pathlib import Path

from app.bdsp_live import (
    BDSP_SP_130_BATTLEPROC_TYPEINFO_OFFSET,
    BDSP_SP_130_HOST_PROFILE,
    BDSPBattleReader,
    BDSPPartyReader,
)
from app.ryujinx_host_memory import (
    RYUJINX_HOST_ADDRESS_SPACE_SIZE,
    RyujinxHostMappedClient,
)


_BATTLE_POKECON_CANDIDATE = (
    BDSP_SP_130_BATTLEPROC_TYPEINFO_OFFSET,
    0x58,  # BattleProc TypeInfo -> SingletonMonoBehaviour<BattleProc> parent
    0xB8,  # parent -> static fields
    0x0,   # static fields -> _instance
    0x20,  # BattleProc -> MainModule
    0x110, # MainModule -> client BattleEnv
    0x10,  # BattleEnv -> POKECON
    0x0,
)


def _error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def _stable(client: RyujinxHostMappedClient, address: int, size: int) -> bytes:
    first = client.read_memory(int(address), int(size))
    second = client.read_memory(int(address), int(size))
    if first != second:
        raise RuntimeError("la estructura candidata cambió durante la doble lectura")
    return first


def _valid_pointer(value: int) -> bool:
    return 0x1000 <= int(value) < RYUJINX_HOST_ADDRESS_SPACE_SIZE


def _active_candidate(client: RyujinxHostMappedClient) -> dict[str, object]:
    """Observa POKECON.m_activePokeParam sin convertirlo en lógica de producción."""

    first = client.resolve_main_pointer(_BATTLE_POKECON_CANDIDATE)
    second = client.resolve_main_pointer(_BATTLE_POKECON_CANDIDATE)
    if first != second or not _valid_pointer(first):
        raise RuntimeError("la raíz candidata POKECON no fue estable")

    arrays = _stable(client, first + 0x18, 24)
    party_array, active_array, stored_array = struct.unpack("<3Q", arrays)
    if not all(_valid_pointer(value) for value in (party_array, active_array, stored_array)):
        raise RuntimeError("POKECON no contiene los tres arrays esperados")

    party_length = int(struct.unpack("<Q", _stable(client, party_array + 0x18, 8))[0])
    active_length = int(struct.unpack("<Q", _stable(client, active_array + 0x18, 8))[0])
    stored_length = int(struct.unpack("<Q", _stable(client, stored_array + 0x18, 8))[0])
    if (party_length, active_length, stored_length) != (5, 30, 30):
        raise RuntimeError(
            "POKECON declaró longitudes inesperadas "
            f"{party_length}/{active_length}/{stored_length}"
        )

    party_objects = struct.unpack("<5Q", _stable(client, party_array + 0x20, 40))
    player_party = int(party_objects[0])
    if not _valid_pointer(player_party):
        raise RuntimeError("POKECON no contiene la BTL_PARTY del jugador")
    party_header = _stable(client, player_party + 0x10, 9)
    member_array, member_count = struct.unpack("<QB", party_header)
    if not _valid_pointer(member_array) or not 1 <= int(member_count) <= 6:
        raise RuntimeError("la BTL_PARTY candidata no contiene miembros coherentes")
    member_objects = struct.unpack(
        "<6Q", _stable(client, int(member_array) + 0x20, 48),
    )[:int(member_count)]

    active_objects = struct.unpack("<30Q", _stable(client, active_array + 0x20, 240))
    stored_objects = struct.unpack("<30Q", _stable(client, stored_array + 0x20, 240))
    member_to_index = {int(pointer): index for index, pointer in enumerate(member_objects)}
    return {
        "candidate_only": True,
        "active_non_null_poke_ids": [
            index for index, pointer in enumerate(active_objects) if int(pointer) != 0
        ],
        "active_player_party_indices": [
            member_to_index[int(pointer)]
            for pointer in active_objects
            if int(pointer) in member_to_index
        ],
        "stored_non_null_poke_ids": [
            index for index, pointer in enumerate(stored_objects) if int(pointer) != 0
        ],
        "stored_player_party_indices": [
            member_to_index[int(pointer)]
            for pointer in stored_objects
            if int(pointer) in member_to_index
        ],
    }


def _party_payload(reader: BDSPPartyReader) -> list[dict[str, object]]:
    return [
        {
            "slot": item.slot,
            "species": item.species_id,
            "hp": item.current_hp,
            "max_hp": item.max_hp,
            "level": item.level,
            "moves": list(item.move_ids),
            "pp": list(item.move_pp),
        }
        for item in reader.read().pokemon
    ]


def _battle_payload(reader: BDSPBattleReader) -> list[dict[str, int]] | None:
    result = reader.read()
    if result is None:
        return None
    return [
        {
            "row": item.row,
            "party_index": item.party_index,
            "species": item.species_id,
            "hp": item.current_hp,
            "max_hp": item.max_hp,
            "level": item.level,
        }
        for item in result.pokemon
    ]


def _write(handle, payload: dict[str, object]) -> None:
    handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    handle.flush()


def capture(*, timeout_seconds: float, post_battle_absent_samples: int) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = Path(__file__).resolve().parent / "diagnostics" / "manual" / (
        f"bdsp_sp130_ko_switch_AUTO_{stamp}.jsonl"
    )
    output.parent.mkdir(parents=True, exist_ok=True)

    started_at = time.perf_counter()
    battle_seen = False
    absent_samples = 0
    sequence = 0
    next_wait_sample = 0.0

    with RyujinxHostMappedClient(BDSP_SP_130_HOST_PROFILE) as client, output.open(
        "x", encoding="utf-8", newline="\n",
    ) as handle:
        _write(handle, {
            "event": "start",
            "title_id": f"{BDSP_SP_130_HOST_PROFILE.title_id:016X}",
            "revision": BDSP_SP_130_HOST_PROFILE.revision,
            "gdb_stub": False,
            "access": "read-only",
            "writes": 0,
        })
        print(f"CAPTURE_READY {output}", flush=True)

        party_reader = BDSPPartyReader(client)
        battle_reader = BDSPBattleReader(client)
        while time.perf_counter() - started_at < float(timeout_seconds):
            tick_started = time.perf_counter()
            elapsed_ms = int((tick_started - started_at) * 1000)
            payload: dict[str, object] = {
                "event": "tick",
                "sequence": sequence,
                "elapsed_ms": elapsed_ms,
            }
            sequence += 1

            try:
                payload["party"] = _party_payload(party_reader)
            except Exception as exc:
                payload["party_error"] = _error(exc)

            battle_error = False
            try:
                battle = _battle_payload(battle_reader)
                payload["battle"] = battle
                if battle is not None:
                    if not battle_seen:
                        print("CAPTURE_BATTLE_SEEN", flush=True)
                    battle_seen = True
                    absent_samples = 0
                    try:
                        payload["active_candidate"] = _active_candidate(client)
                    except Exception as exc:
                        payload["active_candidate_error"] = _error(exc)
                elif battle_seen:
                    absent_samples += 1
            except Exception as exc:
                battle_error = True
                payload["battle_error"] = _error(exc)

            now = time.perf_counter()
            if battle_seen or now >= next_wait_sample:
                _write(handle, payload)
                next_wait_sample = now + 1.0

            if battle_seen and not battle_error and absent_samples >= int(post_battle_absent_samples):
                _write(handle, {
                    "event": "end",
                    "reason": "stable-battle-absence",
                    "elapsed_ms": int((time.perf_counter() - started_at) * 1000),
                    "samples": sequence,
                })
                print(f"CAPTURE_COMPLETE {output}", flush=True)
                return output

            delay = 0.1 - (time.perf_counter() - tick_started)
            if delay > 0:
                time.sleep(delay)

        reason = "battle-never-seen" if not battle_seen else "battle-exit-not-observed"
        _write(handle, {
            "event": "end",
            "reason": reason,
            "elapsed_ms": int((time.perf_counter() - started_at) * 1000),
            "samples": sequence,
        })
    raise TimeoutError(f"La captura agotó el tiempo: {reason}.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Captura read-only de party, batalla y candidato activo BDSP SP 1.3.0.",
    )
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--post-battle-absent-samples", type=int, default=30)
    args = parser.parse_args()
    capture(
        timeout_seconds=max(30.0, args.timeout),
        post_battle_absent_samples=max(5, args.post_battle_absent_samples),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
