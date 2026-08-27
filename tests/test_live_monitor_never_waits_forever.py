"""Un cambio que nadie puede escribir no puede congelar el monitor en vivo.

Este fallo ha aparecido ya dos veces con síntomas muy distintos:

- alpha.16: el botón CURAR de B2/W2 encolaba seis curaciones sin writer y la
  partida dejaba de actualizarse;
- alpha.23: asignar un rol en B2/W2 encolaba un cambio sin writer, y el usuario
  reportó a la vez «los roles no funcionan», «los EV siguen a cero» y «la vida no
  se refleja» — un solo defecto con tres caras.

La causa común: ``_oras_live_reconciliation_can_read`` exigía la cola
completamente vacía. Esperar a un cambio que el adaptador activo no sabe aplicar
es esperar para siempre.

La regla correcta es la de estas pruebas: **solo bloquean la lectura los cambios
que de verdad tienen writer**. Un cambio sin writer sigue en la cola —el usuario
podrá guardarlo por archivo— pero no secuestra el seguimiento en vivo.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models import (  # noqa: E402
    PendingChange,
    PendingPCRoleChange,
    PendingPartyHeal,
    PendingRoleChange,
    PendingTeamChange,
)
from app.ui import RoleRunManager  # noqa: E402


def _manager(live_key: str, pendientes) -> SimpleNamespace:
    manager = SimpleNamespace(
        run=SimpleNamespace(pending_changes=list(pendientes)),
        _active_azahar_realtime_key=lambda: live_key,
    )
    manager._oras_live_unsupported_changes = lambda changes: (
        RoleRunManager._oras_live_unsupported_changes(manager, changes)
    )
    return manager


def _movimiento() -> PendingChange:
    return PendingChange(
        role="Mago", pokemon_slot=0, pokemon="Tepig", species="Tepig",
        move_slot=1, old_move="Placaje", old_move_id=33,
        new_move="Ascuas", new_move_id=52,
    )


def _rol() -> PendingRoleChange:
    return PendingRoleChange(0, "Tepig", "Tepig", "SIN ROL", "Mago")


def _sin_writer() -> PendingPCRoleChange:
    """Un cambio que B2/W2 todavía no sabe escribir.

    Los movimientos sueltos lo eran hasta alpha.46, cuando tuvieron writer. Lo
    que esta prueba protege no es la lista, sino la regla: esperar por algo que
    nunca se va a escribir es esperar para siempre. El rol de un Pokémon que se
    queda en el PC sigue sin writer, así que sirve igual de ejemplo.
    """
    return PendingPCRoleChange(
        box=0, box_slot=0, pokemon="Tepig", species="Tepig",
        pokemon_identity="1:2:3:4", old_role="SIN ROL", new_role="Mago",
    )


def _curacion() -> PendingPartyHeal:
    return PendingPartyHeal(
        pokemon_slot=0, pokemon="Tepig", species="Tepig", pokemon_identity="x",
    )


def _traslado() -> PendingTeamChange:
    return PendingTeamChange(operation="swap-party-box", party_slot=0)


def test_sin_nada_en_cola_se_puede_leer() -> None:
    manager = _manager("b2w2", [])
    assert RoleRunManager._oras_live_pending_changes_block_reads(manager) is False


@pytest.mark.parametrize("cambio", [_rol, _curacion, _traslado])
def test_un_cambio_con_writer_si_bloquea_la_lectura(cambio) -> None:
    """Mientras se puede escribir de verdad, el monitor debe esperar."""
    manager = _manager("b2w2", [cambio()])
    assert RoleRunManager._oras_live_pending_changes_block_reads(manager) is True


def test_un_cambio_sin_writer_no_secuestra_el_seguimiento() -> None:
    """Esperar por algo que nunca se escribirá es esperar para siempre."""
    manager = _manager("b2w2", [_sin_writer()])
    assert RoleRunManager._oras_live_pending_changes_block_reads(manager) is False


def test_basta_uno_aplicable_para_esperar() -> None:
    manager = _manager("b2w2", [_sin_writer(), _rol()])
    assert RoleRunManager._oras_live_pending_changes_block_reads(manager) is True


def test_varios_inaplicables_siguen_sin_bloquear() -> None:
    manager = _manager("b2w2", [_sin_writer(), _sin_writer()])
    assert RoleRunManager._oras_live_pending_changes_block_reads(manager) is False


def test_en_un_backend_completo_todo_lo_normal_bloquea() -> None:
    """En BDSP sí hay writer de movimientos: ahí la espera es legítima."""
    manager = _manager("bdsp", [_movimiento()])
    assert RoleRunManager._oras_live_pending_changes_block_reads(manager) is True


def test_la_condicion_de_lectura_usa_la_nueva_regla() -> None:
    """La regla vive en el predicado, no solo en una función auxiliar."""
    import inspect

    fuente = inspect.getsource(RoleRunManager._oras_live_reconciliation_can_read)
    assert "_oras_live_pending_changes_block_reads()" in fuente
    assert "not self.run.pending_changes" not in fuente


def test_una_sesion_sin_run_no_bloquea() -> None:
    manager = SimpleNamespace(_active_azahar_realtime_key=lambda: "b2w2")
    manager._oras_live_unsupported_changes = lambda changes: []
    assert RoleRunManager._oras_live_pending_changes_block_reads(manager) is False
