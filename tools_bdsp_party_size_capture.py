from __future__ import annotations

import argparse
import hashlib
import json
import struct
import time
from datetime import datetime
from pathlib import Path

from app.bdsp_live import (
    BDSP_BOX_COUNT,
    BDSP_BOX_SLOT_COUNT,
    BDSP_SP_130_BOX_POINTER,
    BDSP_SP_130_HOST_PROFILE,
    BDSP_SP_130_PARTY_POINTER,
    PB8_PARTY_SIZE,
    PB8_STORED_SIZE,
    decrypt_pb8,
)
from app.ryujinx_host_memory import (
    RYUJINX_HOST_ADDRESS_SPACE_SIZE,
    RyujinxHostMappedClient,
)


def _stable(client: RyujinxHostMappedClient, address: int, size: int) -> bytes:
    first = client.read_memory(int(address), int(size))
    second = client.read_memory(int(address), int(size))
    if first != second:
        raise RuntimeError(f"0x{int(address):X}+{int(size)} cambió durante la doble lectura")
    return second


def _valid_pointer(value: int) -> bool:
    return 0x1000 <= int(value) < RYUJINX_HOST_ADDRESS_SPACE_SIZE


def _identity_from_plain(plain: bytes) -> list[int]:
    return [
        int(struct.unpack_from("<H", plain, 8)[0]),
        int(struct.unpack_from("<I", plain, 0x1C)[0]),
        int(struct.unpack_from("<H", plain, 0x0C)[0]),
        int(struct.unpack_from("<H", plain, 0x0E)[0]),
    ]


def _payload(raw: bytes) -> dict[str, object]:
    plain = decrypt_pb8(raw)
    return {
        "identity": _identity_from_plain(plain),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "encrypted_hex": raw.hex(),
        "plain_hex": plain.hex(),
    }


def _party(client: RyujinxHostMappedClient) -> dict[str, object]:
    first_root = client.resolve_main_pointer(BDSP_SP_130_PARTY_POINTER)
    second_root = client.resolve_main_pointer(BDSP_SP_130_PARTY_POINTER)
    if first_root != second_root or not _valid_pointer(first_root):
        raise RuntimeError("La raíz de PokeParty no fue estable")
    header = _stable(client, first_root + 0x10, 16)
    member_array, member_count = struct.unpack_from("<QI", header, 0)
    if not _valid_pointer(member_array) or not 1 <= int(member_count) <= 6:
        raise RuntimeError("La cabecera de PokeParty no es coherente")
    length = int(struct.unpack("<Q", _stable(client, member_array + 0x18, 8))[0])
    if length != 6:
        raise RuntimeError(f"El array de PokeParty declara longitud {length}")
    pointers = struct.unpack("<6Q", _stable(client, member_array + 0x20, 48))
    slots: list[dict[str, object]] = []
    for index, pointer in enumerate(pointers, start=1):
        row: dict[str, object] = {
            "slot": index,
            "active": index <= int(member_count),
            "pokemon_param": int(pointer),
        }
        try:
            if not _valid_pointer(pointer):
                raise RuntimeError("puntero PokemonParam no direccionable")
            core, calc, accessor = struct.unpack(
                "<3Q", _stable(client, int(pointer) + 0x10, 24),
            )
            if not all(_valid_pointer(value) for value in (core, calc, accessor)):
                raise RuntimeError("punteros internos de PokemonParam no direccionables")
            core_length = int(struct.unpack(
                "<Q", _stable(client, core + 0x18, 8),
            )[0])
            calc_length = int(struct.unpack(
                "<Q", _stable(client, calc + 0x18, 8),
            )[0])
            if (core_length, calc_length) != (
                PB8_STORED_SIZE, PB8_PARTY_SIZE - PB8_STORED_SIZE,
            ):
                raise RuntimeError(
                    f"PokemonParam declara {core_length}+{calc_length} bytes",
                )
            raw = _stable(client, core + 0x20, PB8_STORED_SIZE) + _stable(
                client, calc + 0x20, PB8_PARTY_SIZE - PB8_STORED_SIZE,
            )
            row.update({
                "core_data": int(core) + 0x20,
                "calc_data": int(calc) + 0x20,
                **_payload(raw),
            })
        except Exception as exc:
            row["diagnostic_error"] = f"{type(exc).__name__}: {exc}"
        slots.append(row)
    return {
        "timestamp": time.time(),
        "party_object": int(first_root),
        "member_array": int(member_array),
        "member_count_address": int(first_root) + 0x18,
        "member_count": int(member_count),
        "slots": slots,
    }


