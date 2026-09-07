from __future__ import annotations


DEFAULT_PAGE = "team"

# Los iconos se conservan del lenguaje visual original. Los destinos
# secundarios siguen existiendo, pero ya no compiten en la barra principal.
PRIMARY_NAVIGATION: tuple[tuple[str, str], ...] = (
    ("team", "♟  EQUIPO Y PC"),
    ("tms", "▣  MOVIMIENTOS"),
    ("drafts", "◈  DRAFTEOS"),
    ("settings", "⚙  CONFIGURACIÓN"),
    ("help", "?  AYUDA"),
)

SECONDARY_GROUPS: dict[str, tuple[str, ...]] = {
    "team": ("team", "pc"),
    "tms": ("tms", "moves"),
    "settings": ("settings", "history"),
    "help": ("help",),
    "drafts": ("drafts",),
}


def normalize_navigation_target(page: str) -> str:
    target = str(page or "").strip().casefold()
    if target == "dashboard":
        return DEFAULT_PAGE
    valid = {child for children in SECONDARY_GROUPS.values() for child in children}
    return target if target in valid else DEFAULT_PAGE


def primary_page_for(page: str) -> str:
    target = normalize_navigation_target(page)
    for primary, children in SECONDARY_GROUPS.items():
        if target in children:
            return primary
    return DEFAULT_PAGE
