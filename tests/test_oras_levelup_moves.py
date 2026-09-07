"""Aprendizajes por nivel de ORAS ajustados al rol vía mod de Azahar.

Validado físicamente el 2026-09-03 contra una partida real en Azahar/
AzaharPlus (Alfa Zafiro): tanto el registro inicial del mod
(``load/mods/<título>/romfs/a/1/9/1``) como una reescritura de su contenido
en caliente, sin reiniciar el título, cambiaron el movimiento que el juego
ofreció al subir de nivel. Estas pruebas cubren la lógica que decidió qué
sustituir (sin ningún emulador) y la gestión del archivo de mod en disco.
"""

from __future__ import annotations

import json
import struct
import unittest
import unittest.mock
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from app import oras_levelup_moves as mod
from app.oras_levelup_moves import (
    build_party_patched_blob,
    compute_species_patch,
    ensure_registered,
    mod_learnset_path,
    parse_levelup_garc,
    write_blob,
)
from app.oras_rom_service import _ORAS_MAX_MOVE_ID, load_oras_levelup_moves_blob
from app.ui import RoleRunManager

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

# IDs de movimiento reales, reconocibles, usados solo como datos de prueba.
TACKLE, GROWL, VINE_WHIP, LEECH_SEED = 33, 45, 22, 73
THUNDER, EARTHQUAKE, SURF, MIMIC = 87, 89, 57, 102
SUBSTITUTE = 164


def _make_levelup_garc(species_entries: dict[int, list[tuple[int, int]]], count: int = 722) -> bytes:
    """GARC sintético válido para ``_read_garc_entries``, con aprendizajes por nivel.

    Reproduce el mismo formato de cabecera FATO/FATB/FIMB que ya usa la tabla
    personal en ``tests/test_oras_tm.py``, adaptado a registros de tamaño
    variable (pares movimiento/nivel terminados en -1,-1) en vez de los
    registros fijos de estadísticas.
    """
    records: list[bytes] = []
    for species_id in range(count):
        pairs = species_entries.get(species_id, [])
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


BULBASAUR_VANILLA = [(TACKLE, 1), (GROWL, 3), (VINE_WHIP, 7), (LEECH_SEED, 9)]
PIKACHU_VANILLA = [(THUNDER, 1), (EARTHQUAKE, 10)]  # Trueno especial, Terremoto físico.


class RoleRules:
    """Carga las mismas reglas de rol que ya usan MT y drafteo."""

    @classmethod
    def setUpClass(cls) -> None:  # type: ignore[override]
        cls.pools = json.loads((DATA / "moves.json").read_text(encoding="utf-8-sig"))
        metadata = json.loads((DATA / "move_rules_metadata.json").read_text(encoding="utf-8-sig"))
        cls.damage_classes = {int(k): str(v) for k, v in metadata["damage_classes"].items()}
        cls.speed_status_moves = {int(v) for v in metadata["speed_status_moves"]}
        cls.self_healing_damage_moves = {int(v) for v in metadata["self_healing_damage_moves"]}
        cls.usable_move_ids = set(range(1, _ORAS_MAX_MOVE_ID + 1))


class ParseLevelupGarcTests(unittest.TestCase):
    def test_decodifica_pares_movimiento_nivel_por_especie(self) -> None:
        blob = _make_levelup_garc({1: BULBASAUR_VANILLA, 25: PIKACHU_VANILLA})
        entries = parse_levelup_garc(blob)

        self.assertEqual(len(entries), 722)
        bulbasaur = [(move, level) for move, level, _offset in entries[1]]
        self.assertEqual(bulbasaur, BULBASAUR_VANILLA)
        pikachu = [(move, level) for move, level, _offset in entries[25]]
        self.assertEqual(pikachu, PIKACHU_VANILLA)
        # Una especie sin entradas de prueba decodifica a una lista vacía, no
        # a un error: el terminador -1,-1 es su única entrada.
        self.assertEqual(entries[2], ())

    def test_los_offsets_apuntan_exactamente_al_id_de_movimiento(self) -> None:
        blob = _make_levelup_garc({1: BULBASAUR_VANILLA})
        entries = parse_levelup_garc(blob)
        for move_id, _level, offset in entries[1]:
            self.assertEqual(struct.unpack_from("<h", blob, offset)[0], move_id)


