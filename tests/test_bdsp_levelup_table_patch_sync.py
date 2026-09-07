"""``_sync_bdsp_levelup_table_patch``: Enfoque A para BDSP (parche proactivo).

Pedido por el usuario el 2026-09-03 tras rechazar que el diálogo del juego
muestre el movimiento vainilla ("estaría enseñando a ciegas"). Demostrado en
vivo contra la partida real (Staravia, ver memoria
``rolerun-viabilidad-aprendizajes-por-rol``): el propio diálogo del juego
lee la tabla en vivo, así que parchearla antes de que el jugador confirme
hace que ya muestre el nombre correcto.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.ui import RoleRunManager

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

THUNDER, EARTHQUAKE = 87, 89


class SyncBdspLevelupTablePatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pools = json.loads((DATA / "moves.json").read_text(encoding="utf-8-sig"))
        metadata = json.loads((DATA / "move_rules_metadata.json").read_text(encoding="utf-8-sig"))
        cls.damage_classes = {int(k): str(v) for k, v in metadata["damage_classes"].items()}
        cls.speed_status_moves = {int(v) for v in metadata["speed_status_moves"]}
        cls.self_healing_damage_moves = {int(v) for v in metadata["self_healing_damage_moves"]}

    def _fake(self, *, role_by_slot: dict[int, str], table=None) -> SimpleNamespace:
        calls: list[tuple[dict, dict]] = []

        class _Adapter:
            def sync_levelup_table(self, patches, anchors):
                calls.append((dict(patches), dict(anchors)))
                return ()

        fake = SimpleNamespace(
            save_engine=SimpleNamespace(key="bdsp"),
            engine=SimpleNamespace(
                pools=self.pools, damage_classes=self.damage_classes,
                speed_status_moves=self.speed_status_moves,
                self_healing_damage_moves=self.self_healing_damage_moves,
                allowed_move_ids=None,
            ),
            _bdsp_levelup_table=table if table is not None else {
                (229, 0): ((THUNDER, 4, 0), (EARTHQUAKE, 8, 1)),
            },
            _ensure_bdsp_levelup_table_loaded=lambda: None,
            _effective_role=lambda pokemon: (role_by_slot[pokemon.slot], ""),
            _registrar_intento_vivo=lambda evento, **k: (
                (_ for _ in ()).throw(AssertionError(f"{evento}: {k}"))
                if "error" in str(evento) else None
            ),
            bdsp_realtime_adapter=_Adapter(),
        )
        fake._bdsp_levelup_usable_move_ids = RoleRunManager._bdsp_levelup_usable_move_ids.__get__(fake)
        fake._sync_bdsp_levelup_table_patch = (
            RoleRunManager._sync_bdsp_levelup_table_patch.__get__(fake)
        )
        fake._calls = calls
        return fake

    def _houndoom(self, slot: int, move_ids: list[int]) -> SimpleNamespace:
        moves = move_ids + [0] * (4 - len(move_ids))
        return SimpleNamespace(species_id=229, form=0, slot=slot, move_ids=moves)

    def test_asesino_pide_parchear_trueno_por_un_sustituto_fisico(self) -> None:
        fake = self._fake(role_by_slot={1: "Asesino"})
        pokemon = self._houndoom(1, [1, 2, 0, 0])
        game = SimpleNamespace(party=[pokemon])
        fake._sync_bdsp_levelup_table_patch(game)

        self.assertEqual(len(fake._calls), 1)
        patches, anchors = fake._calls[0]
        self.assertIn((229, 0), patches)
        patch = patches[(229, 0)]
        self.assertEqual(set(patch), {0})  # solo la entrada de Trueno (índice 0)
        self.assertNotEqual(patch[0], THUNDER)
        self.assertIn((229, 0), anchors)
        anchor = anchors[(229, 0)]
        self.assertEqual(anchor.entry_count, 2)

    def test_mago_no_necesita_parchear_nada(self) -> None:
        # Solo la entrada de Trueno (especial): Mago no tiene por qué tocar
        # nada aquí -a diferencia de la tabla completa por defecto, cuya
        # entrada de Terremoto (físico) sí necesitaría sustituto para Mago.
        fake = self._fake(
            role_by_slot={1: "Mago"},
            table={(229, 0): ((THUNDER, 4, 0),)},
        )
        pokemon = self._houndoom(1, [1, 2, 0, 0])
        game = SimpleNamespace(party=[pokemon])
        fake._sync_bdsp_levelup_table_patch(game)
        self.assertEqual(fake._calls, [])

    def test_misma_especie_distinto_rol_gana_el_de_menor_slot(self) -> None:
        fake = self._fake(role_by_slot={1: "Asesino", 2: "Mago"})
        primero = self._houndoom(1, [1, 2, 0, 0])
        segundo = self._houndoom(2, [1, 2, 0, 0])
        game = SimpleNamespace(party=[segundo, primero])  # orden de lectura no importa
        fake._sync_bdsp_levelup_table_patch(game)

        self.assertEqual(len(fake._calls), 1)
        patches, _anchors = fake._calls[0]
        # Solo el slot 1 (Asesino) determina el parche; el slot 2 (Mago, que
        # no necesitaría tocar nada) no puede anular ni alternar el valor.
        self.assertIn((229, 0), patches)
        self.assertNotEqual(patches[(229, 0)][0], THUNDER)

    def test_sin_tabla_cargada_no_hace_nada(self) -> None:
        fake = self._fake(role_by_slot={1: "Asesino"}, table={})
        pokemon = self._houndoom(1, [1, 2, 0, 0])
        game = SimpleNamespace(party=[pokemon])
        fake._sync_bdsp_levelup_table_patch(game)
        self.assertEqual(fake._calls, [])

    def test_otro_motor_no_hace_nada(self) -> None:
        fake = self._fake(role_by_slot={1: "Asesino"})
        fake.save_engine = SimpleNamespace(key="oras")
        pokemon = self._houndoom(1, [1, 2, 0, 0])
        game = SimpleNamespace(party=[pokemon])
        fake._sync_bdsp_levelup_table_patch(game)
        self.assertEqual(fake._calls, [])


if __name__ == "__main__":
    unittest.main()
