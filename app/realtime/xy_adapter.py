from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path
from typing import Sequence

from ..oras_live import calculate_pk6_stats
from ..pokemon_stats import stat_dict
from ..save_engine_client import SaveGameData
from ..xy_live import XYLiveReader, XYLiveWriter
from .adapter import RealTimeGameAdapter
from .bridge import AzaharBridge, EmulatorBridge
from .models import (
    BattleState,
    DiagnosticLevel,
    LiveDiagnostic,
    LiveMemoryBlock,
    LiveProcessInfo,
    RealTimeSnapshot,
)


class XYRealTimeAdapter(RealTimeGameAdapter):
    """Adaptador X/Y para un transporte/emulador concreto."""

    game_key = "xy"
    display_name = "Pokémon X / Y"

    def __init__(
        self,
        reader: XYLiveReader,
        writer: XYLiveWriter,
        bridge: EmulatorBridge | None = None,
        *,
        adapter_key: str | None = None,
        profile: str | None = None,
        live_badges: bool = True,
    ) -> None:
        self.reader = reader
        self.writer = writer
        self.bridge = bridge or AzaharBridge(reader.client_factory)
        default_key = {"azahar": "xy-azahar-rpc"}.get(self.bridge.info.key, f"xy-{self.bridge.info.key}")
        self.key = adapter_key or default_key
        self.profile = profile or f"XY-{self.bridge.info.display_name}"
        self.live_badges = bool(live_badges)
        self._last_process_key: tuple[int, str] | None = None

    def _process(self, process) -> LiveProcessInfo:
        return LiveProcessInfo(
            emulator=self.bridge.info.key,
            process_id=int(process.process_id),
            title_id=int(process.title_id),
            name=str(process.name),
        )

    @staticmethod
    def _blocks(blocks) -> tuple[LiveMemoryBlock, ...]:
        return tuple(
            LiveMemoryBlock(int(block.address), bytes(block.data))
            for block in tuple(blocks or ())
        )

    def _enrich_pokemon(self, pokemon, _cache: dict | None = None):
        """Añade Personal y stats derivadas sin inventar datos fuera de ROM.

        Reportado por el usuario el 2026-09-05 probando X/Y en vivo: el equipo
        salía con "BASE —" en las seis estadísticas, y los Pokémon del PC
        aparecían directamente sin stats. La causa era que este adaptador
        nunca enriquecía lo leído, a diferencia del de ORAS
        (``oras_adapter.ORASRealTimeAdapter._enrich_pokemon``), pese a que
        X/Y comparte el mismo PK6 de sexta generación y ya tiene su tabla
        Personal disponible en el writer (``personal_for``, cableado en
        ``app/ui.py`` con ``_xy_personal_for_live``):

        * el PK6 de PARTY sí trae sus stats calculadas, pero nunca las base;
        * el PK6 ALMACENADO (cajas) no trae ninguna de las dos, así que sin
          este paso el PC no podía enseñar ni stats ni base.

        Se calcula con la misma fórmula ya validada para ORAS
        (``calculate_pk6_stats``), y solo cuando la ROM aporta Personal: si
        no hay perfil cargado, el Pokémon se devuelve tal cual en vez de
        inventar una tabla vanilla.
        """
        personal_for = getattr(self.writer, "personal_for", None)
        if not callable(personal_for):
            return pokemon
        # Una caja llena son 930 huecos: sin memoria por pasada se repetiría la
        # misma búsqueda de Personal cientos de veces.
        key = (int(pokemon.species_id), int(pokemon.form))
        if _cache is not None and key in _cache:
            personal = _cache[key]
        else:
            try:
                personal = personal_for(*key)
            except Exception:
                personal = None
            if _cache is not None:
                _cache[key] = personal
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
            try:
                updates["stats"] = calculate_pk6_stats(
                    level=int(pokemon.level),
                    nature_id=int(pokemon.nature_id),
                    personal=personal,
                    ivs=pokemon.ivs,
                    evs=pokemon.evs,
                )
            except Exception:
                # Nivel/naturaleza fuera de rango en un hueco raro no puede
                # tumbar la lectura entera del PC: se deja sin stats, como antes.
                pass
        changed = {
            name: value
            for name, value in updates.items()
            if getattr(pokemon, name) != value
        }
        return replace(pokemon, **changed) if changed else pokemon

    def _enrich_game(self, game: SaveGameData) -> SaveGameData:
        cache: dict = {}
        party = [self._enrich_pokemon(pokemon, cache) for pokemon in game.party]
        if all(enriched is original for enriched, original in zip(party, game.party)):
            return game
        return replace(game, party=party)

    def _convert(
        self,
        raw,
        *,
        save_path: Path | str | None,
        sequence: int,
        include_badges: bool,
    ) -> RealTimeSnapshot:
        game = self._enrich_game(raw.game)
        source = f"{self.bridge.info.display_name} · {self.bridge.info.transport}"
        diagnostics: list[LiveDiagnostic] = [LiveDiagnostic(
            "party", DiagnosticLevel.OK,
            f"Equipo X/Y estable leído en {int(raw.attempts)} intento(s).",
            source,
        )]
        badges = None
        badge_source = None
        if include_badges:
            started = time.perf_counter()
            try:
                if self.live_badges:
                    badges = self.writer.read_badges(save_path)
                    badge_source = self.writer.last_badge_source
                else:
                    # Fallback de compatibilidad para transportes que todavía no
                    # ofrezcan una fuente viva de Misc.
                    from ..xy_live import parse_xy_saved_badges
                    badges = parse_xy_saved_badges(save_path)
                    badge_source = "main X/Y (fallback temporal)"
                level = DiagnosticLevel.OK if badges is not None else DiagnosticLevel.WARNING
                message = (
                    f"Medallas X/Y detectadas: {badges}."
                    if badges is not None else
                    "Todavía no se pudo resolver el bloque de medallas X/Y."
                )
                diagnostics.append(LiveDiagnostic(
                    "badges", level, message, str(badge_source or "X/Y"),
                    (time.perf_counter() - started) * 1000,
                ))
            except Exception as exc:
                diagnostics.append(LiveDiagnostic(
                    "badges", DiagnosticLevel.WARNING,
                    str(exc) or "Fallo al leer medallas X/Y.", "X/Y",
                    (time.perf_counter() - started) * 1000,
                ))
        battle_started = time.perf_counter()
        try:
            probe = self.reader.read_battle_probe(raw.game)
            elapsed = (time.perf_counter() - battle_started) * 1000
            if probe is None:
                battle = BattleState("unknown")
                diagnostics.append(LiveDiagnostic(
                    "battle", DiagnosticLevel.WARNING,
                    "La sonda de batalla X/Y no respondió; la party overworld sigue funcionando como fallback.",
                    f"X/Y · {self.bridge.info.display_name}", elapsed,
                ))
            else:
                battle = BattleState(
                    state=str(getattr(probe, "state", "unknown") or "unknown"),
                    health_game=getattr(probe, "health_game", None),
                    hp_pairs=tuple(getattr(probe, "hp_pairs", ()) or ()),
                    opponent_identity=getattr(probe, "opponent_identity", None),
                )
                diagnostics.append(LiveDiagnostic(
                    "battle", DiagnosticLevel.OK,
                    f"Sonda de batalla X/Y disponible ({battle.state}).",
                    f"X/Y · {self.bridge.info.display_name}", elapsed,
                ))
        except Exception as exc:
            battle = BattleState("unknown")
            diagnostics.append(LiveDiagnostic(
                "battle", DiagnosticLevel.WARNING,
                str(exc) or "Fallo de sonda de batalla X/Y.",
                f"X/Y · {self.bridge.info.display_name}",
                (time.perf_counter() - battle_started) * 1000,
            ))
        self._last_process_key = (int(raw.process.title_id), str(raw.process.name))
        return RealTimeSnapshot(
            game=game,
            process=self._process(raw.process),
            attempts=int(raw.attempts),
            adapter_key=self.key,
            profile=self.profile,
            memory_blocks=self._blocks(raw.memory_blocks),
            battle=battle,
            badges=badges,
            badge_source=badge_source,
            diagnostics=tuple(diagnostics),
            sequence=int(sequence),
            metadata={
                "emulator": self.bridge.info.display_name,
                "transport": self.bridge.info.transport,
                "experimental": True,
            },
        )

    def prepare_connection(self) -> None:
        self.bridge.prepare_connection()

    def capture_monitor(
        self,
        current: SaveGameData,
        *,
        save_path: Path | str | None,
        memory_requests: Sequence[tuple[int, int]] = (),
        sequence: int = 0,
    ) -> RealTimeSnapshot:
        raw = self.reader.read_monitor(current, memory_blocks=memory_requests)
        return self._convert(raw, save_path=save_path, sequence=sequence, include_badges=True)

    def capture_full(
        self,
        current: SaveGameData,
        *,
        save_path: Path | str | None,
        memory_requests: Sequence[tuple[int, int]] = (),
        sequence: int = 0,
    ) -> RealTimeSnapshot:
        raw = self.reader.read(current, memory_blocks=memory_requests)
        return self._convert(raw, save_path=save_path, sequence=sequence, include_badges=True)

    def apply_changes(self, current: SaveGameData, changes):
        return self.writer.apply(current, changes)

    def read_tm_inventory(self, saved_items=None):
        return self.writer.read_tm_inventory(saved_items)

    def read_pc(self, anchors, *, box_count: int | None = None, box_slot_count: int | None = None):
        process, base_address, slots = self.reader.read_pc(anchors)
        # El PK6 almacenado no trae stats ni base: sin este paso el PC de X/Y
        # se veía entero con "—" (reportado 2026-09-05). Mismo enriquecido que
        # ya hace ORAS en su adaptador.
        cache: dict = {}
        enriched = {
            key: None if pokemon is None else self._enrich_pokemon(pokemon, cache)
            for key, pokemon in slots.items()
        }
        return process, base_address, enriched

    def diagnostic_memory_requests(self) -> tuple[tuple[int, int], ...]:
        # Inventario/PC pueden estar calibrados aunque las medallas sigan
        # usando temporalmente el main. El diagnóstico debe registrar
        # cualquier bloque vivo resuelto por el adaptador.
        return self.writer.runtime_memory_requests()

    def runtime_state(self) -> dict[str, object]:
        resolutions = []
        for item in self.writer.block_resolver.last_resolutions:
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
        return {
            "adapter": self.key,
            "game": self.game_key,
            "bridge": {
                "key": self.bridge.info.key,
                "display_name": self.bridge.info.display_name,
                "transport": self.bridge.info.transport,
            },
            "process_key": list(self._last_process_key) if self._last_process_key else None,
            "memory_resolutions": resolutions,
            "capabilities": {
                "party": "read-write",
                "roles": "read-write",
                "moves": "read-write",
                "badges": "read-live-with-save-fallback" if self.live_badges else "save-fallback-temporary",
                "battle": "read-live-with-postbattle-fallback",
                "pc": "read-live",
                "tm_inventory": "read-live",
                "inventory_utilities": "read-write-verified",
            },
        }

    def reset_runtime_state(self) -> None:
        self._last_process_key = None
        self.writer.reset_runtime_state()
