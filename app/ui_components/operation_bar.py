from __future__ import annotations

from collections.abc import Callable

import customtkinter as ctk

from app.ui_state.operation_status import OperationMessage


_KIND_VISUALS = {
    "neutral": ("#C9A45F", "#15130F", "◆"),
    "prepared": ("#C9A45F", "#211B11", "◆"),
    "applying": ("#D7B972", "#211B11", "◷"),
    "verifying": ("#73A9FF", "#111C2A", "◌"),
    "confirmed": ("#55C985", "#102018", "✓"),
    "failed": ("#E76868", "#281414", "!"),
    "restored": ("#9D83E6", "#1B1728", "↺"),
    "warning": ("#D7B972", "#211B11", "⚠"),
    "intervention": ("#E76868", "#281414", "⚠"),
    "disconnected": ("#E76868", "#281414", "○"),
    "pending": ("#9D83E6", "#1B1728", "…"),
}


class OperationStatusBar(ctk.CTkFrame):
    """Barra persistente que refleja hechos, nunca una proyección como éxito."""

    def __init__(
        self,
        master,
        *,
        on_action: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(
            master,
            height=78,
            corner_radius=14,
            fg_color="#15130F",
            border_width=1,
            border_color="#C9A45F",
        )
        self.grid_propagate(False)
        self.grid_columnconfigure(1, weight=1)
        self._on_action = on_action
        self._action_buttons: list[ctk.CTkButton] = []
        self._typing_after_id = None
        self._typing_revision = 0

        self._mark = ctk.CTkLabel(
            self,
            text="◆",
            width=42,
            text_color="#C9A45F",
            font=ctk.CTkFont("Segoe UI Symbol", 21, "bold"),
        )
        self._mark.grid(row=0, column=0, rowspan=2, padx=(17, 10), pady=12)
        self._title = ctk.CTkLabel(
            self,
            text="ROLERUN PREPARADO",
            text_color="#C9A45F",
            anchor="w",
            font=ctk.CTkFont("Segoe UI", 15, "bold"),
        )
        self._title.grid(row=0, column=1, sticky="sw", pady=(11, 0))
        self._detail = ctk.CTkLabel(
            self,
            text="Selecciona una acción para continuar.",
            text_color="#F4F4F4",
            anchor="w",
            justify="left",
            wraplength=760,
            font=ctk.CTkFont("Segoe UI", 15),
        )
        self._detail.grid(row=1, column=1, sticky="nw", pady=(0, 11))
        # CTkFrame solicita 200 px de alto por defecto. Sin una altura acotada
        # desplazaría las dos filas de texto fuera de esta barra de 78 px.
        self._actions = ctk.CTkFrame(self, width=1, height=40, fg_color="transparent")
        self._actions.grid(row=0, column=2, rowspan=2, sticky="e", padx=14, pady=10)

    def show_message(self, message: OperationMessage) -> None:
        self._cancel_typing()
        accent, surface, symbol = _KIND_VISUALS.get(message.kind, _KIND_VISUALS["neutral"])
        self.configure(fg_color=surface, border_color=accent, border_width=2 if message.stays_visible else 1)
        self._mark.configure(text=symbol, text_color=accent)
        self._title.configure(text=message.title, text_color=accent)
        detail = message.detail or " "
        self._detail.configure(text="")
        self._typing_revision += 1
        revision = self._typing_revision

        def reveal(index: int = 1) -> None:
            if revision != self._typing_revision:
                return
            self._detail.configure(text=detail[:index])
            if index < len(detail):
                self._typing_after_id = self.after(14, lambda: reveal(index + 1))
            else:
                self._typing_after_id = None

        reveal()
        for button in self._action_buttons:
            try:
                button.destroy()
            except Exception:
                pass
        self._action_buttons.clear()
        for action in message.actions[:3]:
            button = ctk.CTkButton(
                self._actions,
                text=action.upper(),
                command=lambda value=action: self._dispatch(value),
                height=34,
                fg_color="transparent",
                hover_color="#303030",
                border_width=1,
                border_color=accent,
                text_color=accent,
                font=ctk.CTkFont("Segoe UI", 12, "bold"),
            )
            button.pack(side="left", padx=4)
            self._action_buttons.append(button)

    def _cancel_typing(self) -> None:
        self._typing_revision += 1
        if self._typing_after_id is not None:
            try:
                self.after_cancel(self._typing_after_id)
            except Exception:
                pass
            self._typing_after_id = None

    def destroy(self) -> None:
        self._cancel_typing()
        super().destroy()

    def _dispatch(self, action: str) -> None:
        if self._on_action is not None:
            self._on_action(action)
