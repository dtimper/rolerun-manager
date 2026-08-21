from __future__ import annotations

from types import SimpleNamespace

from app.models import PendingRoleChange
from app.realtime.sm_adapter import SMRealTimeAdapter


def _role(mon: str, old: str, new: str, slot: int) -> PendingRoleChange:
    return PendingRoleChange(
        pokemon_slot=slot,
        pokemon=mon,
        species=mon,
        old_role=old,
        new_role=new,
        pokemon_identity=f"id-{mon}",
    )


class RecordingWriter:
    def __init__(self) -> None:
        self.calls: list[list[tuple[str, str, str]]] = []

    def apply(self, current, changes):
        batch = [(change.pokemon, change.old_role, change.new_role) for change in changes]
        self.calls.append(batch)
        return SimpleNamespace(
            game=current,
            process=SimpleNamespace(process_id=1),
            attempts=1,
            applied_count=len(changes),
            already_applied=False,
        )


def _adapter(writer) -> SMRealTimeAdapter:
    adapter = object.__new__(SMRealTimeAdapter)
    adapter.writer = writer
    return adapter


def test_alpha10_multi_role_swap_restores_alpha4_single_transaction_semantics() -> None:
    writer = RecordingWriter()
    adapter = _adapter(writer)
    changes = [
        _role("A", "Líbero", "Asesino", 1),
        _role("B", "Asesino", "Líbero", 2),
    ]

    result = adapter.apply_changes(SimpleNamespace(), changes)

    assert writer.calls == [[
        ("A", "Líbero", "Asesino"),
        ("B", "Asesino", "Líbero"),
    ]]
    assert result.applied_count == 2


def test_alpha10_single_role_change_still_uses_same_writer_transaction() -> None:
    writer = RecordingWriter()
    adapter = _adapter(writer)
    change = _role("A", "Líbero", "Mago", 1)

    adapter.apply_changes(SimpleNamespace(), [change])

    assert writer.calls == [[("A", "Líbero", "Mago")]]
