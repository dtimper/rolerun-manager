"""Parcheo en vivo del búfer de anuncio de aprendizajes de USUM.

2026-09-04, validado físicamente contra la partida real del usuario: el
diálogo "X quiere aprender Y" no lee la tabla del mod en cada aprendizaje —
lee un búfer de trabajo en RAM (pares movimiento+nivel) que solo se
reconstruye al cargar la escena o abrir la ficha del Pokémon. Esta pieza
localiza y reescribe ese búfer directamente. Ver el docstring de
``app/usum_levelup_announcement_cache.py`` para el porqué de cada paso.
"""

from __future__ import annotations

import struct
import unittest
from unittest.mock import MagicMock

from app.usum_levelup_announcement_cache import (
    PAIR_STRIDE,
    find_guest_cache_addresses,
    find_host_addresses_for_pattern,
    patch_species_announcement_cache,
)

# Tabla de ejemplo: (movimiento, nivel, clave) — niveles no triviales para
# que el ancla no coincida por casualidad con relleno de ceros.
ENTRIES = ((261, 1, "a"), (292, 1, "b"), (610, 13, "c"), (378, 17, "d"), (101, 37, "e"))


def _pairs_bytes(move_ids: list[int], levels: list[int]) -> bytes:
    return b"".join(struct.pack("<HH", mv, lvl) for mv, lvl in zip(move_ids, levels))


