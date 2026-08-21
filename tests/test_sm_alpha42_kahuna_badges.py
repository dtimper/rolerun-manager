from __future__ import annotations

import struct
from pathlib import Path
import pytest

from app.azahar_rpc import AzaharProcess
from app.save_engine_client import SaveGameData
from app.sm_live import (
    SM_ITEMS_LIVEHEX_REFERENCE,
    SM_KAHUNA_ZCRYSTAL_KEY_IDS,
    SM_SAVE_ITEM_BLOCK_SIZE,
    SM_ZCRYSTAL_POCKET_OFFSET,
    SMLiveReader,
    SMLiveWriter,
    count_sm_kahuna_badges,
    parse_sm_saved_kahuna_badges,
    parse_sm_zcrystal_keys,
)


TITLE_ID_SUN = 0x0004000000164800
TITLE_ID_MOON = 0x0004000000175E00


def items_block(crystals: tuple[int, ...] = ()) -> bytes:
    raw = bytearray(SM_SAVE_ITEM_BLOCK_SIZE)
    # Testigos no vacíos fuera del bolsillo Z. Reproducen la condición que
    # evita aceptar como Items una región RAM genérica llena de ceros.
    raw[0x120:0x130] = bytes(range(1, 17))
    raw[0x820:0x830] = bytes(range(17, 33))
    for index, item_id in enumerate(crystals):
        struct.pack_into(
            "<I", raw, SM_ZCRYSTAL_POCKET_OFFSET + (index * 4),
            int(item_id) | (1 << 10),
        )
    return bytes(raw)


def empty_game(name: str = "Pokémon Sol") -> SaveGameData:
    return SaveGameData(
        game=name,
        save_type="SAV7SM + Azahar RPC (SM en vivo)",
        generation=7,
        trainer="Tester",
        party=[],
        raw={"liveSync": True},
    )


@pytest.mark.parametrize("count", range(5))
def test_alpha42_counts_only_exact_kahuna_reward_prefix(count: int) -> None:
    raw = items_block(SM_KAHUNA_ZCRYSTAL_KEY_IDS[:count])
    assert parse_sm_zcrystal_keys(raw) is not None
    assert count_sm_kahuna_badges(raw) == count


def test_alpha42_rejects_gap_in_kahuna_reward_sequence() -> None:
    # Hala + Nanu sin Olivia no se convierte silenciosamente en 2 medallas.
    raw = items_block((SM_KAHUNA_ZCRYSTAL_KEY_IDS[0], SM_KAHUNA_ZCRYSTAL_KEY_IDS[2]))
    assert parse_sm_zcrystal_keys(raw) is not None
    assert count_sm_kahuna_badges(raw) is None


def test_alpha42_rejects_invalid_zcrystal_pocket_structure() -> None:
    raw = bytearray(items_block())
    # Un objeto ajeno al rango de claves Z dentro de este bolsillo invalida la muestra.
    struct.pack_into("<I", raw, SM_ZCRYSTAL_POCKET_OFFSET, 50 | (1 << 10))
    assert parse_sm_zcrystal_keys(bytes(raw)) is None
    assert count_sm_kahuna_badges(bytes(raw)) is None


def test_alpha42_rejects_duplicate_or_quantity_greater_than_one() -> None:
    item_id = SM_KAHUNA_ZCRYSTAL_KEY_IDS[0]
    duplicate = bytearray(items_block((item_id,)))
    struct.pack_into("<I", duplicate, SM_ZCRYSTAL_POCKET_OFFSET + 4, item_id | (1 << 10))
    assert parse_sm_zcrystal_keys(bytes(duplicate)) is None

    quantity_two = bytearray(items_block())
    struct.pack_into("<I", quantity_two, SM_ZCRYSTAL_POCKET_OFFSET, item_id | (2 << 10))
    assert parse_sm_zcrystal_keys(bytes(quantity_two)) is None


def test_alpha42_saved_fallback_reads_absolute_progress(tmp_path: Path) -> None:
    path = tmp_path / "main"
    path.write_bytes(items_block(SM_KAHUNA_ZCRYSTAL_KEY_IDS[:3]))
    assert parse_sm_saved_kahuna_badges(path) == 3


