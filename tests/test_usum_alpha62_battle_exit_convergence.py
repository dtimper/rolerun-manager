from __future__ import annotations

import json
import struct
from pathlib import Path
from unittest.mock import patch

from app.azahar_rpc import AzaharProcess
from app.save_engine_client import SaveGameData, SavePokemon
from app.usum_live import (
    USUM_BATTLE_ACTUAL_FROM_MAX,
    USUM_BATTLE_DISPLAY_FROM_MAX,
    USUM_BATTLE_IDLE_NO_FAINT_TIMEOUT_SECONDS,
    USUM_BATTLE_PHASE_ACTIVE_VALUE,
    USUM_BATTLE_PHASE_ADDRESS,
    USUM_BATTLE_PHASE_IDLE_VALUE,
    USUM_BATTLE_PLAYER_MAX_HP_BASE,
    USUM_BATTLE_PLAYER_STRIDE,
    USUM_BATTLE_STATE_ACTIVE_VALUE,
    USUM_BATTLE_STATE_ADDRESS,
    USUM_BATTLE_STATE_IDLE_VALUE,
    USUMLiveReader,
)
from app.usum_rom_service import USUM_ULTRA_SUN_TITLE_ID


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
PARTY_MAXES = (18, 19, 149, 20, 101, 17)


def _lane(values: tuple[int, ...]) -> bytes:
    raw = bytearray(((len(values) - 1) * USUM_BATTLE_PLAYER_STRIDE) + 2)
    for index, value in enumerate(values):
        struct.pack_into("<H", raw, index * USUM_BATTLE_PLAYER_STRIDE, int(value))
    return bytes(raw)


def _game(hp: tuple[int, ...]) -> SaveGameData:
    species = (379, 133, 115, 137, 763, 455)
    names = ("Registeel", "Eevee", "Kangaskhan", "Porygon", "Tsareena", "Carnivine")
    return SaveGameData(
        game="Pokémon UltraSol",
        save_type="SAV7USUM + Azahar RPC (USUM en vivo)",
        generation=7,
        trainer="Tester",
        party=[
            SavePokemon(
                slot=index + 1,
                species_id=species[index],
                species=names[index],
                nickname=names[index],
                level=30,
                held_item="Ninguno",
                ability="",
                moves=["Placaje", "—", "—", "—"],
                move_ids=[33, 0, 0, 0],
                is_egg=False,
                markings=[False] * 6,
                role="SIN ROL",
                role_symbol="",
                pid=0xA0000000 + index,
                tid=835,
                sid=6011,
                current_hp=int(hp[index]),
                max_hp=int(PARTY_MAXES[index]),
            )
            for index in range(6)
        ],
        raw={"liveSync": True},
    )


class _BattleRPC:
    def __init__(self) -> None:
        self.process = AzaharProcess(11, USUM_ULTRA_SUN_TITLE_ID, "momiji")
        self.state = USUM_BATTLE_STATE_ACTIVE_VALUE
        self.phase = USUM_BATTLE_PHASE_ACTIVE_VALUE
        self.max_hp = PARTY_MAXES
        self.displayed = PARTY_MAXES
        self.actual = PARTY_MAXES

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def process_list(self):
        return [self.process]

    def set_process(self, process_id: int):
        assert int(process_id) == self.process.process_id

    def read_memory(self, address: int, size: int) -> bytes:
        address = int(address)
        if address == USUM_BATTLE_STATE_ADDRESS:
            return struct.pack("<I", int(self.state))
        if address == USUM_BATTLE_PHASE_ADDRESS:
            return struct.pack("<I", int(self.phase))
        if address == USUM_BATTLE_PLAYER_MAX_HP_BASE:
            return _lane(tuple(self.max_hp))[: int(size)]
        if address == USUM_BATTLE_PLAYER_MAX_HP_BASE + USUM_BATTLE_DISPLAY_FROM_MAX:
            return _lane(tuple(self.displayed))[: int(size)]
        if address == USUM_BATTLE_PLAYER_MAX_HP_BASE + USUM_BATTLE_ACTUAL_FROM_MAX:
            return _lane(tuple(self.actual))[: int(size)]
        return b"\0" * int(size)


def _reader(rpc: _BattleRPC) -> USUMLiveReader:
    return USUMLiveReader(
        DATA_DIR / "move_catalog.json",
        client_factory=lambda: rpc,
        stable_delay=0,
        snapshot_attempts=1,
    )


