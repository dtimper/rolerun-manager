from __future__ import annotations

from collections.abc import Callable

import customtkinter as ctk

from app.config import MOVE_TYPE_INFO, MUTED, TEXT

from .window_focus import guard_topmost_on_focus_loss, hide_from_taskbar_and_alttab, release_focus_guard

_CATEGORY_LABELS = {
    "physical": "FÍSICO", "special": "ESPECIAL", "status": "ESTADO",
    "unknown": "SIN CLASIFICAR",
}


class MoveInfoPopover:
    """Ficha de un movimiento: categoría, potencia, precisión, PP y descripción.

    Mismo patrón de dos ventanas (scrim + tarjeta) que
    ``IntegratedRoleInfoPopover``, y por el mismo motivo: destruir un
    ``CTkToplevel`` propio no obliga a repintar Equipo y PC, que un
    ``CTkFrame`` superpuesto sí obligaría.
    """

    def __init__(
        self,
        master,
        move_name: str,
        metadata: dict[str, object],
        *,
        on_close: Callable[[], None],
        category_icons=None,
    ) -> None:
        self.master = master
        self.on_close = on_close
        self._images: list[ctk.CTkImage] = []
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

        card_w = max(420, min(560, int(screen_w * 0.32)))
        card_h = 360
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

        type_id = metadata.get("type_id")
        type_name, type_color = MOVE_TYPE_INFO.get(
            type_id if isinstance(type_id, int) else -1, ("SIN TIPO DEMOSTRADO", "#3A3A3A"),
        )

        self.card = ctk.CTkFrame(
            self.card_window, fg_color="#171717",
            corner_radius=18, border_width=2, border_color=type_color,
        )
        self.card.pack(fill="both", expand=True)
        self.card.pack_propagate(False)

        header = ctk.CTkFrame(self.card, fg_color="transparent")
        header.pack(fill="x", padx=26, pady=(22, 6))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header, text=move_name.upper(), text_color=TEXT, anchor="w",
            font=ctk.CTkFont("Segoe UI", 24, "bold"), wraplength=card_w - 140,
            justify="left",
        ).grid(row=0, column=0, sticky="w")
        close_button = ctk.CTkButton(
            header, text="×", width=42, height=40,
            fg_color="transparent", hover_color="#303030", text_color=TEXT,
            font=ctk.CTkFont("Segoe UI", 22, "bold"),
        )
        close_button.grid(row=0, column=1, sticky="e")
        close_button.bind("<ButtonRelease-1>", lambda _event: self.close(), add="+")

        ctk.CTkLabel(
            self.card, text=type_name, text_color="#111111", fg_color=type_color,
            corner_radius=8, font=ctk.CTkFont("Segoe UI", 13, "bold"),
        ).pack(anchor="w", padx=26, pady=(0, 16), ipadx=10, ipady=4)

        stats = ctk.CTkFrame(self.card, fg_color="#202020", corner_radius=10)
        stats.pack(fill="x", padx=26, pady=(0, 16))
        stats.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="move_info_stats")
        category_key = str(metadata.get("category", "unknown"))
        category_icon = category_icons.image(category_key, 26) if category_icons else None
        category_text = _CATEGORY_LABELS.get(category_key, "SIN CLASIFICAR")
        for column, (label, value) in enumerate((
            ("CATEGORÍA", None if category_icon else category_text),
            ("POTENCIA", str(metadata.get("power", "—"))),
            ("PRECISIÓN", str(metadata.get("accuracy", "—"))),
            ("PP", str(metadata.get("pp", "—"))),
        )):
            ctk.CTkLabel(
                stats, text=label, text_color=MUTED,
                font=ctk.CTkFont("Segoe UI", 10, "bold"),
            ).grid(row=0, column=column, padx=6, pady=(12, 0))
            if column == 0 and category_icon is not None:
                self._images.append(category_icon)
                ctk.CTkLabel(stats, text="", image=category_icon).grid(
                    row=1, column=column, padx=6, pady=(2, 10),
                )
            else:
                ctk.CTkLabel(
                    stats, text=value, text_color=TEXT,
                    font=ctk.CTkFont("Segoe UI", 14, "bold"),
                ).grid(row=1, column=column, padx=6, pady=(0, 12))

        description_label = ctk.CTkLabel(
            self.card,
            text=str(metadata.get("description") or "Descripción no disponible en la fuente activa."),
            text_color=TEXT, wraplength=card_w - 52, justify="left", anchor="w",
            font=ctk.CTkFont("Segoe UI", 14),
        )
        description_label.pack(fill="x", padx=26, pady=(0, 22))

        self._escape_binding = master.winfo_toplevel().bind(
            "<Escape>", lambda _event: self.close(), add="+",
        )

    def close(self) -> str:
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
        return "break"
