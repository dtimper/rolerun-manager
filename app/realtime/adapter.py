from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Mapping, Sequence

from ..save_engine_client import SaveGameData, SavePCData
from .models import RealTimeSnapshot


class RealTimeAdapterError(RuntimeError):
    """Error presentable de un adaptador de tiempo real."""


class RealTimeGameAdapter(ABC):
    """Contrato común entre el Core y la implementación viva de cada juego."""

    key: str
    game_key: str
    display_name: str

    @abstractmethod
    def capture_monitor(
        self,
        current: SaveGameData,
        *,
        save_path: Path | str | None,
        memory_requests: Sequence[tuple[int, int]] = (),
        sequence: int = 0,
    ) -> RealTimeSnapshot: ...

    @abstractmethod
    def capture_full(
        self,
        current: SaveGameData,
        *,
        save_path: Path | str | None,
        memory_requests: Sequence[tuple[int, int]] = (),
        sequence: int = 0,
    ) -> RealTimeSnapshot: ...

    def read_tm_inventory(
        self,
        saved_items: Mapping[int, int] | None = None,
        *,
        save_path: Path | str | None = None,
    ) -> tuple[dict[int, int], object, int]:
        raise RealTimeAdapterError(f"{self.display_name} no expone MT/MO en tiempo real.")

    def read_pc(
        self, anchors, *, box_count: int | None = None, box_slot_count: int | None = None,
    ) -> tuple[object, int, SavePCData]:
        raise RealTimeAdapterError(f"{self.display_name} no expone el PC en tiempo real.")

    def apply_changes(self, current: SaveGameData, changes):
        raise RealTimeAdapterError(f"{self.display_name} no expone escritura en tiempo real.")

    def prepare_connection(self) -> None:
        """Prepara un transporte que necesite handshake antes del primer snapshot.

        La mayoría de emuladores no necesitan nada. Citra, en cambio, puede
        detener el juego al arrancar hasta que un debugger se conecta y envía
        ``continue``. Este hook permite resolver ese requisito sin mezclarlo con
        la lectura del juego ni con la UI.
        """
        return None

    def diagnostic_memory_requests(self) -> tuple[tuple[int, int], ...]:
        """Bloques pequeños que conviene adjuntar mientras se graba diagnóstico.

        Debe evitar regiones grandes (por ejemplo todo el PC). Los adaptadores
        pueden devolver únicamente bloques ya localizados cuya captura ayude a
        reproducir un fallo offline.
        """
        return ()

    def runtime_state(self) -> dict[str, object]:
        """Estado técnico serializable del adaptador para diagnóstico/replay."""
        return {"adapter": self.key, "game": self.game_key}

    def reset_runtime_state(self) -> None:
        """Olvida cachés de proceso/direcciones al cambiar de sesión."""
