"""Pulsar una tarjeta de equipo cuya identidad ya no está registrada no debe
reventar en silencio.

Reportado por el usuario 04-09-2026: tras intercambiar Ledyba (del PC) por un
Pikipek (al PC), pulsar la tarjeta de Ledyba dejó de abrir su ficha -el resto
de tarjetas seguían funcionando-. El clic de una tarjeta está enganchado una
sola vez con la identidad capturada al construirla y relee
`_team_card_pokemon` en cada pulsación (para que una tarjeta reutilizada en
sitio no quede atada al Pokémon de cuando se creó). Si esa identidad deja de
tener una entrada vigente -por ejemplo por una carrera entre el repintado
proyectado del intercambio y el confirmado por la RAM, que no se ha podido
reproducir todavía-, `_select_team(None)` acababa llamando a
`identity_for(None)`, que revienta: Tkinter solo lo imprime en consola, así
que para el usuario el clic simplemente «no hacía nada».

Este test no reproduce la carrera en sí -no se ha podido demostrar su causa
exacta sin el emulador-, pero fija el contrato de `_click_team_card`: una
identidad sin Pokémon vigente no debe llamar a `_select_team` ni levantar una
excepción.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui_state.team_pc_state import TeamPCSelectionState  # noqa: E402
from app.ui_views.team_pc_view import UnifiedTeamPCView  # noqa: E402


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
        self.moves = ["—", "—", "—", "—"]
        self.move_ids = [0, 0, 0, 0]
        self.slot = indice
        self.box_slot = indice


def _equipo() -> tuple[dict, ...]:
    roles = ("TANQUE", "APOYO", "ATACANTE", "VELOZ", "ESPECIAL", "COMODIN")
    return tuple(
        {"slot_role": roles[indice], "state": "", "pokemon": _Mono(indice + 1)}
        for indice in range(6)
    )


def _construir_vista(ctk):
    root = ctk.CTk()
    root.geometry("1360x860")
    root.update_idletasks()
    cuerpo = ctk.CTkFrame(root)
    cuerpo.pack(fill="both", expand=True)
    selecciones: list[tuple[str, object]] = []
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
        move_issues_for=lambda p, contexto: [],
        on_box_change=lambda caja: (caja, {}),
        on_search=lambda texto: [],
        on_action=lambda accion, p: None,
        on_role_info=lambda rol: None,
        on_select=lambda contexto, p: selecciones.append((contexto, p)),
    )
    root.update_idletasks()
    return root, superficie, selecciones


def test_click_con_identidad_sin_pokemon_no_revienta_ni_selecciona() -> None:
    ctk = pytest.importorskip("customtkinter")
    try:
        root, superficie, selecciones = _construir_vista(ctk)
    except Exception as exc:  # pragma: no cover - según entorno
        pytest.skip(f"Sin entorno gráfico para Tk: {exc}")
    try:
        # Una identidad que nunca estuvo (o ya no está) en `_team_card_pokemon`,
        # tal como quedaría tras la carrera reportada por el usuario.
        superficie._click_team_card("id:no-existe")
        assert selecciones == []
        assert superficie.selection.selected_identity is None
    finally:
        root.destroy()


def test_click_con_identidad_vigente_selecciona_con_normalidad() -> None:
    ctk = pytest.importorskip("customtkinter")
    try:
        root, superficie, selecciones = _construir_vista(ctk)
    except Exception as exc:  # pragma: no cover - según entorno
        pytest.skip(f"Sin entorno gráfico para Tk: {exc}")
    try:
        primero = superficie.team_slots[0]["pokemon"]
        ident = superficie.identity_for(primero)
        superficie._click_team_card(ident)
        assert selecciones == [("team", primero)]
        assert superficie.selection.selected_identity == ident
    finally:
        root.destroy()
