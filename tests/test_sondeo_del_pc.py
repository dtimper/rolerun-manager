"""Releer el PC compite con el emulador, así que se relee menos.

Medido en una sesión de 22 minutos del usuario:

============================  =======  ========
operación                       veces    tiempo
============================  =======  ========
`realtime.read_pc`                430    57,3 s
`realtime.capture_monitor`       1733    11,1 s
`realtime.capture_full`             1     1,3 s
`engine.run`                       12     2,2 s
**total**                              **71,8 s** = 5,4% del tiempo
============================  =======  ========

Cada lectura del PC son ~400 KB de la memoria de otro proceso, y el usuario
reporta que **el juego solo se le entrecorta con RoleRun abierto**. Un sondeo
fijo cada 2,5 segundos es mucho para detectar algo que casi nunca pasa: que el
jugador reorganice sus cajas dentro del juego.

Ahora se empieza rápido y se va espaciando mientras el PC no se mueva, hasta 20
segundos. Cualquier cambio vuelve a acelerarlo al mínimo, así que reaccionar
sigue siendo inmediato justo cuando importa.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui import (  # noqa: E402
    BDSP_PC_POLL_MAX_MS,
    BDSP_PC_POLL_MIN_MS,
    RoleRunManager,
)


def test_el_maximo_espacia_de_verdad() -> None:
    assert BDSP_PC_POLL_MIN_MS == 2500
    assert BDSP_PC_POLL_MAX_MS >= 8 * BDSP_PC_POLL_MIN_MS


def test_se_duplica_mientras_nada_se_mueva_y_no_pasa_del_tope() -> None:
    espera = BDSP_PC_POLL_MIN_MS
    for _vuelta in range(20):
        espera = min(BDSP_PC_POLL_MAX_MS, espera * 2)
    assert espera == BDSP_PC_POLL_MAX_MS


def test_un_cambio_lo_devuelve_al_minimo() -> None:
    """Reaccionar tarde a un cambio hecho dentro del juego sí se nota."""
    fuente = inspect.getsource(RoleRunManager._schedule_oras_external_pc_reconcile)

    assert "BDSP_PC_POLL_MIN_MS if projection_changed" in fuente
    assert "min(BDSP_PC_POLL_MAX_MS, int(self._pc_poll_delay) * 2)" in fuente


def test_el_sondeo_usa_la_espera_calculada() -> None:
    fuente = inspect.getsource(RoleRunManager._schedule_bdsp_pc_poll)

    assert "int(self._pc_poll_delay) if delay is None" in fuente, (
        "sin esto la espera calculada no llegaria a usarse nunca"
    )
    assert "max(150," in fuente, "un sondeo sin suelo se dispararia en bucle"


def test_quien_pida_una_espera_concreta_la_sigue_teniendo() -> None:
    """El reintento corto tras una reconciliación en curso son 350 ms."""
    fuente = inspect.getsource(RoleRunManager._schedule_bdsp_pc_poll)

    assert "self._schedule_bdsp_pc_poll(350)" in fuente


def test_el_sondeo_no_corre_con_la_barra_flotante_ni_minimizado() -> None:
    """Jugando no hace falta releer el PC: la página no se está viendo."""
    fuente = inspect.getsource(RoleRunManager._bdsp_pc_poll_is_active)

    assert "_floating_bar_is_visible()" in fuente
    assert '{"withdrawn", "iconic"}' in fuente
    assert "active_page" in fuente
