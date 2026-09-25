from __future__ import annotations

"""Tour de bienvenida: resalta una zona de la pantalla y explica qué hace.

Mismo reparto de ventanas que ``IntegratedRoleInfoPopover`` y
``TransparentWindowSurface`` -velo y contenido como ``CTkToplevel``
independientes, ver esos módulos para el porqué de fondo-, con dos añadidos
propios de un tour:

- El velo recorta un hueco totalmente transparente sobre la zona señalada.
  ``-alpha`` (atenúa lo que queda) y ``-transparentcolor`` (agujero real, sin
  atenuar) conviven en la misma ventana: Windows compone las dos capas.
- Una segunda ventana, sin ``-alpha`` y con ``-transparentcolor`` de fondo,
  dibuja el marco dorado y la flecha: solo el trazo es opaco, el resto de la
  ventana es invisible y deja pasar el clic a lo que haya debajo -incluida la
  propia zona señalada, que sigue siendo utilizable mientras el tour la
  explica.

Las tres ventanas (velo, marco+flecha, ficha) se crean UNA sola vez y se
reutilizan para todos los pasos -solo se mueven, redimensionan y repintan.
Antes cada paso destruía las tres y creaba tres nuevas, y ni construir las
nuevas antes de destruir las viejas ni forzar `update_idletasks()` bastaron
para quitar un parpadeo real de un frame a pantalla completa (hallazgos del
usuario 08-09-2026): crear una `CTkToplevel` nueva de verdad -no solo mover
una que ya existe- deja un instante fuera del control de este módulo en el
que Windows aún no ha terminado de componerla. No recrear ventanas de por
medio quita esa incertidumbre de raíz.
"""

from collections.abc import Callable
from dataclasses import dataclass

import customtkinter as ctk
import tkinter as tk

from app.config import GOLD, MUTED, TEXT

from .window_focus import guard_topmost_on_focus_loss, hide_from_taskbar_and_alttab, release_focus_guard

#: Color centinela de las ventanas con hueco o marco. Muy poco probable que
#: aparezca de verdad en la interfaz; si algún día colisiona, cambiarlo aquí
#: basta, no hay ningún otro sitio que lo repita.
_SENTINEL = "#0b0c0d"
_DIM_ALPHA = 0.55
_HIGHLIGHT_PAD = 8
_HIGHLIGHT_RADIUS = 14
#: 22px dejaba una flecha casi toda cabeza (arrowshape ocupa 16px de eso) y
#: apenas 6px de trazo visible -se veía como un tache suelto, no una
#: flecha-. 32 deja ~20px de trazo real con el mismo tamaño de cabeza.
_CARD_MARGIN = 32
_CARD_WRAP = 340
#: Sondeo de foco más rápido que el de otros popups (400 ms, ver
#: `window_focus._POLL_INTERVAL_MS`): un tour que tarda hasta 400 ms en
#: reaparecer al volver a la ventana principal se siente roto, no discreto.
_FOCUS_POLL_INTERVAL_MS = 100


@dataclass(frozen=True, slots=True)
class OnboardingTourStep:
    """Un paso del tour: a qué widget señalar y qué explicar de él.

    ``target`` es una función sin argumentos, no el widget directamente: para
    cuando haya varios pasos, el widget del segundo paso puede no existir
    todavía -o haber sido sustituido por un repintado- en el momento de
    construir la lista completa.
    """

    target: Callable[[], object]
    text: str
    title: str = ""


