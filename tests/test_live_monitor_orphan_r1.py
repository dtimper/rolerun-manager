"""Regresión de R1: el monitor vivo podía quedarse huérfano.

Escenario real: el usuario guarda dentro del juego mientras una lectura del
monitor está en vuelo. El ``SaveFileWatcher`` reinicia la reconciliación, pero
se encuentra el cerrojo del monitor puesto y no consigue armar nada; el worker
viejo termina, suelta el cerrojo y descarta su resultado por token obsoleto sin
reprogramar. La sesión queda con ``_oras_live_active=True`` y sin nadie leyendo.

La ventana es corta pero se abre en cada guardado del juego, que es justo lo que
el usuario hace constantemente durante una run.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui import RoleRunManager  # noqa: E402


class _MonitorHarness:
    """Reproduce el ciclo del monitor sin Tk, sin emulador y sin hilos.

    Solo se sustituyen las fronteras que no se están probando: ``after`` (que
    aquí anota el rearme en lugar de programarlo en Tk) y el predicado de sesión
    activa. La lógica de programación y de cierre es la de producción.
    """

    def __init__(self, *, activa: bool = True) -> None:
        self._oras_live_monitor_token = 7
        self._oras_live_monitor_in_progress = False
        self._oras_live_monitor_after_id = None
        self._session_generation = 1
        self.project = SimpleNamespace(slug="run", pending_faints=[])
        self.current_game = object()
        self._activa = activa
        self.rearmes: list[int] = []

    def after(self, delay_ms, callback):
        self.rearmes.append(int(delay_ms))
        return f"timer-{len(self.rearmes)}"

    def _oras_live_reconciliation_is_active(self) -> bool:
        return self._activa

    _schedule_oras_live_reconciliation = RoleRunManager._schedule_oras_live_reconciliation
    _finish_oras_live_reconciliation = RoleRunManager._finish_oras_live_reconciliation


def _simular_guardado_del_juego_durante_una_lectura(harness: _MonitorHarness) -> int:
    """Deja el estado exacto que produce el watcher con un worker en vuelo."""
    token_del_worker = harness._oras_live_monitor_token
    harness._oras_live_monitor_in_progress = True      # lectura en vuelo
    harness._oras_live_monitor_token += 1              # el watcher la invalida
    # El watcher intenta rearmar, pero el cerrojo sigue puesto: no arma nada.
    harness._schedule_oras_live_reconciliation(650)
    assert harness.rearmes == [], "el cerrojo debería impedir el rearme del watcher"
    return token_del_worker


def test_el_worker_obsoleto_rearma_el_monitor_en_lugar_de_dejarlo_muerto() -> None:
    harness = _MonitorHarness()
    token_del_worker = _simular_guardado_del_juego_durante_una_lectura(harness)

    harness._finish_oras_live_reconciliation(
        harness._session_generation, "run", token_del_worker, None, None, None,
    )

    assert harness._oras_live_monitor_in_progress is False
    assert harness.rearmes == [650], "la sesión viva se quedó sin monitor (R1)"


def test_el_resultado_obsoleto_se_sigue_descartando() -> None:
    """Rearmar no puede significar aceptar la lectura vieja."""
    harness = _MonitorHarness()
    token_del_worker = _simular_guardado_del_juego_durante_una_lectura(harness)
    harness._oras_live_monitor_failures = 99  # lo tocaría el camino de proceso

    harness._finish_oras_live_reconciliation(
        harness._session_generation, "run", token_del_worker, None, None, "error viejo",
    )

    # El contador de fallos pertenece al procesamiento del resultado; si el
    # snapshot obsoleto se hubiera procesado, habría subido a 100.
    assert harness._oras_live_monitor_failures == 99


def test_una_sesion_cerrada_no_resucita_el_monitor() -> None:
    """Cerrar la run o cambiar de partida debe dejar el monitor apagado."""
    harness = _MonitorHarness(activa=False)
    token_del_worker = harness._oras_live_monitor_token
    harness._oras_live_monitor_in_progress = True
    harness._oras_live_monitor_token += 1

    harness._finish_oras_live_reconciliation(
        harness._session_generation, "run", token_del_worker, None, None, None,
    )

    assert harness._oras_live_monitor_in_progress is False
    assert harness.rearmes == []


def test_el_rearme_no_arranca_una_captura_solapada() -> None:
    """El cerrojo debe seguir protegiendo mientras la lectura está en vuelo.

    Este es el motivo de arreglar R1 en el cierre del worker y no limpiando el
    cerrojo al invalidar el token: soltarlo antes permitiría que arrancara una
    captura nueva sobre readers con estado mutable y sin lock.
    """
    harness = _MonitorHarness()
    harness._oras_live_monitor_in_progress = True

    harness._schedule_oras_live_reconciliation(650)

    assert harness.rearmes == []
