from __future__ import annotations

from collections.abc import Callable
from typing import Any

import customtkinter as ctk
import tkinter as tk

from app.config import DANGER, GOLD, MUTED, PANEL, PANEL_ALT, SUCCESS, TEXT
from app.pc_browser import pokemon_matches_pc_query
from app.pokemon_stats import STAT_KEYS, STAT_LABELS
from app.ui_state.spatial_navigation import event_targets_text_input, keypress_sequences
from app.ui_state.team_pc_state import TeamPCSelectionState


SELECTED = "#73A9FF"
FOCUS = "#E9EEF7"
PREPARATION = "#D7B972"


def _move_issue_map(
    pokemon: Any,
    role: str,
    move_issues_for: Callable[[Any, str], list[dict[str, Any]]] | None,
    *,
    context: str = "team",
) -> dict[int, dict[str, Any]]:
    """Return the demonstrated RoleRun incompatibilities keyed by move slot.

    PC members do not have an active team role, so only the six team cards and
    their inspector may expose corrective actions.
    """
    if context != "team" or move_issues_for is None:
        return {}
    return {
        int(issue["move_slot"]): issue
        for issue in move_issues_for(pokemon, role)
        if 1 <= int(issue.get("move_slot", 0) or 0) <= 4
    }


def _support_damage_map(
    pokemon: Any,
    role: str,
    support_damage_for: Callable[[Any, str], tuple[int, list[dict[str, Any]]]] | None,
    *,
    context: str = "team",
) -> tuple[int, set[int]]:
    """Huecos que el Support puede elegir para quitar, y cuántos le sobran.

    El límite de dos ataques de daño es de conjunto, no de hueco: ninguno de
    ellos es ilegal por sí solo, así que se marcan en dorado —«elige»— y no en
    rojo. Solo tiene sentido en el equipo: un Pokémon del PC no tiene rol
    activo.
    """
    if context != "team" or support_damage_for is None:
        return 0, set()
    excess, candidates = support_damage_for(pokemon, role)
    if excess <= 0:
        return 0, set()
    return int(excess), {
        int(item["move_slot"]) for item in candidates
        if 1 <= int(item.get("move_slot", 0) or 0) <= 4
    }


def _available_body_height(master) -> int:
    canvas = getattr(master, "_parent_canvas", None)
    try:
        viewport = int(canvas.winfo_height() or 0) if canvas is not None else 0
    except Exception:
        viewport = 0
    if viewport >= 320:
        return max(460, viewport)
    direct = int(master.winfo_height() or 0)
    # Con la shell ya resuelta, el cuerpo es la única medida autoritativa.
    # Mezclarla con la altura completa de la ventana fabricaba una vista mayor
    # que su fila y reactivaba el scroll general a pantalla completa.
    if direct >= 320:
        return max(460, direct)
    top = master.winfo_toplevel()
    top_height = int(top.winfo_height() or 0)
    try:
        dimensions = str(top.geometry()).split("+", 1)[0]
        declared_height = int(dimensions.split("x", 1)[1])
    except (IndexError, TypeError, ValueError):
        declared_height = 720
    top_height = max(top_height, declared_height)
    return max(460, top_height - 330)