class BoundingBoxOf:
    """Adapta varios widgets hermanos a un único objetivo de tour.

    Expone la misma interfaz que ``_show_step`` pide de un widget
    (``update_idletasks``/``winfo_rootx``/``winfo_rooty``/``winfo_width``/
    ``winfo_height``), pero devuelve el rectángulo que envuelve a TODOS los
    widgets recibidos -recalculado en cada llamada, no una foto fija tomada
    al construir el paso-. Pensado para señalar un grupo de botones
    relacionados (p. ej. los atajos de objetos de la cabecera) con un único
    recuadro, sin tener que envolverlos en un frame propio solo para esto.
    """

    def __init__(self, *widgets) -> None:
        if not widgets:
            raise ValueError("BoundingBoxOf necesita al menos un widget")
        self._widgets = widgets

    def update_idletasks(self) -> None:
        for widget in self._widgets:
            widget.update_idletasks()

    def winfo_rootx(self) -> int:
        return min(int(w.winfo_rootx()) for w in self._widgets)

    def winfo_rooty(self) -> int:
        return min(int(w.winfo_rooty()) for w in self._widgets)

    def winfo_width(self) -> int:
        right = max(int(w.winfo_rootx()) + int(w.winfo_width()) for w in self._widgets)
        return right - self.winfo_rootx()

    def winfo_height(self) -> int:
        bottom = max(int(w.winfo_rooty()) + int(w.winfo_height()) for w in self._widgets)
        return bottom - self.winfo_rooty()


def _rounded_rect_points(x0: float, y0: float, x1: float, y1: float, radius: float) -> list[float]:
    radius = max(0.0, min(radius, (x1 - x0) / 2, (y1 - y0) / 2))
    return [
        x0 + radius, y0,
        x1 - radius, y0,
        x1, y0,
        x1, y0 + radius,
        x1, y1 - radius,
        x1, y1,
        x1 - radius, y1,
        x0 + radius, y1,
        x0, y1,
        x0, y1 - radius,
        x0, y0 + radius,
        x0, y0,
        x0 + radius, y0,
    ]


