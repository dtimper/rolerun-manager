from __future__ import annotations

import tkinter.font
from collections.abc import Callable
from typing import Any

import customtkinter as ctk

from app.config import DANGER, GOLD, MOVE_TYPE_INFO, MUTED, PANEL, PANEL_ALT, TEXT, move_type_fill
from app.ui_components.repintado import configurar_si_cambia
from app.ui_state.spatial_navigation import SpatialSelection, SpatialTarget, event_targets_text_input, keypress_sequences

SELECTED = "#73A9FF"

#: Las dos procedencias, en el orden en que se muestran.
PESTANAS: tuple[tuple[str, str], ...] = (("tm", "MT"), ("draft", "DRAFTEOS"))

#: Las tres categorías de daño que puede tener un movimiento, para el
#: filtro. `category_key` en cada entrada ya llega en estas mismas claves
#: (ver `RoleRunManager._damage_class_for_move`).
_CATEGORIAS_FILTRO: tuple[tuple[str, str], ...] = (
    ("physical", "FÍSICO"), ("special", "ESPECIAL"), ("status", "ESTADO"),
)


class GlobalTMView:
    """MOVIMIENTOS: lo que puedes enseñar hoy, venga de donde venga.

    A la izquierda, dos pestañas entre las que cambiar:

    - **MT**, lo que llevas en la mochila del juego.
    - **DRAFTEOS**, tiradas que te quedaste y todavía no has enseñado. Cada una
      ya costó su drafteo al guardarla, así que enseñarla no vuelve a cobrar.

    A la derecha, el equipo. Y ahí está el motivo de que sean pestañas y no dos
    columnas: **poniendo las dos listas a la vez no queda sitio para el equipo**,
    y sin el equipo delante no se ve de un vistazo quién puede aprender cada cosa
    y quién no. La lista se turna; el panel que informa, no.
    """

    def __init__(self, master, *, entries: tuple[dict[str, Any], ...], party: tuple[Any, ...],
                 identity_for: Callable[[Any], str], role_for: Callable[[Any], tuple[str, str]],
                 sprite_for: Callable[[Any, tuple[int, int]], Any],
                 role_icon_for: Callable[[str, int], Any | None],
                 on_choose: Callable[[dict[str, Any], Any], None], source_detail: str,
                 drafts: tuple[dict[str, Any], ...] = (),
                 on_choose_draft: Callable[[dict[str, Any], Any], None] | None = None,
                 on_delete_draft: Callable[[dict[str, Any]], None] | None = None,
                 sin_mt: str = "",
                 navigation_keys: dict[str, str] | None = None,
                 on_left_edge: Callable[[], None] | None = None,
                 on_edge_accept: Callable[[], bool] | None = None,
                 category_icons=None,
                 on_open_levelup_history: Callable[[Any], None] | None = None,
                 on_view_compatible_moves: Callable[[Any], None] | None = None) -> None:
        self.master, self.entries, self.party = master, entries, party
        self.drafts = tuple(drafts)
        self.identity_for, self.role_for, self.sprite_for = identity_for, role_for, sprite_for
        self.role_icon_for, self.on_choose, self.source_detail = role_icon_for, on_choose, source_detail
        # Recuerda-movimientos (2026-09-03): siempre disponible, sin importar
        # si el Pokémon puede aprender el movimiento seleccionado ahora mismo.
        self.on_open_levelup_history = on_open_levelup_history
        # Pedido del usuario el 2026-09-03: antes, ver qué MT admite cada
        # Pokémon solo pasaba por retroceder desde el paso "qué hueco
        # olvidará" después de elegir uno con ELEGIR —una pantalla que
        # aparecía sin haberla pedido nunca. Este botón la abre directo,
        # también siempre disponible.
        self.on_view_compatible_moves = on_view_compatible_moves
        self.category_icons = category_icons
        self.on_choose_draft, self.on_delete_draft = on_choose_draft, on_delete_draft
        #: Por qué no hay MT que listar, si es que no las hay.
        self.sin_mt = str(sin_mt or "")
        self.navigation_keys = dict(navigation_keys or {"accept": "z", "back": "x"})
        self.on_left_edge, self.on_edge_accept = on_left_edge, on_edge_accept
        self.navigation_guard: Callable[[], bool] | None = None
        self.navigation_intercept: Callable[[str], bool] | None = None
        self._external_navigation_focus = False
        # Sin mochila que enseñar, la pestaña útil es la otra: abrir en una
        # lista que solo puede explicar por qué está vacía es hacer perder
        # un clic a quien viene a por sus drafteos.
        self.pestana = "draft" if (sin_mt and drafts) else "tm"
        self.preview_key: tuple[str, int] | None = None
        self.selected_key: tuple[str, int] | None = None
        self._search_after = None
        self._images: list[Any] = []
        self._move_buttons: dict[tuple[str, int], Any] = {}
        # El marco de cada fila lleva el color de su tipo; `_update_highlight`
        # lo necesita para no pisarlo con el gris de siempre en cuanto cambia
        # la fila seleccionada.
        self._move_type_colors: dict[tuple[str, int], str] = {}
        # El contenedor visual (borde + relleno teñido) es `fila`, no el botón
        # `card` que hace clic/selección: pedido del usuario 02-09-2026, que
        # el marco envuelva también la columna de la descripción.
        self._move_frames: dict[tuple[str, int], Any] = {}
        # Etiquetas de descripción de la fila actual, para poder corregir su
        # `wraplength` en pasadas posteriores (ver `_reajustar_wraplengths`).
        # Cada entrada guarda también el texto ORIGINAL sin recortar -para
        # poder rehacer el recorte a como mucho 3 líneas contra el ancho
        # nuevo, no encadenar recortes sobre un texto ya recortado antes.
        self._description_labels: list[tuple[Any, str]] = []
        # Una sola instancia para medir Y para pintar: así el recorte a 3
        # líneas usa exactamente la misma fuente que se ve en pantalla
        # -pedido del usuario 02-09-2026, «sube mucho el tamaño de todas las
        # letras»-.
        self._fuente_descripcion = ctk.CTkFont("Segoe UI", 13)
        self._tab_buttons: dict[str, Any] = {}
        # Filtro por categoría/tipo (pedido del usuario 08-09-2026): conjunto
        # vacío = sin restricción en ese eje. Los dos ejes se combinan con Y
        # -una MT debe cumplir la categoría Y el tipo seleccionados-, cada uno
        # por dentro con O -cualquiera de las categorías marcadas vale-.
        self._filter_categories: set[str] = set()
        self._filter_types: set[int] = set()
        self._category_filter_buttons: dict[str, Any] = {}
        self._type_filter_buttons: dict[int, Any] = {}
        self._team_cards: dict[str, Any] = {}
        self._team_widgets: dict[str, tuple[Any, ...]] = {}
        # Botones navegables de cada tarjeta -ELEGIR y, si están disponibles,
        # VER MT COMPATIBLES/RECUERDA-MOVIMIENTOS-, en el orden en que las
        # flechas los recorren. Pedido del usuario 09-09-2026: antes solo se
        # podía seleccionar la tarjeta entera (equivalente a ELEGIR); estos
        # otros dos botones -"siempre disponibles", sin depender de si el
        # movimiento seleccionado encaja- no eran alcanzables con teclado/mando.
        self._team_action_buttons: dict[str, tuple[tuple[Any, Callable[[], None]], ...]] = {}
        # Qué botón de la tarjeta ACTUALMENTE seleccionada está resaltado.
        # Se reinicia a 0 (ELEGIR) en cuanto la selección cambia de tarjeta.
        self._keyboard_card_action_index = 0
        self._keyboard = SpatialSelection()
        self._keyboard_targets: dict[object, tuple[Any, Callable[[], None], str, int]] = {}
        self._bindings: list[tuple[str, str]] = []
        self._viewport_binding = None

        canvas = getattr(master, "_parent_canvas", None)
        viewport = int(canvas.winfo_height() or 0) if canvas is not None else 0
        # Pedido del usuario el 2026-09-03: tomar el MÁXIMO entre el viewport
        # real y la resta heurística (alto de la ventana menos una constante
        # fija) solía quedarse con la heurística, que casi siempre
        # sobrestima el hueco de verdad disponible dentro de `master` -un
        # `CTkScrollableFrame`-. Ese sobrante hacía que este panel midiera
        # más que lo visible, y con eso, que `master` tuviera scroll de
        # verdad para revelar nada más que hueco vacío -«scrolleo y baja la
        # página entera» aunque no había nada más que ver-. Con el viewport
        # ya asentado (razonablemente grande) se usa ESE, no el mayor de los
        # dos; la heurística queda solo para el primer instante, antes de
        # que Tk resuelva la geometría real.
        height = viewport if viewport >= 400 else max(480, int(master.winfo_toplevel().winfo_height() or 720) - 245)
        self.frame = ctk.CTkFrame(master, height=height, fg_color="#151515", corner_radius=16,
                                  border_width=1, border_color="#3A3A3A")
        self.frame.grid(row=0, column=0, sticky="nsew")
        self.frame.grid_propagate(False)
        self.frame.grid_columnconfigure(0, weight=5, uniform="global_tm")
        self.frame.grid_columnconfigure(1, weight=7, uniform="global_tm")
        self.frame.grid_rowconfigure(1, weight=1)

        heading = ctk.CTkFrame(self.frame, fg_color="transparent")
        heading.grid(row=0, column=0, columnspan=2, sticky="ew", padx=20, pady=(14, 10))
        heading.grid_columnconfigure(2, weight=1)
        self.search = ctk.CTkEntry(heading, width=300, height=36,
                                   placeholder_text="⌕  Buscar por MT o movimiento…")
        self.search.grid(row=0, column=0, sticky="w")
        # Filtro por categoría y tipo, combinables (pedido del usuario
        # 08-09-2026): un botón que despliega un panel propio en vez de un
        # `Toplevel` flotante -evita la complejidad de Z-order/foco de una
        # ventana aparte para algo que no necesita salirse de la propia
        # página.
        self.filter_button = ctk.CTkButton(
            heading, text="FILTRO", width=110, height=36, corner_radius=8,
            command=self._toggle_filter_panel,
            fg_color="transparent", hover_color=PANEL_ALT, border_width=1,
            border_color="#4A4A4A", text_color=TEXT,
            font=ctk.CTkFont("Segoe UI", 12, "bold"),
        )
        self.filter_button.grid(row=0, column=1, sticky="w", padx=(10, 0))
        ctk.CTkLabel(heading, text="ELIGE QUÉ ENSEÑAR", text_color=GOLD, anchor="w",
                     font=ctk.CTkFont("Segoe UI", 20, "bold")).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(9, 0),
        )
        self.filter_panel = ctk.CTkFrame(
            heading, fg_color="#111111", corner_radius=10,
            border_width=1, border_color="#3A3A3A",
        )
        self.filter_panel.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        self.filter_panel.grid_remove()
        self._build_filter_panel(self.filter_panel)
        self.search.bind("<KeyRelease>", self._schedule_filter, add="+")

        left = ctk.CTkFrame(self.frame, fg_color="#111111", corner_radius=12)
        left.grid(row=1, column=0, sticky="nsew", padx=(18, 7), pady=(0, 16))
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)
        self.tabs = ctk.CTkFrame(left, fg_color="transparent")
        self.tabs.grid(row=0, column=0, sticky="ew", padx=6, pady=(8, 4))
        self.tabs.grid_columnconfigure(tuple(range(len(PESTANAS))), weight=1, uniform="pestanas")
        for column, (clave, etiqueta) in enumerate(PESTANAS):
            boton = ctk.CTkButton(
                self.tabs, text=etiqueta, height=32, corner_radius=9,
                command=lambda value=clave: self.cambiar_pestana(value),
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
            )
            boton.grid(row=0, column=column, sticky="ew", padx=3)
            self._tab_buttons[clave] = boton
        self.list_scroll = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self.list_scroll.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        self.list_scroll.grid_columnconfigure(0, weight=1)

        self.team_panel = ctk.CTkFrame(self.frame, fg_color="#111111", corner_radius=12)
        self.team_panel.grid(row=1, column=1, sticky="nsew", padx=(7, 18), pady=(0, 16))
        self.team_panel.grid_rowconfigure(1, weight=1)
        self.team_panel.grid_columnconfigure(0, weight=1)
        self.team_title = ctk.CTkLabel(self.team_panel, text="POKÉMON COMPATIBLES", text_color=GOLD,
                                       font=ctk.CTkFont("Segoe UI", 14, "bold"))
        self.team_title.grid(row=0, column=0, sticky="w", padx=16, pady=(13, 4))
        # Pedido del usuario el 2026-09-03: con RECUERDA-MOVIMIENTOS y VER MT
        # COMPATIBLES, cada tarjeta necesita más alto del que le tocaba en un
        # reparto fijo de dos filas -se aplastaban los botones de la fila de
        # arriba y los de la fila de abajo quedaban directamente fuera-. Con
        # scroll propio, cada tarjeta mide lo que necesita de verdad.
        self.team_grid = ctk.CTkScrollableFrame(self.team_panel, fg_color="transparent")
        self.team_grid.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.team_grid.grid_columnconfigure((0, 1, 2), weight=1, uniform="tm_party")
        self.team_grid.grid_rowconfigure((0, 1), weight=1, uniform="tm_party")

        self._bind_keyboard()
        self._render_list()
        self._render_team()
        if canvas is not None:
            self._viewport_binding = canvas.bind(
                "<Configure>",
                lambda event: configurar_si_cambia(
                    self.frame,
                    # Pedido del usuario el 2026-09-03: `event.height` llega en
                    # píxeles FÍSICOS, pero `configure(height=...)` de un
                    # widget CTk ya establecido espera unidades LÓGICAS -sin
                    # convertir, con el escalado de CTk encima (1.12 por
                    # defecto), el marco salía más alto que el viewport real y
                    # su borde inferior no llegaba a cerrar. Mismo criterio que
                    # ya usa ``UnifiedTeamPCView`` (Equipo y PC, sin este fallo).
                    height=max(480, int(self.frame._reverse_widget_scaling(event.height))),
                ),
                add="+")
        for delay in (0, 80, 180, 400):
            self.frame.after(delay, self._fit_to_viewport)

    # ----------------------------------------------------------------- montaje

    def _fit_to_viewport(self) -> None:
        canvas = getattr(self.master, "_parent_canvas", None)
        try:
            height = int(canvas.winfo_height() or 0) if canvas is not None else 0
            if height >= 480:
                logical_height = int(self.frame._reverse_widget_scaling(height))
                configurar_si_cambia(self.frame, height=max(480, logical_height))
        except Exception:
            pass

    def destroy(self) -> None:
        # `winfo_toplevel()` sobre un frame ya destruido lanza TclError («bad
        # window path name»), y esto se llama justo al abrir otra Run, cuando
        # `_clear_root` puede haber arrasado el árbol antes. Era la única línea
        # sin proteger de todo el método.
        try:
            top = self.frame.winfo_toplevel()
        except Exception:
            top = None
        for sequence, binding in self._bindings:
            try:
                if top is not None:
                    top.unbind(sequence, binding)
            except Exception:
                pass
        canvas = getattr(self.master, "_parent_canvas", None)
        if canvas is not None and self._viewport_binding:
            try:
                canvas.unbind("<Configure>", self._viewport_binding)
            except Exception:
                pass
        try:
            self.frame.destroy()
        except Exception:
            pass

    def is_fully_composed(self) -> bool:
        try:
            self.frame.update_idletasks()
            return bool(self.frame.winfo_ismapped() and self.frame.winfo_width() > 800
                        and self.frame.winfo_height() > 450 and self.team_panel.winfo_ismapped())
        except Exception:
            return False

    def update_entries(self, entries: tuple[dict[str, Any], ...], party: tuple[Any, ...],
                       drafts: tuple[dict[str, Any], ...] | None = None) -> None:
        """Publica el readback conservando pestaña, posición y previsualización."""
        fraction = self._scroll_fraction()
        self.entries, self.party = entries, party
        if drafts is not None:
            self.drafts = tuple(drafts)
        self._render_list()
        self._render_team()
        self._restore_scroll(fraction)

    # --------------------------------------------------------------- pestañas

    def cambiar_pestana(self, pestana: str) -> None:
        if pestana not in {clave for clave, _etiqueta in PESTANAS}:
            return
        if pestana == self.pestana:
            return
        self.pestana = pestana
        # La previsualización pertenece a la lista que se estaba viendo. Al
        # cambiar de pestaña se recalcula, o el panel del equipo se quedaría
        # informando sobre un movimiento que ya no está en pantalla.
        self.preview_key = None
        self._render_list()
        self._render_team()

    def _pintar_pestanas(self) -> None:
        for clave, boton in self._tab_buttons.items():
            activa = clave == self.pestana
            cuantos = len(self._filtradas(clave))
            etiqueta = dict(PESTANAS)[clave]
            configurar_si_cambia(
                boton,
                text=f"{etiqueta}  ·  {cuantos}",
                fg_color=GOLD if activa else "transparent",
                hover_color="#D3AF70" if activa else PANEL_ALT,
                text_color="#111111" if activa else MUTED,
                border_width=0 if activa else 1,
                border_color="#3A3A3A",
            )

    # ---------------------------------------------------------------- filtro

    def _build_filter_panel(self, panel) -> None:
        ctk.CTkLabel(
            panel, text="CATEGORÍA", text_color=GOLD,
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 4))
        category_row = ctk.CTkFrame(panel, fg_color="transparent")
        category_row.grid(row=1, column=0, sticky="w", padx=14, pady=(0, 10))
        for index, (key, label) in enumerate(_CATEGORIAS_FILTRO):
            boton = ctk.CTkButton(
                category_row, text=label, width=100, height=30, corner_radius=8,
                command=lambda value=key: self._toggle_category_filter(value),
                fg_color="transparent", hover_color=PANEL_ALT, border_width=1,
                border_color="#4A4A4A", text_color=TEXT,
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
            )
            boton.grid(row=0, column=index, padx=(0, 8))
            self._category_filter_buttons[key] = boton

        ctk.CTkLabel(
            panel, text="TIPO", text_color=GOLD,
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
        ).grid(row=2, column=0, sticky="w", padx=14, pady=(0, 4))
        type_grid = ctk.CTkFrame(panel, fg_color="transparent")
        type_grid.grid(row=3, column=0, sticky="w", padx=14, pady=(0, 6))
        columnas = 9
        for index, (type_id, (label, color)) in enumerate(MOVE_TYPE_INFO.items()):
            boton = ctk.CTkButton(
                type_grid, text=label, width=92, height=28, corner_radius=8,
                command=lambda value=type_id: self._toggle_type_filter(value),
                fg_color="transparent", hover_color=PANEL_ALT, border_width=2,
                border_color=color, text_color=TEXT,
                font=ctk.CTkFont("Segoe UI", 10, "bold"),
            )
            boton.grid(row=index // columnas, column=index % columnas, padx=4, pady=4)
            self._type_filter_buttons[type_id] = boton

        footer = ctk.CTkFrame(panel, fg_color="transparent")
        footer.grid(row=4, column=0, sticky="ew", padx=14, pady=(2, 12))
        ctk.CTkButton(
            footer, text="LIMPIAR FILTROS", height=30, width=150, corner_radius=8,
            command=self._clear_filters,
            fg_color="transparent", hover_color=PANEL_ALT, border_width=1,
            border_color="#4A4A4A", text_color=MUTED,
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
        ).pack(side="left")

    def _toggle_filter_panel(self) -> None:
        if self.filter_panel.winfo_ismapped():
            self.filter_panel.grid_remove()
        else:
            self.filter_panel.grid()

    def _toggle_category_filter(self, category: str) -> None:
        if category in self._filter_categories:
            self._filter_categories.discard(category)
        else:
            self._filter_categories.add(category)
        self._apply_filter_change()

    def _toggle_type_filter(self, type_id: int) -> None:
        if type_id in self._filter_types:
            self._filter_types.discard(type_id)
        else:
            self._filter_types.add(type_id)
        self._apply_filter_change()

    def _clear_filters(self) -> None:
        if not self._filter_categories and not self._filter_types:
            return
        self._filter_categories.clear()
        self._filter_types.clear()
        self._apply_filter_change()

    def _apply_filter_change(self) -> None:
        self._paint_filter_chips()
        self._update_filter_button_label()
        self._render_list()
        self._render_team()

    def _paint_filter_chips(self) -> None:
        for key, boton in self._category_filter_buttons.items():
            seleccionada = key in self._filter_categories
            configurar_si_cambia(
                boton,
                fg_color=GOLD if seleccionada else "transparent",
                text_color="#111111" if seleccionada else TEXT,
                border_width=0 if seleccionada else 1,
            )
        for type_id, boton in self._type_filter_buttons.items():
            seleccionado = type_id in self._filter_types
            _nombre, color = MOVE_TYPE_INFO.get(type_id, (None, "#3A3A3A"))
            configurar_si_cambia(
                boton,
                fg_color=color if seleccionado else "transparent",
                text_color="#111111" if seleccionado else TEXT,
                border_width=0 if seleccionado else 2,
            )

    def _update_filter_button_label(self) -> None:
        total = len(self._filter_categories) + len(self._filter_types)
        activo = total > 0
        configurar_si_cambia(
            self.filter_button,
            text=f"FILTRO  ·  {total}" if activo else "FILTRO",
            fg_color=GOLD if activo else "transparent",
            text_color="#111111" if activo else TEXT,
            border_width=0 if activo else 1,
        )

    def _pasa_filtro(self, entry: dict[str, Any]) -> bool:
        if self._filter_categories and str(entry.get("category_key", "")) not in self._filter_categories:
            return False
        if self._filter_types:
            type_id = entry.get("type_id")
            if not isinstance(type_id, int) or type_id not in self._filter_types:
                return False
        return True

    # -------------------------------------------------------------- las listas

    @staticmethod
    def _clave(entry: dict[str, Any]) -> tuple[str, int]:
        return (str(entry.get("kind", "tm")), int(entry.get("move_id", 0) or 0))

    def _todas(self) -> tuple[dict[str, Any], ...]:
        return (*self.entries, *self.drafts)

    def _buscar(self, clave: tuple[str, int] | None) -> dict[str, Any] | None:
        if clave is None:
            return None
        return next((item for item in self._todas() if self._clave(item) == clave), None)

    def _consulta(self) -> str:
        try:
            return self.search.get().strip().casefold()
        except Exception:
            return ""

    def _filtradas(self, pestana: str | None = None) -> tuple[dict[str, Any], ...]:
        query = self._consulta()
        if (pestana or self.pestana) == "draft":
            base = tuple(item for item in self.drafts if not query or query in
                         f"{item['move_name']} {item.get('role', '')}".casefold())
        else:
            base = tuple(item for item in self.entries if not query or query in
                         f"mt{int(item['number']):02d} {item['move_name']}".casefold())
        return tuple(item for item in base if self._pasa_filtro(item))

    def _schedule_filter(self, _event=None) -> None:
        if self._search_after is not None:
            try:
                self.frame.after_cancel(self._search_after)
            except Exception:
                pass
        self._search_after = self.frame.after(90, self._filter_now)

    def _filter_now(self) -> None:
        self._search_after = None
        self._render_list()
        self._render_team()

    def _scroll_fraction(self) -> float:
        canvas = getattr(self.list_scroll, "_parent_canvas", None)
        try:
            return float(canvas.yview()[0]) if canvas is not None else 0.0
        except Exception:
            return 0.0

    def _restore_scroll(self, fraction: float) -> None:
        canvas = getattr(self.list_scroll, "_parent_canvas", None)
        if canvas is not None:
            self.frame.after_idle(lambda: canvas.yview_moveto(max(0.0, min(1.0, fraction))))

    def _render_list(self) -> None:
        for child in self.list_scroll.winfo_children():
            child.destroy()
        self._move_buttons.clear()
        self._move_type_colors.clear()
        self._move_frames.clear()
        self._description_labels.clear()
        filtradas = self._filtradas()
        claves = {self._clave(item) for item in filtradas}
        if filtradas and self.preview_key not in claves:
            self.preview_key = self._clave(filtradas[0])
        if not filtradas:
            self.preview_key = None
            hay_filtro_activo = bool(self._filter_categories or self._filter_types)
            origen = self.drafts if self.pestana == "draft" else self.entries
            if hay_filtro_activo and origen:
                # Distingue de un buscador vacío -pedido del usuario
                # 08-09-2026-: si SIN el filtro ya habría algo que enseñar,
                # el filtro es la razón real de la lista vacía, no la falta
                # de MT/drafteos.
                vacio = "Ningún movimiento coincide con los filtros seleccionados."
            elif self.pestana == "draft":
                vacio = ("Todavía no has guardado ningún drafteo.\n"
                         "En Drafteos, tira y pulsa GUARDAR para dejarlo aquí.")
            elif self.sin_mt:
                vacio = self.sin_mt
            else:
                vacio = "No tienes ninguna MT que coincida con la búsqueda."
            ctk.CTkLabel(
                self.list_scroll, text=vacio, text_color=MUTED, justify="center",
                wraplength=330,
                font=ctk.CTkFont("Segoe UI", 13, "bold")).grid(row=0, column=0, pady=70, padx=12)
        ancho_descripcion = self._ancho_para_la_descripcion()
        for row, entry in enumerate(filtradas):
            self._fila(row, entry, ancho_descripcion)
        self._pintar_pestanas()
        self._update_highlight()
        self._rebuild_keyboard()
        # Medir aquí puede llegar demasiado pronto: la primera vez que se
        # construye esta vista, `self.frame` acaba de crearse y Tk todavía
        # no resolvió su geometría real -el ancho medido cae al valor de
        # reserva (420) y el `wraplength` sale mal calculado desde el
        # principio. Se corrige en varias pasadas posteriores, igual que ya
        # hace `_fit_to_viewport`. Pedido repetido del usuario 02-09-2026:
        # «el borde sigue sin llegar al final».
        for delay in (0, 80, 200, 450):
            self.frame.after(delay, self._reajustar_wraplengths)

    def _reajustar_wraplengths(self) -> None:
        if not self._description_labels:
            return
        nuevo_ancho = self._ancho_para_la_descripcion()
        for etiqueta, original in self._description_labels:
            try:
                configurar_si_cambia(
                    etiqueta,
                    wraplength=nuevo_ancho,
                    text=self._texto_recortado_a_lineas(original, nuevo_ancho),
                )
            except Exception:
                pass

    def _fuente_de_medicion(self, tamano: int, *, negrita: bool = False) -> tkinter.font.Font:
        """Fuente de MEDIDA al tamaño REAL que acaba pintando CustomTkinter
        -no al lógico que se le da a `CTkFont`-. `ctk.set_widget_scaling(1.12)`
        (en `ui.py`) hace que lo que de verdad se pinta sea
        `round(tamaño * 1.12)`, un redondeo que NO coincide exactamente con
        escalar el ancho de envoltura, que no se redondea. Esa diferencia de
        ~3% bastaba para que una línea que «cabía» a mano no cupiera de
        verdad, y Tk la partiera otra vez por su cuenta -pedido del usuario
        02-09-2026, «hay saltos de línea innecesarios»-. Medir con el tamaño
        REAL, la misma cuenta que hace CustomTkinter por dentro, lo evita."""
        escala = self.list_scroll._get_widget_scaling()
        return tkinter.font.Font(
            family="Segoe UI", size=-abs(round(tamano * escala)),
            weight="bold" if negrita else "normal",
        )

    def _ancho_real(self, ancho_px: int) -> int:
        escala = self.list_scroll._get_widget_scaling()
        return max(1, int(ancho_px * escala))

    def _envolver_multilinea(self, texto: str, ancho_px: int, tamano: int, *, negrita: bool = False) -> str:
        """Envuelve CADA línea de `texto` -puede llegar con saltos de línea
        propios, como el título+detalle del botón- contra `ancho_px`, sin
        recortar nada. Pedido del usuario 02-09-2026: «no puede ser que haya
        una casilla más grande que otra» -`CTkButton` no admite `wraplength`,
        así que el envoltorio hay que hacerlo a mano para que un título largo
        no le pida a su columna más ancho del que le toca."""
        fuente = self._fuente_de_medicion(tamano, negrita=negrita)
        ancho_real_px = self._ancho_real(ancho_px)
        resultado: list[str] = []
        for parrafo in texto.split("\n"):
            palabras = parrafo.split()
            if not palabras:
                resultado.append(parrafo)
                continue
            lineas = [palabras[0]]
            for palabra in palabras[1:]:
                candidato = f"{lineas[-1]} {palabra}"
                if fuente.measure(candidato) <= ancho_real_px:
                    lineas[-1] = candidato
                else:
                    lineas.append(palabra)
            resultado.append("\n".join(lineas))
        return "\n".join(resultado)

    def _texto_recortado_a_lineas(self, texto: str, ancho_px: int, max_lineas: int = 3) -> str:
        """Envuelve `texto` a mano contra `ancho_px` y lo recorta a como
        mucho `max_lineas`, con «…» al final si sobra texto. Pedido del
        usuario 02-09-2026: «si ocupa 4 líneas, que ponga puntos suspensivos
        al final de la tercera» -el recorte por número de caracteres de
        antes no correspondía a un número de líneas fijo, según lo larga que
        fuera cada palabra."""
        fuente = self._fuente_de_medicion(13)
        ancho_real_px = self._ancho_real(ancho_px)
        palabras = texto.split()
        if not palabras:
            return texto
        lineas: list[str] = []
        resto = list(palabras)
        while resto and len(lineas) < max_lineas:
            linea = resto.pop(0)
            while resto and fuente.measure(f"{linea} {resto[0]}") <= ancho_real_px:
                linea = f"{linea} {resto.pop(0)}"
            lineas.append(linea)
        if not resto:
            return "\n".join(lineas)
        ultima = lineas[-1] if lineas else ""
        while ultima and fuente.measure(f"{ultima}…") > ancho_real_px:
            partes = ultima.rsplit(" ", 1)
            ultima = partes[0] if len(partes) == 2 else ultima[:-1]
        lineas = lineas[:-1] + [f"{ultima}…"] if lineas else ["…"]
        return "\n".join(lineas)

    def _ancho_para_la_descripcion(self) -> int:
        """Ancho en píxeles para el `wraplength` de la descripción, medido
        contra el scroll real -no adivinado ni dependiente de que Tk dispare
        un `<Configure>` a tiempo-. Pedido repetido del usuario 02-09-2026:
        el borde se salía porque el ancho de la columna nunca se conocía de
        verdad antes de fijar el envoltorio del texto.
        """
        self.list_scroll.update_idletasks()
        canvas = getattr(self.list_scroll, "_parent_canvas", None)
        ancho_total = int(canvas.winfo_width()) if canvas is not None else 0
        if ancho_total <= 1:
            ancho_total = max(1, int(self.frame.winfo_width() or 0)) * 5 // 12 or 420
        # `fila` resta el padx (4 por lado) al ancho del scroll; sus dos
        # columnas son iguales (weight=1 cada una), así que la mitad de eso
        # es lo que le toca de verdad a la descripción, menos su propio padx
        # y la esquina del tipo -que vive encima, no al lado, y necesita
        # margen propio-. Un 0.8 de más colchón: pedido repetido del usuario
        # 02-09-2026, «el borde sigue sin llegar al final» / «haz que el
        # texto no pueda llegar tan lejos».
        ancho_fila = max(120, ancho_total - 12)
        return max(80, int((ancho_fila // 2 - 32) * 0.8))

    def _fila(self, row: int, entry: dict[str, Any], ancho_descripcion: int) -> None:
        clave = self._clave(entry)
        es_drafteo = clave[0] == "draft"
        if es_drafteo:
            rol = str(entry.get("role", "")) or "cualquier rol"
            titulo = str(entry["move_name"])
            detalle = (f"{rol}  ·  Pot. {entry['power']}  ·  "
                       f"Prec. {entry['accuracy']}  ·  PP {entry['pp']}")
        else:
            titulo = f"MT{int(entry['number']):02d}   {entry['move_name']}"
            detalle = (f"Pot. {entry['power']}  ·  "
                       f"Prec. {entry['accuracy']}  ·  PP {entry['pp']}  ·  x{entry['quantity']}")
        # Pedido del usuario 02-09-2026: la categoría como icono -el que
        # aportó- en vez de la palabra "FÍSICO"/"ESPECIAL"/"ESTADO". Tamaño
        # subido de 32 a 40 junto con el resto de letras -mismo pedido,
        # «sube mucho el tamaño de todas las letras»-.
        category_icon = (
            self.category_icons.image(str(entry.get("category_key", "")), 40)
            if self.category_icons else None
        )
        type_id = entry.get("type_id")
        type_name, type_color = (
            MOVE_TYPE_INFO.get(type_id, (None, None)) if isinstance(type_id, int) else (None, None)
        )
        if type_color:
            self._move_type_colors[clave] = type_color
        relleno = move_type_fill(type_color, PANEL) if type_color else PANEL

        # Pedido del usuario 02-09-2026: en una columna a la derecha del
        # título y el detalle, no debajo -la primera versión la metía como
        # tercera línea dentro del propio botón-, y DENTRO del marco de tipo,
        # no fuera de él -la segunda versión coloreaba solo el botón de la
        # izquierda-. El recorte real a como mucho 3 líneas -con «…» si sobra-
        # se hace más abajo, contra el ancho de columna ya calculado: aquí
        # solo se guarda el texto ORIGINAL sin tocar.
        descripcion = str(entry.get("description") or "").strip()

        # `fila` es ahora el propio marco visible -borde y relleno teñidos
        # del tipo-, no un envoltorio transparente: la papelera se sigue
        # poniendo ENCIMA de todo porque un `CTkButton` no admite hijos
        # colocados sobre su lienzo sin estorbar a su propio texto.
        #
        # Sin alto fijo ni `grid_propagate(False)`: con eso, una fila con
        # descripción larga crecía por dentro pero el marco se quedaba en
        # los 66 px de siempre -el borde no llegaba al final de la casilla,
        # pedido del usuario 02-09-2026-. Ahora la fila mide lo que su
        # contenido más alto necesite, y el marco crece con ella.
        fila = ctk.CTkFrame(
            self.list_scroll, fg_color=relleno, corner_radius=10,
            border_width=2 if type_color else 1,
            border_color=type_color or "#3A3A3A",
            cursor="hand2",
        )
        fila.grid(row=row, column=0, sticky="ew", padx=4, pady=4)
        # Pedido del usuario 02-09-2026: más margen para la descripción -era
        # la mitad de ancho que el título/detalle; ahora se reparten igual-.
        fila.grid_columnconfigure(0, weight=1, uniform="fila_movimiento")
        fila.grid_columnconfigure(1, weight=1, uniform="fila_movimiento")
        self._move_frames[clave] = fila
        if category_icon is not None:
            self._images.append(category_icon)
        # `fg_color=relleno`, no "transparent": encontrado por fin -pedido
        # repetido del usuario 02-09-2026, «el borde no envuelve todo»-. El
        # rectángulo del botón (sin `padx`/`pady` propio) llega hasta el
        # borde de `fila` arriba y abajo; "transparent" en un `CTkButton` no
        # es una ausencia real de fondo, resuelve a un color congelado en el
        # momento de crearse que puede no coincidir con el `relleno` teñido
        # de `fila` -tapando su borde en la franja donde vive el botón.
        # Pintar el mismo color a mano sí garantiza la coincidencia exacta.
        # Sin `height` fijo: con 66 px puestos a mano, el botón se estiraba a
        # ocupar toda la fila -que puede medir mucho más si la descripción
        # es larga- y su texto quedaba pegado arriba en vez de centrado.
        # Pedido del usuario 02-09-2026: «los textos estén alineados
        # verticalmente en el centro»; sin un alto impuesto, el botón mide
        # lo que su propio contenido pide y `grid` lo centra solo en el
        # sobrante de la fila.
        # Pedido del usuario 02-09-2026: «no puede ser que haya una casilla
        # más grande que otra» -sin tope, un título largo podía pedir más
        # ancho del que le tocaba a esta columna (las dos son `uniform`,
        # iguales entre sí DENTRO de una fila), forzando esa fila entera a
        # medir más que sus vecinas. `CTkButton` no admite `wraplength`
        # -reventaba con un `ValueError`-, así que el envoltorio se hace a
        # mano contra el mismo ancho que la descripción: son las dos mitades
        # de la misma fila.
        texto_boton = self._envolver_multilinea(f"{titulo}\n{detalle}", ancho_descripcion, 15, negrita=True)
        card = ctk.CTkButton(
            fila, text=texto_boton,
            image=category_icon, compound="left",
            command=lambda value=clave: self._select(value), anchor="w",
            fg_color=relleno, hover_color=PANEL_ALT, border_width=0,
            text_color=TEXT, font=ctk.CTkFont("Segoe UI", 15, "bold"),
            cursor="hand2")
        # Sin "n"/"s" en el sticky: si la fila crece por la descripción, el
        # botón se centra en el alto sobrante en vez de quedarse pegado
        # arriba -pedido del usuario 02-09-2026, «centra más el texto en
        # cuanto a lo vertical»-. "w", no "center": centrado dejaba un hueco
        # vacío a la izquierda -pedido del usuario 02-09-2026, «trae hacia
        # ahí los iconos»-.
        card.grid(row=0, column=0, sticky="ew", padx=(6, 0))
        self._move_buttons[clave] = card
        etiqueta_descripcion = None
        if descripcion:
            # `wraplength` fijo, calculado antes de construir la fila contra
            # el ancho real del scroll -no adivinado ni dependiente de un
            # evento `<Configure>` que puede no llegar a tiempo-. Pedido
            # repetido del usuario 02-09-2026: «sigue sin verse el marco
            # completo».
            #
            # Pedido del usuario 02-09-2026, otra vuelta: «no está bien
            # alineado en el centro verticalmente» -el intento anterior
            # -anclarla arriba- solo maquillaba el síntoma real: el recorte
            # a 3 líneas media mal (ver `_texto_recortado_a_lineas`) y
            # dejaba una cuarta línea de más, alargando la fila mucho más de
            # lo necesario. Arreglado el recorte, centrada -sin "n"/"s"- es
            # lo que pidió el usuario la vez anterior a esa.
            texto_recortado = self._texto_recortado_a_lineas(descripcion, ancho_descripcion)
            etiqueta_descripcion = ctk.CTkLabel(
                fila, text=texto_recortado, text_color=MUTED, anchor="w", justify="left",
                wraplength=ancho_descripcion, font=self._fuente_descripcion,
                cursor="hand2",
            )
            etiqueta_descripcion.grid(row=0, column=1, sticky="ew", padx=(14, 10), pady=(10, 10))
            self._description_labels.append((etiqueta_descripcion, descripcion))
        insignia_tipo = None
        if type_name:
            insignia_tipo = ctk.CTkLabel(
                fila, text=type_name, text_color="#111111", fg_color=type_color,
                corner_radius=5, font=ctk.CTkFont("Segoe UI", 9, "bold"),
                cursor="hand2",
            )
            insignia_tipo.place(relx=1.0, rely=0.0, anchor="ne", x=-6, y=4)
        # Pedido del usuario 02-09-2026: que se pueda pulsar la casilla
        # entera, no solo la parte del botón -la columna de la descripción
        # se quedaba sin reaccionar al clic-. El propio `.bind()` de
        # `CTkFrame`/`CTkLabel` ya reenvía al `Canvas`/`Label` interno que de
        # verdad recibe el clic (ver sus `bind()`, comprobado aparte); vincular
        # también a mano esos internos duplicaría la llamada. `card` no hace
        # falta aquí: su propio `command=` ya selecciona al pulsarlo.
        #
        # Pedido del usuario 02-09-2026, otra vuelta: «para que cambie de MT
        # tengo que ponerme encima del nombre» -el aviso previo (pasar el
        # ratón cambia qué Pokémon se ven a la derecha) solo estaba en
        # `card`, no en el resto de la casilla-. Ahora pasar el ratón por
        # cualquier punto de la fila también actualiza esa previsualización.
        abrir_fila = lambda _event, value=clave: self._select(value)
        previsualizar_al_pasar = lambda _event, value=clave: self._preview(value)
        for objetivo in (fila, card, etiqueta_descripcion, insignia_tipo):
            if objetivo is not None:
                objetivo.bind("<Button-1>", abrir_fila, add="+")
                objetivo.bind("<Enter>", previsualizar_al_pasar, add="+")

        if es_drafteo and self.on_delete_draft is not None:
            papelera = ctk.CTkButton(
                fila, text="🗑", width=42, height=34, corner_radius=8,
                command=lambda item=entry: self._descartar(item),
                fg_color="#241818", hover_color=DANGER, border_width=1,
                border_color="#4A2C2C", text_color=DANGER,
                font=ctk.CTkFont("Segoe UI Symbol", 15, "bold"),
                cursor="hand2")
            # Aparece solo al pasar por encima: es un botón destructivo y no
            # tiene por qué estar tentando en cada fila de la lista. Pedido
            # del usuario 02-09-2026, otra vuelta: en vez de un tercer hueco
            # en el borde derecho -que acababa solapando otras cosas según
            # el ancho de la fila-, ocupa el sitio exacto del icono de
            # categoría (medido a mano: 6 px desde el borde izquierdo del
            # botón, centrado en su alto) y lo tapa mientras está encima; al
            # salir, vuelve a verse el icono normal.
            # Pedido del usuario 02-09-2026: «cuando paso el ratón de arriba
            # abajo, se queda la papelera; de abajo arriba, se va bien».
            # El fallo real: `ocultar` comprobaba `winfo_pointerxy()` en el
            # mismo instante del `<Leave>`, y ese instante puede llegar con
            # la posición todavía sin asentar según por dónde se sale -Tk no
            # entrega el mismo punto de forma simétrica en las dos
            # direcciones-. Igual que ya se corrigió para los iconos de
            # Cambiar Rol: comprobar tras un pequeño respiro (`after`), no en
            # el acto, da tiempo a que la posición real del cursor se asiente
            # antes de mirarla, y así sale sea cual sea la dirección.
            estado_papelera = {"after_id": None}

            def mostrar(_event=None, boton=papelera, estado=estado_papelera) -> None:
                if estado["after_id"] is not None:
                    fila.after_cancel(estado["after_id"])
                    estado["after_id"] = None
                boton.place(in_=card, x=6, rely=0.5, anchor="w")

            def ocultar(_event=None, boton=papelera, contenedor=fila, estado=estado_papelera) -> None:
                if estado["after_id"] is not None:
                    fila.after_cancel(estado["after_id"])

                def _confirmar(estado=estado) -> None:
                    estado["after_id"] = None
                    try:
                        x, y = contenedor.winfo_pointerxy()
                        dentro = (
                            contenedor.winfo_rootx() <= x <= contenedor.winfo_rootx() + contenedor.winfo_width()
                            and contenedor.winfo_rooty() <= y <= contenedor.winfo_rooty() + contenedor.winfo_height()
                        )
                    except Exception:
                        dentro = False
                    if not dentro:
                        boton.place_forget()

                estado["after_id"] = fila.after(80, _confirmar)

            for widget in (fila, card, papelera):
                widget.bind("<Enter>", mostrar, add="+")
                widget.bind("<Leave>", ocultar, add="+")

    def _descartar(self, entry: dict[str, Any]) -> None:
        if self.on_delete_draft is None:
            return
        self.on_delete_draft(dict(entry.get("guardado", {})))

    def _update_highlight(self) -> None:
        for clave, marco in self._move_frames.items():
            activo = clave == self.preview_key
            type_color = self._move_type_colors.get(clave)
            # Protegido como `_apply_keyboard`, y por el mismo motivo: escribir
            # un color sobre un widget ya destruido lanza `TclError`. Aquí no lo
            # estaba, y esa era la grieta por la que el mando se caía al salir de
            # esta página.
            try:
                configurar_si_cambia(
                    marco,
                    fg_color=(
                        "#27231B" if activo
                        else (move_type_fill(type_color, PANEL) if type_color else PANEL)
                    ),
                    border_color=GOLD if activo else (type_color or "#3A3A3A"),
                    border_width=2 if (activo or type_color) else 1,
                )
            except Exception:
                pass

    # ------------------------------------------------------------- el equipo

    def _entry(self) -> dict[str, Any] | None:
        return self._buscar(self.preview_key)

    def _preview(self, clave: tuple[str, int]) -> None:
        if self.preview_key == clave:
            return
        self.preview_key = clave
        self._update_highlight()
        self._update_team_compatibility()

    def _select(self, clave: tuple[str, int]) -> None:
        self.selected_key = clave
        self._preview(clave)
        self._update_highlight()
        # Confirmar un movimiento termina la fase izquierda: el selector avanza
        # al primer miembro compatible para que la siguiente Z ejecute una
        # elección visible, en lugar de volver a confirmar el mismo preview.
        compatibles = [
            target for target in self._keyboard.targets
            if isinstance(target.key, tuple) and target.key[0] == "pokemon"
        ]
        if compatibles:
            primero = min(compatibles, key=lambda target: (target.row, target.column))
            self._keyboard.selected_key = primero.key
            self._apply_keyboard()

    def _elegir(self, entry: dict[str, Any], pokemon: Any) -> None:
        if str(entry.get("kind", "tm")) == "draft":
            if self.on_choose_draft is not None:
                self.on_choose_draft(dict(entry.get("guardado", {})), pokemon)
            return
        self.on_choose(entry, pokemon)

    def _render_team(self) -> None:
        for child in self.team_grid.winfo_children():
            child.destroy()
        self._images.clear()
        self._team_cards.clear()
        self._team_widgets.clear()
        for index, pokemon in enumerate(self.party[:6]):
            identity = self.identity_for(pokemon)
            role, symbol = self.role_for(pokemon)
            name = str(getattr(pokemon, "nickname", "") or getattr(pokemon, "species", "Pokémon"))
            card = ctk.CTkFrame(self.team_grid, fg_color="#171717", corner_radius=13,
                                border_width=1, border_color="#2D2D2D")
            card.grid(row=index // 3, column=index % 3, sticky="nsew", padx=5, pady=5)
            self._team_cards[identity] = card
            sprite = self.sprite_for(pokemon, (58, 58))
            if sprite is not None:
                self._images.append(sprite)
            ctk.CTkLabel(card, text="", image=sprite, height=56).pack(pady=(2, 0))
            name_label = ctk.CTkLabel(card, text=name, text_color="#666666",
                                      font=ctk.CTkFont("Segoe UI", 16, "bold"))
            name_label.pack()
            species = str(getattr(pokemon, "species", "Pokémon") or "Pokémon")
            level = int(getattr(pokemon, "level", 0) or 0)
            species_label = ctk.CTkLabel(card, text=f"{species} · Nv. {level}", text_color="#4F4F4F",
                                         font=ctk.CTkFont("Segoe UI", 10))
            species_label.pack(pady=(1, 0))
            role_label = ctk.CTkLabel(card, text=f"{symbol} {role}", text_color="#555555",
                                      font=ctk.CTkFont("Segoe UI", 11, "bold"))
            role_label.pack(pady=(1, 2))
            moves = [str(v) for v in tuple(getattr(pokemon, "moves", ()) or ())[:4] if str(v) not in {"", "—"}]
            moves_frame = ctk.CTkFrame(card, fg_color="transparent")
            moves_frame.pack(fill="x", padx=6, pady=(1, 3))
            moves_frame.grid_columnconfigure((0, 1), weight=1, uniform="tm_moves")
            move_labels: list[Any] = []
            for move_index in range(4):
                move_name = moves[move_index] if move_index < len(moves) else "—"
                move_label = ctk.CTkLabel(
                    moves_frame, text=move_name, height=22, corner_radius=6,
                    fg_color="#242424", text_color="#4A4A4A",
                    font=ctk.CTkFont("Segoe UI", 9, "bold"),
                )
                move_label.grid(row=move_index // 2, column=move_index % 2,
                                sticky="ew", padx=2, pady=2)
                move_labels.append(move_label)
            action = ctk.CTkButton(card, text="NO CUMPLE EL ROL", height=32, state="disabled",
                                   fg_color="#242424", hover_color="#D3AF70", text_color="#111111",
                                   text_color_disabled="#777777", font=ctk.CTkFont("Segoe UI", 10, "bold"))
            action.pack(fill="x", padx=8, pady=(0, 5))
            compatible_button = None
            if self.on_view_compatible_moves is not None:
                # Siempre activo, igual que RECUERDA-MOVIMIENTOS: no depende
                # de qué MT esté seleccionada a la izquierda ahora mismo.
                compatible_button = ctk.CTkButton(
                    card, text="VER MT COMPATIBLES", height=26,
                    fg_color="transparent", hover_color=PANEL_ALT,
                    border_width=1, border_color="#3A3A3A", text_color=MUTED,
                    font=ctk.CTkFont("Segoe UI", 9, "bold"),
                    command=lambda member=pokemon: self.on_view_compatible_moves(member),
                )
                compatible_button.pack(fill="x", padx=8, pady=(0, 4))
            history_button = None
            if self.on_open_levelup_history is not None:
                # Siempre activo: a diferencia de ELEGIR, no depende de si el
                # movimiento seleccionado encaja con este Pokémon.
                history_button = ctk.CTkButton(
                    card, text="RECUERDA-MOVIMIENTOS", height=26,
                    fg_color="transparent", hover_color=PANEL_ALT,
                    border_width=1, border_color="#3A3A3A", text_color=MUTED,
                    font=ctk.CTkFont("Segoe UI", 9, "bold"),
                    command=lambda member=pokemon: self.on_open_levelup_history(member),
                )
                history_button.pack(fill="x", padx=8, pady=(0, 6))
            self._team_widgets[identity] = (
                pokemon, card, name_label, species_label, role_label, tuple(move_labels), action,
                compatible_button, history_button,
            )
        self._update_team_compatibility()

    def _update_team_compatibility(self) -> None:
        """Cambia solo propiedades: hover nunca destruye widgets ni geometría."""
        entry = self._entry()
        compatible = set(entry.get("compatible", ())) if entry else set()
        known = set(entry.get("known", ())) if entry else set()
        if entry is None:
            titulo = "POKÉMON COMPATIBLES"
        else:
            titulo = f"¿QUIÉN APRENDERÁ {str(entry['move_name']).upper()}?"
            if str(entry.get("kind", "tm")) == "draft":
                titulo += "   ·   DRAFTEO YA PAGADO"
        configurar_si_cambia(self.team_title, text=titulo)
        for identity, widgets in self._team_widgets.items():
            (
                pokemon, card, name_label, species_label, role_label, move_labels, action,
                compatible_button, history_button,
            ) = widgets
            enabled = identity in compatible
            already = identity in known
            configurar_si_cambia(
                card,
                fg_color=PANEL if enabled else "#171717",
                border_width=2 if enabled else 1,
                border_color=GOLD if enabled else "#2D2D2D",
            )
            configurar_si_cambia(name_label, text_color=TEXT if enabled else "#666666")
            configurar_si_cambia(species_label, text_color=MUTED if enabled else "#4F4F4F")
            configurar_si_cambia(role_label, text_color=GOLD if enabled else "#555555")
            for move_label in move_labels:
                configurar_si_cambia(
                    move_label,
                    text_color="#D8D8D8" if enabled else "#4A4A4A",
                    fg_color="#292929" if enabled else "#202020",
                )
            configurar_si_cambia(
                action,
                text="ELEGIR" if enabled else ("YA LO CONOCE" if already else "NO CUMPLE EL ROL"),
                state="normal" if enabled else "disabled",
                fg_color=GOLD if enabled else "#242424",
                command=lambda item=entry, member=pokemon: self._elegir(item, member),
            )
            actions: list[tuple[Any, Callable[[], None]]] = []
            if enabled:
                actions.append((action, lambda item=entry, member=pokemon: self._elegir(item, member)))
            if compatible_button is not None:
                actions.append((compatible_button, lambda member=pokemon: self.on_view_compatible_moves(member)))
            if history_button is not None:
                actions.append((history_button, lambda member=pokemon: self.on_open_levelup_history(member)))
            self._team_action_buttons[identity] = tuple(actions)
        self._rebuild_keyboard()

    # ----------------------------------------------------------------- teclado

    def _rebuild_keyboard(self) -> None:
        self._keyboard_targets.clear()
        targets: list[SpatialTarget] = []
        # Pedido del usuario 09-09-2026: las pestañas MT/DRAFTEOS no eran
        # alcanzables con flechas/mando, solo con ratón. Se colocan en su
        # propia fila -1, por encima de la lista, para que abajo/arriba
        # entre y salga de ella con naturalidad.
        for column, (clave, _etiqueta) in enumerate(PESTANAS):
            boton = self._tab_buttons.get(clave)
            if boton is None:
                continue
            key = ("tab", clave)
            self._keyboard_targets[key] = (
                boton, lambda value=clave: self.cambiar_pestana(value), "#3A3A3A", 1,
            )
            targets.append(SpatialTarget(key, -1, column))
        for row, entry in enumerate(self._filtradas()):
            clave = self._clave(entry)
            widget = self._move_frames.get(clave)
            if widget is None:
                continue
            # El color/ancho «en reposo» tiene que ser el mismo que pinta
            # `_update_highlight`, o el mando pisaba el marco de tipo en
            # cuanto reconstruía sus objetivos (que ocurre en cada refresco
            # de la lista).
            idle_color = self._move_type_colors.get(clave, "#3A3A3A")
            idle_width = 2 if clave in self._move_type_colors else 1
            self._keyboard_targets[clave] = (
                widget, lambda value=clave: self._select(value), idle_color, idle_width,
            )
            targets.append(SpatialTarget(clave, row, 0))
        entry = self._entry()
        compatible = set(entry.get("compatible", ())) if entry else set()
        for index, pokemon in enumerate(self.party[:6]):
            identity = self.identity_for(pokemon)
            # A diferencia de antes, una tarjeta es alcanzable si tiene AL
            # MENOS UNA acción navegable -ELEGIR (solo si es compatible), o
            # VER MT COMPATIBLES/RECUERDA-MOVIMIENTOS, que están siempre
            # disponibles sin importar la compatibilidad-. Antes, un Pokémon
            # que no podía aprender el movimiento seleccionado no tenía
            # ningún target: sus botones "siempre disponibles" solo se
            # podían pulsar con ratón.
            card_actions = self._team_action_buttons.get(identity, ())
            if not card_actions:
                continue
            widget = self._team_cards.get(identity)
            key = ("pokemon", identity)

            def activate(identity=identity) -> None:
                actions = self._team_action_buttons.get(identity, ())
                index = min(self._keyboard_card_action_index, len(actions) - 1)
                if 0 <= index < len(actions):
                    actions[index][1]()

            # Mismo idle que ya pinta `_update_team_compatibility` para la
            # tarjeta -si no coincidieran, la tarjeta parpadearía al dorado
            # en cuanto se le quitara el foco aunque no sea compatible.
            idle_color = GOLD if identity in compatible else "#2D2D2D"
            idle_width = 2 if identity in compatible else 1
            self._keyboard_targets[key] = (widget, activate, idle_color, idle_width)
            targets.append(SpatialTarget(key, index // 3, 1 + index % 3))
        self._keyboard.reset(targets, preserve=True)
        self._apply_keyboard()

    def _bind_keyboard(self) -> None:
        top = self.frame.winfo_toplevel()
        callbacks = {"<KeyPress-Left>": lambda e: self._move(e, "left"),
                     "<KeyPress-Right>": lambda e: self._move(e, "right"),
                     "<KeyPress-Up>": lambda e: self._move(e, "up"),
                     "<KeyPress-Down>": lambda e: self._move(e, "down"),
                     }
        callbacks.update({sequence: self._accept for sequence in keypress_sequences(self.navigation_keys.get("accept", "z"))})
        callbacks.update({sequence: self._clear for sequence in keypress_sequences(self.navigation_keys.get("back", "x"))})
        for sequence, callback in callbacks.items():
            binding = top.bind(sequence, callback, add="+")
            if binding:
                self._bindings.append((sequence, binding))

    def _move(self, event, direction: str):
        if event_targets_text_input(event):
            return None
        guard = getattr(self, "navigation_guard", None)
        if callable(guard) and not guard():
            return None
        intercept = getattr(self, "navigation_intercept", None)
        if callable(intercept) and intercept(direction):
            return "break"
        before = self._keyboard.selected_key
        # Pedido del usuario 09-09-2026 (dos vueltas): arriba/abajo sobre una
        # tarjeta de Pokémon recorren primero SUS botones (ELEGIR, VER MT
        # COMPATIBLES, RECUERDA-MOVIMIENTOS, apilados de arriba abajo en la
        # propia tarjeta) -antes solo se podía seleccionar la tarjeta entera,
        # equivalente siempre a ELEGIR-. Solo al llegar al borde de esa lista
        # se cae a la navegación normal de la rejilla (moverse a la fila de
        # tarjetas de arriba o de abajo). Izquierda/derecha SIEMPRE mueven a
        # la tarjeta vecina -la primera vuelta los usó para esto mismo, y el
        # usuario la corrigió: apilados verticalmente, "derecha" para bajar y
        # "izquierda" para subir no tenía ningún sentido espacial.
        if direction in ("up", "down") and isinstance(before, tuple) and before[0] == "pokemon":
            actions = self._team_action_buttons.get(before[1], ())
            index = self._keyboard_card_action_index
            if direction == "down" and index < len(actions) - 1:
                self._keyboard_card_action_index = index + 1
                self._apply_keyboard()
                return "break"
            if direction == "up" and index > 0:
                self._keyboard_card_action_index = index - 1
                self._apply_keyboard()
                return "break"
        self._keyboard.move(direction)
        current = self._keyboard.current
        if direction == "left" and before == self._keyboard.selected_key:
            if callable(self.on_left_edge):
                self.on_left_edge()
            return "break"
        if self._keyboard.selected_key != before:
            self._keyboard_card_action_index = 0
        if current and isinstance(current.key, tuple) and current.key[0] in {"tm", "draft"}:
            self._preview(current.key)
        self._apply_keyboard()
        return "break"

    def _accept(self, event=None):
        if event is not None and event_targets_text_input(event):
            return None
        guard = getattr(self, "navigation_guard", None)
        if callable(guard) and not guard():
            return None
        if callable(self.on_edge_accept) and self.on_edge_accept():
            return "break"
        current = self._keyboard.current
        target = self._keyboard_targets.get(current.key) if current else None
        if target:
            target[1]()
        return "break"

    def _clear(self, event=None):
        if event is not None and event_targets_text_input(event):
            return None
        guard = getattr(self, "navigation_guard", None)
        if callable(guard) and not guard():
            return None
        intercept = getattr(self, "navigation_intercept", None)
        if callable(intercept) and intercept("back"):
            return "break"
        current = self._keyboard.current
        if current is not None and isinstance(current.key, tuple) and current.key[0] == "pokemon":
            if self.preview_key in self._keyboard_targets:
                self._keyboard.selected_key = self.preview_key
                self._apply_keyboard()
                return "break"
        self._keyboard.clear()
        self._apply_keyboard()
        return "break"

    def _apply_keyboard(self) -> None:
        selected = None if self._external_navigation_focus else self._keyboard.selected_key
        for key, (widget, _callback, color, width) in self._keyboard_targets.items():
            is_pokemon = isinstance(key, tuple) and key[0] == "pokemon"
            try:
                if is_pokemon:
                    # El resalte vive en el botón concreto que ACEPTAR
                    # dispararía -ELEGIR, VER MT COMPATIBLES o
                    # RECUERDA-MOVIMIENTOS-, nunca en la tarjeta entera: antes
                    # solo existía "la tarjeta entera", equivalente siempre a
                    # ELEGIR. La tarjeta en sí se queda siempre en su borde
                    # de reposo.
                    configurar_si_cambia(widget, border_color=color, border_width=width)
                    # Bug reportado por el usuario 09-09-2026, con captura:
                    # varias tarjetas se quedaban con un botón resaltado a la
                    # vez -esta rama solo se ejecutaba para la tarjeta
                    # ACTUALMENTE seleccionada, así que la anterior nunca
                    # perdía su resalte al moverse a otra-. Ahora TODAS las
                    # tarjetas pasan por aquí en cada pasada, y solo la
                    # seleccionada de verdad calcula un índice real.
                    actions = self._team_action_buttons.get(key[1], ())
                    highlighted = (
                        min(self._keyboard_card_action_index, len(actions) - 1)
                        if key == selected else -1
                    )
                    for action_index, (button, _action_callback) in enumerate(actions):
                        configurar_si_cambia(
                            button,
                            border_color="#F2C45E" if action_index == highlighted else "#3A3A3A",
                            border_width=4 if action_index == highlighted else 1,
                        )
                    continue
                configurar_si_cambia(
                    widget,
                    border_color="#F2C45E" if key == selected else color,
                    border_width=4 if key == selected else width,
                )
            except Exception:
                pass

    def set_external_navigation_focus(self, active: bool) -> None:
        self._external_navigation_focus = bool(active)
        self._apply_keyboard()
