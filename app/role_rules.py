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


# Decidido por el usuario el 2026-09-03: un movimiento de estado que combina
# Velocidad con OTRO stat solo es válido para el rol cuyo propio stat incluya
# — el mismo criterio que ya usan las pools curadas de cada rol (Corpulencia
# sube Ataque y Defensa: solo está en tanque_subir_defensa_fisica, nunca en
# asesino_subir_ataque; Paz Mental sube At. Esp. y Def. Esp.: solo está en
# prisma_subir_defensa_especial, nunca en mago_subir_ataque_esp). Que el
# movimiento suba de propina el otro stat del mismo bloque no lo invalida
# (Danza Aleteo sube At. Esp. y Def. Esp.: vale para Prisma exactamente
# igual que Paz Mental, nunca para Mago exactamente igual que Paz Mental
# tampoco). Asesino/Tanque no tienen ningún movimiento así en la lista de
# Velocidad; si se añade uno nuevo, va aquí.
_SPEED_PLUS_OWN_STAT_STATUS_MOVES: dict[str, tuple[int, ...]] = {
    "Asesino": (349, 508),  # Danza Dragón, Cambio de Marcha: Ataque + Velocidad
    "Prisma": (483, 601),   # Danza Aleteo, Geocontrol: At. Esp. + Def. Esp. + Velocidad
}

# Excluidos de la excepción general de Velocidad para cualquier rol de
# combate: bajan más de un stat rival a la vez (Trampa Venenosa: Ataque,
# At. Esp. y Velocidad — no es un autoboost ni "solo Velocidad"; ya vale
# para Support por su propia regla de "baja cualquier stat rival"), combinan
# Velocidad con un stat que solo encaja con un rol concreto (repartidos
# arriba), envenenan sin dañar directamente (decidido por el usuario el
# 2026-09-03: eso solo lo pueden hacer Prisma, por su pool
# ``problemas_estado`` donde Hilo Venenoso ya está, Support y Líbero), suben
# los cinco stats de golpe (Novena Potencia, Bastión Final, Estruendo
# Escama: la Velocidad ahí no es más protagonista que ningún otro stat, no
# encaja como "Velocidad + el stat propio del rol"), o cuyo efecto
# PRINCIPAL no es la Velocidad sino otra cosa que de paso también la afecta
# — Red Viscosa (confirmado por el usuario el 2026-09-03: es un hazard,
# igual que Giro Rápido es daño físico aunque de paso suba la Velocidad; ya
# está en ``support_hazards``, donde le corresponde).
_SPEED_STATUS_MOVES_EXCLUDED_FROM_ALL_ROLES = frozenset({
    564,  # Red Viscosa: hazard, no un movimiento de Velocidad
    599,  # Trampa Venenosa
    672,  # Hilo Venenoso: envenena sin dañar, solo Prisma/Support/Líbero
    702,  # Novena Potencia: los cinco stats a la vez
    748,  # Bastión Final: los cinco stats a la vez
    775,  # Estruendo Escama: los cinco stats a la vez
    *_SPEED_PLUS_OWN_STAT_STATUS_MOVES["Asesino"],
    *_SPEED_PLUS_OWN_STAT_STATUS_MOVES["Prisma"],
})

# Decidido por el usuario el 2026-09-04: ningún Pokémon de RoleRun, sea cual
# sea su rol —incluido Líbero, que normalmente no tiene restricciones—,
# puede quedarse con un movimiento que suba su propia evasión (cláusula de
# evasión estándar del competitivo). Doble Equipo y Reducción son los únicos
# movimientos de la serie principal cuyo efecto es exactamente ese; los que
# solo bajan la precisión del rival (Ataque Arena, Pantalla de Humo,
# Kinético, Destello, Bofetón Lodo) son un mecanismo distinto y no cuentan
# aquí.
EVASION_MOVE_IDS: frozenset[int] = frozenset({104, 107})


def is_evasion_move(move_id: int) -> bool:
    return int(move_id) in EVASION_MOVE_IDS


# Support recibe casi cualquier movimiento de estado salvo autoboosts (con la
# misma excepción de Velocidad, pero solo la parte que de verdad es
# "Velocidad" — los hazards y los boosts de los cinco stats no cuentan como
# excepción aquí tampoco) y protecciones.
def _pure_speed_status_moves(speed_status_moves, damage_classes) -> set[int]:
    return {
        int(mid) for mid in speed_status_moves
        if damage_classes.get(int(mid)) == "status"
        and int(mid) not in _SPEED_STATUS_MOVES_EXCLUDED_FROM_ALL_ROLES
    }


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
        forbidden_boosts = self_boosts.difference(_pure_speed_status_moves(speed_status_moves, damage_classes))
        protections = {int(mid) for mid in pools.get("tanque_proteccion", [])}
        return all_status.difference(forbidden_boosts).difference(protections).difference(EVASION_MOVE_IDS)

    role_pool_keys: dict[str, tuple[str, ...]] = {
        "Asesino": ("asesino_bajar_defensa", "asesino_subir_ataque"),
        "Mago": ("mago_bajar_defensa_esp", "mago_subir_ataque_esp"),
        "Tanque": (
            "tanque_proteccion",
            "tanque_bajar_ataque",
            "tanque_subir_defensa_fisica",
            "defensa_recuperacion_pasiva",
        ),
        "Prisma": (
            "problemas_estado",
            "prisma_bajar_ataque_esp",
            "prisma_subir_defensa_especial",
            "defensa_recuperacion_pasiva",
        ),
    }
    allowed: set[int] = set()
    for pool_key in role_pool_keys.get(role, ()):  # rol desconocido -> vacío
        allowed.update(int(mid) for mid in pools.get(pool_key, []))

    # Líbero no lo necesita. El resto de roles de combate comparten los
    # movimientos de estado que solo afectan a la Velocidad — decidido por el
    # usuario el 2026-09-03: "siempre que suban velocidad o velocidad y un
    # stat que se puedan boostear ellos, son válidos". Los que combinan
    # Velocidad con otro stat se reparten arriba, por rol.
    if role in {"Asesino", "Mago", "Tanque", "Prisma"}:
        # ``speed_status_moves`` demostró el 2026-09-03 contener 21 de 41
        # movimientos que en realidad son de daño (físico o especial) —
        # Giro Rápido y Restricción entre ellos, ambos ofrecidos de verdad a
        # un Houndoom Mago por la sustitución de aprendizajes. Esta excepción
        # es solo para movimientos de ESTADO cuyo efecto PRINCIPAL es la
        # Velocidad; sin el filtro de clase colaba movimientos de daño de la
        # clase equivocada, y sin la lista de exclusión colaban movimientos
        # de estado cuyo efecto principal es otra cosa (Red Viscosa: hazard).
        allowed.update(_pure_speed_status_moves(speed_status_moves, damage_classes))
        allowed.update(_SPEED_PLUS_OWN_STAT_STATUS_MOVES.get(role, ()))
    if role in {"Asesino", "Mago"}:
        # Sustituto (#164) es una herramienta táctica permitida para ambos
        # atacantes. Se añade solo a la validación del rol: NO entra en ningún
        # pool/categoría de drafteo, por lo que nunca aparece como categoría
        # nueva al generar un drafteo.
        allowed.add(164)
    return allowed.difference(EVASION_MOVE_IDS)


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
