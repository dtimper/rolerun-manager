"""Aprendizajes por rol en X/Y: red de seguridad tras el parche proactivo.

Mirror de ``tests/test_usum_levelup_moves_backup.py``, pero sin indirección
por ``personal_id`` -X/Y indexa 1:1 por species_id, como ORAS-.

2026-09-05, validado físicamente en la partida real del usuario: Zigzagoon
venía de Asesino, se le cambió a Mago -con el archivo del mod ya corregido
varios segundos antes, incluso reabriendo el menú de equipo del propio
juego-, y aprendió Danza Dragón: el sustituto de ASESINO, no el vainilla
ni el de Mago. Solo un reinicio completo del título lo corregía. En vez de
perseguir esa caché, esta red de seguridad reacciona a lo que de verdad
aparece en los 4 huecos de movimientos, sin importar de dónde viniera.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.models import PendingChange
from app.ui import RoleRunManager

ZIGZAGOON_ID = 263
HYPER_VOICE, DRAGON_DANCE, SLEEP_POWDER = 304, 349, 79


class SyncXyLevelupMovesBackupTests(unittest.TestCase):
    def _fake(self, *, role: str = "Mago", last_written: bytes | None = b"PARCHEADO") -> SimpleNamespace:
        applied: list[set] = []
        announcement_cache_calls: list[tuple] = []
        fake = SimpleNamespace(
            save_engine=SimpleNamespace(key="xy"),
            project=SimpleNamespace(oras_levelup_move_history={}),
            run=SimpleNamespace(pending_changes=[]),
            engine=SimpleNamespace(
                pools={
                    "mago_subir_ataque_esp": [HYPER_VOICE],
                    "asesino_subir_ataque": [DRAGON_DANCE],
                    "mago_bajar_defensa_esp": [], "asesino_bajar_defensa": [],
                },
                damage_classes={
                    HYPER_VOICE: "special", DRAGON_DANCE: "status", SLEEP_POWDER: "status",
                },
                speed_status_moves=set(), self_healing_damage_moves=set(),
                allowed_move_ids=None,
                move=lambda move_id: {"name_es": f"Movimiento {move_id}"},
            ),
            _xy_levelup_backup_known_moves={},
            _xy_levelup_moves_last_written=last_written,
            _effective_role=lambda pokemon: (role, ""),
            _pokemon_identity=lambda pokemon: f"identity-{pokemon.pid}",
            _registrar_intento_vivo=lambda *a, **k: None,
            _request_oras_live_auto_apply_since=lambda before: applied.append(before),
            _sync_xy_levelup_announcement_cache=(
                lambda game, roles, blob: announcement_cache_calls.append((game, roles, blob))
            ),
        )
        fake._xy_levelup_usable_move_ids = RoleRunManager._xy_levelup_usable_move_ids.__get__(fake)
        fake._sync_xy_levelup_moves_backup = (
            RoleRunManager._sync_xy_levelup_moves_backup.__get__(fake)
        )
        # Núcleo común con ORAS desde el 2026-09-26.
        fake._substitute_new_off_role_moves = (
            RoleRunManager._substitute_new_off_role_moves.__get__(fake)
        )
        fake._applied_calls = applied
        fake._announcement_cache_calls = announcement_cache_calls
        return fake

    def _zigzagoon(self, move_ids: list[int], *, level: int = 9) -> SimpleNamespace:
        moves = move_ids + [0] * (4 - len(move_ids))
        return SimpleNamespace(
            species_id=ZIGZAGOON_ID, level=level, pid=111, tid=222, sid=333,
            nickname="", species="Zigzagoon", slot=1, move_ids=moves,
        )

    def test_la_primera_vez_que_ve_un_pokemon_solo_fija_la_base(self) -> None:
        fake = self._fake()
        game = SimpleNamespace(party=[self._zigzagoon([1, 2, 0, 0])])
        fake._sync_xy_levelup_moves_backup(game)
        self.assertEqual(fake.run.pending_changes, [])
        self.assertEqual(fake._xy_levelup_backup_known_moves["111:222:333"], [1, 2, 0, 0])

    def test_sin_movimientos_nuevos_no_hace_nada(self) -> None:
        fake = self._fake()
        pokemon = self._zigzagoon([1, 2, 0, 0])
        game = SimpleNamespace(party=[pokemon])
        fake._sync_xy_levelup_moves_backup(game)
        pokemon.move_ids = [2, 1, 0, 0]  # mismo moveset, solo reordenado
        fake._sync_xy_levelup_moves_backup(game)
        self.assertEqual(fake.run.pending_changes, [])

    def test_un_movimiento_del_rol_anterior_se_sustituye_de_inmediato(self) -> None:
        """El caso real: Zigzagoon venía de Asesino, cambiado a Mago con el
        mod ya corregido desde hacía rato, y aprendió Danza Dragón -el
        sustituto de ASESINO, no el de Mago ni el vainilla-."""
        fake = self._fake(role="Mago")
        pokemon = self._zigzagoon([1, 2, 0, 0])
        game = SimpleNamespace(party=[pokemon])
        fake._sync_xy_levelup_moves_backup(game)  # fija la base

        pokemon.move_ids = [1, 2, DRAGON_DANCE, 0]  # sustituto de Asesino, con Mago ya activo
        fake._sync_xy_levelup_moves_backup(game)

        self.assertEqual(len(fake.run.pending_changes), 1)
        change = fake.run.pending_changes[0]
        self.assertIsInstance(change, PendingChange)
        self.assertEqual(change.move_slot, 3)
        self.assertEqual(change.old_move_id, DRAGON_DANCE)
        self.assertEqual(change.new_move_id, HYPER_VOICE)
        self.assertEqual(change.pokemon_identity, "identity-111")
        self.assertEqual(fake._applied_calls, [set(), set()])
        # Bug real, 2026-09-05: el disparador por cruce de nivel no se
        # rearma si el usuario reinicia el JUEGO sin reiniciar RoleRun -su
        # propio flujo de pruebas- y el nivel vuelve a coincidir con el
        # último visto. Esta red de seguridad no depende de ningún
        # historial de niveles, así que engancha el parcheo del cartel
        # aquí mismo, justo cuando sustituye un movimiento de verdad.
        self.assertEqual(len(fake._announcement_cache_calls), 1)
        _game, roles_sent, blob_sent = fake._announcement_cache_calls[0]
        self.assertEqual(roles_sent, {ZIGZAGOON_ID: "Mago"})
        self.assertEqual(blob_sent, b"PARCHEADO")

    def test_un_movimiento_nuevo_ya_compatible_no_se_toca(self) -> None:
        fake = self._fake(role="Asesino")  # Danza Dragón sí es de Asesino
        pokemon = self._zigzagoon([1, 2, 0, 0])
        game = SimpleNamespace(party=[pokemon])
        fake._sync_xy_levelup_moves_backup(game)

        pokemon.move_ids = [1, 2, DRAGON_DANCE, 0]
        fake._sync_xy_levelup_moves_backup(game)
        self.assertEqual(fake.run.pending_changes, [])
        self.assertEqual(fake._announcement_cache_calls, [])

    def test_declinar_el_aprendizaje_no_deja_nada_pendiente_para_siempre(self) -> None:
        fake = self._fake(role="Mago")
        pokemon = self._zigzagoon([1, 2, 0, 0])
        game = SimpleNamespace(party=[pokemon])
        fake._sync_xy_levelup_moves_backup(game)
        for _ in range(5):
            fake._sync_xy_levelup_moves_backup(game)  # moveset sin cambios
        self.assertEqual(fake.run.pending_changes, [])

    def test_otro_juego_no_hace_nada(self) -> None:
        fake = self._fake()
        fake.save_engine = SimpleNamespace(key="oras")
        game = SimpleNamespace(party=[self._zigzagoon([1, 2, 0, 0])])
        fake._sync_xy_levelup_moves_backup(game)
        self.assertEqual(fake.run.pending_changes, [])
        self.assertEqual(fake._xy_levelup_backup_known_moves, {})


if __name__ == "__main__":
    unittest.main()
