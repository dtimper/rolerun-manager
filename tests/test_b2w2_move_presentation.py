"""Lo que la interfaz enseña de cada movimiento en B2/W2.

Dos fallos reportados por el usuario el 27-08-2026, con captura:

1. Las tarjetas de drafteo salían con «Pot. — · Prec. — · PP —» y sin
   descripción. `_draft_move_metadata` no tenía rama para B2/W2, así que no
   había de dónde sacar los números.

2. Un Support con cuatro ataques de daño no ponía ninguno en dorado ni ofrecía
   elegir cuáles quitar. La tarjeta antigua sí lo hacía; la vista compacta de
   «Equipo y PC» solo conocía las incompatibilidades rojas.

La potencia y la precisión salen de la ROM: son los valores de quinta —que no
son los de sexta— y, en una partida randomizada, los de esa partida.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import customtkinter  # noqa: F401
except ModuleNotFoundError:                                  # pragma: no cover
    customtkinter = types.ModuleType("customtkinter")
    customtkinter.CTk = object
    sys.modules["customtkinter"] = customtkinter

from app.ui import RoleRunManager  # noqa: E402
from app.ui_views.team_pc_view import _support_damage_map  # noqa: E402

LANZALLAMAS = 53
TERREMOTO = 89


class _Rom:
    name = "negra2.nds"

    def base_pp(self, move_id):
        return {LANZALLAMAS: 15, TERREMOTO: 10}.get(int(move_id), 0)

    def power(self, move_id):
        return {LANZALLAMAS: 95, TERREMOTO: 100}.get(int(move_id), 0)

    def accuracy(self, move_id):
        return {LANZALLAMAS: 100, TERREMOTO: 100}.get(int(move_id), 0)

    def damage_class(self, move_id):
        return "special" if int(move_id) == LANZALLAMAS else "physical"

    def type_id(self, move_id):
        return {LANZALLAMAS: 9, TERREMOTO: 4}.get(int(move_id))


def _manager(rom=None, descripciones=None):
    return SimpleNamespace(
        save_engine=SimpleNamespace(key="b2w2"),
        _get_b2w2_rom_profile=lambda: rom,
        _get_bdsp_tm_profile=lambda prompt=False: None,
        oras_move_metadata=dict(descripciones or {}),
        b2w2_realtime_adapter=SimpleNamespace(base_pp_for=lambda mid: 15),
        engine=SimpleNamespace(damage_class=lambda mid: "special"),
        _damage_class_for_move=lambda mid: "special",
    )


# --------------------------------------------------------------------------
# La tarjeta de drafteo
# --------------------------------------------------------------------------

def test_la_tarjeta_muestra_los_numeros_de_la_rom() -> None:
    """Es el fallo de la captura: salía todo con guiones."""
    datos = RoleRunManager._draft_move_metadata(_manager(rom=_Rom()), LANZALLAMAS)

    assert datos["power"] == 95
    assert datos["accuracy"] == 100
    assert datos["pp"] == 15


def test_la_potencia_es_la_de_quinta_no_la_de_sexta() -> None:
    """Lanzallamas pasó de 95 a 90 en sexta generación."""
    datos = RoleRunManager._draft_move_metadata(_manager(rom=_Rom()), LANZALLAMAS)

    assert datos["power"] == 95, "90 sería el valor de sexta"


def test_la_descripcion_sale_del_catalogo_en_espanol() -> None:
    """El texto no depende de la randomización: describe el movimiento, no la MT."""
    manager = _manager(
        rom=_Rom(),
        descripciones={LANZALLAMAS: {"description_es": "Lanza una llamarada."}},
    )

    datos = RoleRunManager._draft_move_metadata(manager, LANZALLAMAS)

    assert datos["description"] == "Lanza una llamarada."


def test_sin_rom_no_se_inventa_una_potencia() -> None:
    """Mejor un guion que el número de otra generación.

    Los PP sí se conservan: la tabla de quinta ya está demostrada y el
    adaptador la sirve.
    """
    datos = RoleRunManager._draft_move_metadata(_manager(rom=None), LANZALLAMAS)

    assert datos["power"] == "—"
    assert datos["accuracy"] == "—"
    assert datos["pp"] == 15


def test_un_movimiento_que_no_existe_no_da_numeros() -> None:
    datos = RoleRunManager._draft_move_metadata(_manager(rom=_Rom()), 0)

    assert datos["power"] == "—" and datos["pp"] == "—"


def test_una_potencia_de_cero_se_muestra_como_guion() -> None:
    """Un movimiento de estado no tiene potencia que enseñar."""
    datos = RoleRunManager._draft_move_metadata(_manager(rom=_Rom()), 999)

    assert datos["power"] == "—"


# --------------------------------------------------------------------------
# El Support con ataques de sobra
# --------------------------------------------------------------------------

def _support(excess: int, huecos: tuple[int, ...]):
    return lambda pokemon, role: (
        excess, [{"move_slot": hueco} for hueco in huecos],
    )


def test_un_support_con_cuatro_ataques_marca_los_cuatro() -> None:
    """Ninguno es ilegal por sí solo: se marcan todos para que el usuario elija."""
    excess, slots = _support_damage_map(
        object(), "Support", _support(2, (1, 2, 3, 4)),
    )

    assert excess == 2
    assert slots == {1, 2, 3, 4}


def test_un_support_con_dos_ataques_no_marca_nada() -> None:
    excess, slots = _support_damage_map(object(), "Support", _support(0, (1, 2)))

    assert (excess, slots) == (0, set())


def test_un_pokemon_del_pc_no_se_marca() -> None:
    """Un Pokémon del PC no tiene rol activo, así que no hay nada que elegir."""
    excess, slots = _support_damage_map(
        object(), "Support", _support(2, (1, 2, 3, 4)), context="pc",
    )

    assert (excess, slots) == (0, set())


def test_sin_la_regla_conectada_la_vista_no_inventa_nada() -> None:
    assert _support_damage_map(object(), "Support", None) == (0, set())


def test_los_huecos_fuera_de_rango_se_descartan() -> None:
    excess, slots = _support_damage_map(
        object(), "Support", _support(1, (0, 2, 9)),
    )

    assert slots == {2}


def test_la_vista_recibe_la_regla_y_la_accion() -> None:
    """El fallo era ese: la vista compacta no las tenía conectadas."""
    import inspect

    fuente = inspect.getsource(RoleRunManager)
    assert "support_damage_for=self._support_damage_excess" in fuente
    assert "on_support_damage=self._open_support_damage_removal_selector" in fuente


def test_la_vista_acepta_los_dos_parametros() -> None:
    import inspect

    from app.ui_views.team_pc_view import UnifiedTeamPCView

    firma = inspect.signature(UnifiedTeamPCView.__init__).parameters
    assert "support_damage_for" in firma
    assert "on_support_damage" in firma


# --------------------------------------------------------------------------
# Las acciones sobre un ataque que sobra
# --------------------------------------------------------------------------

def test_eliminar_atiende_tambien_al_exceso_de_support() -> None:
    """`delete_move` solo miraba las incompatibilidades y no hacía nada.

    Un ataque que sobra en un Support no es «incompatible» —el límite de dos es
    de conjunto, así que ninguno lo incumple por sí solo—, pero el usuario
    tiene que poder quitarlo por la misma vía que cualquier otro.
    """
    candidato = {"pokemon": object(), "role": "Support", "move_slot": 3,
                 "move_name": "Ascuas", "move_id": LANZALLAMAS}
    encolados: list[list[dict]] = []
    manager = SimpleNamespace(
        _effective_role=lambda p: ("Support", "◆"),
        _collect_pokemon_move_issues=lambda p, r: [],
        _support_damage_excess=lambda p, r: (2, [candidato]),
        _queue_invalid_move_removals=lambda issues: encolados.append(issues),
    )

    RoleRunManager._team_pc_action(manager, "delete_move:3", object())

    assert encolados == [[candidato]]


def test_una_incompatibilidad_real_sigue_teniendo_prioridad() -> None:
    """Si el movimiento es incompatible, manda esa razón y no la del Support."""
    incompatible = {"pokemon": object(), "role": "Mago", "move_slot": 3,
                    "move_name": "Ascuas", "move_id": LANZALLAMAS}
    encolados: list[list[dict]] = []
    manager = SimpleNamespace(
        _effective_role=lambda p: ("Mago", "♥"),
        _collect_pokemon_move_issues=lambda p, r: [incompatible],
        _support_damage_excess=lambda p, r: pytest.fail("no debe consultarse"),
        _queue_invalid_move_removals=lambda issues: encolados.append(issues),
    )

    RoleRunManager._team_pc_action(manager, "delete_move:3", object())

    assert encolados == [[incompatible]]


def test_un_hueco_sin_motivo_no_encola_nada() -> None:
    encolados: list[list[dict]] = []
    manager = SimpleNamespace(
        _effective_role=lambda p: ("Support", "◆"),
        _collect_pokemon_move_issues=lambda p, r: [],
        _support_damage_excess=lambda p, r: (0, []),
        _queue_invalid_move_removals=lambda issues: encolados.append(issues),
    )

    RoleRunManager._team_pc_action(manager, "delete_move:1", object())

    assert encolados == []


def test_la_celda_con_botones_no_lleva_altura_fija() -> None:
    """Fijarle 54 píxeles recortaba el marco de abajo: es el fallo reportado."""
    import inspect

    from app.ui_views import team_pc_view

    fuente = inspect.getsource(team_pc_view)
    assert "cell.grid_propagate(not accionable)" in fuente
    assert "height=54 if" not in fuente


def test_la_tarjeta_deja_sitio_para_el_marco_de_la_fila_de_ataques() -> None:
    """El marco inferior cortado no era un problema de dibujo, sino de sitio.

    Medido el 27-08-2026: la tarjeta deja 92 píxeles útiles y el contenido
    pedía 95, así que Tk recortaba tres — exactamente el borde de abajo de la
    fila de ataques, que es la última. El hueco sale del bloque de
    estadísticas, que iba sobrado, y no de apretar más la fila.

    Esta prueba fija los números, no el resultado visual: si alguien vuelve a
    subir la altura del bloque o los márgenes, el recorte reaparece.
    """
    import inspect

    from app.ui_views import team_pc_view

    fuente = inspect.getsource(team_pc_view)
    assert "content, width=265, height=64" in fuente, "el bloque de estadísticas creció"
    assert 'move_grid.grid(row=3, column=1, columnspan=2, sticky="ew", pady=(2, 0))' in fuente
    assert 'move_cell.grid(row=0, column=index, sticky="ew", padx=2, pady=(1, 1))' in fuente
