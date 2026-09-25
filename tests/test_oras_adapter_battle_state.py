from __future__ import annotations

import unittest

from app.oras_live import AzaharProcess, ORASBattleProbe, ORASLiveSnapshot
from app.realtime.oras_adapter import ORASRealTimeAdapter
from app.save_engine_client import SaveGameData


class _FakeReader:
    def __init__(self, probe: ORASBattleProbe) -> None:
        self._probe = probe
        self._process = AzaharProcess(77, 0x000400000011C500, "sango-2")

    def read_monitor(self, current, memory_blocks=()):
        return ORASLiveSnapshot(game=current, process=self._process, attempts=1, memory_blocks=())

    def read_battle_probe(self, current):
        return self._probe


class _FakeWriter:
    last_badge_source = "prueba"

    def read_badges(self, save_path):
        return None


class ORASAdapterBattleStateTests(unittest.TestCase):
    def test_opponent_team_size_survives_the_battle_state_conversion(self) -> None:
        # Regresión: `_capture_optional_lanes` reconstruye un `BattleState`
        # nuevo a mano a partir del `ORASBattleProbe` de `oras_live`. Si algún
        # campo nuevo del probe no se copia aquí explícitamente, se pierde en
        # silencio -exactamente lo que le pasó a este mismo campo la primera
        # vez (entonces `opponent_identity`): la regla de "combate de seis"
        # nunca veía datos reales porque `ui.py` solo recibe el `BattleState`
        # genérico, nunca el `ORASBattleProbe` original-.
        current = SaveGameData("AS", "SAV6AO", 6, "Diego", [], {})
        probe = ORASBattleProbe(state="trainer", opponent_team_size=6)
        adapter = ORASRealTimeAdapter(_FakeReader(probe), _FakeWriter(), bridge=object())

        snapshot = adapter.capture_monitor(current, save_path=None)

        self.assertEqual(snapshot.battle.state, "trainer")
        self.assertEqual(snapshot.battle.opponent_team_size, 6)

    def test_wild_battle_never_carries_an_opponent_team_size(self) -> None:
        current = SaveGameData("AS", "SAV6AO", 6, "Diego", [], {})
        probe = ORASBattleProbe(state="wild", opponent_team_size=None)
        adapter = ORASRealTimeAdapter(_FakeReader(probe), _FakeWriter(), bridge=object())

        snapshot = adapter.capture_monitor(current, save_path=None)

        self.assertEqual(snapshot.battle.state, "wild")
        self.assertIsNone(snapshot.battle.opponent_team_size)


if __name__ == "__main__":
    unittest.main()
