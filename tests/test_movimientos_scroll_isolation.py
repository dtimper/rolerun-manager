"""En Movimientos, la rueda del ratón mueve el panel de debajo, no la página.

Bug real reportado por el usuario el 2026-09-03 (con vídeo): al scrollear
con el ratón sobre la lista de MT/drafteos (izquierda) o el equipo
(derecha) en la página Movimientos, se movía la página entera en vez del
panel bajo el puntero. El scroll general de la aplicación (``self`` liga
``<MouseWheel>`` al Tk raíz) capturaba la rueda antes de que llegara al
``CTkScrollableFrame`` correcto, aunque la barra de scroll de la página
esté oculta en esta pantalla (oculta no es lo mismo que sin recorrido: el
canvas seguía siendo desplazable por debajo).

Mismo arreglo que ya existía para CAJAS PC (``_on_smooth_mousewheel``, "no
interceptamos la rueda... para que el panel bajo el puntero reciba el
desplazamiento de forma natural"), extendido a "tms".
"""

from __future__ import annotations

import inspect
import unittest
from types import SimpleNamespace

from app.ui import RoleRunManager


class MouseWheelIsolationTests(unittest.TestCase):
    def test_movimientos_esta_en_la_misma_exclusion_que_cajas_pc(self) -> None:
        fuente = inspect.getsource(RoleRunManager._on_smooth_mousewheel)
        assert 'if self.active_page in {"pc", "tms"}:' in fuente

    def test_con_movimientos_activo_no_se_llega_a_mirar_las_metricas_del_scroll(self) -> None:
        def explota():
            raise AssertionError("no debería consultar el scroll general de la página")

        fake = SimpleNamespace(active_page="tms", _body_scroll_metrics=explota)
        resultado = RoleRunManager._on_smooth_mousewheel(fake, event=SimpleNamespace(delta=120))
        self.assertIsNone(resultado)

    def test_con_cajas_pc_sigue_igual_que_antes(self) -> None:
        def explota():
            raise AssertionError("no debería consultar el scroll general de la página")

        fake = SimpleNamespace(active_page="pc", _body_scroll_metrics=explota)
        resultado = RoleRunManager._on_smooth_mousewheel(fake, event=SimpleNamespace(delta=120))
        self.assertIsNone(resultado)

    def test_otras_paginas_si_consultan_las_metricas_del_scroll(self) -> None:
        llamadas = []

        def metricas():
            llamadas.append(True)
            return None

        fake = SimpleNamespace(active_page="team", _body_scroll_metrics=metricas)
        RoleRunManager._on_smooth_mousewheel(fake, event=SimpleNamespace(delta=120))
        self.assertEqual(llamadas, [True])


if __name__ == "__main__":
    unittest.main()
