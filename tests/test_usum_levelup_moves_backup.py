"""Aprendizajes por rol en USUM: red de seguridad tras el parche proactivo.

2026-09-04, rediseñado tras validarlo en la partida real del usuario: un
primer diseño (calcado de BDSP, predecía de antemano el movimiento vainilla
exacto y esperaba a verlo aparecer) no cubría un caso real — Registeel venía
de Prisma, se le cambió a Mago, y aprendió Somnífero: ni el vainilla ni el
sustituto de Mago, sino el sustituto que USUM tenía cacheado de cuando aún
era Prisma. Ni el vainilla ni el sustituto esperado llegaban a aparecer
nunca, así que la sustitución se quedaba esperando para siempre.

El diseño actual no predice nada: compara los 4 huecos de movimientos
contra el sondeo anterior, y para cualquier movimiento NUEVO que aparezca
comprueba si es compatible con el rol ACTUAL en ese mismo instante — sin
importar de dónde viniera. Si no lo es, lo sustituye ahí mismo.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.models import PendingChange
from app.ui import RoleRunManager

VENUSAUR_ID = 3
LEAF_STORM, PSYCHO_CUT, SLEEP_POWDER = 437, 427, 79


class SyncUsumLevelupMovesBackupTests(unittest.TestCase):
    def _fake(self, *, role: str = "Mago") -> SimpleNamespace:
        applied: list[set] = []
        fake = SimpleNamespace(
            save_engine=SimpleNamespace(key="usum"),
            project=SimpleNamespace(oras_levelup_move_history={}),
            run=SimpleNamespace(pending_changes=[]),
            engine=SimpleNamespace(
                pools={
                    "extra_ataque_especial": [LEAF_STORM],
                    "extra_ataque_fisico": [PSYCHO_CUT],
                    "mago_bajar_defensa_esp": [], "mago_subir_ataque_esp": [],
                },
                damage_classes={LEAF_STORM: "special", PSYCHO_CUT: "physical", SLEEP_POWDER: "status"},
                speed_status_moves=set(), self_healing_damage_moves=set(),
                allowed_move_ids=None,
                move=lambda move_id: {"name_es": f"Movimiento {move_id}"},
            ),
            _usum_levelup_backup_known_moves={},
            _usum_levelup_personal_id_map={(VENUSAUR_ID, 0): VENUSAUR_ID},
            _effective_role=lambda pokemon: (role, ""),
            _pokemon_identity=lambda pokemon: f"identity-{pokemon.pid}",
            _registrar_intento_vivo=lambda *a, **k: None,
            _request_oras_live_auto_apply_since=lambda before: applied.append(before),
        )
        fake._usum_levelup_usable_move_ids = RoleRunManager._usum_levelup_usable_move_ids.__get__(fake)
        fake._usum_levelup_personal_id_for = RoleRunManager._usum_levelup_personal_id_for.__get__(fake)
        fake._sync_usum_levelup_moves_backup = (
            RoleRunManager._sync_usum_levelup_moves_backup.__get__(fake)
        )
        fake._applied_calls = applied
        return fake

    def _venusaur(self, move_ids: list[int], *, level: int = 20) -> SimpleNamespace:
        moves = move_ids + [0] * (4 - len(move_ids))
        return SimpleNamespace(
            species_id=VENUSAUR_ID, level=level, pid=111, tid=222, sid=333, form=0,
            nickname="", species="Venusaur", slot=1, move_ids=moves,
        )

    def test_la_primera_vez_que_ve_un_pokemon_solo_fija_la_base(self) -> None:
        fake = self._fake()
        game = SimpleNamespace(party=[self._venusaur([1, 2, 0, 0])])
        fake._sync_usum_levelup_moves_backup(game)
        self.assertEqual(fake.run.pending_changes, [])
        self.assertEqual(fake._usum_levelup_backup_known_moves["111:222:333"], [1, 2, 0, 0])

    def test_sin_movimientos_nuevos_no_hace_nada(self) -> None:
        fake = self._fake()
        pokemon = self._venusaur([1, 2, 0, 0])
        game = SimpleNamespace(party=[pokemon])
        fake._sync_usum_levelup_moves_backup(game)
        # Mismo moveset, solo reordenado — no es un aprendizaje nuevo.
        pokemon.move_ids = [2, 1, 0, 0]
        fake._sync_usum_levelup_moves_backup(game)
        self.assertEqual(fake.run.pending_changes, [])

    def test_un_movimiento_nuevo_incompatible_se_sustituye_de_inmediato(self) -> None:
        """El caso real: Registeel venía de Prisma, cambiado a Mago, y
        aprendió el sustituto de Prisma (ni vainilla ni el de Mago) — no
        hace falta predecir qué iba a aprender, solo reaccionar a lo que
        de verdad apareció."""
        fake = self._fake(role="Mago")
        pokemon = self._venusaur([1, 2, 0, 0])
        game = SimpleNamespace(party=[pokemon])
        fake._sync_usum_levelup_moves_backup(game)  # fija la base

        pokemon.move_ids = [1, 2, PSYCHO_CUT, 0]  # aprendió algo físico, viniendo de quien sea
        fake._sync_usum_levelup_moves_backup(game)

        self.assertEqual(len(fake.run.pending_changes), 1)
        change = fake.run.pending_changes[0]
        self.assertIsInstance(change, PendingChange)
        self.assertEqual(change.move_slot, 3)
        self.assertEqual(change.old_move_id, PSYCHO_CUT)
        self.assertEqual(change.new_move_id, LEAF_STORM)
        self.assertEqual(change.pokemon_identity, "identity-111")
        self.assertEqual(fake._applied_calls, [set(), set()])

    def test_un_movimiento_nuevo_ya_compatible_no_se_toca(self) -> None:
        fake = self._fake(role="Asesino")  # Asesino acepta físico
        pokemon = self._venusaur([1, 2, 0, 0])
        game = SimpleNamespace(party=[pokemon])
        fake._sync_usum_levelup_moves_backup(game)

        pokemon.move_ids = [1, 2, PSYCHO_CUT, 0]
        fake._sync_usum_levelup_moves_backup(game)
        self.assertEqual(fake.run.pending_changes, [])

    def test_declinar_el_aprendizaje_no_deja_nada_pendiente_para_siempre(self) -> None:
        """Si el jugador no acepta el movimiento, el moveset nunca cambia
        — no debe quedar ninguna sustitución esperando indefinidamente."""
        fake = self._fake(role="Mago")
        pokemon = self._venusaur([1, 2, 0, 0])
        game = SimpleNamespace(party=[pokemon])
        fake._sync_usum_levelup_moves_backup(game)
        for _ in range(5):
            fake._sync_usum_levelup_moves_backup(game)  # moveset sin cambios
        self.assertEqual(fake.run.pending_changes, [])

    def test_otro_juego_no_hace_nada(self) -> None:
        fake = self._fake()
        fake.save_engine = SimpleNamespace(key="oras")
        game = SimpleNamespace(party=[self._venusaur([1, 2, 0, 0])])
        fake._sync_usum_levelup_moves_backup(game)
        self.assertEqual(fake.run.pending_changes, [])
        self.assertEqual(fake._usum_levelup_backup_known_moves, {})


if __name__ == "__main__":
    unittest.main()
