from __future__ import annotations

import os
import struct
import unittest
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.oras_rom_service import (
    ORASRomProfileError,
    discover_azahar_oras_source,
    load_oras_rom_tm_profile,
)
from app.oras_tm_service import load_fvx_oras_tm_profile, load_oras_tm_profile, oras_tm_item_id


def _bps_number(value: int) -> bytes:
    """Codifica el entero variable que usa BPS para un parche de prueba."""
    encoded = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            encoded.append(byte)
            value -= 1
        else:
            encoded.append(byte | 0x80)
            return bytes(encoded)


def _make_bps(source: bytes, target: bytes, changed_at: int, changed: bytes) -> bytes:
    """Crea un BPS mínimo SourceRead/TargetRead/SourceRead para la prueba."""
    assert target == source[:changed_at] + changed + source[changed_at + len(changed):]
    patch = bytearray(b"BPS1")
    patch.extend(_bps_number(len(source)))
    patch.extend(_bps_number(len(target)))
    patch.extend(_bps_number(0))  # Sin metadatos.
    if changed_at:
        patch.extend(_bps_number(((changed_at - 1) << 2) | 0))
    patch.extend(_bps_number(((len(changed) - 1) << 2) | 1))
    patch.extend(changed)
    remaining = len(source) - changed_at - len(changed)
    if remaining:
        patch.extend(_bps_number(((remaining - 1) << 2) | 0))
    patch.extend(struct.pack("<II", zlib.crc32(source) & 0xFFFFFFFF, zlib.crc32(target) & 0xFFFFFFFF))
    patch.extend(struct.pack("<I", zlib.crc32(patch) & 0xFFFFFFFF))
    return bytes(patch)


