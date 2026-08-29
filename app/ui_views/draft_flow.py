from __future__ import annotations

from collections.abc import Callable
from typing import Any

import customtkinter as ctk

from app.config import DANGER, GOLD, MUTED, PANEL, PANEL_ALT, SUCCESS, TEXT
from app.pokemon_stats import STAT_KEYS, STAT_LABELS
from app.ui_components.repintado import configurar_si_cambia
from app.ui_state.spatial_navigation import (
    SpatialSelection,
    SpatialTarget,
    event_targets_text_input,
    keypress_sequences,
)


def _available_body_height(master) -> int:
    canvas = getattr(master, "_parent_canvas", None)
    try:
        viewport = int(canvas.winfo_height() or 0) if canvas is not None else 0
    except Exception:
        viewport = 0
    if viewport >= 320:
        return max(460, viewport)
    direct = int(master.winfo_height() or 0)
    if direct >= 320:
        return max(460, direct)
    top = master.winfo_toplevel()
    top_height = int(top.winfo_height() or 0)
    try:
        dimensions = str(top.geometry()).split("+", 1)[0]
        declared_height = int(dimensions.split("x", 1)[1])
    except (IndexError, TypeError, ValueError):
        declared_height = 720
    top_height = max(top_height, declared_height)
    return max(460, top_height - 330)


