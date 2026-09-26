from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import customtkinter as ctk
from PIL import Image

from app.config import GOLD, MUTED, PANEL, PANEL_ALT, SUCCESS, TEXT


class IntegratedFormatHelpView:
    """Guía del formato renderizada dentro de la superficie principal.

    Es un componente puramente visual: recibe el contenido de roles y callbacks
    de navegación, sin acceder a la Run ni a servicios de juego.
    """

    def __init__(
        self,
        master,
        *,
        logo_path: Path,
        role_order: tuple[str, ...],
        role_guide: Mapping[str, Mapping[str, str]],
        global_role_note: str,
        role_symbols: Mapping[str, str],
        on_back: Callable[[], None],
        on_open_team: Callable[[], None],
        on_open_moves: Callable[[], None],
    ) -> None:
        self.images: list[Any] = []
        self.frame = ctk.CTkFrame(master, fg_color="transparent")
        self.frame.grid(row=0, column=0, sticky="nsew")
        self.frame.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(self.frame, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        top.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(
            top,
            text="‹  VOLVER A AYUDA",
            command=on_back,
            width=165,
            height=38,
            fg_color="transparent",
            hover_color=PANEL_ALT,
            border_width=1,
            border_color=GOLD,
            text_color=GOLD,
            font=ctk.CTkFont("Segoe UI", 12, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            top,
            text="GUÍA DEL FORMATO",
            text_color=MUTED,
            font=ctk.CTkFont("Segoe UI", 12, "bold"),
        ).grid(row=0, column=1, sticky="e")

        hero = ctk.CTkFrame(
            self.frame,
            fg_color="#17140E",
            corner_radius=18,
            border_width=1,
            border_color=GOLD,
        )
        hero.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        hero.grid_columnconfigure(1, weight=1)
        if logo_path.exists():
            try:
                source = Image.open(logo_path).convert("RGBA")
                source.thumbnail((104, 104), Image.Resampling.LANCZOS)
                logo = ctk.CTkImage(
                    light_image=source, dark_image=source, size=source.size,
                )
                self.images.append(logo)
                ctk.CTkLabel(hero, text="", image=logo).grid(
                    row=0, column=0, rowspan=3, padx=(24, 19), pady=20,
                )
            except Exception:
                pass
        ctk.CTkLabel(
            hero,
            text="POKÉMON ROLERUN",
            text_color=GOLD,
            font=ctk.CTkFont("Segoe UI", 28, "bold"),
        ).grid(row=0, column=1, sticky="sw", padx=(0, 22), pady=(22, 2))
        ctk.CTkLabel(
            hero,
            text="Un Nuzlocke más dinámico, con menos paradas y menos azar",
            text_color=TEXT,
            font=ctk.CTkFont("Segoe UI", 18, "bold"),
        ).grid(row=1, column=1, sticky="w", padx=(0, 22))
        ctk.CTkLabel(
            hero,
            text=(
                "RoleRun nace para arreglar dos cosas de los Nuzlockes clásicos: el "
                "backtracking constante a curar al Centro Pokémon, y que el reto "
                "dependa demasiado de qué movimientos te toquen al azar -a veces te "
                "sale un Pokémon tan roto que la partida deja de dar miedo-. La "
                "solución son los roles: cada uno de tus seis Pokémon tiene un rol, "
                "y el rol decide qué movimientos puede aprender, un conjunto ya "
                "pensado para no romper el reto. Ninguno queda libre: ni siquiera "
                "un Pokémon muy fuerte se sale de lo que su rol permite. El Líbero "
                "es el comodín: imita el rol que elijas de los otros cinco, así "
                "que puedes llevar un rol repetido."
            ),
            text_color=MUTED,
            wraplength=760,
            justify="left",
            font=ctk.CTkFont("Segoe UI", 13),
        ).grid(row=2, column=1, sticky="nw", padx=(0, 22), pady=(5, 22))

        cards = ctk.CTkFrame(self.frame, fg_color="transparent")
        cards.grid(row=2, column=0, sticky="ew")
        cards.grid_columnconfigure((0, 1, 2), weight=1, uniform="format_intro")
        concepts = (
            ("SEIS ROLES", "Cada Pokémon aprende solo lo que su rol permite. El Líbero imita el rol que elijas de los otros cinco, así que puedes repetir uno."),
            ("SUPERVIVENCIA", "Como en cualquier Nuzlocke: una captura por ruta, y un Pokémon debilitado se va al Cementerio para siempre."),
            ("10 VIDAS", "Llegan a 0 y la Run se pierde. Suben o bajan según cómo termines cada combate de seis Pokémon -detalle más abajo."),
        )
        for column, (title, detail) in enumerate(concepts):
            card = ctk.CTkFrame(cards, fg_color=PANEL, corner_radius=14, border_width=1, border_color="#383838")
            card.grid(row=0, column=column, sticky="nsew", padx=5)
            ctk.CTkLabel(
                card, text=title, text_color=GOLD,
                font=ctk.CTkFont("Segoe UI", 15, "bold"),
            ).pack(anchor="w", padx=15, pady=(14, 4))
            ctk.CTkLabel(
                card, text=detail, text_color=MUTED, wraplength=285,
                justify="left", font=ctk.CTkFont("Segoe UI", 12),
            ).pack(anchor="w", fill="x", padx=15, pady=(0, 15))

        cycle = ctk.CTkFrame(self.frame, fg_color="#121212", corner_radius=14)
        cycle.grid(row=3, column=0, sticky="ew", pady=14)
        for column, (title, subtitle) in enumerate((
            ("CAPTURA", "Construye"),
            ("ASIGNA ROL", "Especializa"),
            ("COMBATE", "Sobrevive"),
            ("DRAFTEA", "Mejora"),
            ("REORGANIZA", "Adáptate"),
        )):
            cycle.grid_columnconfigure(column, weight=1)
            cell = ctk.CTkFrame(cycle, fg_color="transparent")
            cell.grid(row=0, column=column, sticky="nsew", padx=4, pady=12)
            ctk.CTkLabel(
                cell, text=title, text_color=TEXT,
                font=ctk.CTkFont("Segoe UI", 12, "bold"),
            ).pack()
            ctk.CTkLabel(
                cell, text=subtitle, text_color=MUTED,
                font=ctk.CTkFont("Segoe UI", 11),
            ).pack(pady=(2, 0))

        def bullet_card(row: int, title: str, bullets: list[str]) -> None:
            card = ctk.CTkFrame(
                self.frame, fg_color=PANEL, corner_radius=16,
                border_width=1, border_color="#383838",
            )
            card.grid(row=row, column=0, sticky="ew", pady=8)
            ctk.CTkLabel(
                card, text=title, text_color=GOLD,
                font=ctk.CTkFont("Segoe UI", 18, "bold"),
            ).pack(anchor="w", padx=20, pady=(16, 8))
            for index, bullet in enumerate(bullets):
                line = ctk.CTkFrame(card, fg_color="transparent")
                line.pack(fill="x", padx=20, pady=(3, 15 if index == len(bullets) - 1 else 3))
                ctk.CTkLabel(
                    line, text="◆", text_color=GOLD, width=22,
                    font=ctk.CTkFont("Segoe UI Symbol", 12, "bold"),
                ).pack(side="left")
                ctk.CTkLabel(
                    line, text=bullet, text_color=TEXT, anchor="w",
                    wraplength=880, justify="left",
                    font=ctk.CTkFont("Segoe UI", 13),
                ).pack(side="left", fill="x", expand=True)

        # Números concretos -pedido del usuario 09-09-2026, dictados por él
        # mismo: son la regla real de su serie, no una aproximación genérica
        # de "Nuzlocke con vidas". No inventar otros valores aquí.
        bullet_card(4, "LAS VIDAS, EN NÚMEROS", [
            "Empiezas con 10 vidas. Si llegan a 0, la Run está perdida.",
            "Lo que mueve las vidas es un combate de seis Pokémon -un líder de gimnasio, el Alto Mando, un rival importante-, no cualquier combate suelto.",
            "Si superas uno de esos combates sin perder ningún Pokémon, sumas una vida. Si pierdes Pokémon en él, restas una vida por cada uno perdido en ESE combate.",
            "Superar un combate de seis Pokémon, pierdas o no vidas en él, también te da un drafteo.",
            "Cada vez que entras en un combate contra un líder de gimnasio, ganas una curación.",
            "Completar la Run es derrotar al Campeón de la Liga. Un Pokémon debilitado se va al Cementerio para siempre: no vuelve a estar disponible en esta Run.",
        ])
        ctk.CTkLabel(
            self.frame,
            text="LOS SEIS ROLES",
            text_color=TEXT,
            font=ctk.CTkFont("Segoe UI", 20, "bold"),
        ).grid(row=5, column=0, sticky="w", pady=(5, 9))
        role_grid = ctk.CTkFrame(self.frame, fg_color="transparent")
        role_grid.grid(row=6, column=0, sticky="ew")
        role_grid.grid_columnconfigure((0, 1), weight=1, uniform="format_roles")
        for index, role in enumerate(role_order):
            entry = role_guide[role]
            card = ctk.CTkFrame(
                role_grid, fg_color=PANEL, corner_radius=14,
                border_width=1, border_color="#383838",
            )
            card.grid(row=index // 2, column=index % 2, sticky="nsew", padx=5, pady=5)
            ctk.CTkLabel(
                card,
                text=f"{role_symbols.get(role, '')}  {role.upper()}".strip(),
                text_color=GOLD,
                font=ctk.CTkFont("Segoe UI Symbol", 15, "bold"),
            ).pack(anchor="w", padx=15, pady=(13, 3))
            ctk.CTkLabel(
                card,
                text=entry["summary"],
                text_color=TEXT,
                wraplength=470,
                justify="left",
                font=ctk.CTkFont("Segoe UI", 12, "bold"),
            ).pack(anchor="w", fill="x", padx=15)
            ctk.CTkLabel(
                card,
                text=f"Permitido: {entry['allowed']}\nLímites: {entry['limits']}",
                text_color=MUTED,
                wraplength=470,
                justify="left",
                font=ctk.CTkFont("Segoe UI", 12),
            ).pack(anchor="w", fill="x", padx=15, pady=(5, 13))

        note = ctk.CTkFrame(self.frame, fg_color="#211B11", corner_radius=12, border_width=1, border_color=GOLD)
        note.grid(row=7, column=0, sticky="ew", pady=(12, 8))
        ctk.CTkLabel(
            note,
            text=global_role_note,
            text_color=TEXT,
            wraplength=1000,
            justify="left",
            font=ctk.CTkFont("Segoe UI", 12),
        ).pack(fill="x", padx=16, pady=13)

        bullet_card(8, "MODO DUALROLE (OPCIONAL) · el equivalente a un DualLocke", [
            "Dos jugadores, cada uno con su propia Run, se enfrentan al mejor de tres justo al conseguir la 3ª medalla, justo al conseguir la 6ª medalla y justo antes de entrar a la Liga.",
            "Cada mejor-de-tres reparte puntos: 2-1 da 2 puntos a quien gana y 1 a quien pierde; 2-0 da 2 y 0.",
            "Superar la Liga también da puntos: tantos como Pokémon te queden vivos al terminarla.",
            "Si te haces wipe en la Liga, esa liga te da 0 puntos; con vidas todavía disponibles puedes reintentarla, pero si el wipe te deja a 0 vidas, pierdes el DualRole.",
            "RoleRun Manager no lleva la cuenta de estos puntos por ti -cada jugador gestiona su propia Run por separado-; el DualRole es una forma de jugar, no una función del programa.",
        ])

        actions = ctk.CTkFrame(self.frame, fg_color="transparent")
        actions.grid(row=9, column=0, sticky="ew", pady=(8, 20))
        ctk.CTkButton(
            actions, text="ABRIR EQUIPO Y PC", command=on_open_team,
            height=42, fg_color=GOLD, hover_color="#D3AF70", text_color="#111111",
            font=ctk.CTkFont("Segoe UI", 12, "bold"),
        ).pack(side="left", fill="x", expand=True, padx=(0, 5))
        ctk.CTkButton(
            actions, text="CONSULTA DE MOVIMIENTOS", command=on_open_moves,
            height=42, fg_color="transparent", hover_color=PANEL_ALT,
            border_width=1, border_color=SUCCESS, text_color=SUCCESS,
            font=ctk.CTkFont("Segoe UI", 12, "bold"),
        ).pack(side="left", fill="x", expand=True, padx=(5, 0))

