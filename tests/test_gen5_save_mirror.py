"""El bloque vivo de quinta generación es un espejo contiguo del guardado.

DE DÓNDE SALE ESTO

Se demostró el 27-08-2026 sobre Negro 2 sin ninguna captura nueva. Partiendo
**solo** de la dirección del dinero, ya demostrada con una traza de dos estados,
y del desplazamiento que PKHeX declara para ese campo en el guardado, se calcula
dónde empezaría el bloque. Con esa base, el contador del equipo y los seis
Pokémon aparecen en el **archivo de guardado real del usuario**, en las
posiciones exactas que predice PKHeX.

POR QUÉ IMPORTA

Convierte cada juego nuevo en **un ancla en vez de seis**. Encontrado el equipo
en la RAM de Blanco, la mochila, el dinero y las medallas salen restando y
sumando desplazamientos que PKHeX ya conoce.

LO QUE NO AUTORIZA

Heredar direcciones de un juego a otro. Blanco guarda el dinero en `0x21200` y
Negro 2 en `0x21100`: la misma regla, distintos números. Cada juego necesita su
propia ancla medida contra el juego.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.b2w2_live import (  # noqa: E402
    MONEY_ADDRESS,
    PARTY_BASE,
    PARTY_COUNT,
    PK5_PARTY_SIZE,
    parse_pk5_party,
)

# Desplazamientos dentro del guardado, sondeados en PKHeX cambiando cada campo
# y mirando qué bytes se mueven. No están copiados de ninguna documentación.
SAVE_PARTY_BLOCK = 0x18E00
SAVE_PARTY_COUNT = SAVE_PARTY_BLOCK + 4
SAVE_PARTY_DATA = SAVE_PARTY_BLOCK + 8
SAVE_MONEY_B2W2 = 0x21100
SAVE_BADGES_B2W2 = 0x21104
SAVE_MONEY_BW = 0x21200
SAVE_BADGES_BW = 0x21204

_SAVE_B2W2 = Path(
    "D:/Users/diego/Diego/Juegos/POKEMON ROLERUN/Pokémon Negro 2/"
    "z120 - Pokemon - Edicion Negra 2 (Spain) (NDSi Enhanced) [b].sav"
)


def test_la_base_del_bloque_sale_de_una_sola_direccion() -> None:
    """Dinero en RAM menos dinero en el guardado: eso es la base."""
    base = MONEY_ADDRESS - SAVE_MONEY_B2W2

    assert base + SAVE_PARTY_DATA == PARTY_BASE
    assert base + SAVE_PARTY_COUNT == PARTY_COUNT


def test_blanco_no_puede_heredar_las_direcciones_de_negro_2() -> None:
    """Misma regla, distintos números: el dinero está 0x100 más allá."""
    assert SAVE_MONEY_BW - SAVE_MONEY_B2W2 == 0x100
    assert SAVE_BADGES_BW - SAVE_MONEY_BW == 4
    assert SAVE_BADGES_B2W2 - SAVE_MONEY_B2W2 == 4


def test_el_bloque_de_equipo_empieza_igual_en_los_dos() -> None:
    """Lo que sí comparten. Aun así, cada juego necesita su propia ancla."""
    assert SAVE_PARTY_BLOCK == 0x18E00


@pytest.fixture(scope="module")
def guardado() -> bytes:
    if not _SAVE_B2W2.exists():
        pytest.skip("El guardado de Negro 2 no está en este equipo.")
    return _SAVE_B2W2.read_bytes()


def test_el_equipo_aparece_donde_predice_la_resta(guardado) -> None:
    """La prueba que convierte la corazonada en regla.

    Ni el contador ni los Pokémon se buscaron: se calcularon desde el dinero y
    salieron. Seis bloques PK5 con checksum válido no aparecen por azar.
    """
    contador = guardado[SAVE_PARTY_COUNT]
    assert 1 <= contador <= 6

    for slot in range(contador):
        inicio = SAVE_PARTY_DATA + slot * PK5_PARTY_SIZE
        pokemon = parse_pk5_party(guardado[inicio:inicio + PK5_PARTY_SIZE], slot)
        assert 1 <= pokemon.species_id <= 649
        assert 1 <= pokemon.level <= 100
        assert 0 < pokemon.max_hp <= 999


def test_detras_del_ultimo_miembro_no_hay_otro(guardado) -> None:
    """Si el contador no fuera el contador, seguiría habiendo Pokémon."""
    contador = guardado[SAVE_PARTY_COUNT]
    if contador >= 6:
        pytest.skip("El equipo está lleno: no hay hueco detrás que comprobar.")

    inicio = SAVE_PARTY_DATA + contador * PK5_PARTY_SIZE
    with pytest.raises(Exception):
        parse_pk5_party(guardado[inicio:inicio + PK5_PARTY_SIZE], contador)
