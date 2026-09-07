"""``compute_species_patch`` es reglas de rol puras, no mecánica de ORAS.

Extraído a ``app/role_levelup_moves.py`` el 2026-09-03 al portar el
aprendizaje por rol a BDSP: la clave de cada entrada es opaca (un offset de
bytes para ORAS, un índice de lista para BDSP) — esta prueba usa un entero
cualquiera como clave para demostrar que la función no asume nada sobre su
significado.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from app import oras_levelup_moves
from app.role_levelup_moves import compute_move_substitute, compute_species_patch

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

THUNDER, EARTHQUAKE = 87, 89


class SharedModuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pools = json.loads((DATA / "moves.json").read_text(encoding="utf-8-sig"))
        metadata = json.loads((DATA / "move_rules_metadata.json").read_text(encoding="utf-8-sig"))
        cls.damage_classes = {int(k): str(v) for k, v in metadata["damage_classes"].items()}
        cls.speed_status_moves = {int(v) for v in metadata["speed_status_moves"]}
        cls.self_healing_damage_moves = {int(v) for v in metadata["self_healing_damage_moves"]}

    def test_oras_levelup_moves_reexporta_la_misma_funcion(self) -> None:
        """``app.oras_levelup_moves.compute_species_patch`` debe ser
        literalmente la del módulo compartido, no una copia."""
        self.assertIs(oras_levelup_moves.compute_species_patch, compute_species_patch)

    def test_la_clave_de_cada_entrada_es_opaca_no_un_offset(self) -> None:
        """Un índice de lista (BDSP) funciona igual que un offset de bytes
        (ORAS): la función solo lo usa como clave del resultado."""
        entries = ((THUNDER, 4, 0), (EARTHQUAKE, 8, 1))
        patch = compute_species_patch(
            entries, "Asesino", species_id=229,
            pools=self.pools, damage_classes=self.damage_classes,
            speed_status_moves=self.speed_status_moves,
            self_healing_damage_moves=self.self_healing_damage_moves,
        )
        # Asesino exige daño físico: Trueno (especial) se sustituye, su
        # clave (índice 0) aparece en el resultado.
        self.assertIn(0, patch)

    def test_libero_no_sustituye_nada_fuera_de_la_clausula_de_evasion(self) -> None:
        entries = ((THUNDER, 4, "clave-cualquiera"),)
        patch = compute_species_patch(
            entries, "Líbero", species_id=229,
            pools=self.pools, damage_classes=self.damage_classes,
            speed_status_moves=self.speed_status_moves,
            self_healing_damage_moves=self.self_healing_damage_moves,
        )
        self.assertEqual(patch, {})

    def test_libero_si_sustituye_un_movimiento_de_evasion(self) -> None:
        """Pedido por el usuario el 2026-09-04: la cláusula de evasión es
        absoluta -ni siquiera Líbero, que normalmente no tiene ninguna
        restricción de rol, puede quedarse con Doble Equipo o Reducción-."""
        DOUBLE_TEAM = 104
        entries = ((DOUBLE_TEAM, 4, "clave-cualquiera"),)
        patch = compute_species_patch(
            entries, "Líbero", species_id=229,
            pools=self.pools, damage_classes=self.damage_classes,
            speed_status_moves=self.speed_status_moves,
            self_healing_damage_moves=self.self_healing_damage_moves,
        )
        self.assertIn("clave-cualquiera", patch)
        self.assertNotEqual(patch["clave-cualquiera"], DOUBLE_TEAM)


class ComputeMoveSubstituteTests(unittest.TestCase):
    """``compute_move_substitute`` — 2026-09-04, USUM: red de seguridad
    para un movimiento que aparece en el equipo sin haberlo predicho de
    antemano (p. ej. el sustituto cacheado de un rol anterior al cambiar
    de rol en USUM, ver rolerun-bug-layout-marcadores-gen7)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.pools = json.loads((DATA / "moves.json").read_text(encoding="utf-8-sig"))
        metadata = json.loads((DATA / "move_rules_metadata.json").read_text(encoding="utf-8-sig"))
        cls.damage_classes = {int(k): str(v) for k, v in metadata["damage_classes"].items()}
        cls.speed_status_moves = {int(v) for v in metadata["speed_status_moves"]}
        cls.self_healing_damage_moves = {int(v) for v in metadata["self_healing_damage_moves"]}

    def test_un_movimiento_incompatible_recibe_sustituto_de_la_clase_correcta(self) -> None:
        substitute = compute_move_substitute(
            THUNDER, "Asesino", species_id=229, level=10,
            pools=self.pools, damage_classes=self.damage_classes,
            speed_status_moves=self.speed_status_moves,
            self_healing_damage_moves=self.self_healing_damage_moves,
        )
        self.assertIsNotNone(substitute)
        self.assertEqual(self.damage_classes.get(substitute), "physical")
        self.assertNotEqual(substitute, THUNDER)

    def test_un_movimiento_ya_compatible_no_recibe_sustituto(self) -> None:
        substitute = compute_move_substitute(
            EARTHQUAKE, "Asesino", species_id=229, level=10,
            pools=self.pools, damage_classes=self.damage_classes,
            speed_status_moves=self.speed_status_moves,
            self_healing_damage_moves=self.self_healing_damage_moves,
        )
        self.assertIsNone(substitute)

    def test_no_elige_un_movimiento_ya_excluido(self) -> None:
        excluded = compute_move_substitute(
            THUNDER, "Asesino", species_id=229, level=10,
            pools=self.pools, damage_classes=self.damage_classes,
            speed_status_moves=self.speed_status_moves,
            self_healing_damage_moves=self.self_healing_damage_moves,
        )
        self.assertIsNotNone(excluded)
        substitute = compute_move_substitute(
            THUNDER, "Asesino", species_id=229, level=10,
            pools=self.pools, damage_classes=self.damage_classes,
            speed_status_moves=self.speed_status_moves,
            self_healing_damage_moves=self.self_healing_damage_moves,
            exclude={excluded},
        )
        self.assertIsNotNone(substitute)
        self.assertNotEqual(substitute, excluded)

    def test_sin_rol_no_sustituye_nada(self) -> None:
        substitute = compute_move_substitute(
            THUNDER, "SIN ROL", species_id=229, level=10,
            pools=self.pools, damage_classes=self.damage_classes,
            speed_status_moves=self.speed_status_moves,
            self_healing_damage_moves=self.self_healing_damage_moves,
        )
        self.assertIsNone(substitute)


if __name__ == "__main__":
    unittest.main()
