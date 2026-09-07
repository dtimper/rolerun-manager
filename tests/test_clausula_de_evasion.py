"""Cláusula de evasión: pedida por el usuario el 2026-09-04.

Ningún Pokémon de RoleRun, sea cual sea su rol -incluido Líbero, que
normalmente no tiene ninguna restricción-, puede quedarse con un movimiento
que suba su propia evasión (Doble Equipo #104, Reducción #107). Detectado
al ofrecer Campo de Hierba a un Tanque real vía el sustituto de aprendizajes
de BDSP -no era ese caso, pero destapó que Support tampoco los excluía-.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.role_rules import EVASION_MOVE_IDS, ROLE_ORDER, allowed_status_move_ids, is_evasion_move

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

DOUBLE_TEAM, MINIMIZE = 104, 107


class ClausulaDeEvasionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pools = json.loads((DATA / "moves.json").read_text(encoding="utf-8-sig"))
        metadata = json.loads((DATA / "move_rules_metadata.json").read_text(encoding="utf-8-sig"))
        cls.damage_classes = {int(k): str(v) for k, v in metadata["damage_classes"].items()}
        cls.speed_status_moves = {int(v) for v in metadata["speed_status_moves"]}

    def test_is_evasion_move(self) -> None:
        self.assertTrue(is_evasion_move(DOUBLE_TEAM))
        self.assertTrue(is_evasion_move(MINIMIZE))
        self.assertFalse(is_evasion_move(33))  # Placaje, no tiene nada que ver

    def test_ningun_rol_permite_movimientos_de_evasion(self) -> None:
        for role in ROLE_ORDER:
            allowed = allowed_status_move_ids(role, self.pools, self.damage_classes, self.speed_status_moves)
            if allowed is None:
                # Líbero: "sin restricción" salvo la propia cláusula, que
                # se aplica en compute_species_patch/_needs_substitute, no
                # aquí -este caso se prueba aparte, ver
                # role_levelup_moves_shared-.
                continue
            self.assertFalse(allowed & EVASION_MOVE_IDS, f"{role} no debería admitir movimientos de evasión")

    def test_support_no_admite_movimientos_de_evasion(self) -> None:
        """Antes del 2026-09-04, Support SÍ los admitía: `all_status` incluye
        cualquier movimiento de estado y ninguno de los dos estaba en
        `global_self_boosts`, así que nada los excluía."""
        allowed = allowed_status_move_ids("Support", self.pools, self.damage_classes, self.speed_status_moves)
        assert allowed is not None
        self.assertNotIn(DOUBLE_TEAM, allowed)
        self.assertNotIn(MINIMIZE, allowed)


if __name__ == "__main__":
    unittest.main()
