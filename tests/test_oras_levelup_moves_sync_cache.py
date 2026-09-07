"""El sondeo en vivo de ORAS no debe recalcular el mod de aprendizajes en balde.

Pedido por el usuario el 2026-09-03 ("el programa me está dando un
rendimiento pobre"): ``_sync_oras_levelup_moves_mod`` se llama en cada
sondeo en vivo, hasta cada 250ms mientras la partida está abierta. Antes de
este arreglo, cada llamada reconstruía el blob de aprendizajes entero
—copiar el vainilla y evaluar cada entrada de nivel de cada especie en
juego— aunque el mapa especie→rol fuera idéntico al del sondeo anterior, que
es el caso normal: los roles solo cambian cuando el usuario los cambia.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.ui import RoleRunManager


class SyncCacheTests(unittest.TestCase):
    def _fake(self) -> SimpleNamespace:
        fake = SimpleNamespace(
            save_engine=SimpleNamespace(key="oras"),
            project=SimpleNamespace(oras_levelup_move_history={}),
            project_service=SimpleNamespace(save=lambda _project: None),
            engine=SimpleNamespace(
                pools={}, damage_classes={}, speed_status_moves=set(),
                self_healing_damage_moves=set(), allowed_move_ids=None,
            ),
            _oras_levelup_moves_vanilla=b"VANILLA",
            _oras_levelup_moves_title_id=1,
            _oras_levelup_moves_azahar_root=SimpleNamespace(),
            _oras_levelup_moves_vanilla_entries={},
            _oras_levelup_moves_last_written=None,
            _oras_levelup_moves_last_roles_key=None,
            _oras_levelup_history_last_levels={},
            _effective_role=lambda pokemon: ("Mago", ""),
            _registrar_intento_vivo=lambda *a, **k: None,
        )
        fake._oras_levelup_usable_move_ids = RoleRunManager._oras_levelup_usable_move_ids.__get__(fake)
        fake._append_oras_levelup_history_entries = (
            RoleRunManager._append_oras_levelup_history_entries.__get__(fake)
        )
        fake._purge_oras_levelup_history_above_level = (
            RoleRunManager._purge_oras_levelup_history_above_level.__get__(fake)
        )
        fake._record_oras_levelup_move_history = (
            RoleRunManager._record_oras_levelup_move_history.__get__(fake)
        )
        return fake

    def _houndoom(self, level: int = 10) -> SimpleNamespace:
        return SimpleNamespace(
            species_id=229, level=level, pid=1, tid=2, sid=3,
            nickname="", species="Houndoom",
        )

    def test_dos_sondeos_seguidos_con_los_mismos_roles_no_recalculan_el_parche(self) -> None:
        fake = self._fake()
        game = SimpleNamespace(party=[self._houndoom()])
        with (
            patch("app.ui.oras_levelup_moves_mod.build_party_patched_blob", return_value=b"PARCHEADO") as build,
            patch("app.ui.oras_levelup_moves_mod.write_blob"),
        ):
            RoleRunManager._sync_oras_levelup_moves_mod(fake, game)
            RoleRunManager._sync_oras_levelup_moves_mod(fake, game)
        self.assertEqual(build.call_count, 1)

    def test_un_cambio_de_rol_si_fuerza_recalcular(self) -> None:
        fake = self._fake()
        game = SimpleNamespace(party=[self._houndoom()])
        with (
            patch("app.ui.oras_levelup_moves_mod.build_party_patched_blob", return_value=b"PARCHEADO") as build,
            patch("app.ui.oras_levelup_moves_mod.write_blob"),
        ):
            RoleRunManager._sync_oras_levelup_moves_mod(fake, game)
            fake._effective_role = lambda pokemon: ("Asesino", "")
            RoleRunManager._sync_oras_levelup_moves_mod(fake, game)
        self.assertEqual(build.call_count, 2)

    def test_registrar_de_nuevo_el_mod_reinicia_la_cache_de_roles(self) -> None:
        """Un cambio de ROM/proceso invalida el parche calculado antes."""
        fake = self._fake()
        fake._oras_levelup_moves_last_roles_key = (frozenset({(229, "Mago")}), False)
        fake._oras_levelup_moves_last_written = b"ALGO-DE-UNA-SESION-ANTERIOR"
        from pathlib import Path

        with (
            patch(
                "app.ui.load_oras_levelup_moves_blob",
                return_value=(b"VANILLA-NUEVO", 42),
            ),
            patch("app.ui.oras_levelup_moves_mod.ensure_registered", return_value="kept"),
            patch("app.ui.oras_levelup_moves_mod.parse_levelup_garc", return_value={}),
        ):
            RoleRunManager._ensure_oras_levelup_moves_registered(fake, Path("rom.3ds"), Path("azahar"), None)
        self.assertIsNone(fake._oras_levelup_moves_last_roles_key)
        self.assertIsNone(fake._oras_levelup_moves_last_written)


if __name__ == "__main__":
    unittest.main()
