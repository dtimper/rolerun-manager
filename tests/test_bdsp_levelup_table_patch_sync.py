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
                return tuple(
                    SimpleNamespace(species_form=key, changed=False, patched_indices=())
                    for key in patches
                )

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
            _bdsp_levelup_table_touched=set(),
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
        # Desde el 2026-09-26 se pide la fila de todo lo que algún rol toca:
        # Trueno (0) con el sustituto de Asesino, y Terremoto (1) -que el Mago
        # sí cambiaría- en su vainilla, por si quedó con el de otro rol.
        self.assertEqual(set(patch), {0, 1})
        self.assertNotEqual(patch[0], THUNDER)
        self.assertEqual(patch[1], EARTHQUAKE)
        self.assertIn((229, 0), anchors)
        anchor = anchors[(229, 0)]
        self.assertEqual(anchor.entry_count, 2)

    def test_mago_no_necesita_parchear_nada(self) -> None:
        # Solo la entrada de Trueno (especial): Mago no tiene por qué tocar
        # nada aquí -a diferencia de la tabla completa por defecto, cuya
        # entrada de Terremoto (físico) sí necesitaría sustituto para Mago.
        # Si RoleRun no la ha cambiado en esta sesión, ni siquiera se busca:
        # localizarla cuesta un escaneo de memoria (2026-09-04).
        fake = self._fake(
            role_by_slot={1: "Mago"},
            table={(229, 0): ((THUNDER, 4, 0),)},
        )
        pokemon = self._houndoom(1, [1, 2, 0, 0])
        game = SimpleNamespace(party=[pokemon])
        fake._sync_bdsp_levelup_table_patch(game)
        self.assertEqual(fake._calls, [])

    def test_pasar_de_asesino_a_mago_devuelve_lo_que_el_asesino_cambio(self) -> None:
        """Bug real, 2026-09-26 (Whiscash, Líbero): Asesino→Mago dejaba en la
        tabla los sustitutos de Asesino que el Mago no necesita (Llave Giro),
        porque solo se pedían las entradas que el Mago sustituye."""
        roles = {1: "Asesino"}
        fake = self._fake(role_by_slot=roles, table={(229, 0): ((THUNDER, 4, 0),)})
        game = SimpleNamespace(party=[self._houndoom(1, [1, 2, 0, 0])])
        fake._sync_bdsp_levelup_table_patch(game)
        self.assertNotEqual(fake._calls[-1][0][(229, 0)][0], THUNDER)

        roles[1] = "Mago"
        fake._sync_bdsp_levelup_table_patch(game)
        patches, anchors = fake._calls[-1]
        self.assertEqual(patches[(229, 0)], {0: THUNDER})
        # Y ya devuelta, no se vuelve a pedir en cada sondeo.
        fake._sync_bdsp_levelup_table_patch(game)
        self.assertEqual(len(fake._calls), 2)

    def test_quitarle_el_rol_tambien_devuelve_la_tabla(self) -> None:
        roles = {1: "Asesino"}
        fake = self._fake(role_by_slot=roles, table={(229, 0): ((THUNDER, 4, 0),)})
        game = SimpleNamespace(party=[self._houndoom(1, [1, 2, 0, 0])])
        fake._sync_bdsp_levelup_table_patch(game)
        roles[1] = "SIN ROL"
        fake._sync_bdsp_levelup_table_patch(game)
        self.assertEqual(fake._calls[-1][0][(229, 0)], {0: THUNDER})

    def test_el_ancla_encuentra_la_fila_con_los_sustitutos_de_otro_rol(self) -> None:
        """Si la fila quedó con la tabla de otro rol, el ancla la reconoce;
        un movimiento cualquiera en esa posición, no."""
        import re
        import struct

        roles = {1: "Asesino"}
        fake = self._fake(role_by_slot=roles)
        game = SimpleNamespace(party=[self._houndoom(1, [1, 2, 0, 0])])
        fake._sync_bdsp_levelup_table_patch(game)
        de_asesino = fake._calls[-1][0][(229, 0)]
        roles[1] = "Mago"
        fake._sync_bdsp_levelup_table_patch(game)
        ancla = fake._calls[-1][1][(229, 0)]

        def fila(movs):
            return b"".join(struct.pack("<hh", nivel, mov) for mov, nivel in movs)

        con_asesino = fila([(de_asesino[0], 4), (de_asesino[1], 8)])
        self.assertIsNotNone(re.fullmatch(ancla.search_regex, con_asesino, re.DOTALL))
        vainilla = fila([(THUNDER, 4), (EARTHQUAKE, 8)])
        self.assertIsNotNone(re.fullmatch(ancla.search_regex, vainilla, re.DOTALL))
        # La entrada 0 (Trueno) no la cambia el Mago: solo vainilla o sustitutos conocidos.
        rara = fila([(1, 4), (EARTHQUAKE, 8)])
        self.assertIsNone(re.fullmatch(ancla.search_regex, rara, re.DOTALL))

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

    def _barboach(self, slot: int, species_id: int = 339) -> SimpleNamespace:
        return SimpleNamespace(species_id=species_id, form=0, slot=slot, move_ids=[1, 2, 0, 0])

    def test_prepara_por_adelantado_la_fila_de_su_evolucion(self) -> None:
        """Bug real, 2026-09-26: Barboach (Líbero-Asesino) evolucionó a
        Whiscash y el juego le ofreció su movimiento de evolución sin
        sustituir (Pistola Agua), porque la fila de Whiscash se parcheó 29 s
        después. Ahora la fila de Whiscash ya lleva el mismo rol antes."""
        tabla = {(339, 0): ((THUNDER, 4, 0),), (340, 0): ((THUNDER, 0, 0), (EARTHQUAKE, 40, 1))}
        fake = self._fake(role_by_slot={1: "Asesino"}, table=tabla)
        fake._sync_bdsp_levelup_table_patch(SimpleNamespace(party=[self._barboach(1)]))

        patches, anchors = fake._calls[-1]
        self.assertIn((340, 0), patches)
        self.assertNotEqual(patches[(340, 0)][0], THUNDER)  # el de evolución, ya sustituido
        self.assertIn((340, 0), anchors)

    def test_sin_rol_no_prepara_ninguna_evolucion(self) -> None:
        tabla = {(339, 0): ((THUNDER, 4, 0),), (340, 0): ((THUNDER, 0, 0),)}
        fake = self._fake(role_by_slot={1: "SIN ROL"}, table=tabla)
        fake._sync_bdsp_levelup_table_patch(SimpleNamespace(party=[self._barboach(1)]))
        self.assertTrue(all((340, 0) not in patches for patches, _a in fake._calls))

    def test_la_evolucion_adelantada_no_pisa_a_un_miembro_real_de_esa_especie(self) -> None:
        tabla = {(339, 0): ((THUNDER, 4, 0),), (340, 0): ((THUNDER, 0, 0),)}
        fake = self._fake(role_by_slot={1: "Asesino", 2: "Mago"}, table=tabla)
        game = SimpleNamespace(party=[self._barboach(1), self._barboach(2, species_id=340)])
        fake._sync_bdsp_levelup_table_patch(game)
        # El Whiscash real es Mago: Trueno (especial) no se toca, y la
        # evolución adelantada del Barboach Asesino no puede sustituirlo.
        for patches, _anchors in fake._calls:
            self.assertEqual(patches.get((340, 0), {0: THUNDER}), {0: THUNDER})

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
