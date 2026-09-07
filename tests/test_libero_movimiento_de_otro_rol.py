"""Líbero no restringe movimientos por su cuenta, pero un movimiento que en
realidad se drafteó con OTRO rol activo -y solo se conserva porque el
Pokémon volvió a Líbero después- no es un movimiento «propio» de Líbero.

Reporte del usuario (2026-09-07): cambiar a Support solo para garantizarse un
drafteo de Hazards con certeza (draftear/rerrollear en Support, que sí exige
esa categoría, en vez de fiarse del sorteo de Líbero) y volver a Líbero
después se quedaba el movimiento sin ningún aviso, porque Líbero no tiene
restricciones propias. Se resuelve igual que cualquier otra incompatibilidad
-en rojo, con papelera/MT como salida, mismo flujo que ya usa la cláusula de
evasión de Líbero-, pero con un motivo distinto que delata el origen en vez
de fingir que el movimiento es ilegal.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.role_rules import libero_foreign_move_reason  # noqa: E402
from app.ui import RoleRunManager  # noqa: E402

MOVE_ID = 9001
MOVE_NAME = "Movimiento Drafteado"


# --------------------------------------------------------------------------
# role_rules.libero_foreign_move_reason: reglas puras
# --------------------------------------------------------------------------

def test_sin_registro_no_hay_motivo() -> None:
    """Sin prueba de que el movimiento venga de otro rol, no se avisa -mismo
    criterio que el resto de RoleRun: nunca inventar incompatibilidades."""
    assert libero_foreign_move_reason(None) == ""
    assert libero_foreign_move_reason("") == ""


def test_drafteado_como_libero_no_tiene_motivo() -> None:
    assert libero_foreign_move_reason("Líbero") == ""


def test_drafteado_con_otro_rol_activo_tiene_motivo_y_lo_nombra() -> None:
    motivo = libero_foreign_move_reason("Support")
    assert motivo
    assert "Support" in motivo
    assert "Líbero" in motivo


def test_normaliza_nombres_historicos_del_rol_de_origen() -> None:
    """`canonical_role` traduce "Paladín"/"soporte" a los nombres nuevos; el
    motivo debe usar siempre el nombre vigente, no el histórico guardado."""
    assert "Prisma" in libero_foreign_move_reason("Paladín")
    assert "Support" in libero_foreign_move_reason("soporte")


# --------------------------------------------------------------------------
# RoleRunManager._collect_pokemon_move_issues: integración con el registro
# --------------------------------------------------------------------------

def _manager_libero(origin: dict[str, str]) -> SimpleNamespace:
    return SimpleNamespace(
        engine=SimpleNamespace(pools={}),
        project=SimpleNamespace(drafted_move_origin={"id:1": origin}),
        _effective_moves_for_review=lambda p: (
            [MOVE_NAME, "—", "—", "—"], [MOVE_ID, 0, 0, 0],
        ),
        _pokemon_identity=lambda p: "id:1",
    )


def test_libero_avisa_de_un_movimiento_drafteado_con_otro_rol() -> None:
    manager = _manager_libero({str(MOVE_ID): "Support"})

    issues = RoleRunManager._collect_pokemon_move_issues(manager, object(), "Líbero")

    assert len(issues) == 1
    issue = issues[0]
    assert issue["move_slot"] == 1
    assert issue["move_id"] == MOVE_ID
    assert issue["role"] == "Líbero"
    assert "Support" in issue["reason"]


def test_libero_no_avisa_si_lo_drafteo_el_mismo() -> None:
    manager = _manager_libero({str(MOVE_ID): "Líbero"})

    issues = RoleRunManager._collect_pokemon_move_issues(manager, object(), "Líbero")

    assert issues == []


def test_libero_no_avisa_sin_ningun_registro() -> None:
    """Un movimiento aprendido por otra vía (nivel, MT, migración) o
    drafteado antes de que este historial existiera no lleva registro: no se
    penaliza sin poder demostrar que es ajeno."""
    manager = _manager_libero({})

    issues = RoleRunManager._collect_pokemon_move_issues(manager, object(), "Líbero")

    assert issues == []


def test_sin_project_no_revienta_y_no_avisa() -> None:
    """`self.project` puede ser ``None`` (sin Run cargada); no debe fallar."""
    manager = SimpleNamespace(
        engine=SimpleNamespace(pools={}),
        project=None,
        _effective_moves_for_review=lambda p: (
            [MOVE_NAME, "—", "—", "—"], [MOVE_ID, 0, 0, 0],
        ),
        _pokemon_identity=lambda p: "id:1",
    )

    issues = RoleRunManager._collect_pokemon_move_issues(manager, object(), "Líbero")

    assert issues == []


# --------------------------------------------------------------------------
# RoleRunManager.queue_draft_change: dónde se registra el origen
# --------------------------------------------------------------------------

def test_queue_draft_change_registra_bajo_que_rol_se_drafteo() -> None:
    """El «momento definitivo del drafteo» -ya documentado en el propio
    código- es donde debe quedar anotado el rol activo, junto al resto de
    mutaciones de `self.project` de esta función."""
    fuente = inspect.getsource(RoleRunManager.queue_draft_change)

    assert "self.project.drafted_move_origin.setdefault(pokemon_identity, {})[" in fuente
    assert "canonical_role(draft.role)" in fuente
