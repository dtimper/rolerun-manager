"""Un cambio de rol tiene que llegar al instante a la tabla de aprendizajes de ORAS.

Bug real reportado por el usuario el 2026-09-03: al cambiar el rol de dos
Pokémon desde la barra flotante y darles Caramelo Raro enseguida, seguían
aprendiendo el movimiento del rol ANTERIOR. La sincronización pasiva
(``_finish_oras_live_reconciliation``) tarda hasta ~950ms en volver a
sondear; con el juego acelerado (varios cientos por ciento de velocidad,
confirmado en la misma sesión) ese margen le sobraba de tiempo al juego para
procesar la subida de nivel antes de que RoleRun reaccionara. La solución no
fue de caché: fue disparar la sincronización en el mismo instante en que se
aplica el cambio de rol, en los tres sitios donde eso ocurre.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui import RoleRunManager  # noqa: E402


def test_el_intercambio_de_roles_dispara_la_sincronizacion_al_instante() -> None:
    fuente = inspect.getsource(RoleRunManager._move_pokemon_to_role_by_drag)
    assert "self._sync_oras_levelup_moves_mod(self.current_game)" in fuente


def test_traer_un_pokemon_del_pc_a_un_rol_ocupado_tambien_sincroniza() -> None:
    fuente = inspect.getsource(RoleRunManager._open_team_to_pc_swap_picker)
    assert "self._sync_oras_levelup_moves_mod(self.current_game)" in fuente


def test_el_selector_del_pc_tambien_sincroniza_al_asignar_rol() -> None:
    fuente = inspect.getsource(RoleRunManager.open_pc_selector)
    assert "self._sync_oras_levelup_moves_mod(self.current_game)" in fuente
