"""``_sync_sm_levelup_moves_mod``/``_record_sm_levelup_move_history``.

Mirror de ``tests/test_usum_levelup_moves_sync.py``: SM comparte el mismo
motor/generación que USUM (confirmado el 2026-09-04 contra la ROM real del
usuario, ver ``app/sm_levelup_moves.py``), así que la tabla de aprendizajes
también indexa por ``personal_id`` (formas incluidas), traducido desde
``(species_id, form)`` con ``self._sm_levelup_personal_id_map``.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.ui import RoleRunManager

VENUSAUR_ID, VENUSAUR_MEGA_PERSONAL_ID = 3, 843


class SyncCacheTests(unittest.TestCase):
    def _fake(self, *, personal_id_map=None) -> SimpleNamespace:
        fake = SimpleNamespace(
            save_engine=SimpleNamespace(key="sm"),
            project=SimpleNamespace(oras_levelup_move_history={}),
            project_service=SimpleNamespace(save=lambda _project: None),
            engine=SimpleNamespace(
                pools={}, damage_classes={}, speed_status_moves=set(),
                self_healing_damage_moves=set(), allowed_move_ids=None,
            ),
            _sm_levelup_moves_vanilla=b"VANILLA",
            _sm_levelup_moves_title_id=1,
            _sm_levelup_moves_azahar_root=SimpleNamespace(),
            _sm_levelup_moves_vanilla_entries={},
            _sm_levelup_moves_last_written=None,
            _sm_levelup_moves_last_roles_key=None,
            _sm_levelup_personal_id_map=(
                personal_id_map if personal_id_map is not None
                else {(VENUSAUR_ID, 0): VENUSAUR_ID, (VENUSAUR_ID, 1): VENUSAUR_MEGA_PERSONAL_ID}
            ),
            _sm_levelup_history_last_levels={},
            _effective_role=lambda pokemon: ("Mago", ""),
            _registrar_intento_vivo=lambda *a, **k: None,
        )
        fake._sm_levelup_usable_move_ids = RoleRunManager._sm_levelup_usable_move_ids.__get__(fake)
        fake._sm_levelup_personal_id_for = RoleRunManager._sm_levelup_personal_id_for.__get__(fake)
        fake._append_sm_levelup_history_entries = (
            RoleRunManager._append_sm_levelup_history_entries.__get__(fake)
        )
        fake._purge_sm_levelup_history_above_level = (
            RoleRunManager._purge_sm_levelup_history_above_level.__get__(fake)
        )
        fake._record_sm_levelup_move_history = (
            RoleRunManager._record_sm_levelup_move_history.__get__(fake)
        )
        return fake

    def _venusaur(self, *, form: int = 0, level: int = 10, pid: int = 1) -> SimpleNamespace:
        return SimpleNamespace(
            species_id=VENUSAUR_ID, form=form, level=level, pid=pid, tid=2, sid=3,
            nickname="", species="Venusaur",
        )

    def test_dos_sondeos_seguidos_con_los_mismos_roles_no_recalculan_el_parche(self) -> None:
        fake = self._fake()
        game = SimpleNamespace(party=[self._venusaur()])
        with (
            patch("app.ui.sm_levelup_moves_mod.build_party_patched_blob", return_value=b"PARCHEADO") as build,
            patch("app.ui.sm_levelup_moves_mod.write_blob"),
        ):
            RoleRunManager._sync_sm_levelup_moves_mod(fake, game)
            RoleRunManager._sync_sm_levelup_moves_mod(fake, game)
        self.assertEqual(build.call_count, 1)

    def test_un_cambio_de_rol_si_fuerza_recalcular(self) -> None:
        fake = self._fake()
        game = SimpleNamespace(party=[self._venusaur()])
        with (
            patch("app.ui.sm_levelup_moves_mod.build_party_patched_blob", return_value=b"PARCHEADO") as build,
            patch("app.ui.sm_levelup_moves_mod.write_blob"),
        ):
            RoleRunManager._sync_sm_levelup_moves_mod(fake, game)
            fake._effective_role = lambda pokemon: ("Asesino", "")
            RoleRunManager._sync_sm_levelup_moves_mod(fake, game)
        self.assertEqual(build.call_count, 2)

    def test_la_base_y_su_forma_alternativa_se_traducen_a_personal_id_distintos(self) -> None:
        """Venusaur (personal_id=3) y Mega Venusaur (personal_id=843) en el
        equipo a la vez: cada uno debe aparecer con SU PROPIO personal_id en
        el mapa que se le pasa a build_party_patched_blob, no fundidos en
        uno solo por compartir species_id."""
        fake = self._fake()
        game = SimpleNamespace(party=[
            self._venusaur(form=0, pid=1),
            self._venusaur(form=1, pid=2),
        ])
        with (
            patch("app.ui.sm_levelup_moves_mod.build_party_patched_blob", return_value=b"PARCHEADO") as build,
            patch("app.ui.sm_levelup_moves_mod.write_blob"),
        ):
            RoleRunManager._sync_sm_levelup_moves_mod(fake, game)
        roles_by_personal_id = build.call_args.args[1]
        self.assertEqual(
            roles_by_personal_id,
            {VENUSAUR_ID: "Mago", VENUSAUR_MEGA_PERSONAL_ID: "Mago"},
        )

    def test_una_forma_desconocida_cae_a_la_base_en_vez_de_ignorarse(self) -> None:
        fake = self._fake(personal_id_map={(VENUSAUR_ID, 0): VENUSAUR_ID})  # sin la forma 1
        game = SimpleNamespace(party=[self._venusaur(form=1)])  # forma desconocida
        with (
            patch("app.ui.sm_levelup_moves_mod.build_party_patched_blob", return_value=b"PARCHEADO") as build,
            patch("app.ui.sm_levelup_moves_mod.write_blob"),
        ):
            RoleRunManager._sync_sm_levelup_moves_mod(fake, game)
        self.assertEqual(build.call_args.args[1], {VENUSAUR_ID: "Mago"})

    def test_una_especie_totalmente_ausente_del_mapa_se_ignora_sin_romper_el_sondeo(self) -> None:
        fake = self._fake(personal_id_map={})  # ni siquiera la base
        game = SimpleNamespace(party=[self._venusaur(form=1)])
        with (
            patch("app.ui.sm_levelup_moves_mod.build_party_patched_blob", return_value=b"PARCHEADO") as build,
            patch("app.ui.sm_levelup_moves_mod.write_blob"),
        ):
            RoleRunManager._sync_sm_levelup_moves_mod(fake, game)
        self.assertEqual(build.call_args.args[1], {})

    def test_registrar_de_nuevo_el_mod_reinicia_la_cache_de_roles(self) -> None:
        """Un cambio de ROM/proceso invalida el parche calculado antes."""
        fake = self._fake()
        fake._sm_levelup_moves_last_roles_key = (frozenset({(3, "Mago")}), False)
        fake._sm_levelup_moves_last_written = b"ALGO-DE-UNA-SESION-ANTERIOR"

        with (
            patch(
                "app.ui.load_sm_levelup_moves_blob",
                return_value=(b"VANILLA-NUEVO", 42),
            ),
            patch("app.ui.sm_personal_id_map_for_rom", return_value={(VENUSAUR_ID, 0): VENUSAUR_ID}),
            patch("app.ui.sm_levelup_moves_mod.ensure_registered", return_value="kept"),
            patch("app.ui.sm_levelup_moves_mod.parse_levelup_garc", return_value={}),
        ):
            RoleRunManager._ensure_sm_levelup_moves_registered(fake, Path("rom.3ds"), Path("azahar"), None)
        self.assertIsNone(fake._sm_levelup_moves_last_roles_key)
        self.assertIsNone(fake._sm_levelup_moves_last_written)
        self.assertEqual(fake._sm_levelup_personal_id_map, {(VENUSAUR_ID, 0): VENUSAUR_ID})


class HistoryTests(unittest.TestCase):
    def _fake(self) -> SimpleNamespace:
        fake = SimpleNamespace(
            save_engine=SimpleNamespace(key="sm"),
            project=SimpleNamespace(oras_levelup_move_history={}),
            project_service=SimpleNamespace(save=lambda _project: None),
            engine=SimpleNamespace(
                pools={}, damage_classes={}, speed_status_moves=set(),
                self_healing_damage_moves=set(), allowed_move_ids=None,
            ),
            _sm_levelup_moves_vanilla_entries={
                VENUSAUR_MEGA_PERSONAL_ID: ((999, 16, 0),),
            },
            _sm_levelup_personal_id_map={(VENUSAUR_ID, 1): VENUSAUR_MEGA_PERSONAL_ID},
            _sm_levelup_history_last_levels={},
            _effective_role=lambda pokemon: ("Mago", ""),
            _registrar_intento_vivo=lambda *a, **k: None,
        )
        fake._sm_levelup_usable_move_ids = RoleRunManager._sm_levelup_usable_move_ids.__get__(fake)
        fake._sm_levelup_personal_id_for = RoleRunManager._sm_levelup_personal_id_for.__get__(fake)
        fake._append_sm_levelup_history_entries = (
            RoleRunManager._append_sm_levelup_history_entries.__get__(fake)
        )
        fake._purge_sm_levelup_history_above_level = (
            RoleRunManager._purge_sm_levelup_history_above_level.__get__(fake)
        )
        fake._record_sm_levelup_move_history = (
            RoleRunManager._record_sm_levelup_move_history.__get__(fake)
        )
        return fake

    def test_se_registra_en_el_instante_del_cruce_usando_el_personal_id_de_la_forma(self) -> None:
        fake = self._fake()
        pokemon = SimpleNamespace(
            species_id=VENUSAUR_ID, form=1, level=10, pid=1, tid=2, sid=3,
            nickname="Mega", species="Venusaur",
        )
        game = SimpleNamespace(party=[pokemon])
        fake._sm_levelup_history_last_levels["1:2:3"] = 10
        pokemon.level = 20  # cruza el nivel 16, exclusivo de la forma 1
        fake._record_sm_levelup_move_history(game)

        historial = fake.project.oras_levelup_move_history["1:2:3"]
        self.assertEqual(len(historial), 1)
        self.assertEqual(historial[0]["level"], 16)
        self.assertFalse(historial[0]["pre_capture"])


if __name__ == "__main__":
    unittest.main()
