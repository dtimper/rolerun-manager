"""Las direcciones de cuarta generación salen de un ancla, no de seis medidas.

Medido sobre HeartGold el 27-08-2026 con melonDS abierto: partiendo solo de la
dirección del equipo, las que predice la resta trajeron el dinero que el jugador
llevaba encima, su contador de equipo y el primer Pokémon de la caja 1. Y el
tramo que arranca en el principio del bloque coincidió al **98,65 %** con el
archivo de la partida —lo que no coincidía era justo lo que el jugador había
avanzado desde el último guardado—.

Estas pruebas fijan esa derivación para que nadie la rompa metiendo una
dirección suelta.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.gen4_memory import (  # noqa: E402
    GEN4_MEMORY,
    SAVE_BADGES,
    SAVE_MONEY,
    SAVE_MONEY_SIZE,
    SAVE_PARTY_COUNT,
    SAVE_PARTY_DATA,
    SAVE_PC,
    Gen4Memory,
)

HGSS = GEN4_MEMORY["hgss"]


def test_el_ancla_de_heartgold_es_la_medida() -> None:
    # Cambiar este número exige volver a medirlo contra el juego.
    assert HGSS.party_data == 0x0227C304


def test_el_principio_del_bloque_sale_de_restar_el_desplazamiento() -> None:
    assert HGSS.block_base == 0x0227C304 - SAVE_PARTY_DATA
    assert HGSS.block_base == 0x0227C26C


@pytest.mark.parametrize(
    ("campo", "desplazamiento"),
    [
        ("party_count", SAVE_PARTY_COUNT),
        ("pc", SAVE_PC),
        ("money", SAVE_MONEY),
        ("badges", SAVE_BADGES),
    ],
)
def test_cada_campo_es_el_principio_del_bloque_mas_su_desplazamiento(
    campo: str, desplazamiento: int,
) -> None:
    assert getattr(HGSS, campo) == HGSS.block_base + desplazamiento


def test_las_direcciones_derivadas_son_las_que_se_comprobaron_en_vivo() -> None:
    assert HGSS.party_count == 0x0227C300
    assert HGSS.money == 0x0227C2E4
    assert HGSS.badges == 0x0227C2EA
    assert HGSS.pc == 0x0228B96C


def test_el_dinero_ocupa_tres_bytes_y_no_cuatro() -> None:
    # Escribir el cuarto pisaría algo que no es dinero. Ya pasó en quinta.
    assert SAVE_MONEY_SIZE == 3


def test_el_contador_va_justo_delante_de_los_datos_del_equipo() -> None:
    # Lo confirmó la búsqueda: en el sitio donde aparecieron los PID del equipo,
    # los cuatro bytes anteriores traían el número de miembros.
    assert SAVE_PARTY_DATA - SAVE_PARTY_COUNT == 4


def test_el_pc_esta_dentro_del_mismo_bloque_que_el_equipo() -> None:
    # Si el PC viviera en otro bloque, la resta no valdría para llegar a él.
    assert SAVE_PC > SAVE_PARTY_DATA
    assert HGSS.pc - HGSS.party_data == SAVE_PC - SAVE_PARTY_DATA


def test_otra_ancla_arrastra_a_todas_las_derivadas() -> None:
    otro = Gen4Memory(key="prueba", label="Prueba", party_data=0x02000098)
    assert otro.block_base == 0x02000000
    assert otro.party_count == 0x02000000 + SAVE_PARTY_COUNT
    assert otro.money == 0x02000000 + SAVE_MONEY
    assert otro.badges == 0x02000000 + SAVE_BADGES
    assert otro.pc == 0x02000000 + SAVE_PC


def test_los_desplazamientos_se_pueden_cambiar_por_juego() -> None:
    # Diamante/Perla y Platino colocan sus bloques en otro sitio; el descriptor
    # tiene que dejar declararlo en vez de heredar los de HGSS.
    otro = Gen4Memory(
        key="inventado", label="Inventado",
        party_data=0x02000100, save_money=0x10, save_pc=0x2000,
    )
    assert otro.block_base == 0x02000100 - SAVE_PARTY_DATA
    assert otro.money == otro.block_base + 0x10
    assert otro.pc == otro.block_base + 0x2000


def test_solo_esta_declarado_el_juego_que_se_ha_medido() -> None:
    # Diamante/Perla y Platino todavía no tienen ancla. Declararlos aquí sin
    # medirlos sería inventarse una dirección.
    assert set(GEN4_MEMORY) == {"hgss"}


def test_el_descriptor_es_inmutable() -> None:
    with pytest.raises(Exception):
        HGSS.party_data = 0
