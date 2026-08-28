from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Mapping, Sequence

from ..bdsp_live import (
    BDSP_SP_130_HOST_PROFILE,
    BDSPBattleRead,
    BDSPBattlePresentationRead,
    BDSPBattlePresentationReader,
    BDSPBattleReader,
    BDSPBadgeReader,
    BDSPBoxRead,
    BDSPBoxReader,
    BDSPInventoryReader,
    BDSPLiveWriter,
    BDSPPartyRead,
    BDSPPartyReader,
    BDSPWriteMemoryWatch,
    calculate_bdsp_stats,
)
from ..bdsp_live import read_bdsp_play_time
from ..ventana_activa import tiene_el_foco
from ..bdsp_tm_service import BDSPTMProfile, discover_personal_masterdatas, load_bdsp_tm_profile
from ..boxed_metadata import ability_name, item_name, level_for_experience, species_name
from ..config import APP_VERSION
from ..pokemon_stats import nature_presentation, stat_dict
from ..role_rules import role_from_markings
from ..ryujinx_host_memory import RyujinxHostMappedClient
from ..save_engine_client import SaveGameData, SavePokemon
from .adapter import RealTimeGameAdapter
from .models import (
    BattleState,
    DiagnosticLevel,
    LiveDiagnostic,
    LiveMemoryBlock,
    LiveProcessInfo,
    RealTimeSnapshot,
)


_MOVE_CATALOG = Path(__file__).resolve().parents[2] / "data" / "move_catalog.json"


def _training_kwargs(pokemon) -> dict[str, object]:
    actual = nature_presentation(getattr(pokemon, "nature_id", None))
    effective = nature_presentation(getattr(pokemon, "stat_nature_id", None))
    return {
        "nature_id": actual.nature_id if actual is not None else None,
        "stat_nature_id": effective.nature_id if effective is not None else None,
        "nature": actual.name if actual is not None else "",
        "stat_nature": effective.name if effective is not None else "",
        "nature_increased": effective.increased if effective is not None else None,
        "nature_decreased": effective.decreased if effective is not None else None,
        "stats": stat_dict(getattr(pokemon, "stats", None)),
        "ivs": stat_dict(getattr(pokemon, "ivs", None)),
        "evs": stat_dict(getattr(pokemon, "evs", None)),
    }


@dataclass(frozen=True, slots=True)
class BDSPRealTimeWriteResult:
    game: SaveGameData
    process: object
    attempts: int
    applied_count: int
    memory_watches: tuple[BDSPWriteMemoryWatch, ...] = ()
    already_applied: bool = False


