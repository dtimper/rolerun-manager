from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

try:
    import customtkinter  # noqa: F401
except ModuleNotFoundError:
    customtkinter = types.ModuleType("customtkinter")
    customtkinter.CTk = object
    sys.modules["customtkinter"] = customtkinter

from app.config import APP_VERSION
from app.save_engine_client import SaveGameData
from app.sm_live import (
    PK7_PARTY_SIZE,
    SM_SAVE_PC_BLOCK_OFFSET,
    SM_SAVE_PC_BLOCK_SIZE,
    SMLiveError,
    SMLiveWriter,
)
from app.win_process_memory import HostPartyTarget


class _Client:
    def __init__(self, process):
        self.process = process

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def process_list(self):
        return [self.process]

    def set_process(self, _pid):
        return None


class _Host:
    def find_party_targets(self, **_kwargs):
        return [HostPartyTarget(91, "azahar.exe", 0x60000000)]


def test_alpha23_version_after_diagnostic_fix() -> None:
    assert APP_VERSION == "0.2.6-alpha.58"


def test_alpha22_read_pc_preserves_resolver_rejection_evidence_in_diagnostic(tmp_path: Path) -> None:
    # Main válido en tamaño pero sin PK7 de caja: obliga a entrar en el fallback
    # de imagen viva, igual que la partida real que motivó alpha.22.
    save = tmp_path / "main"
    save.write_bytes(b"\0" * (SM_SAVE_PC_BLOCK_OFFSET + SM_SAVE_PC_BLOCK_SIZE))

    process = SimpleNamespace(title_id=0x0004000000164800, process_id=22, name="main")
    reader = SimpleNamespace(
        move_names={},
        client_factory=lambda: _Client(process),
        _find_sm_process=lambda _processes: process,
        _locate_party_base=lambda _client, _process, _current: 0x34195E10,
    )
    writer = SMLiveWriter(reader, host_memory_factory=_Host)
    writer._capture_stable_party = lambda _client, _base: ([b"P" * PK7_PARTY_SIZE], 1)

    expected_evaluated = [{
        "pid": 91,
        "host_party_base": "0x60000000",
        "guest_pc_reference": "0x330D9838",
        "rejected": "reference-host-guest-full-matrix-proof-failed",
    }]

    def fail_resolver(**_kwargs):
        writer._pc_last_resolution = {
            "source": "livehex-sm-v120-reference-sin-resolver",
            "proofs": 0,
            "guest_reference": 0x330D9838,
            "evaluated": expected_evaluated,
        }
        raise SMLiveError(
            "La referencia live de BoxPokemon para Sol/Luna v1.2.0 no superó la prueba completa host+guest."
        )

    writer._resolve_pc_from_livehex_reference = fail_resolver

    captured = {}
    writer._save_pc_diagnostic = lambda payload: captured.update(payload) or None

    current = SaveGameData("Pokémon Sol", "SAV7SM", 7, "T", [], {})
    with pytest.raises(SMLiveError, match="referencia live"):
        writer.read_pc_for_game(current, save, [], box_count=32, box_slot_count=30)

    assert captured["stage"] == "livehex-sm-v120-reference-proof"
    assert captured["party_target_count"] == 1
    assert captured["proofs"] == 0
    assert captured["resolver_source"] == "livehex-sm-v120-reference-sin-resolver"
    assert captured["bruteforce_scan_attempted"] is False
    assert captured["evaluated"] == expected_evaluated
    assert writer._pc_last_resolution["evaluated"] == expected_evaluated