def test_alpha62_idle_pair_ends_only_after_observed_ko_converges_to_party(
    isolated_role_run_log_dir: Path,
) -> None:
    """Reproduce la primera divergencia física de alpha.61.

    El mismo par 0x00040005/6 aparece durante la sustitución forzada y ya en
    overworld. Lo que cambia es que PartyData solo converge a los dos HP=0 al
    finalizar realmente el combate.
    """
    rpc = _BattleRPC()
    reader = _reader(rpc)
    full_party = _game(PARTY_MAXES)

    baseline = reader.read_battle_probe(full_party)
    assert baseline is not None and baseline.state == "battle"

    rpc.displayed = (18, 0, 149, 0, 101, 17)
    rpc.actual = rpc.displayed
    fainted = reader.read_battle_probe(full_party)
    assert fainted is not None and fainted.state == "battle"

    rpc.state = USUM_BATTLE_STATE_IDLE_VALUE
    rpc.phase = USUM_BATTLE_PHASE_IDLE_VALUE

    forced_replacement = reader.read_battle_probe(full_party)
    assert forced_replacement is not None and forced_replacement.state == "battle"

    overworld_party = _game((18, 0, 149, 0, 101, 17))
    ended = reader.read_battle_probe(overworld_party)
    assert ended is not None and ended.state == "none"
    assert "PartyData" in ended.reason
    # La UI exige dos muestras consecutivas fuera de combate antes de abrir el
    # selector. Tras limpiar el episodio, el mismo overworld sigue publicando
    # ``none`` y permite completar esa compuerta existente sin tocarla.
    confirmed = reader.read_battle_probe(overworld_party)
    assert confirmed is not None and confirmed.state == "none"

    trace = isolated_role_run_log_dir / "usum_battle_health_trace_latest.jsonl"
    events = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    assert any(event.get("event") == "battle-idle-evidence" for event in events)
    assert any(
        event.get("event") == "battle-end"
        and event.get("reason") == "observed-ko-converged-to-party"
        for event in events
    )


def test_alpha62_preexisting_party_zero_cannot_end_forced_replacement() -> None:
    rpc = _BattleRPC()
    reader = _reader(rpc)
    already_fainted = _game((0, 19, 149, 20, 101, 17))
    rpc.displayed = (0, 19, 149, 20, 101, 17)
    rpc.actual = rpc.displayed

    assert reader.read_battle_probe(already_fainted).state == "battle"

    rpc.state = USUM_BATTLE_STATE_IDLE_VALUE
    rpc.phase = USUM_BATTLE_PHASE_IDLE_VALUE
    suspended = reader.read_battle_probe(already_fainted)

    assert suspended is not None and suspended.state == "battle"


def test_idle_timeout_without_any_observed_faint_eventually_ends_the_battle() -> None:
    """Bug real descubierto en directo el 14-09-2026 (ver memoria
    `six-mon-battle-auto-reward`): un combate ganado SIN perder ningún
    Pokémon nunca tiene ninguna baja que converger contra PartyData, así que
    la comprobación de arriba (alpha.62) se queda esperando para siempre y
    ``state`` no vuelve nunca a ``none``. La vía de escape por tiempo real
    -`USUM_BATTLE_IDLE_NO_FAINT_TIMEOUT_SECONDS`- debe cerrarlo igualmente,
    pero solo tras ese margen, nunca antes.
    """
    rpc = _BattleRPC()
    reader = _reader(rpc)
    healthy_party = _game(PARTY_MAXES)

    clock = {"now": 1_000.0}

    with patch("app.usum_live.time.monotonic", side_effect=lambda: clock["now"]):
        baseline = reader.read_battle_probe(healthy_party)
        assert baseline is not None and baseline.state == "battle"

        rpc.state = USUM_BATTLE_STATE_IDLE_VALUE
        rpc.phase = USUM_BATTLE_PHASE_IDLE_VALUE

        # Recién visto el par idle, sin ninguna baja: sigue ambiguo.
        just_idle = reader.read_battle_probe(healthy_party)
        assert just_idle is not None and just_idle.state == "battle"

        # Todavía no ha pasado el margen completo: sigue ambiguo.
        clock["now"] += USUM_BATTLE_IDLE_NO_FAINT_TIMEOUT_SECONDS - 1
        still_waiting = reader.read_battle_probe(healthy_party)
        assert still_waiting is not None and still_waiting.state == "battle"

        # Pasado el margen sin ninguna baja observada: se asume overworld.
        clock["now"] += 2
        ended = reader.read_battle_probe(healthy_party)
        assert ended is not None and ended.state == "none"
        assert "sin ninguna" in ended.reason


def test_idle_timeout_does_not_preempt_a_real_observed_faint_convergence() -> None:
    """El escape por tiempo no debe interferir cuando SÍ hay una baja real que
    converger: esa vía ya estaba probada (ver el primer test de este
    archivo) y debe seguir resolviendo tan pronto como PartyData confirme el
    HP=0, sin esperar el margen de tiempo.
    """
    rpc = _BattleRPC()
    reader = _reader(rpc)
    full_party = _game(PARTY_MAXES)

    clock = {"now": 2_000.0}

    with patch("app.usum_live.time.monotonic", side_effect=lambda: clock["now"]):
        assert reader.read_battle_probe(full_party).state == "battle"

        rpc.displayed = (18, 0, 149, 20, 101, 17)
        rpc.actual = rpc.displayed
        assert reader.read_battle_probe(full_party).state == "battle"

        rpc.state = USUM_BATTLE_STATE_IDLE_VALUE
        rpc.phase = USUM_BATTLE_PHASE_IDLE_VALUE
        # Un instante después del par idle -mucho antes del margen de
        # timeout-, PartyData ya confirma el HP=0: converge de inmediato.
        clock["now"] += 1
        overworld_party = _game((18, 0, 149, 20, 101, 17))
        ended = reader.read_battle_probe(overworld_party)
        assert ended is not None and ended.state == "none"
        assert "sin ninguna" not in ended.reason
