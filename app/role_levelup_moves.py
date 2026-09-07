"""Sustituir por rol una entrada de aprendizaje por nivel: reglas puras.

Extraído de ``app/oras_levelup_moves.py`` el 2026-09-03 al portar la función a
BDSP: estas reglas —qué exige cada rol, cómo se elige el sustituto— no
dependen de ORAS ni de ningún formato de tabla concreto. Operan sobre pares
abstractos ``(movimiento, nivel, clave)``, donde ``clave`` es lo que cada
juego use para identificar la entrada después (un offset de bytes en un GARC
para ORAS, un índice de lista para BDSP): esta función nunca la interpreta,
solo la devuelve tal cual en el resultado.

Compartir este módulo evita que las reglas de rol diverjan entre juegos: si
mañana cambia qué exige Support o qué pool usa Tanque, cambia aquí una vez y
todos los juegos que ya lo usen quedan al día solos.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from .role_rules import (
    EVASION_MOVE_IDS, allowed_status_move_ids, canonical_role,
    damage_move_issue_reason, is_evasion_move,
)

# Pools de daño por rol, en las mismas claves que ``data/moves.json`` y con el
# mismo criterio que ``role_rules.damage_move_issue_reason``: Asesino exige
# físico, Mago exige especial, Tanque/Prisma aceptan cualquiera salvo
# recuperación de PS por daño, Support y Líbero no restringen nada.
_DAMAGE_POOL_KEYS: dict[str, dict[str, str]] = {
    "Asesino": {"physical": "extra_ataque_fisico"},
    "Mago": {"special": "extra_ataque_especial"},
    "Tanque": {"physical": "defensa_ataque_fisico", "special": "defensa_ataque_especial"},
    "Prisma": {"physical": "defensa_ataque_fisico", "special": "defensa_ataque_especial"},
}

# Roles cuya tabla de aprendizajes nunca hace falta tocar: SIN ROL no debe
# recibir sustituciones (no hay nadie a quien priorizar). Ver
# rolerun-viabilidad-aprendizajes-por-rol para el porqué. Líbero SALIÓ de
# esta lista el 2026-09-04: aunque sigue sin tener restricciones de rol,
# la cláusula de evasión es absoluta y también le aplica a él.
_ROLES_SIN_SUSTITUCION = {"SIN ROL", ""}


def _damage_pool_for_role(
    role: str,
    original_damage_class: str,
    pools: Mapping[str, list[int]],
    self_healing_damage_moves: set[int],
) -> set[int] | None:
    """``None`` significa "sin restricción de daño" (Líbero y Support).

    Asesino y Mago exigen una categoría fija (física/especial) sin importar
    la del movimiento que sustituyen; Tanque y Prisma conservan la categoría
    original y solo evitan la recuperación de PS por daño.
    """
    if role in {"Líbero", "Support"}:
        return None
    if role == "Asesino":
        target_class = "physical"
    elif role == "Mago":
        target_class = "special"
    else:
        target_class = original_damage_class
    pool_key = _DAMAGE_POOL_KEYS.get(role, {}).get(target_class)
    if pool_key is None:
        return set()
    pool = {int(move_id) for move_id in pools.get(pool_key, [])}
    if role in {"Tanque", "Prisma"}:
        pool -= {int(move_id) for move_id in self_healing_damage_moves}
    return pool


def _needs_substitute(
    role: str,
    move_id: int,
    damage_class: str,
    *,
    pools: Mapping[str, list[int]],
    damage_classes: Mapping[int, str],
    speed_status_moves: set[int],
    self_healing_damage_moves: set[int],
) -> bool:
    # Absoluto (2026-09-04): ningún rol, ni siquiera Líbero, puede quedarse
    # con un movimiento que suba su propia evasión.
    if is_evasion_move(move_id):
        return True
    if damage_class == "status":
        allowed = allowed_status_move_ids(role, pools, damage_classes, speed_status_moves)
        return allowed is not None and int(move_id) not in allowed
    if damage_class in {"physical", "special"}:
        return bool(damage_move_issue_reason(role, damage_class, int(move_id), self_healing_damage_moves))
    # Categoría desconocida (movimiento sin clasificar): no se toca, por
    # seguridad — nunca se sustituye sin poder validar la regla del rol.
    return False


def _pick_substitute(candidates: set[int], *, exclude: set[int], seed_parts: tuple[object, ...]) -> int | None:
    pool = sorted(candidates - exclude) or sorted(candidates)
    if not pool:
        return None
    digest = hashlib.sha256("|".join(str(part) for part in seed_parts).encode("utf-8")).digest()
    index = int.from_bytes(digest[:8], "little") % len(pool)
    return pool[index]


def compute_species_patch(
    entries: tuple[tuple[int, int, int], ...],
    role: str,
    *,
    species_id: int,
    pools: Mapping[str, list[int]],
    damage_classes: Mapping[int, str],
    speed_status_moves: set[int],
    self_healing_damage_moves: set[int],
    usable_move_ids: set[int] | None = None,
) -> dict[int, int]:
    """``{clave: nuevo_movimiento}`` para las entradas de ``entries`` que no
    encajan con ``role``. Vacío si no hay nadie a quien aplicárselo (SIN
    ROL). Para Líbero, que normalmente no tiene restricciones, solo puede
    haber sustituciones por la cláusula de evasión (absoluta, 2026-09-04).

    Cada entrada de ``entries`` es ``(movimiento, nivel, clave)`` — la
    ``clave`` es opaca para esta función: un offset de bytes, un índice de
    lista, lo que le sirva a quien llama para aplicar el resultado después.

    Determinista: la misma especie, rol, nivel y CLAVE de entrada siempre
    eligen el mismo sustituto, así que reiniciar sin guardar y volver a subir
    de nivel con el mismo rol da el mismo resultado — y, crucialmente,
    también da el mismo resultado sin importar si a esta función se le pasó
    la tabla completa de la especie (como hace el parche proactivo de BDSP,
    Enfoque A) o solo el subconjunto recién cruzado (como hace la
    sustitución posterior de Enfoque B): la semilla usa ``clave``, que es
    estable para una entrada dada, en vez de su posición dentro de
    ``entries`` -que cambiaría según qué subconjunto se pasara-. Antes de
    este cambio (2026-09-03) ambos enfoques podían elegir sustitutos
    distintos para la MISMA entrada, lo que rompía tanto la detección de
    "ya resuelto por el parche proactivo" como el historial de recuerda-
    movimientos, demostrado al no poder reproducir en un cálculo aislado el
    movimiento que el juego mostró de verdad.
    """
    role = canonical_role(role)
    if role in _ROLES_SIN_SUSTITUCION:
        return {}
    already_used = {int(move_id) for move_id, _level, _clave in entries}
    patch: dict[int, int] = {}
    for move_id, level, clave in entries:
        damage_class = damage_classes.get(int(move_id), "unknown")
        if not _needs_substitute(
            role, move_id, damage_class,
            pools=pools, damage_classes=damage_classes,
            speed_status_moves=speed_status_moves,
            self_healing_damage_moves=self_healing_damage_moves,
        ):
            continue
        if damage_class == "status":
            if role == "Líbero":
                # allowed_status_move_ids devuelve None para Líbero (sin
                # restricción alguna) — aquí hace falta un pool concreto
                # para poder elegir un sustituto de la evasión, ya que es
                # el único caso en que Líbero SÍ necesita uno.
                candidates = {
                    int(mid) for mid, category in damage_classes.items()
                    if category == "status"
                } - EVASION_MOVE_IDS
            else:
                candidates = allowed_status_move_ids(role, pools, damage_classes, speed_status_moves) or set()
        else:
            candidates = _damage_pool_for_role(role, damage_class, pools, self_healing_damage_moves) or set()
        if usable_move_ids is not None:
            candidates = candidates & usable_move_ids
        exclude = already_used | set(patch.values())
        substitute = _pick_substitute(
            candidates, exclude=exclude,
            seed_parts=(species_id, role, level, clave, move_id),
        )
        if substitute is None or substitute == move_id:
            continue
        patch[clave] = substitute
    return patch


def compute_move_substitute(
    move_id: int,
    role: str,
    *,
    species_id: int,
    level: int,
    pools: Mapping[str, list[int]],
    damage_classes: Mapping[int, str],
    speed_status_moves: set[int],
    self_healing_damage_moves: set[int],
    exclude: set[int] = frozenset(),
    usable_move_ids: set[int] | None = None,
) -> int | None:
    """Sustituto para UN movimiento suelto que no encaje con ``role``.

    2026-09-04, USUM: a diferencia de ORAS (relee su tabla sin caché en
    cada petición del juego), USUM puede enseñar un movimiento que ya no
    es ni el vainilla ni el sustituto recién calculado — el que tenía
    cacheado de ANTES de un cambio de rol reciente. La red de seguridad
    detecta esto observando qué movimiento apareció de verdad en el hueco
    (en vez de predecir de antemano cuál sería), y usa esta función para
    decidir su sustituto sobre la marcha — mismo criterio de rol que
    :func:`compute_species_patch`, pero sin depender de que ``move_id``
    forme parte de la tabla de aprendizajes conocida de la especie.

    ``None`` si el movimiento ya es compatible con ``role`` (nada que
    hacer) o si no hay ningún candidato disponible.
    """
    role = canonical_role(role)
    if role in _ROLES_SIN_SUSTITUCION:
        return None
    damage_class = damage_classes.get(int(move_id), "unknown")
    if not _needs_substitute(
        role, move_id, damage_class,
        pools=pools, damage_classes=damage_classes,
        speed_status_moves=speed_status_moves,
        self_healing_damage_moves=self_healing_damage_moves,
    ):
        return None
    if damage_class == "status":
        if role == "Líbero":
            candidates = {
                int(mid) for mid, category in damage_classes.items()
                if category == "status"
            } - EVASION_MOVE_IDS
        else:
            candidates = allowed_status_move_ids(role, pools, damage_classes, speed_status_moves) or set()
    else:
        candidates = _damage_pool_for_role(role, damage_class, pools, self_healing_damage_moves) or set()
    if usable_move_ids is not None:
        candidates = candidates & usable_move_ids
    substitute = _pick_substitute(
        candidates, exclude=set(exclude) | {int(move_id)},
        seed_parts=(species_id, role, level, "backup", move_id),
    )
    if substitute is None or substitute == move_id:
        return None
    return substitute
