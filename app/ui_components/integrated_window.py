from __future__ import annotations

import re
from collections.abc import Callable

import customtkinter as ctk


class IntegratedWindowSurface(ctk.CTkFrame):
    """Compatibilidad visual para antiguos diálogos dentro del mismo root.

    Conserva la API mínima que usaban los ``CTkToplevel`` históricos mientras
    los aloja sobre un scrim interno. No crea una ventana del sistema, no aparece
    en la barra de tareas y no altera ningún callback funcional del diálogo.
    """

    def __init__(self, master, *args, **kwargs) -> None:
        self._host = master
        self._scrim = ctk.CTkFrame(master, fg_color="#080808", corner_radius=0)
        self._scrim.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._scrim.lift()
        super().__init__(
            self._scrim,
            *args,
            width=760,
            height=610,
            fg_color="#111111",
            corner_radius=16,
            border_width=1,
            border_color="#3A3A3A",
            **kwargs,
        )
        self.pack_propagate(False)
        self.grid_propagate(False)
        self._requested_width = 760
        self._requested_height = 610
        self._minimum_width = 420
        self._minimum_height = 320
        self._close_callback: Callable[[], object] = self.destroy
        self._surface_title = ""
        self._withdrawn = False
        self._place_surface()
        self._scrim.bind("<Button-1>", self._on_scrim_click, add="+")
        root = self.winfo_toplevel()
        self._escape_binding = root.bind(
            "<Escape>", lambda _event: self._request_close(), add="+",
        )
        self.after(0, self._place_surface)
        self.after(20, self.focus_force)

    def _place_surface(self) -> None:
        if self._withdrawn:
            return
        try:
            host_width = max(1, int(self._host.winfo_width()))
            host_height = max(1, int(self._host.winfo_height()))
        except Exception:
            host_width, host_height = self._requested_width + 40, self._requested_height + 40
        if host_width <= 1:
            host_width = self._requested_width + 40
        if host_height <= 1:
            host_height = self._requested_height + 40
        width = max(
            min(self._minimum_width, max(1, host_width - 24)),
            min(self._requested_width, max(1, host_width - 24)),
        )
        height = max(
            min(self._minimum_height, max(1, host_height - 24)),
            min(self._requested_height, max(1, host_height - 24)),
        )
        self.configure(width=width, height=height)
        self.place(relx=0.5, rely=0.5, anchor="center")
        self.lift()

    def _on_scrim_click(self, event) -> str | None:
        if getattr(event, "widget", None) is self._scrim:
            self._request_close()
            return "break"
        return None

    def _request_close(self) -> str:
        callback = self._close_callback
        callback()
        return "break"

    # API de compatibilidad con los Toplevel sustituidos.
    def title(self, value: str | None = None) -> str:
        if value is not None:
            self._surface_title = str(value)
        return self._surface_title

    def geometry(self, value: str | None = None) -> str:
        if value:
            match = re.match(r"\s*(\d+)x(\d+)", str(value))
            if match:
                self._requested_width = int(match.group(1))
                self._requested_height = int(match.group(2))
                self._place_surface()
        return f"{self._requested_width}x{self._requested_height}"

    def minsize(self, width: int, height: int) -> None:
        self._minimum_width = max(1, int(width))
        self._minimum_height = max(1, int(height))
        self._place_surface()

    def resizable(self, *_args) -> None:
        return None

    def transient(self, *_args) -> None:
        return None

    def grab_set(self) -> None:
        return None

    def grab_release(self) -> None:
        return None

    def protocol(self, name: str, callback: Callable[[], object]) -> None:
        if str(name) == "WM_DELETE_WINDOW":
            self._close_callback = callback

    def iconbitmap(self, *_args, **_kwargs) -> None:
        return None

    def withdraw(self) -> None:
        self._withdrawn = True
        self._scrim.place_forget()

    def deiconify(self) -> None:
        self._withdrawn = False
        self._scrim.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._scrim.lift()
        self._place_surface()

    def state(self) -> str:
        return "withdrawn" if self._withdrawn else "normal"

    def destroy(self) -> None:
        try:
            root = self.winfo_toplevel()
            if self._escape_binding:
                root.unbind("<Escape>", self._escape_binding)
        except Exception:
            pass
        try:
            super().destroy()
        finally:
            try:
                if self._scrim.winfo_exists():
                    self._scrim.destroy()
            except Exception:
                pass
