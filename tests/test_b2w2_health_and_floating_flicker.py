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
        avisos_obs=0,
        _floating_bar_is_visible=lambda: False,
        _refresh_live_health_page=lambda: None,
    )
    manager._schedule_obs_health_refresh = lambda: setattr(
        manager, "avisos_obs", manager.avisos_obs + 1,
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
    # 26-09-2026: la barra de vida de OBS recibe el mismo cambio.
    assert manager.avisos_obs == 1


def test_sin_cambio_de_ps_no_se_toca_absolutamente_nada() -> None:
    """Esta es la mitad que evitaba el parpadeo."""
    manager = _publisher(current_hp=120)

    assert RoleRunManager._publish_live_health(manager, _game(_mon(hp=120))) is False

    assert manager.barra_reconstruida == 0
    assert manager.refrescos_de_pagina == []
    assert manager._floating_bar_last_signature == ("firma", "vieja")
    assert manager.avisos_obs == 0


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
    rama = fuente[fuente.index("in MELONDS_REALTIME_GAME_KEYS"):]
    rama = rama[:rama.index("_schedule_oras_live_reconciliation")]
    # Desde alpha.28 entra en el camino común completo, que además de publicar
    # la salud detecta las bajas.
    assert "_process_oras_health_snapshot" in rama
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


# --------------------------------------------------------------------------
# Un fallo de la lane de presentación no puede congelar a todo el equipo
# --------------------------------------------------------------------------

def _monitor(probe) -> SimpleNamespace:
    """Lo mínimo para recorrer la rama B2/W2 del monitor."""
    publicados = []
    manager = SimpleNamespace(
        _oras_live_monitor_in_progress=True,
        _oras_live_monitor_token=5,
        _session_generation=1,
        project=SimpleNamespace(slug="run"),
        current_game=_game(_mon(hp=120)),
        _oras_live_monitor_failures=0,
        _oras_battle_probe_last_state="none",
        _oras_live_health_snapshot=None,
        _live_sync_in_progress=False,
        publicados=publicados,
        _active_azahar_realtime_key=lambda: "b2w2",
        _oras_live_reconciliation_is_active=lambda: True,
        _cancel_oras_initial_auto_sync=lambda: None,
        _discard_b2w2_ghost_team_changes=lambda: 0,
        _live_metadata_is_missing=lambda current, live: False,
        _publish_oras_live_snapshot=lambda snapshot, **kwargs: None,
        _update_top_status=lambda: None,
        _schedule_oras_live_reconciliation=lambda delay: None,
        _sync_live_layout=lambda refresh_floating=True: None,
        _schedule_team_integrity_check=lambda: None,
        _probe=probe,
        estados_de_combate=[],
        reconciliaciones=[],
    )
    manager._process_oras_battle_state = lambda state: (
        manager.estados_de_combate.append(state)
    )
    manager._process_six_mon_battle_probe = lambda probe, state: None
    manager._reconcile_pending_faints_against_party = lambda game: (
        manager.reconciliaciones.append(game)
    )
    # 06-09-2026: la reconciliación pasiva de quinta ajusta además la tabla de
    # aprendizajes por rol dentro de la RAM de melonDS.
    manager._sync_gen5_levelup_moves = lambda game: None

    def procesar(game, *, source="overworld"):
        publicados.append((game, source))
        manager._oras_live_health_snapshot = game

    manager._process_oras_health_snapshot = procesar
    return manager


def _run_monitor(manager, snapshot) -> None:
    RoleRunManager._finish_oras_live_reconciliation(
        manager, 1, "run", 5, None, snapshot, None, battle_probe=manager._probe,
    )


def test_una_lane_de_batalla_no_validada_ya_no_congela_al_equipo() -> None:
    """El caso real de la captura del 27-08-2026.

    Con Mareep debilitado (0/22) y Azurill a 4/20, la barra flotante pintaba a
    los seis al máximo durante todo el combate. La lane de presentación gobierna
    solo los PS del Pokémon **activo**; los otros cinco salen del bloque de party
    incluso en un combate confirmado, así que no hay nada que destripar en ellos.
    """
    manager = _monitor(SimpleNamespace(state="unknown", health_game=None))
    vivo = _game(_mon(hp=0))

    _run_monitor(manager, SimpleNamespace(game=vivo))

    assert manager.publicados == [(vivo, "overworld")], "debía publicarse el bloque de party"
    assert manager._oras_live_health_snapshot is vivo
    # Seguimos sin saber si esto es un combate: no se afirma lo contrario.
    assert manager._oras_battle_probe_last_state == "none"


def test_un_combate_confirmado_sigue_usando_la_copia_de_presentacion() -> None:
    """La regla validada en alpha.5 no se relaja: nada de adelantar el daño."""
    presentacion = _game(_mon(hp=90))
    manager = _monitor(SimpleNamespace(state="battle", health_game=presentacion))
    vivo = _game(_mon(hp=10))

    _run_monitor(manager, SimpleNamespace(game=vivo))

    # "battle-visible": la copia de presentación ya converge con la animación,
    # así que el KO se registra sin el retraso extra que ORAS necesita.
    assert manager.publicados == [(presentacion, "battle-visible")]
    assert manager._oras_live_health_snapshot is presentacion
    assert manager._oras_battle_probe_last_state == "battle"


def test_fuera_de_combate_manda_el_bloque_de_party() -> None:
    manager = _monitor(SimpleNamespace(state="none", health_game=None))
    vivo = _game(_mon(hp=45))

    _run_monitor(manager, SimpleNamespace(game=vivo))

    assert manager.publicados == [(vivo, "overworld")]
    assert manager._oras_battle_probe_last_state == "none"
