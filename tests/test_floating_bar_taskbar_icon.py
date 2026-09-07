"""El icono de RoleRun no puede desaparecer de la barra de tareas de Windows.

Bug real reportado por el usuario el 2026-09-03: al entrar en la barra
flotante, ``open_floating_bar`` retiraba (``withdraw()``) la ventana
principal por completo. Un ``withdraw()`` deja la ventana sin ninguna
presencia en la barra de tareas de Windows, así que el icono de RoleRun
desaparecía entero mientras la barra flotante estaba activa.

El primer intento de arreglo forzó un icono de tareas propio para la barra
flotante (``WS_EX_APPWINDOW``), pero el usuario mandó una captura mostrando
que ese botón salía en blanco —sin el símbolo de RoleRun— y además pulsarlo
no hacía lo que se pedía (volver al programa). Se revirtió.

El arreglo real reutiliza un mecanismo que ya existía y ya estaba probado
para el cierre de la barra (``_close_from_floating_bar``, comentario "para
que Windows la conserve como aplicación normal en la barra de tareas"):
``deiconify()`` seguido de ``iconify()`` en vez de ``withdraw()``. Así la
ventana principal —con su icono real, fijado una sola vez al arrancar—
queda minimizada pero visible en la barra de tareas, y pulsarla dispara
``<Map>`` → ``_on_main_map``, que ya sabía volver desde la barra flotante.
"""

from __future__ import annotations

import inspect
import unittest
from types import SimpleNamespace

from app.ui import RoleRunManager


class OpenFloatingBarUsesIconifyTests(unittest.TestCase):
    def test_ninguna_rama_usa_withdraw_puro_para_ocultar_la_raiz(self) -> None:
        fuente = inspect.getsource(RoleRunManager.open_floating_bar)
        assert "self.withdraw()" not in fuente, (
            "open_floating_bar debe minimizar (deiconify+iconify), no retirar "
            "(withdraw) la ventana principal: withdraw() la deja sin icono en "
            "la barra de tareas de Windows."
        )

    def test_las_dos_ramas_usan_deiconify_seguido_de_iconify(self) -> None:
        fuente = inspect.getsource(RoleRunManager.open_floating_bar)
        assert fuente.count("self.deiconify()") == 2
        assert fuente.count("self.iconify()") == 2

    def test_no_fuerza_ya_un_icono_de_tareas_propio_para_la_barra(self) -> None:
        """El primer intento (WS_EX_APPWINDOW en la barra) quedó revertido."""
        fuente = inspect.getsource(RoleRunManager.open_floating_bar)
        assert "_apply_floating_bar_taskbar_icon" not in fuente
        assert not hasattr(RoleRunManager, "_apply_floating_bar_taskbar_icon")
        assert not hasattr(RoleRunManager, "_floating_taskbar_icon_exstyle")


class OnMainMapGuardTests(unittest.TestCase):
    """``deiconify()`` para abrir la barra flotante dispara <Map> como
    efecto colateral de la propia apertura: sin el guard, ``_on_main_map``
    lo interpretaría como "el usuario ha vuelto" y podría deshacer la
    apertura que se acaba de pedir.
    """

    def _fake(self, *, guard: bool) -> SimpleNamespace:
        calls: list[str] = []
        fake = SimpleNamespace(
            _auto_floating_guard=guard,
            _floating_bar_is_visible=lambda: (_ for _ in ()).throw(
                AssertionError("no debería consultarse con el guard activo")
            ),
            _schedule_pending_faint_picker=lambda *_a, **_k: calls.append("faint_picker"),
            _schedule_bdsp_pc_poll=lambda *_a, **_k: calls.append("bdsp_poll"),
            _floating_suspended_modal=None,
        )
        fake._calls = calls
        return fake

    def test_con_el_guard_activo_no_hace_nada(self) -> None:
        fake = self._fake(guard=True)
        RoleRunManager._on_main_map(fake)
        self.assertEqual(fake._calls, [])

    def test_sin_el_guard_sigue_funcionando_como_antes(self) -> None:
        fake = self._fake(guard=False)
        fake._floating_bar_is_visible = lambda: False
        RoleRunManager._on_main_map(fake)
        self.assertIn("faint_picker", fake._calls)
        self.assertIn("bdsp_poll", fake._calls)


if __name__ == "__main__":
    unittest.main()
