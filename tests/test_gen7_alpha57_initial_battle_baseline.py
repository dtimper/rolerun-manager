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
    def __init__(self, *, usum: bool, state: str, health=None, validated=True):
        self.client_factory = lambda: None
        self.usum = usum
        self.probe = (
            USUMBattleProbe(state=state, health_game=health, validated=validated)
            if usum else
            SMBattleProbe(state=state, health_game=health, validated=validated)
        )

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
