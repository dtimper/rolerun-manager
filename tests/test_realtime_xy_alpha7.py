from __future__ import annotations

import struct
from pathlib import Path

from app.azahar_rpc import AzaharProcess
from app.models import PendingTeamChange
from app.save_engine_client import SaveGameData, SavePokemon
from app.xy_live import (
    XYLiveReader,
    XYLiveWriter,
    XY_MISC_BADGES_OFFSET,
    XY_MISC_KNOWN_ADDRESS,
    XY_SAVE_MISC_OFFSET,
    XY_SAVE_MISC_SIZE,
    XY_TM_POUCH_ADDRESS,
    XY_TM_POUCH_ADDRESS_V10,
    XY_TM_POUCH_SIZE,
    XY_BATTLE_PARTY_PTR_1,
    XY_BATTLE_PARTY_PTR_2,
    XY_BATTLE_OPPONENT_PTR_1,
    XY_BATTLE_OPPONENT_PTR_2,
    XY_BATTLE_HP_OFFSET,
    XY_TITLE_IDS,
)
from app.oras_tm_service import oras_tm_item_id
from app.live_party_watch import detect_fainted_transitions


class MemoryClient:
    def __init__(self, regions: dict[int, bytes | bytearray]):
        self.regions = {int(k): bytearray(v) for k, v in regions.items()}
        self.process = AzaharProcess(1, next(iter(XY_TITLE_IDS)), "kujira-1")
        self.reads: list[tuple[int, int]] = []

    def __enter__(self): return self
    def __exit__(self, *_): return None
    def process_list(self): return [self.process]
    def set_process(self, _pid): return None

    def read_memory(self, address: int, size: int) -> bytes:
        self.reads.append((int(address), int(size)))
        out = bytearray(size)
        end = address + size
        for base, data in self.regions.items():
            a = max(address, base)
            b = min(end, base + len(data))
            if a < b:
                out[a-address:b-address] = data[a-base:b-base]
        return bytes(out)

    def write_memory(self, address: int, data: bytes) -> None:
        for base, region in self.regions.items():
            if base <= address and address + len(data) <= base + len(region):
                region[address-base:address-base+len(data)] = data
                return
        self.regions[address] = bytearray(data)


def mon(slot=1, *, species=25, pid=111, hp=30, max_hp=47) -> SavePokemon:
    return SavePokemon(
        slot=slot, species_id=species, species=f"Species{species}", nickname=f"P{slot}",
        level=10, held_item="", ability="", moves=["Placaje"], move_ids=[33],
        is_egg=False, markings=[False] * 6, role="Líbero", role_symbol="●",
        pid=pid, tid=1, sid=2, current_hp=hp, max_hp=max_hp,
    )


def game(*party: SavePokemon) -> SaveGameData:
    return SaveGameData(game="xy", save_type="XY", generation=6, trainer="Test", party=list(party), raw={})


def test_alpha7_badges_use_validated_known_misc_before_dynamic_scan(tmp_path: Path) -> None:
    saved_misc = bytearray(XY_SAVE_MISC_SIZE)
    # Huella suficiente fuera de dinero/medallas/BP.
    for i in range(0x20, 0x70):
        saved_misc[i] = (i * 7) & 0xFF
    saved_misc[XY_MISC_BADGES_OFFSET] = 0
    live_misc = bytearray(saved_misc)
    live_misc[XY_MISC_BADGES_OFFSET] = 1

    main = tmp_path / "main"
    blob = bytearray(XY_SAVE_MISC_OFFSET + XY_SAVE_MISC_SIZE)
    blob[XY_SAVE_MISC_OFFSET:XY_SAVE_MISC_OFFSET + XY_SAVE_MISC_SIZE] = saved_misc
    main.write_bytes(blob)

    fake = MemoryClient({XY_MISC_KNOWN_ADDRESS: live_misc})
    reader = XYLiveReader(Path("missing.json"), client_factory=lambda: fake, stable_delay=0)
    writer = XYLiveWriter(reader, move_pp_for=lambda _m: 10)
    writer._discover_misc = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no debe barrer"))

    assert writer.read_badges(main) == 1
    assert writer.last_badge_source == "Misc vivo X/Y"
    assert writer.block_resolver.cached_address((int(fake.process.title_id), fake.process.name), "xy.misc") == XY_MISC_KNOWN_ADDRESS


def test_alpha7_tm_pouch_uses_xy_exact_size_and_known_address_without_scan() -> None:
    mt01 = oras_tm_item_id(1)
    assert mt01 is not None
    pouch = bytearray(XY_TM_POUCH_SIZE)
    struct.pack_into("<HH", pouch, 0, mt01, 1)
    fake = MemoryClient({XY_TM_POUCH_ADDRESS: pouch})
    reader = XYLiveReader(Path("missing.json"), client_factory=lambda: fake, stable_delay=0)
    writer = XYLiveWriter(reader, move_pp_for=lambda _m: 10)
    writer._discover_tm_pouch = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no debe barrer"))

    inventory, _process, _attempt = writer.read_tm_inventory({})
    assert XY_TM_POUCH_SIZE == 0x1A4
    assert inventory[mt01] == 1
    assert any(address == XY_TM_POUCH_ADDRESS and size == 0x1A4 for address, size in fake.reads)


def _pointer_region(pointer: int) -> bytes:
    return struct.pack("<I", pointer)


