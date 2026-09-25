from __future__ import annotations

import unittest

from app.azahar_rpc import AzaharProcess
from app.realtime.xy_adapter import XYRealTimeAdapter
from app.save_engine_client import SaveGameData
from app.xy_live import XYLiveSnapshot, ORASBattleProbe


class _FakeBridgeInfo:
    key = "azahar"
    display_name = "Azahar"
    transport = "RPC UDP"


class _FakeBridge:
    info = _FakeBridgeInfo()


class _FakeReader:
    def __init__(self, probe: ORASBattleProbe) -> None:
        self._probe = probe
        self._process = AzaharProcess(77, 0x000400000011C500, "kujira-1")

    def read_monitor(self, current, memory_blocks=()):
        return XYLiveSnapshot(game=current, process=self._process, attempts=1, memory_blocks=())

    def read_battle_probe(self, current):
        return self._probe


class _FakeWriter:
    last_badge_source = "prueba"

    def read_badges(self, save_path):
        return None


class XYAdapterBattleStateTests(unittest.TestCase):
    def test_opponent_identity_survives_the_battle_state_conversion(self) -> None:
        # Regresión del mismo tipo que ya mordió a ORAS (ver
        # `tests/test_oras_adapter_battle_state.py`): `_convert` reconstruye un
        # `BattleState` a mano a partir del `ORASBattleProbe` que devuelve
        # `xy_live.read_battle_probe`. Si `opponent_identity` no se copia aquí
        # explícitamente, `ui.py` nunca la ve -y la regla de "combate de seis"
        # (vía X/Y, que sí necesita esta identidad) no se dispara nunca-.
        current = SaveGameData("X", "SAV6X", 6, "Diego", [], {})
        probe = ORASBattleProbe(state="trainer", opponent_identity=(412, 0x08206770))
        adapter = XYRealTimeAdapter(_FakeReader(probe), _FakeWriter(), bridge=_FakeBridge())

        snapshot = adapter.capture_monitor(current, save_path=None)

        self.assertEqual(snapshot.battle.state, "trainer")
        self.assertEqual(snapshot.battle.opponent_identity, (412, 0x08206770))

    def test_no_battle_never_carries_an_opponent_identity(self) -> None:
        current = SaveGameData("X", "SAV6X", 6, "Diego", [], {})
        probe = ORASBattleProbe(state="none", opponent_identity=None)
        adapter = XYRealTimeAdapter(_FakeReader(probe), _FakeWriter(), bridge=_FakeBridge())

        snapshot = adapter.capture_monitor(current, save_path=None)

        self.assertEqual(snapshot.battle.state, "none")
        self.assertIsNone(snapshot.battle.opponent_identity)


if __name__ == "__main__":
    unittest.main()
