from __future__ import annotations

import json
import unittest
import random
from pathlib import Path

from app.draft_engine import DraftEngine
from app.role_rules import (
    ROLE_ORDER,
    ROLE_TO_MARKING,
    allowed_status_move_ids,
    canonical_role,
    damage_move_issue_reason,
    engine_role_name,
    role_from_markings,
)
from app.oras_live import _role_from_markings

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


class Alpha42RoleReworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.moves = json.loads((DATA / "moves.json").read_text(encoding="utf-8-sig"))
        cls.roles = json.loads((DATA / "roles.json").read_text(encoding="utf-8-sig"))
        metadata = json.loads((DATA / "move_rules_metadata.json").read_text(encoding="utf-8-sig"))
        cls.damage_classes = {int(k): str(v) for k, v in metadata["damage_classes"].items()}
        cls.speed_moves = {int(v) for v in metadata["speed_status_moves"]}
        cls.healing_damage = {int(v) for v in metadata["self_healing_damage_moves"]}

    def allowed(self, role: str) -> set[int] | None:
        return allowed_status_move_ids(role, self.moves, self.damage_classes, self.speed_moves)

    def test_requested_visual_role_order(self) -> None:
        self.assertEqual(
            ROLE_ORDER,
            ("Líbero", "Asesino", "Mago", "Tanque", "Prisma", "Support"),
        )
        self.assertEqual(list(self.roles), ["Asesino", "Mago", "Tanque", "Prisma", "Support"])

    def test_old_paladin_name_migrates_to_prisma(self) -> None:
        self.assertEqual(canonical_role("Paladín"), "Prisma")
        self.assertEqual(canonical_role("paladin"), "Prisma")

    def test_physical_markers_follow_requested_role_order(self) -> None:
        expected = {
            "Líbero": 0, "Asesino": 1, "Mago": 2,
            "Tanque": 3, "Prisma": 4, "Support": 5,
        }
        self.assertEqual({role: ROLE_TO_MARKING[role] for role in expected}, expected)
        self.assertEqual(_role_from_markings([False, True, False, False, False, False]), ("Asesino", "▲"))
        self.assertEqual(_role_from_markings([False, False, False, False, True, False]), ("Prisma", "★"))
        self.assertEqual(_role_from_markings([False, False, False, False, False, True]), ("Support", "◆"))

    def test_legacy_layout_can_be_reinterpreted_without_losing_semantic_role(self) -> None:
        # Hasta alpha.42: 2º=Tanque, 3º=Asesino, 5º=Support, 6º=Prisma.
        self.assertEqual(role_from_markings([False, True, False, False, False, False], layout=1)[0], "Tanque")
        self.assertEqual(role_from_markings([False, False, True, False, False, False], layout=1)[0], "Asesino")
        self.assertEqual(role_from_markings([False, False, False, False, True, False], layout=1)[0], "Support")
        self.assertEqual(role_from_markings([False, False, False, False, False, True], layout=1)[0], "Prisma")

    def test_legacy_layout_migrates_to_requested_physical_marker_without_role_loss(self) -> None:
        expected_new_mark = {
            "Líbero": 0, "Tanque": 3, "Asesino": 1,
            "Mago": 2, "Support": 5, "Prisma": 4,
        }
        for old_mark in range(6):
            markings = [index == old_mark for index in range(6)]
            semantic_role = role_from_markings(markings, layout=1)[0]
            self.assertEqual(ROLE_TO_MARKING[semantic_role], expected_new_mark[semantic_role])

    def test_legacy_engine_translation_targets_same_physical_bit(self) -> None:
        self.assertEqual(engine_role_name("Líbero", legacy_engine=True), "Líbero")
        self.assertEqual(engine_role_name("Asesino", legacy_engine=True), "Tanque")
        self.assertEqual(engine_role_name("Mago", legacy_engine=True), "Asesino")
        self.assertEqual(engine_role_name("Tanque", legacy_engine=True), "Mago")
        self.assertEqual(engine_role_name("Prisma", legacy_engine=True), "Support")
        self.assertEqual(engine_role_name("Support", legacy_engine=True), "Paladín")

    def test_tank_status_rules_match_design(self) -> None:
        allowed = self.allowed("Tanque")
        assert allowed is not None
        self.assertIn(339, allowed)   # Bulk Up / Corpulencia: +Atk +Def
        self.assertIn(837, allowed)   # Victory Dance: aumenta Defensa, no Def. Esp.
        self.assertIn(334, allowed)   # Iron Defense
        self.assertIn(182, allowed)   # Protect
        self.assertIn(392, allowed)   # Aqua Ring
        self.assertIn(275, allowed)   # Ingrain
        self.assertNotIn(483, allowed)  # Quiver Dance: Def. Esp., no Defensa
        self.assertNotIn(322, allowed)  # Cosmic Power: aumenta también Def. Esp.
        self.assertNotIn(347, allowed)  # Calm Mind
        self.assertNotIn(105, allowed)  # Recover
        self.assertNotIn(97, allowed)   # Agility ya no es excepción para Tanque

    def test_prism_status_rules_match_design(self) -> None:
        allowed = self.allowed("Prisma")
        assert allowed is not None
        self.assertIn(483, allowed)   # Quiver Dance
        self.assertIn(347, allowed)   # Calm Mind
        self.assertIn(133, allowed)   # Amnesia
        self.assertIn(601, allowed)   # Geomancy
        self.assertIn(92, allowed)    # Toxic: problema de estado directo
        self.assertIn(261, allowed)   # Will-O-Wisp: problema de estado directo
        self.assertNotIn(182, allowed)  # Protect ya no pertenece a Prisma
        self.assertIn(392, allowed)   # Aqua Ring
        self.assertIn(275, allowed)   # Ingrain
        self.assertNotIn(339, allowed)  # Bulk Up: Defensa física
        self.assertNotIn(837, allowed)  # Victory Dance: Defensa física
        self.assertNotIn(322, allowed)  # Cosmic Power: también Defensa física
        self.assertNotIn(105, allowed)  # Recover
        self.assertNotIn(97, allowed)   # Agility sin Def. Esp. no basta

    def test_assassin_mage_and_support_keep_speed_exception(self) -> None:
        self.assertIn(97, self.allowed("Asesino"))
        self.assertIn(97, self.allowed("Mago"))
        self.assertIn(97, self.allowed("Support"))

    def test_tank_and_prism_can_damage_both_sides_but_never_drain(self) -> None:
        for role in ("Tanque", "Prisma"):
            self.assertEqual(damage_move_issue_reason(role, "physical", 33, self.healing_damage), "")
            self.assertEqual(damage_move_issue_reason(role, "special", 53, self.healing_damage), "")
            self.assertTrue(damage_move_issue_reason(role, "physical", 409, self.healing_damage))  # Drain Punch
            self.assertTrue(damage_move_issue_reason(role, "special", 202, self.healing_damage))   # Giga Drain

    def test_defensive_draft_damage_pools_exclude_every_self_healing_attack(self) -> None:
        physical = set(self.moves["defensa_ataque_fisico"])
        special = set(self.moves["defensa_ataque_especial"])
        self.assertFalse(physical.intersection(self.healing_damage))
        self.assertFalse(special.intersection(self.healing_damage))

    def test_draft_categories_match_new_roles(self) -> None:
        self.assertEqual(
            [entry["pool_key"] for entry in self.roles["Tanque"]],
            [
                "tanque_subir_defensa_fisica",
                "tanque_proteccion",
                "defensa_ataque_fisico",
                "defensa_ataque_especial",
            ],
        )
        self.assertEqual(
            [entry["pool_key"] for entry in self.roles["Prisma"]],
            [
                "prisma_subir_defensa_especial",
                "prisma_problemas_estado",
                "defensa_ataque_fisico",
                "defensa_ataque_especial",
            ],
        )
        self.assertEqual(
            [entry["pool_key"] for entry in self.roles["Asesino"]],
            ["asesino_bajar_defensa", "asesino_subir_ataque", "extra_ataque_fisico"],
        )
        self.assertEqual(
            [entry["pool_key"] for entry in self.roles["Mago"]],
            ["mago_bajar_defensa_esp", "mago_subir_ataque_esp", "extra_ataque_especial"],
        )
        self.assertEqual(
            [entry["pool_key"] for entry in self.roles["Support"]],
            [
                "support_infatuaciones",
                "support_problemas_estado",
                "support_recuperaciones",
                "support_hazards",
                "support_ataque_estado",
            ],
        )

    def test_prism_status_draft_respects_the_loaded_games_move_catalog(self) -> None:
        engine = DraftEngine(
            DATA / "moves.json",
            DATA / "roles.json",
            DATA / "move_catalog.json",
        )
        # Tóxico existe en X/Y; Hilo Tóxico (672) pertenece a Gen 7.
        engine.set_allowed_moves({92})

        pool = engine._compatible_pool("prisma_problemas_estado")

        self.assertIn(92, pool)
        self.assertNotIn(672, pool)

    def test_libero_draft_places_three_unique_auxiliaries_before_both_damage_categories(self) -> None:
        engine = DraftEngine(
            DATA / "moves.json",
            DATA / "roles.json",
            DATA / "move_catalog.json",
            rng=random.Random(42),
        )

        results = engine.generate_role("Líbero")
        pool_keys = [entry["pool_key"] for entry in results]

        self.assertEqual(len(results), 5)
        self.assertEqual(pool_keys[-2:], ["extra_ataque_fisico", "extra_ataque_especial"])
        self.assertEqual(len(set(pool_keys)), 5)
        self.assertTrue(
            set(pool_keys[:3]).isdisjoint({
                "extra_ataque_fisico", "extra_ataque_especial",
                "defensa_ataque_fisico", "defensa_ataque_especial",
            })
        )


if __name__ == "__main__":
    unittest.main()
