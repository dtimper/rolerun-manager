"""Una baja de B2/W2 no puede quedarse en un limbo del que no se sale.

Fallo reportado el 27-08-2026 con alpha.28: al morir el Asesino en combate no se
descontaba la vida; al salir, el Pokémon desaparecía de la vista; **no aparecía
la opción de sustituirlo**; curarlo no lo devolvía; y reiniciar juego y programa
tampoco. Además el hueco vacío se desplazaba al rol de Support mientras un
Pokémon SIN ROL ocupaba el del Asesino.

Dos causas, con una raíz común: la rama B2/W2 del monitor no llamaba a dos
funciones que los otros cinco backends sí llaman.

1. Sin ``_process_oras_battle_state`` no se marca nunca ``battle_ended``. El
   selector de sustituto exige ``battle_ended``, así que no se abría; y
   ``clear_stale_detected_faint_for_alive_party`` exige ``battle_ended`` o
   ``prompt_shown``, así que curar al debilitado tampoco lo devolvía. Como la
   baja se persiste en la Run, reiniciar no cambiaba nada.
2. Sin ``_reconcile_pending_faints_against_party``, resolver la baja desde el PC
   del propio juego no se detectaba.

Y una tercera, de presentación: la casilla de un rol pertenece al rol, y es la
que heredará el sustituto. Dejar que un miembro SIN ROL se deslizara hasta ella
movía el hueco a otro rol distinto.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.role_rules import ROLE_ORDER  # noqa: E402
from app.run_service import RunProjectService  # noqa: E402
from app.save_engine_client import SavePokemon  # noqa: E402
from app.ui import RoleRunManager  # noqa: E402


# --------------------------------------------------------------------------
# El ciclo completo de una baja
# --------------------------------------------------------------------------

def test_la_rama_b2w2_cierra_el_ciclo_de_bajas() -> None:
    """Las dos llamadas que faltaban, en la rama que las necesita."""
    import inspect

    fuente = inspect.getsource(RoleRunManager._finish_oras_live_reconciliation)
    rama = fuente[fuente.index("in MELONDS_REALTIME_GAME_KEYS"):]
    rama = rama[:rama.index("_schedule_oras_live_reconciliation")]
    assert "_process_oras_battle_state" in rama
    assert "_reconcile_pending_faints_against_party" in rama


@pytest.mark.parametrize(
    ("probe", "esperado"),
    [("battle", "trainer"), ("none", "none"), ("unknown", None)],
)
def test_el_estado_de_combate_se_traduce_al_vocabulario_comun(probe, esperado) -> None:
    """El resto de backends hablan de wild/trainer/none; B2/W2 de battle/none."""
    import inspect

    fuente = inspect.getsource(RoleRunManager._finish_oras_live_reconciliation)
    rama = fuente[fuente.index("in MELONDS_REALTIME_GAME_KEYS"):]
    assert '"trainer" if probe_state == "battle"' in rama
    assert '"none" if probe_state == "none"' in rama


def _proyecto(pendientes) -> SimpleNamespace:
    return SimpleNamespace(pending_faints=list(pendientes))


def test_sin_battle_ended_no_se_podia_limpiar_una_baja_obsoleta(tmp_path) -> None:
    """Reproduce por qué curar al debilitado no lo devolvía.

    ``clear_stale_detected_faint_for_alive_party`` exige que la baja haya llegado
    al menos a ``battle_ended`` o ``prompt_shown``. B2/W2 no marcaba ninguno.
    """
    servicio = RunProjectService(tmp_path)
    proyecto = servicio.open_or_create("b2w2", "Diego", tmp_path / "main")
    proyecto.pending_faints = [{"identity": "179:1:2:3", "pokemon": "Mareep"}]

    assert servicio.clear_stale_detected_faint_for_alive_party(
        proyecto, "179:1:2:3",
    ) is False

    proyecto.pending_faints[0]["battle_ended"] = True
    assert servicio.clear_stale_detected_faint_for_alive_party(
        proyecto, "179:1:2:3",
    ) is True
    assert proyecto.pending_faints == []


def test_el_selector_solo_esta_listo_cuando_termino_el_combate() -> None:
    manager = SimpleNamespace(project=_proyecto([
        {"identity": "a", "prompt_shown": False, "battle_ended": False},
    ]))
    assert RoleRunManager._next_ready_pending_faint(manager) is None

    manager.project.pending_faints[0]["battle_ended"] = True
    assert RoleRunManager._next_ready_pending_faint(manager) is not None


# --------------------------------------------------------------------------
# La casilla del rol se reserva
# --------------------------------------------------------------------------

def _mon(role: str, index: int) -> SavePokemon:
    return SavePokemon(
        slot=index, species_id=500 + index, species=f"E{index}", nickname=f"P{index}",
        level=10, held_item="Ninguno", ability="X", moves=["Placaje"], move_ids=[33],
        is_egg=False, markings=[False] * 6, role=role, role_symbol="",
        pid=1000 + index, tid=1, sid=2,
    )


def _layout_manager(party, reservados) -> SimpleNamespace:
    manager = SimpleNamespace(
        _effective_role=lambda pokemon: (pokemon.role, pokemon.role_symbol),
        _pokemon_identity=lambda pokemon: str(pokemon.pid),
        _roles_reserved_by_pending_faints=lambda: set(reservados),
    )
    manager._role_slot_occupants = lambda members: RoleRunManager._role_slot_occupants(
        manager, members,
    )
    return manager


def test_el_hueco_del_caido_no_se_lo_queda_un_sin_rol() -> None:
    """El caso exacto reportado: cae el Asesino y el hueco se iba a Support."""
    party = [_mon("Líbero", 1), _mon("SIN ROL", 2)]
    manager = _layout_manager(party, {"Asesino"})

    _ocupantes, _extras, posiciones, extras_idx = RoleRunManager._team_role_grid_layout(
        manager, party,
    )

    asesino = ROLE_ORDER.index("Asesino")
    assert asesino not in posiciones.values(), "la casilla del Asesino debe quedar libre"
    assert asesino not in extras_idx
    # El SIN ROL se coloca, pero en otra casilla.
    assert posiciones["1002"] != asesino


def test_sin_bajas_pendientes_el_reparto_no_cambia() -> None:
    party = [_mon("Líbero", 1), _mon("SIN ROL", 2)]
    manager = _layout_manager(party, set())

    _ocupantes, _extras, posiciones, _extras_idx = RoleRunManager._team_role_grid_layout(
        manager, party,
    )

    assert posiciones["1002"] == ROLE_ORDER.index("Asesino"), (
        "sin bajas, el SIN ROL sigue ocupando la primera casilla libre"
    )


def test_una_baja_reserva_exactamente_el_rol_que_tenia() -> None:
    manager = SimpleNamespace(project=_proyecto([
        {"identity": "a", "role": "Asesino"},
        {"identity": "b", "role": "SIN ROL"},
        {"identity": "c", "role": ""},
    ]))
    assert RoleRunManager._roles_reserved_by_pending_faints(manager) == {"Asesino"}


def test_sin_run_abierta_no_se_reserva_nada() -> None:
    manager = SimpleNamespace(project=None)
    assert RoleRunManager._roles_reserved_by_pending_faints(manager) == set()
