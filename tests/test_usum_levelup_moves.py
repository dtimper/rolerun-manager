"""Aprendizajes por nivel de USUM ajustados al rol, vía mod de Azahar.

Confirmado el 2026-09-04 leyendo la ROM real del usuario ("Twitch Ultra Sol
1.cxi", un randomizer): la tabla vive en ``a/0/1/3``, mismo formato de GARC
y de entrada (``<h movimiento, <h nivel>`` terminado en -1,-1) que ya usa
ORAS — reutiliza ``parse_levelup_garc``/``build_party_patched_blob`` sin
tocarlas. La única pieza nueva es la traducción ``(species_id, form) ->
personal_id``: el GARC de USUM tiene 976 ficheros para 807 especies (las
~169 de más son formas alternativas, indexadas por el mismo ``personal_id``
que ya usa la tabla Personal ``a/0/1/7``) — verificado con Venusaur/Mega
Venusaur reales (``personal_id`` 3 y 848).
"""

from __future__ import annotations

import struct
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.oras_levelup_moves import parse_levelup_garc
from app.usum_levelup_moves import LEVELUP_MOVES_PATH, ensure_registered, mod_learnset_path, write_blob
from app.usum_rom_service import USUM_PERSONAL_FORM_COUNT_OFFSET, USUM_PERSONAL_FORM_OFFSET, USUM_PERSONAL_RECORD_SIZE, usum_personal_id_map

TITLE_ID = 0x00040000001B5000

TACKLE, GROWL, VINE_WHIP = 33, 45, 22


def _make_variable_garc(species_entries: dict[int, list[tuple[int, int]]], count: int) -> bytes:
    """GARC sintético de entradas variables (aprendizajes), un fichero por
    índice. Mismo formato que ``tests/test_oras_levelup_moves.py::_make_levelup_garc``
    (FATO/FATB/FIMB), reutilizado aquí porque USUM comparte el formato."""
    records: list[bytes] = []
    for index in range(count):
        pairs = species_entries.get(index, [])
        body = b"".join(struct.pack("<hh", move, level) for move, level in pairs)
        body += struct.pack("<hh", -1, -1)
        records.append(body)

    garc_header_size = 0x1C
    fato_size = 12 + count * 4
    fatb_size = 12 + count * 16
    fimb_size = 12
    data_offset = garc_header_size + fato_size + fatb_size + fimb_size
    data = b"".join(records)
    blob = bytearray(data_offset + len(data))
    blob[:4] = b"GARC"
    struct.pack_into("<IHHIII", blob, 4, garc_header_size, 0xFEFF, 0x0400, 4, data_offset, len(blob))
    pos = garc_header_size
    blob[pos:pos + 4] = b"FATO"
    struct.pack_into("<IHH", blob, pos + 4, fato_size, count, 0)
    pos += fato_size
    blob[pos:pos + 4] = b"FATB"
    struct.pack_into("<II", blob, pos + 4, fatb_size, count)
    pos += 12
    running = 0
    for record in records:
        start = running
        end = start + len(record)
        struct.pack_into("<IIII", blob, pos, 1, start, end, len(record))
        pos += 16
        running = end
    blob[pos:pos + 4] = b"FIMB"
    struct.pack_into("<II", blob, pos + 4, fimb_size, len(data))
    blob[data_offset:data_offset + len(data)] = data
    return bytes(blob)


def _personal_record(*, first_form: int = 0, form_count: int = 0) -> bytes:
    record = bytearray(USUM_PERSONAL_RECORD_SIZE)
    record[:6] = bytes((45, 49, 49, 65, 65, 45))  # stats base cualquiera válida
    record[0x15] = 0  # curva de experiencia
    struct.pack_into("<H", record, USUM_PERSONAL_FORM_OFFSET, first_form)
    record[USUM_PERSONAL_FORM_COUNT_OFFSET] = form_count
    return bytes(record)


class UsumPersonalIdMapTests(unittest.TestCase):
    def test_especie_sin_formas_es_su_propio_personal_id(self) -> None:
        species_count = 3
        flat = bytearray()
        flat += _personal_record()  # índice 0, sin usar
        for _ in range(species_count):
            flat += _personal_record()
        from app import usum_rom_service as mod
        original = mod.USUM_SPECIES_COUNT
        mod.USUM_SPECIES_COUNT = species_count
        try:
            id_map = usum_personal_id_map(bytes(flat))
        finally:
            mod.USUM_SPECIES_COUNT = original
        self.assertEqual(id_map[(1, 0)], 1)
        self.assertEqual(id_map[(2, 0)], 2)
        self.assertEqual(id_map[(3, 0)], 3)
        self.assertNotIn((1, 1), id_map)

    def test_una_forma_alternativa_apunta_a_su_propio_indice(self) -> None:
        """Especie 3 declara 2 formas (base + 1 alternativa), cuyo registro
        vive en el índice 5 de la tabla aplanada -exactamente como Venusaur
        (personal_id=3) y Mega Venusaur (personal_id=848) en la ROM real."""
        species_count = 4
        flat = [bytearray(_personal_record()) for _ in range(species_count + 2)]  # 0..5
        flat[3] = bytearray(_personal_record(first_form=5, form_count=2))
        flat_bytes = b"".join(bytes(row) for row in flat)
        from app import usum_rom_service as mod
        original = mod.USUM_SPECIES_COUNT
        mod.USUM_SPECIES_COUNT = species_count
        try:
            id_map = usum_personal_id_map(flat_bytes)
        finally:
            mod.USUM_SPECIES_COUNT = original
        self.assertEqual(id_map[(3, 0)], 3)
        self.assertEqual(id_map[(3, 1)], 5)


class UsumLevelupMovesPathTests(unittest.TestCase):
    def test_la_ruta_es_la_de_usum_no_la_de_oras(self) -> None:
        self.assertEqual(LEVELUP_MOVES_PATH, "a/0/1/3")

    def test_mod_learnset_path_usa_la_ruta_de_usum(self) -> None:
        root = Path("/tmp/azahar")
        path = mod_learnset_path(root, TITLE_ID)
        self.assertEqual(
            path,
            root / "load" / "mods" / "00040000001B5000" / "romfs" / "a" / "0" / "1" / "3",
        )

    def test_ensure_registered_y_write_blob_reutilizan_la_logica_generica(self) -> None:
        # ``_read_garc_entries`` exige un mínimo de especies calcado del de
        # ORAS (721+1) aunque el GARC sea de USUM — se usa el tamaño real de
        # USUM (976 ficheros) para no toparse con esa cota ajena.
        vanilla = _make_variable_garc({1: [(TACKLE, 1), (GROWL, 3)]}, count=976)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            estado = ensure_registered(root, TITLE_ID, vanilla)
            self.assertEqual(estado, "created")
            target = mod_learnset_path(root, TITLE_ID)
            self.assertEqual(target.read_bytes(), vanilla)

            patched = bytearray(vanilla)
            entries = parse_levelup_garc(vanilla)
            _move, _level, offset = entries[1][0]
            struct.pack_into("<h", patched, offset, VINE_WHIP)
            write_blob(root, TITLE_ID, bytes(patched), expected_size=len(vanilla))
            self.assertEqual(target.read_bytes(), bytes(patched))


if __name__ == "__main__":
    unittest.main()
