"""``_projected_party`` proyecta stats al instante en un cambio de rol.

2026-09-04: el usuario grabó un vídeo mostrando que, tras arrastrar un
Pokémon a otra casilla de rol, el ROL/icono cambia al instante -ya estaba
horneado antes de este cambio- pero las STATS numéricas se quedan con los
valores viejos ~2s más, hasta que la escritura en vivo confirma. La fórmula
de proyección en sí (``project_stats``/``project_current_hp``) ya tiene sus
propias pruebas en ``test_pokemon_stats_projection.py``; estas cubren que
``_projected_party`` la enchufa en el sitio correcto: un simple cambio de
rol entre miembros activos (sin ningún movimiento Equipo↔PC, el caso del
vídeo) NO pasa por la rama de ``team_changes`` y aun así debe proyectar.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import customtkinter  # noqa: F401
except ModuleNotFoundError:                                  # pragma: no cover
    customtkinter = types.ModuleType("customtkinter")
    customtkinter.CTk = object
    sys.modules["customtkinter"] = customtkinter

import unittest

from app.models import PendingRoleChange
from app.save_engine_client import SaveGameData, SavePokemon
from app.ui import RoleRunManager

YUNGOOS_BASE = {"hp": 48, "attack": 70, "defense": 30, "sp_attack": 30, "sp_defense": 30, "speed": 45}
YUNGOOS_IVS = {"hp": 30, "attack": 30, "defense": 15, "sp_attack": 19, "sp_defense": 24, "speed": 11}
TANQUE_EVS = (252, 0, 252, 0, 0, 0)  # orden STAT_KEYS: hp, attack, defense, sp_attack, sp_defense, speed


def _yungoos(**overrides) -> SavePokemon:
    base = dict(
        slot=1, species_id=161, species="Yungoos", nickname="", level=40,
        held_item="", ability="Vigilante", moves=[], move_ids=[],
        is_egg=False, markings=[False] * 6, role="SIN ROL", role_symbol="",
        pid=1, tid=2, sid=3, form=0,
        current_hp=100, max_hp=100,
        nature_id=24, stat_nature_id=24, nature="Rara", stat_nature="Rara",
        stats={"hp": 100, "attack": 73, "defense": 35, "sp_attack": 61, "sp_defense": 38, "speed": 70},
        base_stats=dict(YUNGOOS_BASE), ivs=dict(YUNGOOS_IVS), evs={},
    )
    base.update(overrides)
    return SavePokemon(**base)


def _manager(party: list[SavePokemon], pending_changes: list) -> SimpleNamespace:
    game = SaveGameData(
        game="sm", save_type="live", generation=7, trainer="",
        party=party, raw={},
    )
    manager = SimpleNamespace(
        current_game=game,
        project=SimpleNamespace(pending_faints=[]),
        run=SimpleNamespace(pending_changes=pending_changes),
    )
    manager._pokemon_identity = lambda p: f"{p.species_id}:{p.pid}:{p.tid}:{p.sid}"
    manager._pending_role_change_for = RoleRunManager._pending_role_change_for.__get__(manager)
    manager._projected_party = RoleRunManager._projected_party.__get__(manager)
    return manager


class ProjectedPartyStatsPreviewTests(unittest.TestCase):
    def test_un_cambio_de_rol_sin_movimientos_de_pc_proyecta_las_stats_al_instante(self) -> None:
        """El caso exacto del vídeo: drag entre dos miembros activos."""
        yungoos = _yungoos()
        manager = _manager(
            [yungoos],
            [PendingRoleChange(
                pokemon_slot=1, pokemon="Yungoos", species="Yungoos",
                old_role="SIN ROL", new_role="Tanque",
                pokemon_identity="161:1:2:3",
                old_evs=(0, 0, 0, 0, 0, 0), new_evs=TANQUE_EVS,
            )],
        )

        projected = manager._projected_party()

        self.assertEqual(len(projected), 1)
        self.assertEqual(
            projected[0].stats,
            {"hp": 125, "attack": 73, "defense": 60, "sp_attack": 36, "sp_defense": 38, "speed": 45},
        )
        self.assertEqual(
            projected[0].evs,
            {"hp": 252, "attack": 0, "defense": 252, "sp_attack": 0, "sp_defense": 0, "speed": 0},
        )

    def test_el_ps_actual_conserva_el_dano_ya_sufrido(self) -> None:
        yungoos = _yungoos(current_hp=60, max_hp=100)  # 40 de daño sufrido
        manager = _manager(
            [yungoos],
            [PendingRoleChange(
                pokemon_slot=1, pokemon="Yungoos", species="Yungoos",
                old_role="SIN ROL", new_role="Tanque",
                pokemon_identity="161:1:2:3", new_evs=TANQUE_EVS,
            )],
        )

        projected = manager._projected_party()

        self.assertEqual(projected[0].max_hp, 125)
        self.assertEqual(projected[0].current_hp, 85)  # 125 - 40, no rellena de más

    def test_sin_cambio_de_rol_pendiente_no_toca_nada(self) -> None:
        yungoos = _yungoos()
        original_stats = dict(yungoos.stats)
        manager = _manager([yungoos], [])

        projected = manager._projected_party()

        self.assertEqual(projected[0].stats, original_stats)

    def test_un_cambio_de_rol_sin_new_evs_no_toca_las_stats(self) -> None:
        """Juegos fuera de ROLE_EV_WRITER_GAME_KEYS: new_evs siempre None."""
        yungoos = _yungoos()
        original_stats = dict(yungoos.stats)
        manager = _manager(
            [yungoos],
            [PendingRoleChange(
                pokemon_slot=1, pokemon="Yungoos", species="Yungoos",
                old_role="SIN ROL", new_role="Tanque",
                pokemon_identity="161:1:2:3", new_evs=None,
            )],
        )

        projected = manager._projected_party()

        self.assertEqual(projected[0].stats, original_stats)

    def test_sin_base_stats_publicados_no_rompe_ni_toca_nada(self) -> None:
        """Un backend que todavía no demuestra IV/base_stats: se abstiene."""
        yungoos = _yungoos(base_stats={}, ivs={})
        original_stats = dict(yungoos.stats)
        manager = _manager(
            [yungoos],
            [PendingRoleChange(
                pokemon_slot=1, pokemon="Yungoos", species="Yungoos",
                old_role="SIN ROL", new_role="Tanque",
                pokemon_identity="161:1:2:3", new_evs=TANQUE_EVS,
            )],
        )

        projected = manager._projected_party()

        self.assertEqual(projected[0].stats, original_stats)

    def test_no_afecta_al_original_solo_a_la_copia_proyectada(self) -> None:
        """``current_game.party`` -la fuente de verdad del juego- no se toca."""
        yungoos = _yungoos()
        original_stats = dict(yungoos.stats)
        manager = _manager(
            [yungoos],
            [PendingRoleChange(
                pokemon_slot=1, pokemon="Yungoos", species="Yungoos",
                old_role="SIN ROL", new_role="Tanque",
                pokemon_identity="161:1:2:3", new_evs=TANQUE_EVS,
            )],
        )

        manager._projected_party()

        self.assertEqual(manager.current_game.party[0].stats, original_stats)


if __name__ == "__main__":
    unittest.main()
