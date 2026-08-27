"""Dos fallos reportados el 27-08-2026, con una única causa raíz.

1. La barra flotante parpadeaba **una vez por segundo**, desde hacía muchas
   versiones.
2. Un Mareep perdió vida en Negro 2 y RoleRun no lo reflejaba en ninguna parte.

Ambos nacían de la rama B2/W2 del monitor. Era el único backend que **no**
publicaba la salud viva por el camino común, y a cambio forzaba en cada ciclo
—cada 950 ms— una reconstrucción completa de la barra flotante aunque no hubiera
cambiado absolutamente nada.

Es decir: hacía justo lo contrario de lo que hacía falta. Reconstruía cuando no
había novedad y no publicaba cuando sí la había, porque ``diff_live_party``
ignora los PS a propósito —su trabajo es la composición del equipo, no la vida—.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import DANGER, GOLD, SUCCESS  # noqa: E402
from app.save_engine_client import SaveGameData, SavePokemon  # noqa: E402
from app.ui import RoleRunManager  # noqa: E402


def _mon(*, hp: int, max_hp: int = 120, pid: int = 777) -> SavePokemon:
    return SavePokemon(
        slot=0, species_id=179, species="Mareep", nickname="Mareep", level=20,
        held_item="Ninguno", ability="Estática", moves=["Impactrueno"],
        move_ids=[84], is_egg=False, markings=[False] * 6, role="Mago",
        role_symbol="•", pid=pid, tid=1, sid=2,
        current_hp=hp, max_hp=max_hp,
    )


def _game(pokemon) -> SaveGameData:
    return SaveGameData("B2W2", "SAV5B2W2", 5, "Diego", [pokemon], {})


# --------------------------------------------------------------------------
# La salud vive ahora en un camino común
# --------------------------------------------------------------------------

def _publisher(current_hp: int) -> SimpleNamespace:
    manager = SimpleNamespace(
        current_game=_game(_mon(hp=current_hp)),
        active_page="team",
        _live_health_render_after_id=None,
        _floating_bar_last_signature=("firma", "vieja"),
        _main_ui_dirty_while_floating=False,
        barra_reconstruida=0,
        refrescos_de_pagina=[],
        _floating_bar_is_visible=lambda: False,
        _refresh_live_health_page=lambda: None,
    )
    manager._render_floating_bar = lambda force=False: setattr(
        manager, "barra_reconstruida", manager.barra_reconstruida + 1,
    )
    manager.after = lambda delay, callback: (
        manager.refrescos_de_pagina.append(delay) or "timer"
    )
    return manager


def test_un_cambio_real_de_ps_llega_a_la_partida_y_a_la_vista() -> None:
    manager = _publisher(current_hp=120)

    assert RoleRunManager._publish_live_health(manager, _game(_mon(hp=45))) is True

    assert manager.current_game.party[0].current_hp == 45
    assert manager.refrescos_de_pagina == [90]
    assert manager._live_health_render_after_id == "timer"


def test_sin_cambio_de_ps_no_se_toca_absolutamente_nada() -> None:
    """Esta es la mitad que evitaba el parpadeo."""
    manager = _publisher(current_hp=120)

    assert RoleRunManager._publish_live_health(manager, _game(_mon(hp=120))) is False

    assert manager.barra_reconstruida == 0
    assert manager.refrescos_de_pagina == []
    assert manager._floating_bar_last_signature == ("firma", "vieja")


def test_con_la_barra_flotante_visible_se_refresca_ella_y_no_la_pagina() -> None:
    manager = _publisher(current_hp=120)
    manager._floating_bar_is_visible = lambda: True

    assert RoleRunManager._publish_live_health(manager, _game(_mon(hp=45))) is True

    assert manager.barra_reconstruida == 1
    assert manager.refrescos_de_pagina == []
    assert manager._main_ui_dirty_while_floating is True


def test_la_rama_b2w2_del_monitor_publica_la_salud() -> None:
    """Era el único backend que no lo hacía.

    ``diff_live_party`` ignora los PS, así que un cambio de vida dejaba
    ``difference.changed`` en falso y la salud no llegaba nunca ni a
    ``current_game`` ni a la barra flotante.
    """
    import inspect

    fuente = inspect.getsource(RoleRunManager._finish_oras_live_reconciliation)
    rama = fuente[fuente.index('== "b2w2"'):]
    rama = rama[:rama.index("_schedule_oras_live_reconciliation")]
    assert "_publish_live_health" in rama
    # Y ya no fuerza la reconstrucción de la barra cuando nada cambió.
    assert "_sync_live_layout(refresh_floating=False)" in rama
    assert "_sync_live_layout(refresh_floating=True)" not in rama


# --------------------------------------------------------------------------
# La barra flotante deja de reconstruirse por un cambio de PS
# --------------------------------------------------------------------------

class _Barra:
    def __init__(self, fraction: float) -> None:
        self.fraction = fraction
        self.color: str | None = None
        self.viva = True

    def winfo_exists(self) -> bool:
        return self.viva

    def configure(self, **kwargs) -> None:
        if "progress_color" in kwargs:
            self.color = kwargs["progress_color"]

    def set(self, value: float) -> None:
        self.fraction = value


def _rol(role_key="mago", identity="mareep", hidden=False, sprite=True,
         hp=120, max_hp=120, status=0):
    return (role_key, identity, hidden, sprite, hp, max_hp, status)


def _bar_manager(*, previa, barra=None, has_status=False) -> SimpleNamespace:
    manager = SimpleNamespace(
        _floating_bar_last_signature=previa,
        _floating_health_widgets={"mago": {"bar": barra, "has_status": has_status}},
    )
    manager._floating_status_style = lambda value: (
        RoleRunManager._floating_status_style(value)
    )
    return manager


def test_solo_cambian_los_ps_y_la_barra_se_actualiza_en_su_sitio() -> None:
    barra = _Barra(1.0)
    manager = _bar_manager(previa=((3, 0, 0, 0), (_rol(hp=120),)), barra=barra)

    aplicado = RoleRunManager._update_floating_bar_health_in_place(
        manager, ((3, 0, 0, 0), (_rol(hp=24),)),
    )

    assert aplicado is True
    assert barra.fraction == pytest.approx(0.2)
    assert barra.color == DANGER


@pytest.mark.parametrize(
    ("hp", "color"), [(120, SUCCESS), (60, GOLD), (30, DANGER)],
)
def test_el_color_sigue_los_mismos_umbrales_que_al_reconstruir(hp, color) -> None:
    barra = _Barra(1.0)
    manager = _bar_manager(previa=((0, 0, 0, 0), (_rol(hp=119),)), barra=barra)

    RoleRunManager._update_floating_bar_health_in_place(
        manager, ((0, 0, 0, 0), (_rol(hp=hp),)),
    )

    assert barra.color == color


def test_cambiar_de_pokemon_obliga_a_reconstruir() -> None:
    barra = _Barra(1.0)
    manager = _bar_manager(previa=((0, 0, 0, 0), (_rol(identity="mareep"),)), barra=barra)

    aplicado = RoleRunManager._update_floating_bar_health_in_place(
        manager, ((0, 0, 0, 0), (_rol(identity="flaaffy"),)),
    )

    assert aplicado is False


def test_cambiar_un_contador_obliga_a_reconstruir() -> None:
    manager = _bar_manager(previa=((3, 0, 0, 0), (_rol(),)), barra=_Barra(1.0))

    assert RoleRunManager._update_floating_bar_health_in_place(
        manager, ((2, 0, 0, 0), (_rol(),)),
    ) is False


def test_debilitarse_obliga_a_reconstruir() -> None:
    """Al 0 % la casilla no tiene barra sino un carril neutro."""
    barra = _Barra(0.5)
    manager = _bar_manager(previa=((0, 0, 0, 0), (_rol(hp=60),)), barra=barra)

    assert RoleRunManager._update_floating_bar_health_in_place(
        manager, ((0, 0, 0, 0), (_rol(hp=0),)),
    ) is False


def test_un_estado_que_aparece_obliga_a_reconstruir() -> None:
    """Envenenarse añade una etiqueta que no existía."""
    barra = _Barra(1.0)
    manager = _bar_manager(previa=((0, 0, 0, 0), (_rol(status=0),)), barra=barra)

    assert RoleRunManager._update_floating_bar_health_in_place(
        manager, ((0, 0, 0, 0), (_rol(hp=100, status=8),)),
    ) is False


def test_sin_firma_previa_se_reconstruye() -> None:
    manager = _bar_manager(previa=None, barra=_Barra(1.0))

    assert RoleRunManager._update_floating_bar_health_in_place(
        manager, ((0, 0, 0, 0), (_rol(),)),
    ) is False


def test_una_barra_ya_destruida_cede_a_la_reconstruccion() -> None:
    barra = _Barra(1.0)
    barra.viva = False
    manager = _bar_manager(previa=((0, 0, 0, 0), (_rol(hp=120),)), barra=barra)

    assert RoleRunManager._update_floating_bar_health_in_place(
        manager, ((0, 0, 0, 0), (_rol(hp=60),)),
    ) is False


def test_una_firma_identica_no_hace_ningun_trabajo() -> None:
    barra = _Barra(1.0)
    manager = _bar_manager(previa=((0, 0, 0, 0), (_rol(hp=120),)), barra=barra)

    assert RoleRunManager._update_floating_bar_health_in_place(
        manager, ((0, 0, 0, 0), (_rol(hp=120),)),
    ) is True
    assert barra.color is None, "no debía tocarse ninguna barra"