class ComputeSpeciesPatchTests(RoleRules, unittest.TestCase):
    def test_sin_filtro_los_pools_reales_contienen_movimientos_que_ORAS_no_reconoce(self) -> None:
        """Documenta el bug real del 2026-09-03, no lo repite.

        ``data/moves.json`` es común a todos los juegos y llega a IDs de
        movimiento de generaciones muy posteriores a ORAS (máximo real 621).
        La primera integración en ``app/ui.py`` olvidó pasar
        ``usable_move_ids`` y ofreció el movimiento 905 a un Houndoom real —
        el juego lo mostró con nombre en blanco, tipo Normal y 0 PP. Este
        test deja constancia de que el problema sigue presente en los datos
        (así que el filtro de ``usable_move_ids`` en todas las llamadas de
        producción sigue siendo necesario, no un caso ya resuelto por otra
        vía) y no que se repita nunca sin él.
        """
        fuera_de_rango = {
            int(move_id)
            for ids in self.pools.values()
            for move_id in ids
            if int(move_id) > _ORAS_MAX_MOVE_ID
        }
        self.assertTrue(fuera_de_rango, "si esto deja de fallar, revisar si el filtro sigue haciendo falta")
        self.assertIn(905, fuera_de_rango)

    def test_asesino_sustituye_un_movimiento_especial_por_uno_fisico(self) -> None:
        entries = ((THUNDER, 4, 100),)  # Trueno es especial.
        patch = compute_species_patch(
            entries, "Asesino", species_id=25,
            pools=self.pools, damage_classes=self.damage_classes,
            speed_status_moves=self.speed_status_moves,
            self_healing_damage_moves=self.self_healing_damage_moves,
            usable_move_ids=self.usable_move_ids,
        )
        self.assertEqual(set(patch), {100})
        self.assertEqual(self.damage_classes.get(patch[100]), "physical")

    def test_mago_sustituye_un_movimiento_fisico_por_uno_especial(self) -> None:
        entries = ((TACKLE, 1, 200),)  # Placaje es físico.
        patch = compute_species_patch(
            entries, "Mago", species_id=1,
            pools=self.pools, damage_classes=self.damage_classes,
            speed_status_moves=self.speed_status_moves,
            self_healing_damage_moves=self.self_healing_damage_moves,
            usable_move_ids=self.usable_move_ids,
        )
        self.assertEqual(set(patch), {200})
        self.assertEqual(self.damage_classes.get(patch[200]), "special")

    def test_tanque_evita_un_movimiento_de_daño_con_recuperacion_de_ps(self) -> None:
        healing_move = next(iter(self.self_healing_damage_moves))
        damage_class = self.damage_classes[healing_move]
        entries = ((healing_move, 20, 300),)
        patch = compute_species_patch(
            entries, "Tanque", species_id=1,
            pools=self.pools, damage_classes=self.damage_classes,
            speed_status_moves=self.speed_status_moves,
            self_healing_damage_moves=self.self_healing_damage_moves,
            usable_move_ids=self.usable_move_ids,
        )
        self.assertIn(300, patch)
        self.assertNotIn(patch[300], self.self_healing_damage_moves)
        self.assertEqual(self.damage_classes.get(patch[300]), damage_class)

    def test_support_no_toca_movimientos_de_daño(self) -> None:
        entries = ((THUNDER, 1, 400), (TACKLE, 5, 404))
        patch = compute_species_patch(
            entries, "Support", species_id=25,
            pools=self.pools, damage_classes=self.damage_classes,
            speed_status_moves=self.speed_status_moves,
            self_healing_damage_moves=self.self_healing_damage_moves,
            usable_move_ids=self.usable_move_ids,
        )
        self.assertEqual(patch, {})

    def test_libero_no_sustituye_nada(self) -> None:
        entries = tuple(BULBASAUR_VANILLA[index] + (index * 4,) for index in range(len(BULBASAUR_VANILLA)))
        patch = compute_species_patch(
            entries, "Líbero", species_id=1,
            pools=self.pools, damage_classes=self.damage_classes,
            speed_status_moves=self.speed_status_moves,
            self_healing_damage_moves=self.self_healing_damage_moves,
            usable_move_ids=self.usable_move_ids,
        )
        self.assertEqual(patch, {})

    def test_sin_rol_no_sustituye_nada(self) -> None:
        entries = ((THUNDER, 1, 500),)
        patch = compute_species_patch(
            entries, "SIN ROL", species_id=25,
            pools=self.pools, damage_classes=self.damage_classes,
            speed_status_moves=self.speed_status_moves,
            self_healing_damage_moves=self.self_healing_damage_moves,
            usable_move_ids=self.usable_move_ids,
        )
        self.assertEqual(patch, {})

    def test_el_sustituto_es_determinista(self) -> None:
        entries = ((THUNDER, 4, 600),)
        first = compute_species_patch(
            entries, "Asesino", species_id=25,
            pools=self.pools, damage_classes=self.damage_classes,
            speed_status_moves=self.speed_status_moves,
            self_healing_damage_moves=self.self_healing_damage_moves,
            usable_move_ids=self.usable_move_ids,
        )
        second = compute_species_patch(
            entries, "Asesino", species_id=25,
            pools=self.pools, damage_classes=self.damage_classes,
            speed_status_moves=self.speed_status_moves,
            self_healing_damage_moves=self.self_healing_damage_moves,
            usable_move_ids=self.usable_move_ids,
        )
        self.assertEqual(first, second)


