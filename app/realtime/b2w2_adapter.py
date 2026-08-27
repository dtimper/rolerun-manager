from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path

from ..b2w2_live import (
    STAT_ORDER_PERSONAL, B2W2LiveError, B2W2MelonDSReader, B2W2RoleWrite,
    PK5_PARTY_SIZE, PK5_STORED_SIZE, _crypt,
)
from ..models import PendingPartyHeal, PendingRoleChange, PendingTeamChange
from ..boxed_metadata import (
    ability_name, base_stats_for, boxed_level, item_name, species_name,
)
from ..pokemon_stats import nature_presentation, stat_dict
from ..role_rules import (
    ROLE_SYMBOLS, ROLE_TO_KEY, ROLE_TO_MARKING, canonical_role, role_from_markings,
)
from ..save_engine_client import SaveGameData, SavePokemon
from .adapter import RealTimeGameAdapter
from .models import (
    BattleState, DiagnosticLevel, LiveDiagnostic, LiveProcessInfo,
    RealTimeSnapshot,
)


@dataclass(frozen=True, slots=True)
class B2W2RealTimeWriteResult:
    game: SaveGameData
    process: object
    attempts: int
    applied_count: int
    memory_watches: tuple = ()
    already_applied: bool = False


class B2W2RealTimeAdapter(RealTimeGameAdapter):
    key = "b2w2-melonds-v026"
    game_key = "b2w2"
    display_name = "Pokémon Negro 2 / Blanco 2"

    @staticmethod
    def _strong_role_key(pokemon) -> str:
        return f"{int(pokemon.pid)}:{int(pokemon.tid)}:{int(pokemon.sid)}"

    @classmethod
    def _restore_semantic_roles(cls, game: SaveGameData, role_map) -> None:
        roles = dict(role_map or {})
        for pokemon in game.party:
            role = str(roles.get(cls._strong_role_key(pokemon), "") or "")
            if role in ROLE_TO_KEY:
                pokemon.role = role
                pokemon.role_symbol = ROLE_SYMBOLS.get(role, "")

    def __init__(self, reader=None, role_layout_getter=None) -> None:
        self.reader = reader or B2W2MelonDSReader()
        self.role_layout_getter = role_layout_getter or (lambda: 2)
        path = Path(__file__).resolve().parents[2] / "data" / "move_catalog.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
            self.move_names = {
                int(item["id"]): str(item.get("name_es") or item.get("name_en"))
                for item in raw.get("moves", [])
            }
        except Exception:
            self.move_names = {}
        # PP base de quinta generación, extraídos del mismo PKHeX.Core que usa el
        # motor de guardados. No se reutiliza la tabla de sexta: varios
        # movimientos cambiaron de PP entre generaciones.
        pp_path = Path(__file__).resolve().parents[2] / "data" / "b2w2_move_pp.json"
        try:
            raw_pp = json.loads(pp_path.read_text(encoding="utf-8-sig"))
            self.move_base_pp = {
                int(key): int(value) for key, value in dict(raw_pp.get("pp", {})).items()
            }
        except Exception:
            self.move_base_pp = {}

    def base_pp_for(self, move_id: int) -> int:
        """PP base Gen 5 del movimiento. Cero significa «no demostrado»."""
        return int(self.move_base_pp.get(int(move_id), 0))

    @staticmethod
    def _calculated_stats(base, ivs, evs, level: int, nature_id: int) -> tuple[int, ...]:
        """Calcula PS/Atk/Def/SpA/SpD/Spe con el Personal B2/W2 de PKHeX."""
        binary = tuple(int(value) for value in base)  # HP/Atk/Def/Spe/SpA/SpD
        visible_base = tuple(binary[index] for index in (0, 1, 2, 4, 5, 3))
        hp = ((2 * visible_base[0] + ivs[0] + evs[0] // 4) * level) // 100
        hp += level + 10
        nature = nature_presentation(nature_id)
        stats = [hp]
        for index in range(1, 6):
            value = ((2 * visible_base[index] + ivs[index] + evs[index] // 4) * level) // 100 + 5
            key = ("hp", "attack", "defense", "sp_attack", "sp_defense", "speed")[index]
            if nature is not None and nature.increased == key:
                value = value * 110 // 100
            elif nature is not None and nature.decreased == key:
                value = value * 90 // 100
            stats.append(value)
        return tuple(stats)

    @classmethod
    def _party_block(cls, stored: bytes, pokemon) -> bytes:
        base = base_stats_for("b2w2", pokemon.species_id, pokemon.form)
        level = boxed_level("b2w2", pokemon.species_id, pokemon.form, pokemon.experience)
        stats = cls._calculated_stats(base, pokemon.ivs, pokemon.evs, level, pokemon.nature_id)
        extension = bytearray(PK5_PARTY_SIZE - PK5_STORED_SIZE)
        extension[4] = level
        struct.pack_into(
            "<7H", extension, 6,
            stats[0], stats[0], stats[1], stats[2], stats[5], stats[3], stats[4],
        )
        return stored + _crypt(bytes(extension), pokemon.pid)

    def read_pc(
        self, anchors, *, box_count: int | None = None,
        box_slot_count: int | None = None,
    ):
        if box_count is not None and int(box_count) != 24:
            raise B2W2LiveError(f"B2/W2 declara 24 cajas, no {int(box_count)}.")
        if box_slot_count is not None and int(box_slot_count) != 30:
            raise B2W2LiveError(
                f"B2/W2 declara 30 slots por caja, no {int(box_slot_count)}."
            )
        party_read = self.reader.read_party()
        raw = self.reader.read_pc(party_read)
        anchors_by_identity: dict[tuple[int, int, int], list[SavePokemon]] = {}
        for pokemon in anchors or ():
            identity = (int(pokemon.pid or 0), int(pokemon.tid or 0), int(pokemon.sid or 0))
            anchors_by_identity.setdefault(identity, []).append(pokemon)
        layout = int(self.role_layout_getter())
        slots: dict[tuple[int, int], SavePokemon] = {}
        for pokemon in raw.pokemon:
            identity = (pokemon.pid, pokemon.tid, pokemon.sid)
            matches = anchors_by_identity.get(identity, ())
            old = matches[0] if len(matches) == 1 else None
            markings = list(pokemon.markings)
            role, role_symbol = role_from_markings(markings, layout=layout)
            if role == "SIN ROL" and old is not None and old.role:
                markings = list(old.markings)
                role, role_symbol = old.role, old.role_symbol
            nature = nature_presentation(pokemon.nature_id)
            species = species_name(pokemon.species_id)
            if species.startswith("Especie #") and pokemon.nickname:
                species = pokemon.nickname
            base_binary = base_stats_for("b2w2", pokemon.species_id, pokemon.form)
            level = boxed_level(
                "b2w2", pokemon.species_id, pokemon.form, pokemon.experience,
            )
            base_visible = tuple(base_binary[index] for index in (0, 1, 2, 4, 5, 3))
            slots[(pokemon.box, pokemon.slot)] = SavePokemon(
                slot=pokemon.slot, box=pokemon.box, box_slot=pokemon.slot,
                species_id=pokemon.species_id, species=species,
                nickname=pokemon.nickname or species, level=level,
                held_item=item_name(pokemon.held_item_id),
                ability=ability_name(pokemon.ability_id),
                moves=[
                    self.move_names.get(move_id, "—" if move_id == 0 else f"Movimiento #{move_id}")
                    for move_id in pokemon.move_ids
                ],
                move_ids=list(pokemon.move_ids), is_egg=pokemon.is_egg,
                markings=markings, role=role, role_symbol=role_symbol,
                pid=pokemon.pid, tid=pokemon.tid, sid=pokemon.sid,
                form=pokemon.form, nature_id=pokemon.nature_id,
                stat_nature_id=pokemon.nature_id,
                nature=nature.name if nature else "",
                stat_nature=nature.name if nature else "",
                nature_increased=nature.increased if nature else None,
                nature_decreased=nature.decreased if nature else None,
                base_stats=stat_dict(base_visible),
                stats=stat_dict(self._calculated_stats(
                    base_binary, pokemon.ivs, pokemon.evs, level, pokemon.nature_id,
                )),
                ivs=stat_dict(pokemon.ivs), evs=stat_dict(pokemon.evs),
            )
        return party_read, raw.guest_base, slots

    def _role_write_for(self, party_read, change: PendingRoleChange) -> B2W2RoleWrite:
        """Traduce un cambio de rol de RoleRun a una escritura PK5 concreta."""
        identity = str(getattr(change, "pokemon_identity", "") or "")
        candidatos = [
            (index, member) for index, member in enumerate(party_read.pokemon)
            if self._strong_identity(member) == identity
        ]
        if len(candidatos) != 1:
            raise B2W2LiveError(
                "El Pokémon del cambio de rol B2/W2 no está de forma única en la party."
            )
        slot, member = candidatos[0]
        role = canonical_role(change.new_role)
        marca = ROLE_TO_MARKING.get(role)
        if marca is None:
            raise B2W2LiveError(f"Rol B2/W2 no reconocido: {change.new_role!r}.")
        # Una sola marca gobierna el rol; "SIN ROL" las deja todas a cero. Es el
        # mismo contrato que ``role_from_markings`` usa al leer.
        markings = tuple(index == marca for index in range(6))
        evs = tuple(int(value) for value in (change.new_evs or member.evs))
        base = dict(zip(
            STAT_ORDER_PERSONAL,
            base_stats_for("b2w2", int(member.species_id), int(member.form)),
        ))
        return B2W2RoleWrite(
            slot=slot,
            identity=(int(member.pid), int(member.tid), int(member.sid)),
            markings=markings, evs=evs, base_stats=base,
        )

    @staticmethod
    def _strong_identity(member) -> str:
        """Misma identidad que ``RunProjectService.pokemon_identity_key``.

        No se reinventa el formato: si el adaptador usara otro, un cambio de rol
        no encontraría nunca a su Pokémon.
        """
        return f"{int(member.species_id)}:{int(member.pid)}:{int(member.tid)}:{int(member.sid)}"

    def _heal_target_for(self, party_read, change: PendingPartyHeal):
        """Localiza por identidad fuerte al miembro que hay que curar."""
        identity = str(getattr(change, "pokemon_identity", "") or "")
        candidatos = [
            (index, member) for index, member in enumerate(party_read.pokemon)
            if self._strong_identity(member) == identity
        ]
        if len(candidatos) != 1:
            raise B2W2LiveError(
                "El Pokémon de la curación B2/W2 no está de forma única en la party."
            )
        slot, member = candidatos[0]
        return slot, (int(member.pid), int(member.tid), int(member.sid))

    def apply_changes(self, current: SaveGameData, changes):
        changes = list(changes)
        if changes and all(isinstance(item, PendingPartyHeal) for item in changes):
            party_read = self.reader.read_party()
            objetivos = [self._heal_target_for(party_read, item) for item in changes]
            self.reader.write_party_heal(
                party_read, objetivos, base_pp_for=self.base_pp_for,
            )
            live = self._capture(current, 0)
            live.game.raw["writes_enabled"] = True
            live.game.raw["live_write"] = True
            return B2W2RealTimeWriteResult(live.game, live.process, 2, len(objetivos))
        if changes and all(isinstance(item, PendingRoleChange) for item in changes):
            party_read = self.reader.read_party()
            escrituras = [self._role_write_for(party_read, item) for item in changes]
            self.reader.write_party_roles(party_read, escrituras)
            live = self._capture(current, 0)
            live.game.raw["writes_enabled"] = True
            live.game.raw["live_write"] = True
            return B2W2RealTimeWriteResult(live.game, live.process, 2, len(escrituras))
        if len(changes) != 1 or not isinstance(changes[0], PendingTeamChange):
            raise B2W2LiveError("B2/W2 solo admite un movimiento PC→PC por transacción.")
        change = changes[0]
        if change.operation not in {
            "move-box-slot", "swap-party-box", "party-to-box", "box-to-party",
        }:
            raise B2W2LiveError("La operación B2/W2 todavía no tiene writer validado.")
        if change.operation in {"party-to-box", "box-to-party"}:
            party_read = self.reader.read_party()
            box, box_slot = int(change.box or 0), int(change.box_slot or 0)
            if change.operation == "party-to-box":
                snapshot = dict(change.outgoing_snapshot or {})
                identity = tuple(int(snapshot.get(k, 0) or 0) for k in ("pid", "tid", "sid"))
                built = None
            else:
                pc = self.reader.read_pc(party_read)
                incoming = next((p for p in pc.pokemon if (p.box, p.slot) == (box, box_slot)), None)
                if incoming is None or incoming.held_item_id != 0:
                    raise B2W2LiveError("La retirada B2/W2 exige por ahora un entrante sin objeto.")
                snapshot = dict(change.incoming_snapshot or {})
                identity = tuple(int(snapshot.get(k, 0) or 0) for k in ("pid", "tid", "sid"))
                if identity != (incoming.pid, incoming.tid, incoming.sid):
                    raise B2W2LiveError("La identidad entrante B2/W2 no coincide.")
                offset = (box - 1) * 0x1000 + (box_slot - 1) * PK5_STORED_SIZE
                stored = pc.raw[offset:offset + PK5_STORED_SIZE]
                built = self._party_block(stored, incoming)
            if not all(identity):
                raise B2W2LiveError("Falta la identidad fuerte del cambio B2/W2.")
            self.reader.resize_party_pc(
                party_read, operation=change.operation,
                party_slot=int(change.party_slot), box=box, box_slot=box_slot,
                expected_identity=identity, incoming_party=built,
            )
            live = self._capture(current, 0)
            self._restore_semantic_roles(live.game, change.party_role_snapshot)
            live.game.raw["writes_enabled"] = True
            live.game.raw["live_write"] = True
            return B2W2RealTimeWriteResult(live.game, live.process, 2, 1)
        if change.operation == "swap-party-box":
            party_read = self.reader.read_party()
            party_slot = int(change.party_slot)
            if not 0 <= party_slot < party_read.count:
                raise B2W2LiveError("El slot de party B2/W2 está fuera de rango.")
            before_pc = self.reader.read_pc(party_read)
            box, box_slot = int(change.box or 0), int(change.box_slot or 0)
            incoming = next((
                p for p in before_pc.pokemon if (p.box, p.slot) == (box, box_slot)
            ), None)
            if incoming is None or incoming.held_item_id != 0:
                raise B2W2LiveError(
                    "El intercambio B2/W2 exige por ahora un entrante sin objeto."
                )
            incoming_snapshot = dict(change.incoming_snapshot or {})
            outgoing_snapshot = dict(change.outgoing_snapshot or {})
            incoming_identity = tuple(int(incoming_snapshot.get(k, 0) or 0) for k in ("pid", "tid", "sid"))
            outgoing_identity = tuple(int(outgoing_snapshot.get(k, 0) or 0) for k in ("pid", "tid", "sid"))
            if incoming_identity != (incoming.pid, incoming.tid, incoming.sid) or not all(outgoing_identity):
                raise B2W2LiveError("Los testigos Equipo↔PC B2/W2 no coinciden.")
            offset = (box - 1) * 0x1000 + (box_slot - 1) * PK5_STORED_SIZE
            stored = before_pc.raw[offset:offset + PK5_STORED_SIZE]
            built = self._party_block(stored, incoming)
            self.reader.swap_party_pc(
                party_read, party_slot, box, box_slot, built,
                incoming_identity=incoming_identity, outgoing_identity=outgoing_identity,
            )
            live = self._capture(current, 0)
            member = next((p for p in live.game.party if (p.pid, p.tid, p.sid) == incoming_identity), None)
            if member is not None:
                member.role = str(incoming_snapshot.get("role", member.role) or member.role)
                member.role_symbol = str(incoming_snapshot.get("role_symbol", member.role_symbol) or member.role_symbol)
                member.markings = list(incoming_snapshot.get("markings", member.markings) or member.markings)
            live.game.raw["writes_enabled"] = True
            live.game.raw["live_write"] = True
            return B2W2RealTimeWriteResult(live.game, live.process, 2, 1)
        coordinates = (
            int(change.box or 0), int(change.box_slot or 0),
            int(change.destination_box or 0), int(change.destination_box_slot or 0),
        )
        party_read = self.reader.read_party()
        before = self.reader.read_pc(party_read)
        plan = self.reader.prepare_pc_move(before.raw, *coordinates)
        snapshot = dict(change.incoming_snapshot or {})
        expected = (
            int(snapshot.get("pid", 0) or 0), int(snapshot.get("tid", 0) or 0),
            int(snapshot.get("sid", 0) or 0),
        )
        if not all(expected) or expected != (plan.pokemon.pid, plan.pokemon.tid, plan.pokemon.sid):
            raise B2W2LiveError("La identidad del origen PC B2/W2 ha cambiado.")
        self.reader.move_pc_slot(
            party_read, *coordinates, expected_identity=expected,
        )
        live = self._capture(current, 0)
        live.game.raw["writes_enabled"] = True
        live.game.raw["live_write"] = True
        return B2W2RealTimeWriteResult(
            game=live.game, process=live.process, attempts=2, applied_count=1,
        )

    def _capture(self, current: SaveGameData, sequence: int) -> RealTimeSnapshot:
        raw = self.reader.read_party()
        anchors = {(p.pid, p.tid, p.sid): p for p in current.party}
        live_identities = {(p.pid, p.tid, p.sid) for p in raw.pokemon}
        if not anchors or anchors.keys().isdisjoint(live_identities):
            raise B2W2LiveError(
                "La party viva de melonDS no coincide con ninguna identidad fuerte "
                "del guardado B2/W2 activo. No se publicó la lectura."
            )
        party = []
        for pokemon in raw.pokemon:
            old = anchors.get((pokemon.pid, pokemon.tid, pokemon.sid))
            markings = list(pokemon.markings)
            role, role_symbol = role_from_markings(
                markings, layout=int(self.role_layout_getter()),
            )
            # B2/W2 sigue siendo read-only: una Run existente puede tener roles
            # semánticos que todavía no hemos podido grabar en las marcas PK5.
            # Una marca única viva sí es evidencia; cero o varias marcas no deben
            # borrar el rol persistido hasta que exista writer bidireccional.
            if role == "SIN ROL" and old is not None and old.role:
                markings = list(old.markings)
                role = old.role
                role_symbol = old.role_symbol
            nature = nature_presentation(pokemon.nature_id)
            species = species_name(pokemon.species_id)
            if species.startswith("Especie #") and pokemon.nickname:
                species = pokemon.nickname
            base_binary = base_stats_for("b2w2", pokemon.species_id, pokemon.form)
            base_visible = tuple(base_binary[index] for index in (0, 1, 2, 4, 5, 3))
            party.append(SavePokemon(
                slot=pokemon.slot,
                species_id=pokemon.species_id,
                species=species,
                nickname=pokemon.nickname or species,
                level=pokemon.level,
                held_item=item_name(pokemon.held_item_id),
                ability=ability_name(pokemon.ability_id),
                moves=[
                    self.move_names.get(
                        move_id, "—" if move_id == 0 else f"Movimiento #{move_id}",
                    )
                    for move_id in pokemon.move_ids
                ],
                move_ids=list(pokemon.move_ids),
                is_egg=pokemon.is_egg,
                markings=markings,
                role=role,
                role_symbol=role_symbol,
                pid=pokemon.pid,
                tid=pokemon.tid,
                sid=pokemon.sid,
                form=pokemon.form,
                current_hp=pokemon.current_hp,
                max_hp=pokemon.max_hp,
                status_condition=pokemon.status_condition,
                nature_id=pokemon.nature_id,
                stat_nature_id=pokemon.nature_id,
                nature=nature.name if nature else "",
                stat_nature=nature.name if nature else "",
                nature_increased=nature.increased if nature else None,
                nature_decreased=nature.decreased if nature else None,
                base_stats=stat_dict(base_visible),
                stats=stat_dict(pokemon.stats),
                ivs=stat_dict(pokemon.ivs),
                evs=stat_dict(pokemon.evs),
            ))
        game = SaveGameData(
            "B2W2", "SAV5B2W2", 5, current.trainer, party,
            {
                **dict(current.raw or {}),
                "live_source": "melonDS host RAM · B2/W2 party nominal",
                "writes_enabled": False,
            },
        )
        battle = BattleState("unknown")
        battle_diagnostic = LiveDiagnostic(
            "battle", DiagnosticLevel.WARNING,
            "La fila de batalla B2/W2 no pudo validarse.",
        )
        try:
            battle_raw = self.reader.read_battle(raw)
            if not battle_raw.active:
                battle = BattleState("none")
                battle_diagnostic = LiveDiagnostic(
                    "battle", DiagnosticLevel.OK,
                    "Fuera de combate; ambas filas B2/W2 están vacías.",
                    "mirror + immediate",
                )
            else:
                health_party = [
                    replace(
                        member,
                        current_hp=(
                            battle_raw.current_hp
                            if member.slot == battle_raw.party_slot
                            else member.current_hp
                        ),
                        status_condition=(
                            battle_raw.status_condition
                            if member.slot == battle_raw.party_slot
                            else member.status_condition
                        ),
                    )
                    for member in game.party
                ]
                health_game = replace(game, party=health_party)
                battle = BattleState(
                    "battle", health_game=health_game,
                    hp_pairs=tuple((p.current_hp, p.max_hp) for p in health_party),
                )
                battle_diagnostic = LiveDiagnostic(
                    "battle", DiagnosticLevel.OK,
                    f"PS presentados {battle_raw.current_hp}/{battle_raw.max_hp}; "
                    f"estado presentado {battle_raw.status_condition}; "
                    f"fuente lógica {battle_raw.immediate_hp}; "
                    f"mirror {'convergido' if battle_raw.converged else 'esperando animación'}.",
                    "0x0225B1B0 presentation gate · 0x0225B5F8 logical witness",
                )
        except Exception as exc:
            battle_diagnostic = LiveDiagnostic(
                "battle", DiagnosticLevel.WARNING, str(exc),
                "B2/W2 battle lane aislado",
            )
        diagnostics = (
            LiveDiagnostic(
                "party", DiagnosticLevel.OK,
                f"Equipo B2/W2 validado ({raw.count}/6), con estado, naturaleza, "
                "estadísticas, IV, EV, PP y marcas.",
                "PK5 nominal · doble lectura + checksum + identidad · PKHeX PK5",
            ),
            battle_diagnostic,
        )
        return RealTimeSnapshot(
            game,
            LiveProcessInfo("melonDS", raw.process_id, 0, raw.process_name),
            1,
            self.key,
            "B2W2 Spain · melonDS 1.1",
            battle=battle,
            diagnostics=diagnostics,
            sequence=sequence,
        )

    def capture_monitor(
        self, current, *, save_path, memory_requests=(), sequence=0,
    ):
        return self._capture(current, sequence)

    def capture_full(
        self, current, *, save_path, memory_requests=(), sequence=0,
    ):
        return self._capture(current, sequence)
