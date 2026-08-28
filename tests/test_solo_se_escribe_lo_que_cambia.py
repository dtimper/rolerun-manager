"""En customtkinter, escribir cuesta; comparar antes, no.

Medido con customtkinter en el equipo del usuario:

    configure de un CTkFrame con 4 colores ..... 1,445 ms
    configure de un CTkButton con 5 opciones ... 0,844 ms
    configure(text=) a secas ................... 0,047 ms
    leer esas mismas opciones con cget .........  0,001 ms

Cualquier opción de color obliga a repintar el canvas entero, cambie o no el
valor. El caso peor medido ni siquiera era un repintado de página: pasar el
ratón por una tarjeta dispara `_apply_selection_styles`, que reconfiguraba las
seis tarjetas del equipo y las treinta casillas del PC —135 ms— para mover un
único borde.

Medido de punta a punta sobre la vista real, con los seis miembros y una caja
cambiando de datos enteros:

    destruir y reconstruir la vista .... 660 ms
    refrescar en sitio ................. 376 ms  (antes de esto)
    refrescar en sitio .................  37 ms  (después)

Y mover un resalte por una rejilla, que es lo que hace cada flecha:

                       repintar todo   comparar antes
      8 elementos ....... 13,05 ms ....... 3,17 ms
     30 elementos ....... 46,64 ms ....... 3,16 ms
    100 elementos ...... 153,93 ms ....... 3,34 ms

Lo importante de esa tabla no es el factor sino que el coste deja de crecer
con el tamaño de la rejilla: se escribe lo que cambia, que son dos.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui_components.repintado import configurar_si_cambia  # noqa: E402
from app.ui_views.team_pc_view import UnifiedTeamPCView  # noqa: E402


class _Widget:
    def __init__(self, **opciones) -> None:
        self.opciones = dict(opciones)
        self.escrituras: list[dict] = []

    def cget(self, clave):
        return self.opciones[clave]

    def configure(self, **kwargs) -> None:
        self.escrituras.append(dict(kwargs))
        self.opciones.update(kwargs)


def test_lo_que_no_cambia_no_se_escribe() -> None:
    widget = _Widget(fg_color="#202020", border_width=1, border_color="#303030")

    configurar_si_cambia(
        widget, fg_color="#202020", border_width=1, border_color="#303030",
    )

    assert widget.escrituras == [], "se repintó el canvas para dejarlo igual"


def test_solo_viaja_lo_que_cambia() -> None:
    """Escribir de más cuesta lo mismo que escribirlo todo: es un repintado."""
    widget = _Widget(fg_color="#202020", border_width=1, border_color="#303030")

    configurar_si_cambia(
        widget, fg_color="#202020", border_width=3, border_color="#303030",
    )

    assert widget.escrituras == [{"border_width": 3}]
    assert widget.opciones["border_width"] == 3


def test_una_opcion_que_no_se_puede_leer_se_escribe() -> None:
    """Ante la duda, escribir: quedarse corto deja un dato viejo en pantalla."""
    widget = _Widget(fg_color="#202020")

    configurar_si_cambia(widget, fg_color="#202020", image=None)

    assert widget.escrituras == [{"image": None}]


def test_un_widget_muerto_no_revienta() -> None:
    class _Muerto:
        def cget(self, clave):
            raise RuntimeError("widget destruido")

        def configure(self, **kwargs):
            raise RuntimeError("widget destruido")

    try:
        configurar_si_cambia(_Muerto(), fg_color="#202020")
    except RuntimeError:
        pass                                   # lo gestiona quien llama
    else:
        raise AssertionError("debería propagar para que el que llama repinte")


def test_pasar_el_raton_no_repinta_la_pagina_entera() -> None:
    """`_apply_selection_styles` cuelga de cada `<Leave>` de cada tarjeta."""
    fuente = inspect.getsource(UnifiedTeamPCView._apply_selection_styles)
    assert "_configurar_si_cambia" in fuente
    assert "card.configure(" not in fuente
    assert "button.configure(" not in fuente


def test_los_caminos_calientes_comparan_antes_de_escribir() -> None:
    for metodo in (
        UnifiedTeamPCView.update_team_card,
        UnifiedTeamPCView.update_team_health,
        UnifiedTeamPCView._pc_cell,
    ):
        fuente = inspect.getsource(metodo)
        assert "_configurar_si_cambia" in fuente, metodo.__name__


def test_no_queda_ningun_configure_caro_dentro_de_un_bucle() -> None:
    """El patrón vuelve solo: lo natural al escribirlo es repintarlo todo.

    Se busca por AST, no por texto: un `configure` con opciones de color dentro
    de un bucle repinta el canvas de cada elemento aunque el valor sea el mismo,
    y esos bucles cuelgan de una tecla o del ratón.
    """
    import ast

    caras = {
        "fg_color", "border_color", "text_color", "progress_color", "hover_color",
        "bg_color", "border_width", "corner_radius", "image", "height", "width",
        "text_color_disabled",
    }
    raiz = Path(__file__).resolve().parent.parent

    class Buscador(ast.NodeVisitor):
        def __init__(self) -> None:
            self.bucle = 0
            self.hallazgos: list[tuple[int, str]] = []
            self.funcion = "?"

        def _en_bucle(self, nodo):
            self.bucle += 1
            self.generic_visit(nodo)
            self.bucle -= 1

        visit_For = _en_bucle
        visit_While = _en_bucle

        def visit_FunctionDef(self, nodo):
            previa, self.funcion = self.funcion, nodo.name
            previo, self.bucle = self.bucle, 0
            self.generic_visit(nodo)
            self.funcion, self.bucle = previa, previo

        def visit_Call(self, nodo):
            if (
                isinstance(nodo.func, ast.Attribute)
                and nodo.func.attr == "configure"
                and self.bucle > 0
                and {k.arg for k in nodo.keywords if k.arg} & caras
            ):
                self.hallazgos.append((nodo.lineno, self.funcion))
            self.generic_visit(nodo)

    sobran = []
    for ruta in sorted((raiz / "app").rglob("*.py")):
        buscador = Buscador()
        buscador.visit(ast.parse(ruta.read_text(encoding="utf-8")))
        for linea, funcion in buscador.hallazgos:
            sobran.append(f"{ruta.relative_to(raiz)}:{linea} en {funcion}()")

    assert not sobran, (
        "repintan el canvas dentro de un bucle; usa configurar_si_cambia:\n  "
        + "\n  ".join(sobran)
    )
