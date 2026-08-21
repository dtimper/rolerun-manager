from __future__ import annotations

import unittest

from app.pc_browser import (
    filter_pc_pokemon,
    normalize_pc_search_text,
    pokemon_matches_pc_query,
    reset_scrollable_to_top,
)
from app.save_engine_client import SavePokemon


def pokemon(*, species: str, nickname: str = "", ability: str = "", moves=None, box=1, slot=1) -> SavePokemon:
    return SavePokemon(
        slot=slot,
        species_id=1,
        species=species,
        nickname=nickname,
        level=50,
        held_item="",
        ability=ability,
        moves=list(moves or []),
        move_ids=[0, 0, 0, 0],
        is_egg=False,
        markings=[False] * 6,
        role="SIN ROL",
        role_symbol="",
        box=box,
        box_slot=slot,
    )


class Alpha44PCBrowserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.entries = [
            pokemon(
                species="Gardevoir", nickname="Luz", ability="Rastro",
                moves=["Psíquico", "Paz Mental", "Brillo Mágico", "Protección"],
                box=1, slot=30,
            ),
            pokemon(
                species="Breloom", nickname="Seta", ability="Antídoto",
                moves=["Espora", "Puño Drenaje", "Bomba Germen", "Danza Espada"],
                box=2, slot=2,
            ),
            pokemon(
                species="Pikachu", nickname="Chispa", ability="Electricidad Estática",
                moves=["Onda Trueno", "Rayo"], box=7, slot=4,
            ),
        ]

    def test_search_is_case_and_accent_insensitive(self) -> None:
        self.assertTrue(pokemon_matches_pc_query(self.entries[0], "PSIQUICO"))
        self.assertTrue(pokemon_matches_pc_query(self.entries[1], "antidoto"))
        self.assertEqual(normalize_pc_search_text("Pokémon Élite"), "pokemon elite")

    def test_searches_species_nickname_ability_and_moves(self) -> None:
        self.assertEqual(filter_pc_pokemon(self.entries, "gardevoir"), [self.entries[0]])
        self.assertEqual(filter_pc_pokemon(self.entries, "seta"), [self.entries[1]])
        self.assertEqual(filter_pc_pokemon(self.entries, "electricidad estatica"), [self.entries[2]])
        self.assertEqual(filter_pc_pokemon(self.entries, "onda trueno"), [self.entries[2]])

    def test_multiple_words_can_match_different_fields(self) -> None:
        self.assertEqual(filter_pc_pokemon(self.entries, "chispa rayo estatica"), [self.entries[2]])
        self.assertEqual(filter_pc_pokemon(self.entries, "breloom espora antidoto"), [self.entries[1]])

    def test_results_keep_original_box_and_slot(self) -> None:
        result = filter_pc_pokemon(self.entries, "puño drenaje")
        self.assertEqual(len(result), 1)
        self.assertEqual((result[0].box, result[0].box_slot), (2, 2))
        self.assertIs(result[0], self.entries[1])

    def test_empty_query_returns_all_entries(self) -> None:
        self.assertEqual(filter_pc_pokemon(self.entries, ""), self.entries)

    def test_scroll_reset_targets_parent_canvas(self) -> None:
        class Canvas:
            def __init__(self):
                self.values = []
            def yview_moveto(self, value):
                self.values.append(value)
        class Frame:
            def __init__(self):
                self._parent_canvas = Canvas()
        frame = Frame()
        self.assertTrue(reset_scrollable_to_top(frame))
        self.assertEqual(frame._parent_canvas.values, [0.0])

    def test_scroll_reset_falls_back_to_canvas(self) -> None:
        class Broken:
            def yview_moveto(self, value):
                raise RuntimeError("old canvas")
        class Canvas:
            def __init__(self): self.value = None
            def yview_moveto(self, value): self.value = value
        class Frame:
            _parent_canvas = Broken()
            _canvas = Canvas()
        frame = Frame()
        self.assertTrue(reset_scrollable_to_top(frame))
        self.assertEqual(frame._canvas.value, 0.0)


if __name__ == "__main__":
    unittest.main()
