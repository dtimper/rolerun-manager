from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path
from typing import Mapping, Sequence

from ..oras_live import (
    ORASLiveReader, ORASLiveWriter, ORAS_TM_POUCH_SIZE,
    ORAS_SAVE_MISC_SIZE, ORAS_SAVE_EVENTWORK_SIZE, ORAS_SAVE_SUBEVENT_SIZE,
    calculate_pk6_stats,
)
from ..pokemon_stats import stat_dict
from ..save_engine_client import SaveGameData
from .adapter import RealTimeGameAdapter
from .bridge import AzaharBridge
from .models import (
    BattleState,
    DiagnosticLevel,
    LiveDiagnostic,
    LiveMemoryBlock,
    LiveProcessInfo,
    RealTimeSnapshot,
)


class ORASRealTimeAdapter(RealTimeGameAdapter):
    """Implementación de referencia del Real-Time Core para ORAS/Azahar."""

    key = "oras-azahar-rpc"
    game_key = "oras"
    display_name = "Pokémon Omega Rubí / Zafiro Alfa"

    def __init__(
        self,
        reader: ORASLiveReader,
        writer: ORASLiveWriter,
        bridge: AzaharBridge | None = None,
    ) -> None:
        self.reader = reader
        self.writer = writer
        # Bridge explícito para que futuros adaptadores no dependan de Azahar.
        # ORASLiveReader mantiene por ahora sus rutinas validadas de bajo nivel.
        self.bridge = bridge or AzaharBridge(reader.client_factory)
        self._last_process_key: tuple[int, str] | None = None

    @staticmethod
    def _process(process) -> LiveProcessInfo:
        return LiveProcessInfo(
            emulator="azahar",
            process_id=int(process.process_id),
            title_id=int(process.title_id),
            name=str(process.name),
        )

    @staticmethod
    def _blocks(blocks) -> tuple[LiveMemoryBlock, ...]:
        return tuple(LiveMemoryBlock(int(block.address), bytes(block.data)) for block in tuple(blocks or ()))

    def _capture_optional_lanes(
        self,
        current: SaveGameData,
        save_path: Path | str | None,
    ) -> tuple[BattleState, int | None, str | None, list[LiveDiagnostic]]:
        diagnostics: list[LiveDiagnostic] = []

        start = time.perf_counter()
        try:
            probe = self.reader.read_battle_probe(current)
            elapsed = (time.perf_counter() - start) * 1000
            if probe is None:
                battle = BattleState("unknown")
                diagnostics.append(LiveDiagnostic(
                    "battle", DiagnosticLevel.WARNING,
                    "La sonda de batalla no respondió; el monitor principal sigue válido.",
                    "Azahar RPC", elapsed,
                ))
            else:
                battle = BattleState(
                    state=str(getattr(probe, "state", "unknown") or "unknown"),
                    health_game=getattr(probe, "health_game", None),
                    hp_pairs=tuple(getattr(probe, "hp_pairs", ()) or ()),
                    opponent_team_size=getattr(probe, "opponent_team_size", None),
                )
                diagnostics.append(LiveDiagnostic(
                    "battle", DiagnosticLevel.OK, "Sonda de batalla disponible.",
                    "Azahar RPC", elapsed,
                ))
        except Exception as exc:
            battle = BattleState("unknown")
            diagnostics.append(LiveDiagnostic(
                "battle", DiagnosticLevel.WARNING, str(exc) or "Fallo de sonda de batalla.",
                "Azahar RPC", (time.perf_counter() - start) * 1000,
            ))

        start = time.perf_counter()
        try:
            badges = self.writer.read_badges(save_path)
            badge_source = self.writer.last_badge_source
            diagnostics.append(LiveDiagnostic(
                "badges", DiagnosticLevel.OK if badges is not None else DiagnosticLevel.WARNING,
                f"Medallas detectadas: {badges}." if badges is not None else "No se obtuvo un valor de medallas.",
                str(badge_source or "ORAS"), (time.perf_counter() - start) * 1000,
            ))
        except Exception as exc:
            badges = None
            badge_source = None
            diagnostics.append(LiveDiagnostic(
                "badges", DiagnosticLevel.WARNING, str(exc) or "Fallo al leer medallas.",
                "ORAS", (time.perf_counter() - start) * 1000,
            ))
        return battle, badges, badge_source, diagnostics

    def _enrich_pokemon(self, pokemon):
        """Añade Personal y stats derivadas sin inventar datos fuera de ROM."""
        personal_for = getattr(self.writer, "personal_for", None)
        if not callable(personal_for):
            return pokemon
        personal = personal_for(int(pokemon.species_id), int(pokemon.form))
        if personal is None:
            return pokemon
        base_stats = stat_dict(tuple(personal.base_stats[index] for index in (0, 1, 2, 4, 5, 3)))
        updates = {"base_stats": base_stats}
        if (
            not pokemon.stats
            and pokemon.nature_id is not None
            and len(pokemon.ivs) == 6
            and len(pokemon.evs) == 6
        ):
            updates["stats"] = calculate_pk6_stats(
                level=int(pokemon.level),
                nature_id=int(pokemon.nature_id),
                personal=personal,
                ivs=pokemon.ivs,
                evs=pokemon.evs,
            )
        changed = {
            name: value
            for name, value in updates.items()
            if getattr(pokemon, name) != value
        }
        return replace(pokemon, **changed) if changed else pokemon

    def _enrich_game(self, game: SaveGameData) -> SaveGameData:
        party = [self._enrich_pokemon(pokemon) for pokemon in game.party]
        if all(enriched is original for enriched, original in zip(party, game.party)):
            return game
        return replace(game, party=party)

    def _convert(
        self,
        raw,
        *,
        save_path: Path | str | None,
        sequence: int,
        include_optional_lanes: bool,
        lane_current: SaveGameData | None = None,
    ) -> RealTimeSnapshot:
        game = self._enrich_game(raw.game)
        diagnostics: list[LiveDiagnostic] = [LiveDiagnostic(
            "party", DiagnosticLevel.OK,
            f"Equipo estable leído en {int(raw.attempts)} intento(s).",
            "Azahar RPC",
        )]
        if include_optional_lanes:
            battle, badges, badge_source, optional = self._capture_optional_lanes(
                lane_current or game, save_path,
            )
            diagnostics.extend(optional)
        else:
            battle, badges, badge_source = BattleState("unknown"), None, None
        self._last_process_key = (int(raw.process.title_id), str(raw.process.name))
        return RealTimeSnapshot(
            game=game,
            process=self._process(raw.process),
            attempts=int(raw.attempts),
            adapter_key=self.key,
            profile="ORAS-1.4",
            memory_blocks=self._blocks(raw.memory_blocks),
            battle=battle,
            badges=badges,
            badge_source=badge_source,
            diagnostics=tuple(diagnostics),
            sequence=int(sequence),
            metadata={"emulator": "Azahar", "transport": "RPC UDP"},
        )

    def capture_monitor(
        self,
        current: SaveGameData,
        *,
        save_path: Path | str | None,
        memory_requests: Sequence[tuple[int, int]] = (),
        sequence: int = 0,
    ) -> RealTimeSnapshot:
        raw = self.reader.read_monitor(current, memory_blocks=memory_requests)
        return self._convert(
            raw, save_path=save_path, sequence=sequence, include_optional_lanes=True,
            lane_current=current,
        )

    def capture_full(
        self,
        current: SaveGameData,
        *,
        save_path: Path | str | None,
        memory_requests: Sequence[tuple[int, int]] = (),
        sequence: int = 0,
    ) -> RealTimeSnapshot:
        # La resincronización inicial/F5 conserva el comportamiento histórico:
        # solo exige que el equipo sea estable. Las sondas opcionales no pueden
        # hacer fallar la entrada a una Run.
        raw = self.reader.read(current, memory_blocks=memory_requests)
        return self._convert(raw, save_path=save_path, sequence=sequence, include_optional_lanes=False)

    def read_tm_inventory(
        self,
        saved_items: Mapping[int, int] | None = None,
    ):
        return self.writer.read_tm_inventory(saved_items)

    def read_pc(self, anchors, *, box_count: int | None = None, box_slot_count: int | None = None):
        process, base_address, slots = self.reader.read_pc(anchors)
        enriched = {
            key: None if pokemon is None else self._enrich_pokemon(pokemon)
            for key, pokemon in slots.items()
        }
        return process, base_address, enriched

    def apply_changes(self, current: SaveGameData, changes):
        return self.writer.apply(current, changes)

    def diagnostic_memory_requests(self) -> tuple[tuple[int, int], ...]:
        """Adjunta al recorder solo bloques pequeños ya calibrados.

        No capturamos las 31 cajas completas en cada tick. PC puede añadirse en
        una captura puntual más adelante si un bug específico lo requiere.
        """
        key = self._last_process_key
        if key is None:
            return ()
        requests: dict[int, int] = {}
        resolver = getattr(self.writer, "block_resolver", None)
        if resolver is not None:
            address = resolver.cached_address(key, "inventory.tm_hm")
            if address is not None:
                requests[int(address)] = ORAS_TM_POUCH_SIZE
        for cache_name, size in (
            ("_misc_bases_by_process", ORAS_SAVE_MISC_SIZE),
            ("_eventwork_bases_by_process", ORAS_SAVE_EVENTWORK_SIZE),
            ("_subevent_bases_by_process", ORAS_SAVE_SUBEVENT_SIZE),
        ):
            cache = getattr(self.writer, cache_name, None)
            if isinstance(cache, dict) and key in cache:
                requests[int(cache[key])] = int(size)
        return tuple((address, requests[address]) for address in sorted(requests))

    def runtime_state(self) -> dict[str, object]:
        key = self._last_process_key
        resolver = getattr(self.writer, "block_resolver", None)
        resolutions: list[dict[str, object]] = []
        if resolver is not None:
            for item in resolver.last_resolutions:
                resolutions.append({
                    "block": item.block_key,
                    "session": item.session_key,
                    "address": item.address,
                    "source": item.source,
                    "cache_hit": item.cache_hit,
                    "score": list(item.score) if item.score is not None else None,
                    "candidates": item.candidate_count,
                    "elapsed_ms": item.elapsed_ms,
                    "success": item.success,
                    "message": item.message,
                })
        legacy: dict[str, str] = {}
        if key is not None:
            for owner_name, owner, cache_name in (
                ("reader", self.reader, "_pc_bases_by_process"),
                ("writer", self.writer, "_pc_bases_by_process"),
                ("writer", self.writer, "_misc_bases_by_process"),
                ("writer", self.writer, "_eventwork_bases_by_process"),
                ("writer", self.writer, "_subevent_bases_by_process"),
                ("writer", self.writer, "_tm_badge_bases_by_process"),
                ("writer", self.writer, "_tm_inventory_bases_by_process"),
            ):
                cache = getattr(owner, cache_name, None)
                if isinstance(cache, dict) and key in cache:
                    legacy[f"{owner_name}.{cache_name}"] = f"0x{int(cache[key]):08X}"
        return {
            "adapter": self.key,
            "game": self.game_key,
            "bridge": {
                "key": self.bridge.info.key,
                "display_name": self.bridge.info.display_name,
                "transport": self.bridge.info.transport,
            },
            "process_key": list(key) if key is not None else None,
            "memory_resolutions": resolutions,
            "legacy_caches": legacy,
        }

    def reset_runtime_state(self) -> None:
        # Las cachés de bloques pertenecen al adaptador ORAS. Evitar limpiar las
        # cachés al comienzo de cada tick; solo se hace al cambiar de sesión.
        for owner, names in (
            (self.reader, ("_pc_bases_by_process",)),
            (self.writer, (
                "_pc_bases_by_process", "_inventory_deltas_by_process",
                "_misc_bases_by_process", "_eventwork_bases_by_process",
                "_subevent_bases_by_process", "_tm_badge_bases_by_process",
                "_tm_inventory_bases_by_process",
            )),
        ):
            for name in names:
                value = getattr(owner, name, None)
                if hasattr(value, "clear"):
                    value.clear()
        resolver = getattr(self.writer, "block_resolver", None)
        if resolver is not None:
            resolver.reset()
        self._last_process_key = None
