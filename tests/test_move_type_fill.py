"""`move_type_fill` teñe un color de fondo con el color de un tipo, sin
convertirse en el color del tipo -tiene que distinguirse del borde, que se
queda saturado (pedido del usuario 02-09-2026)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import mix_hex_colors, move_type_fill  # noqa: E402


def test_mix_en_ratio_cero_da_el_origen() -> None:
    assert mix_hex_colors("#F08030", "#1B1B1B", 0.0) == "#F08030"


def test_mix_en_ratio_uno_da_el_destino() -> None:
    assert mix_hex_colors("#F08030", "#1B1B1B", 1.0) == "#1B1B1B"


def test_mix_fuera_de_rango_se_recorta() -> None:
    assert mix_hex_colors("#F08030", "#1B1B1B", -5) == "#F08030"
    assert mix_hex_colors("#F08030", "#1B1B1B", 5) == "#1B1B1B"


def test_move_type_fill_se_distingue_del_color_del_tipo() -> None:
    relleno = move_type_fill("#F08030", "#1B1B1B")

    assert relleno != "#F08030"
    assert relleno != "#1B1B1B"


def test_move_type_fill_queda_mas_cerca_del_fondo_que_del_tipo() -> None:
    """El tipo se nota, pero no domina: sigue siendo un fondo oscuro con
    texto claro encima, no un bloque del color puro del tipo."""
    tipo = (0xF0, 0x80, 0x30)
    fondo = (0x1B, 0x1B, 0x1B)
    relleno = move_type_fill("#F08030", "#1B1B1B")
    rgb = tuple(int(relleno[i:i + 2], 16) for i in (1, 3, 5))

    for canal_tipo, canal_fondo, canal_relleno in zip(tipo, fondo, rgb):
        distancia_a_fondo = abs(canal_relleno - canal_fondo)
        distancia_a_tipo = abs(canal_relleno - canal_tipo)
        assert distancia_a_fondo < distancia_a_tipo
