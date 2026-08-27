from __future__ import annotations

import customtkinter as ctk


class CenteredLoadingIndicator(ctk.CTkFrame):
    """Indicador no modal para trabajos que continúan fuera del hilo de Tk."""

    def __init__(self, master, message: str) -> None:
        super().__init__(
            master,
            width=310,
            height=108,
            fg_color="#171717",
            corner_radius=16,
            border_width=2,
            border_color="#C9A45F",
        )
        self.pack_propagate(False)
        self.grid_propagate(False)
        self._label = ctk.CTkLabel(
            self,
            text=message,
            text_color="#F4F4F4",
            font=ctk.CTkFont("Segoe UI", 13, "bold"),
        )
        self._label.pack(fill="x", padx=22, pady=(19, 10))
        self._progress = ctk.CTkProgressBar(
            self,
            width=230,
            height=8,
            mode="indeterminate",
            fg_color="#2B2B2B",
            progress_color="#C9A45F",
        )
        self._progress.pack(padx=32, pady=(0, 20))
        self._progress.start()
        self.place(relx=0.5, rely=0.52, anchor="center")
        self.lift()

    def show_message(self, message: str) -> None:
        self._label.configure(text=str(message))
        self.lift()

    def destroy(self) -> None:
        try:
            self._progress.stop()
        except Exception:
            pass
        super().destroy()