class OnboardingTour:
    """Recorre ``steps`` uno a uno; un clic en lo atenuado avanza al siguiente."""

    def __init__(
        self,
        master,
        steps: list[OnboardingTourStep],
        *,
        on_finished: Callable[[], None] | None = None,
        overlay_unsafe_check: Callable[[], bool] | None = None,
    ) -> None:
        self._root = master.winfo_toplevel()
        self._steps = list(steps)
        self._on_finished = on_finished
        self._overlay_unsafe_check = overlay_unsafe_check
        self._index = -1

        self._dim_window = None
        self._dim_canvas = None
        self._dim_shape_id = None
        self._fx_window = None
        self._fx_canvas = None
        self._fx_border_id = None
        self._fx_arrow_id = None
        self._card_window = None
        self._card_body = None
        self._windows: list[object] = []
        self._focus_guard = None

        self._resize_after_id: str | None = None
        self._configure_binding: str | None = None
        self._escape_binding = self._root.bind("<Escape>", self._finish, add="+")
        if self._steps:
            self._show_step(0)
        else:
            self._finish()
            return
        # El recuadro se calcula una vez, en coordenadas absolutas de pantalla:
        # si la ventana principal se mueve, se redimensiona o se maximiza
        # mientras el tour sigue abierto -algo muy normal justo al arrancar-,
        # el paso se queda apuntando a donde ESTABA el widget, no a donde está
        # ahora. Recomponerlo en el propio sitio es más simple y fiable que
        # intentar desplazar cada ventana a mano.
        self._configure_binding = self._root.bind("<Configure>", self._on_root_configure, add="+")

    # ---------- ciclo de un paso ----------

    @staticmethod
    def _destroy_windows(windows) -> None:
        for window in windows:
            try:
                if window.winfo_exists():
                    window.destroy()
            except Exception:
                pass

    def _advance(self, _event=None) -> str:
        next_index = self._index + 1
        if next_index >= len(self._steps):
            return self._finish()
        self._show_step(next_index)
        return "break"

    def _go_back(self, _event=None) -> str:
        if self._index > 0:
            self._show_step(self._index - 1)
        return "break"

    def _finish(self, _event=None) -> str:
        self._destroy_windows(self._windows)
        self._windows = []
        release_focus_guard(self._focus_guard)
        self._focus_guard = None
        self._dim_window = None
        self._dim_canvas = None
        self._dim_shape_id = None
        self._fx_window = None
        self._fx_canvas = None
        self._fx_border_id = None
        self._fx_arrow_id = None
        self._card_window = None
        self._card_body = None
        if self._resize_after_id is not None:
            try:
                self._root.after_cancel(self._resize_after_id)
            except Exception:
                pass
            self._resize_after_id = None
        for attribute, sequence in (("_escape_binding", "<Escape>"), ("_configure_binding", "<Configure>")):
            binding = getattr(self, attribute, None)
            if not binding:
                continue
            try:
                self._root.unbind(sequence, binding)
            except Exception:
                pass
            setattr(self, attribute, None)
        callback = self._on_finished
        self._on_finished = None
        if callback is not None:
            callback()
        return "break"

    def _on_root_configure(self, _event=None) -> None:
        """La ventana principal cambió de tamaño o posición: recomponer.

        `<Configure>` llega en ráfaga durante un arrastre de borde -uno por
        cada píxel-, y reconstruir tres ``CTkToplevel`` en cada uno sería
        visible y costoso. Se espera a que la ráfaga pare antes de recomponer.

        Tk entrega también aquí el `<Configure>` de CUALQUIER descendiente
        -la ventana raíz es uno de los bindtags de todo widget interior, así
        que cada casilla del PC redimensionándose dispara este mismo
        manejador-. Filtrar por ``event.widget`` es lo que separa un cambio
        real de la ventana principal del ruido de su propio contenido.
        """
        if _event is not None and getattr(_event, "widget", None) is not self._root:
            return
        if self._resize_after_id is not None:
            try:
                self._root.after_cancel(self._resize_after_id)
            except Exception:
                pass
        self._resize_after_id = self._root.after(150, self._reflow_current_step)

    def _reflow_current_step(self) -> None:
        self._resize_after_id = None
        if 0 <= self._index < len(self._steps) and self._windows:
            self._show_step(self._index)

    def _show_step(self, index: int) -> None:
        self._index = index
        step = self._steps[index]
        try:
            target = step.target()
            target.update_idletasks()
            tx = int(target.winfo_rootx())
            ty = int(target.winfo_rooty())
            tw = max(1, int(target.winfo_width()))
            th = max(1, int(target.winfo_height()))
        except Exception:
            # Sin el widget que hay que señalar no hay nada que resaltar en
            # ESTE paso -por ejemplo un botón que solo existe en algunos
            # juegos/estados-, pero eso no invalida el resto del tour: se
            # salta al siguiente en vez de cortarlo entero aquí. Las ventanas
            # ya construidas (si las hay) se dejan tal cual, mostrando el
            # último paso válido hasta que el siguiente las actualice.
            next_index = index + 1
            if next_index < len(self._steps):
                self._show_step(next_index)
            else:
                self._finish()
            return

        root = self._root
        root.update_idletasks()
        screen_w = max(1, int(root.winfo_width()))
        screen_h = max(1, int(root.winfo_height()))
        root_x = int(root.winfo_rootx())
        root_y = int(root.winfo_rooty())

        hx0 = tx - root_x - _HIGHLIGHT_PAD
        hy0 = ty - root_y - _HIGHLIGHT_PAD
        hx1 = hx0 + tw + _HIGHLIGHT_PAD * 2
        hy1 = hy0 + th + _HIGHLIGHT_PAD * 2

        self._ensure_dim_window(root, screen_w, screen_h, root_x, root_y)
        self._update_dim_hole(hx0, hy0, hx1, hy1)

        card_x, card_y, card_w, card_h = self._update_card(
            step, root_x, root_y, screen_w, screen_h, hx0, hy0, hx1, hy1,
        )

        self._ensure_fx_window(root, screen_w, screen_h, root_x, root_y)
        self._update_fx_shape(hx0, hy0, hx1, hy1, card_x - root_x, card_y - root_y, card_w, card_h)

        self._windows = [self._dim_window, self._fx_window, self._card_window]
        hide_from_taskbar_and_alttab(*self._windows)
        # El bug de verdad detrás de "la flecha no coincide con el recuadro"
        # (capturas del usuario 08-09-2026, en prácticamente todos los pasos):
        # NO era la flecha -su geometría siempre apuntaba bien, comprobado con
        # un diagnóstico aparte-, era que la VENTANA DE LA FICHA dejaba de
        # moverse de verdad a partir del segundo paso, aunque `.geometry()`
        # seguía recibiendo la posición nueva correcta en cada uno. Aislado
        # con réplicas mínimas (`three_window_repro.py`/`isolate_lift.py`):
        # con TRES `CTkToplevel` `-topmost` a la vez, llamar a `.lift()` sobre
        # más de una justo después de reposicionarlas -sin que Tk procese
        # antes esas peticiones de geometría pendientes- hace que Windows
        # descarte el movimiento de alguna de ellas; con una sola ventana
        # `-topmost`, o con un `update_idletasks()` de por medio, nunca pasaba.
        # `update_idletasks()` aquí, antes de reordenar el Z-order, le da a Tk
        # esa oportunidad y quita el atasco -confirmado en cinco pasos
        # seguidos con las tres ventanas reales presentes.
        root.update_idletasks()
        for window in self._windows:
            window.lift()
        if self._focus_guard is None:
            # Se crea una sola vez, sobre las mismas tres ventanas que van a
            # vivir todo el tour.
            #
            # Segundo intento (08-09-2026): una variante propia que solo
            # quitaba `-topmost` sin `.lower()`, para que el tour no
            # desapareciera del todo al cambiar de ventana. Revertido el
            # mismo día: sin bajarlas de verdad, un clic sobre el EMULADOR
            # dejaba el velo semitransparente mal ordenado frente a esa
            # superficie de juego -"empieza como a ver el juego y te
            # bloquea la pantalla"-, el mismo tipo de riesgo que ya obligó a
            # este mismo patrón (`_retire_initial_shell_when_ready`, ver su
            # comentario sobre Ryujinx) a comprobar el foco real en vez de
            # asumir que quitar `-topmost` basta.
            #
            # Tercer intento (mismo día): el guardia compartido con su
            # criterio por defecto ("el foco es de este proceso") evitaba el
            # glitch, pero desaparecía en CUALQUIER cambio de ventana.
            #
            # Cuarto intento (mismo día): se acotó el criterio a
            # `overlay_unsafe_check` -aquí,
            # `RoleRunManager._foreground_is_supported_emulator`-, asumiendo
            # que el riesgo era específico del emulador: el tour se quedaba
            # topmost sobre CUALQUIER OTRA ventana y solo se bajaba ante el
            # emulador. Revertido también: el usuario reprodujo el mismo
            # glitch con el Explorador de Windows en primer plano, no solo
            # con el emulador -la causa real es más general (cualquier
            # ventana ajena que el compositor de Windows esté repintando
            # activamente mientras nuestras tres capas siguen exigiendo
            # `-topmost`), no algo que se pueda acotar de forma fiable a una
            # lista de procesos conocidos.
            #
            # Quinto intento, el que queda: volver al criterio por defecto
            # del guardia compartido (`should_be_visible=None` →
            # `foreground_belongs_to_this_process`, sin pasar
            # `overlay_unsafe_check` desde `app/ui.py`) -el mismo patrón que
            # usan sin incidentes el resto de popups de este código base.
            # `.lower()` manda las tres ventanas de verdad detrás de
            # CUALQUIER aplicación ajena que pase a primer plano -así esa
            # ventana obtiene prioridad de verdad, no solo la pierde el
            # atributo `-topmost`-, y el sondeo a 100 ms las trae de vuelta
            # casi al instante en cuanto RoleRun recupera el foco: no hace
            # falta ningún paso adicional de "ocultar", el tour sigue abierto
            # todo el rato, solo se reordena.
            check = self._overlay_unsafe_check
            should_be_visible = None
            if check is not None:
                def should_be_visible() -> bool:
                    try:
                        return not check()
                    except Exception:
                        return True

            self._focus_guard = guard_topmost_on_focus_loss(
                root, *self._windows, interval_ms=_FOCUS_POLL_INTERVAL_MS,
                should_be_visible=should_be_visible,
            )

    # ---------- ventanas persistentes ----------

    def _ensure_dim_window(self, root, screen_w, screen_h, root_x, root_y) -> None:
        if self._dim_window is None or not self._dim_window.winfo_exists():
            dim = ctk.CTkToplevel(root)
            dim.overrideredirect(True)
            dim.attributes("-topmost", True)
            dim.attributes("-alpha", _DIM_ALPHA)
            dim.attributes("-transparentcolor", _SENTINEL)
            dim.configure(fg_color="#000000")
            canvas = tk.Canvas(dim, bg="#000000", highlightthickness=0, bd=0)
            canvas.pack(fill="both", expand=True)
            # Clic en lo atenuado = avanzar. El hueco recortado es, a su vez,
            # transparente al clic -cae hacia la zona señalada de verdad, que
            # sigue siendo utilizable.
            canvas.bind("<ButtonRelease-1>", self._advance, add="+")
            self._dim_window = dim
            self._dim_canvas = canvas
            self._dim_shape_id = None
        self._dim_window.geometry(f"{screen_w}x{screen_h}+{root_x}+{root_y}")

    def _update_dim_hole(self, hx0, hy0, hx1, hy1) -> None:
        points = _rounded_rect_points(hx0, hy0, hx1, hy1, _HIGHLIGHT_RADIUS)
        if self._dim_shape_id is None:
            self._dim_shape_id = self._dim_canvas.create_polygon(
                points, fill=_SENTINEL, outline=_SENTINEL, smooth=True,
            )
        else:
            self._dim_canvas.coords(self._dim_shape_id, *points)

    def _ensure_fx_window(self, root, screen_w, screen_h, root_x, root_y) -> None:
        if self._fx_window is None or not self._fx_window.winfo_exists():
            window = ctk.CTkToplevel(root)
            window.overrideredirect(True)
            window.attributes("-topmost", True)
            window.attributes("-transparentcolor", _SENTINEL)
            window.configure(fg_color=_SENTINEL)
            canvas = tk.Canvas(window, bg=_SENTINEL, highlightthickness=0, bd=0)
            canvas.pack(fill="both", expand=True)
            # El trazo es lo único opaco de esta ventana: pulsarlo también avanza.
            canvas.bind("<ButtonRelease-1>", self._advance, add="+")
            self._fx_window = window
            self._fx_canvas = canvas
            self._fx_border_id = None
            self._fx_arrow_id = None
        self._fx_window.geometry(f"{screen_w}x{screen_h}+{root_x}+{root_y}")

    def _update_fx_shape(self, hx0, hy0, hx1, hy1, card_x, card_y, card_w, card_h) -> None:
        border_points = _rounded_rect_points(hx0, hy0, hx1, hy1, _HIGHLIGHT_RADIUS)
        if self._fx_border_id is None:
            self._fx_border_id = self._fx_canvas.create_line(
                border_points, fill=GOLD, width=3, smooth=True, joinstyle=tk.ROUND,
            )
        else:
            self._fx_canvas.coords(self._fx_border_id, *border_points)

        start_x, start_y, end_x, end_y = self._arrow_endpoints(
            hx0, hy0, hx1, hy1, card_x, card_y, card_w, card_h,
        )
        if self._fx_arrow_id is None:
            self._fx_arrow_id = self._fx_canvas.create_line(
                start_x, start_y, end_x, end_y,
                fill=GOLD, width=3, arrow=tk.LAST, arrowshape=(14, 16, 6), capstyle=tk.ROUND,
            )
        else:
            self._fx_canvas.coords(self._fx_arrow_id, start_x, start_y, end_x, end_y)

    def _update_card(self, step, root_x, root_y, screen_w, screen_h, hx0, hy0, hx1, hy1):
        if self._card_window is None or not self._card_window.winfo_exists():
            window = ctk.CTkToplevel(self._root)
            window.overrideredirect(True)
            window.attributes("-topmost", True)
            self._card_window = window
            self._card_body = None
        window = self._card_window

        # El contenido (texto, botones) cambia de un paso a otro, pero la
        # ventana que lo aloja no: destruir y reconstruir el frame de dentro
        # es una operación normal de Tk sin ningún HWND de por medio, y no
        # tiene el parpadeo que sí tenía recrear la CTkToplevel entera.
        if self._card_body is not None:
            try:
                self._card_body.destroy()
            except Exception:
                pass

        card = ctk.CTkFrame(
            window, fg_color="#171717", corner_radius=16,
            border_width=2, border_color=GOLD,
        )
        card.pack(fill="both", expand=True)
        self._card_body = card

        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=22, pady=(18, 6))
        if step.title:
            ctk.CTkLabel(
                header, text=step.title, text_color=GOLD, anchor="w",
                font=ctk.CTkFont("Segoe UI", 16, "bold"),
            ).pack(side="left")
        ctk.CTkLabel(
            header, text=f"{self._index + 1} / {len(self._steps)}",
            text_color=MUTED, font=ctk.CTkFont("Segoe UI", 11, "bold"),
        ).pack(side="right")

        ctk.CTkLabel(
            card, text=step.text, text_color=TEXT, justify="left", anchor="w",
            wraplength=_CARD_WRAP, font=ctk.CTkFont("Segoe UI", 13),
        ).pack(fill="x", padx=22, pady=(0, 16))

        footer = ctk.CTkFrame(card, fg_color="transparent")
        footer.pack(fill="x", padx=22, pady=(0, 18))
        skip_button = ctk.CTkButton(
            footer, text="SALTAR TOUR", width=100, height=30,
            fg_color="transparent", hover_color="#242424",
            text_color=MUTED, font=ctk.CTkFont("Segoe UI", 11, "bold"),
        )
        skip_button.pack(side="left")
        skip_button.bind("<ButtonRelease-1>", self._finish, add="+")
        is_last = self._index >= len(self._steps) - 1
        next_button = ctk.CTkButton(
            footer, text="ENTENDIDO" if is_last else "SIGUIENTE",
            width=120, height=32, corner_radius=8, fg_color="transparent",
            hover_color="#332B1D", border_width=1, border_color=GOLD,
            text_color=GOLD, font=ctk.CTkFont("Segoe UI", 12, "bold"),
        )
        next_button.pack(side="right")
        next_button.bind("<ButtonRelease-1>", self._advance, add="+")
        if self._index > 0:
            back_button = ctk.CTkButton(
                footer, text="ANTERIOR", width=100, height=32, corner_radius=8,
                fg_color="transparent", hover_color="#242424", border_width=1,
                border_color="#4A4A4A", text_color=TEXT,
                font=ctk.CTkFont("Segoe UI", 12, "bold"),
            )
            back_button.pack(side="right", padx=(0, 8))
            back_button.bind("<ButtonRelease-1>", self._go_back, add="+")

        window.update_idletasks()
        card_w = max(320, card.winfo_reqwidth())
        card_h = max(120, card.winfo_reqheight())

        card_x, card_y = self._place_card(
            root_x, root_y, screen_w, screen_h, hx0, hy0, hx1, hy1, card_w, card_h,
        )
        window.geometry(f"{card_w}x{card_h}+{card_x}+{card_y}")
        return card_x, card_y, card_w, card_h

    @staticmethod
    def _place_card(root_x, root_y, screen_w, screen_h, hx0, hy0, hx1, hy1, card_w, card_h):
        """Prefiere la derecha del recuadro; si no cabe, abajo, izquierda, arriba.

        Centrada en el centro del recuadro, no en su esquina: un recuadro
        mucho más alto que la ficha -como el panel EQUIPO entero- dejaba la
        ficha pegada arriba y la flecha cruzando media pantalla en diagonal
        para alcanzarla.
        """
        hcx, hcy = (hx0 + hx1) / 2, (hy0 + hy1) / 2
        right_x = hx1 + _CARD_MARGIN
        if right_x + card_w <= screen_w:
            y = min(max(0.0, hcy - card_h / 2), screen_h - card_h)
            return root_x + int(right_x), root_y + int(y)
        below_y = hy1 + _CARD_MARGIN
        if below_y + card_h <= screen_h:
            x = min(max(0.0, hcx - card_w / 2), screen_w - card_w)
            return root_x + int(x), root_y + int(below_y)
        left_x = hx0 - _CARD_MARGIN - card_w
        if left_x >= 0:
            y = min(max(0.0, hcy - card_h / 2), screen_h - card_h)
            return root_x + int(left_x), root_y + int(y)
        above_y = hy0 - _CARD_MARGIN - card_h
        if above_y >= 0:
            x = min(max(0.0, hcx - card_w / 2), screen_w - card_w)
            return root_x + int(x), root_y + int(above_y)
        x = max(0.0, min(hcx - card_w / 2, screen_w - card_w))
        y = max(0.0, min(hcy - card_h / 2, screen_h - card_h))
        return root_x + int(x), root_y + int(y)

    @staticmethod
    def _arrow_endpoints(hx0, hy0, hx1, hy1, card_x, card_y, card_w, card_h):
        """Punta (``arrow=tk.LAST`` en el llamante) siempre en el recuadro.

        Bug encontrado el 08-09-2026 a partir de capturas del usuario ("no
        coincide la flecha con el recuadro" en prácticamente todos los
        pasos): las cuatro ramas devolvían ``(borde del recuadro, borde de
        la ficha)`` en ese orden, y como el llamante dibuja la punta en el
        SEGUNDO punto, la flecha señalaba hacia la ficha -que no necesita
        que se le señale, es autoevidente que es el texto- en vez de hacia
        el elemento resaltado, que es lo que de verdad hay que indicar. La
        distancia entre ambos bordes SÍ era correcta en los tres casos
        probados (`arrow_geometry_check.py`); solo la punta estaba en el
        extremo equivocado. Aquí se devuelve al revés: cola en la ficha,
        punta en el recuadro.
        """
        hcx, hcy = (hx0 + hx1) / 2, (hy0 + hy1) / 2
        if card_x >= hx1:  # ficha a la derecha del recuadro
            end_y = min(max(hcy, card_y + 16), card_y + card_h - 16)
            return card_x, end_y, hx1, hcy
        if card_x + card_w <= hx0:  # ficha a la izquierda
            end_y = min(max(hcy, card_y + 16), card_y + card_h - 16)
            return card_x + card_w, end_y, hx0, hcy
        if card_y >= hy1:  # ficha debajo
            end_x = min(max(hcx, card_x + 16), card_x + card_w - 16)
            return end_x, card_y, hcx, hy1
        if card_y + card_h <= hy0:  # ficha genuinamente encima, con margen real
            end_x = min(max(hcx, card_x + 16), card_x + card_w - 16)
            return end_x, card_y + card_h, hcx, hy0
        # Solapada de verdad -`_place_card` no encontró sitio en NINGUNA
        # dirección y centró la ficha dentro del propio recuadro-: no hay
        # ningún borde limpio al que apuntar sin cruzarlo entero. Bug
        # encontrado el 08-09-2026 con un recuadro casi del tamaño de toda
        # la pantalla (el primer paso de Drafteos, pensado como
        # introducción general sin señalar nada en concreto): la rama de
        # arriba asumía "encima, con margen pequeño" incluso aquí, y
        # devolvía una flecha vertical clavada desde el centro de la
        # ficha hasta `hy0` -el borde superior de un recuadro casi tan
        # alto como la ventana-, atravesando el propio marco de lado a
        # lado. Sin flecha (inicio y fin en el mismo punto, longitud cero)
        # es mejor que una que no señala nada real.
        return hcx, hcy, hcx, hcy
