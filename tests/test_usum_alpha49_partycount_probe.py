from __future__ import annotations

from pathlib import Path

from app.save_engine_client import SavePokemon
from app.usum_live import (
    USUM_PARTY_ALTERNATE_REFERENCE_ADDRESS,
    USUM_PARTY_REFERENCE_ADDRESS,
    USUM_PARTY_STRIDE,
    USUMLiveReader,
    USUMLiveWriter,
)


class _Client:
    def __init__(self, count: int):
        self.count = int(count)
        self.calls: list[tuple[int, int]] = []

    def read_memory(self, address: int, size: int) -> bytes:
        self.calls.append((int(address), int(size)))
        raw = bytearray(int(size))
        # Una metadata ficticia 0x40 bytes antes de la party cambia exactamente
        # con el número lógico. El test no afirma que ESTE sea el offset real:
        # solo valida que la sonda acotada detecta N→M sin escanear FCRAM.
        raw[0xC0] = self.count
        return bytes(raw)


def _party(count: int) -> dict[int, SavePokemon]:
    return {
        slot: SavePokemon(
            slot=slot, species_id=100 + slot, species=f"P{slot}", nickname=f"P{slot}", level=5,
            held_item="Ninguno", ability="", moves=["—"] * 4, move_ids=[0] * 4,
            is_egg=False, markings=[False] * 6, role="SIN ROL", role_symbol="",
            pid=0x10000000 + slot, tid=1, sid=2,
        )
        for slot in range(1, count + 1)
    }


def test_alpha49_probe_is_bounded_and_compares_6_to_5(tmp_path: Path) -> None:
    reader = USUMLiveReader(Path("missing.json"), stable_delay=0, snapshot_attempts=1)
    writer = USUMLiveWriter(reader, diagnostic_dir=tmp_path / "diag")

    six = _Client(6)
    path6 = writer._collect_partycount_probe(client=six, expected_sparse=_party(6))
    assert path6 is not None

    five = _Client(5)
    path5 = writer._collect_partycount_probe(client=five, expected_sparse=_party(5))
    assert path5 is not None

    import json
    payload = json.loads(path5.read_text(encoding="utf-8"))
    assert payload["party_count"] == 5
    assert payload["fcram_scan_attempted"] is False
    assert payload["writes_attempted"] is False
    assert payload["comparison"]["previous_count"] == 6
    for name in ("primary", "alternate"):
        matches = payload["comparison"]["regions"][name]["exact_previous_to_current_count"]
        assert matches and matches[0]["before"] == 6 and matches[0]["after"] == 5

    # Cada snapshot son exactamente 2 regiones × 2 lecturas estables; no hay
    # búsqueda iterativa ni acceso fuera de las ventanas acotadas.
    assert len(six.calls) == 4
    assert len(five.calls) == 4
    allowed_starts = {
        USUM_PARTY_REFERENCE_ADDRESS - 0x100,
        USUM_PARTY_ALTERNATE_REFERENCE_ADDRESS - 0x100,
    }
    expected_size = (6 * USUM_PARTY_STRIDE) + 0x100 + 0x300
    for address, size in six.calls + five.calls:
        assert address in allowed_starts
        assert size == expected_size
