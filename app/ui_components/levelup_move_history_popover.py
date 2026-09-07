from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

import customtkinter as ctk

from app.config import GOLD, MUTED, TEXT

from .window_focus import guard_topmost_on_focus_loss, hide_from_taskbar_and_alttab, release_focus_guard

_CATEGORY_LABELS = {
    "physical": "Físico", "special": "Especial", "status": "Estado",
    "unknown": "Sin clasificar",
}


class LevelupMoveHistoryPopover:
    """Recuerda-movimientos: todo lo que un Pokémon ha aprendido por nivel.

    Pedido por el usuario el 2026-09-03. Cada movimiento se muestra con la
    misma ficha que el resto del catálogo —coloreada por tipo, con
    categoría/potencia/precisión/PP— y ENSEÑAR solo se activa si el
    movimiento encaja con el ROL ACTUAL del Pokémon, no con el que tenía
    cuando lo aprendió. Mismo patrón de dos ventanas (scrim + tarjeta) que
    ``MoveInfoPopover``, por el mismo motivo: cerrar un ``CTkToplevel`` propio
    no obliga a repintar Equipo y PC.
    """

    def __init__(
        self,
        master,
        pokemon_name: str,
        role: str,
        entries: Sequence[Mapping[str, Any]],
        *,
        on_close: Callable[[], None],
        on_teach: Callable[[Mapping[str, Any]], None],
    ) -> None:
        self.master = master
        self.on_close = on_close
        self.on_teach = on_teach
        master.update_idletasks()
        screen_w = max(1, int(master.winfo_width()))
        screen_h = max(1, int(master.winfo_height()))
        root_x = int(master.winfo_rootx())
        root_y = int(master.winfo_rooty())

        self.scrim = ctk.CTkToplevel(master)
        self.scrim.overrideredirect(True)
        self.scrim.attributes("-topmost", True)
        self.scrim.attributes("-alpha", 0.55)
        self.scrim.configure(fg_color="#000000")
        self.scrim.geometry(f"{screen_w}x{screen_h}+{root_x}+{root_y}")
        self.scrim.bind("<ButtonRelease-1>", lambda _event: self.close(), add="+")

        card_w = max(480, min(680, int(screen_w * 0.42)))
        self._card_w = card_w
        card_h = max(420, min(720, int(screen_h * 0.78)))
        card_x = root_x + (screen_w - card_w) // 2
        card_y = root_y + (screen_h - card_h) // 2
        self.card_window = ctk.CTkToplevel(master)
        self.card_window.overrideredirect(True)
        self.card_window.attributes("-topmost", True)
        self.card_window.geometry(f"{card_w}x{card_h}+{card_x}+{card_y}")
        self._focus_guard = guard_topmost_on_focus_loss(
            master.winfo_toplevel(), self.scrim, self.card_window,
        )
        hide_from_taskbar_and_alttab(self.scrim, self.card_window)

        self.card = ctk.CTkFrame(
            self.card_window, fg_color="#111111",
            corner_radius=18, border_width=2, border_color=GOLD,
        )
        self.card.pack(fill="both", expand=True)
        self.card.pack_propagate(False)

        header = ctk.CTkFrame(self.card, fg_color="transparent")
        header.pack(fill="x", padx=22, pady=(20, 4))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header, text=f"{pokemon_name.upper()} · RECUERDA-MOVIMIENTOS",
            text_color=GOLD, anchor="w", wraplength=card_w - 140,
            font=ctk.CTkFont("Segoe UI", 18, "bold"), justify="left",
        ).grid(row=0, column=0, sticky="w")
        close_button = ctk.CTkButton(
            header, text="×", width=40, height=38,
            fg_color="transparent", hover_color="#303030", text_color=TEXT,
            font=ctk.CTkFont("Segoe UI", 20, "bold"),
        )
        close_button.grid(row=0, column=1, sticky="e")
        close_button.bind("<ButtonRelease-1>", lambda _event: self.close(), add="+")

        ctk.CTkLabel(
            self.card,
            text=(
                f"Rol actual: {role}. Solo puedes volver a enseñar los movimientos "
                "compatibles con el rol de ahora, aunque los aprendiera con otro."
            ),
            text_color=MUTED, wraplength=card_w - 44, justify="left", anchor="w",
            font=ctk.CTkFont("Segoe UI", 12),
        ).pack(fill="x", padx=22, pady=(0, 14))

        if not entries:
            ctk.CTkLabel(
                self.card,
                text="Todavía no se ha registrado ningún movimiento aprendido por nivel.",
                text_color=MUTED, wraplength=card_w - 44, justify="left",
                font=ctk.CTkFont("Segoe UI", 13),
            ).pack(padx=22, pady=30)
        else:
            scroll = ctk.CTkScrollableFrame(self.card, fg_color="transparent")
            scroll.pack(fill="both", expand=True, padx=16, pady=(0, 16))
            for entry in entries:
                self._build_entry_card(scroll, entry)

        self._escape_binding = master.winfo_toplevel().bind(
            "<Escape>", lambda _event: self.close(), add="+",
        )

    def _build_entry_card(self, parent, entry: Mapping[str, Any]) -> None:
        type_color = str(entry.get("type_color") or "#3A3A3A")
        already_known = bool(entry.get("already_known"))
        teachable = bool(entry.get("teachable"))

        card = ctk.CTkFrame(
            parent, fg_color="#171717", corner_radius=12,
            border_width=2, border_color=type_color,
        )
        card.pack(fill="x", pady=5)
        card.grid_columnconfigure(0, weight=1)

        row = 0
        top = ctk.CTkFrame(card, fg_color="transparent")
        top.grid(row=row, column=0, columnspan=2, sticky="ew", padx=16, pady=(12, 2))
        top.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            top, text=f"Nv. {entry.get('level', 0)}  ·  {entry.get('move_name', '')}",
            text_color=TEXT, font=ctk.CTkFont("Segoe UI", 15, "bold"), anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            top, text=str(entry.get("type_name", "")), text_color="#111111",
            fg_color=type_color, corner_radius=6,
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
        ).grid(row=0, column=1, padx=(10, 0), ipadx=8, ipady=2)
        row += 1

        category_key = str(entry.get("category", "unknown"))
        category_label = _CATEGORY_LABELS.get(category_key, category_key.title())
        detalle = (
            f"Categoría: {category_label}  ·  "
            f"Potencia: {entry.get('power', '—')}  ·  "
            f"Precisión: {entry.get('accuracy', '—')}  ·  "
            f"PP: {entry.get('pp', '—')}"
        )
        ctk.CTkLabel(
            card, text=detalle, text_color=MUTED,
            font=ctk.CTkFont("Segoe UI", 11), anchor="w",
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 6))
        row += 1

        description = str(entry.get("description") or "").strip()
        if description:
            ctk.CTkLabel(
                card, text=description, text_color=MUTED, wraplength=self._card_w - 44,
                justify="left", font=ctk.CTkFont("Segoe UI", 11), anchor="w",
            ).grid(row=row, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 6))
            row += 1

        ctk.CTkLabel(
            card, text=str(entry.get("procedencia", "")), text_color=MUTED,
            font=ctk.CTkFont("Segoe UI", 10), anchor="w",
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 6))
        row += 1

        if already_known:
            reason_text = "Ya está entre sus movimientos actuales."
        elif not teachable:
            reason_text = str(entry.get("reason") or "No es compatible con el rol actual.")
        else:
            reason_text = ""
        if reason_text:
            ctk.CTkLabel(
                card, text=reason_text, text_color="#C99A4A", wraplength=self._card_w - 44,
                justify="left", font=ctk.CTkFont("Segoe UI", 10, "bold"), anchor="w",
            ).grid(row=row, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 8))
            row += 1

        def teach(entry=entry) -> None:
            self.close()
            self.on_teach(entry)

        button_text = "YA LO CONOCE" if already_known else ("ENSEÑAR" if teachable else "NO COMPATIBLE")
        ctk.CTkButton(
            card,
            text=button_text,
            height=30, state="normal" if teachable else "disabled",
            fg_color=GOLD if teachable else "#242424", hover_color="#D3AF70",
            text_color="#111111", text_color_disabled="#777777",
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
            command=teach if teachable else None,
        ).grid(row=row, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 12))

    def close(self) -> None:
        try:
            if self._escape_binding:
                self.master.winfo_toplevel().unbind("<Escape>", self._escape_binding)
        except Exception:
            pass
        release_focus_guard(getattr(self, "_focus_guard", None))
        for window in (self.card_window, self.scrim):
            try:
                window.destroy()
            except Exception:
                pass
        self.on_close()
