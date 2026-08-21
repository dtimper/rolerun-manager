from __future__ import annotations

import time
from pathlib import Path
from typing import Iterable, Sequence

from ..save_engine_client import SaveGameData
from ..xy_live import XYLiveReader, XYLiveWriter
from .adapter import RealTimeAdapterError, RealTimeGameAdapter
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
        default_key = {"azahar": "xy-azahar-rpc", "citra": "xy-citra-gdb"}.get(self.bridge.info.key, f"xy-{self.bridge.info.key}")
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

    def _convert(
        self,
        raw,
        *,
        save_path: Path | str | None,
        sequence: int,
        include_badges: bool,
    ) -> RealTimeSnapshot:
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
            game=raw.game,
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
        return self.reader.read_pc(anchors)

    def diagnostic_memory_requests(self) -> tuple[tuple[int, int], ...]:
        # Inventario/PC pueden estar calibrados también en Citra aunque las
        # medallas sigan usando temporalmente el main. El diagnóstico debe
        # registrar cualquier bloque vivo resuelto por el adaptador.
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


class XYMultiRealTimeAdapter(RealTimeGameAdapter):
    """Selecciona automáticamente Azahar o Citra sin perder compatibilidad.

    La última ruta que funcionó se prueba primero. Si desaparece, el adaptador
    vuelve a sondear el resto. El Core, la UI y los eventos siguen viendo una
    única implementación ``xy``.
    """

    key = "xy-multi"
    game_key = "xy"
    display_name = "Pokémon X / Y"

    def __init__(self, adapters: Iterable[XYRealTimeAdapter]) -> None:
        self.adapters = tuple(adapters)
        if not self.adapters:
            raise ValueError("XYMultiRealTimeAdapter necesita al menos un transporte.")
        self._active: XYRealTimeAdapter | None = None
        self._errors: dict[str, str] = {}

    @property
    def active_adapter(self) -> XYRealTimeAdapter | None:
        return self._active

    def _ordered(self) -> tuple[XYRealTimeAdapter, ...]:
        if self._active is None:
            return self.adapters
        return (self._active, *tuple(a for a in self.adapters if a is not self._active))

    def _capture(self, method: str, current: SaveGameData, **kwargs) -> RealTimeSnapshot:
        errors: list[str] = []
        for adapter in self._ordered():
            try:
                snapshot = getattr(adapter, method)(current, **kwargs)
            except Exception as exc:
                message = str(exc) or type(exc).__name__
                self._errors[adapter.key] = message
                errors.append(f"{adapter.bridge.info.display_name}: {message}")
                if adapter is self._active:
                    self._active = None
                continue
            self._active = adapter
            self._errors.pop(adapter.key, None)
            return snapshot
        raise RealTimeAdapterError(
            "No se encontró X/Y en un emulador compatible. " + " | ".join(errors)
        )

    def prepare_connection(self) -> None:
        """Libera transportes que bloquean el arranque sin seleccionar aún uno.

        Azahar no necesita preparación. Citra sí: su GDB Stub puede detener la
        CPU hasta recibir ``continue``. El transporte activo se decidirá después
        mediante una captura validada; este método no fuerza Citra sobre Azahar.
        """
        errors: list[str] = []
        for adapter in self.adapters:
            try:
                adapter.prepare_connection()
            except Exception as exc:
                # Es normal que un emulador alternativo no esté abierto. Solo
                # conservamos el detalle para diagnóstico; la captura posterior
                # decidirá qué ruta está realmente disponible.
                errors.append(f"{adapter.bridge.info.display_name}: {str(exc) or type(exc).__name__}")
        if errors:
            self._errors["prepare"] = " | ".join(errors)
        else:
            self._errors.pop("prepare", None)

    def capture_monitor(self, current: SaveGameData, *, save_path, memory_requests=(), sequence=0):
        return self._capture(
            "capture_monitor", current, save_path=save_path,
            memory_requests=memory_requests, sequence=sequence,
        )

    def capture_full(self, current: SaveGameData, *, save_path, memory_requests=(), sequence=0):
        return self._capture(
            "capture_full", current, save_path=save_path,
            memory_requests=memory_requests, sequence=sequence,
        )

    def _require_active(self) -> XYRealTimeAdapter:
        if self._active is None:
            raise RealTimeAdapterError("X/Y todavía no está enlazado a Azahar ni Citra.")
        return self._active

    def apply_changes(self, current: SaveGameData, changes):
        return self._require_active().apply_changes(current, changes)

    def read_tm_inventory(self, saved_items=None):
        return self._require_active().read_tm_inventory(saved_items)

    def read_pc(self, anchors, *, box_count: int | None = None, box_slot_count: int | None = None):
        return self._require_active().read_pc(
            anchors, box_count=box_count, box_slot_count=box_slot_count,
        )

    def diagnostic_memory_requests(self) -> tuple[tuple[int, int], ...]:
        return self._active.diagnostic_memory_requests() if self._active is not None else ()

    def runtime_state(self) -> dict[str, object]:
        return {
            "adapter": self.key,
            "game": self.game_key,
            "active": self._active.key if self._active is not None else None,
            "active_emulator": self._active.bridge.info.display_name if self._active is not None else None,
            "errors": dict(self._errors),
            "transports": [adapter.runtime_state() for adapter in self.adapters],
        }

    def reset_runtime_state(self) -> None:
        self._active = None
        self._errors.clear()
        for adapter in self.adapters:
            adapter.reset_runtime_state()
