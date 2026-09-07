"""La ficha enseña el tipo de cada movimiento y deja consultar el resto.

Pedido del usuario el 02-09-2026: un marco del color del tipo alrededor de
cada movimiento, su nombre en una esquina, y un clic que abra su categoría,
potencia, precisión, PP y descripción. El tipo nunca sale de una tabla
estática -ver [[rolerun-randomizers]]-, sino de lo mismo que ya sirve
potencia/precisión/PP: `move_metadata_for`, que el controlador conecta a
`RoleRunManager._draft_move_metadata`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import DANGER, MOVE_TYPE_INFO  # noqa: E402
from app.ui_state.team_pc_state import TeamPCSelectionState  # noqa: E402
from app.ui_views.team_pc_view import UnifiedTeamPCView  # noqa: E402

ROLES = ("TANQUE", "APOYO", "ATACANTE", "VELOZ", "ESPECIAL", "COMODIN")
LANZALLAMAS_ID = 53
FUEGO_NOMBRE, FUEGO_COLOR = MOVE_TYPE_INFO[9]


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
        self.moves = ["Lanzallamas", "—", "—", "—"]
        self.move_ids = [LANZALLAMAS_ID, 0, 0, 0]
        self.slot = indice
        self.box_slot = indice


def _equipo() -> tuple[dict, ...]:
    return tuple(
        {"slot_role": ROLES[indice], "state": "", "pokemon": _Mono(indice + 1)}
        for indice in range(6)
    )


def _metadata_para(move_id: int) -> dict[str, object]:
    assert move_id == LANZALLAMAS_ID, "no debe consultarse un hueco vacío"
    return {
        "category": "special", "power": 95, "accuracy": 100, "pp": 15,
        "type_id": 9, "description": "Una gran ráfaga de fuego.",
    }


def _construir_vista(ctk, move_issues_for):
    root = ctk.CTk()
    root.geometry("1360x860")
    root.update_idletasks()
    cuerpo = ctk.CTkFrame(root)
    cuerpo.pack(fill="both", expand=True)
    consultas = []
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
        on_box_change=lambda caja: (caja, {}),
        on_search=lambda texto: [],
        on_action=lambda accion, p: None,
        on_role_info=lambda rol: None,
        move_metadata_for=_metadata_para,
        on_move_info=lambda move_id, nombre: consultas.append((move_id, nombre)),
    )
    root.update_idletasks()
    superficie._select_team(superficie.team_slots[0]["pokemon"])
    root.update_idletasks()
    return root, superficie, consultas


@pytest.fixture
def vista():
    ctk = pytest.importorskip("customtkinter")
    try:
        root, superficie, consultas = _construir_vista(ctk, lambda p, contexto: [])
    except Exception as exc:                   # pragma: no cover - según entorno
        pytest.skip(f"Sin entorno gráfico para Tk: {exc}")
    try:
        yield root, superficie, consultas
    finally:
        try:
            root.destroy()
        except Exception:
            pass


@pytest.fixture
def vista_con_movimiento_incompatible():
    """Igual que `vista`, pero Lanzallamas (hueco 1) es incompatible con el rol."""
    ctk = pytest.importorskip("customtkinter")
    try:
        root, superficie, consultas = _construir_vista(
            ctk, lambda p, contexto: [{"move_slot": 1}],
        )
    except Exception as exc:                   # pragma: no cover - según entorno
        pytest.skip(f"Sin entorno gráfico para Tk: {exc}")
    try:
        yield root, superficie, consultas
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def _texto(widget) -> str:
    try:
        return str(widget.cget("text"))
    except Exception:
        return ""


def _celda_de_lanzallamas(superficie):
    move_grid = None
    for frame in superficie.inspector_panel.winfo_children():
        for child in frame.winfo_children():
            texto = _texto(child)
            if texto == "MOVIMIENTOS":
                move_grid = frame.winfo_children()[frame.winfo_children().index(child) + 1]
    assert move_grid is not None, "no se encontró la rejilla de movimientos"
    for cell in move_grid.winfo_children():
        for child in cell.winfo_children():
            if _texto(child) == "Lanzallamas":
                return cell, child
    raise AssertionError("no se encontró la celda de Lanzallamas")


def test_la_celda_lleva_el_marco_del_color_de_su_tipo(vista) -> None:
    _root, superficie, _consultas = vista

    cell, _label = _celda_de_lanzallamas(superficie)

    assert str(cell.cget("border_color")) == FUEGO_COLOR


def test_el_interior_de_la_celda_tambien_se_tine_del_tipo(vista) -> None:
    """Pedido del usuario el 02-09-2026: por dentro, distinguiéndose del
    borde, no solo el marco."""
    from app.config import PANEL_ALT, move_type_fill

    _root, superficie, _consultas = vista

    cell, _label = _celda_de_lanzallamas(superficie)
    relleno_esperado = move_type_fill(FUEGO_COLOR, PANEL_ALT)

    assert str(cell.cget("fg_color")) == relleno_esperado
    assert relleno_esperado != FUEGO_COLOR


def test_la_celda_lleva_el_nombre_del_tipo_en_una_esquina(vista) -> None:
    _root, superficie, _consultas = vista

    cell, _label = _celda_de_lanzallamas(superficie)
    etiquetas = [_texto(child) for child in cell.winfo_children()]

    assert FUEGO_NOMBRE in etiquetas


def test_pulsar_el_movimiento_abre_su_ficha(vista) -> None:
    """La ficha vive en `inspector_panel`, sin `overrideredirect` ni topmost.

    Un clic real ahí solo se demuestra con el truco de
    ``test_avisos_persistentes_y_clic_perdido`` (mover el cursor de verdad con
    `user32` y esperar a que la ventana quede mapeada) — en esta batería el
    widget nunca llega a `winfo_ismapped()` porque no hay sesión de escritorio
    interactiva. Se comprueba en su lugar, como ya hace
    `test_la_vista_recibe_la_regla_y_la_accion` en
    `test_b2w2_move_presentation.py`, que el enganche está en el código.
    """
    import inspect

    from app.ui_views import team_pc_view

    _root, superficie, _consultas = vista
    fuente = inspect.getsource(team_pc_view)
    assert 'cell.bind("<Button-1>", abrir_ficha, add="+")' in fuente
    assert 'move_label.bind("<Button-1>", abrir_ficha, add="+")' in fuente
    assert "self.on_move_info(mid, name)" in fuente

    _cell, label = _celda_de_lanzallamas(superficie)
    assert label.cget("text") == "Lanzallamas"


def test_un_hueco_vacio_no_lleva_marco_de_tipo_ni_es_clicable(vista) -> None:
    _root, superficie, consultas = vista

    move_grid = None
    for frame in superficie.inspector_panel.winfo_children():
        for child in frame.winfo_children():
            if _texto(child) == "MOVIMIENTOS":
                move_grid = frame.winfo_children()[frame.winfo_children().index(child) + 1]
    hueco = move_grid.winfo_children()[1]
    for child in hueco.winfo_children():
        if _texto(child) == "—":
            child._label.event_generate("<Button-1>", x=1, y=1)

    assert str(hueco.cget("border_width")) == "0"
    assert consultas == []


def _icono_de_aviso(cell):
    for child in cell.winfo_children():
        if _texto(child) == "i":
            return child
    return None


def test_un_movimiento_incompatible_lleva_el_circulo_de_aviso(
    vista_con_movimiento_incompatible,
) -> None:
    """Pedido del usuario el 02-09-2026: un «i» rojo, arriba a la izquierda."""
    _root, superficie, _consultas = vista_con_movimiento_incompatible

    cell, _label = _celda_de_lanzallamas(superficie)
    icono = _icono_de_aviso(cell)

    assert icono is not None, "el movimiento incompatible no lleva el círculo de aviso"
    assert str(icono.cget("fg_color")) == DANGER


def test_un_movimiento_compatible_no_lleva_circulo_de_aviso(vista) -> None:
    _root, superficie, _consultas = vista

    cell, _label = _celda_de_lanzallamas(superficie)

    assert _icono_de_aviso(cell) is None


def test_el_aviso_explica_la_incompatibilidad_al_pasar_el_raton(
    vista_con_movimiento_incompatible,
) -> None:
    """El hover real no se puede simular en este entorno sin sesión de
    escritorio (mismo hallazgo que con el clic de abrir la ficha, ver
    `test_pulsar_el_movimiento_abre_su_ficha`): se comprueba el enganche y el
    texto en el código en vez de disparar `<Enter>`/`<Leave>` de verdad.
    """
    import inspect

    from app.ui_views import team_pc_view

    fuente = inspect.getsource(team_pc_view)
    assert "self._show_move_issue_tooltip(boton)" in fuente
    assert "self._hide_move_issue_tooltip()" in fuente
    assert "Movimiento incompatible con el rol de este Pokémon" in fuente
