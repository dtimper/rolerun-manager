"""Aprendizajes por rol en ORAS: red de seguridad tras el parche proactivo.

Mirror de ``tests/test_xy_levelup_moves_backup.py`` (mismo núcleo,
``_substitute_new_off_role_moves``).

2026-09-26, demostrado en la partida real del usuario (Alfa Zafiro
randomizado): Quagsire, Líbero, pasó de imitar al Asesino a imitar al Mago.
El archivo del mod quedó en la tabla de Mago a las 11:04:02 (Maquinación en
el nivel 24) y, al llegar al 24 segundos después, aprendió Afilagarras: el
sustituto de ASESINO de esa entrada, no el de Mago ni el vainilla
(Gravedad). ORAS guarda la tabla igual que X/Y, así que se corrige lo que de
verdad aparece en los 4 huecos.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.models import PendingChange
from app.ui import RoleRunManager

QUAGSIRE_ID = 195
AFILAGARRAS, MAQUINACION, SISMICO, DANZA_ESPADA = 468, 417, 69, 14


class SyncOrasLevelupMovesBackupTests(unittest.TestCase):
    def _fake(self, *, role: str = "Mago", imitado: str | None = None) -> SimpleNamespace:
        applied: list[set] = []
        registros: list[tuple] = []
        fake = SimpleNamespace(
            save_engine=SimpleNamespace(key="oras"),
            project=SimpleNamespace(oras_levelup_move_history={}),
            run=SimpleNamespace(pending_changes=[]),
            engine=SimpleNamespace(
                pools={
                    "mago_subir_ataque_esp": [MAQUINACION],
                    "asesino_subir_ataque": [AFILAGARRAS, DANZA_ESPADA],
                    "mago_bajar_defensa_esp": [], "asesino_bajar_defensa": [],
                },
                damage_classes={
                    AFILAGARRAS: "status", MAQUINACION: "status", SISMICO: "physical",
                    DANZA_ESPADA: "status",
                },
                speed_status_moves=set(), self_healing_damage_moves=set(),
                allowed_move_ids=None,
                move=lambda move_id: {"name_es": f"Movimiento {move_id}"},
            ),
            _oras_levelup_backup_known_moves={},
            _oras_levelup_moves_vanilla_entries={},
            _oras_levelup_backup_known_levels={},
            _effective_role=lambda pokemon: (role, ""),
            _rules_role_for=lambda pokemon, rol, libero_role=None: imitado or "SIN ROL",
            _pokemon_identity=lambda pokemon: f"identity-{pokemon.pid}",
            _registrar_intento_vivo=lambda evento, **k: registros.append((evento, k)),
            _request_oras_live_auto_apply_since=lambda before: applied.append(before),
        )
        fake._oras_levelup_usable_move_ids = RoleRunManager._oras_levelup_usable_move_ids.__get__(fake)
        fake._substitute_new_off_role_moves = RoleRunManager._substitute_new_off_role_moves.__get__(fake)
        fake._oras_levelup_table_substitute = RoleRunManager._oras_levelup_table_substitute.__get__(fake)
        fake._sync_oras_levelup_moves_backup = RoleRunManager._sync_oras_levelup_moves_backup.__get__(fake)
        fake._applied_calls = applied
        fake._registros = registros
        return fake

    def _quagsire(self, move_ids: list[int], *, level: int = 23) -> SimpleNamespace:
        return SimpleNamespace(
            species_id=QUAGSIRE_ID, level=level, pid=111, tid=222, sid=333,
            nickname="", species="Quagsire", slot=1, move_ids=move_ids + [0] * (4 - len(move_ids)),
        )

    def test_el_caso_real_libero_mago_que_aprende_afilagarras(self) -> None:
        fake = self._fake(role="Líbero", imitado="Mago")
        pokemon = self._quagsire([1, 2, SISMICO, 0])
        game = SimpleNamespace(party=[pokemon])
        fake._sync_oras_levelup_moves_backup(game)  # fija la base

        pokemon.level = 24
        pokemon.move_ids = [1, 2, SISMICO, AFILAGARRAS]
        fake._sync_oras_levelup_moves_backup(game)

        self.assertEqual(len(fake.run.pending_changes), 1)
        change = fake.run.pending_changes[0]
        self.assertIsInstance(change, PendingChange)
        self.assertEqual(change.move_slot, 4)
        self.assertEqual(change.old_move_id, AFILAGARRAS)
        self.assertEqual(change.new_move_id, MAQUINACION)
        self.assertEqual(change.pokemon_identity, "identity-111")
        self.assertEqual(fake._applied_calls, [set(), set()])
        self.assertEqual(fake._registros[-1][0], "oras_levelup_backup_sustitucion_encolada")

    def test_un_movimiento_nuevo_ya_compatible_no_se_toca(self) -> None:
        fake = self._fake(role="Líbero", imitado="Asesino")
        pokemon = self._quagsire([1, 2, 0, 0])
        game = SimpleNamespace(party=[pokemon])
        fake._sync_oras_levelup_moves_backup(game)
        pokemon.level, pokemon.move_ids = 24, [1, 2, AFILAGARRAS, 0]
        fake._sync_oras_levelup_moves_backup(game)
        self.assertEqual(fake.run.pending_changes, [])

    def test_un_libero_sin_rol_imitado_no_se_toca(self) -> None:
        fake = self._fake(role="Líbero", imitado=None)
        pokemon = self._quagsire([1, 2, 0, 0])
        game = SimpleNamespace(party=[pokemon])
        fake._sync_oras_levelup_moves_backup(game)
        pokemon.level, pokemon.move_ids = 24, [1, 2, AFILAGARRAS, 0]
        fake._sync_oras_levelup_moves_backup(game)
        self.assertEqual(fake.run.pending_changes, [])

    def test_reiniciar_el_juego_para_bajar_de_nivel_no_sustituye_lo_que_ya_tenia(self) -> None:
        """El flujo de pruebas del usuario: tras reiniciar sin cerrar RoleRun
        reaparecen movimientos aprendidos con el rol anterior. Se marcan en
        rojo como siempre, pero no se cambian solos."""
        fake = self._fake(role="Líbero", imitado="Mago")
        pokemon = self._quagsire([1, 2, MAQUINACION, 0], level=24)
        game = SimpleNamespace(party=[pokemon])
        fake._sync_oras_levelup_moves_backup(game)

        pokemon.level, pokemon.move_ids = 19, [1, 2, AFILAGARRAS, 0]  # partida anterior
        fake._sync_oras_levelup_moves_backup(game)
        self.assertEqual(fake.run.pending_changes, [])

        # Y a partir de ahí vuelve a vigilar con normalidad.
        pokemon.level, pokemon.move_ids = 20, [1, 2, AFILAGARRAS, DANZA_ESPADA]
        fake._sync_oras_levelup_moves_backup(game)
        self.assertEqual([c.old_move_id for c in fake.run.pending_changes], [DANZA_ESPADA])

    def test_un_aprendizaje_con_retraso_en_el_mismo_nivel_si_se_corrige(self) -> None:
        """El diálogo de «¿olvidar un movimiento?» puede terminar un sondeo
        después de que el nivel ya subiera: mismo nivel no es un reinicio."""
        fake = self._fake(role="Líbero", imitado="Mago")
        pokemon = self._quagsire([1, 2, SISMICO, 0])
        game = SimpleNamespace(party=[pokemon])
        fake._sync_oras_levelup_moves_backup(game)
        pokemon.level = 24
        fake._sync_oras_levelup_moves_backup(game)
        pokemon.move_ids = [1, 2, SISMICO, AFILAGARRAS]
        fake._sync_oras_levelup_moves_backup(game)
        self.assertEqual([c.new_move_id for c in fake.run.pending_changes], [MAQUINACION])

    def test_el_sustituto_es_el_de_la_tabla_del_rol_actual_en_ese_nivel(self) -> None:
        """Segunda prueba del usuario (Houndoom, nivel 13): la red de seguridad
        ponía un movimiento de Mago cualquiera (Esfera Aural) en vez del que
        la tabla de Mago marca en ese nivel (Estallido), y el recuerda-
        movimientos -que sí anota el de la tabla- dejaba de coincidir."""
        from app.role_levelup_moves import compute_species_patch

        # Con estos datos el sustituto genérico elegiría 500 y la tabla de
        # Mago pone Maquinación: la prueba distingue los dos caminos.
        otro_mago = 500
        fake = self._fake(role="Líbero", imitado="Mago")
        fake.engine.pools["mago_subir_ataque_esp"] = [MAQUINACION, otro_mago]
        fake.engine.damage_classes[otro_mago] = "status"
        entradas = ((SISMICO, 19, 0), (AFILAGARRAS, 24, 1))  # vainilla de la especie
        fake._oras_levelup_moves_vanilla_entries = {QUAGSIRE_ID: entradas}
        de_la_tabla = compute_species_patch(
            entradas, "Mago", species_id=QUAGSIRE_ID, pools=fake.engine.pools,
            damage_classes=fake.engine.damage_classes, speed_status_moves=set(),
            self_healing_damage_moves=set(), usable_move_ids=set(range(1, 622)),
        )[1]
        self.assertEqual(de_la_tabla, MAQUINACION)

        pokemon = self._quagsire([1, 2, SISMICO, 0])
        game = SimpleNamespace(party=[pokemon])
        fake._sync_oras_levelup_moves_backup(game)
        pokemon.level, pokemon.move_ids = 24, [1, 2, SISMICO, AFILAGARRAS]
        fake._sync_oras_levelup_moves_backup(game)

        self.assertEqual([c.new_move_id for c in fake.run.pending_changes], [de_la_tabla])

    def test_un_movimiento_que_no_sale_de_la_tabla_usa_el_sustituto_de_siempre(self) -> None:
        fake = self._fake(role="Líbero", imitado="Mago")
        fake._oras_levelup_moves_vanilla_entries = {QUAGSIRE_ID: ((SISMICO, 19, 0),)}
        pokemon = self._quagsire([1, 2, 0, 0])
        game = SimpleNamespace(party=[pokemon])
        fake._sync_oras_levelup_moves_backup(game)
        pokemon.level, pokemon.move_ids = 24, [1, 2, AFILAGARRAS, 0]  # p. ej. un tutor
        fake._sync_oras_levelup_moves_backup(game)
        self.assertEqual([c.new_move_id for c in fake.run.pending_changes], [MAQUINACION])

    def test_otro_juego_no_hace_nada(self) -> None:
        fake = self._fake()
        fake.save_engine = SimpleNamespace(key="xy")
        game = SimpleNamespace(party=[self._quagsire([1, 2, 0, 0])])
        fake._sync_oras_levelup_moves_backup(game)
        self.assertEqual(fake._oras_levelup_backup_known_moves, {})

    def test_esta_enganchada_al_sondeo_y_a_la_sincronizacion_inmediata(self) -> None:
        import inspect

        assert "self._sync_oras_levelup_moves_backup(snapshot.game if snapshot else None)" in inspect.getsource(
            RoleRunManager
        )
        assert "self._sync_oras_levelup_moves_backup(self.current_game)" in inspect.getsource(
            RoleRunManager._sync_levelup_tables_now
        )


if __name__ == "__main__":
    unittest.main()
