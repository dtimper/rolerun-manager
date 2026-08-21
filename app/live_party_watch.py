from __future__ import annotations

from dataclasses import dataclass

from .oras_live import live_party_fingerprint
from .save_engine_client import SaveGameData, SavePokemon


@dataclass(frozen=True, slots=True)
class LivePartyDiff:
    """Resumen de cambios relevantes observados dentro del juego.

    El monitor ignora deliberadamente HP y EXP. El nivel sí forma parte de la
    vista de RoleRun y se toma directamente de la RAM viva de ORAS.
    """

    party_changed: bool = False
    order_changed: bool = False
    roles_changed: bool = False
    moves_changed: bool = False
    levels_changed: bool = False

    @property
    def changed(self) -> bool:
        return (
            self.party_changed or self.order_changed or self.roles_changed
            or self.moves_changed or self.levels_changed
        )

    def label(self) -> str:
        parts: list[str] = []
        if self.party_changed:
            parts.append("equipo")
        elif self.order_changed:
            parts.append("orden")
        if self.roles_changed:
            parts.append("roles")
        if self.moves_changed:
            parts.append("movimientos")
        if self.levels_changed:
            parts.append("nivel")
        return " · ".join(parts) if parts else "sin cambios"


@dataclass(frozen=True, slots=True)
class LiveRoleAssignment:
    """Rol que RoleRun debe asignar a un Pokémon que acaba de entrar al equipo.

    ``current_role`` es la marca que tiene el Pokémon en la RAM de ORAS en ese
    momento. ``new_role`` es el rol que debe quedar escrito tras normalizar el
    cambio realizado desde el propio juego.
    """

    slot: int
    identity: tuple[int, int, int, int]
    current_role: str
    new_role: str
    reason: str


def _identity(pokemon: SavePokemon) -> tuple[int, int, int, int]:
    return (
        int(pokemon.species_id),
        int(pokemon.pid or 0),
        int(pokemon.tid or 0),
        int(pokemon.sid or 0),
    )




@dataclass(frozen=True, slots=True)
class LiveFaintTransition:
    """Transición confirmada de PS positivos a cero en la party viva."""

    slot: int
    identity: tuple[int, int, int, int]
    pokemon: str
    species: str
    role: str
    previous_hp: int
    current_hp: int = 0


def detect_fainted_transitions(
    before: SaveGameData,
    after: SaveGameData,
) -> tuple[LiveFaintTransition, ...]:
    """Detecta únicamente cambios reales ``con vida -> debilitado``.

    No considera como una muerte abrir RoleRun con un Pokémon que ya estaba a
    0 PS. Tampoco depende del slot: la identidad PK6 permite seguir al mismo
    Pokémon aunque ORAS recomponga el orden de la party entre dos capturas.
    """

    previous = {_identity(pokemon): pokemon for pokemon in before.party}
    result: list[LiveFaintTransition] = []
    for pokemon in after.party:
        identity = _identity(pokemon)
        old = previous.get(identity)
        if old is None:
            continue
        old_hp = int(getattr(old, "current_hp", 0) or 0)
        new_hp = int(getattr(pokemon, "current_hp", 0) or 0)
        if old_hp <= 0 or new_hp != 0:
            continue
        result.append(LiveFaintTransition(
            slot=int(pokemon.slot),
            identity=identity,
            pokemon=pokemon.nickname or pokemon.species,
            species=pokemon.species,
            role=str(pokemon.role or "SIN ROL"),
            previous_hp=old_hp,
            current_hp=new_hp,
        ))
    return tuple(result)

def diff_live_party(before: SaveGameData, after: SaveGameData) -> LivePartyDiff:
    """Compara dos capturas sin reaccionar a PS/EXP, pero sí al nivel vivo."""

    before_by_identity = {_identity(p): p for p in before.party}
    after_by_identity = {_identity(p): p for p in after.party}
    before_ids = set(before_by_identity)
    after_ids = set(after_by_identity)

    party_changed = before_ids != after_ids
    order_changed = False
    if not party_changed:
        before_order = [_identity(p) for p in sorted(before.party, key=lambda p: int(p.slot))]
        after_order = [_identity(p) for p in sorted(after.party, key=lambda p: int(p.slot))]
        order_changed = before_order != after_order

    common = before_ids.intersection(after_ids)
    roles_changed = any(
        str(before_by_identity[key].role or "SIN ROL")
        != str(after_by_identity[key].role or "SIN ROL")
        for key in common
    )
    moves_changed = any(
        tuple(int(value or 0) for value in before_by_identity[key].move_ids)
        != tuple(int(value or 0) for value in after_by_identity[key].move_ids)
        for key in common
    )
    levels_changed = any(
        int(getattr(before_by_identity[key], "level", 0) or 0)
        != int(getattr(after_by_identity[key], "level", 0) or 0)
        for key in common
    )

    # Si entra/sale un Pokémon, sus roles, movimientos y nivel también pueden
    # pero la etiqueta "equipo" ya explica ese cambio y evita ruido duplicado.
    return LivePartyDiff(
        party_changed=party_changed,
        order_changed=order_changed,
        roles_changed=roles_changed and not party_changed,
        moves_changed=moves_changed and not party_changed,
        levels_changed=levels_changed and not party_changed,
    )