class BuildPartyPatchedBlobTests(RoleRules, unittest.TestCase):
    def test_solo_toca_las_especies_con_rol_y_conserva_el_tamano(self) -> None:
        vanilla = _make_levelup_garc({1: BULBASAUR_VANILLA, 25: PIKACHU_VANILLA})
        patched = build_party_patched_blob(
            vanilla, {25: "Asesino"},
            pools=self.pools, damage_classes=self.damage_classes,
            speed_status_moves=self.speed_status_moves,
            self_healing_damage_moves=self.self_healing_damage_moves,
            usable_move_ids=self.usable_move_ids,
        )
        self.assertEqual(len(patched), len(vanilla))

        entries_before = parse_levelup_garc(vanilla)
        entries_after = parse_levelup_garc(patched)
        # Bulbasaur no tenía rol asignado: su fila queda exactamente igual.
        self.assertEqual(entries_before[1], entries_after[1])
        # Pikachu (Asesino) pierde Trueno (especial) y conserva Terremoto (físico).
        pikachu_after = [(move, level) for move, level, _offset in entries_after[25]]
        self.assertNotIn((THUNDER, 1), pikachu_after)
        self.assertIn((EARTHQUAKE, 10), pikachu_after)

    def test_una_especie_sin_rol_asignado_no_aparece_en_el_resultado(self) -> None:
        vanilla = _make_levelup_garc({1: BULBASAUR_VANILLA})
        patched = build_party_patched_blob(
            vanilla, {},
            pools=self.pools, damage_classes=self.damage_classes,
            speed_status_moves=self.speed_status_moves,
            self_healing_damage_moves=self.self_healing_damage_moves,
            usable_move_ids=self.usable_move_ids,
        )
        self.assertEqual(patched, vanilla)


class ModFileManagementTests(unittest.TestCase):
    TITLE_ID = 0x000400000011C500

    def test_mod_learnset_path_sigue_el_layout_de_layeredfs(self) -> None:
        root = Path("/tmp/azahar")
        path = mod_learnset_path(root, self.TITLE_ID)
        self.assertEqual(
            path,
            root / "load" / "mods" / "000400000011C500" / "romfs" / "a" / "1" / "9" / "1",
        )

    def test_ensure_registered_crea_el_archivo_una_sola_vez(self) -> None:
        vanilla = _make_levelup_garc({1: BULBASAUR_VANILLA})
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first = ensure_registered(root, self.TITLE_ID, vanilla)
            self.assertEqual(first, "created")
            target = mod_learnset_path(root, self.TITLE_ID)
            self.assertEqual(target.read_bytes(), vanilla)

            # Una segunda llamada no debe pisar un contenido ya activo (podría
            # llevar roles aplicados por una sesión anterior).
            target.write_bytes(vanilla + b"\x00")  # contenido distinto, a propósito
            second = ensure_registered(root, self.TITLE_ID, vanilla)
            self.assertEqual(second, "size_mismatch")

    def test_write_blob_exige_el_mismo_tamano_ya_registrado(self) -> None:
        vanilla = _make_levelup_garc({1: BULBASAUR_VANILLA})
        with TemporaryDirectory() as directory:
            root = Path(directory)
            ensure_registered(root, self.TITLE_ID, vanilla)
            with self.assertRaises(ValueError):
                write_blob(root, self.TITLE_ID, vanilla + b"\x00\x00", expected_size=len(vanilla))

    def test_write_blob_reescribe_el_contenido_en_caliente(self) -> None:
        vanilla = _make_levelup_garc({1: BULBASAUR_VANILLA})
        patched = bytearray(vanilla)
        struct.pack_into("<h", patched, 0, MIMIC)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            ensure_registered(root, self.TITLE_ID, vanilla)
            write_blob(root, self.TITLE_ID, bytes(patched), expected_size=len(vanilla))
            target = mod_learnset_path(root, self.TITLE_ID)
            self.assertEqual(target.read_bytes(), bytes(patched))


