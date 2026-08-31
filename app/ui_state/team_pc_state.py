from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

CANONICAL_ROLE_ORDER = ("Líbero", "Asesino", "Mago", "Tanque", "Prisma", "Support")


@dataclass(frozen=True, slots=True)
class TeamPCDropIntent:
    operation: str | None
    reason: str = ""


def resolve_team_pc_drop(
    source_context: str,
    target_context: str,
    *,
    target_occupied: bool,
    team_count: int,
) -> TeamPCDropIntent:
    """Traduce un gesto a una operación existente, sin reglas de escritura.

    El orden físico Equipo→Equipo no existe en los writers actuales. PC→PC
    distingue dos operaciones distintas: llevar una criatura a un hueco vacío
    (``move-box-slot``) e intercambiar dos huecos ocupados
    (``swap-box-slots``). Qué backend sabe escribir cada una lo decide la
    interfaz, no este resolutor.
    """
    source = str(source_context)
    target = str(target_context)
    if source == "team" and target == "pc":
        return TeamPCDropIntent("swap-party-box" if target_occupied else "party-to-box")
    if source == "pc" and target == "team":
        if target_occupied:
            return TeamPCDropIntent("swap-party-box")
        if int(team_count) >= 6:
            return TeamPCDropIntent(None, "El equipo ya tiene seis Pokémon.")
        return TeamPCDropIntent("box-to-party")
    if source == target == "pc":
        if target_occupied:
            return TeamPCDropIntent("swap-box-slots")
        return TeamPCDropIntent("move-box-slot")
    if source == target == "team":
        return TeamPCDropIntent(None, "El backend actual no declara reordenación física Equipo→Equipo.")
    return TeamPCDropIntent(None, "El destino no pertenece a Equipo o PC.")


@dataclass(slots=True)
class TMTeachFlowState:
    """Estado puro del selector MT integrado de tres pasos."""

    candidates: tuple[dict[str, Any], ...]
    step: int = 1
    selected_move_id: int | None = None
    selected_slot: int | None = None

    def select_tm(self, move_id: int) -> dict[str, Any]:
        candidate = self.candidate(move_id)
        if candidate is None:
            raise ValueError("La MT no pertenece al conjunto validado.")
        self.selected_move_id = int(move_id)
        self.selected_slot = None
        self.step = 2
        return candidate

    def select_slot(self, slot: int) -> int:
        candidate = self.selected_candidate
        if candidate is None:
            raise ValueError("Primero hay que seleccionar una MT.")
        slot = int(slot)
        valid_slots = tuple(int(value) for value in candidate.get("valid_slots", ()))
        if slot not in valid_slots:
            raise ValueError("Ese hueco no produce un moveset válido para el rol.")
        self.selected_slot = slot
        self.step = 3
        return slot

    def back(self) -> int:
        if self.step == 3:
            self.step = 2
            self.selected_slot = None
        elif self.step == 2:
            self.step = 1
            self.selected_move_id = None
        return self.step

    def candidate(self, move_id: int) -> dict[str, Any] | None:
        return next(
            (item for item in self.candidates if int(item.get("move_id", 0)) == int(move_id)),
            None,
        )

    @property
    def selected_candidate(self) -> dict[str, Any] | None:
        if self.selected_move_id is None:
            return None
        return self.candidate(self.selected_move_id)


def build_fixed_team_slots(
    party: Iterable[Any],
    role_for: Callable[[Any], str],
    identity_for: Callable[[Any], str],
) -> tuple[dict[str, Any], ...]:
    """Proyecta como máximo seis miembros sobre seis casillas, nunca una séptima.

    El primer ocupante válido va a su casilla canónica. Duplicados y miembros
    SIN ROL ocupan una casilla canónica libre solo como estado de preparación;
    ``occupant_role`` conserva su rol real para que la vista no finja que posee
    el rol cuyo hueco físico está utilizando.
    """
    members = sorted(list(party)[:6], key=lambda pokemon: int(getattr(pokemon, "slot", 0) or 0))
    by_role: dict[str, Any] = {}
    extras: list[Any] = []
    seen_identities: set[str] = set()
    for pokemon in members:
        identity = identity_for(pokemon)
        if identity in seen_identities:
            continue
        seen_identities.add(identity)
        role = role_for(pokemon)
        if role in CANONICAL_ROLE_ORDER and role not in by_role:
            by_role[role] = pokemon
        else:
            extras.append(pokemon)

    slots: list[dict[str, Any]] = []
    for slot_role in CANONICAL_ROLE_ORDER:
        pokemon = by_role.get(slot_role)
        if pokemon is None and extras:
            pokemon = extras.pop(0)
        occupant_role = role_for(pokemon) if pokemon is not None else "SIN ROL"
        state = "empty"
        if pokemon is not None:
            state = "assigned" if occupant_role == slot_role else "preparation"
        slots.append({
            "slot_role": slot_role,
            "pokemon": pokemon,
            "occupant_role": occupant_role,
            "state": state,
        })
    return tuple(slots)