def infer_incoming_role_assignments(
    before: SaveGameData,
    after: SaveGameData,
    role_order: tuple[str, ...] | list[str],
) -> tuple[LiveRoleAssignment, ...]:
    """Deduce el rol de los Pokémon que entran al equipo desde el propio juego.

    Reglas:
    - sustitución directa con el mismo tamaño de party: el Pokémon entrante hereda
      el rol del Pokémon que sale;
    - si el equipo crece: cada entrante toma el primer rol libre de izquierda a
      derecha;
    - si una sustitución múltiple no puede emparejarse por slot, los salientes y
      entrantes restantes se emparejan por su posición para mantener un resultado
      determinista;
    - nunca se reasignan aquí Pokémon que ya permanecían en el equipo.
    """

    ordered_roles = tuple(str(role) for role in role_order)
    valid_roles = set(ordered_roles)
    before_by_identity = {_identity(p): p for p in before.party}
    after_by_identity = {_identity(p): p for p in after.party}
    before_ids = set(before_by_identity)
    after_ids = set(after_by_identity)

    incoming = [p for p in sorted(after.party, key=lambda p: int(p.slot)) if _identity(p) not in before_ids]
    outgoing = [p for p in sorted(before.party, key=lambda p: int(p.slot)) if _identity(p) not in after_ids]
    if not incoming:
        return ()

    common_ids = before_ids.intersection(after_ids)
    occupied: set[str] = {
        str(after_by_identity[key].role)
        for key in common_ids
        if str(after_by_identity[key].role) in valid_roles
    }

    assigned: dict[tuple[int, int, int, int], tuple[str, str]] = {}
    used_outgoing: set[tuple[int, int, int, int]] = set()

    def reserve(pokemon: SavePokemon, role: str, reason: str) -> bool:
        if role not in valid_roles or role in occupied:
            return False
        key = _identity(pokemon)
        if key in assigned:
            return False
        assigned[key] = (role, reason)
        occupied.add(role)
        return True

    same_size_replacement = len(before.party) == len(after.party) and len(incoming) == len(outgoing)
    if same_size_replacement:
        # El caso normal de Caja Pokémon es un intercambio uno-a-uno. Cuando solo
        # cambia un miembro no dependemos del slot: el entrante hereda siempre el
        # rol del único saliente, aunque ORAS haya recompuesto el orden.
        if len(incoming) == 1 and len(outgoing) == 1:
            outgoing_role = str(outgoing[0].role or "SIN ROL")
            if reserve(incoming[0], outgoing_role, "direct-replacement"):
                used_outgoing.add(_identity(outgoing[0]))
        else:
            outgoing_by_slot = {int(p.slot): p for p in outgoing}
            for pokemon in incoming:
                previous = outgoing_by_slot.get(int(pokemon.slot))
                if previous is None:
                    continue
                previous_role = str(previous.role or "SIN ROL")
                if reserve(pokemon, previous_role, "direct-replacement"):
                    used_outgoing.add(_identity(previous))

            remaining_incoming = [p for p in incoming if _identity(p) not in assigned]
            remaining_outgoing = [p for p in outgoing if _identity(p) not in used_outgoing]
            for pokemon, previous in zip(remaining_incoming, remaining_outgoing):
                previous_role = str(previous.role or "SIN ROL")
                if reserve(pokemon, previous_role, "direct-replacement"):
                    used_outgoing.add(_identity(previous))

    # Entradas a un hueco físico, o cualquier sustitución sin un rol válido que
    # heredar, usan siempre el primer rol libre empezando por Líbero.
    for pokemon in incoming:
        key = _identity(pokemon)
        if key in assigned:
            continue
        free_role = next((role for role in ordered_roles if role not in occupied), None)
        if free_role is None:
            continue
        reserve(pokemon, free_role, "first-free")

    result: list[LiveRoleAssignment] = []
    for pokemon in incoming:
        key = _identity(pokemon)
        chosen = assigned.get(key)
        if chosen is None:
            continue
        role, reason = chosen
        result.append(LiveRoleAssignment(
            slot=int(pokemon.slot),
            identity=key,
            current_role=str(pokemon.role or "SIN ROL"),
            new_role=role,
            reason=reason,
        ))
    return tuple(result)

def infer_unassigned_role_assignments(
    game: SaveGameData,
    role_order: tuple[str, ...] | list[str],
    reserved_assignments: tuple[LiveRoleAssignment, ...] | list[LiveRoleAssignment] = (),
) -> tuple[LiveRoleAssignment, ...]:
    """Asigna el primer rol libre a cualquier miembro activo que siga SIN ROL.

    Se usa como segunda capa tras las sustituciones directas. Las asignaciones ya
    reservadas se consideran el estado final previsto: su rol actual deja de ocupar
    una casilla y su ``new_role`` sí la ocupa. Así un Pokémon que entra desde el PC
    puede heredar el rol del saliente y, a la vez, otro miembro SIN ROL recibe el
    primer hueco restante sin crear conflictos.
    """

    ordered_roles = tuple(str(role) for role in role_order)
    valid_roles = set(ordered_roles)
    reserved = tuple(reserved_assignments or ())
    reserved_ids = {assignment.identity for assignment in reserved}

    occupied: set[str] = {
        str(pokemon.role)
        for pokemon in game.party
        if _identity(pokemon) not in reserved_ids and str(pokemon.role) in valid_roles
    }
    occupied.update(
        assignment.new_role for assignment in reserved if assignment.new_role in valid_roles
    )

    result: list[LiveRoleAssignment] = []
    for pokemon in sorted(game.party, key=lambda item: int(item.slot)):
        identity = _identity(pokemon)
        if identity in reserved_ids or str(pokemon.role) in valid_roles:
            continue
        free_role = next((role for role in ordered_roles if role not in occupied), None)
        if free_role is None:
            break
        result.append(LiveRoleAssignment(
            slot=int(pokemon.slot),
            identity=identity,
            current_role=str(pokemon.role or "SIN ROL"),
            new_role=free_role,
            reason="unassigned-first-free",
        ))
        occupied.add(free_role)

    return tuple(result)

