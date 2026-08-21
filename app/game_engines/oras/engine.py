from __future__ import annotations

from pathlib import Path
from typing import Any

from ..base import GameEngine
from ...save_engine_client import MoveReplaceResult, SaveEngineClient, SaveGameData


class ORASEngine(GameEngine):
    """Motor experimental para Pokémon Omega Rubí / Zafiro Alfa."""

    key = "oras"
    display_name = "Pokémon Omega Rubí / Zafiro Alfa"

    def __init__(self, client: SaveEngineClient) -> None:
        self.client = client

    @property
    def available(self) -> bool:
        return self.client.available

    def read(self, save_path: str | Path) -> SaveGameData:
        data = self.client.read(save_path)
        self.ensure_compatible(data)
        return data

    def valid_moves(self, save_path: str | Path) -> list[int]:
        return self.client.valid_moves(save_path)

    def replace_move(
        self,
        save_path: str | Path,
        output_path: str | Path,
        party_slot: int,
        move_slot: int,
        move_id: int,
    ) -> MoveReplaceResult:
        return self.client.replace_move(
            save_path, output_path, party_slot, move_slot, move_id
        )

    def set_role(
        self,
        save_path: str | Path,
        output_path: str | Path,
        party_slot: int,
        role: str,
    ) -> dict[str, Any]:
        return self.client.set_role(save_path, output_path, party_slot, role)

    def set_item(
        self,
        save_path: str | Path,
        output_path: str | Path,
        item_key: str,
        quantity: int,
    ) -> dict[str, Any]:
        return self.client.set_item(save_path, output_path, item_key, quantity)

    def set_money(
        self,
        save_path: str | Path,
        output_path: str | Path,
    ) -> dict[str, Any]:
        return self.client.set_money(save_path, output_path)

    def accepts(self, data: SaveGameData) -> bool:
        game = data.game.strip().upper().replace(" ", "").replace("_", "")
        save_type = data.save_type.strip().upper().replace(" ", "").replace("_", "")
        # PKHeX.Core suele exponer estas ediciones como OR/AS y el guardado
        # como SAV6AO. Se aceptan nombres largos para tolerar cambios en la
        # representación textual del enum GameVersion.
        return (
            game in {"OR", "AS", "ORAS", "OMEGARUBY", "ALPHASAPPHIRE"}
            or "OMEGARUBY" in game
            or "ALPHASAPPHIRE" in game
            or "SAV6AO" in save_type
            or "SAV6ORAS" in save_type
        )
