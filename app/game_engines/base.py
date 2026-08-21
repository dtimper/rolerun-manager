from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from ..save_engine_client import MoveReplaceResult, SaveGameData, SavePCData


class GameEngineError(RuntimeError):
    """Error de compatibilidad o funcionamiento de un motor de juego."""


class GameEngine(ABC):
    """Contrato estable entre la interfaz de RoleRun y cada juego soportado.

    La UI nunca debe conocer detalles de PKHeX.Core ni del formato concreto del
    guardado. Cada plugin traduce estas operaciones comunes al motor nativo.
    """

    key: str
    display_name: str

    @property
    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def read(self, save_path: str | Path) -> SaveGameData: ...

    @abstractmethod
    def valid_moves(self, save_path: str | Path) -> list[int]: ...

    @abstractmethod
    def replace_move(
        self,
        save_path: str | Path,
        output_path: str | Path,
        party_slot: int,
        move_slot: int,
        move_id: int,
    ) -> MoveReplaceResult: ...

    @abstractmethod
    def set_role(
        self,
        save_path: str | Path,
        output_path: str | Path,
        party_slot: int,
        role: str,
    ) -> dict[str, Any]: ...

    @abstractmethod
    def set_item(
        self,
        save_path: str | Path,
        output_path: str | Path,
        item_key: str,
        quantity: int,
    ) -> dict[str, Any]: ...

    @abstractmethod
    def set_money(
        self,
        save_path: str | Path,
        output_path: str | Path,
    ) -> dict[str, Any]: ...

    def read_inventory(self, save_path: str | Path) -> dict[int, int]:
        client = getattr(self, "client", None)
        if client is None:
            raise GameEngineError("Este motor no expone lectura de la mochila.")
        return client.read_inventory(save_path)

    def read_inventory_records(self, save_path: str | Path) -> list[tuple[str, int, int, int]]:
        """Expone el bolsillo de cada objeto cuando el adaptador lo conoce."""
        client = getattr(self, "client", None)
        if client is None:
            raise GameEngineError("Este motor no expone lectura detallada de la mochila.")
        return client.read_inventory_records(save_path)

    def teach_tm(
        self, save_path: str | Path, output_path: str | Path,
        party_slot: int, move_slot: int, move_id: int, item_id: int,
    ) -> dict[str, Any]:
        client = getattr(self, "client", None)
        if client is None:
            raise GameEngineError("Este motor no expone enseñanza de MTs.")
        return client.teach_tm(save_path, output_path, party_slot, move_slot, move_id, item_id)

    def read_boxes(self, save_path: str | Path) -> SavePCData:
        client = getattr(self, "client", None)
        if client is None:
            raise GameEngineError("Este motor no expone acceso al PC.")
        return client.read_boxes(save_path)

    def set_box_role(
        self, save_path: str | Path, output_path: str | Path,
        box: int, box_slot: int, role: str,
    ) -> dict[str, Any]:
        client = getattr(self, "client", None)
        if client is None:
            raise GameEngineError("Este motor no expone cambios de rol dentro del PC.")
        return client.set_box_role(save_path, output_path, box, box_slot, role)

    def party_to_box(
        self, save_path: str | Path, output_path: str | Path, party_slot: int,
        box: int | None = None, box_slot: int | None = None,
    ) -> dict[str, Any]:
        client = getattr(self, "client", None)
        if client is None:
            raise GameEngineError("Este motor no expone movimientos Equipo → PC.")
        return client.party_to_box(save_path, output_path, party_slot, box, box_slot)

    def box_to_party(
        self, save_path: str | Path, output_path: str | Path, box: int, box_slot: int,
        role: str | None = None, remove_move_slots: list[int] | None = None,
    ) -> dict[str, Any]:
        client = getattr(self, "client", None)
        if client is None:
            raise GameEngineError("Este motor no expone movimientos PC → Equipo.")
        return client.box_to_party(save_path, output_path, box, box_slot, role, remove_move_slots)

    def swap_party_box(
        self, save_path: str | Path, output_path: str | Path, party_slot: int,
        box: int, box_slot: int, role: str | None = None,
        remove_move_slots: list[int] | None = None,
    ) -> dict[str, Any]:
        client = getattr(self, "client", None)
        if client is None:
            raise GameEngineError("Este motor no expone intercambios Equipo ↔ PC.")
        return client.swap_party_box(save_path, output_path, party_slot, box, box_slot, role, remove_move_slots)

    @abstractmethod
    def accepts(self, data: SaveGameData) -> bool: ...

    def ensure_compatible(self, data: SaveGameData) -> None:
        if not self.accepts(data):
            raise GameEngineError(
                f"El archivo seleccionado no pertenece a {self.display_name}."
            )