class BDSPRealTimeAdapter(RealTimeGameAdapter):
    """Adaptador validado para Perla Reluciente 1.3.0 en Ryujinx.

    PlayerWork aporta identidad y estructura completa del equipo; BDSPBoxReader
    expone por separado la matriz PC de solo lectura. Durante una batalla,
    BTL_PARTY es la autoridad inmediata de HP; sus filas se vuelven a ordenar al
    cambiar Pokémon, por lo que se aplican mediante PokeID/party_index y nunca
    mediante el número de fila visible.
    """

    key = "bdsp-sp130-ryujinx-hostmapped"
    game_key = "bdsp"
    display_name = "Pokémon Perla Reluciente"

    def __init__(
        self,
        *,
        client_factory: Callable[[], RyujinxHostMappedClient] | None = None,
        party_reader_factory: Callable[[RyujinxHostMappedClient], BDSPPartyReader] = BDSPPartyReader,
        battle_reader_factory: Callable[[RyujinxHostMappedClient], BDSPBattleReader] = BDSPBattleReader,
        presentation_reader_factory: Callable[
            [RyujinxHostMappedClient], BDSPBattlePresentationReader
        ] = BDSPBattlePresentationReader,
        box_reader_factory: Callable[
            [RyujinxHostMappedClient], BDSPBoxReader
        ] = BDSPBoxReader,
        inventory_reader_factory: Callable[
            [RyujinxHostMappedClient], BDSPInventoryReader
        ] = BDSPInventoryReader,
        badge_reader_factory: Callable[
            [RyujinxHostMappedClient], BDSPBadgeReader
        ] = BDSPBadgeReader,
        role_layout_getter: Callable[[], int] | None = None,
        tm_profile_getter: Callable[[], BDSPTMProfile | None] | None = None,
        writer_factory: Callable[[RyujinxHostMappedClient], object] | None = None,
        move_catalog_path: Path | str = _MOVE_CATALOG,
        trace_path: Path | str | None = None,
    ) -> None:
        self.client_factory = client_factory or (
            lambda: RyujinxHostMappedClient(BDSP_SP_130_HOST_PROFILE)
        )
        self.party_reader_factory = party_reader_factory
        self.battle_reader_factory = battle_reader_factory
        self.presentation_reader_factory = presentation_reader_factory
        self.box_reader_factory = box_reader_factory
        self.inventory_reader_factory = inventory_reader_factory
        self.badge_reader_factory = badge_reader_factory
        self.role_layout_getter = role_layout_getter or (lambda: 2)
        self.tm_profile_getter = tm_profile_getter or self._discover_tm_profile
        self.writer_factory = writer_factory
        self.move_names = self._load_move_names(Path(move_catalog_path))
        self.trace_path = Path(trace_path) if trace_path is not None else None
        self._trace_started = False
        self._client: RyujinxHostMappedClient | None = None
        # La lectura de 40×30 cajas y el monitor comparten un handle Win32 de
        # solo lectura. Se serializan para que sus dobles lecturas no se mezclen
        # con un reset/cierre concurrente ni publiquen instantes incompatibles.
        self._read_lock = threading.RLock()
        self._battle_identity: tuple[tuple[int, int, int, int, int], ...] = ()
        self._published_battle_hp: dict[int, tuple[int, int]] = {}
        # PokeID cuya barra visible ha entrado en animación para el descenso
        # lógico pendiente. No se limita al cero: la UI del juego empieza a
        # animar cualquier daño después de que BTL_PARTY ya contenga el valor
        # final, por lo que publicar descensos positivos desde esa estructura
        # adelantaba RoleRun a la pantalla física.
        self._battle_hp_animation_seen: set[int] = set()

    @staticmethod
    def _discover_tm_profile() -> BDSPTMProfile | None:
        source = discover_personal_masterdatas()
        return load_bdsp_tm_profile(source) if source is not None else None

    def _writer(self, client: RyujinxHostMappedClient):
        if self.writer_factory is not None:
            return self.writer_factory(client)
        return BDSPLiveWriter(
            client,
            tm_profile_getter=self.tm_profile_getter,
            party_reader_factory=self.party_reader_factory,
            inventory_reader_factory=self.inventory_reader_factory,
            battle_reader_factory=self.battle_reader_factory,
        )

    def _trace(self, payload: dict[str, object]) -> None:
        path = self.trace_path
        if path is None:
            return
        row = {
            "version": APP_VERSION,
            "timestamp": time.time(),
            **payload,
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if self._trace_started else "w"
            with path.open(mode, encoding="utf-8") as stream:
                stream.write(json.dumps(
                    row, ensure_ascii=False, separators=(",", ":"), default=str,
                ))
                stream.write("\n")
            self._trace_started = True
        except OSError:
            # El diagnóstico nunca puede invalidar una captura RAM válida.
            return

    @staticmethod
    def _describir_cambio(change: object) -> dict[str, object]:
        """Lo que identifica un cambio, sin suponer de qué tipo es.

        Se anota para poder volver sobre una escritura después: si el juego se
        queda congelado, saber que se aplicó "1 cambio" no dice qué mirar.
        """
        interesa = (
            "operation", "pokemon", "pokemon_identity", "species",
            "old_role", "new_role", "move_slot", "old_move", "new_move",
            "new_move_id", "tm_number", "item_id", "item_name",
            "quantity_before", "party_slot", "box", "box_slot",
        )
        fila: dict[str, object] = {"tipo": type(change).__name__}
        for nombre in interesa:
            valor = getattr(change, nombre, None)
            if valor is not None:
                fila[nombre] = valor if isinstance(valor, (int, bool)) else str(valor)
        return fila

    def record_ui_event(self, event: str, **fields: object) -> None:
        """Añade una frontera UI compacta al journal BDSP de la sesión."""
        self._trace({"event": str(event), **fields})

    @staticmethod
    def _load_move_names(path: Path) -> dict[int, str]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
            return {
                int(item["id"]): str(
                    item.get("name_es") or item.get("name_en")
                    or f"Movimiento #{item['id']}"
                )
                for item in raw.get("moves", [])
            }
        except (OSError, ValueError, TypeError, KeyError):
            return {}

    def _ensure_client(self) -> RyujinxHostMappedClient:
        if self._client is None:
            client = self.client_factory()
            try:
                client.connect()
            except Exception:
                client.close()
                raise
            self._client = client
        return self._client

    def _discard_client(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            client.close()

    def _party_game(self, raw: BDSPPartyRead, current: SaveGameData) -> SaveGameData:
        try:
            layout = 2 if int(self.role_layout_getter()) >= 2 else 1
        except Exception:
            layout = 1
        party: list[SavePokemon] = []
        try:
            profile = self.tm_profile_getter()
        except Exception:
            profile = None
        for pokemon in raw.pokemon:
            species = species_name(pokemon.species_id)
            role, role_symbol = role_from_markings(pokemon.markings, layout=layout)
            move_ids = [int(value) for value in pokemon.move_ids]
            moves = [
                "—" if move_id == 0 else self.move_names.get(
                    move_id, f"Movimiento #{move_id}",
                )
                for move_id in move_ids
            ]
            training = _training_kwargs(pokemon)
            if profile is not None:
                personal = profile.base_stats(int(pokemon.species_id), int(pokemon.form))
                if personal is not None:
                    training["base_stats"] = stat_dict(personal)
            party.append(SavePokemon(
                slot=int(pokemon.slot),
                species_id=int(pokemon.species_id),
                species=species,
                nickname=str(pokemon.nickname or species),
                level=int(pokemon.level),
                held_item=item_name(pokemon.held_item_id),
                ability=ability_name(pokemon.ability_id),
                moves=moves,
                move_ids=move_ids,
                is_egg=bool(pokemon.is_egg),
                markings=[bool(value) for value in pokemon.markings],
                role=role,
                role_symbol=role_symbol,
                pid=int(pokemon.pid),
                tid=int(pokemon.tid),
                sid=int(pokemon.sid),
                form=int(pokemon.form),
                current_hp=int(pokemon.current_hp),
                max_hp=int(pokemon.max_hp),
                status_condition=int(pokemon.status_condition),
                **training,
            ))
        return SaveGameData(
            game="SP",
            save_type="SAV8BS",
            generation=8,
            trainer=str(current.trainer or ""),
            party=party,
            raw={
                **dict(current.raw or {}),
                "live_source": "Ryujinx HostMappedUnsafe · PlayerWork._playerParty",
                "party_object": int(raw.party_object),
                "party_member_array": int(raw.member_array),
                "party_member_count": int(raw.member_count),
                "writes_enabled": True,
            },
        )

    @staticmethod
    def _strong_identity(pokemon) -> tuple[int, int, int, int]:
        return (
            int(pokemon.species_id), int(pokemon.pid or 0),
            int(pokemon.tid or 0), int(pokemon.sid or 0),
        )

    @staticmethod
    def _diagnostic_identity(identity: tuple[int, int, int, int]) -> str:
        material = ":".join(str(int(value)) for value in identity).encode("ascii")
        return hashlib.sha256(material).hexdigest()[:16]

    def _box_slots(
        self, raw: BDSPBoxRead, anchors,
    ) -> dict[tuple[int, int], SavePokemon]:
        try:
            layout = 2 if int(self.role_layout_getter()) >= 2 else 1
        except Exception:
            layout = 1
        anchors_by_identity: dict[tuple[int, int, int, int], list[SavePokemon]] = {}
        for anchor in tuple(anchors or ()):
            anchors_by_identity.setdefault(self._strong_identity(anchor), []).append(anchor)

        result: dict[tuple[int, int], SavePokemon] = {}
        try:
            profile = self.tm_profile_getter()
        except Exception:
            # Los metadatos derivados son opcionales: su ausencia no invalida
            # una matriz PC cuya identidad y ocupación ya han sido verificadas.
            profile = None
        for pokemon in raw.pokemon:
            identity = self._strong_identity(pokemon)
            matches = anchors_by_identity.get(identity, ())
            anchor = matches[0] if len(matches) == 1 else None
            species = species_name(pokemon.species_id)
            role, role_symbol = role_from_markings(pokemon.markings, layout=layout)
            move_ids = [int(value) for value in pokemon.move_ids]
            moves = [
                "—" if move_id == 0 else self.move_names.get(
                    move_id, f"Movimiento #{move_id}",
                )
                for move_id in move_ids
            ]
            training = _training_kwargs(pokemon)
            level = int(anchor.level) if anchor is not None else 0
            if profile is not None and level <= 0:
                growth = profile.exp_growth(int(pokemon.species_id), int(pokemon.form))
                if growth is not None:
                    level = level_for_experience(int(pokemon.experience), growth)
            if level > 0 and profile is not None:
                base_stats = profile.base_stats(int(pokemon.species_id), int(pokemon.form))
                if base_stats is not None:
                    training["base_stats"] = stat_dict(base_stats)
                    training["stats"] = stat_dict(calculate_bdsp_stats(
                        base_stats, tuple(pokemon.ivs), tuple(pokemon.evs),
                        level, int(pokemon.stat_nature_id),
                    ))
            result[(int(pokemon.box), int(pokemon.slot))] = SavePokemon(
                slot=int(pokemon.slot),
                species_id=int(pokemon.species_id),
                species=species,
                nickname=str(pokemon.nickname or species),
                # El nivel no forma parte del bloque almacenado PB8. Solo se
                # conserva cuando una identidad fuerte única del save/party lo
                # demuestra; nunca se calcula con una curva supuesta.
                level=level,
                held_item=item_name(pokemon.held_item_id),
                ability=ability_name(pokemon.ability_id),
                moves=moves,
                move_ids=move_ids,
                is_egg=bool(pokemon.is_egg),
                markings=[bool(value) for value in pokemon.markings],
                role=role,
                role_symbol=role_symbol,
                box=int(pokemon.box),
                box_slot=int(pokemon.slot),
                pid=int(pokemon.pid),
                tid=int(pokemon.tid),
                sid=int(pokemon.sid),
                form=int(pokemon.form),
                **training,
            )
        return result

    def read_pc(
        self, anchors, *, box_count: int | None = None,
        box_slot_count: int | None = None,
    ) -> tuple[object, int, dict[tuple[int, int], SavePokemon]]:
        """Publica la matriz BDSP demostrada sin habilitar ninguna escritura."""
        if box_count is not None and int(box_count) != 40:
            raise ValueError(f"BDSP SP 1.3.0 declara 40 cajas, no {int(box_count)}.")
        if box_slot_count is not None and int(box_slot_count) != 30:
            raise ValueError(
                f"BDSP SP 1.3.0 declara 30 slots por caja, no {int(box_slot_count)}."
            )
        with self._read_lock:
            client = self._ensure_client()
            raw = self.box_reader_factory(client).read()
            if int(raw.total_slots) != 1200:
                raise ValueError(
                    f"La matriz BDSP publicó {raw.total_slots} slots; se esperaban 1200."
                )
            slots = self._box_slots(raw, anchors)
            self._trace({
                "event": "pc-read",
                "pointer_base": int(raw.pointer_base),
                "total_slots": int(raw.total_slots),
                "empty_slots": int(raw.empty_slots),
                "occupied_slots": len(slots),
                "slots": [
                    {
                        "box": int(box), "slot": int(slot),
                        "species": int(pokemon.species_id),
                        "identity": self._diagnostic_identity(
                            self._strong_identity(pokemon)
                        ),
                    }
                    for (box, slot), pokemon in sorted(slots.items())
                ],
            })
            return client.session.process, int(raw.pointer_base), slots

    def read_tm_inventory(
        self,
        saved_items: Mapping[int, int] | None = None,
        *,
        save_path: Path | str | None = None,
    ) -> tuple[dict[int, int], object, int]:
        """Lee la mochila activa; ``saved_items`` es solo un testigo diagnóstico.

        Una diferencia con el guardado es esperable cuando el jugador obtiene o
        consume un objeto. Nunca se sustituye la muestra RAM por ese valor stale.
        """
        del save_path  # La cadena demostrada pertenece al proceso, no al archivo.
        with self._read_lock:
            client = self._ensure_client()
            raw = self.inventory_reader_factory(client).read()
            if int(raw.total_records) != 3000:
                raise ValueError(
                    f"La mochila BDSP publicó {raw.total_records} registros; se esperaban 3000."
                )
            inventory = {
                int(item.item_id): int(item.count)
                for item in raw.items
                if int(item.item_id) > 0 and int(item.count) > 0
            }
            saved = {
                int(item_id): int(count)
                for item_id, count in (saved_items or {}).items()
                if int(item_id) > 0 and int(count) > 0
            }
            differing_ids = sorted(
                item_id for item_id in set(inventory) | set(saved)
                if inventory.get(item_id, 0) != saved.get(item_id, 0)
            ) if saved_items is not None else []
            self._trace({
                "event": "tm-inventory-read",
                "data_pointer": int(raw.data_pointer),
                "total_records": int(raw.total_records),
                "positive_records": len(inventory),
                "saved_witness_records": len(saved),
                "differing_from_save": differing_ids,
            })
            return inventory, client.session.process, int(raw.data_pointer)

    def apply_changes(self, current: SaveGameData, changes):
        """Aplica roles/movimientos sobre PlayerWork y verifica la transacción."""
        with self._read_lock:
            client = self._ensure_client()
            receipt = self._writer(client).apply(changes)
            game = self._party_game(receipt.party, current)
            game.raw["writes_enabled"] = True
            game.raw["live_write"] = True
            self._trace({
                "event": "write-verified",
                # Antes y después de escribir. Si el reloj se para justo aquí,
                # la escritura es la culpable; si sigue, hay que buscar después.
                "reloj": read_bdsp_play_time(client),
                "foco": tiene_el_foco(int(client.session.process.pid)),
                "applied_count": int(receipt.applied_count),
                "already_applied": bool(receipt.already_applied),
                # Qué se pidió escribir, no solo cuántos bytes. Tras un
                # congelado del juego, "applied_count: 1" no permite reconstruir
                # qué se tocó ni volver a mirarlo leyendo.
                "cambios": [self._describir_cambio(change) for change in changes],
                "watches": [
                    {"address": int(watch.address), "size": len(watch.expected)}
                    for watch in receipt.memory_watches
                ],
            })
            return BDSPRealTimeWriteResult(
                game=game,
                process=receipt.process,
                attempts=int(receipt.attempts),
                applied_count=int(receipt.applied_count),
                memory_watches=tuple(receipt.memory_watches),
                already_applied=bool(receipt.already_applied),
            )

    @staticmethod
    def _battle_state(game: SaveGameData, raw: BDSPBattleRead | None) -> BattleState:
        if raw is None:
            return BattleState("none")
        if int(raw.member_count) != len(game.party):
            raise ValueError(
                f"BTL_PARTY declara {raw.member_count} miembros y PlayerWork {len(game.party)}."
            )
        expected_indices = set(range(len(game.party)))
        observed_indices = {int(pokemon.party_index) for pokemon in raw.pokemon}
        if observed_indices != expected_indices:
            raise ValueError(
                "BTL_PARTY no cubre exactamente los índices de la party activa: "
                f"{sorted(observed_indices)} != {sorted(expected_indices)}."
            )
        by_slot = {int(pokemon.slot) - 1: pokemon for pokemon in game.party}
        battle_hp: dict[int, tuple[int, int]] = {}
        for row in raw.pokemon:
            party = by_slot.get(int(row.party_index))
            if party is None:
                raise ValueError(
                    f"La fila {row.row} apunta al índice de party inexistente {row.party_index}."
                )
            if (
                int(row.species_id) != int(party.species_id)
                or int(row.level) != int(party.level)
                or int(row.max_hp) != int(party.max_hp)
            ):
                raise ValueError(
                    f"La fila {row.row}/PokeID {row.party_index} no coincide con "
                    f"PlayerWork: especie/nivel/HP máx. "
                    f"{row.species_id}/{row.level}/{row.max_hp} != "
                    f"{party.species_id}/{party.level}/{party.max_hp}."
                )
            battle_hp[int(row.party_index)] = (int(row.current_hp), int(row.max_hp))

        health_party = [
            replace(
                pokemon,
                current_hp=battle_hp[index][0],
                max_hp=battle_hp[index][1],
            )
            for index, pokemon in enumerate(game.party)
        ]
        health_game = replace(
            game,
            party=health_party,
            raw={
                **dict(game.raw or {}),
                "health_source": "BattleProc.client.BTL_PARTY",
                "battle_party_object": int(raw.battle_party_object),
                "battle_member_array": int(raw.member_array),
            },
        )
        return BattleState(
            "battle",
            health_game=health_game,
            hp_pairs=tuple(
                (int(pokemon.current_hp), int(pokemon.max_hp))
                for pokemon in health_party
            ),
        )

    def _presentation_gated_battle_state(
        self,
        game: SaveGameData,
        logical: BattleState,
        presentation: BDSPBattlePresentationRead | None,
    ) -> tuple[BattleState, list[dict[str, object]]]:
        """No publica un KO antes de que la barra del mismo PokeID termine.

        La traza física alpha.68 demuestra una separación de 6,17 s entre el
        cero lógico y el inicio de la barra visible. Un temporizador no puede
        representar ataques/efectos de duración distinta. Conservamos el último
        HP positivo publicado hasta observar la secuencia demostrada
        ``currentHP=0/IsAnimation=true`` → ``0/false`` en la BUIStatusWindow
        jugador validada. Si se pierde esa prueba, el fallback seguro es la
        convergencia PlayerWork/salida de combate, nunca el cero lógico precoz.
        """
        if logical.state == "none":
            self._battle_identity = ()
            self._published_battle_hp.clear()
            self._battle_hp_animation_seen.clear()
            return logical, []
        if logical.state != "battle" or logical.health_game is None:
            return logical, []

        identity = tuple(
            (
                int(pokemon.species_id), int(pokemon.pid or 0),
                int(pokemon.tid or 0), int(pokemon.sid or 0),
                int(pokemon.max_hp),
            )
            for pokemon in game.party
        )
        first_sample = identity != self._battle_identity
        if first_sample:
            self._battle_identity = identity
            self._published_battle_hp.clear()
            self._battle_hp_animation_seen.clear()

        windows_by_poke_id: dict[int, list[object]] = {}
        if presentation is not None:
            for window in presentation.windows:
                if not window.is_player or not window.initialized or not window.setup:
                    continue
                windows_by_poke_id.setdefault(int(window.poke_id), []).append(window)

        published_party: list[SavePokemon] = []
        gate_rows: list[dict[str, object]] = []
        for party_index, pokemon in enumerate(logical.health_game.party):
            logical_hp = int(pokemon.current_hp)
            max_hp = int(pokemon.max_hp)
            previous = self._published_battle_hp.get(party_index)
            published_hp = logical_hp
            reason = "logical"

            if first_sample or previous is None or int(previous[1]) != max_hp:
                # La sincronización inicial es baseline. Si ya estaba a cero no
                # se fabrica una muerte retrospectiva esperando una animación.
                reason = "initial-baseline"
            elif logical_hp >= int(previous[0]) or int(previous[0]) <= 0:
                # Curación/subida y valores ya publicados no necesitan esperar
                # una animación de daño. Una nueva subida cancela cualquier
                # descenso anterior que hubiese quedado pendiente.
                reason = "logical-rise" if logical_hp > int(previous[0]) else "logical-stable"
                self._battle_hp_animation_seen.discard(party_index)
            else:
                candidates = windows_by_poke_id.get(party_index, [])
                window = candidates[0] if len(candidates) == 1 else None
                if (
                    window is not None
                    and bool(window.displayed)
                    and int(window.max_hp) == max_hp
                    and int(window.current_hp) == logical_hp
                    and bool(window.hp_animation)
                ):
                    self._battle_hp_animation_seen.add(party_index)
                presentation_complete = bool(
                    window is not None
                    and bool(window.displayed)
                    and int(window.max_hp) == max_hp
                    and int(window.current_hp) == logical_hp
                    and not bool(window.hp_animation)
                    and party_index in self._battle_hp_animation_seen
                )
                if presentation_complete:
                    published_hp = logical_hp
                    self._battle_hp_animation_seen.discard(party_index)
                    reason = (
                        "presentation-zero-animation-complete" if logical_hp == 0
                        else "presentation-damage-animation-complete"
                    )
                else:
                    published_hp = int(previous[0])
                    reason = (
                        "presentation-ambiguous" if len(candidates) > 1
                        else "presentation-pending" if window is not None
                        else "presentation-unavailable"
                    )

            self._published_battle_hp[party_index] = (published_hp, max_hp)
            published_party.append(replace(pokemon, current_hp=published_hp))
            gate_rows.append({
                "party_index": int(party_index),
                "logical_hp": logical_hp,
                "published_hp": int(published_hp),
                "max_hp": max_hp,
                "reason": reason,
            })

        health_game = replace(
            logical.health_game,
            party=published_party,
            raw={
                **dict(logical.health_game.raw or {}),
                "health_source": (
                    "BattleProc.client.BTL_PARTY · "
                    "KO gated by BattleViewUISystem._statusWindows"
                ),
            },
        )
        return BattleState(
            "battle",
            health_game=health_game,
            hp_pairs=tuple(
                (int(pokemon.current_hp), int(pokemon.max_hp))
                for pokemon in published_party
            ),
        ), gate_rows

    def _capture(
        self,
        current: SaveGameData,
        *,
        memory_requests: Sequence[tuple[int, int]],
        sequence: int,
    ) -> RealTimeSnapshot:
        diagnostics: list[LiveDiagnostic] = []
        blocks: list[LiveMemoryBlock] = []
        started = time.perf_counter()
        try:
            client = self._ensure_client()
            party_raw = self.party_reader_factory(client).read()
            game = self._party_game(party_raw, current)
        except Exception as exc:
            self._trace({
                "event": "capture-error",
                "sequence": int(sequence),
                "lane": "party",
                "error": str(exc),
            })
            self._discard_client()
            raise
        diagnostics.append(LiveDiagnostic(
            "party",
            DiagnosticLevel.OK,
            f"PlayerWork estable: {len(game.party)} miembro(s) PB8 validados.",
            "Ryujinx HostMappedUnsafe",
            (time.perf_counter() - started) * 1000,
        ))

        badge_started = time.perf_counter()
        badge_source = "SystemFlags vivos · PlayerWork.SaveData"
        try:
            badge_raw = self.badge_reader_factory(client).read()
            badges = int(badge_raw.count)
            diagnostics.append(LiveDiagnostic(
                "badges",
                DiagnosticLevel.OK,
                f"Medallas BDSP detectadas: {badges}/8.",
                badge_source,
                (time.perf_counter() - badge_started) * 1000,
            ))
        except Exception as exc:
            badges = None
            badge_source = None
            diagnostics.append(LiveDiagnostic(
                "badges",
                DiagnosticLevel.WARNING,
                str(exc) or "No se pudo validar el progreso de medallas BDSP.",
                "PlayerWork.SaveData.systemFlags",
                (time.perf_counter() - badge_started) * 1000,
            ))

        battle_started = time.perf_counter()
        try:
            battle_raw = self.battle_reader_factory(client).read()
            battle = self._battle_state(game, battle_raw)
            diagnostics.append(LiveDiagnostic(
                "battle",
                DiagnosticLevel.OK,
                (
                    "BTL_PARTY validada por PokeID contra PlayerWork."
                    if battle.state == "battle"
                    else "BattleProc inactivo."
                ),
                "BattleProc.client.BTL_PARTY",
                (time.perf_counter() - battle_started) * 1000,
            ))
        except Exception as exc:
            battle = BattleState("unknown")
            diagnostics.append(LiveDiagnostic(
                "battle",
                DiagnosticLevel.WARNING,
                str(exc) or "No se pudo validar BTL_PARTY.",
                "BattleProc.client.BTL_PARTY",
                (time.perf_counter() - battle_started) * 1000,
            ))

        logical_battle = battle
        presentation: BDSPBattlePresentationRead | None = None
        if battle.state == "battle":
            presentation_started = time.perf_counter()
            try:
                presentation = self.presentation_reader_factory(client).read()
                diagnostics.append(LiveDiagnostic(
                    "presentation",
                    DiagnosticLevel.OK,
                    "BUIStatusWindow validada; HP visible y animación observables.",
                    "BattleViewUISystem._statusWindows",
                    (time.perf_counter() - presentation_started) * 1000,
                ))
            except Exception as exc:
                diagnostics.append(LiveDiagnostic(
                    "presentation",
                    DiagnosticLevel.WARNING,
                    str(exc) or "No se pudo validar BUIStatusWindow.",
                    "BattleViewUISystem._statusWindows",
                    (time.perf_counter() - presentation_started) * 1000,
                ))

        battle, gate_rows = self._presentation_gated_battle_state(
            game, logical_battle, presentation,
        )
        held_kos = [
            row for row in gate_rows
            if int(row["logical_hp"]) == 0 and int(row["published_hp"]) > 0
        ]
        if held_kos:
            diagnostics.append(LiveDiagnostic(
                "health-sync",
                DiagnosticLevel.OK,
                "KO lógico retenido hasta terminar la barra visible validada.",
                "BattleViewUISystem._statusWindows",
            ))

        for address, size in memory_requests:
            if int(size) <= 0:
                continue
            try:
                first = client.read_memory(int(address), int(size))
                second = client.read_memory(int(address), int(size))
                if first != second:
                    raise ValueError("el bloque cambió durante la doble lectura")
                blocks.append(LiveMemoryBlock(int(address), second))
            except Exception as exc:
                diagnostics.append(LiveDiagnostic(
                    "memory",
                    DiagnosticLevel.WARNING,
                    f"No se capturó 0x{int(address):X}+{int(size)}: {exc}",
                    "Ryujinx HostMappedUnsafe",
                ))

        session = client.session
        snapshot = RealTimeSnapshot(
            game=game,
            process=LiveProcessInfo(
                emulator="ryujinx",
                process_id=int(session.process.pid),
                title_id=int(session.profile.title_id),
                name=str(session.process.window_title or session.process.exe_name),
            ),
            attempts=1,
            adapter_key=self.key,
            profile=session.profile.key,
            memory_blocks=tuple(blocks),
            battle=battle,
            badges=badges,
            badge_source=badge_source,
            diagnostics=tuple(diagnostics),
            sequence=int(sequence),
            metadata={
                "emulator": "Ryujinx 1.3.3",
                "transport": "HostMappedUnsafe read + transactional write",
                "revision": session.profile.revision,
                "writes_enabled": True,
            },
        )
        self._trace({
            "event": "snapshot",
            "sequence": int(sequence),
            "process_id": int(session.process.pid),
            # El reloj del juego. Es lo único que avanza sin que el jugador
            # haga nada, así que si se repite entre capturas el juego está
            # parado. Pero también se para al perder el foco el emulador -24,5 s
            # medidos solo por abrir RoleRun-, así que sin saber quién tiene la
            # ventana un reloj quieto no dice nada. Parado CON foco es colgado.
            "reloj": read_bdsp_play_time(client),
            "foco": tiene_el_foco(int(session.process.pid)),
            "battle_state": battle.state,
            "badges": badges,
            "badge_source": badge_source,
            "party": [
                {
                    "slot": int(pokemon.slot),
                    "species": int(pokemon.species_id),
                    "hp": int(pokemon.current_hp),
                    "max_hp": int(pokemon.max_hp),
                }
                for pokemon in game.party
            ],
            "battle_health": [] if battle.health_game is None else [
                {
                    "slot": int(pokemon.slot),
                    "species": int(pokemon.species_id),
                    "hp": int(pokemon.current_hp),
                    "max_hp": int(pokemon.max_hp),
                }
                for pokemon in battle.health_game.party
            ],
            "battle_logical_health": [] if logical_battle.health_game is None else [
                {
                    "slot": int(pokemon.slot),
                    "species": int(pokemon.species_id),
                    "hp": int(pokemon.current_hp),
                    "max_hp": int(pokemon.max_hp),
                }
                for pokemon in logical_battle.health_game.party
            ],
            "battle_health_gate": gate_rows,
            "battle_presentation": [] if presentation is None else [
                {
                    "window": int(window.window_index),
                    "displayed": bool(window.displayed),
                    "poke_id": int(window.poke_id),
                    "player": bool(window.is_player),
                    "hp": int(window.current_hp),
                    "max_hp": int(window.max_hp),
                    "needs_hp_apply": bool(window.needs_hp_apply),
                    "hp_animation": bool(window.hp_animation),
                    "initialized": bool(window.initialized),
                    "setup": bool(window.setup),
                }
                for window in presentation.windows
            ],
            "diagnostics": [
                {
                    "lane": diagnostic.lane,
                    "level": diagnostic.level.value,
                    "message": diagnostic.message,
                }
                for diagnostic in diagnostics
            ],
        })
        return snapshot

    def capture_monitor(
        self,
        current: SaveGameData,
        *,
        save_path: Path | str | None,
        memory_requests: Sequence[tuple[int, int]] = (),
        sequence: int = 0,
    ) -> RealTimeSnapshot:
        with self._read_lock:
            return self._capture(current, memory_requests=memory_requests, sequence=sequence)

    def capture_full(
        self,
        current: SaveGameData,
        *,
        save_path: Path | str | None,
        memory_requests: Sequence[tuple[int, int]] = (),
        sequence: int = 0,
    ) -> RealTimeSnapshot:
        # La captura inicial también incluye BattleProc: conectarse con un KO ya
        # presente establece baseline y nunca fabrica una transición retrospectiva.
        with self._read_lock:
            return self._capture(current, memory_requests=memory_requests, sequence=sequence)

    def runtime_state(self) -> dict[str, object]:
        client = self._client
        if client is None:
            return {
                "adapter": self.key,
                "game": self.game_key,
                "connected": False,
                "writes_enabled": True,
                "capabilities": {
                    "progress": "read-live-alpha.77-system-flags-validated",
                },
            }
        session = client.session
        return {
            "adapter": self.key,
            "game": self.game_key,
            "connected": True,
            "process_id": int(session.process.pid),
            "title_id": f"{int(session.profile.title_id):016X}",
            "revision": session.profile.revision,
            "guest_to_host_delta": f"0x{int(session.guest_to_host_delta):X}",
            "writes_enabled": True,
            "capabilities": {
                "progress": "read-live-alpha.77-system-flags-validated",
            },
        }

    def reset_runtime_state(self) -> None:
        with self._read_lock:
            self._discard_client()
            self._trace_started = False
            self._battle_identity = ()
            self._published_battle_hp.clear()
            self._battle_hp_animation_seen.clear()
