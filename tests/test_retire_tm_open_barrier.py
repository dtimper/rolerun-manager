"""La barrera de apertura del selector de MT tiene que soltarse siempre.

Bug real reportado por el usuario el 2026-09-03 ("si le doy a enseñar un
movimiento y quiero retroceder, el programa no nos da opción"): al enseñar
una MT directamente desde su tarjeta en Movimientos (``initial_move_id``,
que salta al paso "qué hueco olvidará"), la barrera "Abriendo el selector de
MT…" —un ``Toplevel`` opaco y ``-topmost`` sobre el contenido— podía
quedarse encima para siempre si ``is_fully_composed()`` nunca llegaba a
devolver ``True``. El flujo de debajo, con su propio botón de volver, quedaba
completo pero inalcanzable: tapado por la barrera, que bloqueaba todos los
clics. Mismo arreglo que ya tenía la barrera simétrica de CIERRE
(``_retire_tm_close_when_ready``): reintentar con tope y soltarse igual al
agotar la paciencia — una barrera eterna es peor que un fallo ruidoso.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.ui import RoleRunManager


class _NeverReadyFlow:
    def is_fully_composed(self) -> bool:
        return False


class OpenBarrierManager:
    INTENTOS_BARRERA_MT = RoleRunManager.INTENTOS_BARRERA_MT
    _retire_tm_open_when_ready = RoleRunManager._retire_tm_open_when_ready

    def __init__(self, flow) -> None:
        self._tm_teach_flow = flow
        self.hidden_reasons: list[str] = []
        self.status_calls: list[tuple] = []
        self.after_calls = 0

    def after(self, _delay, callback):
        self.after_calls += 1
        callback()

    def _hide_busy_indicator(self, reason: str) -> None:
        self.hidden_reasons.append(reason)

    def _set_operation_status(self, *args, **kwargs) -> None:
        self.status_calls.append((args, kwargs))


class RetireTmOpenBarrierTests(unittest.TestCase):
    def test_se_suelta_sola_al_agotar_la_paciencia_si_nunca_termina_de_componerse(self) -> None:
        flow = _NeverReadyFlow()
        manager = OpenBarrierManager(flow)
        manager._retire_tm_open_when_ready(flow)
        # Se soltó exactamente una vez: no se quedó pegada para siempre.
        self.assertEqual(manager.hidden_reasons, ["tm-flow"])
        self.assertEqual(len(manager.status_calls), 1)
        self.assertLessEqual(manager.after_calls, manager.INTENTOS_BARRERA_MT)

    def test_se_suelta_de_inmediato_si_el_flujo_ya_esta_compuesto(self) -> None:
        flow = SimpleNamespace(is_fully_composed=lambda: True)
        manager = OpenBarrierManager(flow)
        manager._retire_tm_open_when_ready(flow)
        self.assertEqual(manager.hidden_reasons, ["tm-flow"])
        self.assertEqual(manager.after_calls, 0)
        self.assertEqual(manager.status_calls, [])

    def test_no_hace_nada_si_ya_no_es_el_flujo_activo(self) -> None:
        flow = _NeverReadyFlow()
        manager = OpenBarrierManager(SimpleNamespace())  # otro flujo pasó a ser el activo
        manager._retire_tm_open_when_ready(flow)
        self.assertEqual(manager.hidden_reasons, [])
        self.assertEqual(manager.after_calls, 0)


if __name__ == "__main__":
    unittest.main()
