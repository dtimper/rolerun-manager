from __future__ import annotations

import re
from collections.abc import Callable

import customtkinter as ctk

from .window_focus import guard_topmost_on_focus_loss, hide_from_taskbar_and_alttab, release_focus_guard


class TransparentWindowSurface(ctk.CTkFrame):
    """Como ``IntegratedWindowSurface``, pero oscurece el fondo sin ocultarlo.

    Pedido del usuario 31-08-2026 para el editor de rol: Equipo y PC deben
    seguir viéndose detrás, atenuados, no tapados por un rectángulo opaco.

    Windows aplica la transparencia a la ventana entera, no a un widget suelto
    dentro de ella — por eso, a diferencia de ``IntegratedWindowSurface`` (un
    ``CTkFrame`` de velo dentro del MISMO root), aquí el velo y el contenido
    son dos ``CTkToplevel`` independientes: el velo lleva alfa, el contenido
    no. Mismo patrón ya validado en ``IntegratedRoleInfoPopover``.

    Conserva el mismo subconjunto de API de compatibilidad que
    ``IntegratedWindowSurface`` usa el editor de rol — no más, no menos.
    """

    def __init__(self, master, *args, **kwargs) -> None:
        self._host = master
        master.update_idletasks()
        screen_w = max(1, int(master.winfo_width()))
        screen_h = max(1, int(master.winfo_height()))
        root_x = int(master.winfo_rootx())
        root_y = int(master.winfo_rooty())

        self._scrim = ctk.CTkToplevel(master)
        self._scrim.overrideredirect(True)
        self._scrim.attributes("-topmost", True)
        self._scrim.attributes("-alpha", 0.55)
        self._scrim.configure(fg_color="#000000")
        self._scrim.geometry(f"{screen_w}x{screen_h}+{root_x}+{root_y}")
        # Cerrar en el <Button-1> (al PULSAR) rompe el grab implícito de Tk a
        # mitad del gesto de clic y deja escapar el <ButtonRelease-1> a lo que
        # haya debajo (mismo hallazgo que en IntegratedRoleInfoPopover).
        self._scrim.bind("<ButtonRelease-1>", lambda _event: self._request_close(), add="+")

        self._window = ctk.CTkToplevel(master)
        self._window.overrideredirect(True)
        self._window.attributes("-topmost", True)
        # Pedido del usuario 02-09-2026: cambiar de aplicación con este editor
        # abierto dejaba el velo y el diálogo por delante de la app nueva. El
        # ancla es la ventana PRINCIPAL, no `self._window`: ver el porqué en
        # `guard_topmost_on_focus_loss`.
        self._focus_guard = guard_topmost_on_focus_loss(
            master.winfo_toplevel(), self._scrim, self._window,
        )
        # Mismo día, segundo hallazgo: el velo y el diálogo, al ser dos
        # `CTkToplevel` sin dueño declarado, contaban como dos ventanas de
        # RoleRun en Alt+Tab.
        hide_from_taskbar_and_alttab(self._scrim, self._window)

        self._requested_width = 760
        self._requested_height = 610
        self._minimum_width = 420
        self._minimum_height = 320
        self._close_callback: Callable[[], object] = self.destroy
        self._surface_title = ""
        self._withdrawn = False

        super().__init__(
            self._window,
            *args,
            fg_color="#111111",
            corner_radius=16,
            border_width=1,
            border_color="#3A3A3A",
            **kwargs,
        )
        self.pack(fill="both", expand=True)
        self.pack_propagate(False)
        self.grid_propagate(False)

        self._place_surface()
        root = self._host.winfo_toplevel()
        self._escape_binding = root.bind(
            "<Escape>", lambda _event: self._request_close(), add="+",
        )
        # Hallazgo del usuario 31-08-2026: sin esto, el foco de teclado se
        # quedaba en lo que estuviera seleccionado detrás (una tarjeta del
        # equipo, la flecha del lateral…) y, al cerrar este diálogo, la
        # página de atrás terminaba pintando DOS cosas como seleccionadas a
        # la vez. `IntegratedWindowSurface` ya hacía esto mismo — se quedó
        # fuera al crear esta clase nueva.
        self.after(20, self.focus_force)

    def _place_surface(self) -> None:
        if self._withdrawn:
            return
        try:
            host_width = max(1, int(self._host.winfo_width()))
            host_height = max(1, int(self._host.winfo_height()))
            root_x = int(self._host.winfo_rootx())
            root_y = int(self._host.winfo_rooty())
        except Exception:
            host_width, host_height = self._requested_width + 40, self._requested_height + 40
            root_x, root_y = 0, 0
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
        x = root_x + (host_width - width) // 2
        y = root_y + (host_height - height) // 2
        try:
            self._window.geometry(f"{int(width)}x{int(height)}+{int(x)}+{int(y)}")
            self._window.lift()
        except Exception:
            pass

    def _request_close(self) -> str:
        callback = self._close_callback
        callback()
        return "break"

    # API de compatibilidad con IntegratedWindowSurface / los Toplevel que sustituye.
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
        for window in (self._scrim, self._window):
            try:
                window.withdraw()
            except Exception:
                pass

    def deiconify(self) -> None:
        self._withdrawn = False
        for window in (self._scrim, self._window):
            try:
                window.deiconify()
            except Exception:
                pass
        self._place_surface()

    def state(self) -> str:
        return "withdrawn" if self._withdrawn else "normal"

    def destroy(self) -> None:
        try:
            root = self._host.winfo_toplevel()
            if self._escape_binding:
                root.unbind("<Escape>", self._escape_binding)
        except Exception:
            pass
        release_focus_guard(getattr(self, "_focus_guard", None))
        try:
            super().destroy()
        finally:
            for window in (self._window, self._scrim):
                try:
                    if window.winfo_exists():
                        window.destroy()
                except Exception:
                    pass