def _make_oras_cxi(path: Path) -> bytes:
    """Genera una CXI mínima con las dos tablas que lee el adaptador.

    No contiene ningún dato del juego: es una estructura sintética para que la
    prueba cubra NCCH, RomFS, GARC, MT93+ y una forma alternativa.
    """
    code = bytearray(0x400)
    prefix_at = 0x50
    code[prefix_at:prefix_at + 8] = bytes.fromhex("D400AE02AF02B002")
    table = prefix_at + 8
    moves = [25] * 100
    moves[31] = 11
    moves[79] = 89
    moves[92] = 528
    moves[99] = 590
    for index, move_id in enumerate(moves[:92]):
        struct.pack_into("<H", code, table + index * 2, move_id)
    second = table + 98 * 2
    for index, move_id in enumerate(moves[92:]):
        struct.pack_into("<H", code, second + index * 2, move_id)

    count = 723  # registro 0, 721 especies y una forma de prueba.
    record_size = 0x50
    garc_header_size = 0x1C
    fato_size = 12 + count * 4
    fatb_size = 12 + count * 16
    fimb_size = 12
    data_offset = garc_header_size + fato_size + fatb_size + fimb_size
    personal = bytearray(data_offset + count * record_size)
    personal[:4] = b"GARC"
    struct.pack_into("<IHHIII", personal, 4, garc_header_size, 0xFEFF, 0x0400, 4, data_offset, len(personal))
    struct.pack_into("<I", personal, 24, record_size)
    pos = garc_header_size
    personal[pos:pos + 4] = b"FATO"
    struct.pack_into("<IHH", personal, pos + 4, fato_size, count, 0)
    pos += fato_size
    personal[pos:pos + 4] = b"FATB"
    struct.pack_into("<II", personal, pos + 4, fatb_size, count)
    pos += 12
    for index in range(count):
        start = index * record_size
        struct.pack_into("<IIII", personal, pos, 1, start, start + record_size, record_size)
        pos += 16
    personal[pos:pos + 4] = b"FIMB"
    struct.pack_into("<II", personal, pos + 4, fimb_size, count * record_size)
    for species_id in range(1, 722):
        entry = data_offset + species_id * record_size
        personal[entry:entry + 6] = bytes((45, 49, 49, 45, 65, 65))
        personal[entry + 0x15] = 0  # Crecimiento medio rápido.
        personal[entry + 40] = 0x01  # MT01 para todas las especies base.
    poochyena = data_offset + 261 * record_size
    personal[poochyena + 40:poochyena + 54] = b"\0" * 14
    personal[poochyena + 43] = 0x80  # MT32 (bit 7 del cuarto byte).
    bulbasaur = data_offset + 3 * record_size
    struct.pack_into("<H", personal, bulbasaur + 28, 722)
    personal[bulbasaur + 32] = 2
    form = data_offset + 722 * record_size
    personal[form:form + 6] = bytes((80, 82, 83, 80, 100, 100))
    personal[form + 0x15] = 5
    personal[form + 49] = 0x80  # MT80 (byte 9, bit 7).

    exefs_offset = 0x2000
    romfs_offset = 0x6000
    level3_offset = romfs_offset + 0x60
    file_data_offset = 0x100
    image = bytearray(level3_offset + file_data_offset + len(personal))
    image[0x100:0x104] = b"NCCH"
    image[0x118:0x120] = (0x000400000011C500).to_bytes(8, "little")
    image[0x150:0x15A] = b"CTR-P-ECLA"
    struct.pack_into("<I", image, 0x1A0, exefs_offset // 0x200)
    struct.pack_into("<I", image, 0x1B0, romfs_offset // 0x200)
    exefs = exefs_offset
    image[exefs:exefs + 5] = b".code"
    struct.pack_into("<II", image, exefs + 8, 0, len(code))
    image[exefs + 0x200:exefs + 0x200 + len(code)] = code
    image[romfs_offset:romfs_offset + 4] = b"IVFC"
    struct.pack_into("<I", image, romfs_offset + 0x08, 0)
    struct.pack_into("<I", image, romfs_offset + 0x4C, 0)
    struct.pack_into("<I", image, level3_offset, 0x28)
    struct.pack_into("<II", image, level3_offset + 0x0C, 0x28, 0x20)
    struct.pack_into("<III", image, level3_offset + 0x1C, 0x48, 0x60, file_data_offset)
    directory = level3_offset + 0x28
    struct.pack_into("<III", image, directory + 4, 0xFFFFFFFF, 0xFFFFFFFF, 0)
    file = level3_offset + 0x48
    struct.pack_into("<I", image, file + 4, 0xFFFFFFFF)
    struct.pack_into("<QQ", image, file + 8, 0, len(personal))
    struct.pack_into("<II", image, file + 0x18, 0xFFFFFFFF, len("a/1/9/5".encode("utf-16le")))
    image[file + 0x20:file + 0x20 + 14] = "a/1/9/5".encode("utf-16le")
    image[level3_offset + file_data_offset:level3_offset + file_data_offset + len(personal)] = personal
    path.write_bytes(image)
    return bytes(code)


def _make_oras_cci(path: Path) -> None:
    """Envuelve la CXI sintética en una CCI cuya partición no está en 0x4000."""
    cxi_path = path.with_suffix(".cxi")
    _make_oras_cxi(cxi_path)
    cxi = cxi_path.read_bytes()
    partition_offset = 0x6000
    image = bytearray(partition_offset + len(cxi))
    image[0x100:0x104] = b"NCSD"
    struct.pack_into("<II", image, 0x120, partition_offset // 0x200, (len(cxi) + 0x1FF) // 0x200)
    image[partition_offset:partition_offset + len(cxi)] = cxi
    path.write_bytes(image)
    cxi_path.unlink()


class ORASTMProfileTests(unittest.TestCase):
    def test_standard_oras_profile_has_machine_table_and_compatibility(self) -> None:
        profile = load_oras_tm_profile(Path("data/oras_tms.json"))
        self.assertEqual(len(profile.tms), 100)
        self.assertGreaterEqual(len(profile.compatibility), 700)
        self.assertEqual((profile.tm(1).item_id, profile.tm(1).move_id), (328, 468))
        self.assertEqual(profile.tm(93).item_id, 618)
        self.assertEqual(profile.tm(100).item_id, 694)
        self.assertTrue(profile.can_learn(261, 0, 97))  # Poochyena -> Pulso Umbrío
        self.assertFalse(profile.can_learn(261, 0, 24))  # No aprende Rayo en el juego base.

    def test_fvx_log_loads_real_tm_map_and_windows_compatibility_section(self) -> None:
        """Los logs de FVX normalmente se escriben con saltos de línea CRLF."""
        tm_lines = [
            f"TM{number:02d} {'Vice Grip' if number == 32 else 'Mega Kick'}"
            for number in range(1, 101)
        ]
        species_lines = []
        for species_id in range(1, 701):
            learned = "TM32 Vice Grip" if species_id == 261 else "TM01 Mega Kick"
            species_lines.extend((f"#{species_id:03d} Species {species_id}", f"\t{learned}"))
        content = "\r\n".join([
            "==========================================================",
            "( TM Moves {TMMV} )",
            *tm_lines,
            "",
            "==========================================================",
            "( TM/HM Compatibility {TMCB} )",
            "--By Species:--",
            *species_lines,
            "",
            "--By TM/HM:--",
            "TM01 Mega Kick",
            "\t#001 Species 1",
            "",
            "==========================================================",
        ])
        with TemporaryDirectory() as directory:
            source = Path(directory) / "randomized-oras.log"
            source.write_text(content, encoding="utf-8")
            profile = load_fvx_oras_tm_profile(source)

        self.assertEqual(profile.source_kind, "fvx")
        self.assertEqual(len(profile.tms), 100)
        self.assertGreaterEqual(len(profile.compatibility), 700)
        self.assertEqual((profile.tm(1).item_id, profile.tm(1).move_id), (328, 25))
        # Universal Pokémon Randomizer FVX usa la grafía inglesa histórica
        # "Vice Grip"; el catálogo de PKHeX usa "Vise Grip".
        self.assertEqual((profile.tm(32).item_id, profile.tm(32).move_id), (359, 11))
        self.assertTrue(profile.can_learn(261, 0, 32))
        self.assertFalse(profile.can_learn(261, 0, 1))

    def test_oras_tm_item_ids_include_the_two_non_contiguous_oras_blocks(self) -> None:
        self.assertEqual(oras_tm_item_id(1), 328)
        self.assertEqual(oras_tm_item_id(92), 419)
        self.assertEqual(oras_tm_item_id(93), 618)
        self.assertEqual(oras_tm_item_id(95), 620)
        self.assertEqual(oras_tm_item_id(96), 690)
        self.assertEqual(oras_tm_item_id(100), 694)
        self.assertIsNone(oras_tm_item_id(101))

    def test_generic_rom_reader_uses_native_oras_tables_and_forms(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "randomizer-ajeno.cxi"
            _make_oras_cxi(source)
            profile = load_oras_rom_tm_profile(source, process_name="sango-2")

        self.assertEqual(profile.source_kind, "rom")
        self.assertEqual((profile.tm(1).item_id, profile.tm(1).move_id), (328, 25))
        self.assertEqual((profile.tm(32).item_id, profile.tm(32).move_id), (359, 11))
        self.assertEqual((profile.tm(80).item_id, profile.tm(80).move_id), (407, 89))
        self.assertEqual((profile.tm(93).item_id, profile.tm(93).move_id), (618, 528))
        self.assertEqual((profile.tm(100).item_id, profile.tm(100).move_id), (694, 590))
        self.assertTrue(profile.can_learn(261, 0, 32))
        self.assertFalse(profile.can_learn(261, 0, 1))
        self.assertTrue(profile.can_learn(3, 1, 80))
        self.assertFalse(profile.can_learn(3, 0, 80))
        self.assertEqual(profile.personal_for(261, 0).base_stats, (45, 49, 49, 45, 65, 65))
        self.assertEqual(profile.personal_for(3, 1).base_stats, (80, 82, 83, 80, 100, 100))
        self.assertEqual(profile.personal_for(3, 1).exp_growth, 5)

    def test_generic_reader_uses_the_ncsd_partition_table_for_a_3ds_image(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "repacked-randomizer.3ds"
            _make_oras_cci(source)
            profile = load_oras_rom_tm_profile(source, process_name="sango-2")

        self.assertEqual(profile.tm(93).item_id, 618)
        self.assertEqual(profile.tm(93).move_id, 528)

    def test_rom_reader_refuses_a_rom_that_does_not_match_azahar_process(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "zafiro-alfa.cxi"
            _make_oras_cxi(source)
            with self.assertRaises(ORASRomProfileError):
                load_oras_rom_tm_profile(source, process_name="sango-1")

    def test_generic_reader_applies_active_bps_mod_before_reading_mt_table(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "randomizer-ajeno.cxi"
            code = _make_oras_cxi(source)
            # MT01 ocupa los dos primeros bytes posteriores a la firma.
            changed_at = 0x50 + 8
            target = bytearray(code)
            target[changed_at:changed_at + 2] = struct.pack("<H", 468)
            root = Path(directory) / "Azahar"
            patch = root / "load" / "mods" / "000400000011c500" / "exefs" / "code.bps"
            patch.parent.mkdir(parents=True)
            patch.write_bytes(_make_bps(code, bytes(target), changed_at, bytes(target[changed_at:changed_at + 2])))
            profile = load_oras_rom_tm_profile(source, process_name="sango-2", azahar_root=root)

        self.assertEqual(profile.tm(1).move_id, 468)
        self.assertIn("mod BPS code.bps", profile.source_detail)

    def test_discovery_reads_the_last_oras_rom_from_azahar_log(self) -> None:
        with TemporaryDirectory() as directory:
            appdata = Path(directory) / "AppData"
            root = appdata / "Azahar"
            rom = Path(directory) / "mi randomizer.cxi"
            _make_oras_cxi(rom)
            log = root / "log" / "azahar_log.txt"
            log.parent.mkdir(parents=True)
            log.write_text(f"Loader: Loading file {rom} as NCCH...\n", encoding="utf-8")
            with patch.dict(os.environ, {"APPDATA": str(appdata), "LOCALAPPDATA": ""}, clear=False):
                discovered = discover_azahar_oras_source("sango-2")

        self.assertIsNotNone(discovered)
        self.assertEqual(discovered.path, rom.resolve())


if __name__ == "__main__":
    unittest.main()
