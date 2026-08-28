"""Volver a la ventana principal desde la barra no tiene por qué repintar.

Repintar cuesta **610 ms de mediana y hasta 2576 medidos**, y todo eso ocurre en
el hilo de Tk: un núcleo a tope mientras el emulador también lo necesita. El
usuario lo oye como un corte de dos segundos en la música del juego cada vez que
maximiza RoleRun.

Mientras se está en la barra, la ventana principal solo está **retirada**, no
destruida. Si nadie marcó la página como sucia y se vuelve a la misma, el árbol
que ya hay es el bueno.

El riesgo de esto no es la velocidad: es que alguna ruta olvide marcar la página
como sucia y se muestre un dato viejo. Por eso, cuando se reutiliza el árbol, se
refresca en sitio con la ventana ya visible: 37 ms medidos, y si algo no cuadra
esa ruta se niega sola y no toca nada.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui import RoleRunManager  # noqa: E402


def _fuente() -> str:
    return inspect.getsource(RoleRunManager._floating_logo_to_dashboard)


def test_no_se_repinta_si_nada_cambio() -> None:
    fuente = _fuente()

    assert "if not reutilizable:" in fuente
    assert "self.render_page()" in fuente, "sigue haciendo falta cuando si cambio"


def test_las_tres_condiciones_para_reutilizar() -> None:
    """Cualquiera que falte deja una pagina vieja o un arbol muerto en pantalla."""
    fuente = _fuente()

    assert '_pagina_del_body", None) == str(self.active_page)' in fuente, (
        "hay que comprobar para que pagina es el arbol, no deducirlo"
    )
    assert '_widget_alive(getattr(self, "body", None))' in fuente, (
        "sin arbol vivo no hay nada que reutilizar"
    )
    assert "not self._main_ui_dirty_while_floating" in fuente, (
        "si algo cambio mientras se estaba en la barra hay que repintar"
    )


def test_reutilizar_lleva_una_red_de_seguridad() -> None:
    """Si una ruta olvido marcar la pagina como sucia, esto lo corrige."""
    fuente = _fuente()
    despues = fuente[fuente.index("_restore_main_window_maximized"):]

    assert "if reutilizable:" in despues
    assert "_refrescar_team_pc_en_sitio" in despues


def test_la_red_de_seguridad_va_con_la_ventana_ya_visible() -> None:
    """El refresco en sitio exige los paneles mapeados: retirada se negaria."""
    fuente = _fuente()
    restaurar = fuente.index("_restore_main_window_maximized")
    refrescar = fuente.index("_refrescar_team_pc_en_sitio")

    assert restaurar < refrescar


def test_la_marca_de_sucia_se_limpia_en_los_dos_casos() -> None:
    """Dejarla puesta obligaria a repintar la siguiente vez sin motivo."""
    fuente = _fuente()
    limpieza = fuente.index("self._main_ui_dirty_while_floating = False")
    condicional = fuente.index("if not reutilizable:")

    assert limpieza > condicional, "tiene que quedar fuera del `if`"


def test_el_body_apunta_para_que_pagina_se_construyo() -> None:
    """Mientras se esta en la barra, `active_page` no habla del arbol principal.

    La barra y su menu cambian de pagina por su cuenta, asi que deducir de
    `active_page` que hay en la ventana retirada era adivinar. El body lo dice.
    """
    fuente = inspect.getsource(RoleRunManager.render_page)

    assert "self._pagina_del_body = str(self.active_page)" in fuente
    cuerpo = fuente.index("_render_page_body()")
    marca = fuente.index("_pagina_del_body")
    assert marca > cuerpo, "se apunta despues de construirlo, no antes"
