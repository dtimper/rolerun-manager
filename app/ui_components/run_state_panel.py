from __future__ import annotations

from collections.abc import Callable

import customtkinter as ctk


class IntegratedRunStatePanel:
    """Panel de Estado de la Run contenido por la ventana principal."""

    def __init__(
        self,
        master,
        *,
        snapshot: dict,
        on_close: Callable[[], None],
        on_adjust_counter: Callable[[str, int], None],
        on_open_floating: Callable[[], None],
    ) -> None:
        self.master = master
        self._on_close = on_close
        self._on_adjust_counter = on_adjust_counter
        self._on_open_floating = on_open_floating
        self._escape_binding = None

        self.scrim = ctk.CTkFrame(master, fg_color="#080808", corner_radius=0)
        self.scrim.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.scrim.lift()
        self.scrim.bind("<Button-1>", self._close_from_scrim, add="+")

        self.panel = ctk.CTkFrame(
            self.scrim,
            width=470,
            corner_radius=18,
            fg_color="#151515",
            border_width=2,
            border_color="#C9A45F",
        )
        self.panel.place(relx=1.0, x=-20, rely=0.02, relheight=0.96, anchor="ne")
        self.panel.pack_propagate(False)
        self.panel.bind("<Button-1>", lambda _event: "break", add="+")

        header = ctk.CTkFrame(self.panel, fg_color="transparent")
        header.pack(fill="x", padx=22, pady=(20, 12))
        ctk.CTkLabel(
            header,
            text="ESTADO DE LA RUN",
            text_color="#C9A45F",
            font=ctk.CTkFont("Segoe UI", 22, "bold"),
        ).pack(side="left")
        ctk.CTkButton(
            header,
            text="×",
            command=self.close,
            width=38,
            height=34,
            fg_color="transparent",
            hover_color="#2B2B2B",
            text_color="#F4F4F4",
            font=ctk.CTkFont("Segoe UI", 20, "bold"),
        ).pack(side="right")

        ctk.CTkLabel(
            self.panel,
            text=str(snapshot.get("name") or "Run activa"),
            text_color="#F4F4F4",
            anchor="w",
            font=ctk.CTkFont("Segoe UI", 20, "bold"),
        ).pack(fill="x", padx=22)
        ctk.CTkLabel(
            self.panel,
            text=str(snapshot.get("game") or "Juego no disponible"),
            text_color="#A7A7A7",
            anchor="w",
            font=ctk.CTkFont("Segoe UI", 13),
        ).pack(fill="x", padx=22, pady=(2, 14))

        counters = ctk.CTkFrame(self.panel, fg_color="transparent")
        counters.pack(fill="x", padx=18)
        counters.grid_columnconfigure((0, 1), weight=1)
        definitions = (
            ("vidas", "VIDAS"),
            ("pociones", "CURACIONES"),
            ("medallas", str(snapshot.get("progress_label") or "PROGRESO")),
            ("drafteos", "DRAFTEOS"),
        )
        values = dict(snapshot.get("counters") or {})
        automatic = set(snapshot.get("automatic_counters") or ())
        for index, (key, label) in enumerate(definitions):
            card = ctk.CTkFrame(
                counters,
                fg_color="#202020",
                corner_radius=13,
                border_width=1,
                border_color="#363636",
            )
            card.grid(row=index // 2, column=index % 2, sticky="nsew", padx=4, pady=4)
            ctk.CTkLabel(
                card,
                text=label,
                text_color="#A7A7A7",
                font=ctk.CTkFont("Segoe UI", 12, "bold"),
            ).pack(pady=(11, 0))
            ctk.CTkLabel(
                card,
                text=str(int(values.get(key, 0))),
                text_color="#F4F4F4",
                font=ctk.CTkFont("Segoe UI", 27, "bold"),
            ).pack(pady=(1, 3))
            controls = ctk.CTkFrame(card, fg_color="transparent")
            controls.pack(pady=(0, 10))
            if key in automatic:
                ctk.CTkLabel(
                    controls,
                    text="AUTOMÁTICO",
                    text_color="#C9A45F",
                    font=ctk.CTkFont("Segoe UI", 11, "bold"),
                ).pack(pady=6)
            else:
                for delta, symbol in ((-1, "−"), (1, "+")):
                    ctk.CTkButton(
                        controls,
                        text=symbol,
                        command=lambda name=key, amount=delta: self._adjust(name, amount),
                        width=38,
                        height=32,
                        fg_color="#2B2B2B" if delta < 0 else "#C9A45F",
                        hover_color="#3A3A3A" if delta < 0 else "#D7B972",
                        text_color="#F4F4F4" if delta < 0 else "#111111",
                        font=ctk.CTkFont("Segoe UI", 16, "bold"),
                    ).pack(side="left", padx=3)

        status = ctk.CTkFrame(
            self.panel,
            fg_color="#111111",
            corner_radius=13,
            border_width=1,
            border_color="#343434",
        )
        status.pack(fill="x", padx=22, pady=(16, 10))
        ctk.CTkLabel(
            status,
            text="CONEXIÓN Y SINCRONIZACIÓN",
            text_color="#C9A45F",
            anchor="w",
            font=ctk.CTkFont("Segoe UI", 12, "bold"),
        ).pack(fill="x", padx=14, pady=(12, 3))
        ctk.CTkLabel(
            status,
            text=str(snapshot.get("sync_status") or "Sin información"),
            text_color="#F4F4F4",
            anchor="w",
            justify="left",
            wraplength=390,
            font=ctk.CTkFont("Segoe UI", 13),
        ).pack(fill="x", padx=14, pady=(0, 8))
        pending = int(snapshot.get("pending_changes") or 0)
        faints = int(snapshot.get("pending_faints") or 0)
        ctk.CTkLabel(
            status,
            text=f"{pending} cambio(s) pendiente(s) · {faints} baja(s) pendiente(s)",
            text_color="#9D83E6" if pending or faints else "#55C985",
            anchor="w",
            font=ctk.CTkFont("Segoe UI", 12, "bold"),
        ).pack(fill="x", padx=14, pady=(0, 12))

        ctk.CTkButton(
            self.panel,
            text="ABRIR BARRA FLOTANTE",
            command=self._open_floating,
            height=42,
            fg_color="#C9A45F",
            hover_color="#D7B972",
            text_color="#111111",
            font=ctk.CTkFont("Segoe UI", 12, "bold"),
        ).pack(fill="x", padx=22, pady=(8, 20))

        self._escape_binding = master.bind("<Escape>", self.close, add="+")
        self.panel.focus_set()

    def _adjust(self, counter: str, delta: int) -> None:
        self._on_adjust_counter(counter, delta)

    def _open_floating(self) -> None:
        self.close()
        self._on_open_floating()

    def _close_from_scrim(self, event=None):
        if event is None or event.widget is self.scrim:
            self.close()
            return "break"
        return None

    def close(self, _event=None):
        try:
            if self._escape_binding:
                self.master.unbind("<Escape>", self._escape_binding)
        except Exception:
            pass
        try:
            self.scrim.destroy()
        finally:
            self._on_close()
        return "break"
