"""``self.body`` no debe tener ningún recorrido de scroll propio en Movimientos,
y lo que hay dentro nunca puede quedar recortado sin forma de alcanzarlo.

Bug real reportado por el usuario el 2026-09-03, en varias vueltas:

1. Scrollear sobre la lista de MT/drafteos, el equipo o el selector de MT
   seguía moviendo la página entera. Calcular el alto exacto de cada panel
   para que nunca superara el viewport de ``self.body`` era frágil -en el
   primer render ``canvas.winfo_height()`` vale 200 (el tamaño por defecto
   de CustomTkinter, antes de que Tk resuelva la geometría real), así que
   el cálculo caía siempre a la heurística que sobrestima-.
2. ``self.body`` es también un ``CTkScrollableFrame``, y CustomTkinter le
   liga su propio manejador de rueda con ``bind_all`` (independiente de
   ``_on_smooth_mousewheel``): mientras su canvas tenga scrollregion real
   por encima de su viewport, esa rueda global sigue moviendo la página
   entera. Primer arreglo: fijar el scrollregion de ``self.body`` a su
   propio viewport directamente.
3. Pero fijar SOLO el scrollregion, sin tocar el marco de la vista activa
   (``GlobalTMView``/``IntegratedTMTeachFlow``), recortaba lo que ese marco
   sobrara por debajo -sin ninguna forma de alcanzarlo, ni con el scroll
   propio de sus paneles de dentro («el recuerda-movimientos cortado» en
   los tres Pokémon de la fila de abajo)-. Arreglo final: forzar a la vez
   el alto del marco activo a la MISMA medida que se fija como
   scrollregion, así nunca puede sobrar nada.
"""

from __future__ import annotations

import inspect
import unittest
from types import SimpleNamespace

from app.ui import RoleRunManager


class _FakeCanvas:
    def __init__(self, width: int, height: int, *, exists: bool = True) -> None:
        self._width = width
        self._height = height
        self._exists = exists
        self.configured_scrollregion = None

    def winfo_exists(self) -> bool:
        return self._exists

    def winfo_width(self) -> int:
        return self._width

    def winfo_height(self) -> int:
        return self._height

    def configure(self, **kwargs) -> None:
        if "scrollregion" in kwargs:
            self.configured_scrollregion = kwargs["scrollregion"]


class _FakeFrame:
    def __init__(self) -> None:
        self.height = None

    def winfo_exists(self) -> bool:
        return True

    def configure(self, **kwargs) -> None:
        if "height" in kwargs:
            self.height = kwargs["height"]

    def _reverse_widget_scaling(self, value):
        # Identidad a propósito: aquí solo interesa que se llame -y con qué
        # medida-, no la conversión real de CTk.
        return value


