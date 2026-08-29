from __future__ import annotations

from collections.abc import Callable
from typing import Any

import customtkinter as ctk

from app.config import DANGER, GOLD, MUTED, PANEL, PANEL_ALT, TEXT
from app.ui_components.repintado import configurar_si_cambia
from app.ui_state.spatial_navigation import SpatialSelection, SpatialTarget, event_targets_text_input, keypress_sequences

SELECTED = "#73A9FF"

#: Las dos procedencias, en el orden en que se muestran.
PESTANAS: tuple[tuple[str, str], ...] = (("tm", "MT"), ("draft", "DRAFTEOS"))


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
                 navigation_keys: dict[str, str] | None = None,
                 on_left_edge: Callable[[], None] | None = None,
                 on_edge_accept: Callable[[], bool] | None = None) -> None:
        self.master, self.entries, self.party = master, entries, party
        self.drafts = tuple(drafts)
        self.identity_for, self.role_for, self.sprite_for = identity_for, role_for, sprite_for
        self.role_icon_for, self.on_choose, self.source_detail = role_icon_for, on_choose, source_detail
        self.on_choose_draft, self.on_delete_draft = on_choose_draft, on_delete_draft
        self.navigation_keys = dict(navigation_keys or {"accept": "z", "back": "x"})
        self.on_left_edge, self.on_edge_accept = on_left_edge, on_edge_accept
        self.navigation_guard: Callable[[], bool] | None = None
        self.navigation_intercept: Callable[[str], bool] | None = None
        self._external_navigation_focus = False
        self.pestana = "tm"
        self.preview_key: tuple[str, int] | None = None
        self.selected_key: tuple[str, int] | None = None
        self._search_after = None
        self._images: list[Any] = []
        self._move_buttons: dict[tuple[str, int], Any] = {}
        self._tab_buttons: dict[str, Any] = {}
        self._team_cards: dict[str, Any] = {}
        self._team_widgets: dict[str, tuple[Any, ...]] = {}
        self._keyboard = SpatialSelection()
        self._keyboard_targets: dict[object, tuple[Any, Callable[[], None], str, int]] = {}
        self._bindings: list[tuple[str, str]] = []
        self._viewport_binding = None

        canvas = getattr(master, "_parent_canvas", None)
        viewport = int(canvas.winfo_height() or 0) if canvas is not None else 0
        height = max(480, viewport, int(master.winfo_toplevel().winfo_height() or 720) - 245)
        self.frame = ctk.CTkFrame(master, height=height, fg_color="#151515", corner_radius=16,
                                  border_width=1, border_color="#3A3A3A")
        self.frame.grid(row=0, column=0, sticky="nsew")
        self.frame.grid_propagate(False)
        self.frame.grid_columnconfigure(0, weight=5, uniform="global_tm")
        self.frame.grid_columnconfigure(1, weight=7, uniform="global_tm")
        self.frame.grid_rowconfigure(1, weight=1)

        heading = ctk.CTkFrame(self.frame, fg_color="transparent")
        heading.grid(row=0, column=0, columnspan=2, sticky="ew", padx=20, pady=(14, 10))
        heading.grid_columnconfigure(1, weight=1)
        self.search = ctk.CTkEntry(heading, width=300, height=36,
                                   placeholder_text="⌕  Buscar por MT o movimiento…")
        self.search.grid(row=0, column=0, columnspan=2, sticky="w")
        ctk.CTkLabel(heading, text="ELIGE QUÉ ENSEÑAR", text_color=GOLD, anchor="w",
                     font=ctk.CTkFont("Segoe UI", 20, "bold")).grid(row=1, column=0, sticky="w", pady=(9, 0))
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
        self.team_grid = ctk.CTkFrame(self.team_panel, fg_color="transparent")
        self.team_grid.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.team_grid.grid_columnconfigure((0, 1, 2), weight=1, uniform="tm_party")
        self.team_grid.grid_rowconfigure((0, 1), weight=1, uniform="tm_party")

        self._bind_keyboard()
        self._render_list()
        self._render_team()
        if canvas is not None:
            self._viewport_binding = canvas.bind(
                "<Configure>", lambda event: self.frame.configure(height=max(480, int(event.height))), add="+")
        for delay in (0, 80, 180, 400):
            self.frame.after(delay, self._fit_to_viewport)

    # ----------------------------------------------------------------- montaje

    def _fit_to_viewport(self) -> None:
        canvas = getattr(self.master, "_parent_canvas", None)
        try:
            height = int(canvas.winfo_height() or 0) if canvas is not None else 0
            if height >= 480:
                self.frame.configure(height=height)
        except Exception:
            pass

    def destroy(self) -> None:
        top = self.frame.winfo_toplevel()
        for sequence, binding in self._bindings:
            try:
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
            return tuple(item for item in self.drafts if not query or query in
                         f"{item['move_name']} {item.get('role', '')}".casefold())
        return tuple(item for item in self.entries if not query or query in
                     f"mt{int(item['number']):02d} {item['move_name']}".casefold())

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
        filtradas = self._filtradas()
        claves = {self._clave(item) for item in filtradas}
        if filtradas and self.preview_key not in claves:
            self.preview_key = self._clave(filtradas[0])
        if not filtradas:
            self.preview_key = None
            ctk.CTkLabel(
                self.list_scroll,
                text=(
                    "Todavía no has guardado ningún drafteo.\n"
                    "En Drafteos, tira y pulsa GUARDAR para dejarlo aquí."
                    if self.pestana == "draft" else
                    "No tienes ninguna MT que coincida con la búsqueda."
                ),
                text_color=MUTED, justify="center",
                font=ctk.CTkFont("Segoe UI", 13, "bold")).grid(row=0, column=0, pady=70)
        for row, entry in enumerate(filtradas):
            self._fila(row, entry)
        self._pintar_pestanas()
        self._update_highlight()
        self._rebuild_keyboard()

    def _fila(self, row: int, entry: dict[str, Any]) -> None:
        clave = self._clave(entry)
        es_drafteo = clave[0] == "draft"
        if es_drafteo:
            rol = str(entry.get("role", "")) or "cualquier rol"
            titulo = str(entry["move_name"])
            detalle = (f"{rol}  ·  {entry['category']}  ·  Pot. {entry['power']}  ·  "
                       f"Prec. {entry['accuracy']}  ·  PP {entry['pp']}")
        else:
            titulo = f"MT{int(entry['number']):02d}   {entry['move_name']}"
            detalle = (f"{entry['category']}  ·  Pot. {entry['power']}  ·  "
                       f"Prec. {entry['accuracy']}  ·  PP {entry['pp']}  ·  x{entry['quantity']}")

        # Cada fila es un contenedor porque la papelera se pone ENCIMA del botón.
        # Un `CTkButton` no admite hijos colocados sobre su lienzo sin estorbar
        # a su propio texto, y el hueco reservado a la derecha es lo que evita
        # que el nombre del movimiento pase por debajo del icono.
        fila = ctk.CTkFrame(self.list_scroll, fg_color="transparent")
        fila.grid(row=row, column=0, sticky="ew", padx=4, pady=4)
        fila.grid_columnconfigure(0, weight=1)
        card = ctk.CTkButton(
            fila, text=f"{titulo}\n{detalle}",
            command=lambda value=clave: self._select(value), anchor="w", height=66,
            fg_color=PANEL, hover_color=PANEL_ALT, border_width=1, border_color="#3A3A3A",
            text_color=TEXT, font=ctk.CTkFont("Segoe UI", 12, "bold"))
        card.grid(row=0, column=0, sticky="ew")
        card.bind("<Enter>", lambda _event, value=clave: self._preview(value), add="+")
        self._move_buttons[clave] = card

        if es_drafteo and self.on_delete_draft is not None:
            papelera = ctk.CTkButton(
                fila, text="🗑", width=34, height=30, corner_radius=8,
                command=lambda item=entry: self._descartar(item),
                fg_color="#241818", hover_color=DANGER, border_width=1,
                border_color="#4A2C2C", text_color=DANGER,
                font=ctk.CTkFont("Segoe UI Symbol", 13, "bold"))
            # Aparece solo al pasar por encima: es un botón destructivo y no
            # tiene por qué estar tentando en cada fila de la lista.
            def mostrar(_event=None, boton=papelera) -> None:
                boton.place(relx=1.0, x=-10, rely=0.5, anchor="e")

            def ocultar(_event=None, boton=papelera, contenedor=fila) -> None:
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

            for widget in (fila, card, papelera):
                widget.bind("<Enter>", mostrar, add="+")
                widget.bind("<Leave>", ocultar, add="+")

    def _descartar(self, entry: dict[str, Any]) -> None:
        if self.on_delete_draft is None:
            return
        self.on_delete_draft(dict(entry.get("guardado", {})))

    def _update_highlight(self) -> None:
        for clave, button in self._move_buttons.items():
            activo = clave == self.preview_key
            configurar_si_cambia(
                button,
                fg_color="#27231B" if activo else PANEL,
                border_color=GOLD if activo else "#3A3A3A",
                border_width=2 if activo else 1,
            )

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
            self._team_widgets[identity] = (
                pokemon, card, name_label, species_label, role_label, tuple(move_labels), action,
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
            pokemon, card, name_label, species_label, role_label, move_labels, action = widgets
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
        self._rebuild_keyboard()

    # ----------------------------------------------------------------- teclado

    def _rebuild_keyboard(self) -> None:
        self._keyboard_targets.clear()
        targets: list[SpatialTarget] = []
        for row, entry in enumerate(self._filtradas()):
            clave = self._clave(entry)
            widget = self._move_buttons.get(clave)
            if widget is None:
                continue
            self._keyboard_targets[clave] = (
                widget, lambda value=clave: self._select(value), "#3A3A3A", 1,
            )
            targets.append(SpatialTarget(clave, row, 0))
        entry = self._entry()
        compatible = set(entry.get("compatible", ())) if entry else set()
        for index, pokemon in enumerate(self.party[:6]):
            identity = self.identity_for(pokemon)
            if identity not in compatible or entry is None:
                continue
            widget = self._team_cards.get(identity)
            key = ("pokemon", identity)
            self._keyboard_targets[key] = (
                widget, lambda item=entry, member=pokemon: self._elegir(item, member), GOLD, 2,
            )
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
        self._keyboard.move(direction)
        current = self._keyboard.current
        if direction == "left" and before == self._keyboard.selected_key:
            if callable(self.on_left_edge):
                self.on_left_edge()
            return "break"
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
            try:
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
