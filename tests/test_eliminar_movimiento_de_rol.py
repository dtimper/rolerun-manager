"""ELIMINAR en un movimiento incompatible con el rol debe vaciar el hueco.

Reporte del usuario (04-09-2026): en Sol/Luna, Gruñido salía en rojo por no
encajar con el rol del Pikipek. Al pulsar ELIMINAR desaparecía el aviso
SUSTITUIR/ELIMINAR, pero el hueco seguía enseñando «Gruñido» — solo que ya sin
marcarlo como incompatible, como si de repente fuera legal.

Causa raíz: `_render_inspector` (y las dos tarjetas de equipo) pintaban el
nombre del movimiento desde `pokemon.moves` sin proyectar, mientras que el
aviso rojo salía de `move_issues_for`, que sí proyecta `pending_changes`
(incluida la baja en cola que deja ELIMINAR). Dos fuentes de verdad para la
misma celda en el mismo repintado: en cuanto la baja quedaba en cola, el aviso
desaparecía pero el texto seguía siendo el antiguo.

Este test reproduce exactamente esa divergencia: `move_issues_for` ya no
reporta el hueco 1 como incompatible (como ocurre nada más encolar la baja),
y comprueba que el nombre mostrado también refleja la baja -a través de
`effective_moves_for`, la misma proyección que ya usa `move_issues_for`- en
vez de quedarse con el movimiento antiguo.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui_state.team_pc_state import TeamPCSelectionState  # noqa: E402
from app.ui_views.team_pc_view import UnifiedTeamPCView  # noqa: E402

GRUNIDO_ID = 33


class _Mono:
    def __init__(self, indice: int) -> None:
        self.species_id = 100 + indice
        self.species = f"ESPECIE{indice}"
        self.nickname = f"MONO{indice}"
        self.level = 20 + indice
        self.max_hp = 60
        self.current_hp = 60
        self.stats = {
            "hp": 60, "attack": 50, "defense": 45,
            "sp_attack": 40, "sp_defense": 42, "speed": 55,
        }
        self.nature_increased = "attack"
        self.nature_decreased = "sp_attack"
        self.ability = f"HAB{indice}"
        self.held_item = f"OBJ{indice}"
        self.moves = ["Gruñido", "—", "—", "—"]
        self.move_ids = [GRUNIDO_ID, 0, 0, 0]
        self.slot = indice
        self.box_slot = indice


def _equipo() -> tuple[dict, ...]:
    roles = ("TANQUE", "APOYO", "ATACANTE", "VELOZ", "ESPECIAL", "COMODIN")
    return tuple(
        {"slot_role": roles[indice], "state": "", "pokemon": _Mono(indice + 1)}
        for indice in range(6)
    )


def _texto(widget) -> str:
    try:
        return str(widget.cget("text"))
    except Exception:
        return ""


def _celda_del_hueco_uno(superficie):
    move_grid = None
    for frame in superficie.inspector_panel.winfo_children():
        for child in frame.winfo_children():
            if _texto(child) == "MOVIMIENTOS":
                move_grid = frame.winfo_children()[frame.winfo_children().index(child) + 1]
    assert move_grid is not None, "no se encontró la rejilla de movimientos"
    celdas = move_grid.winfo_children()
    assert celdas, "la rejilla de movimientos está vacía"
    cell = celdas[0]
    label = next(
        child for child in cell.winfo_children()
        if child.winfo_manager() and "CTkLabel" in str(type(child))
    )
    return cell, label


def _construir_vista(ctk, *, move_issues_for, effective_moves_for):
    root = ctk.CTk()
    root.geometry("1360x860")
    root.update_idletasks()
    cuerpo = ctk.CTkFrame(root)
    cuerpo.pack(fill="both", expand=True)
    superficie = UnifiedTeamPCView(
        cuerpo,
        team_slots=_equipo(), pc_members={},
        pc_box=1, pc_box_count=1, pc_slot_count=30,
        selection=TeamPCSelectionState(),
        identity_for=lambda p: f"id:{p.species_id}",
        role_for=lambda p, contexto: (contexto, ""),
        sprite_for=lambda p, tamano: None,
        role_icon_for=lambda rol, tamano: None,
        pending_for=lambda p, contexto: False,
        move_issues_for=move_issues_for,
        effective_moves_for=effective_moves_for,
        on_box_change=lambda caja: (caja, {}),
        on_search=lambda texto: [],
        on_action=lambda accion, p: None,
        on_role_info=lambda rol: None,
        move_metadata_for=lambda move_id: None,
        on_move_info=lambda move_id, nombre: None,
    )
    root.update_idletasks()
    superficie._select_team(superficie.team_slots[0]["pokemon"])
    root.update_idletasks()
    return root, superficie


@pytest.fixture
def entorno_tk():
    ctk = pytest.importorskip("customtkinter")
    return ctk


def test_tras_eliminar_el_hueco_se_vacia_en_vez_de_seguir_mostrando_el_viejo_movimiento(
    entorno_tk,
) -> None:
    """Reproduce el bug: `move_issues_for` ya proyecta la baja en cola (como
    hace `_collect_pokemon_move_issues` en cuanto ELIMINAR encola el cambio) y
    `effective_moves_for` debe proyectar esa misma baja para el nombre."""
    ctk = entorno_tk
    try:
        root, superficie = _construir_vista(
            ctk,
            move_issues_for=lambda p, contexto: [],
            effective_moves_for=lambda p: (["—", "—", "—", "—"], [0, 0, 0, 0]),
        )
    except Exception as exc:  # pragma: no cover - según entorno
        pytest.skip(f"Sin entorno gráfico para Tk: {exc}")
    try:
        _cell, label = _celda_del_hueco_uno(superficie)
        assert _texto(label) == "—", (
            "el hueco sigue mostrando el movimiento eliminado en vez de vaciarse"
        )
    finally:
        root.destroy()


def test_sin_baja_en_cola_el_movimiento_incompatible_sigue_viendose_y_en_rojo(
    entorno_tk,
) -> None:
    """Control: sin ninguna baja en cola, el hueco 1 sigue mostrando Gruñido
    y el aviso de incompatibilidad, para no confundir "ya se puede vaciar
    limpiamente" con "ocultar el aviso a secas"."""
    from app.config import DANGER

    ctk = entorno_tk
    try:
        root, superficie = _construir_vista(
            ctk,
            move_issues_for=lambda p, contexto: [{"move_slot": 1}],
            effective_moves_for=lambda p: (
                list(p.moves), list(p.move_ids),
            ),
        )
    except Exception as exc:  # pragma: no cover - según entorno
        pytest.skip(f"Sin entorno gráfico para Tk: {exc}")
    try:
        cell, label = _celda_del_hueco_uno(superficie)
        assert _texto(label) == "Gruñido"
        assert str(cell.cget("border_color")) == DANGER
    finally:
        root.destroy()


def test_sin_effective_moves_for_se_conserva_el_comportamiento_previo(
    entorno_tk,
) -> None:
    """`effective_moves_for` es opcional: otros llamantes que todavía no lo
    conectan (p.ej. pruebas antiguas o el contexto "pc") deben seguir viendo
    el movimiento crudo del Pokémon, sin romperse por el nuevo parámetro."""
    ctk = entorno_tk
    try:
        root, superficie = _construir_vista(
            ctk,
            move_issues_for=lambda p, contexto: [],
            effective_moves_for=None,
        )
    except Exception as exc:  # pragma: no cover - según entorno
        pytest.skip(f"Sin entorno gráfico para Tk: {exc}")
    try:
        _cell, label = _celda_del_hueco_uno(superficie)
        assert _texto(label) == "Gruñido"
    finally:
        root.destroy()
