"""Decodificar WazaOboeTable: aprendizajes vainilla de BDSP por especie/forma.

Confirmado el 2026-09-03 contra el ``personal_masterdatas`` real del
usuario: ``WazaOboeTable`` existe, indexada por ``personal_id`` (el mismo
identificador de forma que usa ``PersonalTable``), con cada fila
``[personal_id, [nivel, movimiento, nivel, movimiento, ...]]`` — una lista
plana de pares intercalados nivel/movimiento. Estos fixtures reproducen esa
misma forma con datos sintéticos, no con la ROM real.
"""

from __future__ import annotations

import unittest

from app.bdsp_levelup_moves import parse_wazaoboe_table

THUNDER, EARTHQUAKE, TACKLE = 87, 89, 33


def _personal_table(rows: list[tuple[int, int, int, int]]) -> list:
    """``rows`` = (valid_flag, personal_id, species_id, form_index)."""
    return [None, None, None, "PersonalTable", [list(row) + [0] * 34 for row in rows]]


def _waza_oboe_table(rows: list[tuple[int, list[int]]]) -> list:
    """``rows`` = (personal_id, [nivel, movimiento, nivel, movimiento, ...])."""
    return [None, None, None, "WazaOboeTable", [[pid, list(flat)] for pid, flat in rows]]


class ParseWazaOboeTableTests(unittest.TestCase):
    def test_decodifica_pares_nivel_movimiento_por_especie(self) -> None:
        objects = {
            "PersonalTable": _personal_table([(1, 229, 229, 0)]),
            "WazaOboeTable": _waza_oboe_table([(229, [4, THUNDER, 8, EARTHQUAKE])]),
        }
        tabla = parse_wazaoboe_table(objects)
        self.assertEqual(
            tabla[(229, 0)],
            ((THUNDER, 4, 0), (EARTHQUAKE, 8, 1)),
        )

    def test_una_forma_no_base_usa_su_propio_form_id(self) -> None:
        """``personal_id`` distinto de ``species_id``: forma no base."""
        objects = {
            "PersonalTable": _personal_table([
                (1, 201, 201, 0),  # Unown forma A: personal_id == species_id
                (1, 202, 201, 1),  # Unown forma B: form_index=1 -> form_id = 202-1+1 = 202
            ]),
            "WazaOboeTable": _waza_oboe_table([
                (201, [1, TACKLE]),
                (202, [1, THUNDER]),
            ]),
        }
        tabla = parse_wazaoboe_table(objects)
        self.assertEqual(tabla[(201, 0)], ((TACKLE, 1, 0),))
        self.assertEqual(tabla[(201, 202)], ((THUNDER, 1, 0),))

    def test_una_fila_sin_aprendizajes_no_aparece_en_el_resultado(self) -> None:
        objects = {
            "PersonalTable": _personal_table([(0, 0, 0, 0)]),
            "WazaOboeTable": _waza_oboe_table([(0, [])]),
        }
        tabla = parse_wazaoboe_table(objects)
        self.assertEqual(tabla, {})

    def test_sin_wazaoboetable_lanza_un_error_claro(self) -> None:
        objects = {"PersonalTable": _personal_table([(1, 1, 1, 0)])}
        with self.assertRaises(ValueError):
            parse_wazaoboe_table(objects)


if __name__ == "__main__":
    unittest.main()
