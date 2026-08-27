"""Los PS en vivo se actualizan sin reconstruir la página.

Medido en Windows sobre la vista real: reconstruir Equipo y PC cuesta **845 ms**
de hilo Tk y 642 widgets. Durante un combate el monitor lee cada 250-450 ms, así
que cada cambio de PS pagaba esa reconstrucción entera solo para mover unas
barras. Actualizar las seis barras cuesta **8,2 ms**: ×103.

Estas pruebas fijan dos cosas distintas:

- que la ruta incremental produce **exactamente** la misma presentación que el
  render completo (misma fracción, mismo color, mismo texto), porque una barra
  actualizada en vivo que no coincidiera con la que se dibujaría al reconstruir
  sería una mentira sobre el estado de la partida;
- que es una ruta de *aceleración*, no de decisión: ante cualquier duda cede el
  paso al render completo y no cambia lo que el usuario ve.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import DANGER, GOLD, SUCCESS  # noqa: E402
from app.save_engine_client import SavePokemon  # noqa: E402
from app.ui import TEAM_PC_PAGES, RoleRunManager  # noqa: E402
from app.ui_state.team_pc_state import (  # noqa: E402
    TeamPCSelectionState,
    build_fixed_team_slots,
)
from app.ui_views.team_pc_view import UnifiedTeamPCView  # noqa: E402

ROLES = ("Líbero", "Asesino", "Mago", "Tanque", "Prisma", "Support")


def _mon(index: int, *, hp: int = 90, box=None, box_slot=None) -> SavePokemon:
    return SavePokemon(
        slot=index, species_id=100 + index, species=f"Especie{index}",
        nickname=f"Mote{index}", level=50, held_item="Ninguno", ability="Presión",
        moves=["Placaje"], move_ids=[33], is_egg=False, markings=[False] * 6,
        role=ROLES[index % 6], role_symbol="•", box=box, box_slot=box_slot,
        pid=1000 + index, tid=1, sid=2, current_hp=hp, max_hp=120,
        stats={"hp": 120, "atk": 90, "def": 80, "spa": 70, "spd": 75, "spe": 95},
    )


def _identity(pokemon) -> str:
    return str(getattr(pokemon, "pid", 0))


# --------------------------------------------------------------------------
# Presentación: una sola fuente de verdad
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("hp", "maximo", "color"),
    [
        (120, 120, SUCCESS),
        (61, 120, SUCCESS),
        (60, 120, GOLD),
        (31, 120, GOLD),
        (30, 120, DANGER),
        (1, 120, DANGER),
    ],
)
def test_los_umbrales_de_color_son_los_mismos_para_ambos_caminos(hp, maximo, color) -> None:
    fraccion, obtenido, texto = UnifiedTeamPCView._health_presentation(hp, maximo)
    assert obtenido == color
    assert texto == f"{hp}/{maximo}"
    assert fraccion == pytest.approx(hp / maximo)


def test_sin_ps_conocidos_se_dice_que_no_estan_disponibles() -> None:
    fraccion, _color, texto = UnifiedTeamPCView._health_presentation(None, 120)
    assert texto == "No disponible"
    assert fraccion == 0.0

    fraccion, _color, texto = UnifiedTeamPCView._health_presentation(50, 0)
    assert texto == "No disponible"
    assert fraccion == 0.0


def test_los_ps_nunca_se_salen_de_la_barra() -> None:
    """Un PS mayor que el máximo no puede pintar una barra desbordada."""
    fraccion, _color, _texto = UnifiedTeamPCView._health_presentation(999, 120)
    assert fraccion == 1.0
    fraccion, _color, _texto = UnifiedTeamPCView._health_presentation(-5, 120)
    assert fraccion == 0.0


# --------------------------------------------------------------------------
# La vista real bajo Tk
# --------------------------------------------------------------------------

@pytest.fixture
def vista_real():
    """Construye la vista de verdad. Se omite si no hay entorno gráfico."""
    ctk = pytest.importorskip("customtkinter")
    try:
        root = ctk.CTk()
    except Exception as exc:  # pragma: no cover - depende del entorno
        pytest.skip(f"Sin entorno gráfico para Tk: {exc}")
    try:
        root.geometry("1360x860")
        root.update_idletasks()
        party = [_mon(index) for index in range(6)]
        pc_members = {slot: _mon(100 + slot, box=1, box_slot=slot) for slot in range(1, 31)}
        body = ctk.CTkFrame(root)
        body.pack(fill="both", expand=True)
        view = UnifiedTeamPCView(
            body,
            team_slots=build_fixed_team_slots(
                party, lambda p: getattr(p, "role", "SIN ROL"), _identity,
            ),
            pc_members=pc_members, pc_box=1, pc_box_count=24, pc_slot_count=30,
            selection=TeamPCSelectionState(),
            identity_for=_identity,
            role_for=lambda p, ctx: (getattr(p, "role", ""), "•"),
            sprite_for=lambda p, size: None, role_icon_for=lambda role, size: None,
            pending_for=lambda p, ctx: False, move_issues_for=lambda p, ctx: [],
            on_box_change=lambda box: (box, pc_members),
            on_search=lambda text: [], on_action=lambda action, p: None,
            on_role_info=lambda role: None,
        )
        root.update_idletasks()
        yield root, view, party
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_las_seis_tarjetas_exponen_su_barra_de_ps(vista_real) -> None:
    _root, view, party = vista_real
    assert view.rendered_team_identities() == frozenset(_identity(p) for p in party)


def test_actualizar_los_ps_cambia_barra_y_texto_sin_reconstruir(vista_real) -> None:
    root, view, party = vista_real
    objetivo = party[0]
    widgets = view._team_health_widgets[_identity(objetivo)]
    barra, etiqueta = widgets["bar"], widgets["label"]

    assert view.update_team_health(_identity(objetivo), 24, 120) is True
    root.update_idletasks()

    assert etiqueta.cget("text") == "PS 24/120"
    assert barra.get() == pytest.approx(0.2)
    assert barra.cget("progress_color") == DANGER
    # Los mismos widgets: no se ha reconstruido nada.
    assert view._team_health_widgets[_identity(objetivo)]["bar"] is barra


def test_la_evidencia_de_la_barrera_inicial_no_se_queda_mintiendo(vista_real) -> None:
    """La barrera publica la interfaz según lo que la vista materializó.

    Si actualizáramos los widgets sin actualizar esa evidencia, la firma diría
    que se está mostrando un PS que ya no es el que se ve.
    """
    root, view, party = vista_real
    view.update_team_health(_identity(party[0]), 7, 120)
    root.update_idletasks()

    assert (7, 120) in view.rendered_team_health_signature


def test_una_identidad_desconocida_no_se_inventa_nada(vista_real) -> None:
    _root, view, _party = vista_real
    assert view.update_team_health("identidad-que-no-existe", 50, 120) is False


def test_una_tarjeta_ya_destruida_cede_al_render_completo(vista_real) -> None:
    root, view, party = vista_real
    identidad = _identity(party[0])
    view._team_health_widgets[identidad]["bar"].destroy()
    root.update_idletasks()

    assert view.update_team_health(identidad, 50, 120) is False


# --------------------------------------------------------------------------
# El controlador: acelerar sí, decidir no
# --------------------------------------------------------------------------

class _Vista:
    def __init__(self, identidades) -> None:
        self.identidades = frozenset(identidades)
        self.actualizaciones: list[tuple[str, int | None, int]] = []
        self.fallar_en: set[str] = set()

    def rendered_team_identities(self):
        return self.identidades

    def update_team_health(self, identity, hp_value, max_hp) -> bool:
        if identity in self.fallar_en:
            return False
        self.actualizaciones.append((identity, hp_value, max_hp))
        return True


def _controlador(vista, party) -> SimpleNamespace:
    manager = SimpleNamespace(
        _team_pc_view=vista,
        _presented_team_pc_view=vista,
        active_page="team",
        _live_health_render_after_id="pendiente",
        renders=0,
        _projected_party=lambda: list(party),
        _pokemon_identity=lambda p: _identity(p),
        _floating_bar_is_visible=lambda: False,
    )
    manager._smooth_render_page = lambda **kwargs: setattr(
        manager, "renders", manager.renders + 1,
    )
    manager._apply_live_health_incrementally = lambda: (
        RoleRunManager._apply_live_health_incrementally(manager)
    )
    return manager


def test_los_ps_se_actualizan_sin_reconstruir_la_pagina() -> None:
    party = [_mon(index, hp=40) for index in range(6)]
    vista = _Vista(_identity(p) for p in party)
    manager = _controlador(vista, party)

    RoleRunManager._refresh_live_health_page(manager)

    assert manager.renders == 0, "no debía reconstruirse la página"
    assert len(vista.actualizaciones) == 6
    assert vista.actualizaciones[0] == (_identity(party[0]), 40, 120)
    assert manager._live_health_render_after_id is None


def test_si_el_equipo_ya_no_es_el_mismo_se_reconstruye() -> None:
    """Una baja o una entrada desde el PC no se arreglan moviendo barras."""
    party = [_mon(index) for index in range(6)]
    vista = _Vista(_identity(p) for p in party[:-1])  # falta uno
    manager = _controlador(vista, party)

    RoleRunManager._refresh_live_health_page(manager)

    assert manager.renders == 1
    assert vista.actualizaciones == []


def test_si_una_tarjeta_no_se_puede_actualizar_se_reconstruye() -> None:
    party = [_mon(index) for index in range(6)]
    vista = _Vista(_identity(p) for p in party)
    vista.fallar_en = {_identity(party[3])}
    manager = _controlador(vista, party)

    RoleRunManager._refresh_live_health_page(manager)

    assert manager.renders == 1


def test_una_vista_que_no_es_la_publicada_no_se_toca() -> None:
    """Durante un intercambio de body hay dos vistas vivas a la vez."""
    party = [_mon(index) for index in range(6)]
    vista = _Vista(_identity(p) for p in party)
    manager = _controlador(vista, party)
    manager._presented_team_pc_view = object()

    RoleRunManager._refresh_live_health_page(manager)

    assert manager.renders == 1
    assert vista.actualizaciones == []


def test_con_la_barra_flotante_visible_no_se_toca_la_pagina_principal() -> None:
    party = [_mon(index) for index in range(6)]
    vista = _Vista(_identity(p) for p in party)
    manager = _controlador(vista, party)
    manager._floating_bar_is_visible = lambda: True

    RoleRunManager._refresh_live_health_page(manager)

    assert manager.renders == 0
    assert vista.actualizaciones == []


def test_fuera_de_equipo_y_pc_no_se_hace_nada() -> None:
    party = [_mon(index) for index in range(6)]
    vista = _Vista(_identity(p) for p in party)
    manager = _controlador(vista, party)
    manager.active_page = "tms"

    RoleRunManager._refresh_live_health_page(manager)

    assert manager.renders == 0
    assert vista.actualizaciones == []


def test_la_ruta_incremental_cubre_las_dos_paginas_de_la_vista_unificada() -> None:
    for pagina in sorted(TEAM_PC_PAGES):
        party = [_mon(index) for index in range(6)]
        vista = _Vista(_identity(p) for p in party)
        manager = _controlador(vista, party)
        manager.active_page = pagina

        RoleRunManager._refresh_live_health_page(manager)

        assert manager.renders == 0, pagina
        assert len(vista.actualizaciones) == 6, pagina
