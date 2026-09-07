"""Debuffs al rival: pedido por el usuario el 2026-09-05.

Hasta esta fecha, Asesino y Mago sí tenían un pool de movimientos que bajan
una estadística defensiva del rival (``asesino_bajar_defensa``,
``mago_bajar_defensa_esp``), pero Tanque y Prisma no tenían ningún pool
equivalente para bajar una estadística OFENSIVA del rival -la categoría ni
existía-. Por eso Danza Pluma (baja el Ataque rival, un movimiento
claramente defensivo) nunca podía pertenecer a Tanque.

Regla exacta dada por el usuario, simétrica con la de autobuffs ya existente:
- Asesino baja Defensa rival, salvo que también baje Ataque o At. Especial.
- Mago baja Defensa Especial rival, salvo que también baje Ataque o At. Especial.
- Tanque baja Ataque rival, salvo que también baje At. Especial.
- Prisma baja At. Especial rival, salvo que también baje Ataque.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.role_rules import allowed_status_move_ids

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

# Feather Dance (baja Ataque rival, -2). El caso real que destapó el hueco.
FEATHER_DANCE = 297
GROWL = 45
CHARM = 204
BABY_DOLL_EYES = 608
TICKLE = 321  # baja Ataque Y Defensa rival, ninguna es At. Especial: sigue siendo válido para Tanque.
PLAY_NICE = 589

CAPTIVATE = 445
EERIE_IMPULSE = 598  # baja At. Especial rival.

# Bajan Ataque Y At. Especial rival a la vez: no valen ni para Tanque ni para Prisma.
NOBLE_ROAR = 568
TEARFUL_LOOK = 715
MEMENTO = 262


class DebuffsRivalesPorRolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pools = json.loads((DATA / "moves.json").read_text(encoding="utf-8-sig"))
        metadata = json.loads((DATA / "move_rules_metadata.json").read_text(encoding="utf-8-sig"))
        cls.damage_classes = {int(k): str(v) for k, v in metadata["damage_classes"].items()}
        cls.speed_status_moves = {int(v) for v in metadata["speed_status_moves"]}

    def _allowed(self, role: str) -> set[int]:
        allowed = allowed_status_move_ids(role, self.pools, self.damage_classes, self.speed_status_moves)
        assert allowed is not None
        return allowed

    def test_tanque_admite_movimientos_que_bajan_el_ataque_rival(self) -> None:
        allowed = self._allowed("Tanque")
        for move_id in (FEATHER_DANCE, GROWL, CHARM, BABY_DOLL_EYES, PLAY_NICE):
            self.assertIn(move_id, allowed)

    def test_tanque_admite_bajar_ataque_y_defensa_rival_a_la_vez(self) -> None:
        """Tickle baja Ataque Y Defensa del rival. La regla de Tanque solo
        excluye si también baja At. Especial -no dice nada de la Defensa-,
        así que sigue siendo válido."""
        self.assertIn(TICKLE, self._allowed("Tanque"))

    def test_prisma_admite_movimientos_que_bajan_el_ataque_especial_rival(self) -> None:
        allowed = self._allowed("Prisma")
        for move_id in (CAPTIVATE, EERIE_IMPULSE):
            self.assertIn(move_id, allowed)

    def test_tanque_rechaza_movimientos_que_tambien_bajan_el_ataque_especial_rival(self) -> None:
        allowed = self._allowed("Tanque")
        for move_id in (NOBLE_ROAR, TEARFUL_LOOK, MEMENTO):
            self.assertNotIn(move_id, allowed)

    def test_prisma_rechaza_movimientos_que_tambien_bajan_el_ataque_rival(self) -> None:
        allowed = self._allowed("Prisma")
        for move_id in (NOBLE_ROAR, TEARFUL_LOOK, MEMENTO):
            self.assertNotIn(move_id, allowed)

    def test_asesino_y_mago_no_admiten_los_debuffs_ofensivos_de_tanque_y_prisma(self) -> None:
        """Bajar el Ataque o At. Especial del rival no ayuda a un atacante a
        pegar más fuerte -eso lo hace bajar la DEFENSA correspondiente,
        pool ya existente-, así que estos movimientos no deben colarse en
        los pools de Asesino/Mago."""
        for move_id in (FEATHER_DANCE, GROWL, CHARM, CAPTIVATE, EERIE_IMPULSE):
            self.assertNotIn(move_id, self._allowed("Asesino"))
            self.assertNotIn(move_id, self._allowed("Mago"))


if __name__ == "__main__":
    unittest.main()
