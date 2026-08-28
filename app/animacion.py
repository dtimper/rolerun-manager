"""Mover cosas por la pantalla sin que cueste caro.

Una animación en Tk es una sucesión de ``place()``, y eso importa: mover un
widget cuesta poco, pero **reconfigurar colores cuesta 0,8–1,4 ms medidos** y a
sesenta fotogramas por segundo no hay presupuesto para eso. Por eso lo que se
anima aquí es la posición, nunca el aspecto.

## Por qué hay suavizado

Un movimiento a velocidad constante se lee como una animación de programa; uno
que arranca despacio, coge velocidad y frena al llegar se lee como un objeto.
Es la diferencia entre «se ha movido» y «lo he movido».

## Por qué se puede cancelar

Un Pokémon puede volar del PC al equipo justo cuando la página se repinta o el
usuario cierra la ventana. Un vuelo huérfano dejaría un sprite pegado en mitad
de la pantalla, así que todo vuelo se puede parar y siempre limpia lo suyo.
"""

from __future__ import annotations

import math
from typing import Any, Callable

#: Un fotograma. 16 ms son ~60 por segundo, que es lo que da Windows.
FOTOGRAMA_MS = 16

#: Lo que dura mover un Pokémon de un sitio a otro. Bastante para seguirlo con
#: la vista y poco para no estorbar a quien encadena movimientos.
VUELO_MS = 300


def suavizar(paso: float) -> float:
    """Arranca despacio, acelera y frena. Cúbica, de 0 a 1."""
    paso = max(0.0, min(1.0, paso))
    if paso < 0.5:
        return 4 * paso * paso * paso
    return 1 - ((-2 * paso + 2) ** 3) / 2


def altura_del_arco(paso: float, alto: float) -> float:
    """Cuánto se levanta el objeto a mitad de camino.

    Una línea recta entre dos paneles se lee como un corte de vídeo. Un arco
    pequeño convierte el salto en un recorrido.
    """
    return -math.sin(math.pi * max(0.0, min(1.0, paso))) * alto


def medida(widget: Any) -> tuple[int, int] | None:
    """Ancho y alto de un widget, o ``None`` si ya no está."""
    try:
        if not widget.winfo_exists():
            return None
        return int(widget.winfo_width()), int(widget.winfo_height())
    except Exception:
        return None


def centro_en_la_raiz(widget: Any, raiz: Any) -> tuple[int, int] | None:
    """Dónde está el centro de un widget, en coordenadas de la ventana.

    Los paneles están dentro de marcos con scroll, así que las coordenadas
    propias del widget no sirven: hay que pasar por las del escritorio y
    restarle el origen de la ventana.
    """
    try:
        if not widget.winfo_exists():
            return None
        x = widget.winfo_rootx() - raiz.winfo_rootx() + widget.winfo_width() // 2
        y = widget.winfo_rooty() - raiz.winfo_rooty() + widget.winfo_height() // 2
        return int(x), int(y)
    except Exception:
        return None


class Vuelo:
    """Lleva un widget de un punto a otro y lo destruye al llegar.

    El widget lo crea quien llama —así este módulo no sabe de sprites ni de
    customtkinter— y aquí solo se le mueve y se le retira.
    """

    def __init__(
        self,
        raiz: Any,
        movil: Any,
        desde: tuple[int, int],
        hasta: tuple[int, int],
        *,
        duracion_ms: int = VUELO_MS,
        arco: float = 0.0,
        desde_tam: tuple[int, int] | None = None,
        hasta_tam: tuple[int, int] | None = None,
        al_crecer: Callable[[float], None] | None = None,
        al_terminar: Callable[[], None] | None = None,
    ) -> None:
        self.raiz = raiz
        self.movil = movil
        self.desde = desde
        self.hasta = hasta
        self.duracion_ms = max(FOTOGRAMA_MS, int(duracion_ms))
        self.arco = float(arco)
        # Crecer mientras se viaja convierte «algo se ha movido» en «esto se
        # está convirtiendo en aquello». Es la diferencia entre un icono que
        # aterriza y una tarjeta que se forma.
        self.desde_tam = desde_tam
        self.hasta_tam = hasta_tam
        self.al_crecer = al_crecer
        self.al_terminar = al_terminar
        self.transcurrido = 0
        self._pendiente: Any = None
        self._acabado = False

    def empezar(self) -> "Vuelo":
        self._colocar(0.0)
        self._programar()
        return self

    def _programar(self) -> None:
        try:
            self._pendiente = self.raiz.after(FOTOGRAMA_MS, self._fotograma)
        except Exception:
            self.parar()

    def _colocar(self, paso: float) -> bool:
        suave = suavizar(paso)
        x = self.desde[0] + (self.hasta[0] - self.desde[0]) * suave
        y = self.desde[1] + (self.hasta[1] - self.desde[1]) * suave
        y += altura_del_arco(paso, self.arco)
        if self.desde_tam and self.hasta_tam:
            # El tamaño va por `configure`, no por `place`: customtkinter
            # rechaza `width`/`height` en `place` con un ValueError, y como aquí
            # todo está protegido, ese error se tragaba y mataba el vuelo en dos
            # fotogramas en vez de dar la cara.
            try:
                self.movil.configure(
                    width=int(
                        self.desde_tam[0]
                        + (self.hasta_tam[0] - self.desde_tam[0]) * suave
                    ),
                    height=int(
                        self.desde_tam[1]
                        + (self.hasta_tam[1] - self.desde_tam[1]) * suave
                    ),
                )
            except Exception:
                return False
        try:
            self.movil.place(x=int(x), y=int(y), anchor="center")
        except Exception:
            return False
        if self.al_crecer is not None:
            try:
                self.al_crecer(suave)
            except Exception:
                pass
        return True

    def _fotograma(self) -> None:
        self._pendiente = None
        if self._acabado:
            return
        self.transcurrido += FOTOGRAMA_MS
        paso = min(1.0, self.transcurrido / self.duracion_ms)
        if not self._colocar(paso):
            self.parar()
            return
        if paso >= 1.0:
            self.parar()
            return
        self._programar()

    def parar(self) -> None:
        """Retira el móvil y avisa. Se puede llamar dos veces sin efecto."""
        if self._acabado:
            return
        self._acabado = True
        if self._pendiente is not None:
            try:
                self.raiz.after_cancel(self._pendiente)
            except Exception:
                pass
            self._pendiente = None
        try:
            self.movil.destroy()
        except Exception:
            pass
        if self.al_terminar is not None:
            try:
                self.al_terminar()
            except Exception:
                pass
