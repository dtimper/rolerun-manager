from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..save_engine_client import SaveGameData


_LIVE_BADGE_SOURCE_PREFIXES = (
    # B2/W2: un bit por medalla, cuatro bytes detrás del dinero ya demostrado.
    "melonDS vivo ·",
    "Premios líderes ·",
    "SUBE vivo",
    "EventWork vivo ·",
    "Misc vivo",
    "Z-Crystals vivos ·",
    "SystemFlags vivos ·",
)


def badge_source_is_live(source: str | None) -> bool:
    """True solo para las procedencias RAM declaradas por los adapters actuales.

    Una procedencia nueva o ausente queda cerrada por defecto hasta incorporarla
    explícitamente a este contrato común con su prueba correspondiente.
    """
    return str(source or "").startswith(_LIVE_BADGE_SOURCE_PREFIXES)


class DiagnosticLevel(str, Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class LiveProcessInfo:
    """Identidad del proceso de juego, independiente del emulador concreto."""

    emulator: str
    process_id: int
    title_id: int
    name: str


@dataclass(frozen=True, slots=True)
class LiveMemoryBlock:
    """Bloque auxiliar capturado junto al estado vivo principal."""

    address: int
    data: bytes


@dataclass(frozen=True, slots=True)
class LiveDiagnostic:
    """Estado de un carril del Real-Time Core.

    Un fallo en un carril opcional (por ejemplo, batalla) no invalida el carril
    principal. Esto evita que una animación o una estructura transitoria tumbe
    toda la sincronización.
    """

    lane: str
    level: DiagnosticLevel
    message: str
    source: str = ""
    elapsed_ms: float | None = None


@dataclass(frozen=True, slots=True)
class BattleState:
    state: str = "unknown"  # wild | trainer | none | unknown
    health_game: SaveGameData | None = None
    hp_pairs: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True, slots=True)
class RealTimeSnapshot:
    """Instantánea común consumida por RoleRun, independientemente del juego.

    ``game`` es siempre la vista viva estable del equipo. El resto de carriles
    viajan en el mismo objeto para que UI, OBS y automatismos no consulten
    fuentes diferentes durante un mismo ciclo lógico.
    """

    game: SaveGameData
    process: LiveProcessInfo
    attempts: int
    adapter_key: str
    profile: str
    memory_blocks: tuple[LiveMemoryBlock, ...] = ()
    battle: BattleState = field(default_factory=BattleState)
    badges: int | None = None
    badge_source: str | None = None
    diagnostics: tuple[LiveDiagnostic, ...] = ()
    captured_at: float = field(default_factory=time.time)
    sequence: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def healthy(self) -> bool:
        return not any(item.level is DiagnosticLevel.ERROR for item in self.diagnostics)

    def diagnostic(self, lane: str) -> LiveDiagnostic | None:
        target = str(lane).casefold()
        return next((item for item in self.diagnostics if item.lane.casefold() == target), None)