class FindGuestCacheAddressesTests(unittest.TestCase):
    def test_encuentra_el_ancla_de_niveles_con_movimientos_cualquiera(self) -> None:
        levels = [lvl for _mv, lvl, _key in ENTRIES]
        noise = b"\x00" * 40
        buffer_bytes = _pairs_bytes([999, 998, 997, 996, 995], levels)
        client = MagicMock()
        client.read_memory.return_value = noise + buffer_bytes + noise
        party_base = 0x1000
        hits = find_guest_cache_addresses(client, party_base=party_base, levels=levels)
        self.assertEqual(len(hits), 1)
        # La dirección encontrada debe apuntar exactamente al inicio del búfer.
        base_addr = client.read_memory.call_args[0][0]
        self.assertEqual(hits[0] - base_addr, len(noise))

    def test_una_secuencia_de_niveles_distinta_no_coincide(self) -> None:
        client = MagicMock()
        client.read_memory.return_value = _pairs_bytes([1, 2, 3], [5, 6, 7])
        hits = find_guest_cache_addresses(client, party_base=0x1000, levels=[1, 1, 1])
        self.assertEqual(hits, [])

    def test_sin_niveles_no_hace_ninguna_lectura(self) -> None:
        client = MagicMock()
        hits = find_guest_cache_addresses(client, party_base=0x1000, levels=[])
        self.assertEqual(hits, [])
        client.read_memory.assert_not_called()

    def test_scan_span_amplia_la_ventana_leida(self) -> None:
        """2026-09-05: para X/Y el búfer vive a ~13 MiB de la party -muy
        fuera de la ventana por defecto, validada solo para USUM/SM-, así
        que su orquestación pide una ventana más ancha explícitamente."""
        client = MagicMock()
        client.read_memory.return_value = b"\x00" * 100
        custom_span = 40 * 1024 * 1024
        find_guest_cache_addresses(
            client, party_base=0x1000000, levels=[1], scan_span=custom_span,
        )
        called_base, called_size = client.read_memory.call_args[0]
        self.assertEqual(called_size, custom_span)
        self.assertEqual(called_base, 0x1000000 - custom_span // 2)


class FindHostAddressesForPatternTests(unittest.TestCase):
    def test_ignora_regiones_pequenas_y_devuelve_hits_de_las_grandes(self) -> None:
        wpm = MagicMock()
        wpm.iter_writable_regions.return_value = [
            (0x2000, 1024),  # demasiado pequeña, se ignora
            (0x5000, 64 * 1024 * 1024),
        ]
        wpm._scan_region.return_value = [0x5100, 0x5900]
        hits = find_host_addresses_for_pattern(wpm, handle=object(), pattern=b"abc")
        self.assertEqual(hits, [0x5100, 0x5900])
        self.assertEqual(wpm._scan_region.call_count, 1)


class PatchSpeciesAnnouncementCacheTests(unittest.TestCase):
    def _client(self, guest_addr: int, current_move_ids: list[int], levels: list[int]) -> MagicMock:
        client = MagicMock()

        def read_memory(address, size):
            if address == guest_addr:
                return _pairs_bytes(current_move_ids, levels)
            # ventana amplia del escaneo: coloca el búfer en su sitio, resto ceros
            span_base = guest_addr - 0  # simplificado: el test llama con party_base=guest_addr+offset conocido
            return b"\x00" * size
        client.read_memory.side_effect = read_memory
        return client

    def test_reescribe_todas_las_copias_encontradas_y_revalida_antes_de_escribir(self) -> None:
        levels = [lvl for _mv, lvl, _key in ENTRIES]
        vanilla_ids = [mv for mv, _lvl, _key in ENTRIES]
        want = {"a": 111, "c": 222}  # solo dos entradas necesitan sustituto
        expected_move_ids = [want.get(key, mv) for mv, _lvl, key in ENTRIES]

        guest_addr = 0x33000000
        guest_bytes = _pairs_bytes(vanilla_ids, levels)

        client = MagicMock()
        # primera lectura (escaneo): ventana con el búfer embebido
        window = b"\x00" * 16 + guest_bytes + b"\x00" * 16
        client.read_memory.side_effect = [window, guest_bytes]

        wpm = MagicMock()
        wpm.iter_writable_regions.return_value = [(0x9000000, 64 * 1024 * 1024)]
        host_hit = 0x9001234
        wpm._scan_region.return_value = [host_hit]
        wpm.read.return_value = guest_bytes  # coincide con lo esperado -> se escribe

        patched = patch_species_announcement_cache(
            client, wpm, handle=object(),
            party_base=guest_addr + 16,  # la ventana se centra alrededor de esto
            entries=ENTRIES,
            move_ids_by_key=want,
        )

        self.assertEqual(patched, 1)
        wpm.write.assert_called_once()
        written_addr, written_payload = wpm.write.call_args[0][1], wpm.write.call_args[0][2]
        self.assertEqual(written_addr, host_hit)
        decoded = [
            struct.unpack_from("<HH", written_payload, i * PAIR_STRIDE)
            for i in range(len(ENTRIES))
        ]
        self.assertEqual([mv for mv, _lvl in decoded], expected_move_ids)
        self.assertEqual([lvl for _mv, lvl in decoded], levels)

    def test_no_escribe_si_el_nivel_cambio_entre_localizar_y_escribir(self) -> None:
        """Revalidación de seguridad: si el búfer ya no tiene los niveles
        esperados justo antes de traducir a Windows, se descarta esa copia
        en vez de escribir a ciegas sobre lo que sea que haya ahora."""
        levels = [lvl for _mv, lvl, _key in ENTRIES]
        vanilla_ids = [mv for mv, _lvl, _key in ENTRIES]
        guest_addr = 0x33000000
        guest_bytes_at_scan = _pairs_bytes(vanilla_ids, levels)
        # en la relectura de verificación, el nivel de la última entrada cambió
        mutated_levels = levels[:-1] + [levels[-1] + 1]
        guest_bytes_at_reread = _pairs_bytes(vanilla_ids, mutated_levels)

        client = MagicMock()
        window = b"\x00" * 16 + guest_bytes_at_scan + b"\x00" * 16
        client.read_memory.side_effect = [window, guest_bytes_at_reread]

        wpm = MagicMock()

        patched = patch_species_announcement_cache(
            client, wpm, handle=object(),
            party_base=guest_addr + 16,
            entries=ENTRIES,
            move_ids_by_key={},
        )

        self.assertEqual(patched, 0)
        wpm.write.assert_not_called()

    def test_scan_span_se_reenvia_a_la_busqueda_en_ram_huesped(self) -> None:
        client = MagicMock()
        client.read_memory.return_value = b"\x00" * 100
        wpm = MagicMock()
        custom_span = 40 * 1024 * 1024
        patch_species_announcement_cache(
            client, wpm, handle=object(), party_base=0x1000000,
            entries=ENTRIES, move_ids_by_key={}, scan_span=custom_span,
        )
        _called_base, called_size = client.read_memory.call_args[0]
        self.assertEqual(called_size, custom_span)

    def test_ningun_hit_no_lanza_y_devuelve_cero(self) -> None:
        client = MagicMock()
        client.read_memory.return_value = b"\x00" * 100
        wpm = MagicMock()
        patched = patch_species_announcement_cache(
            client, wpm, handle=object(), party_base=0x1000,
            entries=ENTRIES, move_ids_by_key={},
        )
        self.assertEqual(patched, 0)
        wpm.write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
