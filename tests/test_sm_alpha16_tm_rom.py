from pathlib import Path
from types import SimpleNamespace

import pytest

from app.sm_rom_service import (
    SMRomProfileError, SM_SUN_TITLE_ID, _SM_TM_SEARCH_START, _SM_TM_SIGNATURE,
    _tm_table_from_code, load_sm_rom_tm_profile,
)


def _code_with_table(values):
    code = bytearray(_SM_TM_SEARCH_START + 0x1000)
    pos = _SM_TM_SEARCH_START + 0x200
    code[pos:pos + len(_SM_TM_SIGNATURE)] = _SM_TM_SIGNATURE
    start = pos + len(_SM_TM_SIGNATURE)
    for index, move_id in enumerate(values):
        code[start + index * 2:start + index * 2 + 2] = int(move_id).to_bytes(2, "little")
    return bytes(code)


def test_alpha16_sm_tm_table_is_100_consecutive_ushorts_after_unique_signature():
    values = list(range(1, 101))
    table = _tm_table_from_code(_code_with_table(values), set(values))
    assert len(table) == 100
    assert table[1].item_id == 328 and table[1].move_id == 1
    assert table[92].item_id == 419
    assert table[93].item_id == 618
    assert table[96].item_id == 690
    assert table[100].item_id == 694 and table[100].move_id == 100


def test_alpha16_sm_tm_table_rejects_ambiguous_signature():
    values = list(range(1, 101))
    first = bytearray(_code_with_table(values))
    pos = _SM_TM_SEARCH_START + 0x700
    first[pos:pos + len(_SM_TM_SIGNATURE)] = _SM_TM_SIGNATURE
    start = pos + len(_SM_TM_SIGNATURE)
    for index, move_id in enumerate(values):
        first[start + index * 2:start + index * 2 + 2] = int(move_id).to_bytes(2, "little")
    with pytest.raises(SMRomProfileError, match="2 tablas"):
        _tm_table_from_code(bytes(first), set(values))


def test_alpha16_loader_rejects_wrong_edition_against_live_title(monkeypatch, tmp_path: Path):
    import app.sm_rom_service as service
    source = tmp_path / "sun.cxi"
    source.write_bytes(b"stub")
    values = list(range(1, 101))
    monkeypatch.setattr(service, "_read_ncch", lambda _path: SimpleNamespace(
        title_id=SM_SUN_TITLE_ID, code=_code_with_table(values), path=source,
    ))
    monkeypatch.setattr(service, "azahar_user_roots", lambda: ())
    with pytest.raises(SMRomProfileError, match="no coincide con la edición"):
        load_sm_rom_tm_profile(
            source, allowed_move_ids=set(values), expected_title_id=0x0004000000175E00,
        )
