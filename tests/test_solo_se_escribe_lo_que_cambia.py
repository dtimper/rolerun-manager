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
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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

    UnifiedTeamPCView._configurar_si_cambia(
        widget, fg_color="#202020", border_width=1, border_color="#303030",
    )

    assert widget.escrituras == [], "se repintó el canvas para dejarlo igual"


def test_solo_viaja_lo_que_cambia() -> None:
    """Escribir de más cuesta lo mismo que escribirlo todo: es un repintado."""
    widget = _Widget(fg_color="#202020", border_width=1, border_color="#303030")

    UnifiedTeamPCView._configurar_si_cambia(
        widget, fg_color="#202020", border_width=3, border_color="#303030",
    )

    assert widget.escrituras == [{"border_width": 3}]
    assert widget.opciones["border_width"] == 3


def test_una_opcion_que_no_se_puede_leer_se_escribe() -> None:
    """Ante la duda, escribir: quedarse corto deja un dato viejo en pantalla."""
    widget = _Widget(fg_color="#202020")

    UnifiedTeamPCView._configurar_si_cambia(widget, fg_color="#202020", image=None)

    assert widget.escrituras == [{"image": None}]


def test_un_widget_muerto_no_revienta() -> None:
    class _Muerto:
        def cget(self, clave):
            raise RuntimeError("widget destruido")

        def configure(self, **kwargs):
            raise RuntimeError("widget destruido")

    try:
        UnifiedTeamPCView._configurar_si_cambia(_Muerto(), fg_color="#202020")
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
