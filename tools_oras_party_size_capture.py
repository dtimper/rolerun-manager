"""Captura de solo lectura para localizar el contador de tamaño de party de ORAS.

RoleRun ya sabe escribir Equipo↔PC en ORAS cuando el tamaño del equipo no
cambia (sustitución 1↔1, `ORASLiveWriter`). Para depositar o retirar un
Pokémon sin sustituto hace falta, además, una dirección de RAM que el juego
trate como "cuántos miembros tiene la party" — X/Y ya tiene la suya
(`XY_PARTY_COUNT_ADDRESS = 0x08CE1C74`, demostrada físicamente), pero ORAS no
tiene ninguna todavía. Este script no escribe nada: solo lee dos veces (con
verificación de estabilidad) una ventana de memoria justo antes de la party y
la party completa, y guarda ambas capturas para compararlas a mano.

Procedimiento:
  1. Abre ORAS en Azahar, activa el servidor RPC y entra en una Run con el
     equipo casi lleno (seis miembros, si puedes).
  2. Ejecuta este script: ``python tools_oras_party_size_capture.py``.
  3. Cuando el script imprima CAPTURE_READY, deposita UN Pokémon en el PC
     usando el menú del propio juego (no RoleRun).
  4. El script detecta el cambio solo, confirma que se ha asentado y guarda
     la captura en ``diagnostics/manual/``. Compárteme ese archivo.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import time
from datetime import datetime
from pathlib import Path

from app.azahar_rpc import AzaharRPCClient, AzaharRPCError
from app.oras_live import (
    ORAS_PARTY_ADDRESS,
    ORAS_PARTY_STRIDE,
    ORAS_TITLE_IDS,
    PK6_PARTY_SIZE,
    _checksum,
    decrypt_pk6,
)

# Cubre bastante más que el desplazamiento de X/Y (-0x74, 29 palabras) por si
# el layout de ORAS no es idéntico palabra a palabra.
CANDIDATE_WINDOW_BYTES = 0x200
WORD_SIZE = 4


def _stable(client: AzaharRPCClient, address: int, size: int) -> bytes:
    first = client.read_memory(int(address), int(size))
    second = client.read_memory(int(address), int(size))
    if first != second:
        raise RuntimeError(f"0x{int(address):X}+{int(size)} cambió durante la doble lectura")
    return second


def _identity_from_plain(plain: bytes) -> list[int]:
    return [
        int(struct.unpack_from("<H", plain, 8)[0]),   # species
        int(struct.unpack_from("<I", plain, 0x18)[0]),  # pid
        int(struct.unpack_from("<H", plain, 0x0C)[0]),  # tid
        int(struct.unpack_from("<H", plain, 0x0E)[0]),  # sid
    ]


def _stored_checksum_valid(data: bytes) -> bool:
    """Solo el bloque almacenado (checksum de 112 palabras desde el offset 8).

    Deliberadamente NO exige que la extensión de combate (nivel, PS...) sea
    coherente: un slot puede tener esa mitad obsoleta o sin refrescar (visto
    en una captura real: Torkoal seguía con especie/checksum válidos pero un
    nivel decodificado sin sentido) sin que eso signifique que el slot esté
    vacío. Contar "ocupado" solo por esta mitad evita ese falso vacío.
    """
    sentinel = struct.unpack_from("<H", data, 4)[0]
    checksum_field = struct.unpack_from("<H", data, 6)[0]
    species = struct.unpack_from("<H", data, 8)[0]
    return sentinel == 0 and checksum_field == _checksum(data) and 1 <= species <= 721


def _slot_payload(raw: bytes) -> dict[str, object]:
    if not any(raw):
        return {"empty": True}
    if _stored_checksum_valid(raw):
        return {
            "empty": False,
            "was_encrypted": False,
            "identity": _identity_from_plain(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    decrypted = decrypt_pk6(raw)
    if _stored_checksum_valid(decrypted):
        return {
            "empty": False,
            "was_encrypted": True,
            "identity": _identity_from_plain(decrypted),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    return {
        "empty": False,
        "diagnostic_error": "checksum del bloque almacenado no válido ni en crudo ni descifrado",
        "sha256": hashlib.sha256(raw).hexdigest(),
        # Un slot que no valida como PK6 es justo el caso que hay que poder
        # inspeccionar byte a byte después: guardamos el crudo completo aquí,
        # no solo en los vacíos/válidos donde el hash ya basta.
        "raw_hex": raw.hex(),
    }


def _candidate_words(client: AzaharRPCClient) -> dict[str, object]:
    start = ORAS_PARTY_ADDRESS - CANDIDATE_WINDOW_BYTES
    raw = _stable(client, start, CANDIDATE_WINDOW_BYTES)
    words = struct.unpack(f"<{CANDIDATE_WINDOW_BYTES // WORD_SIZE}I", raw)
    return {
        f"0x{start + index * WORD_SIZE:08X}": int(value)
        for index, value in enumerate(words)
    }


def _party(client: AzaharRPCClient) -> dict[str, object]:
    slots: list[dict[str, object]] = []
    for index in range(6):
        address = ORAS_PARTY_ADDRESS + index * ORAS_PARTY_STRIDE
        raw = _stable(client, address, PK6_PARTY_SIZE)
        slots.append({"slot": index + 1, "address": f"0x{address:08X}", **_slot_payload(raw)})
    occupied = sum(1 for row in slots if not row.get("empty", True))
    return {
        "timestamp": time.time(),
        "occupied_count": occupied,
        "candidate_words": _candidate_words(client),
        "slots": slots,
    }


def _party_fingerprint(party: dict[str, object]) -> tuple[object, ...]:
    slots = party.get("slots", [])
    assert isinstance(slots, list)
    return (
        int(party["occupied_count"]),
        tuple(
            (
                bool(row.get("empty", True)),
                str(row.get("sha256", "")),
                str(row.get("diagnostic_error", "")),
            )
            for row in slots
            if isinstance(row, dict)
        ),
    )


def _changed_candidate_words(
    before: dict[str, object], after: dict[str, object],
) -> list[dict[str, object]]:
    before_words = before.get("candidate_words", {})
    after_words = after.get("candidate_words", {})
    assert isinstance(before_words, dict) and isinstance(after_words, dict)
    changed = []
    for address in before_words:
        old = int(before_words[address])
        new = int(after_words.get(address, old))
        if old != new:
            changed.append({
                "address": address, "before": old, "after": new, "delta": new - old,
            })
    return changed


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
        "oras_party_size_transition_AUTO_"
        + datetime.now().strftime("%Y%m%d_%H%M%S")
        + ".json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)

    with AzaharRPCClient() as client:
        process = _find_process(client)
        client.set_process(process.process_id)

        before = _party(client)
        baseline = int(before["occupied_count"])
        print(
            f"CAPTURE_READY equipo={baseline} proceso={process.name} output={output}",
            flush=True,
        )
        print(
            "Deposita ahora UN Pokémon en el PC desde el menú del propio juego...",
            flush=True,
        )

        deadline = time.monotonic() + max(30.0, float(timeout_seconds))
        candidate: dict[str, object] | None = None
        before_fingerprint = _party_fingerprint(before)
        while time.monotonic() < deadline:
            current = _party(client)
            # Compara la huella completa (identidad/vacío de los 6 slots), no
            # solo el recuento: un depósito puede dejar un slot con checksum
            # válido pero corrupto sin cambiar cuántos slots "cuentan" como
            # ocupados con la validación estricta.
            if _party_fingerprint(current) != before_fingerprint:
                time.sleep(0.35)
                confirmed = _party(client)
                if _party_fingerprint(current) == _party_fingerprint(confirmed):
                    candidate = confirmed
                    break
            time.sleep(0.15)
        if candidate is None:
            raise TimeoutError(
                f"No se observó un cambio del equipo ({baseline} miembros) antes del timeout",
            )

        changed_words = _changed_candidate_words(before, candidate)
        payload = {
            "purpose": "ORAS party size transition — localizar el contador de tamaño",
            "read_only": True,
            "process": {
                "pid": int(process.process_id),
                "name": str(process.name),
                "title_id": f"{int(process.title_id):016X}",
            },
            "before_party": before,
            "after_party": candidate,
            "changed_candidate_words": changed_words,
        }
        output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(f"CAPTURE_COMPLETE {output}", flush=True)
    if changed_words:
        print("Palabras candidatas que cambiaron:", flush=True)
        for entry in changed_words:
            print(
                f"  {entry['address']}: {entry['before']} -> {entry['after']} "
                f"(delta={entry['delta']:+d})",
                flush=True,
            )
    else:
        print(
            "Ninguna palabra en la ventana candidata cambió — el contador (si existe) "
            "vive fuera de la ventana explorada o no es un entero de 4 bytes.",
            flush=True,
        )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Captura de solo lectura para localizar el contador de party de ORAS.",
    )
    parser.add_argument("--timeout", type=float, default=900.0)
    args = parser.parse_args()
    capture(timeout_seconds=args.timeout)


if __name__ == "__main__":
    main()
