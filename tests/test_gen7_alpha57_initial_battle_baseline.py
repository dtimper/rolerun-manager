from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.azahar_rpc import AzaharProcess
from app.realtime.sm_adapter import SMRealTimeAdapter
from app.realtime.usum_adapter import USUMRealTimeAdapter
from app.save_engine_client import SaveGameData, SavePokemon
from app.sm_live import SMBattleProbe
from app.usum_live import USUMBattleProbe


def mon(hp: int = 20) -> SavePokemon:
    return SavePokemon(
        slot=1, species_id=25, species="Pikachu", nickname="Pikachu", level=5,
        held_item="Ninguno", ability="Static", moves=["Placaje", "—", "—", "—"],
        move_ids=[33, 0, 0, 0], is_egg=False, markings=[False] * 6,
        role="Líbero", role_symbol="●", pid=1234, tid=1, sid=2,
        current_hp=hp, max_hp=20,
    )


def game(name: str, hp: int = 20) -> SaveGameData:
    return SaveGameData(
        game=name, save_type="live", generation=7, trainer="Tester",
        party=[mon(hp)], raw={"liveSync": True},
    )


class Reader:
    def __init__(
        self, *, usum: bool, state: str, health=None, validated=True,
        opponent_team_size: int | None = None,
    ):
        self.client_factory = lambda: None
        self.usum = usum
        self.probe = (
            USUMBattleProbe(state=state, health_game=health, validated=validated)
            if usum else
            SMBattleProbe(state=state, health_game=health, validated=validated)
        )
        self._opponent_team_size = opponent_team_size

    def read(self, current, memory_blocks=()):
        title = 0x00040000001B5000 if self.usum else 0x0004000000164800
        base = 0x33F7FA44 if self.usum else 0x34195E10
        return SimpleNamespace(
            game=current,
            process=AzaharProcess(9, title, "niji_loc"),
            attempts=1,
            party_base=base,
            memory_blocks=(),
            runtime_party_region=b"",
        )

    def read_battle_probe(self, current):
        return self.probe

    def read_battle_opponent_team_size(self):
        return self._opponent_team_size


def test_alpha57_usum_full_sync_knows_it_started_outside_battle() -> None:
    source = game("Pokémon UltraSol")
    adapter = USUMRealTimeAdapter(Reader(usum=True, state="none"))
    snap = adapter.capture_full(source, save_path=Path("main"))
    assert snap.battle.state == "none"
    assert snap.battle.health_game is None
    assert snap.diagnostic("battle") is not None


def test_alpha57_sm_full_sync_knows_it_started_outside_battle() -> None:
    source = game("Pokémon Sol")
    adapter = SMRealTimeAdapter(Reader(usum=False, state="none"))
    snap = adapter.capture_full(source, save_path=Path("main"))
    assert snap.battle.state == "none"
    assert snap.battle.health_game is None
    assert snap.diagnostic("battle") is not None


def test_alpha57_full_sync_inside_battle_carries_safe_health_baseline() -> None:
    source = game("Pokémon UltraSol", hp=20)
    battle_health = game("Pokémon UltraSol", hp=0)
    adapter = USUMRealTimeAdapter(
        Reader(usum=True, state="battle", health=battle_health, validated=True),
    )
    snap = adapter.capture_full(source, save_path=Path("main"))
    assert snap.battle.state == "battle"
    assert snap.battle.health_game is battle_health
    # La UI usará este payload como baseline, no como transición retrospectiva.
    assert snap.battle.health_game.party[0].current_hp == 0


def test_opponent_team_size_survives_the_battle_state_conversion() -> None:
    # Regresión del mismo tipo que ya mordió a ORAS y X/Y (ver
    # `tests/test_oras_adapter_battle_state.py`, `tests/test_xy_adapter_battle_state.py`):
    # `_convert` reconstruye un `BattleState` a mano. Regla de "combate de
    # seis" (dictada 09-09-2026, ver memoria `six-mon-battle-auto-reward`):
    # USUM lee el roster completo del rival de una vez, igual que ORAS -no
    # persigue sustituciones-, así que basta con que el campo sobreviva la
    # conversión.
    source = game("Pokémon UltraSol", hp=20)
    adapter = USUMRealTimeAdapter(
        Reader(usum=True, state="battle", validated=True, opponent_team_size=6),
    )
    snap = adapter.capture_full(source, save_path=Path("main"))
    assert snap.battle.opponent_team_size == 6


def test_opponent_team_size_is_none_outside_battle() -> None:
    source = game("Pokémon UltraSol", hp=20)
    adapter = USUMRealTimeAdapter(
        Reader(usum=True, state="none", opponent_team_size=None),
    )
    snap = adapter.capture_full(source, save_path=Path("main"))
    assert snap.battle.opponent_team_size is None


def test_sm_opponent_team_size_survives_the_battle_state_conversion() -> None:
    # Mismas direcciones que USUM, confirmadas en vivo el 14-09-2026 contra
    # un combate real de Sol/Luna. Ver memoria `six-mon-battle-auto-reward`.
    source = game("Pokémon Sol", hp=20)
    adapter = SMRealTimeAdapter(
        Reader(usum=False, state="battle", validated=True, opponent_team_size=6),
    )
    snap = adapter.capture_full(source, save_path=Path("main"))
    assert snap.battle.opponent_team_size == 6


def test_sm_opponent_team_size_is_none_outside_battle() -> None:
    source = game("Pokémon Sol", hp=20)
    adapter = SMRealTimeAdapter(
        Reader(usum=False, state="none", opponent_team_size=None),
    )
    snap = adapter.capture_full(source, save_path=Path("main"))
    assert snap.battle.opponent_team_size is None
