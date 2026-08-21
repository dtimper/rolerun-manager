from __future__ import annotations

import copy
from dataclasses import replace

from .models import (
    PendingChange,
    PendingPCRoleChange,
    PendingRoleChange,
    PendingTMTeach,
    PendingTeamChange,
)


def inverse_oras_live_change(change):
    """Construye la edición semántica inversa de una acción viva de ORAS.

    Nunca restaura un PK6 completo antiguo: devuelve otra operación que modifica
    únicamente el campo gestionado por RoleRun, conservando el resto del estado
    actual del juego (EXP, PS, amistad, etc.).
    """
    if isinstance(change, PendingRoleChange):
        return replace(change, old_role=change.new_role, new_role=change.old_role)
    if isinstance(change, PendingChange):
        return replace(
            change,
            old_move=change.new_move,
            old_move_id=change.new_move_id,
            new_move=change.old_move,
            new_move_id=change.old_move_id,
        )
    if isinstance(change, PendingTMTeach):
        # En ORAS las MT son reutilizables: restaurar el movimiento anterior no
        # requiere ninguna escritura adicional sobre la mochila.
        return PendingChange(
            role=change.role,
            pokemon_slot=change.pokemon_slot,
            pokemon=change.pokemon,
            species=change.species,
            move_slot=change.move_slot,
            old_move=change.new_move,
            old_move_id=change.new_move_id,
            new_move=change.old_move,
            new_move_id=change.old_move_id,
            pokemon_identity=change.pokemon_identity,
        )
    if isinstance(change, PendingPCRoleChange):
        return replace(change, old_role=change.new_role, new_role=change.old_role)
    if isinstance(change, PendingTeamChange) and change.operation == "swap-party-box":
        old_role = str(change.outgoing_snapshot.get("role", "SIN ROL") or "SIN ROL")
        return PendingTeamChange(
            operation="swap-party-box",
            party_slot=change.party_slot,
            box=change.box,
            box_slot=change.box_slot,
            outgoing_pokemon=change.incoming_pokemon,
            outgoing_species=change.incoming_species,
            incoming_pokemon=change.outgoing_pokemon,
            incoming_species=change.outgoing_species,
            incoming_role=old_role,
            remove_move_slots=[],
            incoming_snapshot=copy.deepcopy(change.outgoing_snapshot),
            outgoing_snapshot=copy.deepcopy(change.incoming_snapshot),
            incoming_identity=change.outgoing_identity,
            outgoing_identity=change.incoming_identity,
            box_witnesses=tuple(change.box_witnesses or ()),
        )
    # Las utilidades de inventario no se invierten a ciegas: la cantidad puede
    # haber cambiado después jugando y restaurar un valor viejo sería peligroso.
    return None
