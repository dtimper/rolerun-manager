from __future__ import annotations

import struct

from app.xy_rom_service import _tm_table_from_xy_code, XYRomProfileError
from app.oras_rom_service import _TM_PREFIX


def _code_with_xy_tm_table(values: list[int]) -> bytes:
    assert len(values) == 100
    start = 0x500
    raw = bytearray(0x2000)
    raw[start:start + len(_TM_PREFIX)] = _TM_PREFIX
    data = start + len(_TM_PREFIX)
    for index, value in enumerate(values[:92]):
        struct.pack_into("<H", raw, data + index * 2, value)
    # 92..96 are HMs in X/Y; TM93 begins at physical entry 97.
    for index, value in enumerate(values[92:]):
        struct.pack_into("<H", raw, data + (97 + index) * 2, value)
    return bytes(raw)


def test_xy_tm_table_uses_xy_gap_not_oras_gap():
    values = list(range(1, 101))
    table = _tm_table_from_xy_code(_code_with_xy_tm_table(values))
    assert table[1].move_id == 1
    assert table[92].move_id == 92
    assert table[93].move_id == 93
    assert table[100].move_id == 100


def test_xy_tm_table_rejects_oras_only_move_ids():
    values = list(range(1, 101))
    values[-1] = 621
    try:
        _tm_table_from_xy_code(_code_with_xy_tm_table(values))
    except XYRomProfileError:
        pass
    else:
        raise AssertionError("X/Y no debe aceptar una tabla que use un movimiento posterior a XY")


def test_alpha10_xy_profile_uses_azahar_layeredfs_personal_compatibility(tmp_path, monkeypatch):
    """Un randomizer LayeredFS debe ganar al Personal GARC del .3ds base."""
    from pathlib import Path
    import app.xy_rom_service as xy
    from app.oras_rom_service import _NCCHData, ORASPersonalStats
    from app.oras_tm_service import ORASTM

    rom = tmp_path / "Pokemon X.3ds"
    rom.write_bytes(b"stub")
    base = _NCCHData(rom, xy.XY_X_TITLE_ID, "CTR-P-EKJA", b"BASECODE", b"BASEPERSONAL")
    root = tmp_path / "Azahar"
    override = root / "load" / "mods" / f"{xy.XY_X_TITLE_ID:016X}" / "romfs" / "a" / "2" / "1" / "8"
    override.parent.mkdir(parents=True)
    override.write_bytes(b"RANDOMIZED_PERSONAL")

    monkeypatch.setattr(xy, "_read_xy_ncch", lambda _path: base)
    monkeypatch.setattr(xy, "azahar_user_roots", lambda: (root,))
    monkeypatch.setattr(xy, "_find_xy_update", lambda *_args: None)
    monkeypatch.setattr(
        xy, "_compatibility_from_personal",
        lambda raw: {664: frozenset({83})} if raw == b"RANDOMIZED_PERSONAL" else {664: frozenset()},
    )
    monkeypatch.setattr(
        xy, "_stats_from_personal",
        lambda _raw: {664: ORASPersonalStats((38, 35, 40, 35, 27, 25), 0)},
    )
    monkeypatch.setattr(xy, "_tm_table_from_xy_code", lambda _code: {83: ORASTM(83, 410, 611)})

    profile = xy.load_xy_rom_tm_profile(rom, emulator_key="azahar")
    assert profile.can_learn(664, 0, 83) is True
    assert "mod RomFS personal" in profile.source_detail


def test_alpha8_tm_pouch_accepts_v10_known_address_and_first_live_tm_without_saved_witnesses() -> None:
    """Movida desde `test_citra_broker_alpha8.py` (retirado el 07-09-2026 con el

    resto del soporte de Citra): esta cobertura es genérica de X/Y -parsing de
    la bolsa de MT sobre el transporte Azahar-, sin relación real con Citra.
    """
    import struct
    from pathlib import Path
    from app.azahar_rpc import AzaharProcess
    from app.oras_tm_service import oras_tm_item_id
    from app.xy_live import (
        XYLiveReader, XYLiveWriter, XY_TM_POUCH_ADDRESS_V10, XY_TM_POUCH_SIZE, XY_TITLE_IDS,
    )

    tm83 = oras_tm_item_id(83)
    assert tm83 is not None
    pouch = bytearray(XY_TM_POUCH_SIZE)
    struct.pack_into("<HH", pouch, 0, int(tm83), 1)

    class Memory:
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def process_list(self): return [AzaharProcess(1, next(iter(XY_TITLE_IDS)), "kujira-1")]
        def set_process(self, _pid): return None
        def read_memory(self, address, size):
            if XY_TM_POUCH_ADDRESS_V10 <= address < XY_TM_POUCH_ADDRESS_V10 + len(pouch):
                start = address - XY_TM_POUCH_ADDRESS_V10
                return bytes(pouch[start:start+size]).ljust(size, b"\0")
            return bytes(size)

    reader = XYLiveReader(Path("missing.json"), client_factory=Memory, stable_delay=0)
    writer = XYLiveWriter(reader, move_pp_for=lambda _m: 10)
    inventory, _process, _attempt = writer.read_tm_inventory({})
    assert inventory[int(tm83)] == 1
    assert XY_TM_POUCH_SIZE == 0x1A4
