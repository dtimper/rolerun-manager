from __future__ import annotations

from collections.abc import Callable

import customtkinter as ctk

from app.config import DANGER, GOLD, MUTED, SUCCESS, TEXT
from app.role_content import GLOBAL_ROLE_NOTE, ROLE_GUIDE

from .window_focus import guard_topmost_on_focus_loss, hide_from_taskbar_and_alttab, release_focus_guard


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
        master.update_idletasks()
        screen_w = max(1, int(master.winfo_width()))
        screen_h = max(1, int(master.winfo_height()))
        root_x = int(master.winfo_rootx())
        root_y = int(master.winfo_rooty())

        # Antes esto era un CTkFrame cubriendo `master` con `place()`. Cerrarlo
        # —destruirlo— obliga a Tk a repintar TODO lo que queda al
        # descubierto: medido sobre Equipo y PC de verdad, ~195 ms de bloqueo
        # visible (31 casillas del PC, 6 tarjetas). Una ventana propia la
        # compone Windows por DWM: la principal nunca deja de estar pintada
        # debajo, así que cerrar no obliga a repintar nada de ella. Medido:
        # ~2 ms. Mismo patrón que ya usan el fantasma de arrastre y la barra
        # flotante en este mismo programa.
        self.scrim = ctk.CTkToplevel(master)
        self.scrim.overrideredirect(True)
        self.scrim.attributes("-topmost", True)
        # Pedido del usuario 31-08-2026: Equipo y PC oscurecidos, no ocultos.
        # El scrim y la ficha son DOS ventanas separadas a propósito — un solo
        # HWND con alfa habría atenuado la ficha igual que el fondo. La alfa
        # solo se aplica aquí, nunca en `self.card_window`.
        self.scrim.attributes("-alpha", 0.55)
        self.scrim.configure(fg_color="#000000")
        self.scrim.geometry(f"{screen_w}x{screen_h}+{root_x}+{root_y}")
        # Cerrar en el <Button-1> (al PULSAR) rompe el grab implícito de Tk a
        # mitad del gesto de clic: el <ButtonRelease-1> que ya venía en camino
        # se entrega a lo que haya debajo. Cerrar en el SUELTA lo evita.
        self.scrim.bind("<ButtonRelease-1>", lambda _event: self.close(), add="+")

        # Pedido del usuario 31-08-2026: letra y ventana MUCHO más grandes
        # para la cantidad de pantalla disponible. Proporcional al tamaño real
        # de `master` (no un píxel fijo) para que siga viéndose bien tanto
        # maximizado como en una ventana más pequeña.
        card_w = max(760, min(1360, int(screen_w * 0.66)))
        card_h = max(620, min(980, int(screen_h * 0.80)))
        card_x = root_x + (screen_w - card_w) // 2
        card_y = root_y + (screen_h - card_h) // 2
        self.card_window = ctk.CTkToplevel(master)
        self.card_window.overrideredirect(True)
        self.card_window.attributes("-topmost", True)
        self.card_window.geometry(f"{card_w}x{card_h}+{card_x}+{card_y}")
        # Pedido del usuario 02-09-2026 (visto en el editor de rol, mismo
        # patrón aquí): sin esto, cambiar de aplicación deja esta ficha por
        # delante de la app nueva, porque `-topmost` es global a Windows. El
        # ancla es la ventana PRINCIPAL, no `self.card_window`: ver el porqué
        # en `guard_topmost_on_focus_loss`.
        self._focus_guard = guard_topmost_on_focus_loss(
            master.winfo_toplevel(), self.scrim, self.card_window,
        )
        hide_from_taskbar_and_alttab(self.scrim, self.card_window)

        self.card = ctk.CTkFrame(
            self.card_window, fg_color="#171717",
            corner_radius=18, border_width=2, border_color=GOLD,
        )
        self.card.pack(fill="both", expand=True)
        self.card.pack_propagate(False)

        # Estimación de partida, corregida en cuanto Tk asienta el layout real
        # (ver `_wrap_to_own_width`). Un margen fijo calculado a mano se salía
        # de la ficha en algunos textos más largos (hallazgo del usuario
        # 31-08-2026, "REGLA GLOBAL" cortada) — atarlo al ancho real que Tk le
        # da a CADA etiqueta no depende de adivinar el margen correcto.
        wrap_wide = card_w - 90
        wrap_section = card_w - 112
        data = ROLE_GUIDE.get(role, ROLE_GUIDE["Líbero"])
        header = ctk.CTkFrame(self.card, fg_color="transparent")
        header.pack(fill="x", padx=28, pady=(24, 12))
        ctk.CTkLabel(header, text=role.upper(), text_color=GOLD,
                     font=ctk.CTkFont("Segoe UI", 34, "bold")).pack(side="left")
        close_button = ctk.CTkButton(
            header, text="×", width=48, height=46,
            fg_color="transparent", hover_color="#303030", text_color=TEXT,
            font=ctk.CTkFont("Segoe UI", 24, "bold"),
        )
        close_button.pack(side="right")
        # Sin `command=`: CTkButton lo dispara en el <Button-1>, con el mismo
        # problema que el scrim de arriba.
        close_button.bind("<ButtonRelease-1>", lambda _event: self.close(), add="+")

        summary_label = ctk.CTkLabel(
            self.card, text=data["summary"], text_color=TEXT, wraplength=wrap_wide,
            justify="left", anchor="w", font=ctk.CTkFont("Segoe UI", 19, "bold"),
        )
        summary_label.pack(fill="x", padx=32, pady=(0, 16))
        self._wrap_to_own_width(summary_label)
        for title, key, color, background in (
            ("✓  PUEDE USAR", "allowed", SUCCESS, "#172219"),
            ("×  LIMITACIONES", "limits", DANGER, "#251919"),
            ("PREPARACIÓN DEL EQUIPO", "preparation", GOLD, "#211D13"),
        ):
            section = ctk.CTkFrame(self.card, fg_color=background, corner_radius=10)
            section.pack(fill="x", padx=32, pady=6)
            ctk.CTkLabel(section, text=title, text_color=color,
                         font=ctk.CTkFont("Segoe UI", 15, "bold")).pack(anchor="w", padx=16, pady=(11, 3))
            body_label = ctk.CTkLabel(
                section, text=data[key], text_color=TEXT, wraplength=wrap_section,
                justify="left", anchor="w", font=ctk.CTkFont("Segoe UI", 16),
            )
            body_label.pack(fill="x", padx=16, pady=(0, 13))
            self._wrap_to_own_width(body_label)
        global_note_label = ctk.CTkLabel(
            self.card, text="REGLA GLOBAL · " + GLOBAL_ROLE_NOTE, text_color=MUTED,
            wraplength=wrap_wide, justify="left", anchor="w", font=ctk.CTkFont("Segoe UI", 14, "bold"),
        )
        global_note_label.pack(fill="x", padx=32, pady=(12, 14))
        self._wrap_to_own_width(global_note_label)
        if on_open_moves is not None:
            ctk.CTkButton(
                self.card,
                text="CONSULTAR MOVIMIENTOS DEL ROL",
                command=lambda: (self.close(), on_open_moves()),
                height=50,
                fg_color="transparent",
                hover_color="#303030",
                border_width=1,
                border_color=GOLD,
                text_color=GOLD,
                font=ctk.CTkFont("Segoe UI", 16, "bold"),
            ).pack(fill="x", padx=32, pady=(0, 22))
        self._escape_binding = master.winfo_toplevel().bind("<Escape>", lambda _event: self.close(), add="+")

    @staticmethod
    def _wrap_to_own_width(label: ctk.CTkLabel) -> None:
        """El ``wraplength`` sigue al ancho real que Tk le da a la etiqueta.

        Primer intento (31-08-2026, insuficiente): atar el `wraplength` al
        ancho de `<Configure>` seguía cortando el texto. La causa real no era
        el margen: CustomTkinter reescala `wraplength` con su propio factor de
        escala de pantalla (`_apply_widget_scaling`, en `ctk_label.py`) antes
        de dárselo al Label de Tk real, y `.cget("wraplength")` devuelve el
        valor SIN escalar que se le pasó — nunca el aplicado de verdad. Pasarle
        el ancho físico de `event.width` tal cual hacía que CTk lo multiplicara
        POR SEGUNDA VEZ: con un 125% de escala de Windows, un ancho físico de
        700 px se convertía en un `wraplength` interno de 875 px, más ancho que
        la propia ficha. `_reverse_widget_scaling` es la misma conversión que
        usa el propio CustomTkinter en su manejador de `<Configure>`
        (`ctk_base_class.py`) para deshacer exactamente este escalado.

        Segundo intento (31-08-2026, insuficiente): comparar solo contra
        `wraplength` seguía temblando en todos los textos más largos que el
        de Líbero. Ligar un margen de tolerancia al ancho tampoco bastó — la
        causa real no era ruido de un par de píxeles, sino las 5 etiquetas de
        la ficha compitiendo por una altura fija (``card_h``,
        `pack_propagate(False)`) que el texto de un rol largo no siempre
        cabe: al no entrar, Tk reparte el sobrante entre ellas en cada
        `<Configure>`, cada reparto cambia el ancho real de alguna, nuestro
        propio `configure(wraplength=...)` dispara el siguiente `<Configure>`
        — medido en vivo con ROLE_GUIDE["Prisma"] (el texto más largo): más
        de 500 disparos sin converger nunca, alternando entre ~11 anchos.
        Meterlas en un `CTkScrollableFrame` tampoco lo paró: su barra de
        desplazamiento aparece y desaparece según si el contenido cabe, y
        ESE cambio de ancho realimenta el mismo ciclo.

        La ventana de esta ficha es ``overrideredirect`` y de geometría fija
        — nunca la redimensiona el usuario tras crearse — así que no hace
        falta reaccionar para siempre: basta con corregir el par de pasadas
        iniciales en las que Tk todavía está asentando el layout y dejar de
        escuchar. Un tope duro de aplicaciones reales garantiza que termine
        pase lo que pase dentro de Tk, sin depender de que el reparto de
        espacio llegue a un equilibrio que a veces no existe.
        """
        aplicaciones_restantes = [4]

        def ajustar(event) -> None:
            if aplicaciones_restantes[0] <= 0:
                label.unbind("<Configure>", binding[0])
                return
            fisico = max(1, int(event.width) - 4)
            logico = int(label._reverse_widget_scaling(fisico))
            if int(label.cget("wraplength") or 0) != logico:
                aplicaciones_restantes[0] -= 1
                label.configure(wraplength=logico)

        binding = [label.bind("<Configure>", ajustar, add="+")]

    def close(self) -> str:
        try:
            if self._escape_binding:
                self.master.winfo_toplevel().unbind("<Escape>", self._escape_binding)
        except Exception:
            pass
        release_focus_guard(getattr(self, "_focus_guard", None))
        # La ficha y el scrim son dos ventanas independientes: cerrar una no
        # destruye la otra sola.
        for window in (self.card_window, self.scrim):
            try:
                window.destroy()
            except Exception:
                pass
        self.on_close()
        return "break"
