from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.save_engine_client import SaveGameData
from app.sm_live import SM_PC_LIVEHEX_B1S1_REFERENCE, SMLiveWriter
from app.win_process_memory import HostPartyTarget


class _Client:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def process_list(self):
        return [SimpleNamespace()]

    def set_process(self, _pid: int) -> None:
        return None


class _Memory:
    def find_party_targets(self, **_kwargs):
        return [HostPartyTarget(77, "azahar.exe", 0x50020000)]


def test_alpha32_prefers_proven_live_pc_reference_before_stale_main_witnesses(tmp_path: Path) -> None:
    """Un main con PC poblado/desfasado no puede bloquear una prueba live más fuerte.

    Alpha.31 intentaba primero reconstruir la matriz a partir de PK7 exactos del
    último main. Si el PC vivo había cambiado, esa ruta podía fallar y abortar sin
    probar la referencia live que ya se había validado físicamente en la sesión.
    Alpha.32 debe resolver primero la candidata live y no consultar el main como
    autoridad del estado actual.
    """
    save = tmp_path / "main"
    save.write_bytes(b"stale-saved-pc-witnesses")

    process = SimpleNamespace(title_id=0x0004000000164800, process_id=1234, name="azahar.exe")
    reader = SimpleNamespace(
        move_names={},
        client_factory=lambda: _Client(),
        _find_sm_process=lambda _items: process,
        _locate_party_base=lambda _client, _process, _current: 0x34195E10,
    )
    writer = SMLiveWriter(reader, host_memory_factory=lambda: _Memory())
    writer._capture_stable_party = lambda _client, _base: ([b"party-slot"], 1)  # type: ignore[method-assign]
    live_parsed = {(1, 1): None}
    writer._resolve_pc_from_livehex_reference = lambda **_kwargs: (  # type: ignore[method-assign]
        77, 0x50010000, SM_PC_LIVEHEX_B1S1_REFERENCE, live_parsed, [{"accepted": True}],
    )
    writer._save_pc_diagnostic = lambda _payload: None  # type: ignore[method-assign]

    current = SaveGameData("Pokémon Sol", "SAV7SM", 7, "Timper", [], {})
    with patch("app.sm_live._saved_pc_matrix_candidates", side_effect=AssertionError("stale main path must not run")):
        resolved_process, guest_base, parsed = writer.read_pc_for_game(
            current, save, [], box_count=32, box_slot_count=30,
        )

    assert resolved_process is process
    assert guest_base == SM_PC_LIVEHEX_B1S1_REFERENCE
    assert parsed is live_parsed
    assert writer._pc_last_resolution["source"].endswith("(preferred live path)")
    assert writer._pc_live_cache is not None