class PinBodyScrollregionTests(unittest.TestCase):
    def _fake(self, canvas, *, global_tm_frame=None, tm_teach_frame=None) -> SimpleNamespace:
        body = SimpleNamespace(_parent_canvas=canvas, winfo_exists=lambda: True)
        fake = SimpleNamespace(
            body=body,
            _global_tm_view=SimpleNamespace(frame=global_tm_frame) if global_tm_frame is not None else None,
            _tm_teach_flow=SimpleNamespace(frame=tm_teach_frame) if tm_teach_frame is not None else None,
        )
        fake._widget_alive = RoleRunManager._widget_alive.__get__(fake)
        fake._pin_body_scrollregion_to_viewport = (
            RoleRunManager._pin_body_scrollregion_to_viewport.__get__(fake)
        )
        return fake

    def test_fija_el_scrollregion_al_viewport_real(self) -> None:
        canvas = _FakeCanvas(width=1400, height=760)
        fake = self._fake(canvas)
        fake._pin_body_scrollregion_to_viewport()
        self.assertEqual(canvas.configured_scrollregion, (0, 0, 1400, 760))

    def test_no_hace_nada_si_el_canvas_aun_no_tiene_geometria(self) -> None:
        canvas = _FakeCanvas(width=1, height=1)
        fake = self._fake(canvas)
        fake._pin_body_scrollregion_to_viewport()
        self.assertIsNone(canvas.configured_scrollregion)

    def test_no_revienta_si_el_body_ya_no_existe(self) -> None:
        canvas = _FakeCanvas(width=1400, height=760)
        body = SimpleNamespace(_parent_canvas=canvas, winfo_exists=lambda: False)
        fake = SimpleNamespace(body=body, _global_tm_view=None, _tm_teach_flow=None)
        fake._widget_alive = RoleRunManager._widget_alive.__get__(fake)
        fake._pin_body_scrollregion_to_viewport = (
            RoleRunManager._pin_body_scrollregion_to_viewport.__get__(fake)
        )
        fake._pin_body_scrollregion_to_viewport()  # no debe lanzar
        self.assertIsNone(canvas.configured_scrollregion)

    def test_el_marco_de_movimientos_se_ajusta_a_la_misma_medida(self) -> None:
        """Pedido por el usuario el 2026-09-03: sin esto, RECUERDA-MOVIMIENTOS
        de los Pokémon de la última fila quedaba cortado, inalcanzable
        incluso con el scroll propio del panel del equipo."""
        canvas = _FakeCanvas(width=1400, height=760)
        marco = _FakeFrame()
        fake = self._fake(canvas, global_tm_frame=marco)
        fake._pin_body_scrollregion_to_viewport()
        self.assertEqual(marco.height, 760)
        self.assertEqual(canvas.configured_scrollregion, (0, 0, 1400, 760))

    def test_el_marco_del_selector_de_mt_tambien_se_ajusta(self) -> None:
        canvas = _FakeCanvas(width=1400, height=760)
        marco = _FakeFrame()
        fake = self._fake(canvas, tm_teach_frame=marco)
        fake._pin_body_scrollregion_to_viewport()
        self.assertEqual(marco.height, 760)

    def test_convierte_el_alto_fisico_a_logico_antes_de_fijarlo(self) -> None:
        """Pedido por el usuario el 2026-09-03, quinto intento: sin convertir
        con ``_reverse_widget_scaling`` -como ya hace ``UnifiedTeamPCView``,
        que nunca tuvo este fallo-, el marco salía un 12% más alto que el
        viewport real (el escalado de CTk, ``set_widget_scaling(1.12)``,
        puesto encima de un valor sin convertir) y su borde inferior no
        llegaba a cerrar."""
        canvas = _FakeCanvas(width=1400, height=760)
        marco = _FakeFrame()
        marco._reverse_widget_scaling = lambda value: value / 1.12
        fake = self._fake(canvas, global_tm_frame=marco)
        fake._pin_body_scrollregion_to_viewport()
        self.assertEqual(marco.height, int(760 / 1.12))

    def test_reintenta_en_varias_esperas_mientras_tk_asienta_la_geometria(self) -> None:
        llamadas = []
        fake = SimpleNamespace(
            after=lambda delay, callback: llamadas.append(delay),
            _pin_body_scrollregion_to_viewport=lambda: None,
        )
        fake._pin_body_scrollregion_soon = RoleRunManager._pin_body_scrollregion_soon.__get__(fake)
        fake._pin_body_scrollregion_soon()
        self.assertEqual(llamadas, [0, 30, 80, 180, 400])


class WiringTests(unittest.TestCase):
    def test_movimientos_fija_el_scrollregion_al_construir_la_vista(self) -> None:
        fuente = inspect.getsource(RoleRunManager._render_global_tm_page)
        assert "self._pin_body_scrollregion_soon()" in fuente

    def test_el_selector_de_mt_tambien_fija_el_scrollregion(self) -> None:
        fuente = inspect.getsource(RoleRunManager._open_integrated_tm_flow)
        assert "self._pin_body_scrollregion_soon()" in fuente


if __name__ == "__main__":
    unittest.main()
