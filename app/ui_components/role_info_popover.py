from __future__ import annotations

from collections.abc import Callable

import customtkinter as ctk

from app.config import DANGER, GOLD, MUTED, SUCCESS, TEXT
from app.role_content import GLOBAL_ROLE_NOTE, ROLE_GUIDE


class IntegratedRoleInfoPopover:
    def __init__(
        self,
        master,
        role: str,
        *,
        on_close: Callable[[], None],
        on_open_moves: Callable[[], None] | None = None,
    ) -> None:
        self.master = master
        self.on_close = on_close
        self.scrim = ctk.CTkFrame(master, fg_color="#080808", corner_radius=0)
        self.scrim.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.scrim.lift()
        self.scrim.bind("<Button-1>", lambda _event: self.close(), add="+")
        self.card = ctk.CTkFrame(
            self.scrim, width=610, height=474, fg_color="#171717",
            corner_radius=18, border_width=2, border_color=GOLD,
        )
        self.card.place(relx=0.5, rely=0.48, anchor="center")
        self.card.pack_propagate(False)
        data = ROLE_GUIDE.get(role, ROLE_GUIDE["Líbero"])
        header = ctk.CTkFrame(self.card, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(17, 8))
        ctk.CTkLabel(header, text=role.upper(), text_color=GOLD,
                     font=ctk.CTkFont("Segoe UI", 22, "bold")).pack(side="left")
        ctk.CTkButton(header, text="×", width=34, height=32, command=self.close,
                      fg_color="transparent", hover_color="#303030", text_color=TEXT).pack(side="right")
        ctk.CTkLabel(
            self.card, text=data["summary"], text_color=TEXT, wraplength=550,
            justify="left", anchor="w", font=ctk.CTkFont("Segoe UI", 13, "bold"),
        ).pack(fill="x", padx=22, pady=(0, 10))
        for title, key, color, background in (
            ("✓  PUEDE USAR", "allowed", SUCCESS, "#172219"),
            ("×  LIMITACIONES", "limits", DANGER, "#251919"),
            ("PREPARACIÓN DEL EQUIPO", "preparation", GOLD, "#211D13"),
        ):
            section = ctk.CTkFrame(self.card, fg_color=background, corner_radius=10)
            section.pack(fill="x", padx=22, pady=4)
            ctk.CTkLabel(section, text=title, text_color=color,
                         font=ctk.CTkFont("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=(7, 1))
            ctk.CTkLabel(section, text=data[key], text_color=TEXT, wraplength=540,
                         justify="left", anchor="w", font=ctk.CTkFont("Segoe UI", 11)).pack(fill="x", padx=12, pady=(0, 8))
        ctk.CTkLabel(
            self.card, text="REGLA GLOBAL · " + GLOBAL_ROLE_NOTE, text_color=MUTED,
            wraplength=550, justify="left", anchor="w", font=ctk.CTkFont("Segoe UI", 10, "bold"),
        ).pack(fill="x", padx=22, pady=(8, 9))
        if on_open_moves is not None:
            ctk.CTkButton(
                self.card,
                text="CONSULTAR MOVIMIENTOS DEL ROL",
                command=lambda: (self.close(), on_open_moves()),
                height=36,
                fg_color="transparent",
                hover_color="#303030",
                border_width=1,
                border_color=GOLD,
                text_color=GOLD,
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
            ).pack(fill="x", padx=22, pady=(0, 14))
        self._escape_binding = master.winfo_toplevel().bind("<Escape>", lambda _event: self.close(), add="+")

    def close(self) -> str:
        try:
            if self._escape_binding:
                self.master.winfo_toplevel().unbind("<Escape>", self._escape_binding)
        except Exception:
            pass
        try:
            self.scrim.destroy()
        except Exception:
            pass
        self.on_close()
        return "break"