def _battle_target(max_hp: int, current_hp: int) -> bytearray:
    raw = bytearray(XY_BATTLE_HP_OFFSET + 4)
    struct.pack_into("<HH", raw, XY_BATTLE_HP_OFFSET, max_hp, current_hp)
    return raw


def test_alpha10_battle_probe_uses_redundant_active_battler_not_fake_six_slot_table() -> None:
    # PARTY_1/PARTY_2 son dos copias del battler activo, no slots consecutivos.
    assert XY_BATTLE_PARTY_PTR_2 != XY_BATTLE_PARTY_PTR_1 + 4
    pa, pb, opa, opb = 0x08210000, 0x08211000, 0x08212000, 0x08213000
    fake = MemoryClient({
        XY_BATTLE_PARTY_PTR_1: _pointer_region(pa),
        XY_BATTLE_PARTY_PTR_2: _pointer_region(pb),
        XY_BATTLE_OPPONENT_PTR_1: _pointer_region(opa),
        XY_BATTLE_OPPONENT_PTR_2: _pointer_region(opb),
        pa: _battle_target(47, 22), pb: _battle_target(47, 22),
        opa: _battle_target(39, 20), opb: _battle_target(39, 20),
    })
    reader = XYLiveReader(Path("missing.json"), client_factory=lambda: fake, stable_delay=0)
    tank = mon(1, hp=22, max_hp=47)
    libero = mon(2, species=133, pid=222, hp=35, max_hp=47)

    # Battler 1 vivo: se identifica por current/max aunque comparta max HP.
    probe = reader.read_battle_probe(game(tank, libero))
    assert probe is not None and probe.health_game is not None
    first_health = probe.health_game
    assert first_health.party[0].current_hp == 22
    assert first_health.party[1].current_hp == 35

    # Muere el tanque: solo él pasa a 0.
    struct.pack_into("<HH", fake.regions[pa], XY_BATTLE_HP_OFFSET, 47, 0)
    struct.pack_into("<HH", fake.regions[pb], XY_BATTLE_HP_OFFSET, 47, 0)
    probe = reader.read_battle_probe(game(tank, libero))
    assert probe is not None and probe.health_game is not None
    faint_health = probe.health_game
    assert faint_health.party[0].current_hp == 0
    assert faint_health.party[1].current_hp == 35
    assert len(detect_fainted_transitions(first_health, faint_health)) == 1

    # Entra Líbero con el MISMO max HP: 0 -> positivo fuerza remapeo y no puede
    # interpretarse como una segunda muerte.
    struct.pack_into("<HH", fake.regions[pa], XY_BATTLE_HP_OFFSET, 47, 35)
    struct.pack_into("<HH", fake.regions[pb], XY_BATTLE_HP_OFFSET, 47, 35)
    tank_dead = mon(1, hp=0, max_hp=47)
    probe = reader.read_battle_probe(game(tank_dead, libero))
    assert probe is not None and probe.health_game is not None
    switch_health = probe.health_game
    assert switch_health.party[0].current_hp == 0
    assert switch_health.party[1].current_hp == 35
    assert not detect_fainted_transitions(faint_health, switch_health)

    # Muere el Pokémon DEL RIVAL: los PS del jugador no se tocan.
    struct.pack_into("<HH", fake.regions[opa], XY_BATTLE_HP_OFFSET, 39, 0)
    struct.pack_into("<HH", fake.regions[opb], XY_BATTLE_HP_OFFSET, 39, 0)
    probe = reader.read_battle_probe(game(tank_dead, libero))
    assert probe is not None and probe.health_game is not None
    opponent_faint_health = probe.health_game
    assert opponent_faint_health.party[0].current_hp == 0
    assert opponent_faint_health.party[1].current_hp == 35
    assert not detect_fainted_transitions(switch_health, opponent_faint_health)


def test_alpha7_battle_probe_reports_none_outside_battle() -> None:
    fake = MemoryClient({})
    reader = XYLiveReader(Path("missing.json"), client_factory=lambda: fake, stable_delay=0)
    probe = reader.read_battle_probe(game(mon()))
    assert probe is not None
    assert probe.state == "none"
    assert probe.health_game is None


def test_alpha7_writer_allows_replace_fainted_but_still_blocks_party_resize() -> None:
    class R:
        client_factory = staticmethod(lambda: None)
        transport_label = "fake"
    writer = XYLiveWriter(R(), move_pp_for=lambda _m: 10)
    replace = PendingTeamChange(
        operation="replace-fainted", party_slot=1, box=2, box_slot=3,
        outgoing_pokemon="A", incoming_pokemon="B", graveyard_box=4, graveyard_box_slot=1,
    )
    deposit = PendingTeamChange(
        operation="party-to-box", party_slot=1, box=2, box_slot=3,
        outgoing_pokemon="A",
    )
    assert writer._unsupported_changes([replace]) == []
    assert writer._unsupported_changes([deposit])


def test_alpha7_adapter_reports_live_battle_capability() -> None:
    from app.realtime.xy_adapter import XYRealTimeAdapter
    class R:
        client_factory = staticmethod(lambda: None)
        transport_label = "fake"
        def reset_runtime_state(self): pass
    class W:
        block_resolver = type("B", (), {"last_resolutions": ()})()
        def reset_runtime_state(self): pass
    adapter = XYRealTimeAdapter(R(), W(), live_badges=True)
    caps = adapter.runtime_state()["capabilities"]
    assert caps["badges"] == "read-live-with-save-fallback"
    assert caps["battle"] == "read-live-with-postbattle-fallback"
