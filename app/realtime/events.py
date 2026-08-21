from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..save_engine_client import SaveGameData, SavePokemon
from .models import RealTimeSnapshot


class RealTimeEventType(str, Enum):
    PARTY_CHANGED = "party_changed"
    ORDER_CHANGED = "order_changed"
    ROLE_CHANGED = "role_changed"
    MOVES_CHANGED = "moves_changed"
    LEVEL_CHANGED = "level_changed"
    POKEMON_FAINTED = "pokemon_fainted"
    BADGE_CHANGED = "badge_changed"
    BATTLE_STATE_CHANGED = "battle_state_changed"


@dataclass(frozen=True, slots=True)
class RealTimeEvent:
    type: RealTimeEventType
    message: str
    pokemon_identity: tuple[int, int, int, int] | None = None
    before: object | None = None
    after: object | None = None


def pokemon_identity(pokemon: SavePokemon) -> tuple[int, int, int, int]:
    return (
        int(pokemon.species_id),
        int(pokemon.pid or 0),
        int(pokemon.tid or 0),
        int(pokemon.sid or 0),
    )


def _party_events(before: SaveGameData, after: SaveGameData) -> list[RealTimeEvent]:
    events: list[RealTimeEvent] = []
    old = {pokemon_identity(p): p for p in before.party}
    new = {pokemon_identity(p): p for p in after.party}
    old_ids, new_ids = set(old), set(new)

    if old_ids != new_ids:
        events.append(RealTimeEvent(
            RealTimeEventType.PARTY_CHANGED,
            "Cambió la composición del equipo.",
            before=tuple(old_ids), after=tuple(new_ids),
        ))
    else:
        old_order = tuple(pokemon_identity(p) for p in sorted(before.party, key=lambda x: int(x.slot)))
        new_order = tuple(pokemon_identity(p) for p in sorted(after.party, key=lambda x: int(x.slot)))
        if old_order != new_order:
            events.append(RealTimeEvent(
                RealTimeEventType.ORDER_CHANGED,
                "Cambió el orden del equipo.",
                before=old_order, after=new_order,
            ))

    for identity in old_ids.intersection(new_ids):
        previous, current = old[identity], new[identity]
        old_role = str(previous.role or "SIN ROL")
        new_role = str(current.role or "SIN ROL")
        if old_role != new_role:
            events.append(RealTimeEvent(
                RealTimeEventType.ROLE_CHANGED,
                f"Cambió el rol de {current.nickname or current.species}.",
                pokemon_identity=identity, before=old_role, after=new_role,
            ))
        old_moves = tuple(int(value or 0) for value in previous.move_ids)
        new_moves = tuple(int(value or 0) for value in current.move_ids)
        if old_moves != new_moves:
            events.append(RealTimeEvent(
                RealTimeEventType.MOVES_CHANGED,
                f"Cambió el moveset de {current.nickname or current.species}.",
                pokemon_identity=identity, before=old_moves, after=new_moves,
            ))
        old_level = int(getattr(previous, "level", 0) or 0)
        new_level = int(getattr(current, "level", 0) or 0)
        if old_level != new_level:
            events.append(RealTimeEvent(
                RealTimeEventType.LEVEL_CHANGED,
                f"Cambió el nivel de {current.nickname or current.species}.",
                pokemon_identity=identity, before=old_level, after=new_level,
            ))
        old_hp = int(getattr(previous, "current_hp", 0) or 0)
        new_hp = int(getattr(current, "current_hp", 0) or 0)
        if old_hp > 0 and new_hp == 0:
            events.append(RealTimeEvent(
                RealTimeEventType.POKEMON_FAINTED,
                f"{current.nickname or current.species} se debilitó.",
                pokemon_identity=identity, before=old_hp, after=0,
            ))
    return events


def diff_realtime_snapshots(
    before: RealTimeSnapshot | None,
    after: RealTimeSnapshot,
) -> tuple[RealTimeEvent, ...]:
    """Genera eventos semánticos sin depender de offsets ni del emulador."""

    if before is None:
        return ()
    events = _party_events(before.game, after.game)
    if before.badges is not None and after.badges is not None and int(before.badges) != int(after.badges):
        events.append(RealTimeEvent(
            RealTimeEventType.BADGE_CHANGED,
            f"Medallas: {int(before.badges)} → {int(after.badges)}.",
            before=int(before.badges), after=int(after.badges),
        ))
    if before.battle.state != after.battle.state:
        events.append(RealTimeEvent(
            RealTimeEventType.BATTLE_STATE_CHANGED,
            f"Estado de batalla: {before.battle.state} → {after.battle.state}.",
            before=before.battle.state, after=after.battle.state,
        ))
    return tuple(events)
