"""HeartGold: mochila/dinero sí, fijar-roles/curar/PC no, mientras la

escritura de equipo siga apagada.

Encontrado el 06-09-2026 investigando cómo desbloquear solo mochila/dinero
para probar los aprendizajes por rol: `_oras_live_unsupported_changes` y
`_request_oras_live_auto_apply` trataban a "hgss" igual que a "b2w2"/"bw" en
cuanto entraba en `MELONDS_REALTIME_GAME_KEYS` -necesario para poder LEER en
vivo-, dejando pasar sin ninguna comprobación cambios de rol, curación y PC,
pese a que `MELONDS_GEN4_ESCRIBE = False` por el historial real de cuatro
«Huevo malo». No era una decisión: era un agujero real.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.models import PendingInventoryChange, PendingPartyHeal, PendingRoleChange, PendingTeamChange
from app.ui import MELONDS_GEN4_ESCRIBE, RoleRunManager


def _manager(changes):
    return SimpleNamespace(
        _active_azahar_realtime_key=lambda: "hgss",
        _oras_live_auto_apply_available=lambda: True,
        run=SimpleNamespace(pending_changes=list(changes)),
        _oras_live_auto_apply_ids=set(),
        _schedule_oras_live_auto_apply=lambda: None,
    )


class MientrasLaEscrituraSigaApagadaTests(unittest.TestCase):
    def setUp(self) -> None:
        if MELONDS_GEN4_ESCRIBE:
            self.skipTest("MELONDS_GEN4_ESCRIBE ya está en True; estas pruebas ya no aplican.")

    def test_la_mochila_no_aparece_como_no_soportada(self) -> None:
        cambio = PendingInventoryChange(item_key="rare-candy", item_name="Caramelo Raro", quantity=999)
        manager = _manager([cambio])
        self.assertEqual(RoleRunManager._oras_live_unsupported_changes(manager, [cambio]), [])

    def test_la_mochila_si_entra_en_la_cola_de_escritura_automatica(self) -> None:
        cambio = PendingInventoryChange(item_key="rare-candy", item_name="Caramelo Raro", quantity=999)
        manager = _manager([cambio])
        RoleRunManager._request_oras_live_auto_apply(manager, [cambio])
        self.assertEqual(manager._oras_live_auto_apply_ids, {id(cambio)})

    def test_fijar_rol_aparece_como_no_soportado(self) -> None:
        cambio = PendingRoleChange(
            pokemon_slot=0, pokemon="Totodile", species="Totodile",
            old_role="SIN ROL", new_role="Mago", pokemon_identity="1:2:3",
        )
        manager = _manager([cambio])
        self.assertNotEqual(RoleRunManager._oras_live_unsupported_changes(manager, [cambio]), [])

    def test_fijar_rol_no_entra_en_la_cola_de_escritura_automatica(self) -> None:
        cambio = PendingRoleChange(
            pokemon_slot=0, pokemon="Totodile", species="Totodile",
            old_role="SIN ROL", new_role="Mago", pokemon_identity="1:2:3",
        )
        manager = _manager([cambio])
        RoleRunManager._request_oras_live_auto_apply(manager, [cambio])
        self.assertEqual(manager._oras_live_auto_apply_ids, set())

    def test_curar_aparece_como_no_soportado(self) -> None:
        cambio = PendingPartyHeal(
            pokemon_slot=0, pokemon="Totodile", species="Totodile", pokemon_identity="1:2:3",
        )
        manager = _manager([cambio])
        self.assertNotEqual(RoleRunManager._oras_live_unsupported_changes(manager, [cambio]), [])

    def test_mover_en_el_pc_aparece_como_no_soportado(self) -> None:
        cambio = PendingTeamChange(
            operation="swap-box-slots", party_slot=0,
            box=1, box_slot=1, destination_box=1, destination_box_slot=2,
            incoming_identity="1:2:3", outgoing_identity="4:5:6",
        )
        manager = _manager([cambio])
        self.assertNotEqual(RoleRunManager._oras_live_unsupported_changes(manager, [cambio]), [])

    def test_una_mezcla_solo_deja_pasar_la_mochila(self) -> None:
        inventario = PendingInventoryChange(item_key="rare-candy", item_name="Caramelo Raro", quantity=999)
        rol = PendingRoleChange(
            pokemon_slot=0, pokemon="Totodile", species="Totodile",
            old_role="SIN ROL", new_role="Mago", pokemon_identity="1:2:3",
        )
        manager = _manager([inventario, rol])
        RoleRunManager._request_oras_live_auto_apply(manager, [inventario, rol])
        self.assertEqual(manager._oras_live_auto_apply_ids, {id(inventario)})


if __name__ == "__main__":
    unittest.main()