class UnifiedTeamPCView:
    """Vista de presentación Equipo | Caja PC | Ficha.

    Recibe objetos ya proyectados y callbacks del controlador. No lee saves,
    decide roles ni escribe memoria.
    """

    def __init__(
        self,
        master,
        *,
        team_slots: tuple[dict[str, Any], ...],
        pc_members: dict[int, Any],
        pc_box: int,
        pc_box_count: int,
        pc_slot_count: int,
        selection: TeamPCSelectionState,
        identity_for: Callable[[Any], str],
        role_for: Callable[[Any, str], tuple[str, str]],
        sprite_for: Callable[[Any, tuple[int, int]], Any],
        role_icon_for: Callable[[str, int], Any | None],
        pending_for: Callable[[Any, str], bool],
        move_issues_for: Callable[[Any, str], list[dict[str, Any]]] | None,
        support_damage_for: Callable[[Any, str], tuple[int, list[dict[str, Any]]]] | None = None,
        on_support_damage: Callable[[Any], None] | None = None,
        on_box_change: Callable[[int], tuple[int, dict[int, Any]]],
        on_search: Callable[[str], list[tuple[int, int, Any]]],
        on_action: Callable[[str, Any], None],
        on_role_info: Callable[[str], None],
        on_heal_party: Callable[[], None] | None = None,
        on_drop: Callable[[str, Any, str, dict[str, Any]], None] | None = None,
        can_drop: Callable[[str, Any, str, dict[str, Any]], bool] | None = None,
        on_select: Callable[[str, Any], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
        on_composed: Callable[[Any], None] | None = None,
        interaction_mode: str = "normal",
        mode_banner: dict[str, str] | None = None,
        excluded_boxes: set[int] | None = None,
        compact: bool = False,
        navigation_keys: dict[str, str] | None = None,
        base_stats_for: Callable[[Any], dict[str, int]] | None = None,
        on_left_edge: Callable[[], None] | None = None,
        on_edge_accept: Callable[[], bool] | None = None,
    ) -> None:
        self.master = master
        self.team_slots = team_slots
        self.pc_members = dict(pc_members)
        self.pc_box = int(pc_box)
        self.pc_box_count = max(1, int(pc_box_count))
        self.pc_slot_count = max(1, int(pc_slot_count))
        self.selection = selection
        self.identity_for = identity_for
        self.role_for = role_for
        self.sprite_for = sprite_for
        self.role_icon_for = role_icon_for
        self.base_stats_for = base_stats_for
        self.pending_for = pending_for
        self.move_issues_for = move_issues_for
        self.support_damage_for = support_damage_for
        self.on_support_damage = on_support_damage
        self.on_box_change = on_box_change
        self.on_search = on_search
        self.on_action = on_action
        self.on_role_info = on_role_info
        self.on_heal_party = on_heal_party
        self.on_drop = on_drop
        self.can_drop = can_drop
        self.on_select = on_select
        self.on_cancel = on_cancel
        self.on_composed = on_composed
        self.interaction_mode = str(interaction_mode or "normal")
        self.mode_banner = dict(mode_banner or {})
        self.excluded_boxes = {int(value) for value in (excluded_boxes or set())}
        self.compact = bool(compact)
        self.navigation_keys = dict(navigation_keys or {"accept": "z", "back": "x"})
        self.on_left_edge = on_left_edge
        self.on_edge_accept = on_edge_accept
        # Los bindings viven en el toplevel y pueden coexistir durante una
        # transición o debajo de un flujo modal. El controlador decide cuál es
        # la única vista autorizada a consumir navegación.
        self.navigation_guard: Callable[[], bool] | None = None
        self.navigation_intercept: Callable[[str], bool] | None = None
        self._external_navigation_focus = False
        self.images: list[Any] = []
        self.team_frames: dict[str, ctk.CTkFrame] = {}
        self.role_info_buttons: dict[str, ctk.CTkButton] = {}
        self.team_preparation: set[str] = set()
        self.pc_buttons: dict[int, ctk.CTkButton] = {}
        self.pc_occupied_slots: set[int] = set()
        self.drop_targets: list[tuple[Any, str, dict[str, Any]]] = []
        self._drag_origin: tuple[int, int] | None = None
        self._drag_source: tuple[str, Any] | None = None
        self._drag_started = False
        self._drag_ghost = None
        self._drag_target_widget: Any | None = None
        self._drag_source_widget: Any | None = None
        self._drag_capture_bindings: list[tuple[Any, str, str]] = []
        self._drag_box_hover_after_id: str | None = None
        self._drag_box_hover_direction: int | None = None
        self._drag_box_hover_consumed: int | None = None
        self._previous_box_button: Any | None = None
        self._next_box_button: Any | None = None
        self._suppress_click_once = False
        self._global_search = False
        self._viewport_canvas = None
        self._viewport_bind_id = None
        self._keyboard_bindings: list[tuple[str, str]] = []
        self._role_tooltip = None
        self._inspector_action_buttons: dict[str, ctk.CTkButton] = {}
        self._keyboard_inspector_action: tuple[str, Any] | None = None
        self.pc_columns = 3
        self._layout_passes_complete = 0
        self._composition_notified = False
        self._inspector_render_after_id: str | None = None
        # Evidencia semántica de lo que las tarjetas han materializado. No
        # basta con que el controlador haya entregado un modelo live: la
        # barrera inicial debe comprobar los valores que esta superficie llegó
        # realmente a convertir en widgets antes de exponerla.
        self._rendered_team_health: list[tuple[int, int, int]] = []
        # Referencias a la barra y la etiqueta de PS de cada miembro, para poder
        # actualizarlas sin reconstruir la página. Medido en Windows: una
        # reconstrucción completa cuesta 845 ms de hilo Tk.
        self._team_health_widgets: dict[str, dict[str, Any]] = {}

        identities = [
            self.identity_for(slot["pokemon"])
            for slot in team_slots if slot.get("pokemon") is not None
        ]
        self.selection.set_team(identities)
        self.selection.set_pc_box(self.pc_box, self.pc_members)

        # El cuerpo ya descuenta cabecera y barra de estado. Medirlo directamente
        # evita fabricar una vista más alta que el espacio real y, con ello, el
        # scroll general que antes ocultaba la sexta fila del PC en 16:9.
        available_height = _available_body_height(master)
        self.viewport_height = max(460, available_height - 6)
        self.frame = ctk.CTkFrame(
            master,
            height=self.viewport_height,
            fg_color="transparent",
            corner_radius=0,
        )
        self.frame.grid(row=0, column=0, sticky="nsew")
        self.frame.grid_propagate(False)
        # ``place`` hace que el ancho disponible mande sobre el tamaño ideal de
        # los controles. Con ``grid`` los treinta botones del PC imponían su
        # ancho solicitado y recortaban la ficha en la ventana mínima.
        widths = (0.42, 0.23, 0.35) if self.compact else (0.46, 0.20, 0.34)
        starts = (0.0, widths[0], widths[0] + widths[1])
        self._content_rely = 0.15 if self.mode_banner else 0.002
        self._content_relheight = 0.842 if self.mode_banner else 0.992
        if self.mode_banner:
            self._render_mode_banner()
        self.team_panel = self._panel(starts[0], widths[0])
        self.pc_panel = self._panel(starts[1], widths[1])
        self.inspector_panel = self._panel(starts[2], widths[2])
        self._render_team()
        self._render_pc_shell()
        self._render_pc_grid()
        self._render_inspector()
        self._apply_selection_styles()

        # El CTkScrollableFrame resuelve el alto de su canvas después de crear
        # sus hijos. Ajustamos entonces esta superficie al viewport final para
        # usar toda la pantalla sin fabricar overflow en el cuerpo general.
        for delay in (0, 80, 180):
            self.frame.after(delay, self._complete_layout_pass)
        self._bind_viewport_resize()
        self.frame.bind("<Destroy>", self._release_viewport_resize, add="+")
        self.frame.bind("<Destroy>", self._release_keyboard_navigation, add="+")
        self._bind_keyboard_navigation()

    def _fit_frame_to_viewport(self) -> None:
        canvas = getattr(self.master, "_parent_canvas", None)
        try:
            viewport = int(canvas.winfo_height() or 0) if canvas is not None else 0
            if viewport >= 460 and self.frame.winfo_exists():
                logical_height = int(self.frame._reverse_widget_scaling(viewport - 8))
                self.frame.configure(height=max(460, logical_height))
        except Exception:
            pass

    def _complete_layout_pass(self) -> None:
        self._fit_frame_to_viewport()
        try:
            self.frame.update_idletasks()
        except Exception:
            return
        self._layout_passes_complete += 1
        if (
            self._layout_passes_complete >= 3
            and not self._composition_notified
            and callable(self.on_composed)
        ):
            self._composition_notified = True
            self.on_composed(self)

    def is_fully_composed(self, expected_box_count: int) -> bool:
        """Declara la frontera visual final de la vista, no solo sus datos."""
        try:
            widgets = (
                self.frame, self.team_panel, self.pc_panel, self.inspector_panel,
            )
            return bool(
                self._layout_passes_complete >= 3
                and self.pc_box_count == int(expected_box_count)
                and len(self.pc_buttons) == self.pc_slot_count
                and all(widget.winfo_exists() and widget.winfo_ismapped() for widget in widgets)
                and all(widget.winfo_width() > 40 and widget.winfo_height() > 80 for widget in widgets)
            )
        except Exception:
            return False

    @property
    def rendered_team_health_signature(self) -> tuple[tuple[int, int], ...]:
        # Las tarjetas se presentan por rol, mientras el reader publica el
        # equipo por posición física. El slot original permite comparar la
        # misma identidad semántica sin confundir ambos órdenes.
        return tuple(
            (current_hp, max_hp)
            for _slot, current_hp, max_hp in sorted(self._rendered_team_health)
        )

    def _bind_viewport_resize(self) -> None:
        canvas = getattr(self.master, "_parent_canvas", None)
        if canvas is None:
            return
        try:
            self._viewport_canvas = canvas
            self._viewport_bind_id = canvas.bind(
                "<Configure>", lambda _event: self._fit_frame_to_viewport(), add="+",
            )
        except Exception:
            self._viewport_canvas = None
            self._viewport_bind_id = None

    def _release_viewport_resize(self, event=None) -> None:
        if event is not None and getattr(event, "widget", None) is not self.frame:
            return
        try:
            if self._viewport_canvas is not None and self._viewport_bind_id:
                self._viewport_canvas.unbind("<Configure>", self._viewport_bind_id)
        except Exception:
            pass
        self._viewport_canvas = None
        self._viewport_bind_id = None

    def suspend_interaction(self) -> None:
        """Desconecta eventos sin retirar la superficie usada como buffer."""
        self._release_keyboard_navigation()
        self._release_viewport_resize()
        self._hide_role_tooltip()

    def _bind_keyboard_navigation(self) -> None:
        top = self.frame.winfo_toplevel()
        callbacks = {
            "<KeyPress-Left>": lambda event: self._move_direction_key(event, "left"),
            "<KeyPress-Right>": lambda event: self._move_direction_key(event, "right"),
            "<KeyPress-Up>": lambda event: self._move_direction_key(event, "up"),
            "<KeyPress-Down>": lambda event: self._move_direction_key(event, "down"),
            "<Escape>": self._on_escape,
        }
        callbacks.update({sequence: self._accept_keyboard_selection for sequence in keypress_sequences(self.navigation_keys.get("accept", "z"))})
        callbacks.update({sequence: self._clear_keyboard_selection for sequence in keypress_sequences(self.navigation_keys.get("back", "x"))})
        for sequence, callback in callbacks.items():
            try:
                binding = top.bind(sequence, callback, add="+")
                if binding:
                    self._keyboard_bindings.append((sequence, binding))
            except Exception:
                pass

    def _release_keyboard_navigation(self, event=None) -> None:
        if event is not None and getattr(event, "widget", None) is not self.frame:
            return
        try:
            top = self.frame.winfo_toplevel()
            for sequence, binding in self._keyboard_bindings:
                top.unbind(sequence, binding)
        except Exception:
            pass
        self._keyboard_bindings.clear()

    def _panel(self, relx: float, relwidth: float) -> ctk.CTkFrame:
        panel = ctk.CTkFrame(
            self.frame,
            fg_color="#171717",
            corner_radius=16,
            border_width=1,
            border_color="#343434",
        )
        panel.place(
            relx=relx + 0.004,
            rely=self._content_rely,
            relwidth=max(0.01, relwidth - 0.008),
            relheight=self._content_relheight,
        )
        return panel

    def _render_mode_banner(self) -> None:
        banner = ctk.CTkFrame(
            self.frame,
            fg_color="#281414",
            corner_radius=14,
            border_width=2,
            border_color=DANGER,
        )
        banner.place(relx=0.004, rely=0.002, relwidth=0.992, relheight=0.13)
        banner.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            banner,
            text="☠",
            width=48,
            text_color=DANGER,
            font=ctk.CTkFont("Segoe UI Symbol", 24, "bold"),
        ).grid(row=0, column=0, rowspan=2, padx=(14, 8), pady=8)
        ctk.CTkLabel(
            banner,
            text=self.mode_banner.get("title", "SUSTITUCIÓN DE BAJA"),
            text_color=DANGER,
            anchor="w",
            font=ctk.CTkFont("Segoe UI", 13, "bold"),
        ).grid(row=0, column=1, sticky="sw", pady=(9, 0))
        ctk.CTkLabel(
            banner,
            text=self.mode_banner.get("detail", "Elige un sustituto en el PC."),
            text_color=TEXT,
            anchor="w",
            justify="left",
            font=ctk.CTkFont("Segoe UI", 12),
        ).grid(row=1, column=1, sticky="nw", pady=(0, 9))
        ctk.CTkButton(
            banner,
            text="CERRAR",
            command=self.on_cancel,
            width=82,
            height=32,
            fg_color="transparent",
            hover_color="#3A2222",
            border_width=1,
            border_color=DANGER,
            text_color=DANGER,
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
        ).grid(row=0, column=2, rowspan=2, padx=14, pady=10)

    def _render_team(self) -> None:
        heading = ctk.CTkFrame(self.team_panel, fg_color="transparent", corner_radius=0)
        heading.pack(fill="x", padx=14, pady=(7, 4) if self.mode_banner else (10, 5))
        ctk.CTkLabel(
            heading,
            text="EQUIPO",
            text_color=GOLD,
            font=ctk.CTkFont("Segoe UI", 17, "bold"),
        ).pack(side="left")
        if self.on_heal_party is not None and not self.mode_banner:
            ctk.CTkButton(
                heading, text="✚  CURAR EQUIPO", command=self.on_heal_party,
                width=132, height=30, corner_radius=8, fg_color="transparent",
                hover_color="#303030", border_width=1, border_color=GOLD,
                text_color=GOLD, font=ctk.CTkFont("Segoe UI", 11, "bold"),
            ).pack(side="right")
        slots = ctk.CTkFrame(self.team_panel, fg_color="transparent")
        slots.pack(
            fill="both", expand=True, padx=9,
            pady=(0, 4) if self.mode_banner else (0, 10),
        )
        slots.grid_columnconfigure(0, weight=1)
        # En el modo de baja la banda contextual reduce la altura disponible.
        # Las seis casillas siguen siendo visibles incluso en 1100x720 sin
        # reducir las fuentes funcionales por debajo de sus mínimos.
        card_height = 42 if self.mode_banner else 102
        for index, slot in enumerate(self.team_slots):
            slots.grid_rowconfigure(index, weight=1, uniform="team_slots")
            pokemon = slot.get("pokemon")
            slot_role = str(slot.get("slot_role") or "SIN ROL")
            preparation = slot.get("state") == "preparation"
            identity = self.identity_for(pokemon) if pokemon is not None else f"empty:{slot_role}"
            card = ctk.CTkFrame(
                slots,
                height=card_height,
                fg_color="#202020",
                corner_radius=12,
                border_width=1,
                border_color=PREPARATION if preparation else "#383838",
            )
            card.grid(
                row=index,
                column=0,
                sticky="nsew",
                pady=1 if self.mode_banner else 3,
            )
            card.grid_propagate(False)
            card.grid_columnconfigure(0, weight=1)
            card.grid_rowconfigure(0, weight=1)
            self.team_frames[identity] = card
            self.drop_targets.append((
                card,
                "team",
                {"slot_role": slot_role, "pokemon": pokemon},
            ))
            if preparation:
                self.team_preparation.add(identity)

            if pokemon is not None:
                self._render_team_card(
                    card, pokemon, slot_role, identity,
                    preparation=preparation,
                )
            else:
                empty = ctk.CTkFrame(card, fg_color="transparent", corner_radius=0)
                empty.pack(fill="both", expand=True, padx=8, pady=6)
                ctk.CTkLabel(
                    empty,
                    text=slot_role.upper(),
                    text_color=GOLD,
                    anchor="w",
                    font=ctk.CTkFont("Segoe UI", 12, "bold"),
                ).pack(anchor="w", padx=6, pady=((2, 0) if self.mode_banner else (8, 2)))
                ctk.CTkLabel(
                    empty,
                    text="CASILLA LIBRE",
                    text_color=MUTED,
                    anchor="w",
                    font=ctk.CTkFont("Segoe UI", 12),
                ).pack(anchor="w", padx=6, pady=(0, 2) if self.mode_banner else 0)

    @staticmethod
    def _health_presentation(
        hp_value: int | None, max_hp: int,
    ) -> tuple[float, str, str]:
        """Fracción, color y texto de una barra de PS.

        Lo usan por igual el render completo y la actualización incremental: si
        cada uno calculara lo suyo, una barra actualizada en vivo podría acabar
        mostrando un color distinto al que tendría tras un render normal.
        """
        text = (
            f"{hp_value}/{max_hp}"
            if hp_value is not None and max_hp > 0 else "No disponible"
        )
        if hp_value is None or max_hp <= 0:
            return 0.0, SUCCESS, text
        fraction = max(0.0, min(1.0, hp_value / max_hp))
        color = DANGER if fraction <= 0.25 else (GOLD if fraction <= 0.5 else SUCCESS)
        return fraction, color, text

    def rendered_team_identities(self) -> frozenset[str]:
        """Identidades cuyas barras de PS existen ahora mismo en la superficie.

        Permite al controlador distinguir "solo han cambiado los PS" de "la
        composición del equipo es otra", que sí exige reconstruir.
        """
        return frozenset(self._team_health_widgets)

    def update_team_health(
        self, identity: str, hp_value: int | None, max_hp: int,
    ) -> bool:
        """Actualiza los PS de un miembro sin reconstruir la página.

        Devuelve ``False`` cuando no puede hacerlo —identidad no renderizada,
        tarjeta ya destruida o tarjeta en modo banner, que muestra los PS dentro
        de otra etiqueta—. En ese caso el controlador debe recurrir al render
        completo: esta ruta acelera, nunca decide qué se muestra.
        """
        entry = self._team_health_widgets.get(str(identity))
        if not entry:
            return False
        bar = entry.get("bar")
        label = entry.get("label")
        try:
            if bar is None or label is None:
                return False
            if not bar.winfo_exists() or not label.winfo_exists():
                return False
            max_hp = int(max_hp or 0)
            value = int(hp_value) if hp_value is not None else None
            fraction, color, text = self._health_presentation(value, max_hp)
            bar.configure(progress_color=color)
            bar.set(fraction)
            label.configure(text=f"PS {text}")
        except Exception:
            return False
        # La barrera inicial comprueba lo que esta superficie materializó de
        # verdad. Si actualizamos los widgets sin actualizar esa evidencia, la
        # firma quedaría mintiendo sobre lo que el usuario está viendo.
        index = entry.get("health_index")
        if isinstance(index, int) and 0 <= index < len(self._rendered_team_health):
            slot = self._rendered_team_health[index][0]
            self._rendered_team_health[index] = (
                slot, value if value is not None else -1, max_hp,
            )
        return True

    def _render_team_card(
        self, card, pokemon: Any, slot_role: str, identity: str, *, preparation: bool,
    ) -> None:
        content = ctk.CTkFrame(card, fg_color="transparent", corner_radius=0)
        content.grid(row=0, column=0, sticky="nsew", padx=8, pady=5)
        content.grid_columnconfigure(1, weight=1)
        # Bajo una altura fija Tk reduce primero las filas con peso. La fila de
        # identidad era precisamente la única ponderada y podía colapsar a cero,
        # ocultando mote, especie y nivel aunque el resto de la tarjeta cupiera.
        content.grid_rowconfigure(0, minsize=20)

        current_hp = getattr(pokemon, "current_hp", None)
        max_hp = int(getattr(pokemon, "max_hp", 0) or 0)
        hp_value = int(current_hp) if current_hp is not None else None
        _fraction, _color, hp_text = self._health_presentation(hp_value, max_hp)
        self._rendered_team_health.append((
            int(getattr(pokemon, "slot", 0) or 0),
            int(hp_value) if hp_value is not None else -1,
            int(max_hp),
        ))
        health_index = len(self._rendered_team_health) - 1
        role_heading = slot_role.upper()
        if preparation:
            role_heading += " · PREPARACIÓN"
        if self.pending_for(pokemon, "team"):
            role_heading += " · PENDIENTE"

        if self.mode_banner:
            image = self.sprite_for(pokemon, (31, 31))
            if image is not None:
                self.images.append(image)
            ctk.CTkLabel(content, text="", image=image, width=44).grid(
                row=0, column=0, rowspan=2, padx=(3, 5), pady=1,
            )
            ctk.CTkLabel(
                content, text=f"{role_heading} · {hp_text}", text_color=GOLD,
                anchor="w", font=ctk.CTkFont("Segoe UI", 11, "bold"),
            ).grid(row=0, column=1, sticky="sw")
            ctk.CTkLabel(
                content,
                text=str(getattr(pokemon, "nickname", "") or getattr(pokemon, "species", "Pokémon")),
                text_color=TEXT, anchor="w", font=ctk.CTkFont("Segoe UI", 12, "bold"),
            ).grid(row=1, column=1, sticky="nw")
            info_rowspan = 2
        else:
            image = self.sprite_for(pokemon, (76, 76))
            if image is not None:
                self.images.append(image)
            ctk.CTkLabel(content, text="", image=image, width=84, height=80).grid(
                row=0, column=0, rowspan=4, padx=(2, 8), pady=1,
            )
            nickname = str(getattr(pokemon, "nickname", "") or getattr(pokemon, "species", "Pokémon"))
            ctk.CTkLabel(
                content,
                text=f"{nickname}  ·  Nv. {getattr(pokemon, 'level', '—')}",
                height=19, text_color=TEXT, anchor="w",
                font=ctk.CTkFont("Segoe UI", 16, "bold"),
            ).grid(row=0, column=1, sticky="ew")

            health = ctk.CTkFrame(content, fg_color="transparent", corner_radius=0)
            health.grid(row=1, column=1, sticky="ew")
            health.grid_columnconfigure(0, weight=1)
            fraction, health_color = _fraction, _color
            bar = ctk.CTkProgressBar(
                health, height=8, fg_color="#343434", progress_color=health_color,
            )
            bar.grid(row=0, column=0, sticky="ew", padx=(0, 8))
            bar.set(fraction)
            hp_label = ctk.CTkLabel(
                health, text=f"PS {hp_text}", width=78, height=13, text_color=TEXT,
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
            )
            hp_label.grid(row=0, column=1, sticky="e")
            # Referencias para poder refrescar los PS en vivo sin reconstruir.
            self._team_health_widgets[str(identity)] = {
                "bar": bar, "label": hp_label, "health_index": health_index,
            }

            stats = dict(getattr(pokemon, "stats", {}) or {})
            if max_hp > 0:
                stats["hp"] = max_hp
            increased = getattr(pokemon, "nature_increased", None)
            decreased = getattr(pokemon, "nature_decreased", None)
            stat_grid = ctk.CTkFrame(
                # 70 no dejaba sitio: el contenido de la tarjeta pedía 95 px y
                # solo hay 92 útiles, así que Tk recortaba el último borde de la
                # fila de ataques. Dos filas de etiqueta (10) y valor (11) con su
                # margen ocupan unos 46, así que 64 sigue sobrando de largo.
                content, width=265, height=64, fg_color="#252525", corner_radius=7,
            )
            stat_grid.grid(row=0, column=2, rowspan=3, sticky="nsew", padx=(8, 0))
            stat_grid.grid_propagate(False)
            for column in range(3):
                stat_grid.grid_columnconfigure(column, weight=1, uniform="team_card_stats")
            stat_grid.grid_rowconfigure((0, 1), weight=1, uniform="team_card_stat_rows")
            for index, key in enumerate(STAT_KEYS):
                column = index % 3
                row = index // 3
                color = DANGER if key == increased else (SELECTED if key == decreased else GOLD)
                stat = ctk.CTkFrame(stat_grid, fg_color="transparent", corner_radius=0)
                stat.grid(row=row, column=column, sticky="nsew", padx=2, pady=1)
                ctk.CTkLabel(
                    stat, text=STAT_LABELS[key], height=10, text_color=color,
                    font=ctk.CTkFont("Segoe UI", 9, "bold"),
                ).pack()
                ctk.CTkLabel(
                    stat, text=str(stats.get(key, "—")), height=11, text_color=TEXT,
                    font=ctk.CTkFont("Segoe UI", 12, "bold"),
                ).pack()

            ability = str(getattr(pokemon, "ability", "") or "No disponible")
            item = str(getattr(pokemon, "held_item", "") or "Ninguno")
            meta = ctk.CTkFrame(content, fg_color="transparent", corner_radius=0)
            meta.grid(row=2, column=1, sticky="ew")
            meta.grid_columnconfigure((0, 1), weight=1, uniform="team_card_meta")
            for column, text_value in enumerate((f"HABILIDAD · {ability}", f"OBJETO · {item}")):
                ctk.CTkLabel(
                    meta, text=text_value, height=13, text_color=MUTED, anchor="w",
                    font=ctk.CTkFont("Segoe UI", 10, "bold"),
                ).grid(row=0, column=column, sticky="ew", padx=(0, 5))

            moves = list(getattr(pokemon, "moves", None) or [])[:4]
            while len(moves) < 4:
                moves.append("—")
            issue_by_slot = _move_issue_map(
                pokemon, slot_role, self.move_issues_for, context="team",
            )
            support_excess, support_slots = _support_damage_map(
                pokemon, slot_role, self.support_damage_for, context="team",
            )
            move_grid = ctk.CTkFrame(content, fg_color="transparent", corner_radius=0)
            move_grid.grid(row=3, column=1, columnspan=2, sticky="ew", pady=(2, 0))
            move_grid.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="team_card_moves")
            for index, move in enumerate(moves):
                issue = issue_by_slot.get(index + 1)
                # El dorado no dice «ilegal», dice «elige cuál sobra». Una
                # incompatibilidad real manda sobre él.
                elegible = (index + 1) in support_slots and not issue
                marcado = bool(issue) or elegible
                move_cell = ctk.CTkFrame(
                    # Con marco hacen falta dos píxeles más: uno por borde. El
                    # sitio para ellos sale del bloque de estadísticas, no de
                    # apretar la tarjeta, que es lo que recortaba el borde.
                    move_grid, height=18 if marcado else 16, corner_radius=6,
                    fg_color="#341A1A" if issue else ("#292315" if elegible else "#292929"),
                    border_width=1 if marcado else 0,
                    border_color=DANGER if issue else (GOLD if elegible else "#292929"),
                )
                move_cell.grid(row=0, column=index, sticky="ew", padx=2, pady=(1, 1))
                move_cell.grid_propagate(False)
                ctk.CTkLabel(
                    move_cell, text=str(move), height=14,
                    fg_color="transparent",
                    text_color=(
                        DANGER if issue
                        else (GOLD if elegible else (TEXT if move != "—" else MUTED))
                    ),
                    font=ctk.CTkFont("Segoe UI", 9, "bold"),
                ).place(relx=0.5, rely=0.5, anchor="center")
            # La tarjeta solo marca; las acciones viven en la ficha, que es
            # donde ya estaban las de un movimiento incompatible.
            info_rowspan = 4

        role_icon = self.role_icon_for(slot_role, 27)
        if role_icon is not None:
            self.images.append(role_icon)
        info = ctk.CTkButton(
            content, text="" if role_icon is not None else "?", image=role_icon,
            command=lambda role_name=slot_role: self.on_role_info(role_name),
            width=34, height=34, corner_radius=17, fg_color="transparent",
            hover_color="#303030", border_width=1, border_color=GOLD,
            text_color=GOLD, font=ctk.CTkFont("Trebuchet MS", 14, "bold"),
        )
        info.grid(row=0, column=3, rowspan=info_rowspan, padx=(6, 1))
        self.role_info_buttons[identity] = info
        info.bind("<Enter>", lambda _event, button=info, role=slot_role: self._show_role_tooltip(button, role), add="+")
        info.bind("<Leave>", lambda _event: self._hide_role_tooltip(), add="+")
        self._bind_click_tree(card, lambda _event=None, p=pokemon: self._select_team(p), exclude={info})
        self._bind_drag_tree(card, "team", pokemon, exclude={info})
        self._bind_hover_tree(
            card,
            lambda _event=None, ident=identity, widget=card: self._team_hover(widget, ident),
            lambda _event=None: self.frame.after_idle(self._apply_selection_styles),
            exclude={info},
        )

    def _render_pc_shell(self) -> None:
        header = ctk.CTkFrame(self.pc_panel, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(12, 7))
        self._previous_box_button = ctk.CTkButton(
            header, text="‹", command=lambda: self._change_box(-1),
            width=34, height=32, fg_color=PANEL_ALT, hover_color="#303030",
            text_color=TEXT, font=ctk.CTkFont("Segoe UI", 18, "bold"),
        )
        self._previous_box_button.pack(side="left")
        self.box_label = ctk.CTkLabel(
            header,
            text=self._box_title(),
            text_color=GOLD,
            font=ctk.CTkFont("Segoe UI", 15, "bold"),
        )
        self.box_label.pack(side="left", expand=True)
        self._next_box_button = ctk.CTkButton(
            header, text="›", command=lambda: self._change_box(1),
            width=34, height=32, fg_color=PANEL_ALT, hover_color="#303030",
            text_color=TEXT, font=ctk.CTkFont("Segoe UI", 18, "bold"),
        )
        self._next_box_button.pack(side="right")

        search = ctk.CTkFrame(self.pc_panel, fg_color="transparent")
        search.pack(fill="x", padx=11, pady=(0, 8))
        self.search_var = ctk.StringVar(value="")
        self.search_entry = ctk.CTkEntry(
            search,
            textvariable=self.search_var,
            height=34,
            placeholder_text=("Buscar" if self.compact else "Buscar por nombre, especie, habilidad o movimiento"),
            fg_color="#111111",
            border_color="#3B3B3B",
            text_color=TEXT,
            font=ctk.CTkFont("Segoe UI", 12),
        )
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.search_scope = ctk.CTkButton(
            search,
            text="CAJA",
            command=self._toggle_search_scope,
            width=67,
            height=34,
            fg_color="transparent",
            hover_color="#303030",
            border_width=1,
            border_color="#4A4A4A",
            text_color=MUTED,
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
        )
        self.search_scope.pack(side="right")
        self.search_var.trace_add("write", lambda *_args: self._render_pc_grid())

        self.pc_grid = ctk.CTkScrollableFrame(
            self.pc_panel,
            fg_color="#111111",
            corner_radius=12,
            scrollbar_button_color="#343434",
            scrollbar_button_hover_color="#4A4A4A",
        )
        self.pc_grid.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        for column in range(self.pc_columns):
            self.pc_grid.grid_columnconfigure(column, weight=1, uniform="pc_cells")

    def _render_pc_grid(self) -> None:
        for child in self.pc_grid.winfo_children():
            child.destroy()
        self.pc_buttons.clear()
        self.pc_occupied_slots.clear()
        self.drop_targets = [target for target in self.drop_targets if target[1] == "team"]
        self.images = self.images[:len([slot for slot in self.team_slots if slot.get("pokemon")])]
        query = self.search_var.get().strip() if hasattr(self, "search_var") else ""
        if self._global_search and query:
            results = self.on_search(query)
            self._render_search_results(results)
            return
        if self._global_search and not query:
            ctk.CTkLabel(
                self.pc_grid,
                text="Escribe una búsqueda para consultar todas las cajas.",
                text_color=MUTED,
                wraplength=320,
                justify="center",
                font=ctk.CTkFont("Segoe UI", 13),
            ).grid(row=0, column=0, columnspan=self.pc_columns, padx=20, pady=40)
            return

        visible_slots: list[int] = []
        for slot in range(1, self.pc_slot_count + 1):
            pokemon = self.pc_members.get(slot)
            if pokemon is not None and query and not pokemon_matches_pc_query(pokemon, query):
                pokemon = None
            if pokemon is not None:
                visible_slots.append(slot)
            self._pc_cell(slot, pokemon)
        self.selection.set_pc_box(self.pc_box, visible_slots if query else self.pc_members)
        self._apply_selection_styles()
        if self.selection.context == "pc" and self.selection.selected_box_slot is None:
            self._render_inspector()

    def _render_search_results(self, results: list[tuple[int, int, Any]]) -> None:
        if not results:
            ctk.CTkLabel(
                self.pc_grid, text="No hay resultados en el PC.", text_color=MUTED,
                font=ctk.CTkFont("Segoe UI", 13, "bold"),
            ).grid(row=0, column=0, columnspan=self.pc_columns, pady=40)
            return
        for index, (box, slot, pokemon) in enumerate(results[:30]):
            image = self.sprite_for(pokemon, (42, 42))
            if image is not None:
                self.images.append(image)
            button = ctk.CTkButton(
                self.pc_grid,
                text=f"C{box} · {slot}",
                image=image,
                compound="top",
                command=lambda b=box, s=slot: self._jump_to_result(b, s),
                fg_color="#202020",
                hover_color="#2A2A2A",
                border_width=1,
                border_color="#383838",
                text_color=MUTED,
                font=ctk.CTkFont("Segoe UI", 10, "bold"),
            )
            button.grid(
                row=index // self.pc_columns,
                column=index % self.pc_columns,
                sticky="nsew", padx=3, pady=3,
            )

    def _pc_cell(self, slot: int, pokemon: Any | None) -> None:
        image = self.sprite_for(pokemon, (42, 42)) if pokemon is not None else None
        if image is not None:
            self.images.append(image)
        pending = pokemon is not None and self.pending_for(pokemon, "pc")
        button = ctk.CTkButton(
            self.pc_grid,
            width=1,
            height=66,
            text=str(slot),
            image=image,
            compound="top",
            command=lambda p=pokemon: self._activate_pc_cell(p),
            state="normal",
            fg_color="#211B2B" if pending else ("#202020" if pokemon is not None else "#161616"),
            hover_color="#2A2A2A",
            border_width=1,
            border_color="#9D83E6" if pending else "#303030",
            text_color=TEXT if pokemon is not None else "#555555",
            text_color_disabled="#555555",
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
        )
        button.grid(
            row=(slot - 1) // self.pc_columns,
            column=(slot - 1) % self.pc_columns,
            sticky="nsew", padx=3, pady=3,
        )
        self.pc_buttons[slot] = button
        if pokemon is not None:
            self.pc_occupied_slots.add(slot)
        self.drop_targets.append((
            button,
            "pc",
            {"box": self.pc_box, "slot": slot, "pokemon": pokemon},
        ))
        if pokemon is not None:
            self._bind_drag_tree(button, "pc", pokemon)

    def _render_inspector(self) -> None:
        self._inspector_action_buttons.clear()
        self._keyboard_inspector_action = None
        for child in self.inspector_panel.winfo_children():
            child.destroy()
        header = ctk.CTkFrame(self.inspector_panel, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(12, 4))
        ctk.CTkButton(
            header, text="‹", command=lambda: self._move_selection(-1), width=34, height=32,
            fg_color="transparent", hover_color="#303030", border_width=1,
            border_color="#4A4A4A", text_color=TEXT,
        ).pack(side="left")
        ctk.CTkLabel(
            header, text="FICHA" if self.compact else "FICHA DEL POKÉMON", text_color=GOLD,
            font=ctk.CTkFont("Segoe UI", 14, "bold"),
        ).pack(side="left", expand=True)
        ctk.CTkButton(
            header, text="›", command=lambda: self._move_selection(1), width=34, height=32,
            fg_color="transparent", hover_color="#303030", border_width=1,
            border_color="#4A4A4A", text_color=TEXT,
        ).pack(side="right")

        pokemon = self._selected_pokemon()
        if pokemon is None:
            ctk.CTkLabel(
                self.inspector_panel,
                text="Selecciona un Pokémon del equipo o del PC.",
                text_color=MUTED,
                wraplength=280,
                justify="center",
                font=ctk.CTkFont("Segoe UI", 14),
            ).pack(expand=True, padx=20, pady=40)
            return

        context = self.selection.context
        if self.interaction_mode == "faint-replacement":
            definitions = (("ELEGIR COMO SUSTITUTO", "replace_fainted"),) if context == "pc" else ()
        elif context == "team":
            definitions = (
                ("CAMBIAR ROL", "change_role"),
                ("ENSEÑAR MT", "teach_tm"),
            )
        else:
            definitions = (("AÑADIR O CAMBIAR CON EQUIPO", "pc_to_team"),)

        # Las acciones son un pie fijo del inspector. Antes formaban parte del
        # cuerpo expandible y la ficha de stats podía empujarlas fuera del
        # viewport (especialmente con el aviso de sustitución visible).
        actions = ctk.CTkFrame(self.inspector_panel, fg_color="transparent")
        actions.pack(side="bottom", fill="x", padx=14, pady=(3, 11))
        actions.grid_columnconfigure((0, 1), weight=1, uniform="inspector_actions")
        for index, (label, action) in enumerate(definitions):
            button = ctk.CTkButton(
                actions,
                text=label,
                command=lambda key=action, p=pokemon: self.on_action(key, p),
                height=40,
                fg_color=GOLD if action in {"swap_with_pc", "pc_to_team", "teach_tm", "replace_fainted"} else "transparent",
                hover_color="#D3AF70" if action in {"swap_with_pc", "pc_to_team", "teach_tm", "replace_fainted"} else "#303030",
                border_width=1,
                border_color=GOLD if action != "send_to_pc" else "#666666",
                text_color="#111111" if action in {"swap_with_pc", "pc_to_team", "teach_tm", "replace_fainted"} else TEXT,
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
            )
            button.grid(row=index // 2, column=index % 2, sticky="ew", padx=2, pady=2)
            self._inspector_action_buttons[action] = button

        # La única barra de scroll de esta vista pertenece al PC. La ficha se
        # mantiene como tarjeta fija: en ventanas bajas puede recortarse, pero no
        # compite con la navegación vertical de las cajas.
        details = ctk.CTkFrame(
            self.inspector_panel, fg_color="transparent", corner_radius=0,
        )
        details.pack(fill="both", expand=True, padx=7, pady=(0, 7))

        identity = ctk.CTkFrame(details, fg_color="transparent")
        identity.pack(fill="x", padx=5, pady=(0, 3))
        identity.grid_columnconfigure(1, weight=1)
        inspector_image_size = 64 if self.compact else 72
        image = self.sprite_for(pokemon, (inspector_image_size, inspector_image_size))
        if image is not None:
            self.images.append(image)
        ctk.CTkLabel(
            identity, text="", image=image, width=inspector_image_size + 8,
            height=inspector_image_size + 4,
        ).grid(row=0, column=0, rowspan=5, padx=(0, 8), pady=2)
        name = str(getattr(pokemon, "nickname", "") or getattr(pokemon, "species", "Pokémon"))
        ctk.CTkLabel(
            identity, text=name, text_color=TEXT, anchor="w",
            font=ctk.CTkFont("Segoe UI", 17 if self.compact else 20, "bold"),
        ).grid(row=0, column=1, sticky="sw")
        ctk.CTkLabel(
            identity,
            text=f"{getattr(pokemon, 'species', 'No disponible')} · Nv. {getattr(pokemon, 'level', '—')}",
            text_color=MUTED, anchor="w",
            font=ctk.CTkFont("Segoe UI", 12),
        ).grid(row=1, column=1, sticky="w")
        role, symbol = self.role_for(pokemon, context)
        location = (
            f"CAJA {self.pc_box} · POSICIÓN {int(getattr(pokemon, 'box_slot', 0) or 0)}"
            if context == "pc" else f"POSICIÓN FÍSICA {int(getattr(pokemon, 'slot', 0) or 0)}"
        )
        ctk.CTkLabel(
            identity, text=f"{symbol} {role}".strip(), anchor="w",
            text_color=GOLD if role != "SIN ROL" else PREPARATION,
            font=ctk.CTkFont("Segoe UI", 13, "bold"),
        ).grid(row=2, column=1, sticky="w", pady=(2, 0))
        ctk.CTkLabel(
            identity, text=location, text_color=MUTED, anchor="w",
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
        ).grid(row=3, column=1, sticky="nw")

        nature = str(getattr(pokemon, "nature", "") or "No disponible")
        stat_nature = str(getattr(pokemon, "stat_nature", "") or "")
        nature_text = f"NATURALEZA · {nature}"
        if stat_nature and stat_nature != nature:
            nature_text += f"  (efecto {stat_nature})"
        ctk.CTkLabel(
            details, text=nature_text, text_color=GOLD, anchor="w",
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
        ).pack(fill="x", padx=8, pady=(1, 4))

        stats = dict(getattr(pokemon, "stats", {}) or {})
        base_stats = (
            dict(self.base_stats_for(pokemon) or {})
            if self.base_stats_for is not None
            else dict(getattr(pokemon, "base_stats", {}) or {})
        )
        ivs = dict(getattr(pokemon, "ivs", {}) or {})
        evs = dict(getattr(pokemon, "evs", {}) or {})
        max_hp = int(getattr(pokemon, "max_hp", 0) or 0)
        if max_hp > 0:
            stats["hp"] = max_hp
        increased = getattr(pokemon, "nature_increased", None)
        decreased = getattr(pokemon, "nature_decreased", None)
        stat_grid = ctk.CTkFrame(details, fg_color="#202020", corner_radius=10)
        stat_grid.pack(fill="x", padx=7, pady=(0, 4))
        stat_columns = 3 if self.compact else 6
        for column in range(stat_columns):
            stat_grid.grid_columnconfigure(column, weight=1, uniform="pokemon_stats")
        for index, key in enumerate(STAT_KEYS):
            column = index % stat_columns
            row = (index // stat_columns) * 5
            color = DANGER if key == increased else (SELECTED if key == decreased else GOLD)
            ctk.CTkLabel(
                stat_grid, text=STAT_LABELS[key], text_color=color,
                font=ctk.CTkFont("Segoe UI", 10, "bold"),
            ).grid(row=row, column=column, padx=1, pady=(7, 0))
            ctk.CTkLabel(
                stat_grid, text=str(stats.get(key, "—")), text_color=TEXT,
                font=ctk.CTkFont("Segoe UI", 15, "bold"),
            ).grid(row=row + 1, column=column, padx=1, pady=(0, 1))
            ctk.CTkLabel(
                stat_grid, text=f"BASE {base_stats.get(key, '—')}", text_color=GOLD,
                font=ctk.CTkFont("Segoe UI", 9, "bold"),
            ).grid(row=row + 2, column=column, padx=1, pady=0)
            ctk.CTkLabel(
                stat_grid, text=f"IV {ivs.get(key, '—')}", text_color=MUTED,
                font=ctk.CTkFont("Segoe UI", 10, "bold"),
            ).grid(row=row + 3, column=column, padx=1, pady=0)
            ctk.CTkLabel(
                stat_grid, text=f"EV {evs.get(key, '—')}", text_color=MUTED,
                font=ctk.CTkFont("Segoe UI", 10, "bold"),
            ).grid(row=row + 4, column=column, padx=1, pady=(0, 5))

        summary = ctk.CTkFrame(details, fg_color="transparent")
        summary.pack(fill="x", padx=7, pady=(0, 3))
        summary.grid_columnconfigure((0, 1), weight=1, uniform="pokemon_summary")
        for column, (label, value) in enumerate((
            ("HABILIDAD", str(getattr(pokemon, "ability", "") or "No disponible")),
            ("OBJETO", str(getattr(pokemon, "held_item", "") or "Ninguno")),
        )):
            box = ctk.CTkFrame(summary, fg_color="#202020", corner_radius=9)
            box.grid(row=0, column=column, sticky="nsew", padx=(0, 2) if column == 0 else (2, 0))
            ctk.CTkLabel(
                box, text=label, text_color=GOLD,
                font=ctk.CTkFont("Segoe UI", 10, "bold"),
            ).pack(pady=(7, 1))
            ctk.CTkLabel(
                box, text=value, text_color=TEXT,
                font=ctk.CTkFont("Segoe UI", 13, "bold"),
            ).pack(padx=9, pady=(0, 7))

        moves = list(getattr(pokemon, "moves", None) or [])[:4]
        while len(moves) < 4:
            moves.append("—")
        ctk.CTkLabel(
            details, text="MOVIMIENTOS", text_color=GOLD,
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
        ).pack(anchor="w", padx=8, pady=(3, 1))
        move_grid = ctk.CTkFrame(details, fg_color="transparent")
        move_grid.pack(fill="x", padx=5, pady=(0, 3))
        move_grid.grid_columnconfigure((0, 1), weight=1, uniform="inspector_moves")
        issue_by_slot = _move_issue_map(
            pokemon, role, self.move_issues_for, context=context,
        )
        support_excess, support_slots = _support_damage_map(
            pokemon, role, self.support_damage_for, context=context,
        )
        if support_excess:
            ctk.CTkLabel(
                details,
                text=(
                    f"Support conserva 2 ataques de daño: elige {support_excess} "
                    "para quitar o sustituir."
                ),
                text_color=GOLD, wraplength=260, justify="center",
                font=ctk.CTkFont("Segoe UI", 10, "bold"),
            ).pack(padx=8, pady=(0, 3))
        for index, move in enumerate(moves):
            issue = issue_by_slot.get(index + 1)
            # El dorado no dice «ilegal», dice «elige cuál sobra». Las acciones
            # son las mismas que para una incompatibilidad: el usuario decide.
            elegible = (index + 1) in support_slots and not issue
            accionable = bool(issue) or elegible
            color = DANGER if issue else GOLD
            cell = ctk.CTkFrame(
                move_grid,
                height=32,
                corner_radius=8,
                fg_color="#341A1A" if issue else ("#292315" if elegible else PANEL_ALT),
                border_width=1 if accionable else 0,
                border_color=color if accionable else PANEL_ALT,
            )
            cell.grid(
                row=index // 2, column=index % 2,
                sticky="ew", padx=2, pady=2,
            )
            # Una celda con botones se ajusta a lo que lleva dentro. Fijarle 54
            # píxeles recortaba el marco de abajo en cuanto el texto ocupaba dos
            # líneas o el tema cambiaba de fuente.
            cell.grid_propagate(not accionable)
            ctk.CTkLabel(
                cell, text=str(move),
                text_color=color if accionable else (TEXT if move != "—" else MUTED),
                font=ctk.CTkFont("Segoe UI", 12, "bold"),
            ).pack(fill="x", padx=4, pady=(4, 1) if accionable else 6)
            if accionable:
                row = ctk.CTkFrame(cell, fg_color="transparent")
                row.pack(fill="x", padx=4, pady=(0, 4))
                ctk.CTkButton(
                    row, text="SUSTITUIR", height=21,
                    command=lambda p=pokemon, s=index + 1: self.on_action(f"replace_move:{s}", p),
                    fg_color=GOLD, hover_color="#D3AF70", text_color="#111111",
                    font=ctk.CTkFont("Segoe UI", 9, "bold"),
                ).pack(side="left", fill="x", expand=True, padx=(0, 2))
                ctk.CTkButton(
                    row, text="ELIMINAR", height=21,
                    command=lambda p=pokemon, s=index + 1: self.on_action(f"delete_move:{s}", p),
                    fg_color="transparent",
                    hover_color="#4A2020" if issue else "#332B1D",
                    border_width=1, border_color=color, text_color=color,
                    font=ctk.CTkFont("Segoe UI", 9, "bold"),
                ).pack(side="left", fill="x", expand=True, padx=(2, 0))

        if context == "pc":
            ctk.CTkLabel(
                details,
                text="Las flechas recorren solo posiciones ocupadas de esta caja.",
                text_color=MUTED,
                wraplength=260,
                justify="center",
                font=ctk.CTkFont("Segoe UI", 11),
            ).pack(padx=8, pady=(1, 4))

    def _selected_pokemon(self) -> Any | None:
        if not self.selection.active:
            return None
        if self.selection.context == "pc":
            return self.pc_members.get(int(self.selection.selected_box_slot or 0))
        identity = self.selection.selected_identity
        for slot in self.team_slots:
            pokemon = slot.get("pokemon")
            if pokemon is not None and self.identity_for(pokemon) == identity:
                return pokemon
        return None

    def _select_team(self, pokemon: Any) -> None:
        if self._suppress_click_once:
            return
        self.selection.select_team(self.identity_for(pokemon))
        self._apply_selection_styles()
        self._render_inspector()
        if self.on_select is not None:
            self.on_select("team", pokemon)

    def _select_pc(self, pokemon: Any) -> None:
        if self._suppress_click_once:
            return
        slot = int(getattr(pokemon, "box_slot", 0) or getattr(pokemon, "slot", 0) or 0)
        self.selection.select_pc(slot)
        self._apply_selection_styles()
        self._render_inspector()
        if self.on_select is not None:
            self.on_select("pc", pokemon)

    def _activate_pc_cell(self, pokemon: Any | None) -> None:
        if pokemon is not None:
            self._select_pc(pokemon)

    def _move_selection(self, delta: int):
        if self.selection.move(delta) is None:
            return "break"
        self._apply_selection_styles()
        self._render_inspector()
        return "break"

    def _move_direction_key(self, event, direction: str) -> str | None:
        if event_targets_text_input(event):
            return None
        guard = getattr(self, "navigation_guard", None)
        if callable(guard) and not guard():
            return None
        intercept = getattr(self, "navigation_intercept", None)
        if callable(intercept) and intercept(direction):
            return "break"
        if self._keyboard_inspector_action is not None:
            action, pokemon = self._keyboard_inspector_action
            actions = tuple(self._inspector_action_buttons)
            index = actions.index(action) if action in actions else 0
            if direction == "right" and index < len(actions) - 1:
                self._keyboard_inspector_action = (actions[index + 1], pokemon)
            elif direction == "left" and index > 0:
                self._keyboard_inspector_action = (actions[index - 1], pokemon)
            elif direction == "left":
                self._keyboard_inspector_action = None
            self._apply_selection_styles()
            return "break"
        before = (
            self.selection.context,
            self.selection.selected_identity,
            self.selection.selected_box_slot,
        )
        if self.selection.move_direction(direction, pc_columns=self.pc_columns) is None:
            return "break"
        after = (
            self.selection.context,
            self.selection.selected_identity,
            self.selection.selected_box_slot,
        )
        if direction == "left" and before == after and self.selection.context == "team":
            if callable(self.on_left_edge):
                self.on_left_edge()
            return "break"
        if (
            direction == "right"
            and before == after
            and self._inspector_action_buttons
        ):
            pokemon = self._selected_pokemon()
            action = next(iter(self._inspector_action_buttons))
            if pokemon is not None:
                self._keyboard_inspector_action = (action, pokemon)
        self._apply_selection_styles()
        if self._keyboard_inspector_action is None:
            self._schedule_inspector_render()
        if self.selection.context == "pc":
            self.frame.after_idle(self._scroll_pc_selection_into_view)
        return "break"

    def _accept_keyboard_selection(self, event=None) -> str | None:
        if event is not None and event_targets_text_input(event):
            return None
        guard = getattr(self, "navigation_guard", None)
        if callable(guard) and not guard():
            return None
        if callable(self.on_edge_accept) and self.on_edge_accept():
            return "break"
        if self._keyboard_inspector_action is not None:
            action, pokemon = self._keyboard_inspector_action
            self.on_action(action, pokemon)
            return "break"
        pokemon = self._selected_pokemon()
        if pokemon is None:
            return "break"
        if self._inspector_action_buttons:
            action = next(iter(self._inspector_action_buttons))
            self._keyboard_inspector_action = (action, pokemon)
            self._apply_selection_styles()
        return "break"

    def _clear_keyboard_selection(self, event=None) -> str | None:
        if event is not None and event_targets_text_input(event):
            return None
        guard = getattr(self, "navigation_guard", None)
        if callable(guard) and not guard():
            return None
        intercept = getattr(self, "navigation_intercept", None)
        if callable(intercept) and intercept("back"):
            return "break"
        if self._keyboard_inspector_action is not None:
            self._keyboard_inspector_action = None
            self._apply_selection_styles()
            return "break"
        # El cursor se conserva: Atrás sale del nivel de ficha sin obligar al
        # usuario a empezar de nuevo desde la primera casilla.
        self._keyboard_inspector_action = None
        self._apply_selection_styles()
        return "break"

    def _schedule_inspector_render(self) -> None:
        """Agrupa ráfagas de flechas y pinta solamente la ficha final."""
        if self._inspector_render_after_id is not None:
            try:
                self.frame.after_cancel(self._inspector_render_after_id)
            except Exception:
                pass
        self._inspector_render_after_id = self.frame.after(18, self._flush_inspector_render)

    def _flush_inspector_render(self) -> None:
        self._inspector_render_after_id = None
        self._render_inspector()

    def _scroll_pc_selection_into_view(self) -> None:
        slot = self.selection.selected_box_slot
        if not self.selection.active or self.selection.context != "pc" or slot is None:
            return
        button = self.pc_buttons.get(int(slot))
        canvas = getattr(self.pc_grid, "_parent_canvas", None)
        if button is None or canvas is None:
            return
        try:
            content_height = max(1, int(canvas.bbox("all")[3]))
            viewport_height = max(1, int(canvas.winfo_height()))
            button_top = int(button.winfo_y())
            button_bottom = button_top + int(button.winfo_height())
            visible_top = int(canvas.canvasy(0))
            visible_bottom = visible_top + viewport_height
            if button_top < visible_top:
                canvas.yview_moveto(max(0.0, button_top / content_height))
            elif button_bottom > visible_bottom:
                target = max(0, button_bottom - viewport_height)
                canvas.yview_moveto(min(1.0, target / content_height))
        except Exception:
            pass

    def _apply_selection_styles(self) -> None:
        selected_identity = (
            self.selection.selected_identity
            if (
                self.selection.active and self.selection.context == "team"
                and not self._external_navigation_focus
            ) else None
        )
        for identity, card in self.team_frames.items():
            selected = identity == selected_identity
            preparation = identity in self.team_preparation
            try:
                card.configure(
                    fg_color="#2A2417" if selected else "#202020",
                    border_width=3 if selected else 1,
                    border_color="#F2C45E" if selected else (PREPARATION if preparation else "#383838"),
                )
            except Exception:
                pass
        selected_slot = (
            self.selection.selected_box_slot
            if (
                self.selection.active and self.selection.context == "pc"
                and not self._external_navigation_focus
            ) else None
        )
        for slot, button in self.pc_buttons.items():
            selected = slot == selected_slot
            occupied = slot in self.pc_occupied_slots
            try:
                button.configure(
                    fg_color="#2A2417" if selected else ("#202020" if occupied else "#161616"),
                    border_width=3 if selected else 1,
                    border_color="#F2C45E" if selected else "#303030",
                )
            except Exception:
                pass
        active_action = (
            self._keyboard_inspector_action[0]
            if self._keyboard_inspector_action is not None and not self._external_navigation_focus
            else None
        )
        for action, button in self._inspector_action_buttons.items():
            try:
                button.configure(
                    border_width=3 if action == active_action else 1,
                    border_color="#F7D47D" if action == active_action else GOLD,
                )
            except Exception:
                pass

    def set_external_navigation_focus(self, active: bool) -> None:
        """Oculta el cursor local mientras el menú lateral posee el foco."""
        self._external_navigation_focus = bool(active)
        self._apply_selection_styles()

    def _team_hover(self, card, identity: str) -> None:
        selected = (
            self.selection.context == "team"
            and self.selection.selected_identity == identity
        )
        if not selected:
            try:
                card.configure(fg_color="#292929")
            except Exception:
                pass

    def _change_box(self, delta: int) -> None:
        preferred = self.selection.selected_box_slot
        target = ((self.pc_box - 1 + delta) % self.pc_box_count) + 1
        for _unused in range(self.pc_box_count):
            if target not in self.excluded_boxes:
                break
            target = ((target - 1 + delta) % self.pc_box_count) + 1
        box, members = self.on_box_change(target)
        self.pc_box = int(box)
        self.pc_members = dict(members)
        self.selection.context = "pc"
        self.selection.selected_box_slot = preferred
        self.selection.set_pc_box(self.pc_box, self.pc_members)
        self.box_label.configure(text=self._box_title())
        self._render_pc_grid()
        self._render_inspector()

    def _toggle_search_scope(self) -> None:
        self._global_search = not self._global_search
        self.search_scope.configure(
            text="TODO PC" if self._global_search else "CAJA",
            border_color=GOLD if self._global_search else "#4A4A4A",
            text_color=GOLD if self._global_search else MUTED,
        )
        self._render_pc_grid()

    def _clear_search(self) -> str:
        if self.search_var.get():
            self.search_var.set("")
            return "break"
        return "break"

    def _on_escape(self, _event=None) -> str:
        if self._drag_source is not None:
            self._cancel_drag()
            return "break"
        if self.on_cancel is not None:
            self.on_cancel()
        return self._clear_search()

    def _begin_drag(self, event, context: str, pokemon: Any) -> None:
        if self.on_drop is None:
            return
        self._cancel_drag()
        self._drag_origin = (int(event.x_root), int(event.y_root))
        self._drag_source = (str(context), pokemon)
        if context == "team":
            self._drag_source_widget = self.team_frames.get(self.identity_for(pokemon))
        else:
            slot = int(getattr(pokemon, "box_slot", 0) or getattr(pokemon, "slot", 0) or 0)
            self._drag_source_widget = self.pc_buttons.get(slot)

    @staticmethod
    def _point_inside_widget(widget: Any | None, x_root: int, y_root: int) -> bool:
        if widget is None:
            return False
        try:
            return bool(
                widget.winfo_exists()
                and widget.winfo_rootx() <= x_root <= widget.winfo_rootx() + widget.winfo_width()
                and widget.winfo_rooty() <= y_root <= widget.winfo_rooty() + widget.winfo_height()
            )
        except Exception:
            return False

    def _capture_drag_events(self) -> None:
        if self._drag_capture_bindings:
            return
        try:
            # Tk no propaga eventos por la jerarquía padre/hijo. La captura
            # anterior usaba ``grab_set`` sobre ``frame`` para compensarlo,
            # pero eso retargeteaba el puntero a la superficie de origen: el
            # drop terminaba resolviéndose contra esa casilla y las flechas de
            # caja nunca recibían un hover real. El bindtag del Toplevel es
            # estable aunque se redibuje la caja y conserva las coordenadas
            # físicas del widget que está realmente bajo el cursor.
            event_surface = self.frame.winfo_toplevel()
            motion_id = event_surface.bind("<B1-Motion>", self._move_drag, add="+")
            release_id = event_surface.bind("<ButtonRelease-1>", self._end_drag, add="+")
            self._drag_capture_bindings = [
                (event_surface, "<B1-Motion>", motion_id),
                (event_surface, "<ButtonRelease-1>", release_id),
            ]
        except Exception:
            self._release_drag_capture()

    def _release_drag_capture(self) -> None:
        self._cancel_drag_box_hover()
        for event_surface, sequence, binding_id in self._drag_capture_bindings:
            try:
                event_surface.unbind(sequence, binding_id)
            except Exception:
                pass
        self._drag_capture_bindings.clear()

    def _cancel_drag_box_hover(self) -> None:
        after_id = self._drag_box_hover_after_id
        self._drag_box_hover_after_id = None
        self._drag_box_hover_direction = None
        if after_id is not None:
            try:
                self.frame.after_cancel(after_id)
            except Exception:
                pass

    def _update_drag_box_hover(self, x_root: int, y_root: int) -> None:
        direction = None
        if self._point_inside_widget(self._previous_box_button, x_root, y_root):
            direction = -1
        elif self._point_inside_widget(self._next_box_button, x_root, y_root):
            direction = 1

        if direction is None:
            self._cancel_drag_box_hover()
            self._drag_box_hover_consumed = None
            return
        if direction == self._drag_box_hover_consumed:
            return
        if direction == self._drag_box_hover_direction and self._drag_box_hover_after_id is not None:
            return
        self._cancel_drag_box_hover()
        self._drag_box_hover_direction = direction

        def change_box_after_hover(expected_direction: int = direction) -> None:
            self._drag_box_hover_after_id = None
            self._drag_box_hover_direction = None
            if not self._drag_started or self._drag_source is None:
                return
            try:
                pointer_x, pointer_y = self.frame.winfo_pointerxy()
            except Exception:
                return
            button = self._previous_box_button if expected_direction < 0 else self._next_box_button
            if not self._point_inside_widget(button, int(pointer_x), int(pointer_y)):
                return
            self._drag_box_hover_consumed = expected_direction
            self._change_box(expected_direction)
            self._highlight_drop_target(int(pointer_x), int(pointer_y))

        self._drag_box_hover_after_id = self.frame.after(420, change_box_after_hover)

    def _move_drag(self, event) -> str | None:
        if self._drag_source is None or self._drag_origin is None:
            return None
        distance = abs(int(event.x_root) - self._drag_origin[0]) + abs(int(event.y_root) - self._drag_origin[1])
        if not self._drag_started and distance >= 7:
            self._drag_started = True
            self._suppress_click_once = True
            context, pokemon = self._drag_source
            label = str(getattr(pokemon, "nickname", "") or getattr(pokemon, "species", "Pokémon"))
            # Mover un CTkFrame con ``place`` obliga a varios canvas hermanos a
            # invalidar regiones distintas; Windows conservaba cada posición y
            # dibujaba la estela observada. Un HWND independiente se desplaza por
            # composición DWM y tiene una sola superficie que destruir al soltar.
            self._drag_ghost = tk.Toplevel(self.frame)
            self._drag_ghost.withdraw()
            self._drag_ghost.overrideredirect(True)
            self._drag_ghost.configure(background="#172236")
            try:
                self._drag_ghost.attributes("-topmost", True)
            except Exception:
                pass
            tk.Label(
                self._drag_ghost,
                text=f"{label}\n{'EQUIPO' if context == 'team' else 'PC'}",
                foreground=TEXT, background="#172236",
                font=("Segoe UI", 11, "bold"), padx=12, pady=7,
            ).pack(fill="both", expand=True, padx=2, pady=2)
            self._drag_ghost.geometry(
                f"+{int(event.x_root) + 12}+{int(event.y_root) + 12}"
            )
            self._drag_ghost.deiconify()
            self._drag_ghost.lift()
            # La casilla de origen puede destruirse al navegar a otra caja.
            # Capturamos el ratón en la superficie estable para conservar los
            # eventos de movimiento y liberación hasta completar el drop.
            self._capture_drag_events()
            if self._drag_source_widget is not None:
                try:
                    self._drag_source_widget.configure(border_width=2, border_color=GOLD)
                except Exception:
                    pass
        if self._drag_started and self._drag_ghost is not None:
            self._drag_ghost.geometry(
                f"+{int(event.x_root) + 12}+{int(event.y_root) + 12}"
            )
            self._drag_ghost.lift()
            self._update_drag_box_hover(int(event.x_root), int(event.y_root))
            self._highlight_drop_target(int(event.x_root), int(event.y_root))
            return "break"
        return None

    def _end_drag(self, event) -> str | None:
        moved = self._drag_started
        source = self._drag_source
        target = self._drop_target_at(int(event.x_root), int(event.y_root)) if moved else None
        self._clear_drag_visuals()
        self._drag_origin = None
        self._drag_source = None
        self._drag_started = False
        self._drag_source_widget = None
        self._release_drag_capture()
        if moved:
            self.frame.after(80, lambda: setattr(self, "_suppress_click_once", False))
            if source is not None and target is not None and self.on_drop is not None:
                source_context, pokemon = source
                target_context, target_data = target
                self.on_drop(source_context, pokemon, target_context, target_data)
            return "break"
        self._suppress_click_once = False
        return None

    def _cancel_drag(self) -> None:
        self._clear_drag_visuals()
        self._drag_origin = None
        self._drag_source = None
        self._drag_started = False
        self._drag_source_widget = None
        self._suppress_click_once = False
        self._release_drag_capture()

    def _clear_drag_visuals(self) -> None:
        if self._drag_ghost is not None:
            try:
                self._drag_ghost.destroy()
            except Exception:
                pass
        self._drag_ghost = None
        self._restore_target_border()

    def _drop_target_at(self, x_root: int, y_root: int) -> tuple[str, dict[str, Any]] | None:
        for widget, context, target in list(self.drop_targets):
            try:
                if (
                    widget.winfo_exists()
                    and widget.winfo_rootx() <= x_root <= widget.winfo_rootx() + widget.winfo_width()
                    and widget.winfo_rooty() <= y_root <= widget.winfo_rooty() + widget.winfo_height()
                ):
                    return context, target
            except Exception:
                continue
        return None

    def _highlight_drop_target(self, x_root: int, y_root: int) -> None:
        target_widget = None
        target_context = None
        target_data = None
        for widget, context, target in list(self.drop_targets):
            try:
                if (
                    widget.winfo_rootx() <= x_root <= widget.winfo_rootx() + widget.winfo_width()
                    and widget.winfo_rooty() <= y_root <= widget.winfo_rooty() + widget.winfo_height()
                ):
                    target_widget = widget
                    target_context = context
                    target_data = target
                    break
            except Exception:
                continue
        if target_widget is self._drag_target_widget:
            return
        self._restore_target_border()
        self._drag_target_widget = target_widget
        if target_widget is not None:
            try:
                valid = True
                if self.can_drop is not None and self._drag_source is not None:
                    source_context, source = self._drag_source
                    valid = bool(self.can_drop(
                        source_context, source, str(target_context), dict(target_data or {}),
                    ))
                target_widget.configure(
                    border_width=2,
                    border_color=SUCCESS if valid else DANGER,
                )
            except Exception:
                pass

    def _restore_target_border(self) -> None:
        widget = self._drag_target_widget
        self._drag_target_widget = None
        if widget is None:
            return
        self._apply_selection_styles()

    def _jump_to_result(self, box: int, slot: int) -> None:
        loaded_box, members = self.on_box_change(int(box))
        self.pc_box = int(loaded_box)
        self.pc_members = dict(members)
        self._global_search = False
        self.search_var.set("")
        self.search_scope.configure(text="CAJA", border_color="#4A4A4A", text_color=MUTED)
        self.selection.context = "pc"
        self.selection.selected_box_slot = int(slot)
        self.selection.set_pc_box(self.pc_box, self.pc_members)
        self.box_label.configure(text=self._box_title())
        self._render_pc_grid()
        self._render_inspector()

    def _show_role_tooltip(self, button, role: str) -> None:
        self._hide_role_tooltip()
        try:
            tooltip = ctk.CTkLabel(
                self.frame,
                text=str(role).upper(),
                fg_color="#111111",
                corner_radius=7,
                text_color=GOLD,
                font=ctk.CTkFont("Segoe UI", 10, "bold"),
                height=24,
            )
            # Anclar contra el propio botón evita mezclar coordenadas del frame
            # interno con las del canvas desplazable (el desfase observado era
            # exactamente el origen X de la barra lateral colapsada).
            tooltip.place(in_=button, relx=0.5, y=-5, anchor="s")
            tooltip.lift()
            self._role_tooltip = tooltip
        except Exception:
            self._role_tooltip = None

    def _hide_role_tooltip(self) -> None:
        tooltip = self._role_tooltip
        self._role_tooltip = None
        try:
            if tooltip is not None and tooltip.winfo_exists():
                tooltip.destroy()
        except Exception:
            pass

    def _box_title(self) -> str:
        return f"CAJA {self.pc_box} DE {self.pc_box_count}"

    @staticmethod
    def _bind_click_tree(widget, callback, *, exclude: set[Any] | None = None) -> None:
        excluded = exclude or set()
        if widget in excluded:
            return
        widget.bind("<ButtonRelease-1>", callback, add="+")
        for child in widget.winfo_children():
            UnifiedTeamPCView._bind_click_tree(child, callback, exclude=excluded)

    @staticmethod
    def _bind_hover_tree(widget, on_enter, on_leave, *, exclude: set[Any] | None = None) -> None:
        excluded = exclude or set()
        if widget in excluded:
            return
        widget.bind("<Enter>", on_enter, add="+")
        widget.bind("<Leave>", on_leave, add="+")
        for child in widget.winfo_children():
            if child not in excluded:
                child.bind("<Enter>", on_enter, add="+")
                child.bind("<Leave>", on_leave, add="+")

    def _bind_drag_tree(
        self,
        widget,
        context: str,
        pokemon: Any,
        *,
        exclude: set[Any] | None = None,
    ) -> None:
        excluded = exclude or set()
        if widget in excluded:
            return
        widget.bind(
            "<ButtonPress-1>",
            lambda event, c=context, p=pokemon: self._begin_drag(event, c, p),
            add="+",
        )
        widget.bind("<B1-Motion>", self._move_drag, add="+")
        widget.bind("<ButtonRelease-1>", self._end_drag, add="+")
        for child in widget.winfo_children():
            self._bind_drag_tree(child, context, pokemon, exclude=excluded)
