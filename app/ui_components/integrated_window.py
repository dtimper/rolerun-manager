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
        # El host (RoleRunManager) usa esta cuenta para aplazar cualquier
        # repintado de fondo mientras haya al menos un diálogo de estos
        # abierto -ver `_smooth_render_page`-, en vez de dejar que ambos
        # compitan por la misma superficie. `getattr`/`setattr` sueltos: este
        # componente no depende de que el host declare el atributo de antemano.
        try:
            setattr(master, "_integrated_modal_count", int(getattr(master, "_integrated_modal_count", 0)) + 1)
        except Exception:
            pass
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
        # Reportado por el usuario 03-09-2026: al cambiar de rol hacia/desde
        # Líbero con este diálogo abierto, un repintado de fondo (el sondeo en
        # vivo puede reconstruir Equipo/PC en cualquier momento) crea widgets
        # nuevos que, en Tk, se apilan por encima de cualquier hermano ya
        # existente -incluido este velo- salvo que alguien vuelva a levantarlo.
        # Sin una ventana de sistema propia que lo proteja, ese repintado se
        # veía encima del diálogo. Mismo patrón que ya usa
        # `guard_topmost_on_focus_loss` para un problema equivalente con
        # ventanas reales: un sondeo ligero que se limita a re-levantar el
        # velo y el propio diálogo mientras siga vivo.
        self._keep_on_top_after_id = None
        self._modal_count_released = False
        self._schedule_keep_on_top()

    def _schedule_keep_on_top(self) -> None:
        try:
            self._keep_on_top_after_id = self.after(150, self._keep_on_top_tick)
        except Exception:
            self._keep_on_top_after_id = None

    def _keep_on_top_tick(self) -> None:
        self._keep_on_top_after_id = None
        if self._withdrawn:
            return
        try:
            if self._scrim.winfo_exists():
                self._scrim.lift()
            if self.winfo_exists():
                self.lift()
        except Exception:
            pass
        self._schedule_keep_on_top()

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
        if self._keep_on_top_after_id is None:
            self._schedule_keep_on_top()

    def state(self) -> str:
        return "withdrawn" if self._withdrawn else "normal"

    def destroy(self) -> None:
        if self._keep_on_top_after_id is not None:
            try:
                self.after_cancel(self._keep_on_top_after_id)
            except Exception:
                pass
            self._keep_on_top_after_id = None
        if not getattr(self, "_modal_count_released", False):
            self._modal_count_released = True
            try:
                host = self._host
                count = max(0, int(getattr(host, "_integrated_modal_count", 1)) - 1)
                setattr(host, "_integrated_modal_count", count)
                if count == 0:
                    resume = getattr(host, "_resume_deferred_render_after_modal", None)
                    if callable(resume):
                        resume()
            except Exception:
                pass
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
