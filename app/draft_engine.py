from __future__ import annotations

import json
import random
from pathlib import Path


class DraftEngine:
    """Genera drafteos usando IDs estables y nombres localizados."""

    def __init__(self, moves_path: Path, roles_path: Path, catalog_path: Path) -> None:
        if not moves_path.exists() or not catalog_path.exists():
            raise RuntimeError(
                "La base localizada todavía no está preparada. Ejecuta preparar_motor.bat."
            )
        self.pools: dict[str, list[int]] = json.loads(moves_path.read_text(encoding="utf-8-sig"))
        self.roles = json.loads(roles_path.read_text(encoding="utf-8-sig"))
        catalog = json.loads(catalog_path.read_text(encoding="utf-8-sig"))
        self.catalog: dict[int, dict] = {int(m["id"]): m for m in catalog["moves"]}
        metadata_path = catalog_path.with_name("move_rules_metadata.json")
        self.damage_classes: dict[int, str] = {}
        self.speed_status_moves: set[int] = set()
        self.self_healing_damage_moves: set[int] = set()
        if metadata_path.exists():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
                self.damage_classes = {
                    int(move_id): str(category)
                    for move_id, category in metadata.get("damage_classes", {}).items()
                }
                self.speed_status_moves = {
                    int(move_id) for move_id in metadata.get("speed_status_moves", [])
                }
                self.self_healing_damage_moves = {
                    int(move_id) for move_id in metadata.get("self_healing_damage_moves", [])
                }
            except (OSError, ValueError, TypeError):
                self.damage_classes = {}
                self.speed_status_moves = set()
                self.self_healing_damage_moves = set()
        self.allowed_move_ids: set[int] | None = None

    def set_allowed_moves(self, move_ids: list[int] | set[int] | None) -> None:
        """Limita los drafteos a movimientos realmente utilizables en el juego cargado."""
        self.allowed_move_ids = None if move_ids is None else {int(move_id) for move_id in move_ids}

    def _compatible_pool(self, pool_key: str) -> list[int]:
        pool = [int(move_id) for move_id in self.pools.get(pool_key, [])]
        if self.allowed_move_ids is None:
            return pool
        return [move_id for move_id in pool if move_id in self.allowed_move_ids]

    def role_names(self) -> list[str]:
        return list(self.roles.keys())

    def move(self, move_id: int) -> dict:
        return self.catalog.get(move_id, {"id": move_id, "name_es": f"Movimiento #{move_id}", "name_en": ""})

    def damage_class(self, move_id: int) -> str:
        """Devuelve physical, special, status o unknown."""
        return self.damage_classes.get(int(move_id), "unknown")

    def is_speed_status_move(self, move_id: int) -> bool:
        return int(move_id) in self.speed_status_moves

    def is_self_healing_damage_move(self, move_id: int) -> bool:
        return int(move_id) in self.self_healing_damage_moves

    def generate_role(self, role: str) -> list[dict]:
        if role not in self.roles:
            raise ValueError(f"Rol desconocido: {role}")
        results = []
        for category in self.roles[role]:
            pool = self._compatible_pool(category["pool_key"])
            if not pool:
                raise ValueError(
                    f"La categoría {category['pool_key']} no tiene movimientos utilizables en el juego cargado."
                )
            move_id = random.choice(pool)
            move = self.move(move_id)
            results.append({
                "title": category["title"],
                "pool_key": category["pool_key"],
                "move_id": move_id,
                "move": move["name_es"],
                "move_en": move.get("name_en", ""),
            })
        return results

    def reroll(self, pool_key: str, current_move_id: int) -> dict:
        pool = self._compatible_pool(pool_key)
        if not pool:
            raise ValueError(f"No hay movimientos utilizables para la categoría: {pool_key}")
        alternatives = [m for m in pool if m != current_move_id]
        move_id = random.choice(alternatives or pool)
        move = self.move(move_id)
        return {"move_id": move_id, "move": move["name_es"], "move_en": move.get("name_en", "")}
