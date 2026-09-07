"""El menú de la barra flotante no se abre encima de una capa ya abierta.

Reportado por el usuario el 06-09-2026: con RECUERDA-MOVIMIENTOS abierto,
pulsar MENÚ abría el lanzador ENCIMA. El selector se dibuja dentro de la
ventana principal y el lanzador es un `Toplevel` con `-topmost`, así que el
selector quedaba detrás y sin forma de volver a él.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.ui import RoleRunManager


class _Capa:
    """Una capa abierta (o ya destruida, si `existe` es False)."""

    def __init__(self, existe: bool = True) -> None:
        self.existe = existe

    def winfo_exists(self) -> bool:
        return self.existe


class _CapaRota:
    """Una capa cuyo widget ya no responde: no debe bloquear nada."""

    def winfo_exists(self):
        raise RuntimeError("widget destruido")


def _fake(**capas) -> SimpleNamespace:
    fake = SimpleNamespace(
        _levelup_history_popover=None,
        _move_info_popover=None,
        _role_info_popover=None,
        _floating_launcher=None,
        **capas,
    )
    fake._capa_abierta_bloquea_el_menu = (
        RoleRunManager._capa_abierta_bloquea_el_menu.__get__(fake)
    )
    return fake


class BloqueoDelMenuTests(unittest.TestCase):
    def test_sin_ninguna_capa_abierta_el_menu_puede_abrirse(self) -> None:
        self.assertFalse(_fake()._capa_abierta_bloquea_el_menu())

    def test_recuerda_movimientos_abierto_bloquea_el_menu(self) -> None:
        fake = _fake()
        fake._levelup_history_popover = _Capa()
        self.assertTrue(fake._capa_abierta_bloquea_el_menu())

    def test_tambien_bloquean_las_otras_capas(self) -> None:
        for atributo in ("_move_info_popover", "_role_info_popover"):
            fake = _fake()
            setattr(fake, atributo, _Capa())
            self.assertTrue(fake._capa_abierta_bloquea_el_menu(), atributo)

    def test_una_capa_ya_cerrada_no_bloquea(self) -> None:
        fake = _fake()
        fake._levelup_history_popover = _Capa(existe=False)
        self.assertFalse(fake._capa_abierta_bloquea_el_menu())

    def test_una_capa_rota_no_deja_el_menu_inutilizable(self) -> None:
        """Un widget ya destruido no puede dejar el MENÚ bloqueado para siempre."""
        fake = _fake()
        fake._levelup_history_popover = _CapaRota()
        self.assertFalse(fake._capa_abierta_bloquea_el_menu())


class ToggleTests(unittest.TestCase):
    def test_no_abre_el_lanzador_con_una_capa_delante(self) -> None:
        fake = _fake()
        fake._levelup_history_popover = _Capa()
        fake.floating_bar = None
        fake.open_floating_bar = lambda: self.fail("no debía intentar abrir nada")

        RoleRunManager._toggle_floating_launcher(fake)

        self.assertIsNone(fake._floating_launcher)

    def test_cerrar_el_lanzador_sigue_permitido_aunque_haya_una_capa(self) -> None:
        """El guardia solo impide ABRIR: si ya está abierto, hay que poder cerrarlo."""
        cerrados = []
        fake = _fake()
        fake._levelup_history_popover = _Capa()
        fake._floating_launcher = _Capa()
        fake._close_floating_launcher = lambda: cerrados.append(True)

        RoleRunManager._toggle_floating_launcher(fake)

        self.assertEqual(cerrados, [True])


if __name__ == "__main__":
    unittest.main()
