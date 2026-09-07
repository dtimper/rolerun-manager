"""SM/USUM: precargar Personal también para un cambio de rol puro.

2026-09-04: el usuario abrió RoleRun y le salió un mensaje rojo de error
que desapareció al pulsar REINTENTAR. El log en vivo mostró la causa real:
``"La ROM efectiva no aportó Personal para especie #166, forma 0; no se
escribió ningún byte."`` — un ``PendingRoleChange`` (sin ningún traslado
Equipo↔PC) se auto-aplicó antes de que ``self._sm_rom_tm_profile`` se
hubiera precargado nunca esta sesión, porque
``_save_oras_live_changes`` (``app/ui.py``) solo precargaba Personal para
SM/USUM cuando había ``sm_team_transfers`` -operaciones Equipo↔PC-, nunca
para un cambio de rol puro, aunque éste TAMBIÉN recalcula EV/stats
(``PendingRoleChange.new_evs``) y por tanto también necesita Personal. El
reintento del usuario funcionaba porque, para entonces, algún otro camino
ya había poblado la caché.
"""

from __future__ import annotations

import inspect
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import customtkinter  # noqa: F401
except ModuleNotFoundError:                                  # pragma: no cover
    customtkinter = types.ModuleType("customtkinter")
    customtkinter.CTk = object
    sys.modules["customtkinter"] = customtkinter

import unittest

from app.ui import RoleRunManager


class Gen7PersonalPreloadTests(unittest.TestCase):
    def test_un_cambio_de_rol_puro_con_new_evs_tambien_precarga_personal(self) -> None:
        fuente = inspect.getsource(RoleRunManager._save_oras_live_changes)
        assert "gen7_needs_personal = sm_team_transfers or any(" in fuente
        assert "isinstance(change, PendingRoleChange) and change.new_evs is not None" in fuente
        # Y sigue usándose exactamente donde antes solo miraba sm_team_transfers.
        assert "if gen7_needs_personal and self._active_azahar_realtime_key() in GEN7_REALTIME_GAME_KEYS:" in fuente


if __name__ == "__main__":
    unittest.main()