@dataclass(slots=True)
class TeamPCSelectionState:
    """Selección y navegación del inspector sin reconstruir la página."""

    context: str = "team"
    selected_identity: str | None = None
    selected_box_slot: int | None = None
    current_box: int = 1
    team_identities: tuple[str, ...] = ()
    pc_slots: tuple[int, ...] = ()
    active: bool = False

    def __post_init__(self) -> None:
        if self.selected_identity is not None or self.selected_box_slot is not None:
            self.active = True

    def set_team(self, identities: Iterable[str]) -> None:
        self.team_identities = tuple(identity for identity in identities if identity)
        if self.context == "team" and self.selected_identity not in self.team_identities:
            self.selected_identity = None
            self.active = False

    def set_pc_box(self, box: int, occupied_slots: Iterable[int]) -> None:
        self.current_box = max(1, int(box))
        self.pc_slots = tuple(sorted({int(slot) for slot in occupied_slots if int(slot) > 0}))
        if self.active and self.context == "pc" and self.selected_box_slot not in self.pc_slots:
            self.selected_box_slot = self._nearest_pc_slot(self.selected_box_slot)
            if self.selected_box_slot is None:
                self.active = False

    def select_team(self, identity: str) -> None:
        if identity not in self.team_identities:
            raise ValueError("El Pokémon no pertenece al equipo visible.")
        self.context = "team"
        self.selected_identity = identity
        self.selected_box_slot = None
        self.active = True

    def select_pc(self, slot: int) -> None:
        slot = int(slot)
        if slot not in self.pc_slots:
            raise ValueError("La posición del PC está vacía o no pertenece a la caja visible.")
        self.context = "pc"
        self.selected_box_slot = slot
        self.selected_identity = None
        self.active = True

    def move(self, delta: int) -> tuple[str, int | str] | None:
        values: tuple[int | str, ...]
        current: int | str | None
        if self.context == "pc":
            values = self.pc_slots
            current = self.selected_box_slot
        else:
            values = self.team_identities
            current = self.selected_identity
        if not values:
            return None
        try:
            index = values.index(current) if current is not None else 0
        except ValueError:
            index = 0
        target = values[(index + (1 if delta >= 0 else -1)) % len(values)]
        if self.context == "pc":
            self.selected_box_slot = int(target)
            self.active = True
            return "pc", int(target)
        self.selected_identity = str(target)
        self.active = True
        return "team", str(target)

    def move_direction(self, direction: str, *, pc_columns: int = 3) -> tuple[str, int | str] | None:
        """Mueve una sola posición según las dos listas visuales reales.

        Equipo no comparte una cuadrícula con las treinta posiciones PC.
        Escalar sus seis filas sobre las diez del PC hacía que el algoritmo
        geométrico eligiera otra columna y saltara Mago/Prisma. Dentro de cada
        panel el orden es ahora explícito; solo izquierda/derecha cruza paneles.
        """

        direction = str(direction).casefold()
        pc_columns = max(1, int(pc_columns))
        if not self.active:
            if self.team_identities:
                self.select_team(self.team_identities[0])
                return "team", self.team_identities[0]
            if self.pc_slots:
                self.select_pc(self.pc_slots[0])
                return "pc", self.pc_slots[0]
            return None

        if self.context == "team":
            if not self.team_identities or self.selected_identity not in self.team_identities:
                return None
            index = self.team_identities.index(self.selected_identity)
            if direction == "up":
                index = max(0, index - 1)
            elif direction == "down":
                index = min(len(self.team_identities) - 1, index + 1)
            elif direction == "right" and self.pc_slots:
                target_row = round(index * 9 / max(1, len(self.team_identities) - 1))
                slot = min(
                    self.pc_slots,
                    key=lambda value: (
                        abs(((value - 1) // pc_columns) - target_row),
                        (value - 1) % pc_columns,
                        value,
                    ),
                )
                self.select_pc(slot)
                return "pc", slot
            self.select_team(self.team_identities[index])
            return "team", self.team_identities[index]

        if not self.pc_slots or self.selected_box_slot not in self.pc_slots:
            return None
        slot = int(self.selected_box_slot)
        row = (slot - 1) // pc_columns
        column = (slot - 1) % pc_columns
        candidates: tuple[int, ...]
        if direction == "left":
            candidates = tuple(value for value in self.pc_slots if (value - 1) // pc_columns == row and value < slot)
            if not candidates and self.team_identities:
                team_index = min(
                    range(len(self.team_identities)),
                    key=lambda value: abs(round(value * 9 / max(1, len(self.team_identities) - 1)) - row),
                )
                self.select_team(self.team_identities[team_index])
                return "team", self.team_identities[team_index]
            target = max(candidates, default=slot)
        elif direction == "right":
            candidates = tuple(value for value in self.pc_slots if (value - 1) // pc_columns == row and value > slot)
            target = min(candidates, default=slot)
        elif direction == "up":
            candidates = tuple(value for value in self.pc_slots if (value - 1) % pc_columns == column and value < slot)
            target = max(candidates, default=slot)
        elif direction == "down":
            candidates = tuple(value for value in self.pc_slots if (value - 1) % pc_columns == column and value > slot)
            target = min(candidates, default=slot)
        else:
            target = slot
        self.select_pc(target)
        return "pc", target

    def clear(self) -> None:
        self.active = False
        self.selected_identity = None
        self.selected_box_slot = None

    def _nearest_pc_slot(self, preferred: int | None) -> int | None:
        if not self.pc_slots:
            return None
        if preferred is None:
            return self.pc_slots[0]
        return min(self.pc_slots, key=lambda slot: (abs(slot - int(preferred)), slot))
