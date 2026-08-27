from __future__ import annotations

from collections.abc import Mapping

# Alpha.43: existe un único orden canónico para interfaz, drafteos, atajos y
# los seis marcadores físicos del Pokémon. El número visible para el usuario es
# simplemente índice + 1: Líbero=1, Asesino=2, Mago=3, Tanque=4, Prisma=5,
# Support=6.
ROLE_ORDER: tuple[str, ...] = (
    "Líbero", "Asesino", "Mago", "Tanque", "Prisma", "Support",
)

ROLE_TO_KEY: dict[str, str] = {
    "Líbero": "libero",
    "Asesino": "asesino",
    "Mago": "mago",
    "Tanque": "tanque",
    "Prisma": "prisma",
    "Support": "support",
}

# Los símbolos corresponden al orden físico de las seis marcas de Pokémon:
# círculo, triángulo, cuadrado, corazón, estrella y rombo. Al reordenar roles,
# también cambia qué símbolo representa a cada rol.
ROLE_SYMBOLS: dict[str, str] = {
    "Líbero": "●",
    "Asesino": "▲",
    "Mago": "■",
    "Tanque": "♥",
    "Prisma": "★",
    "Support": "◆",
    "SIN ROL": "",
}

ROLE_OPTIONS: tuple[tuple[str, str], ...] = tuple(
    (role, ROLE_SYMBOLS[role]) for role in ROLE_ORDER
) + (("SIN ROL", "—"),)

# Orden físico NUEVO. Debe ser idéntico a ROLE_ORDER.
MARKING_ROLE_ORDER: tuple[str, ...] = ROLE_ORDER
ROLE_TO_MARKING: dict[str, int] = {role: index for index, role in enumerate(MARKING_ROLE_ORDER)}
ROLE_TO_MARKING["SIN ROL"] = -1

# Layout usado hasta alpha.42. Se conserva exclusivamente para migrar Runs ya
# existentes sin convertir silenciosamente un Tanque en Asesino, etc.
LEGACY_MARKING_ROLE_ORDER: tuple[str, ...] = (
    "Líbero", "Tanque", "Asesino", "Mago", "Support", "Prisma",
)


def role_from_markings(markings, *, layout: int = 2) -> tuple[str, str]:
    selected = [index for index, marked in enumerate(markings[:6]) if bool(marked)]
    if len(selected) != 1:
        return "SIN ROL", ""
    order = MARKING_ROLE_ORDER if int(layout) >= 2 else LEGACY_MARKING_ROLE_ORDER
    role = order[selected[0]]
    return role, ROLE_SYMBOLS[role]


def canonical_role(role: str) -> str:
    """Normaliza nombres históricos sin exponer Paladín en la interfaz nueva."""
    value = str(role or "SIN ROL").strip()
    if value.casefold() in {"paladín", "paladin"}:
        return "Prisma"
    if value.casefold() in {"soporte"}:
        return "Support"
    if value.casefold() in {"libero", "líbero"}:
        return "Líbero"
    return value


def allowed_status_move_ids(
    role: str,
    pools: Mapping[str, list[int]],
    damage_classes: Mapping[int, str],
    speed_status_moves: set[int],
) -> set[int] | None:
    """Movimientos de estado compatibles con un rol.

    ``None`` significa sin restricción (Líbero). Para Tanque y Prisma, la regla
    antigua que permitía Velocidad globalmente deja de aplicarse: un boost de
    Velocidad solo es legal si el propio movimiento también cumple su defensa
    obligatoria (p. ej. Danza Triunfal / Danza Aleteo).
    """
    role = canonical_role(role)
    if role == "Líbero":
        return None
    if role in {"SIN ROL", ""}:
        return set()

    if role == "Support":
        all_status = {
            int(move_id) for move_id, category in damage_classes.items()
            if category == "status"
        }
        self_boosts = {int(mid) for mid in pools.get("global_self_boosts", [])}
        forbidden_boosts = self_boosts.difference(speed_status_moves)
        protections = {int(mid) for mid in pools.get("tanque_proteccion", [])}
        return all_status.difference(forbidden_boosts).difference(protections)

    role_pool_keys: dict[str, tuple[str, ...]] = {
        "Asesino": ("asesino_bajar_defensa", "asesino_subir_ataque"),
        "Mago": ("mago_bajar_defensa_esp", "mago_subir_ataque_esp"),
        "Tanque": (
            "tanque_proteccion",
            "tanque_subir_defensa_fisica",
            "defensa_recuperacion_pasiva",
        ),
        "Prisma": (
            "prisma_problemas_estado",
            "prisma_subir_defensa_especial",
            "defensa_recuperacion_pasiva",
        ),
    }
    allowed: set[int] = set()
    for pool_key in role_pool_keys.get(role, ()):  # rol desconocido -> vacío
        allowed.update(int(mid) for mid in pools.get(pool_key, []))

    # Líbero no lo necesita; Asesino/Mago/Support conservan exactamente la
    # excepción previa de Velocidad. Tanque/Prisma quedan sujetos a su defensa.
    if role in {"Asesino", "Mago"}:
        allowed.update(int(mid) for mid in speed_status_moves)
        # Sustituto (#164) es una herramienta táctica permitida para ambos
        # atacantes. Se añade solo a la validación del rol: NO entra en ningún
        # pool/categoría de drafteo, por lo que nunca aparece como categoría
        # nueva al generar un drafteo.
        allowed.add(164)
    return allowed


def damage_move_issue_reason(
    role: str,
    damage_class: str,
    move_id: int,
    self_healing_damage_moves: set[int],
) -> str:
    """Devuelve el motivo de incompatibilidad para un movimiento de daño."""
    role = canonical_role(role)
    damage_class = str(damage_class)
    move_id = int(move_id or 0)

    if role == "Asesino" and damage_class != "physical":
        return "El Asesino solo puede usar movimientos de daño físico"
    if role == "Mago" and damage_class != "special":
        return "El Mago solo puede usar movimientos de daño especial"
    if role in {"Tanque", "Prisma"} and move_id in self_healing_damage_moves:
        return f"{role} no puede recuperar PS mediante movimientos de daño"
    return ""


def engine_role_name(role: str, *, legacy_engine: bool = False) -> str:
    """Nombre enviado al SaveEngine.

    El binario empaquetado con alpha.42 todavía traduce nombres usando el layout
    físico antiguo. Mientras no se haya recompilado con ``preparar_motor.bat``
    alpha.43 traduce el rol nuevo al nombre histórico que apunta al MISMO bit.
    Un motor recompilado alpha.43 acepta directamente los nombres nuevos.
    """
    role = canonical_role(role)
    if not legacy_engine:
        return role
    if role == "SIN ROL":
        return role
    try:
        selected = ROLE_TO_MARKING[role]
    except KeyError:
        return role
    legacy_engine_names = ("Líbero", "Tanque", "Asesino", "Mago", "Support", "Paladín")
    return legacy_engine_names[selected]