def _draft_result_layout(count: int) -> list[tuple[int, int, int]]:
    """Distribuye hasta cinco resultados en seis columnas sin crear scroll vertical."""
    layouts = {
        0: [],
        1: [(0, 0, 6)],
        2: [(0, 0, 3), (0, 3, 3)],
        3: [(0, 0, 2), (0, 2, 2), (0, 4, 2)],
        4: [(0, 0, 3), (0, 3, 3), (1, 0, 3), (1, 3, 3)],
        5: [(0, 0, 2), (0, 2, 2), (0, 4, 2), (1, 1, 2), (1, 3, 2)],
    }
    if count in layouts:
        return layouts[count]
    return [(index // 3, (index % 3) * 2, 2) for index in range(max(0, count))]


class IntegratedDraftFlow:
    """Tres pantallas de drafteo que comparten la superficie principal."""

    def __init__(
        self,
        master,
        *,
        team_slots: tuple[dict[str, Any], ...],
        selected_pokemon: Any | None,
        selected_pool: str | None,
        results: list[dict[str, Any]],
        selected_draft: Any | None,
        draft_count: int,
        role_names: tuple[str, ...],
        role_for: Callable[[Any], tuple[str, str]],
        sprite_for: Callable[[Any, tuple[int, int]], Any],
        role_icon_for: Callable[[str, int], Any | None],
        move_metadata_for: Callable[[int], dict[str, Any]],
        moves_for: Callable[[Any], tuple[list[str], list[int]]],
        on_choose_pokemon: Callable[[Any, str], None],
        on_choose_move: Callable[[int], None],
        on_reroll: Callable[[int], None],
        on_choose_slot: Callable[[int], None],
        on_save_move: Callable[[int], None] | None = None,
        on_back: Callable[[], None],
        on_cancel: Callable[[], None],
        on_open_moves: Callable[[], None] | None = None,
        navigation_keys: dict[str, str] | None = None,
        on_left_edge: Callable[[], None] | None = None,
        on_edge_accept: Callable[[], bool] | None = None,
    ) -> None:
        self.team_slots = team_slots
        self.selected_pokemon = selected_pokemon
        self.selected_pool = selected_pool
        self.results = results
        self.selected_draft = selected_draft
        self.draft_count = max(0, int(draft_count))
        self.role_names = role_names
        self.role_for = role_for
        self.sprite_for = sprite_for
        self.role_icon_for = role_icon_for
        self.move_metadata_for = move_metadata_for
        self.moves_for = moves_for
        self.on_choose_pokemon = on_choose_pokemon
        self.on_choose_move = on_choose_move
        self.on_reroll = on_reroll
        self.on_choose_slot = on_choose_slot
        self.on_save_move = on_save_move
        self.on_back = on_back
        self.on_cancel = on_cancel
        self.on_open_moves = on_open_moves
        self.navigation_keys = dict(navigation_keys or {"accept": "z", "back": "x"})
        self.on_left_edge, self.on_edge_accept = on_left_edge, on_edge_accept
        self.navigation_guard: Callable[[], bool] | None = None
        self.navigation_intercept: Callable[[str], bool] | None = None
        self._external_navigation_focus = False
        self.images: list[Any] = []
        self.libero_choice: Any | None = None
        self._fade_after_ids: set[str] = set()
        self._viewport_canvas = None
        self._viewport_bind_id = None
        self._keyboard_navigation = SpatialSelection()
        self._keyboard_targets: dict[object, tuple[Any, Callable[[], None], str, int]] = {}
        self._keyboard_bindings: list[tuple[str, str]] = []

        available_height = _available_body_height(master)
        height = max(460, available_height - 6)
        self.frame = ctk.CTkFrame(master, height=height, fg_color="#151515", corner_radius=16,
                                  border_width=1, border_color="#373737")
        self.frame.grid(row=0, column=0, sticky="nsew")
        self.frame.grid_propagate(False)
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_rowconfigure(1, weight=1)
        self._render_header()
        self.content = ctk.CTkFrame(self.frame, fg_color="transparent")
        self.content.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 16))
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)
        self._render_step()
        for delay in (0, 80, 180):
            self.frame.after(delay, self._fit_frame_to_viewport)
        self._bind_viewport_resize()
        self._escape_binding = master.winfo_toplevel().bind("<Escape>", lambda _event: self.on_cancel(), add="+")
        self._bind_keyboard_navigation()

    def _fit_frame_to_viewport(self) -> None:
        canvas = getattr(self.frame.master, "_parent_canvas", None)
        try:
            viewport = int(canvas.winfo_height() or 0) if canvas is not None else 0
            if viewport >= 460 and self.frame.winfo_exists():
                logical_height = int(self.frame._reverse_widget_scaling(viewport - 8))
                configurar_si_cambia(self.frame, height=max(460, logical_height))
        except Exception:
            pass

    def _bind_viewport_resize(self) -> None:
        canvas = getattr(self.frame.master, "_parent_canvas", None)
        if canvas is None:
            return
        try:
            self._viewport_canvas = canvas
            self._viewport_bind_id = canvas.bind(
                "<Configure>", lambda _event: self._fit_frame_to_viewport(), add="+",
            )
        except Exception:
            self._viewport_canvas = None
            self._viewport_bind_id = None

    def _release_viewport_resize(self) -> None:
        try:
            if self._viewport_canvas is not None and self._viewport_bind_id:
                self._viewport_canvas.unbind("<Configure>", self._viewport_bind_id)
        except Exception:
            pass
        self._viewport_canvas = None
        self._viewport_bind_id = None

    def destroy(self) -> None:
        self._release_viewport_resize()
        self._release_keyboard_navigation()
        for after_id in list(self._fade_after_ids):
            try:
                self.frame.after_cancel(after_id)
            except Exception:
                pass
        self._fade_after_ids.clear()
        try:
            if self._escape_binding:
                self.frame.winfo_toplevel().unbind("<Escape>", self._escape_binding)
        except Exception:
            pass
        try:
            if self.frame.winfo_exists():
                self.frame.destroy()
        except Exception:
            pass

    def suspend_interaction(self) -> None:
        """Mantiene los píxeles visibles mientras el nuevo body se prepara."""
        self._release_viewport_resize()
        self._release_keyboard_navigation()
        for after_id in list(self._fade_after_ids):
            try:
                self.frame.after_cancel(after_id)
            except Exception:
                pass
        self._fade_after_ids.clear()
        try:
            if self._escape_binding:
                self.frame.winfo_toplevel().unbind("<Escape>", self._escape_binding)
                self._escape_binding = None
        except Exception:
            pass

    def _bind_keyboard_navigation(self) -> None:
        top = self.frame.winfo_toplevel()
        callbacks = {
            "<KeyPress-Left>": lambda event: self._move_keyboard(event, "left"),
            "<KeyPress-Right>": lambda event: self._move_keyboard(event, "right"),
            "<KeyPress-Up>": lambda event: self._move_keyboard(event, "up"),
            "<KeyPress-Down>": lambda event: self._move_keyboard(event, "down"),
        }
        callbacks.update({sequence: self._accept_keyboard for sequence in keypress_sequences(self.navigation_keys.get("accept", "z"))})
        callbacks.update({sequence: self._clear_keyboard for sequence in keypress_sequences(self.navigation_keys.get("back", "x"))})
        for sequence, callback in callbacks.items():
            try:
                binding = top.bind(sequence, callback, add="+")
                if binding:
                    self._keyboard_bindings.append((sequence, binding))
            except Exception:
                pass

    def _release_keyboard_navigation(self) -> None:
        try:
            top = self.frame.winfo_toplevel()
            for sequence, binding in self._keyboard_bindings:
                top.unbind(sequence, binding)
        except Exception:
            pass
        self._keyboard_bindings.clear()

    def _reset_keyboard_targets(self) -> None:
        self._keyboard_targets.clear()
        self._keyboard_navigation.reset((), preserve=False)

    def _register_keyboard_target(
        self, key: object, row: int, column: int, widget, callback: Callable[[], None],
    ) -> None:
        try:
            base_color = str(widget.cget("border_color"))
            base_width = int(widget.cget("border_width"))
        except Exception:
            base_color, base_width = "#3A3A3A", 1
        self._keyboard_targets[key] = (widget, callback, base_color, base_width)
        targets = list(self._keyboard_navigation.targets)
        targets.append(SpatialTarget(key, int(row), int(column)))
        self._keyboard_navigation.reset(targets)

    def _move_keyboard(self, event, direction: str) -> str | None:
        if event_targets_text_input(event):
            return None
        guard = getattr(self, "navigation_guard", None)
        if callable(guard) and not guard():
            return None
        intercept = getattr(self, "navigation_intercept", None)
        if callable(intercept) and intercept(direction):
            return "break"
        before = self._keyboard_navigation.selected_key
        self._keyboard_navigation.move(direction)
        if direction == "left" and before == self._keyboard_navigation.selected_key:
            if callable(self.on_left_edge): self.on_left_edge()
            return "break"
        self._apply_keyboard_selection()
        return "break"

    def _accept_keyboard(self, event=None) -> str | None:
        if event is not None and event_targets_text_input(event):
            return None
        guard = getattr(self, "navigation_guard", None)
        if callable(guard) and not guard():
            return None
        if callable(self.on_edge_accept) and self.on_edge_accept():
            return "break"
        current = self._keyboard_navigation.current
        target = self._keyboard_targets.get(current.key) if current is not None else None
        if target is not None:
            target[1]()
        return "break"

    def _clear_keyboard(self, event=None) -> str | None:
        if event is not None and event_targets_text_input(event):
            return None
        guard = getattr(self, "navigation_guard", None)
        if callable(guard) and not guard():
            return None
        intercept = getattr(self, "navigation_intercept", None)
        if callable(intercept) and intercept("back"):
            return "break"
        if self.step > 1:
            self.on_back()
            return "break"
        self._keyboard_navigation.clear()
        self._apply_keyboard_selection()
        return "break"

    def _apply_keyboard_selection(self) -> None:
        selected = None if self._external_navigation_focus else self._keyboard_navigation.selected_key
        for key, (widget, _callback, base_color, base_width) in self._keyboard_targets.items():
            try:
                configurar_si_cambia(
                    widget,
                    border_color="#F2C45E" if key == selected else base_color,
                    border_width=4 if key == selected else base_width,
                )
            except Exception:
                pass

    def set_external_navigation_focus(self, active: bool) -> None:
        self._external_navigation_focus = bool(active)
        self._apply_keyboard_selection()

    @property
    def step(self) -> int:
        if self.selected_pokemon is None:
            return 1
        return 3 if self.selected_draft is not None else 2

    def _render_header(self) -> None:
        header = ctk.CTkFrame(self.frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(14, 8))
        header.grid_columnconfigure(1, weight=1)
        if self.step > 1:
            ctk.CTkButton(
                header, text="←", width=40, height=34,
                # Este único control siempre vuelve al inicio del drafteo. En la
                # pantalla 1 no existe nada que cerrar ni deshacer.
                command=self.on_cancel,
                fg_color="transparent", hover_color="#303030", border_width=1,
                border_color="#4A4A4A", text_color=TEXT,
            ).grid(row=0, column=0, rowspan=2, padx=(0, 12))
        titles = {
            1: "1 · ELIGE EL POKÉMON",
            2: "2 · ELIGE EL MOVIMIENTO NUEVO",
            3: "3 · ELIGE QUÉ MOVIMIENTO OLVIDARÁ",
        }
        subtitles = {
            1: "Los seis miembros se muestran a la vez. Cada rol genera su propio conjunto de opciones.",
            2: "Enseñarla ahora o guardarla para después cuesta un drafteo. Repetir la tirada, no.",
            3: "El drafteo se consume únicamente al confirmar uno de estos cuatro huecos.",
        }
        ctk.CTkLabel(header, text=titles[self.step], text_color=GOLD, anchor="w",
                     font=ctk.CTkFont("Segoe UI", 20, "bold")).grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(header, text=subtitles[self.step], text_color=MUTED, anchor="w",
                     font=ctk.CTkFont("Segoe UI", 11)).grid(row=1, column=1, sticky="w")
        if self.on_open_moves is not None:
            ctk.CTkButton(
                header,
                text="CONSULTAR MOVIMIENTOS",
                command=self.on_open_moves,
                width=165,
                height=34,
                fg_color="transparent",
                hover_color="#303030",
                border_width=1,
                border_color=GOLD,
                text_color=GOLD,
                font=ctk.CTkFont("Segoe UI", 10, "bold"),
            ).grid(row=0, column=2, rowspan=2, padx=(12, 0))
        ctk.CTkLabel(header, text=f"DRAFTEOS · {self.draft_count}", text_color=SUCCESS if self.draft_count else DANGER,
                     font=ctk.CTkFont("Segoe UI", 12, "bold")).grid(row=0, column=3, rowspan=2, padx=(12, 0))

    def _render_step(self) -> None:
        self._reset_keyboard_targets()
        if self.step == 1:
            self._render_pokemon_step()
        elif self.step == 2:
            self._render_results_step()
        else:
            self._render_replace_step()

    def _render_pokemon_step(self) -> None:
        host = ctk.CTkFrame(self.content, fg_color="transparent")
        host.grid(row=0, column=0, sticky="nsew")
        for column in range(3):
            host.grid_columnconfigure(column, weight=1, uniform="draft_party")
        card_row = 0
        for row in range(card_row, card_row + 2):
            host.grid_rowconfigure(row, weight=0, minsize=246, uniform="draft_party_rows")
        for index, slot in enumerate(self.team_slots):
            pokemon = slot.get("pokemon")
            if pokemon is None:
                card = ctk.CTkFrame(host, height=240, fg_color="#181818", corner_radius=13,
                                    border_width=1, border_color="#303030")
                card.grid(row=card_row + index // 3, column=index % 3, sticky="nsew", padx=5, pady=5)
                card.grid_propagate(False)
                ctk.CTkLabel(card, text=slot.get("slot_role", "CASILLA").upper(), text_color=MUTED,
                             font=ctk.CTkFont("Segoe UI", 10, "bold")).pack(expand=True)
                continue
            role, symbol = self.role_for(pokemon)
            eligible = role != "SIN ROL" and self.draft_count > 0
            image = self.sprite_for(pokemon, (112, 112))
            if image is not None:
                self.images.append(image)
            moves, _move_ids = self.moves_for(pokemon)
            visible_moves = [str(move) for move in moves[:4]]
            while len(visible_moves) < 4:
                visible_moves.append("—")
            nature = str(getattr(pokemon, "nature", "") or "Naturaleza no disponible")
            item = str(getattr(pokemon, "held_item", "") or "Sin objeto")
            name = str(getattr(pokemon, "nickname", "") or getattr(pokemon, "species", "Pokémon"))
            species = str(getattr(pokemon, "species", "") or "Pokémon")
            stats = dict(getattr(pokemon, "stats", {}) or {})
            ivs = dict(getattr(pokemon, "ivs", {}) or {})
            evs = dict(getattr(pokemon, "evs", {}) or {})
            max_hp = int(getattr(pokemon, "max_hp", 0) or 0)
            if max_hp > 0:
                stats["hp"] = max_hp
            increased = getattr(pokemon, "nature_increased", None)
            decreased = getattr(pokemon, "nature_decreased", None)
            card = ctk.CTkFrame(
                host,
                height=240,
                corner_radius=13,
                fg_color=PANEL if eligible else "#191919",
                # Líbero ya queda identificado por texto e icono. Su antiguo
                # borde dorado parecía un segundo cursor persistente.
                border_width=1,
                border_color="#3A3A3A",
            )
            card.grid(row=card_row + index // 3, column=index % 3, sticky="nsew", padx=5, pady=5)
            card.grid_propagate(False)
            card.grid_columnconfigure(1, weight=1)
            card.grid_rowconfigure(5, weight=1)

            portrait = ctk.CTkFrame(card, fg_color="transparent", corner_radius=0)
            portrait.grid(row=0, column=0, rowspan=7, sticky="ns", padx=(12, 8), pady=10)
            ctk.CTkLabel(
                portrait, text="", image=image, width=118, height=118,
            ).pack()
            ctk.CTkLabel(
                portrait,
                text=f"{symbol} {role}".strip(),
                text_color=GOLD if eligible else MUTED,
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
            ).pack(pady=(2, 0))
            role_icon = self.role_icon_for(role, 38)
            if role_icon is not None:
                self.images.append(role_icon)
                ctk.CTkLabel(
                    portrait, text="", image=role_icon, width=42, height=42,
                ).pack(pady=(2, 0))

            top = ctk.CTkFrame(card, fg_color="transparent", corner_radius=0)
            top.grid(row=0, column=1, rowspan=5, sticky="nsew", padx=(0, 11), pady=(8, 2))
            top.grid_columnconfigure(0, weight=2)
            top.grid_columnconfigure(1, weight=3)
            identity = ctk.CTkFrame(top, fg_color="transparent", corner_radius=0)
            identity.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
            ctk.CTkLabel(
                identity, text=name, text_color=TEXT if eligible else MUTED,
                height=24, anchor="w", font=ctk.CTkFont("Segoe UI", 19, "bold"),
            ).pack(fill="x")
            ctk.CTkLabel(
                identity,
                text=f"{species}  ·  Nv. {getattr(pokemon, 'level', '—')}",
                height=17, text_color=MUTED, anchor="w",
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
            ).pack(fill="x")
            ctk.CTkLabel(
                identity, text=f"NATURALEZA · {nature}",
                text_color=GOLD if eligible else MUTED,
                height=18, anchor="w", font=ctk.CTkFont("Segoe UI", 10, "bold"),
            ).pack(fill="x", pady=(3, 0))
            ctk.CTkLabel(
                identity, text=f"OBJETO · {item}", text_color=MUTED,
                height=18, anchor="w", font=ctk.CTkFont("Segoe UI", 10),
            ).pack(fill="x")

            stat_grid = ctk.CTkFrame(top, fg_color="#202020", corner_radius=8)
            stat_grid.grid(row=0, column=1, sticky="nsew")
            for stat_column in range(3):
                stat_grid.grid_columnconfigure(stat_column, weight=1, uniform="draft_card_stats")
            stat_grid.grid_rowconfigure((0, 1), weight=1, uniform="draft_card_stat_rows")
            for stat_index, key in enumerate(STAT_KEYS):
                stat_column = stat_index % 3
                stat_row = stat_index // 3
                color = DANGER if key == increased else ("#73A9FF" if key == decreased else GOLD)
                stat = ctk.CTkFrame(stat_grid, fg_color="transparent", corner_radius=0)
                stat.grid(row=stat_row, column=stat_column, sticky="nsew", padx=1, pady=1)
                ctk.CTkLabel(
                    stat, text=STAT_LABELS[key], height=10, text_color=color,
                    font=ctk.CTkFont("Segoe UI", 8, "bold"),
                ).pack()
                ctk.CTkLabel(
                    stat, text=str(stats.get(key, "—")), height=12, text_color=TEXT,
                    font=ctk.CTkFont("Segoe UI", 11, "bold"),
                ).pack()
                ctk.CTkLabel(
                    stat,
                    text=f"IV {ivs.get(key, '—')} · EV {evs.get(key, '—')}",
                    height=10, text_color=MUTED,
                    font=ctk.CTkFont("Segoe UI", 8, "bold"),
                ).pack()

            move_grid = ctk.CTkFrame(card, fg_color="transparent", corner_radius=0)
            move_grid.grid(row=5, column=1, sticky="nsew", padx=(0, 11), pady=(3, 3))
            move_grid.grid_columnconfigure((0, 1), weight=1, uniform="draft_card_moves")
            for move_index, move in enumerate(visible_moves):
                ctk.CTkLabel(
                    move_grid,
                    text=move,
                    height=30,
                    corner_radius=7,
                    fg_color="#252525" if eligible else "#1D1D1D",
                    text_color=TEXT if eligible and move != "—" else MUTED,
                    font=ctk.CTkFont("Segoe UI", 12, "bold"),
                ).grid(
                    row=move_index // 2,
                    column=move_index % 2,
                    sticky="ew",
                    padx=2,
                    pady=2,
                )

            choose = ctk.CTkButton(
                card,
                text="ELEGIR" if eligible else "EN PREPARACIÓN",
                command=lambda p=pokemon, r=role: self._choose_pokemon(p, r),
                state="normal" if eligible else "disabled",
                height=28,
                fg_color=GOLD if eligible else "#252525",
                hover_color="#D3AF70",
                text_color="#111111",
                text_color_disabled="#666666",
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
            )
            choose.grid(row=6, column=1, sticky="ew", padx=(0, 13), pady=(0, 9))
            if eligible:
                self._register_keyboard_target(
                    ("pokemon", index), card_row + index // 3, index % 3, card,
                    lambda p=pokemon, r=role: self._choose_pokemon(p, r),
                )
                self._bind_card_click(
                    card,
                    lambda _event=None, p=pokemon, r=role: self._choose_pokemon(p, r),
                    exclude={choose},
                )

    def _choose_pokemon(self, pokemon: Any, role: str) -> None:
        self.on_choose_pokemon(pokemon, role)

    def _render_results_step(self) -> None:
        grid = ctk.CTkFrame(self.content, fg_color="transparent")
        grid.grid(row=0, column=0, sticky="nsew")
        layout = _draft_result_layout(len(self.results))
        for column in range(6):
            grid.grid_columnconfigure(column, weight=1, uniform="draft_results")
        rows = max(1, max((row for row, _column, _span in layout), default=0) + 1)
        for row in range(rows):
            grid.grid_rowconfigure(row, weight=0, minsize=224, uniform="draft_results")
        for index, result in enumerate(self.results):
            result_row, result_column, result_span = layout[index]
            metadata = self.move_metadata_for(int(result["move_id"]))
            selected = bool(
                self.selected_draft is not None
                and getattr(self.selected_draft, "pool_key", "") == result.get("pool_key")
                and int(getattr(self.selected_draft, "move_id", 0)) == int(result["move_id"])
            )
            card = ctk.CTkFrame(grid, height=212, fg_color=PANEL, corner_radius=13,
                                border_width=2 if selected else 1,
                                border_color=GOLD if selected else "#3A3A3A")
            card.grid(row=result_row, column=result_column, columnspan=result_span,
                      sticky="nsew", padx=6, pady=6)
            card.pack_propagate(False)
            ctk.CTkLabel(card, text=str(result.get("title", "OPCIÓN")).upper(), text_color=MUTED,
                         font=ctk.CTkFont("Segoe UI", 10, "bold")).pack(pady=(12, 2))
            ctk.CTkLabel(card, text=str(result["move"]), text_color=GOLD if selected else TEXT,
                         font=ctk.CTkFont("Segoe UI", 19, "bold")).pack()
            ctk.CTkLabel(card, text=self._metadata_line(metadata), text_color=MUTED,
                         font=ctk.CTkFont("Segoe UI", 10, "bold")).pack(pady=(3, 5))
            ctk.CTkLabel(
                card,
                text=str(metadata.get("description", "Descripción no disponible")),
                text_color=MUTED,
                wraplength=390,
                justify="center",
                font=ctk.CTkFont("Segoe UI", 10),
            ).pack(fill="x", padx=16, pady=(0, 7))
            actions = ctk.CTkFrame(card, fg_color="transparent")
            actions.pack(side="bottom", fill="x", padx=12, pady=(0, 12))
            # Dos salidas para la misma tirada: enseñarla ahora o quedársela.
            # Las dos cuestan el mismo drafteo, así que guardar no es una vía
            # para acumular tiradas gratis.
            choose = ctk.CTkButton(
                actions, text="ENSEÑAR AHORA", height=32,
                command=lambda i=index: self.on_choose_move(i),
                fg_color=GOLD, hover_color="#D3AF70", text_color="#111111",
                font=ctk.CTkFont("Segoe UI", 10, "bold"),
            )
            choose.pack(side="left", fill="x", expand=True)
            columna = result_column * 3
            self._register_keyboard_target(
                ("result-choose", index), result_row, columna, choose,
                lambda i=index: self.on_choose_move(i),
            )
            if self.on_save_move is not None:
                save = ctk.CTkButton(
                    actions, text="GUARDAR", width=86, height=32,
                    command=lambda i=index: self.on_save_move(i),
                    fg_color="transparent", hover_color="#303030", border_width=1,
                    border_color=GOLD, text_color=GOLD,
                    font=ctk.CTkFont("Segoe UI", 10, "bold"),
                )
                save.pack(side="left", padx=(7, 0))
                columna += 1
                self._register_keyboard_target(
                    ("result-save", index), result_row, columna, save,
                    lambda i=index: self.on_save_move(i),
                )
            reroll = ctk.CTkButton(
                actions, text="↻", width=38, height=32,
                command=lambda i=index: self.on_reroll(i),
                fg_color="transparent", hover_color="#303030", border_width=1,
                border_color="#4A4A4A", text_color=MUTED,
            )
            reroll.pack(side="left", padx=(7, 0))
            self._register_keyboard_target(
                ("result-reroll", index), result_row, columna + 1,
                reroll, lambda i=index: self.on_reroll(i),
            )

    def _render_replace_step(self) -> None:
        names, ids = self.moves_for(self.selected_pokemon)
        grid = ctk.CTkFrame(self.content, fg_color="transparent")
        grid.grid(row=0, column=0, sticky="nsew")
        grid.grid_columnconfigure((0, 1), weight=1, uniform="draft_replace")
        grid.grid_rowconfigure((0, 1), weight=0, minsize=220, uniform="draft_replace")
        for index in range(4):
            metadata = self.move_metadata_for(int(ids[index] or 0))
            card = ctk.CTkFrame(grid, height=208, fg_color=PANEL, corner_radius=13,
                                border_width=1, border_color="#3A3A3A")
            card.grid(row=index // 2, column=index % 2, sticky="ew", padx=7, pady=7)
            card.pack_propagate(False)
            ctk.CTkLabel(card, text=f"HUECO {index + 1}", text_color=GOLD,
                         font=ctk.CTkFont("Segoe UI", 10, "bold")).pack(pady=(12, 2))
            ctk.CTkLabel(card, text=names[index] or "—", text_color=TEXT,
                         font=ctk.CTkFont("Segoe UI", 18, "bold")).pack()
            ctk.CTkLabel(card, text=self._metadata_line(metadata), text_color=MUTED,
                         font=ctk.CTkFont("Segoe UI", 10, "bold")).pack(pady=(3, 3))
            ctk.CTkLabel(
                card,
                text=str(metadata.get("description", "Descripción no disponible")),
                text_color=MUTED,
                wraplength=470,
                justify="center",
                font=ctk.CTkFont("Segoe UI", 10),
            ).pack(fill="x", padx=16, pady=(0, 4))
            ctk.CTkLabel(card, text=f"→ {getattr(self.selected_draft, 'move', '—')}", text_color=SUCCESS,
                         font=ctk.CTkFont("Segoe UI", 11, "bold")).pack(pady=(0, 5))
            choose = ctk.CTkButton(
                card, text="SUSTITUIR Y CONSUMIR 1 DRAFTEO", height=32,
                command=lambda slot=index + 1: self.on_choose_slot(slot),
                fg_color=GOLD, hover_color="#D3AF70", text_color="#111111",
                font=ctk.CTkFont("Segoe UI", 10, "bold"),
            )
            choose.pack(side="bottom", fill="x", padx=18, pady=(0, 10))
            self._register_keyboard_target(
                ("replace", index), index // 2, index % 2, card,
                lambda slot=index + 1: self.on_choose_slot(slot),
            )

    def _rerender_content(self) -> None:
        for child in self.content.winfo_children():
            child.destroy()
        self._render_step()

    def fade_out(self, on_complete: Callable[[], None]) -> None:
        """Desvanece solo el contenido del flujo, nunca la ventana principal."""
        targets = self._fade_targets()
        if not targets:
            on_complete()
            return
        self._run_fade(targets, (0.32, 0.66, 1.0), on_complete, hide_images=True)

    def fade_in(self) -> None:
        """Hace aparecer el nuevo paso sobre el fondo estable del flujo."""
        targets = self._fade_targets()
        if not targets:
            return
        self._apply_fade(targets, 1.0, hide_images=True)
        self._run_fade(targets, (0.68, 0.34, 0.0), None, hide_images=False)

    def _run_fade(
        self,
        targets: list[tuple[Any, dict[str, str], Any]],
        ratios: tuple[float, ...],
        on_complete: Callable[[], None] | None,
        *,
        hide_images: bool,
    ) -> None:
        def step(index: int) -> None:
            if index >= len(ratios):
                if on_complete is not None:
                    on_complete()
                return
            ratio = ratios[index]
            self._apply_fade(
                targets,
                ratio,
                hide_images=hide_images and ratio >= 0.66,
            )
            after_id = self.frame.after(34, lambda: step(index + 1))
            self._fade_after_ids.add(after_id)

        step(0)

    def _fade_targets(self) -> list[tuple[Any, dict[str, str], Any]]:
        targets: list[tuple[Any, dict[str, str], Any]] = []

        def walk(widget) -> None:
            colors: dict[str, str] = {}
            for option in ("fg_color", "text_color", "text_color_disabled", "border_color"):
                try:
                    value = widget.cget(option)
                except Exception:
                    continue
                if isinstance(value, str) and value.startswith("#") and len(value) == 7:
                    colors[option] = value
            try:
                image = widget.cget("image")
            except Exception:
                image = None
            if colors or image is not None:
                targets.append((widget, colors, image))
            try:
                children = widget.winfo_children()
            except Exception:
                children = ()
            for child in children:
                walk(child)

        walk(self.content)
        return targets

    @staticmethod
    def _mix_color(source: str, target: str, ratio: float) -> str:
        ratio = max(0.0, min(float(ratio), 1.0))
        source_rgb = tuple(int(source[index:index + 2], 16) for index in (1, 3, 5))
        target_rgb = tuple(int(target[index:index + 2], 16) for index in (1, 3, 5))
        mixed = tuple(round(start + (end - start) * ratio) for start, end in zip(source_rgb, target_rgb))
        return "#" + "".join(f"{value:02X}" for value in mixed)

    def _apply_fade(
        self,
        targets: list[tuple[Any, dict[str, str], Any]],
        ratio: float,
        *,
        hide_images: bool,
    ) -> None:
        background = "#151515"
        for widget, colors, image in targets:
            try:
                updates = {
                    option: self._mix_color(value, background, ratio)
                    for option, value in colors.items()
                }
                if image is not None:
                    updates["image"] = None if hide_images else image
                if updates:
                    widget.configure(**updates)
            except Exception:
                continue

    @classmethod
    def _bind_card_click(
        cls,
        widget,
        callback: Callable[..., None],
        *,
        exclude: set[Any] | None = None,
    ) -> None:
        excluded = exclude or set()
        if widget in excluded:
            return
        try:
            widget.bind("<Button-1>", callback, add="+")
            widget.configure(cursor="hand2")
        except Exception:
            pass
        try:
            children = widget.winfo_children()
        except Exception:
            children = ()
        for child in children:
            cls._bind_card_click(child, callback, exclude=excluded)

    @staticmethod
    def _metadata_line(metadata: dict[str, Any]) -> str:
        category = {"physical": "FÍSICO", "special": "ESPECIAL", "status": "ESTADO"}.get(
            str(metadata.get("category", "unknown")), "NO DISPONIBLE",
        )
        return (
            f"{category} · Pot. {metadata.get('power', '—')} · "
            f"Prec. {metadata.get('accuracy', '—')} · PP {metadata.get('pp', '—')}"
        )