class LoadOrasLevelupMovesBlobTests(unittest.TestCase):
    def _make_oras_cxi_with_levelup_table(self, path: Path) -> bytes:
        """CXI mínima cuyo único archivo RomFS es ``a/1/9/1``.

        Reutiliza el mismo truco que ``tests/test_oras_tm.py``: RomFS no
        necesita directorios anidados de verdad para que
        ``_find_romfs_file`` encuentre la ruta, basta con que el nombre del
        único archivo bajo la raíz sea el string completo de la ruta.
        """
        levelup = _make_levelup_garc({1: BULBASAUR_VANILLA, 25: PIKACHU_VANILLA})

        code = bytearray(0x400)
        exefs_offset = 0x2000
        romfs_offset = 0x6000
        level3_offset = romfs_offset + 0x60
        file_data_offset = 0x100
        image = bytearray(level3_offset + file_data_offset + len(levelup))
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
        struct.pack_into("<QQ", image, file + 8, 0, len(levelup))
        name = "a/1/9/1".encode("utf-16le")
        struct.pack_into("<II", image, file + 0x18, 0xFFFFFFFF, len(name))
        image[file + 0x20:file + 0x20 + len(name)] = name
        image[level3_offset + file_data_offset:level3_offset + file_data_offset + len(levelup)] = levelup
        path.write_bytes(image)
        return bytes(levelup)

    def test_lee_la_tabla_de_aprendizajes_de_una_rom_sintetica(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "oras-sintetica.cxi"
            expected = self._make_oras_cxi_with_levelup_table(source)
            blob, title_id = load_oras_levelup_moves_blob(source, process_name="sango-2")

        self.assertEqual(blob, expected)
        self.assertEqual(title_id, 0x000400000011C500)
        entries = parse_levelup_garc(blob)
        bulbasaur = [(move, level) for move, level, _offset in entries[1]]
        self.assertEqual(bulbasaur, BULBASAUR_VANILLA)


class SyncOrasLevelupMovesModWiringTests(RoleRules, unittest.TestCase):
    """Prueba la función real de app/ui.py, no una réplica.

    El bug del 2026-09-03 no estaba en ``compute_species_patch`` (ya
    probado arriba con ``usable_move_ids``): estaba en que
    ``_sync_oras_levelup_moves_mod`` nunca se lo pasaba al llamar al módulo
    desde la aplicación real. Un test que solo llamara a la lógica pura con
    los parámetros "correctos" no lo habría detectado nunca.
    """

    def test_siempre_pasa_usable_move_ids_al_calcular_el_parche(self) -> None:
        """Verifica la llamada real, no que la lógica pura funcione bien.

        El bug del 2026-09-03 era exactamente que ``_sync_oras_levelup_moves_mod``
        no le pasaba ``usable_move_ids`` a ``build_party_patched_blob`` — un
        test que solo comprobara el resultado final podría no toparse con un
        movimiento fuera de rango según qué sustituto tocara al azar. Este
        test espía la llamada real y exige que el argumento nunca falte ni
        sea ``None``, tanto si ``engine.allowed_move_ids`` ya está poblado
        como si no (el caso que expuso el bug).
        """
        vanilla = _make_levelup_garc({229: [(THUNDER, 4)]})
        for allowed_move_ids in (None, {THUNDER, EARTHQUAKE, SURF}):
            with TemporaryDirectory() as directory:
                root = Path(directory)
                title_id = 0x000400000011C500
                ensure_registered(root, title_id, vanilla)

                fake = SimpleNamespace(
                    save_engine=SimpleNamespace(key="oras"),
                    engine=SimpleNamespace(
                        pools=self.pools, damage_classes=self.damage_classes,
                        speed_status_moves=self.speed_status_moves,
                        self_healing_damage_moves=self.self_healing_damage_moves,
                        allowed_move_ids=allowed_move_ids,
                    ),
                    _oras_levelup_moves_vanilla=vanilla,
                    _oras_levelup_moves_title_id=title_id,
                    _oras_levelup_moves_azahar_root=root,
                    _oras_levelup_moves_last_written=None,
                    _oras_levelup_moves_last_roles_key=None,
                    _oras_levelup_moves_vanilla_entries=None,
                    _effective_role=lambda pokemon: ("Mago", ""),
                    _registrar_intento_vivo=lambda *a, **k: None,
                    # El recuerda-movimientos es una función aparte, con sus
                    # propios tests; aquí solo importa que se llame sin
                    # reventar cuando el fake no tiene lo que ella necesita.
                    _record_oras_levelup_move_history=lambda *a, **k: None,
                )
                houndoom = SimpleNamespace(species_id=229)
                game = SimpleNamespace(party=[houndoom])

                real = mod.build_party_patched_blob
                calls = []

                def spy(*args, **kwargs):
                    calls.append(kwargs)
                    return real(*args, **kwargs)

                with unittest.mock.patch.object(mod, "build_party_patched_blob", spy):
                    RoleRunManager._sync_oras_levelup_moves_mod(fake, game)

            self.assertEqual(len(calls), 1, f"con allowed_move_ids={allowed_move_ids!r}")
            usable = calls[0].get("usable_move_ids")
            self.assertIsNotNone(usable, f"con allowed_move_ids={allowed_move_ids!r}")
            self.assertTrue(
                all(1 <= move_id <= _ORAS_MAX_MOVE_ID for move_id in usable),
                f"usable_move_ids contiene IDs fuera de rango: {usable!r}",
            )


if __name__ == "__main__":
    unittest.main()
