"""Aprendizajes por rol en BDSP: sustitución posterior en RAM, no un mod.

Pedido por el usuario el 2026-09-03, tras cerrar la función en ORAS: la
misma idea para BDSP, que corre en Ryujinx sin mecanismo de LayeredFS
demostrado (memoria ``rolerun-viabilidad-aprendizajes-por-rol``). Se deja
que el juego enseñe el movimiento vainilla y se sustituye reescribiendo el
mismo hueco, reutilizando el camino que ya usa cualquier cambio de
movimiento confirmado por el usuario (``PendingChange`` +
``_request_oras_live_auto_apply_since``).
"""

from __future__ import annotations

import json
import unittest
import unittest.mock
from pathlib import Path
from types import SimpleNamespace

from app.models import PendingChange
from app.ui import RoleRunManager

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

THUNDER, EARTHQUAKE = 87, 89


class SyncBdspLevelupMovesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pools = json.loads((DATA / "moves.json").read_text(encoding="utf-8-sig"))
        metadata = json.loads((DATA / "move_rules_metadata.json").read_text(encoding="utf-8-sig"))
        cls.damage_classes = {int(k): str(v) for k, v in metadata["damage_classes"].items()}
        cls.speed_status_moves = {int(v) for v in metadata["speed_status_moves"]}
        cls.self_healing_damage_moves = {int(v) for v in metadata["self_healing_damage_moves"]}

    def _fake(self, *, role: str = "Mago", table=None) -> SimpleNamespace:
        applied: list[set] = []
        intentos: list[tuple[str, dict]] = []
        fake = SimpleNamespace(
            save_engine=SimpleNamespace(key="bdsp"),
            project=SimpleNamespace(oras_levelup_move_history={}),
            project_service=SimpleNamespace(save=lambda _project: None),
            run=SimpleNamespace(pending_changes=[]),
            engine=SimpleNamespace(
                pools=self.pools, damage_classes=self.damage_classes,
                speed_status_moves=self.speed_status_moves,
                self_healing_damage_moves=self.self_healing_damage_moves,
                allowed_move_ids=None,
                move=lambda move_id: {"name_es": f"Movimiento {move_id}"},
            ),
            _bdsp_levelup_table=table if table is not None else {
                (229, 0): ((THUNDER, 4, 0), (EARTHQUAKE, 8, 1)),
            },
            _bdsp_levelup_last_levels={},
            _bdsp_levelup_pending={},
            _ensure_bdsp_levelup_table_loaded=lambda: None,
            _effective_role=lambda pokemon: (role, ""),
            _pokemon_identity=lambda pokemon: f"identity-{pokemon.pid}",
            _registrar_intento_vivo=lambda evento, **k: (
                intentos.append((evento, k)),
                (_ for _ in ()).throw(AssertionError(f"{evento}: {k}"))
                if "error" in str(evento) else None,
            ),
            _request_oras_live_auto_apply_since=lambda before: applied.append(before),
        )
        fake._bdsp_levelup_usable_move_ids = RoleRunManager._bdsp_levelup_usable_move_ids.__get__(fake)
        fake._append_bdsp_levelup_history_record = (
            RoleRunManager._append_bdsp_levelup_history_record.__get__(fake)
        )
        fake._append_bdsp_levelup_history_entries = (
            RoleRunManager._append_bdsp_levelup_history_entries.__get__(fake)
        )
        fake._sync_bdsp_levelup_moves = RoleRunManager._sync_bdsp_levelup_moves.__get__(fake)
        fake._applied_calls = applied
        fake._intentos = intentos
        return fake

    def _houndoom(self, level: int, move_ids: list[int]) -> SimpleNamespace:
        moves = move_ids + [0] * (4 - len(move_ids))
        return SimpleNamespace(
            species_id=229, level=level, pid=111, tid=222, sid=333, form=0,
            nickname="", species="Houndoom", slot=1, move_ids=moves,
        )

    def test_la_primera_vez_que_ve_un_pokemon_solo_fija_la_base(self) -> None:
        fake = self._fake()
        game = SimpleNamespace(party=[self._houndoom(2, [1, 2, 0, 0])])
        fake._sync_bdsp_levelup_moves(game)
        self.assertEqual(fake.run.pending_changes, [])
        self.assertEqual(fake._bdsp_levelup_last_levels["111:222:333"], 2)

    def test_cruzar_un_nivel_sin_que_el_juego_haya_escrito_aun_deja_pendiente(self) -> None:
        fake = self._fake(role="Asesino")  # exige físico: Trueno sí necesita sustituto
        fake._bdsp_levelup_last_levels["111:222:333"] = 2
        # El Pokémon ya subió a 5 (cruza el nivel 4), pero el juego todavía
        # no escribió Trueno en ningún hueco -diálogo sin resolver todavía-.
        game = SimpleNamespace(party=[self._houndoom(5, [1, 2, 0, 0])])
        fake._sync_bdsp_levelup_moves(game)
        self.assertEqual(fake.run.pending_changes, [])
        self.assertIn("111:222:333", fake._bdsp_levelup_pending)

    def test_el_historial_se_registra_al_cruzar_aunque_el_juego_no_lo_confirme(self) -> None:
        """Pedido por el usuario el 2026-09-04: igual que ya hace ORAS
        (``_record_oras_levelup_move_history``), recuerda-movimientos debe
        mostrar lo que le toca por su rol en el instante del cruce, no solo
        cuando el jugador confirma el diálogo del juego -si lo rechaza o lo
        deja sin resolver, el movimiento debe seguir apareciendo igual-."""
        fake = self._fake(role="Asesino")
        fake._bdsp_levelup_last_levels["111:222:333"] = 2
        # El diálogo del juego nunca se resuelve: el hueco nunca cambia.
        game = SimpleNamespace(party=[self._houndoom(5, [1, 2, 0, 0])])
        fake._sync_bdsp_levelup_moves(game)

        self.assertEqual(fake.run.pending_changes, [])
        historial = fake.project.oras_levelup_move_history["111:222:333"]
        self.assertEqual(len(historial), 1)
        self.assertEqual(historial[0]["level"], 4)
        self.assertNotEqual(historial[0]["move_id"], THUNDER)  # ya sustituido
        self.assertEqual(historial[0]["role"], "Asesino")
        self.assertFalse(historial[0]["pre_capture"])

    def test_cuando_el_juego_escribe_el_vainilla_se_sustituye(self) -> None:
        fake = self._fake(role="Mago")  # Mago exige daño especial
        fake._bdsp_levelup_last_levels["111:222:333"] = 2
        pokemon = self._houndoom(5, [1, 2, 0, 0])
        game = SimpleNamespace(party=[pokemon])
        fake._sync_bdsp_levelup_moves(game)  # cruza el nivel, queda pendiente

        # El juego ya escribió Trueno (especial) en el hueco 3. Mago lo
        # acepta -Trueno es especial-, así que NO debería sustituirse.
        pokemon.move_ids = [1, 2, THUNDER, 0]
        fake._sync_bdsp_levelup_moves(game)
        self.assertEqual(fake.run.pending_changes, [])

    def test_asesino_exige_fisico_y_sustituye_trueno(self) -> None:
        fake = self._fake(role="Asesino")  # Asesino exige daño físico
        fake._bdsp_levelup_last_levels["111:222:333"] = 2
        pokemon = self._houndoom(5, [1, 2, 0, 0])
        game = SimpleNamespace(party=[pokemon])
        fake._sync_bdsp_levelup_moves(game)

        pokemon.move_ids = [1, 2, THUNDER, 0]
        fake._sync_bdsp_levelup_moves(game)

        self.assertEqual(len(fake.run.pending_changes), 1)
        change = fake.run.pending_changes[0]
        self.assertIsInstance(change, PendingChange)
        self.assertEqual(change.move_slot, 3)
        self.assertEqual(change.old_move_id, THUNDER)
        self.assertNotEqual(change.new_move_id, THUNDER)
        self.assertEqual(change.pokemon_identity, "identity-111")
        # Una llamada por sondeo, siempre -aunque no haya nada nuevo que
        # aplicar en la primera, mientras el diálogo del juego no se resolvía-.
        self.assertEqual(fake._applied_calls, [set(), set()])
        # Ya resuelta: no debe quedar pendiente ni volver a duplicarse.
        self.assertNotIn("111:222:333", fake._bdsp_levelup_pending)
        # Recuerda-movimientos: la sustitución CONFIRMADA queda registrada,
        # con el movimiento que de verdad se escribió -no Trueno-.
        historial = fake.project.oras_levelup_move_history["111:222:333"]
        self.assertEqual(len(historial), 1)
        self.assertEqual(historial[0]["level"], 4)
        self.assertEqual(historial[0]["move_id"], change.new_move_id)
        self.assertEqual(historial[0]["role"], "Asesino")
        self.assertFalse(historial[0]["pre_capture"])
        fake.run.pending_changes.clear()
        fake._sync_bdsp_levelup_moves(game)
        self.assertEqual(fake.run.pending_changes, [])
        # No se duplica en el historial al volver a sondear ya resuelto.
        self.assertEqual(len(fake.project.oras_levelup_move_history["111:222:333"]), 1)

    def test_el_parche_proactivo_ya_resuelto_registra_historial_sin_pending_change(self) -> None:
        """Pedido por el usuario el 2026-09-03: si el parche proactivo de la
        tabla en vivo (Enfoque A, ``_sync_bdsp_levelup_table_patch``) llegó
        a tiempo, el juego enseña directamente el sustituto y el vainilla
        nunca aparece -este método (Enfoque B) debe reconocerlo igual como
        resuelto, sin crear ningún PendingChange, y registrar el historial."""
        fake = self._fake(role="Asesino")
        fake._bdsp_levelup_last_levels["111:222:333"] = 2
        pokemon = self._houndoom(5, [1, 2, 0, 0])
        game = SimpleNamespace(party=[pokemon])
        fake._sync_bdsp_levelup_moves(game)

        pending = fake._bdsp_levelup_pending["111:222:333"]
        self.assertEqual(len(pending), 1)
        _vanilla, substitute, _known_before, _role, _entry_level, _expires_at = next(iter(pending))

        # El parche proactivo ya escribió el sustituto directamente en la
        # tabla en vivo: el juego lo enseña sin que el vainilla aparezca
        # nunca en ningún hueco.
        pokemon.move_ids = [1, 2, substitute, 0]
        fake._sync_bdsp_levelup_moves(game)

        self.assertEqual(fake.run.pending_changes, [])
        self.assertNotIn("111:222:333", fake._bdsp_levelup_pending)
        historial = fake.project.oras_levelup_move_history["111:222:333"]
        self.assertEqual(len(historial), 1)
        self.assertEqual(historial[0]["move_id"], substitute)
        self.assertEqual(historial[0]["role"], "Asesino")
        self.assertFalse(historial[0]["pre_capture"])
        self.assertIn(
            "bdsp_levelup_confirmado_por_parche_proactivo",
            [nombre for nombre, _ in fake._intentos],
        )

        # No se duplica al volver a sondear ya resuelto.
        fake._sync_bdsp_levelup_moves(game)
        self.assertEqual(len(fake.project.oras_levelup_move_history["111:222:333"]), 1)

    def test_ver_por_primera_vez_a_un_pokemon_ya_crecido_retro_rellena_sin_rol(self) -> None:
        """Pedido por el usuario el 2026-09-03: recuerda-movimientos también
        para BDSP, igual que ya existe para ORAS -incluido el retro-relleno
        de lo aprendido antes de que RoleRun lo gestionara."""
        fake = self._fake(role="Asesino")
        # Ya llega al nivel 10, sin que RoleRun lo haya visto nunca antes:
        # pasó los niveles 4 y 8 de la tabla sin que RoleRun estuviera ahí.
        pokemon = self._houndoom(10, [THUNDER, EARTHQUAKE, 0, 0])
        game = SimpleNamespace(party=[pokemon])
        fake._sync_bdsp_levelup_moves(game)

        historial = fake.project.oras_levelup_move_history["111:222:333"]
        self.assertEqual({(item["level"], item["move_id"]) for item in historial}, {(4, THUNDER), (8, EARTHQUAKE)})
        self.assertTrue(all(item["role"] == "SIN ROL" for item in historial))
        self.assertTrue(all(item["pre_capture"] for item in historial))
        # No hay sustitución en vivo por el retro-relleno: es solo historial.
        self.assertEqual(fake.run.pending_changes, [])

    def test_el_retro_relleno_solo_pasa_una_vez_en_toda_la_run(self) -> None:
        fake = self._fake(role="Asesino")
        fake.project.oras_levelup_move_history["111:222:333"] = [
            {"level": 4, "move_id": THUNDER, "role": "SIN ROL", "species_id": 229,
             "nickname": "Houndoom", "recorded_at": "", "pre_capture": True},
        ]
        pokemon = self._houndoom(10, [THUNDER, EARTHQUAKE, 0, 0])
        game = SimpleNamespace(party=[pokemon])
        fake._sync_bdsp_levelup_moves(game)
        # Solo la entrada que ya existía: no se duplica ni se rellena la de
        # nivel 8 por una «primera vez» que en realidad no lo es.
        self.assertEqual(len(fake.project.oras_levelup_move_history["111:222:333"]), 1)

    def test_un_movimiento_que_ya_tenia_de_antes_no_se_toca(self) -> None:
        """No fue ESTE aprendizaje el que lo puso ahí: no hay que sustituirlo."""
        fake = self._fake(role="Asesino")
        fake._bdsp_levelup_last_levels["111:222:333"] = 2
        # Trueno ya estaba en el equipo ANTES de cruzar el nivel 4.
        pokemon = self._houndoom(5, [1, THUNDER, 0, 0])
        game = SimpleNamespace(party=[pokemon])
        fake._sync_bdsp_levelup_moves(game)
        self.assertEqual(fake.run.pending_changes, [])
        self.assertNotIn("111:222:333", fake._bdsp_levelup_pending)

    def test_libero_nunca_sustituye_nada(self) -> None:
        fake = self._fake(role="Líbero")
        fake._bdsp_levelup_last_levels["111:222:333"] = 2
        pokemon = self._houndoom(5, [1, 2, THUNDER, 0])
        game = SimpleNamespace(party=[pokemon])
        fake._sync_bdsp_levelup_moves(game)
        self.assertEqual(fake.run.pending_changes, [])
        self.assertNotIn("111:222:333", fake._bdsp_levelup_pending)

    def test_sin_tabla_cargada_no_hace_nada(self) -> None:
        fake = self._fake(table={})
        game = SimpleNamespace(party=[self._houndoom(5, [1, 2, 0, 0])])
        fake._sync_bdsp_levelup_moves(game)
        self.assertEqual(fake.run.pending_changes, [])
        self.assertEqual(fake._bdsp_levelup_last_levels, {})

    def test_otro_juego_no_hace_nada(self) -> None:
        fake = self._fake()
        fake.save_engine = SimpleNamespace(key="oras")
        game = SimpleNamespace(party=[self._houndoom(5, [1, 2, THUNDER, 0])])
        fake._sync_bdsp_levelup_moves(game)
        self.assertEqual(fake.run.pending_changes, [])

    def test_una_espera_muy_larga_sin_ver_el_movimiento_se_abandona(self) -> None:
        # Se abandona solo cuando se agotan AMBOS márgenes -por nivel Y por
        # tiempo real-, para que un salto de nivel enorme de una sola vez no
        # descarte una entrada antes de que el jugador pueda confirmar el
        # diálogo en cadena del juego (ver BDSP_LEVELUP_PENDING_GRACE_SECONDS).
        fake = self._fake(role="Asesino")
        fake._bdsp_levelup_last_levels["111:222:333"] = 2
        pokemon = self._houndoom(5, [1, 2, 0, 0])
        game = SimpleNamespace(party=[pokemon])
        with unittest.mock.patch("app.ui.time.monotonic", return_value=1_000.0):
            fake._sync_bdsp_levelup_moves(game)  # queda pendiente en nivel 5

        # Sube mucho más sin que el hueco 3 llegue a tener Trueno nunca, pero
        # todavía dentro del margen de tiempo: sigue pendiente.
        pokemon.level = 30
        fake._bdsp_levelup_last_levels["111:222:333"] = 29
        with unittest.mock.patch("app.ui.time.monotonic", return_value=1_010.0):
            fake._sync_bdsp_levelup_moves(game)
        self.assertIn("111:222:333", fake._bdsp_levelup_pending)

        # Pasado también el margen de tiempo: ahora sí se abandona.
        with unittest.mock.patch("app.ui.time.monotonic", return_value=1_000.0 + 999.0):
            fake._sync_bdsp_levelup_moves(game)
        self.assertNotIn("111:222:333", fake._bdsp_levelup_pending)
        self.assertEqual(fake.run.pending_changes, [])


class RecuerdaMovimientosAdmiteBdspTests(unittest.TestCase):
    """El candado de ``_open_oras_levelup_history`` ya no es solo ORAS."""

    def test_la_fuente_admite_oras_y_bdsp(self) -> None:
        """Los juegos que pueden abrir RECUERDA MOVIMIENTOS.

        06-09-2026: quinta se suma con su propio historial
        (`_record_gen5_levelup_move_history`), así que la lista deja de ser un
        literal suelto y se compone con `MELONDS_GEN5_REALTIME_GAME_KEYS`.
        """
        import inspect

        from app.ui import MELONDS_GEN5_REALTIME_GAME_KEYS

        fuente = inspect.getsource(RoleRunManager._open_oras_levelup_history)
        assert '{"oras", "bdsp", "usum", "sm", "xy"}' in fuente
        assert "MELONDS_GEN5_REALTIME_GAME_KEYS" in fuente
        assert {"b2w2", "bw"} <= MELONDS_GEN5_REALTIME_GAME_KEYS


if __name__ == "__main__":
    unittest.main()
