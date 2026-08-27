"""El seguimiento del PC vivo debe funcionar en la página que el usuario usa.

Fallo físico del 27-08-2026 en Negro 2/melonDS: el usuario movió un Azurill al
slot 7 del PC desde RoleRun, lo movió al slot 2 **dentro del juego**, y RoleRun
siguió mostrándolo en el 7. Al retirarlo al equipo desde esa vista desfasada,
apareció duplicado.

Causa raíz: `_bdsp_pc_poll_is_active` exige `active_page == "pc"`, pero desde que
Equipo y PC se unificaron en una sola vista **ninguna ruta de navegación produce
ese valor**. La barra principal solo ofrece `("team", "♟ EQUIPO Y PC")` y
`_render_context_navigation` oculta los controles secundarios justamente para
`{"team", "pc"}`, así que no hay ningún botón que lleve a `"pc"`. El sondeo del
PC vivo y el refresco al entrar en la vista quedaron inalcanzables para B2/W2 y
BDSP: RoleRun no volvía a mirar el PC del juego nunca.

El resto del archivo ya se había actualizado a la vista unificada y comprueba
`in {"team", "pc"}` en diez sitios; estos tres se quedaron atrás.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui import PRIMARY_NAVIGATION, TEAM_PC_PAGES, RoleRunManager  # noqa: E402
from app.ui_state.navigation import (  # noqa: E402
    SECONDARY_GROUPS,
    normalize_navigation_target,
)


def _poll_manager(*, active_page: str, live_key: str = "b2w2") -> SimpleNamespace:
    manager = SimpleNamespace(
        active_page=active_page,
        _oras_live_active=True,
        current_game=object(),
        _session_generation=3,
        _oras_pc_reconcile_in_progress=False,
        _bdsp_pc_poll_after_id=None,
        armados=[],
        reconciliaciones=[],
        _active_azahar_realtime_key=lambda: live_key,
        _floating_bar_is_visible=lambda: False,
        _record_bdsp_ui_event=lambda *args, **kwargs: None,
    )
    manager.after = lambda delay, callback: (
        manager.armados.append((delay, callback)) or f"timer-{len(manager.armados)}"
    )
    manager.after_cancel = lambda _after_id: None
    manager._schedule_oras_external_pc_reconcile = (
        lambda before, after, force=False: manager.reconciliaciones.append(force)
    )
    manager._cancel_bdsp_pc_poll = lambda: RoleRunManager._cancel_bdsp_pc_poll(manager)
    manager._bdsp_pc_poll_is_active = lambda: RoleRunManager._bdsp_pc_poll_is_active(manager)
    manager._schedule_bdsp_pc_poll = lambda delay=2500: RoleRunManager._schedule_bdsp_pc_poll(
        manager, delay,
    )
    return manager


# --------------------------------------------------------------------------
# La página "pc" no existe para el usuario
# --------------------------------------------------------------------------

def test_ninguna_ruta_de_navegacion_lleva_a_la_pagina_pc() -> None:
    """Si nadie puede llegar a "pc", nada puede depender de estar en "pc"."""
    destinos_de_la_barra = {key for key, _label in PRIMARY_NAVIGATION}
    assert "pc" not in destinos_de_la_barra
    assert "team" in destinos_de_la_barra

    # ``normalize_navigation_target`` admite "pc" como destino secundario, pero
    # los controles secundarios están ocultos precisamente en esta vista.
    assert "pc" in SECONDARY_GROUPS["team"]
    assert normalize_navigation_target("team") == "team"


def test_la_vista_unificada_se_declara_en_un_solo_sitio() -> None:
    assert TEAM_PC_PAGES == {"team", "pc"}


# --------------------------------------------------------------------------
# El sondeo del PC vivo
# --------------------------------------------------------------------------

@pytest.mark.parametrize("live_key", ["b2w2", "bdsp"])
def test_el_sondeo_esta_activo_en_la_pagina_real_del_usuario(live_key: str) -> None:
    manager = _poll_manager(active_page="team", live_key=live_key)
    assert RoleRunManager._bdsp_pc_poll_is_active(manager) is True


@pytest.mark.parametrize("live_key", ["b2w2", "bdsp"])
def test_el_sondeo_se_arma_desde_la_pagina_real_del_usuario(live_key: str) -> None:
    manager = _poll_manager(active_page="team", live_key=live_key)

    RoleRunManager._schedule_bdsp_pc_poll(manager, 200)

    assert manager._bdsp_pc_poll_after_id == "timer-1"
    # Ejecutar el tick debe pedir una reconciliación forzada del PC vivo.
    _delay, callback = manager.armados[0]
    callback()
    assert manager.reconciliaciones == [True]


def test_el_sondeo_sigue_valiendo_para_la_pagina_pc_historica() -> None:
    """Una sesión restaurada podría conservar "pc" como página activa."""
    manager = _poll_manager(active_page="pc")
    assert RoleRunManager._bdsp_pc_poll_is_active(manager) is True


def test_el_sondeo_no_corre_fuera_de_equipo_y_pc() -> None:
    for pagina in ("tms", "drafts", "settings", "help", "moves", "history"):
        manager = _poll_manager(active_page=pagina)
        assert RoleRunManager._bdsp_pc_poll_is_active(manager) is False, pagina


def test_el_sondeo_sigue_reservado_a_los_backends_con_matriz_viva() -> None:
    for live_key in ("oras", "xy", "sm", "usum"):
        manager = _poll_manager(active_page="team", live_key=live_key)
        assert RoleRunManager._bdsp_pc_poll_is_active(manager) is False, live_key


def test_la_barra_flotante_sigue_deteniendo_el_sondeo() -> None:
    manager = _poll_manager(active_page="team")
    manager._floating_bar_is_visible = lambda: True
    assert RoleRunManager._bdsp_pc_poll_is_active(manager) is False


# --------------------------------------------------------------------------
# Entrar y salir de la vista
# --------------------------------------------------------------------------

def _navigation_manager(active_page: str) -> SimpleNamespace:
    manager = SimpleNamespace(
        active_page=active_page,
        _navigation_transition_token=0,
        cancelaciones=0,
        refrescos=[],
        _smooth_render_page=lambda **kwargs: None,
        _destroy_navigation_transition=lambda overlay: None,
    )
    manager._cancel_bdsp_pc_poll = lambda: setattr(
        manager, "cancelaciones", manager.cancelaciones + 1,
    )
    manager._schedule_gen6_live_pc_refresh = lambda: manager.refrescos.append(True)
    manager.after = lambda _delay, callback: callback()
    return manager


def test_entrar_en_equipo_y_pc_refresca_el_pc_vivo() -> None:
    """Al abrir la vista hay que mirar el PC del juego, no la copia vieja."""
    manager = _navigation_manager("tms")

    RoleRunManager._commit_page_navigation(manager, "team", "tms", None, 0)

    assert manager.active_page == "team"
    assert manager.refrescos == [True]


def test_salir_de_equipo_y_pc_detiene_el_sondeo() -> None:
    manager = _navigation_manager("team")

    RoleRunManager._commit_page_navigation(manager, "tms", "team", None, 0)

    assert manager.cancelaciones == 1


def test_moverse_dentro_de_la_vista_unificada_no_reinicia_nada() -> None:
    """"team" y "pc" son la misma pantalla: no hay entrada ni salida real."""
    manager = _navigation_manager("team")

    RoleRunManager._commit_page_navigation(manager, "pc", "team", None, 0)

    assert manager.cancelaciones == 0
    assert manager.refrescos == []
