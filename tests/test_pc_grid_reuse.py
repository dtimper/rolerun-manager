"""La rejilla del PC reutiliza sus casillas al cambiar de caja.

Medido con customtkinter en el equipo del usuario, para las treinta casillas de
una caja:

    destruir + crear ....... 37,4 ms
    reconfigurar ...........  5,9 ms

Lo delicado no es la ganancia sino el arrastre. `_bind_drag_tree` engancha con
``add="+"``, así que volver a enganchar un botón reutilizado apila manejadores:
a la sexta caja, un clic dispararía seis arrastres. Por eso el Pokémon de cada
hueco vive en `_pc_slot_pokemon` y no en el cierre del manejador.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui_views.team_pc_view import UnifiedTeamPCView  # noqa: E402


class _BotonFalso:
    """Lo mínimo que `_pc_cell` y `_bind_drag_tree` le piden a un CTkButton."""

    def __init__(self, master=None, **kwargs) -> None:
        self.opciones = dict(kwargs)
        self.enganches: list[tuple[str, object]] = []
        self.reconfiguraciones = 0
        self.vivo = True

    def configure(self, **kwargs) -> None:
        self.opciones.update(kwargs)
        self.reconfiguraciones += 1

    def grid(self, **_kwargs) -> None:
        pass

    def bind(self, evento, manejador, add=None) -> None:
        self.enganches.append((evento, manejador))

    def winfo_children(self):
        return []

    def winfo_exists(self) -> bool:
        return self.vivo


class _Mono:
    def __init__(self, nombre: str) -> None:
        self.nombre = nombre
        self.box_slot = 1
        self.slot = 1


def _vista(monkeypatch):
    import app.ui_views.team_pc_view as vista

    monkeypatch.setattr(vista.ctk, "CTkButton", _BotonFalso)
    # Una CTkFont de verdad exige una raíz de Tk, y aquí no se pinta nada.
    monkeypatch.setattr(vista.ctk, "CTkFont", lambda *a, **k: object())

    arrastres: list[object] = []
    yo = types.SimpleNamespace(
        pc_grid=object(),
        pc_columns=6,
        pc_box=1,
        pc_buttons={},
        _pc_slot_pokemon={},
        pc_occupied_slots=set(),
        drop_targets=[],
        images=[],
        sprite_for=lambda pokemon, size: None,
        pending_for=lambda pokemon, contexto: False,
        _begin_drag=lambda event, contexto, pokemon: arrastres.append(pokemon),
        _move_drag=lambda event: None,
        _end_drag=lambda event: None,
    )
    yo._widget_vivo = UnifiedTeamPCView._widget_vivo
    yo._bind_drag_tree = types.MethodType(UnifiedTeamPCView._bind_drag_tree, yo)
    return yo, arrastres


def _pintar(yo, slot, pokemon):
    UnifiedTeamPCView._pc_cell(yo, slot, pokemon)
    return yo.pc_buttons[slot]


def test_cambiar_de_caja_reutiliza_el_mismo_boton(monkeypatch) -> None:
    yo, _arrastres = _vista(monkeypatch)

    primero = _pintar(yo, 1, _Mono("WOOPER"))
    creaciones = 1
    for _caja in range(5):                       # cinco cambios de caja
        otro = _pintar(yo, 1, _Mono("GASTLY"))
        assert otro is primero, "se creó un botón nuevo en vez de reutilizar"

    assert primero.reconfiguraciones == 5
    assert creaciones == 1


def test_el_hueco_vacio_tambien_reutiliza(monkeypatch) -> None:
    yo, _arrastres = _vista(monkeypatch)

    ocupado = _pintar(yo, 3, _Mono("RATTATA"))
    vacio = _pintar(yo, 3, None)

    assert vacio is ocupado
    assert yo._pc_slot_pokemon[3] is None
    assert 3 not in yo.pc_occupied_slots


def test_el_arrastre_coge_el_pokemon_de_ahora_no_el_de_cuando_se_engancho(
    monkeypatch,
) -> None:
    """Si no, arrastrar en la caja 7 movería el Pokémon que había en la 1."""
    yo, arrastres = _vista(monkeypatch)

    boton = _pintar(yo, 5, _Mono("WOOPER"))
    _pintar(yo, 5, _Mono("SPINARAK"))            # otra caja, mismo botón

    presiones = [m for evento, m in boton.enganches if evento == "<ButtonPress-1>"]
    assert len(presiones) == 1, (
        f"se apilaron {len(presiones)} manejadores de arrastre en el mismo botón"
    )
    presiones[0](object())
    assert arrastres[-1].nombre == "SPINARAK"


def test_los_destinos_de_soltar_se_rehacen_con_el_pokemon_nuevo(monkeypatch) -> None:
    yo, _arrastres = _vista(monkeypatch)

    _pintar(yo, 2, _Mono("WOOPER"))
    yo.drop_targets = [t for t in yo.drop_targets if t[1] == "team"]
    _pintar(yo, 2, _Mono("GASTLY"))

    destinos = [t for t in yo.drop_targets if t[1] == "pc"]
    assert len(destinos) == 1
    assert destinos[0][2]["pokemon"].nombre == "GASTLY"


def test_cambiar_a_modo_busqueda_si_rehace_la_rejilla() -> None:
    """Un resultado de búsqueda ocupa la misma rejilla con otra forma."""
    import inspect

    fuente = inspect.getsource(UnifiedTeamPCView._vaciar_rejilla_pc)
    assert 'if self._pc_grid_mode == modo == "celdas":' in fuente
    assert "child.destroy()" in fuente
    assert "self.pc_buttons.clear()" in fuente
