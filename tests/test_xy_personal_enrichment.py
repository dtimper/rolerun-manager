"""X/Y: el adaptador enriquece con Personal, igual que ya hacía ORAS.

2026-09-05, reportado por el usuario probando X/Y en vivo: el equipo salía
con "BASE —" en las seis estadísticas y los Pokémon del PC aparecían sin
stats de ningún tipo. Causa: ``XYRealTimeAdapter`` nunca enriquecía lo
leído, a diferencia de ``ORASRealTimeAdapter._enrich_pokemon``, pese a que
X/Y comparte el PK6 de sexta generación y su writer ya recibe la tabla
Personal (``personal_for``).

* El PK6 de PARTY trae stats calculadas pero nunca las base.
* El PK6 ALMACENADO (cajas) no trae ninguna de las dos.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import customtkinter  # noqa: F401
except ModuleNotFoundError:                                  # pragma: no cover
    customtkinter = types.ModuleType("customtkinter")
    customtkinter.CTk = object
    sys.modules["customtkinter"] = customtkinter

import unittest

from app.oras_tm_service import ORASPersonalStats
from app.realtime.xy_adapter import XYRealTimeAdapter
from app.save_engine_client import SavePokemon

# Orden Personal nativo: PS, Atq., Def., Vel., At. Esp., Def. Esp.
DELPHOX_PERSONAL = ORASPersonalStats((75, 69, 72, 104, 114, 100), 0)


def _pokemon(**overrides) -> SavePokemon:
    base = dict(
        slot=1, species_id=655, species="Delphox", nickname="", level=50,
        held_item="", ability="", moves=[], move_ids=[],
        is_egg=False, markings=[False] * 6, role="SIN ROL", role_symbol="",
        pid=1, tid=2, sid=3, form=0,
        nature_id=0,
        ivs={"hp": 31, "attack": 31, "defense": 31, "sp_attack": 31, "sp_defense": 31, "speed": 31},
        evs={"hp": 0, "attack": 0, "defense": 0, "sp_attack": 0, "sp_defense": 0, "speed": 0},
    )
    base.update(overrides)
    return SavePokemon(**base)


def _adapter(*, personal=DELPHOX_PERSONAL) -> XYRealTimeAdapter:
    adapter = XYRealTimeAdapter.__new__(XYRealTimeAdapter)
    adapter.writer = SimpleNamespace(personal_for=lambda species_id, form: personal)
    return adapter


class EnrichPokemonTests(unittest.TestCase):
    def test_un_pokemon_de_party_recibe_sus_stats_base(self) -> None:
        """El PK6 de party ya trae stats calculadas; solo faltaban las base."""
        party_stats = {
            "hp": 160, "attack": 90, "defense": 93, "sp_attack": 136,
            "sp_defense": 121, "speed": 126,
        }
        enriched = _adapter()._enrich_pokemon(_pokemon(stats=dict(party_stats)))
        # Personal nativo -> orden visible (Velocidad al final).
        self.assertEqual(
            enriched.base_stats,
            {"hp": 75, "attack": 69, "defense": 72, "sp_attack": 114, "sp_defense": 100, "speed": 104},
        )
        self.assertEqual(enriched.stats, party_stats, "las stats vivas no se recalculan")

    def test_un_pokemon_de_caja_recibe_base_y_stats_calculadas(self) -> None:
        """El PK6 almacenado no trae ninguna de las dos."""
        enriched = _adapter()._enrich_pokemon(_pokemon(stats={}))
        self.assertEqual(enriched.base_stats["hp"], 75)
        # 31 IV / 0 EV / nivel 50 / naturaleza neutra (id 0 = Fuerte).
        self.assertEqual(enriched.stats["hp"], (2 * 75 + 31) * 50 // 100 + 50 + 10)
        self.assertEqual(enriched.stats["speed"], (2 * 104 + 31) * 50 // 100 + 5)

    def test_sin_personal_no_inventa_nada(self) -> None:
        """Sin ROM validada se devuelve el Pokémon tal cual, sin tabla vanilla."""
        pokemon = _pokemon(stats={})
        enriched = _adapter(personal=None)._enrich_pokemon(pokemon)
        self.assertIs(enriched, pokemon)

    def test_sin_writer_con_personal_for_no_rompe(self) -> None:
        adapter = XYRealTimeAdapter.__new__(XYRealTimeAdapter)
        adapter.writer = SimpleNamespace()
        pokemon = _pokemon(stats={})
        self.assertIs(adapter._enrich_pokemon(pokemon), pokemon)

    def test_un_nivel_invalido_no_tumba_la_lectura_entera(self) -> None:
        """Un hueco raro se queda sin stats, pero sigue dando las base."""
        enriched = _adapter()._enrich_pokemon(_pokemon(stats={}, level=0))
        self.assertEqual(enriched.base_stats["hp"], 75)
        self.assertEqual(enriched.stats, {})

    def test_una_caja_llena_no_repite_la_busqueda_de_personal(self) -> None:
        """930 huecos no pueden ser 930 búsquedas: ``_xy_personal_for_live``
        puede tocar disco la primera vez, así que se memoriza por pasada."""
        llamadas: list[tuple[int, int]] = []

        def personal_for(species_id, form):
            llamadas.append((species_id, form))
            return DELPHOX_PERSONAL

        adapter = XYRealTimeAdapter.__new__(XYRealTimeAdapter)
        adapter.writer = SimpleNamespace(personal_for=personal_for)
        slots = {(1, index): _pokemon(stats={}) for index in range(1, 31)}
        adapter.reader = SimpleNamespace(read_pc=lambda anchors: ("p", 0, slots))

        adapter.read_pc(anchors=None)

        self.assertEqual(len(llamadas), 1, "misma especie/forma: una sola búsqueda")

    def test_el_pc_se_enriquece_hueco_a_hueco(self) -> None:
        adapter = _adapter()
        adapter.reader = SimpleNamespace(read_pc=lambda anchors: (
            "proceso", 0x1234, {(1, 1): _pokemon(stats={}), (1, 2): None},
        ))
        process, base_address, slots = adapter.read_pc(anchors=None)
        self.assertEqual((process, base_address), ("proceso", 0x1234))
        self.assertIsNone(slots[(1, 2)], "un hueco vacío sigue vacío")
        self.assertEqual(slots[(1, 1)].base_stats["hp"], 75)
        self.assertTrue(slots[(1, 1)].stats)


if __name__ == "__main__":
    unittest.main()
