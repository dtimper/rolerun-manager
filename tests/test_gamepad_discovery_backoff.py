"""El bucle de mando no puede enumerar procesos 60 veces por segundo.

``_poll_gamepad`` corre a 16 ms en el hilo de Tkinter. Mientras no haya un mando
resuelto llamaba a ``SDLGamepad.from_ryujinx_process``, que enumera la tabla
completa de procesos de Windows. Sin Ryujinx abierto —todos los juegos salvo
BDSP— eso costaba, medido en la máquina del proyecto, 2,36 ms por intento: unos
142 ms de CPU por segundo, el 14 % de un núcleo, robados al hilo que dibuja la
interfaz durante toda la sesión y ya desde el splash.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui import GAMEPAD_DISCOVERY_INTERVAL_SECONDS, RoleRunManager  # noqa: E402


def _manager() -> SimpleNamespace:
    return SimpleNamespace()


def test_el_primer_intento_siempre_se_permite() -> None:
    manager = _manager()
    assert RoleRunManager._gamepad_discovery_is_due(manager, now=1000.0) is True


def test_no_se_repite_en_cada_tick_de_60_hz() -> None:
    manager = _manager()
    RoleRunManager._gamepad_discovery_is_due(manager, now=1000.0)

    # Un segundo entero de ticks a 16 ms no puede producir ni un intento más.
    intentos = sum(
        1 for tick in range(1, 61)
        if RoleRunManager._gamepad_discovery_is_due(manager, now=1000.0 + tick * 0.016)
    )

    assert intentos == 0


def test_se_reintenta_pasado_el_intervalo() -> None:
    """Abrir Ryujinx a mitad de sesión debe seguir detectándose."""
    manager = _manager()
    RoleRunManager._gamepad_discovery_is_due(manager, now=1000.0)

    justo_antes = 1000.0 + GAMEPAD_DISCOVERY_INTERVAL_SECONDS - 0.01
    assert RoleRunManager._gamepad_discovery_is_due(manager, now=justo_antes) is False

    justo_despues = 1000.0 + GAMEPAD_DISCOVERY_INTERVAL_SECONDS + 0.01
    assert RoleRunManager._gamepad_discovery_is_due(manager, now=justo_despues) is True


def test_el_intervalo_es_perceptiblemente_corto() -> None:
    """Debe ahorrar CPU sin que conectar el mando parezca que no funciona."""
    assert 0.5 <= GAMEPAD_DISCOVERY_INTERVAL_SECONDS <= 5.0


def test_el_poll_solo_busca_cuando_toca() -> None:
    """La condición vive en _poll_gamepad, no solo en el helper."""
    import inspect

    fuente = inspect.getsource(RoleRunManager._poll_gamepad)
    assert "_gamepad_discovery_is_due()" in fuente
    assert "from_ryujinx_process()" in fuente
