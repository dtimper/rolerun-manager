"""El roce de la tarjeta de equipo debe seguir vigente sobre cualquier hijo.

Reportado por el usuario 04-09-2026, en dos intentos:

1. Al pasar el ratón por las seis tarjetas de equipo, solo se marcaban como
   rozadas mientras el cursor estaba sobre el fondo de la tarjeta -en cuanto
   pasaba por encima de un texto, la barra de PS o cualquier otro contenido,
   el marcado desaparecía-.

   Causa: `_bind_hover_tree` solo enganchaba `<Enter>`/`<Leave>` en el widget
   raíz y en sus hijos DIRECTOS, a diferencia de `_bind_click_tree` -la
   función hermana para el clic-, que sí recorre todos los descendientes.

2. Enganchar también los nietos no bastó: pasó a marcarse SOLO en el borde
   de la tarjeta -la única franja sin ningún hijo debajo-.

   Causa: cada hijo de Tk es una ventana real propia. Moverse de la tarjeta
   a uno de sus hijos sigue disparando `<Leave>` en la tarjeta y `<Enter>` en
   el hijo, en ese orden, aunque el cursor nunca salió visualmente de la
   tarjeta. El `on_leave` de esta vista difiere su efecto (`after_idle`)
   mientras que `on_enter` actúa al momento, así que el `<Leave>` diferido
   siempre ganaba la carrera y deshacía el marcado justo después de que
   `<Enter>` lo hubiera puesto.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui_views.team_pc_view import UnifiedTeamPCView  # noqa: E402


class _WidgetFalso:
    """Lo mínimo que `_bind_hover_tree` necesita: enganchar, listar hijos y
    responder por su rectángulo en pantalla."""

    def __init__(
        self, hijos: list["_WidgetFalso"] | None = None, *,
        x: int = 0, y: int = 0, ancho: int = 100, alto: int = 100,
    ) -> None:
        self._hijos = list(hijos or [])
        self._x, self._y, self._ancho, self._alto = x, y, ancho, alto
        self.eventos: list[str] = []
        self.manejadores: dict[str, object] = {}

    def bind(self, secuencia: str, callback, add: str = "") -> None:
        self.eventos.append(secuencia)
        self.manejadores[secuencia] = callback

    def winfo_children(self) -> list["_WidgetFalso"]:
        return list(self._hijos)

    def winfo_rootx(self) -> int:
        return self._x

    def winfo_rooty(self) -> int:
        return self._y

    def winfo_width(self) -> int:
        return self._ancho

    def winfo_height(self) -> int:
        return self._alto


def _evento(x: int, y: int) -> SimpleNamespace:
    return SimpleNamespace(x_root=x, y_root=y)


def test_el_roce_llega_a_nietos_y_bisnietos() -> None:
    """El bug real: un texto dentro de una fila de estadísticas es un NIETO
    de la tarjeta (tarjeta -> content -> fila -> texto), no un hijo directo."""
    texto_nieto = _WidgetFalso()
    fila = _WidgetFalso([texto_nieto])
    barra_ps_bisnieta = _WidgetFalso()
    content = _WidgetFalso([fila, barra_ps_bisnieta])
    tarjeta = _WidgetFalso([content])

    UnifiedTeamPCView._bind_hover_tree(tarjeta, lambda _e=None: None, lambda _e=None: None)

    for widget in (tarjeta, content, fila, texto_nieto, barra_ps_bisnieta):
        assert "<Enter>" in widget.eventos, "un descendiente se quedó sin <Enter>"
        assert "<Leave>" in widget.eventos, "un descendiente se quedó sin <Leave>"


def test_un_widget_excluido_y_sus_hijos_no_se_enganchan() -> None:
    """El botón de información de rol (`info`) sigue sin marcar la tarjeta
    como rozada -ni él ni nada dentro de él-."""
    hijo_del_boton_info = _WidgetFalso()
    boton_info = _WidgetFalso([hijo_del_boton_info])
    tarjeta = _WidgetFalso([boton_info])

    UnifiedTeamPCView._bind_hover_tree(
        tarjeta, lambda _e=None: None, lambda _e=None: None, exclude={boton_info},
    )

    assert tarjeta.eventos == ["<Enter>", "<Leave>"]
    assert boton_info.eventos == []
    assert hijo_del_boton_info.eventos == []


def test_salir_de_un_hijo_hacia_otro_hijo_de_la_misma_tarjeta_no_deshace_el_roce() -> None:
    """El caso exacto reportado: la tarjeta ocupa (0,0)-(100,100). Un texto
    interior dispara `<Leave>` al salir hacia otro hijo, pero el cursor
    (50, 60) sigue dentro del rectángulo de la tarjeta -solo cambió de hijo-,
    así que `on_leave` no debe llamarse."""
    texto = _WidgetFalso(x=10, y=10, ancho=30, alto=10)
    tarjeta = _WidgetFalso([texto], x=0, y=0, ancho=100, alto=100)
    salidas: list[object] = []

    UnifiedTeamPCView._bind_hover_tree(
        tarjeta, lambda _e=None: None, lambda e=None: salidas.append(e),
    )

    # El texto dispara <Leave> al salir hacia otro hijo de la MISMA tarjeta:
    # el cursor sigue dentro del rectángulo de la tarjeta.
    texto.manejadores["<Leave>"](_evento(50, 60))
    assert salidas == [], "un cambio de hijo dentro de la misma tarjeta deshizo el roce"


def test_salir_de_verdad_de_la_tarjeta_si_deshace_el_roce() -> None:
    """El mismo texto, pero el cursor ya está fuera del rectángulo de la
    tarjeta: esta vez sí debe llamarse a `on_leave`."""
    texto = _WidgetFalso(x=10, y=10, ancho=30, alto=10)
    tarjeta = _WidgetFalso([texto], x=0, y=0, ancho=100, alto=100)
    salidas: list[object] = []

    UnifiedTeamPCView._bind_hover_tree(
        tarjeta, lambda _e=None: None, lambda e=None: salidas.append(e),
    )

    texto.manejadores["<Leave>"](_evento(500, 500))
    assert len(salidas) == 1
