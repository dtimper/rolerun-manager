from __future__ import annotations

from collections.abc import Callable
from typing import Any

import customtkinter as ctk

from app.config import DANGER, GOLD, MUTED, PANEL, PANEL_ALT, TEXT
from app.ui_components.repintado import configurar_si_cambia
from app.ui_state.spatial_navigation import SpatialSelection, SpatialTarget, event_targets_text_input, keypress_sequences

SELECTED = "#73A9FF"


class GlobalTMView:
    """MOVIMIENTOS: lo que puedes enseñar hoy, venga de donde venga.

    Dos columnas con el mismo peso, porque son dos formas de lo mismo:

    - **MT**, lo que llevas en la mochila del juego.
    - **DRAFTEOS**, tiradas que te quedaste y todavía no has enseñado. Cada una
      ya costó su drafteo al guardarla, así que enseñarla aquí no vuelve a
      cobrar.

    El equipo ya no ocupa media pantalla esperando. Antes había que elegir el
    movimiento **y** al Pokémon en la misma vista, y el panel de la derecha
    estaba siempre ahí, apagado, sin nada que decir hasta que elegías. Ahora se
    pulsa un movimiento y **entonces** aparece el selector, que es el orden en
    que se piensa: primero qué quiero enseñar, después a quién.
    """

    def __init__(self, master, *, entries: tuple[dict[str, Any], ...], party: tuple[Any, ...],
                 identity_for: Callable[[Any], str], role_for: Callable[[Any], tuple[str, str]],
                 sprite_for: Callable[[Any, tuple[int, int]], Any],
                 role_icon_for: Callable[[str, int], Any | None],
                 on_choose: Callable[[dict[str, Any], Any], None], source_detail: str,
                 drafts: tuple[dict[str, Any], ...] = (),
                 on_choose_draft: Callable[[dict[str, Any], Any], None] | None = None,
                 navigation_keys: dict[str, str] | None = None,
                 on_left_edge: Callable[[], None] | None = None,
                 on_edge_accept: Callable[[], bool] | None = None) -> None:
        self.master, self.entries, self.party = master, entries, party
        self.drafts = tuple(drafts)
        self.identity_for, self.role_for, self.sprite_for = identity_for, role_for, sprite_for
        self.role_icon_for, self.on_choose, self.source_detail = role_icon_for, on_choose, source_detail
        self.on_choose_draft = on_choose_draft
        self.navigation_keys = dict(navigation_keys or {"accept": "z", "back": "x"})
        self.on_left_edge, self.on_edge_accept = on_left_edge, on_edge_accept
        self.navigation_guard: Callable[[], bool] | None = None
        self.navigation_intercept: Callable[[str], bool] | None = None
        self._external_navigation_focus = False
        #: Qué movimiento tiene abierto el selector, o ``None`` si está cerrado.
        self.abierto: dict[str, Any] | None = None
        self._search_after = None
        self._images: list[Any] = []
        self._move_buttons: dict[tuple[str, int], Any] = {}
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
        self.frame.grid_columnconfigure((0, 1), weight=1, uniform="movimientos")
        self.frame.grid_rowconfigure(1, weight=1)

        heading = ctk.CTkFrame(self.frame, fg_color="transparent")
        heading.grid(row=0, column=0, columnspan=2, sticky="ew", padx=20, pady=(14, 10))
        heading.grid_columnconfigure(1, weight=1)
        self.search = ctk.CTkEntry(heading, width=300, height=36,
                                   placeholder_text="⌕  Buscar por MT o movimiento…")
        self.search.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(heading, text="ELIGE QUÉ ENSEÑAR", text_color=GOLD, anchor="w",
                     font=ctk.CTkFont("Segoe UI", 20, "bold")).grid(row=1, column=0, sticky="w", pady=(9, 0))
        self.search.bind("<KeyRelease>", self._schedule_filter, add="+")

        self.tm_scroll = self._columna(0, "MT", "Las que llevas en la mochila.", (18, 7))
        self.draft_scroll = self._columna(
            1, "DRAFTEOS", "Tiradas que te guardaste. Ya están pagadas.", (7, 18),
        )
        self._montar_selector()

        self._bind_keyboard()
        self._render_lists()
        if canvas is not None:
            self._viewport_binding = canvas.bind(
                "<Configure>", lambda event: self.frame.configure(height=max(480, int(event.height))), add="+")
        for delay in (0, 80, 180, 400):
            self.frame.after(delay, self._fit_to_viewport)

    # ----------------------------------------------------------------- montaje

    def _columna(self, column: int, titulo: str, detalle: str, padx) -> Any:
        panel = ctk.CTkFrame(self.frame, fg_color="#111111", corner_radius=12)
        panel.grid(row=1, column=column, sticky="nsew", padx=padx, pady=(0, 16))
        panel.grid_rowconfigure(2, weight=1)
        panel.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(panel, text=titulo, text_color=GOLD,
                     font=ctk.CTkFont("Segoe UI", 14, "bold")).grid(
                         row=0, column=0, sticky="w", padx=16, pady=(13, 0))
        ctk.CTkLabel(panel, text=detalle, text_color=MUTED,
                     font=ctk.CTkFont("Segoe UI", 10)).grid(
                         row=1, column=0, sticky="w", padx=16, pady=(1, 6))
        scroll = ctk.CTkScrollableFrame(panel, fg_color="transparent")
        scroll.grid(row=2, column=0, sticky="nsew", padx=5, pady=(0, 5))
        scroll.grid_columnconfigure(0, weight=1)
        return scroll

    def _montar_selector(self) -> None:
        """El selector existe desde el principio, pero no se coloca hasta abrirlo."""
        self.selector = ctk.CTkFrame(self.frame, fg_color="#0D0D0D", corner_radius=18,
                                     border_width=2, border_color=GOLD)
        self.selector.grid_columnconfigure(0, weight=1)
        self.selector.grid_rowconfigure(2, weight=1)
        self.team_title = ctk.CTkLabel(self.selector, text="", text_color=GOLD, anchor="w",
                                       font=ctk.CTkFont("Segoe UI", 17, "bold"))
        self.team_title.grid(row=0, column=0, sticky="w", padx=22, pady=(18, 1))
        self.team_detail = ctk.CTkLabel(self.selector, text="", text_color=MUTED, anchor="w",
                                        font=ctk.CTkFont("Segoe UI", 11))
        self.team_detail.grid(row=1, column=0, sticky="w", padx=22, pady=(0, 8))
        ctk.CTkButton(self.selector, text="×", width=40, height=40, corner_radius=12,
                      command=self.cerrar_selector, fg_color="transparent",
                      hover_color=DANGER, border_width=1, border_color=GOLD,
                      text_color=GOLD, font=ctk.CTkFont("Segoe UI", 20, "bold")).grid(
                          row=0, column=1, rowspan=2, padx=(10, 18), pady=(16, 0))
        self.team_grid = ctk.CTkFrame(self.selector, fg_color="transparent")
        self.team_grid.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=12, pady=(0, 14))
        self.team_grid.grid_columnconfigure((0, 1, 2), weight=1, uniform="tm_party")
        self.team_grid.grid_rowconfigure((0, 1), weight=1, uniform="tm_party")

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
                        and self.frame.winfo_height() > 450
                        and self.tm_scroll.winfo_ismapped()
                        and self.draft_scroll.winfo_ismapped())
        except Exception:
            return False

    def update_entries(self, entries: tuple[dict[str, Any], ...], party: tuple[Any, ...],
                       drafts: tuple[dict[str, Any], ...] | None = None) -> None:
        """Publica el readback conservando la misma página y posición."""
        fraction = self._scroll_fraction()
        self.entries, self.party = entries, party
        if drafts is not None:
            self.drafts = tuple(drafts)
        # Si el movimiento abierto ha dejado de existir —se acaba de enseñar, o
        # era la última MT— el selector no puede seguir en pantalla ofreciendo
        # algo que ya no está.
        if self.abierto is not None and self._buscar(self._clave(self.abierto)) is None:
            self.cerrar_selector()
        self._render_lists()
        self._restore_scroll(fraction)
        if self.abierto is not None:
            self._render_team()

    # -------------------------------------------------------------- las listas

    @staticmethod
    def _clave(entry: dict[str, Any]) -> tuple[str, int]:
        return (str(entry.get("kind", "tm")), int(entry.get("move_id", 0) or 0))

    def _todas(self) -> tuple[dict[str, Any], ...]:
        return (*self.entries, *self.drafts)

    def _buscar(self, clave: tuple[str, int]) -> dict[str, Any] | None:
        return next((item for item in self._todas() if self._clave(item) == clave), None)

    def _consulta(self) -> str:
        try:
            return self.search.get().strip().casefold()
        except Exception:
            return ""

    def _filtered_entries(self) -> tuple[dict[str, Any], ...]:
        query = self._consulta()
        return tuple(item for item in self.entries if not query or query in
                     f"mt{int(item['number']):02d} {item['move_name']}".casefold())

    def _filtered_drafts(self) -> tuple[dict[str, Any], ...]:
        query = self._consulta()
        return tuple(item for item in self.drafts if not query or query in
                     f"{item['move_name']} {item.get('role', '')}".casefold())

    def _schedule_filter(self, _event=None) -> None:
        if self._search_after is not None:
            try:
                self.frame.after_cancel(self._search_after)
            except Exception:
                pass
        self._search_after = self.frame.after(90, self._filter_now)

    def _filter_now(self) -> None:
        self._search_after = None
        self._render_lists()

    def _scroll_fraction(self) -> float:
        canvas = getattr(self.tm_scroll, "_parent_canvas", None)
        try:
            return float(canvas.yview()[0]) if canvas is not None else 0.0
        except Exception:
            return 0.0

    def _restore_scroll(self, fraction: float) -> None:
        canvas = getattr(self.tm_scroll, "_parent_canvas", None)
        if canvas is not None:
            self.frame.after_idle(lambda: canvas.yview_moveto(max(0.0, min(1.0, fraction))))

    def _render_lists(self) -> None:
        self._move_buttons.clear()
        for child in self.tm_scroll.winfo_children():
            child.destroy()
        for child in self.draft_scroll.winfo_children():
            child.destroy()

        mts = self._filtered_entries()
        if not mts:
            ctk.CTkLabel(self.tm_scroll, text="Ninguna MT coincide con la búsqueda.",
                         text_color=MUTED, font=ctk.CTkFont("Segoe UI", 12, "bold")).grid(
                             row=0, column=0, pady=50)
        for row, entry in enumerate(mts):
            self._tarjeta_de_movimiento(
                self.tm_scroll, row, entry,
                f"MT{int(entry['number']):02d}   {entry['move_name']}",
                (f"{entry['category']}  ·  Pot. {entry['power']}  ·  Prec. {entry['accuracy']}  ·  "
                 f"PP {entry['pp']}  ·  x{entry['quantity']}"),
            )

        drafteos = self._filtered_drafts()
        if not drafteos:
            ctk.CTkLabel(
                self.draft_scroll,
                text=("Todavía no has guardado ningún drafteo.\n"
                      "En Drafteos, tira y pulsa GUARDAR para dejarlo aquí."),
                text_color=MUTED, justify="center",
                font=ctk.CTkFont("Segoe UI", 12, "bold")).grid(row=0, column=0, pady=50)
        for row, entry in enumerate(drafteos):
            rol = str(entry.get("role", "")) or "cualquier rol"
            self._tarjeta_de_movimiento(
                self.draft_scroll, row, entry,
                str(entry["move_name"]),
                (f"{rol}  ·  {entry['category']}  ·  Pot. {entry['power']}  ·  "
                 f"Prec. {entry['accuracy']}  ·  PP {entry['pp']}"),
            )
        self._update_highlight()
        self._rebuild_keyboard()

    def _tarjeta_de_movimiento(self, host, row: int, entry: dict[str, Any],
                               titulo: str, detalle: str) -> None:
        clave = self._clave(entry)
        card = ctk.CTkButton(
            host, text=f"{titulo}\n{detalle}",
            command=lambda value=clave: self.abrir_selector(value), anchor="w", height=66,
            fg_color=PANEL, hover_color=PANEL_ALT, border_width=1, border_color="#3A3A3A",
            text_color=TEXT, font=ctk.CTkFont("Segoe UI", 12, "bold"))
        card.grid(row=row, column=0, sticky="ew", padx=4, pady=4)
        self._move_buttons[clave] = card

    def _update_highlight(self) -> None:
        activo = self._clave(self.abierto) if self.abierto is not None else None
        for clave, button in self._move_buttons.items():
            encendido = clave == activo
            configurar_si_cambia(
                button,
                fg_color="#27231B" if encendido else PANEL,
                border_color=GOLD if encendido else "#3A3A3A",
                border_width=2 if encendido else 1,
            )

    # ------------------------------------------------------------- el selector

    def abrir_selector(self, clave: tuple[str, int]) -> None:
        entry = self._buscar(clave)
        if entry is None:
            return
        self.abierto = entry
        self.selector.grid(row=0, column=0, rowspan=2, columnspan=2, sticky="nsew",
                           padx=40, pady=34)
        self.selector.lift()
        self._render_team()
        self._update_highlight()

    def cerrar_selector(self) -> None:
        self.abierto = None
        try:
            self.selector.grid_forget()
        except Exception:
            pass
        self._update_highlight()
        self._rebuild_keyboard()

    def _entry(self) -> dict[str, Any] | None:
        return self.abierto

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
        if entry is not None:
            self.team_title.configure(
                text=f"¿QUIÉN APRENDERÁ {str(entry['move_name']).upper()}?")
            self.team_detail.configure(text=(
                "Este drafteo ya está pagado: enseñarlo no consume otro."
                if str(entry.get("kind", "tm")) == "draft" else
                f"Te queda x{entry.get('quantity', 1)} de esta MT."
            ))
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
        if self.abierto is None:
            for column, filtradas in ((0, self._filtered_entries()), (1, self._filtered_drafts())):
                for row, entry in enumerate(filtradas):
                    clave = self._clave(entry)
                    widget = self._move_buttons.get(clave)
                    if widget is None:
                        continue
                    self._keyboard_targets[clave] = (
                        widget, lambda value=clave: self.abrir_selector(value), "#3A3A3A", 1,
                    )
                    targets.append(SpatialTarget(clave, row, column))
        else:
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
                targets.append(SpatialTarget(key, index // 3, index % 3))
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
        # Solo se sale hacia la barra lateral desde la lista: con el selector
        # abierto, izquierda es moverse entre los seis del equipo.
        if direction == "left" and before == self._keyboard.selected_key and self.abierto is None:
            if callable(self.on_left_edge):
                self.on_left_edge()
            return "break"
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
        # Con el selector abierto, atrás significa cerrarlo: es la única forma de
        # volver a la lista sin tocar el ratón.
        if self.abierto is not None:
            self.cerrar_selector()
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
