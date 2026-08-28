"""El menú flotante no puede quedarse pintado encima de otra aplicación.

El menú es un ``Toplevel`` sin marco, del tamaño exacto de la ventana del juego
y en ``-topmost``. Mientras se juega eso es justo lo que se quiere. Al cambiar a
otra aplicación dejaba de serlo: RoleRun se quedaba ocupando media pantalla del
navegador, porque nadie estaba mirando.

Y nadie estaba mirando literalmente. El sondeo lo reprograma el repintado de la
barra, y abrir el menú retira la barra, así que el sondeo se apagaba en el mismo
gesto que creaba el problema.

La regla es la misma que para la barra —lo que va encima del juego no pinta nada
cuando el juego no se ve— pero aquí se **esconde** en vez de destruirse: al
volver, el menú sigue en la sección donde estaba.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui import RoleRunManager  # noqa: E402


class MenuFalso:
    def __init__(self, estado: str = "normal") -> None:
        self._estado = estado
        self.agarrado = True
        self.enfocado = False
        self.encima = True

    def winfo_exists(self) -> int:
        return 1

    def state(self) -> str:
        return self._estado

    def withdraw(self) -> None:
        self._estado = "withdrawn"

    def deiconify(self) -> None:
        self._estado = "normal"

    def grab_release(self) -> None:
        self.agarrado = False

    def grab_set(self) -> None:
        self.agarrado = True

    def attributes(self, nombre: str, valor: object) -> None:
        if nombre == "-topmost":
            self.encima = bool(valor)

    def lift(self) -> None:
        pass

    def focus_force(self) -> None:
        self.enfocado = True


class CompuertaFalsa:
    def __init__(self) -> None:
        self.retenido = True
        self.sueltas = 0
        self.tomas = 0

    def acquire(self) -> bool:
        self.retenido = True
        self.tomas += 1
        return True

    def release(self, *, all_levels: bool = False) -> bool:
        self.retenido = False
        self.sueltas += 1
        return True


class ManagerFalso:
    """Solo las piezas que tocan al menú, montadas sobre los métodos reales."""

    _widget_alive = RoleRunManager._widget_alive
    _vigilar_el_menu_flotante = RoleRunManager._vigilar_el_menu_flotante
    _esconder_el_menu_flotante = RoleRunManager._esconder_el_menu_flotante
    _devolver_el_menu_flotante = RoleRunManager._devolver_el_menu_flotante

    def __init__(self, menu: MenuFalso | None, tapado: bool) -> None:
        self._floating_launcher = menu
        self._menu_oculto_por_tapado = False
        self._ryujinx_input_gate = CompuertaFalsa()
        self.tapado = tapado
        self._estado_ventana = "withdrawn"

    def _el_juego_esta_tapado(self) -> bool:
        return self.tapado

    def state(self) -> str:
        return self._estado_ventana

    def iconify(self) -> None:
        self._estado_ventana = "iconic"

    def withdraw(self) -> None:
        self._estado_ventana = "withdrawn"


def test_si_tapan_el_juego_el_menu_se_esconde() -> None:
    menu = MenuFalso()
    app = ManagerFalso(menu, tapado=True)

    assert app._vigilar_el_menu_flotante() is True
    assert menu.state() == "withdrawn"
    assert app._menu_oculto_por_tapado is True


def test_esconderlo_suelta_el_agarre_y_el_emulador() -> None:
    """Un ``grab`` de una ventana invisible se lo come todo.

    Y retener el emulador con el menú escondido solo consigue congelar la
    partida mientras el usuario está en otra aplicación.
    """
    menu = MenuFalso()
    app = ManagerFalso(menu, tapado=True)

    app._vigilar_el_menu_flotante()

    assert menu.agarrado is False
    assert app._ryujinx_input_gate.retenido is False


def test_esconderlo_no_deja_a_rolerun_sin_icono() -> None:
    """Con el menú abierto, la barra y la ventana principal están retiradas."""
    menu = MenuFalso()
    app = ManagerFalso(menu, tapado=True)

    app._vigilar_el_menu_flotante()

    assert app.state() == "iconic", "RoleRun desaparecería de la barra de tareas"


def test_al_despejarse_el_juego_el_menu_vuelve_entero() -> None:
    menu = MenuFalso()
    app = ManagerFalso(menu, tapado=True)
    app._vigilar_el_menu_flotante()

    app.tapado = False
    assert app._vigilar_el_menu_flotante() is True

    assert menu.state() == "normal"
    assert menu.encima is True, "por debajo del juego no se vería"
    assert menu.agarrado is True
    assert menu.enfocado is True
    assert app._menu_oculto_por_tapado is False
    assert app._ryujinx_input_gate.retenido is True
    assert app.state() == "withdrawn", "en modo flotante solo debe verse el menú"


def test_el_menu_no_se_destruye_al_esconderlo() -> None:
    """Volver a la sección donde estabas es la mitad de la gracia."""
    menu = MenuFalso()
    app = ManagerFalso(menu, tapado=True)

    app._vigilar_el_menu_flotante()

    assert app._floating_launcher is menu


def test_un_menu_retirado_por_otra_cosa_no_se_trae_de_vuelta() -> None:
    """Igual que con la barra: cerrar a mano es una decisión, no un despiste."""
    menu = MenuFalso(estado="withdrawn")
    app = ManagerFalso(menu, tapado=False)

    assert app._vigilar_el_menu_flotante() is True
    assert menu.state() == "withdrawn"


def test_sin_menu_abierto_el_sondeo_sigue_con_la_barra() -> None:
    app = ManagerFalso(None, tapado=True)

    assert app._vigilar_el_menu_flotante() is False
    assert app._menu_oculto_por_tapado is False


def test_el_sondeo_atiende_al_menu_antes_que_a_la_barra() -> None:
    """Con el menú abierto la barra está retirada, y el sondeo se cortaba ahí."""
    fuente = inspect.getsource(RoleRunManager._poll_floating_bar)
    cabeza = fuente[:fuente.index("bar = self.floating_bar")]

    assert "self._vigilar_el_menu_flotante()" in cabeza
    assert "self.after(500, self._poll_floating_bar)" in cabeza, (
        "sin reprogramar, el menú se queda otra vez sin nadie que lo vigile"
    )


def test_abrir_el_menu_arranca_el_sondeo() -> None:
    """Lo reprograma el repintado de la barra, y abrir el menú la retira."""
    fuente = inspect.getsource(RoleRunManager._toggle_floating_launcher)

    assert "self._schedule_floating_bar_poll()" in fuente
    assert "self._menu_oculto_por_tapado = False" in fuente


def test_cerrar_el_menu_escondido_no_saca_la_barra_encima_del_estorbo() -> None:
    fuente = inspect.getsource(RoleRunManager._close_floating_launcher)

    assert "escondido = self._menu_oculto_por_tapado" in fuente
    assert "if not escondido and not self._game_overlay_active" in fuente
    assert "self._barra_oculta_por_tapado = True" in fuente, (
        "sin marcarla, el sondeo no la traería de vuelta al despejarse el juego"
    )
