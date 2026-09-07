"""MENÚ es navegación, no una capacidad de escritura.

Reportado el 06-09-2026 al llevar HeartGold a la barra flotante: el botón
estaba enganchado a `_floating_live_actions_available` -que en realidad
pregunta si el backend puede CURAR en vivo-, así que cualquier juego sin
curación (HeartGold, mientras su escritura de equipo siga apagada) se
quedaba sin poder abrir el lanzador siquiera, sin que un botón tuviera nada
que ver con el otro.
"""

from __future__ import annotations

import inspect
import re
import unittest

from app.ui import RoleRunManager


class MenuIndependienteDeCurarTests(unittest.TestCase):
    def test_el_boton_menu_no_esta_dentro_del_if_de_curar(self) -> None:
        """El `ctk.CTkButton(...)` de MENÚ debe colgar de `actions`, no del `if`.

        Se comprueba por indentación: la llamada de CURAR cuelga con cuatro
        espacios más que `actions.grid_propagate`, la de MENÚ con la MISMA
        indentación -es decir, fuera del bloque condicional-.
        """
        fuente = inspect.getsource(RoleRunManager._render_floating_bar)

        m_propagate = re.search(r"^( *)actions\.grid_propagate\(False\)", fuente, re.M)
        self.assertIsNotNone(m_propagate, "no se encontró `actions.grid_propagate`")
        base_indent = m_propagate.group(1)

        m_menu = re.search(r'^( *)ctk\.CTkButton\(\s*\n\s*actions, text="☰ MENÚ"', fuente, re.M)
        self.assertIsNotNone(m_menu, "no se encontró el botón MENÚ")
        self.assertEqual(
            m_menu.group(1), base_indent,
            "el botón MENÚ debe estar a la misma indentación que `actions`, "
            "no anidado dentro de un `if`",
        )

    def test_el_boton_curar_sigue_condicionado(self) -> None:
        """CURAR sí debe seguir detrás de `_floating_live_actions_available`."""
        fuente = inspect.getsource(RoleRunManager._render_floating_bar)
        indice_curar = fuente.index('text="♥ CURAR"')
        antes = fuente[:indice_curar]
        self.assertIn("if self._floating_live_actions_available():", antes[-400:])

    def test_el_marco_de_acciones_se_crea_siempre(self) -> None:
        fuente = inspect.getsource(RoleRunManager._render_floating_bar)
        self.assertNotRegex(
            fuente,
            r'if self\._floating_live_actions_available\(\):\s*\n\s*actions = ',
        )


if __name__ == "__main__":
    unittest.main()
