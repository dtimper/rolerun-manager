from __future__ import annotations

from collections.abc import Callable
from typing import Any

import customtkinter as ctk

from app.config import DANGER, GOLD, MUTED, PANEL, PANEL_ALT, SUCCESS, TEXT
from app.ui_components.repintado import configurar_si_cambia
from app.ui_state.spatial_navigation import (
    SpatialSelection,
    SpatialTarget,
    event_targets_text_input,
    keypress_sequences,
)
from app.ui_state.team_pc_state import TMTeachFlowState


_CATEGORY_NAMES = {
    "physical": "FÍSICO",
    "special": "ESPECIAL",
    "status": "ESTADO",
    "unknown": "NO DISPONIBLE",
}


class IntegratedTMTeachFlow:
    """Selector MT de tres etapas embebido en la página Equipo y PC."""

    def __init__(
        self,
        master,
        *,
        pokemon: Any,
        role: str,
        moves: tuple[dict[str, Any], ...],
        candidates: tuple[dict[str, Any], ...],
        source_detail: str,
        on_apply: Callable[[int, dict[str, Any]], None],
        on_close: Callable[[], None],
        on_open_moves: Callable[[], None] | None = None,
        navigation_keys: dict[str, str] | None = None,
    ) -> None:
        self.master = master
        self.pokemon = pokemon
        self.role = role
        self.moves = moves
        self.source_detail = source_detail
        self.on_apply = on_apply
        self.on_close = on_close
        self.on_open_moves = on_open_moves
        self.navigation_keys = dict(navigation_keys or {"accept": "z", "back": "x"})
        self.navigation_guard: Callable[[], bool] | None = None
        self.state = TMTeachFlowState(candidates=candidates)
        self._keyboard_navigation = SpatialSelection()
        self._keyboard_targets: dict[object, tuple[Any, Callable[[], None], str, int]] = {}
        self._keyboard_bindings: list[tuple[str, str]] = []
        self._keyboard_scroll = None

        height = max(460, int(master.winfo_toplevel().winfo_height() or 720) - 230)
        self.frame = ctk.CTkFrame(
            master, height=height, fg_color="#151515", corner_radius=16,
            border_width=1, border_color="#3A3A3A",
        )
        self.frame.grid(row=0, column=0, sticky="nsew")
        self.frame.grid_propagate(False)
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_rowconfigure(1, weight=1)

        self.header = ctk.CTkFrame(self.frame, fg_color="transparent")
        self.header.grid(row=0, column=0, sticky="ew", padx=20, pady=(15, 8))
        self.header.grid_columnconfigure(1, weight=1)
        self.back_button = ctk.CTkButton(
            self.header, text="←", width=40, height=34, command=self._back,
            fg_color="transparent", hover_color="#303030", border_width=1,
            border_color="#4A4A4A", text_color=TEXT,
        )
        self.back_button.grid(row=0, column=0, rowspan=2, padx=(0, 12))
        self.title = ctk.CTkLabel(
            self.header, text="", text_color=GOLD, anchor="w",
            font=ctk.CTkFont("Segoe UI", 20, "bold"),
        )
        self.title.grid(row=0, column=1, sticky="w")
        self.subtitle = ctk.CTkLabel(
            self.header, text="", text_color=MUTED, anchor="w", justify="left",
            font=ctk.CTkFont("Segoe UI", 11),
        )
        self.subtitle.grid(row=1, column=1, sticky="w")
        ctk.CTkButton(
            self.header, text="CANCELAR", width=105, height=34, command=self._close,
            fg_color="transparent", hover_color="#303030", border_width=1,
            border_color="#4A4A4A", text_color=MUTED,
        ).grid(row=0, column=3, rowspan=2, padx=(8, 0))
        if self.on_open_moves is not None:
            ctk.CTkButton(
                self.header,
                text="CONSULTAR MOVIMIENTOS",
                width=165,
                height=34,
                command=self._open_moves,
                fg_color="transparent",
                hover_color="#303030",
                border_width=1,
                border_color=GOLD,
                text_color=GOLD,
                font=ctk.CTkFont("Segoe UI", 10, "bold"),
            ).grid(row=0, column=2, rowspan=2, padx=(12, 0))

        self.content = ctk.CTkFrame(self.frame, fg_color="transparent")
        self.content.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 15))
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)
        self._escape_binding = self.frame.winfo_toplevel().bind("<Escape>", lambda _event: self._close(), add="+")
        self._bind_keyboard_navigation()
        self._render()

    def destroy(self) -> None:
        self._release_keyboard_navigation()
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

    def is_fully_composed(self) -> bool:
        """Confirma que el selector que se publicará ya tiene geometría final."""
        try:
            self.frame.update_idletasks()
            return bool(
                self.frame.winfo_exists()
                and self.frame.winfo_ismapped()
                and self.frame.winfo_width() > 400
                and self.frame.winfo_height() > 400
                and self.content.winfo_ismapped()
                and self.content.winfo_width() > 300
                and self.content.winfo_height() > 250
            )
        except Exception:
            return False

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
        self._keyboard_scroll = None

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
        self._keyboard_navigation.move(direction)
        self._apply_keyboard_selection()
        return "break"

    def _accept_keyboard(self, event=None) -> str | None:
        if event is not None and event_targets_text_input(event):
            return None
        guard = getattr(self, "navigation_guard", None)
        if callable(guard) and not guard():
            return None
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
        # Atrás recorre la jerarquía MT ← hueco ← confirmación. No
        # borra un cursor sin cambiar de nivel, comportamiento que parecía no
        # responder y obligaba a empezar la navegación desde cero.
        self._back()
        return "break"

    def _apply_keyboard_selection(self) -> None:
        selected = self._keyboard_navigation.selected_key
        selected_widget = None
        for key, (widget, _callback, base_color, base_width) in self._keyboard_targets.items():
            try:
                configurar_si_cambia(
                    widget,
                    border_color="#F2C45E" if key == selected else base_color,
                    border_width=4 if key == selected else base_width,
                )
                if key == selected:
                    selected_widget = widget
            except Exception:
                pass
        if selected_widget is not None and self._keyboard_scroll is not None:
            self.frame.after_idle(lambda widget=selected_widget: self._reveal_keyboard_widget(widget))

    def _reveal_keyboard_widget(self, widget) -> None:
        canvas = getattr(self._keyboard_scroll, "_parent_canvas", None)
        if canvas is None:
            return
        try:
            content_height = max(1, int(canvas.bbox("all")[3]))
            viewport_height = max(1, int(canvas.winfo_height()))
            top = int(widget.winfo_y())
            bottom = top + int(widget.winfo_height())
            visible_top = int(canvas.canvasy(0))
            if top < visible_top:
                canvas.yview_moveto(max(0.0, top / content_height))
            elif bottom > visible_top + viewport_height:
                canvas.yview_moveto(min(1.0, max(0, bottom - viewport_height) / content_height))
        except Exception:
            pass

    def _close(self) -> str:
        # `<Escape>` está enganchado al toplevel, no a este frame. Al navegar a
        # otra página el flujo no se destruye, así que su Escape seguía vivo:
        # pulsarlo en otra sección levantaba la barrera de «Volviendo a…» sobre
        # una página que nunca había abierto ningún selector.
        try:
            if not self.frame.winfo_exists():
                return "break"
        except Exception:
            return "break"

        # El controlador captura primero esta superficie completa y solo después
        # la destruye. Retirarla aquí dejaba a la captura el árbol inferior a
        # medio reconstruir, origen demostrado del frame roto al volver.
        self.on_close()
        return "break"

    def _open_moves(self) -> None:
        callback = self.on_open_moves
        self.on_close()
        if callback is not None:
            callback()

    def _back(self) -> None:
        if self.state.step == 1:
            self._close()
            return
        self.state.back()
        self._render()

    def _render(self) -> None:
        for child in self.content.winfo_children():
            child.destroy()
        self._reset_keyboard_targets()
        self.back_button.configure(text="×" if self.state.step == 1 else "←")
        if self.state.step == 1:
            self._render_tm_step()
        elif self.state.step == 2:
            self._render_slot_step()
        else:
            self._render_preview_step()

    def _render_tm_step(self) -> None:
        name = str(getattr(self.pokemon, "nickname", "") or getattr(self.pokemon, "species", "Pokémon"))
        self.title.configure(text=f"1 · ELIGE UNA MT PARA {name.upper()}")
        self.subtitle.configure(text=f"Rol {self.role} · {self.source_detail}")
        scroll = ctk.CTkScrollableFrame(self.content, fg_color="#111111", corner_radius=12)
        self._keyboard_scroll = scroll
        scroll.grid(row=0, column=0, sticky="nsew")
        scroll.grid_columnconfigure((0, 1), weight=1, uniform="tm_flow")
        if not self.state.candidates:
            ctk.CTkLabel(
                scroll,
                text="No hay ninguna MT demostrada en la mochila que pueda producir un moveset válido para este rol.",
                text_color=MUTED, wraplength=700, justify="center",
                font=ctk.CTkFont("Segoe UI", 14, "bold"),
            ).grid(row=0, column=0, columnspan=2, padx=30, pady=80)
            return
        for index, candidate in enumerate(self.state.candidates):
            card = ctk.CTkFrame(
                scroll, fg_color=PANEL, corner_radius=12,
                border_width=1, border_color="#3B3B3B",
            )
            card.grid(row=index // 2, column=index % 2, sticky="nsew", padx=6, pady=6)
            card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(
                card,
                text=f"MT{int(candidate['number']):02d} · {candidate['move_name']}",
                text_color=TEXT, anchor="w",
                font=ctk.CTkFont("Segoe UI", 15, "bold"),
            ).grid(row=0, column=0, sticky="ew", padx=13, pady=(10, 1))
            category = _CATEGORY_NAMES.get(str(candidate.get("category", "unknown")), "NO DISPONIBLE")
            ctk.CTkLabel(
                card,
                text=(
                    f"{category} · Pot. {candidate.get('power', '—')} · Prec. {candidate.get('accuracy', '—')} · "
                    f"PP {candidate.get('pp', '—')} · x{candidate.get('quantity', 0)}"
                ),
                text_color=MUTED, anchor="w",
                font=ctk.CTkFont("Segoe UI", 10, "bold"),
            ).grid(row=1, column=0, sticky="ew", padx=13, pady=(0, 9))
            ctk.CTkButton(
                card, text="ELEGIR", width=82, height=34,
                command=lambda move_id=int(candidate["move_id"]): self._choose_tm(move_id),
                fg_color=GOLD, hover_color="#D3AF70", text_color="#111111",
                font=ctk.CTkFont("Segoe UI", 10, "bold"),
            ).grid(row=0, column=1, rowspan=2, padx=(4, 11), pady=10)
            self._register_keyboard_target(
                ("tm", int(candidate["move_id"])), index // 2, index % 2, card,
                lambda move_id=int(candidate["move_id"]): self._choose_tm(move_id),
            )

    def _choose_tm(self, move_id: int) -> None:
        self.state.select_tm(move_id)
        self._render()

    def _render_slot_step(self) -> None:
        candidate = self.state.selected_candidate
        if candidate is None:
            self.state.step = 1
            self._render()
            return
        self.title.configure(text=f"2 · ¿QUÉ MOVIMIENTO OLVIDARÁ?")
        self.subtitle.configure(
            text=f"MT{int(candidate['number']):02d} · {candidate['move_name']} · solo están activos los resultados válidos",
        )
        grid = ctk.CTkFrame(self.content, fg_color="transparent")
        # Cuatro tarjetas compactas centradas. Antes heredaban todo el alto del
        # viewport y dejaban grandes franjas vacías bajo cada botón.
        grid.place(relx=.5, rely=.5, anchor="center", relwidth=.94, relheight=.66)
        grid.grid_columnconfigure((0, 1), weight=1, uniform="tm_slots")
        grid.grid_rowconfigure((0, 1), weight=1, uniform="tm_slots")
        valid_slots = {int(value) for value in candidate.get("valid_slots", ())}
        for index, move in enumerate(self.moves, start=1):
            enabled = index in valid_slots
            card = ctk.CTkFrame(
                grid, fg_color=PANEL if enabled else "#181818", corner_radius=14,
                border_width=2 if enabled else 1,
                border_color=GOLD if enabled else "#333333",
            )
            card.grid(row=(index - 1) // 2, column=(index - 1) % 2, sticky="nsew", padx=7, pady=7)
            ctk.CTkLabel(
                card, text=f"HUECO {index}", text_color=GOLD if enabled else MUTED,
                font=ctk.CTkFont("Segoe UI", 10, "bold"),
            ).pack(pady=(14, 2))
            ctk.CTkLabel(
                card, text=str(move.get("name") or "—"),
                text_color=TEXT if enabled else MUTED,
                font=ctk.CTkFont("Segoe UI", 18, "bold"),
            ).pack(pady=(0, 2))
            category = _CATEGORY_NAMES.get(str(move.get("category", "unknown")), "NO DISPONIBLE")
            ctk.CTkLabel(
                card,
                text=(
                    f"{category} · Pot. {move.get('power', '—')} · Prec. {move.get('accuracy', '—')} · "
                    f"PP {move.get('pp', '—')}"
                ),
                text_color=MUTED, font=ctk.CTkFont("Segoe UI", 10, "bold"),
            ).pack(pady=(0, 7))
            ctk.CTkLabel(
                card,
                text=(f"Resultado válido para {self.role}" if enabled else f"Este reemplazo no cumple {self.role}"),
                text_color=SUCCESS if enabled else DANGER,
                font=ctk.CTkFont("Segoe UI", 10, "bold"),
            ).pack(pady=(0, 4))
            ctk.CTkButton(
                card, text="SUSTITUIR" if int(move.get("move_id", 0) or 0) else "USAR HUECO LIBRE",
                height=30, state="normal" if enabled else "disabled",
                command=lambda slot=index: self._choose_slot(slot),
                fg_color=GOLD, hover_color="#D3AF70", text_color="#111111",
                text_color_disabled="#666666",
                font=ctk.CTkFont("Segoe UI", 10, "bold"),
            ).pack(fill="x", padx=18, pady=(2, 14))
            if enabled:
                self._register_keyboard_target(
                    ("slot", index), (index - 1) // 2, (index - 1) % 2, card,
                    lambda slot=index: self._choose_slot(slot),
                )

    def _choose_slot(self, slot: int) -> None:
        self.state.select_slot(slot)
        self._render()

    def _render_preview_step(self) -> None:
        candidate = self.state.selected_candidate
        slot = int(self.state.selected_slot or 0)
        if candidate is None or not 1 <= slot <= len(self.moves):
            self.state.step = 2
            self._render()
            return
        old_move = str(self.moves[slot - 1].get("name") or "—")
        name = str(getattr(self.pokemon, "nickname", "") or getattr(self.pokemon, "species", "Pokémon"))
        self.title.configure(text="3 · REVISA LA OPERACIÓN")
        self.subtitle.configure(text="RoleRun aún no ha escrito nada. La aplicación empieza al confirmar.")
        preview = ctk.CTkFrame(
            self.content, fg_color="#171717", corner_radius=16,
            border_width=2, border_color=GOLD,
        )
        preview.grid(row=0, column=0, sticky="nsew")
        preview.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            preview, text=name, text_color=TEXT,
            font=ctk.CTkFont("Segoe UI", 25, "bold"),
        ).pack(pady=(36, 18))
        item_result = (
            f"MT{int(candidate['number']):02d} ×1"
            if bool(candidate.get("consumes_item", True))
            else f"MT{int(candidate['number']):02d} · reutilizable"
        )
        lines = (
            ("APRENDERÁ", str(candidate["move_name"]), SUCCESS),
            ("OLVIDARÁ", old_move if old_move != "—" else "Hueco libre", DANGER if old_move != "—" else MUTED),
            ("CONSUMIRÁ" if bool(candidate.get("consumes_item", True)) else "MT", item_result, GOLD),
        )
        for label, value, color in lines:
            row = ctk.CTkFrame(preview, fg_color=PANEL_ALT, corner_radius=11)
            row.pack(fill="x", padx=80, pady=5)
            ctk.CTkLabel(row, text=label, text_color=MUTED, width=120, anchor="w",
                         font=ctk.CTkFont("Segoe UI", 10, "bold")).pack(side="left", padx=(14, 4), pady=11)
            ctk.CTkLabel(row, text=value, text_color=color, anchor="w",
                         font=ctk.CTkFont("Segoe UI", 14, "bold")).pack(side="left", fill="x", expand=True, pady=11)
        confirm = ctk.CTkButton(
            preview, text="APLICAR Y VERIFICAR", height=42,
            command=lambda: self.on_apply(slot, candidate),
            fg_color=GOLD, hover_color="#D3AF70", text_color="#111111",
            font=ctk.CTkFont("Segoe UI", 12, "bold"),
        )
        confirm.pack(fill="x", padx=80, pady=(22, 36))
        self._register_keyboard_target(
            ("confirm", slot), 0, 0, preview,
            lambda: self.on_apply(slot, candidate),
        )
