"""``app/pokemon_evolutions.py``: qué especies son alcanzables evolucionando."""

from __future__ import annotations

import unittest

from app.pokemon_evolutions import EVOLUTIONS, evolution_descendants


class PokemonEvolutionsTests(unittest.TestCase):
    def test_cadena_simple_de_tres_etapas(self) -> None:
        self.assertEqual(evolution_descendants(1), frozenset({2, 3}))  # Bulbasaur

    def test_cadena_de_dos_etapas(self) -> None:
        self.assertEqual(evolution_descendants(415), frozenset({416}))  # Combee -> Vespiquen

    def test_eevee_incluye_las_ocho_ramas(self) -> None:
        vaporeon, jolteon, flareon = 134, 135, 136
        espeon, umbreon = 196, 197
        leafeon, glaceon, sylveon = 470, 471, 700
        self.assertEqual(
            evolution_descendants(133),
            frozenset({vaporeon, jolteon, flareon, espeon, umbreon, leafeon, glaceon, sylveon}),
        )

    def test_flabebe_confirmado_en_la_partida_real(self) -> None:
        """Flabébé (669) -> Floette (670) -> Florges (671): el caso que
        destapó el bug real el 2026-09-05."""
        self.assertEqual(evolution_descendants(669), frozenset({670, 671}))

    def test_una_especie_final_no_tiene_descendientes(self) -> None:
        self.assertEqual(evolution_descendants(3), frozenset())  # Venusaur
        self.assertNotIn(3, EVOLUTIONS)

    def test_una_especie_sin_evolucion_conocida_no_tiene_descendientes(self) -> None:
        self.assertEqual(evolution_descendants(999999), frozenset())

    def test_no_se_incluye_la_propia_especie_de_partida(self) -> None:
        self.assertNotIn(1, evolution_descendants(1))


if __name__ == "__main__":
    unittest.main()