def _party_fingerprint(party: dict[str, object]) -> tuple[object, ...]:
    slots = party.get("slots", [])
    assert isinstance(slots, list)
    return (
        int(party["party_object"]),
        int(party["member_array"]),
        int(party["member_count"]),
        tuple(
            (
                int(row.get("pokemon_param", 0)),
                str(row.get("sha256", "")),
                str(row.get("diagnostic_error", "")),
            )
            for row in slots
            if isinstance(row, dict)
        ),
    )


def _boxes(client: RyujinxHostMappedClient) -> dict[tuple[int, int], dict[str, object]]:
    first_root = client.resolve_main_pointer(BDSP_SP_130_BOX_POINTER)
    second_root = client.resolve_main_pointer(BDSP_SP_130_BOX_POINTER)
    if first_root != second_root or not _valid_pointer(first_root):
        raise RuntimeError("La raíz de cajas no fue estable")
    box_pointers = struct.unpack(
        f"<{BDSP_BOX_COUNT}Q",
        _stable(client, first_root, BDSP_BOX_COUNT * 8),
    )
    result: dict[tuple[int, int], dict[str, object]] = {}
    for box, box_pointer in enumerate(box_pointers, start=1):
        if not _valid_pointer(box_pointer):
            raise RuntimeError(f"La caja {box} tiene un puntero inválido")
        slot_pointers = struct.unpack(
            f"<{BDSP_BOX_SLOT_COUNT}Q",
            _stable(client, int(box_pointer) + 0x20, BDSP_BOX_SLOT_COUNT * 8),
        )
        for slot, slot_pointer in enumerate(slot_pointers, start=1):
            if not _valid_pointer(slot_pointer):
                raise RuntimeError(f"Caja {box}, slot {slot}: puntero inválido")
            length = int(struct.unpack(
                "<Q", _stable(client, int(slot_pointer) + 0x18, 8),
            )[0])
            if length != PB8_PARTY_SIZE:
                raise RuntimeError(
                    f"Caja {box}, slot {slot}: longitud {length} != {PB8_PARTY_SIZE}",
                )
            raw = _stable(client, int(slot_pointer) + 0x20, PB8_PARTY_SIZE)
            result[(box, slot)] = {
                "box": box,
                "slot": slot,
                "data": int(slot_pointer) + 0x20,
                **_payload(raw),
            }
    return result


def _changed_boxes(
    before: dict[tuple[int, int], dict[str, object]],
    after: dict[tuple[int, int], dict[str, object]],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for position in sorted(set(before) | set(after)):
        old = before.get(position)
        new = after.get(position)
        if old is None or new is None or old.get("sha256") != new.get("sha256"):
            result.append({
                "box": position[0],
                "slot": position[1],
                "before": old,
                "after": new,
            })
    return result


def capture(*, timeout_seconds: float) -> Path:
    output = Path(__file__).resolve().parent / "diagnostics" / "manual" / (
        "bdsp_sp130_party_size_transition_AUTO_"
        + datetime.now().strftime("%Y%m%d_%H%M%S")
        + ".json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with RyujinxHostMappedClient(BDSP_SP_130_HOST_PROFILE) as client:
        before_party = _party(client)
        before_boxes = _boxes(client)
        baseline_count = int(before_party["member_count"])
        print(
            f"CAPTURE_READY party={baseline_count} output={output}",
            flush=True,
        )
        deadline = time.monotonic() + max(30.0, float(timeout_seconds))
        candidate: dict[str, object] | None = None
        while time.monotonic() < deadline:
            current = _party(client)
            if int(current["member_count"]) != baseline_count:
                time.sleep(0.35)
                confirmed = _party(client)
                if _party_fingerprint(current) == _party_fingerprint(confirmed):
                    candidate = confirmed
                    break
            time.sleep(0.15)
        if candidate is None:
            raise TimeoutError(
                f"No se observó un cambio del contador {baseline_count} antes del timeout",
            )
        after_boxes = _boxes(client)
        payload = {
            "purpose": "BDSP SP 1.3.0 party size and box-empty transition proof",
            "read_only": True,
            "process": {
                "pid": int(client.session.process.pid),
                "exe": str(client.session.process.exe_name),
                "title_id": f"{int(client.session.profile.title_id):016X}",
                "revision": str(client.session.profile.revision),
                "transport": "Ryujinx HostMappedUnsafe read-only",
            },
            "before_party": before_party,
            "after_party": candidate,
            "changed_box_slots": _changed_boxes(before_boxes, after_boxes),
        }
        output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(f"CAPTURE_COMPLETE {output}", flush=True)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Captura de solo lectura de una transición de tamaño de party BDSP.",
    )
    parser.add_argument("--timeout", type=float, default=900.0)
    args = parser.parse_args()
    capture(timeout_seconds=args.timeout)


if __name__ == "__main__":
    main()