class BadgeRPC:
    def __init__(self, live_items: bytes, *, title_id: int = TITLE_ID_SUN):
        self.live_items = bytes(live_items)
        self.process = AzaharProcess(55, int(title_id), "niji_loc")
        self.reads: list[tuple[int, int]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def process_list(self):
        return [self.process]

    def set_process(self, process_id: int):
        assert int(process_id) == int(self.process.process_id)

    def read_memory(self, address: int, size: int) -> bytes:
        self.reads.append((int(address), int(size)))
        if int(address) == SM_ITEMS_LIVEHEX_REFERENCE:
            return self.live_items[: int(size)]
        return b"\0" * int(size)


def writer_for(fake: BadgeRPC) -> SMLiveWriter:
    reader = SMLiveReader(
        Path("missing-move-catalog.json"),
        client_factory=lambda: fake,
        stable_delay=0,
        snapshot_attempts=1,
    )
    return SMLiveWriter(reader)


@pytest.mark.parametrize("title_id,game_name", [
    (TITLE_ID_SUN, "Pokémon Sol"),
    (TITLE_ID_MOON, "Pokémon Luna"),
])
def test_alpha42_fast_live_candidate_is_structurally_validated_for_both_editions(
    tmp_path: Path, title_id: int, game_name: str,
) -> None:
    # El main sigue en 1; la RAM ya contiene el premio de Olivia. El valor live
    # debe ganar sin esperar a guardar y la misma ruta debe aceptar Sol y Luna.
    saved = items_block(SM_KAHUNA_ZCRYSTAL_KEY_IDS[:1])
    live = items_block(SM_KAHUNA_ZCRYSTAL_KEY_IDS[:2])
    path = tmp_path / "main"
    path.write_bytes(saved)
    fake = BadgeRPC(live, title_id=title_id)
    writer = writer_for(fake)

    value = writer.read_kahuna_badges_for_game(
        empty_game(game_name), path, party_base=0x34195E10, allow_full_scan=False,
    )

    assert value == 2
    assert writer.last_badge_source == "Z-Crystals vivos · candidata LiveHeX validada"
    assert fake.reads.count((SM_ITEMS_LIVEHEX_REFERENCE, SM_SAVE_ITEM_BLOCK_SIZE)) == 2


def test_alpha42_does_not_trust_candidate_that_fails_structural_witness(tmp_path: Path) -> None:
    saved = items_block(SM_KAHUNA_ZCRYSTAL_KEY_IDS[:1])
    path = tmp_path / "main"
    path.write_bytes(saved)
    # 0xFF no puede pasar ni el testigo estructural ni el parser del bolsillo.
    fake = BadgeRPC(b"\xFF" * SM_SAVE_ITEM_BLOCK_SIZE)
    writer = writer_for(fake)

    value = writer.read_kahuna_badges_for_game(
        empty_game(), path, party_base=0x34195E10, allow_full_scan=False,
    )

    assert value == 1  # fallback del main, nunca la candidata falsa
    assert writer.last_badge_source == "main · Z-Crystals (fallback)"




def test_alpha42_adapter_publishes_badges_and_source_in_monitor_snapshot(tmp_path: Path) -> None:
    from app.realtime.sm_adapter import SMRealTimeAdapter
    from app.sm_live import SMBattleProbe, SMLiveSnapshot

    current = empty_game()
    process = AzaharProcess(99, TITLE_ID_SUN, "niji_loc")
    raw = SMLiveSnapshot(
        game=current, process=process, attempts=1,
        party_base=0x34195E10, memory_blocks=(), runtime_party_region=b"",
    )
    reader = SMLiveReader(Path("missing-move-catalog.json"), stable_delay=0)
    reader.read_monitor = lambda _current, memory_blocks=(): raw  # type: ignore[method-assign]
    reader.read_battle_probe = lambda _current: SMBattleProbe(  # type: ignore[method-assign]
        state="none", validated=True, reason="test",
    )
    adapter = SMRealTimeAdapter(reader)

    path = tmp_path / "main"
    path.write_bytes(items_block())

    def read_badges(_current, _path, *, party_base=None, allow_full_scan=True):
        assert party_base == 0x34195E10
        assert allow_full_scan is True
        adapter.writer._last_badge_source = "Z-Crystals vivos · test"
        return 3

    adapter.writer.read_kahuna_badges_for_game = read_badges  # type: ignore[method-assign]
    snapshot = adapter.capture_monitor(current, save_path=path)

    assert snapshot.badges == 3
    assert snapshot.badge_source == "Z-Crystals vivos · test"
    assert any(diagnostic.lane == "badges" for diagnostic in snapshot.diagnostics)
    assert adapter.runtime_state()["capabilities"]["progress"] == "read-live-alpha.42-kahuna-zcrystals-validated"
