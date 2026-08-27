"""Las direcciones de Blanco/Negro, derivadas de un solo ancla.

CÓMO SE DEMOSTRÓ EL ANCLA (27-08-2026)

`buscar_ancla_blanco.bat` recorrió la RAM de melonDS buscando bloques PK5 de
party creíbles —checksum válido, especie, nivel y PS posibles—. En
`0x02234974` aparecieron **cuatro seguidos separados exactamente 220 bytes**,
que es el equipo de cuatro que el usuario declaró.

Y una segunda confirmación independiente de la primera: en la dirección que
predice la resta del guardado, el dinero leído era **1624**, exactamente el que
el usuario había apuntado antes de empezar. De los diez candidatos del volcado,
solo ese predijo el dinero correcto.

LO QUE ESTAS PRUEBAS PROTEGEN

Que nadie herede una dirección de Negro 2 por parecido. Los dos juegos usan la
misma regla y números distintos.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.b2w2_live import (  # noqa: E402
    BAG_BASE,
    BADGES_ADDRESS,
    MONEY_ADDRESS,
    PARTY_BASE,
    PARTY_COUNT,
    PC_BASE,
    PK5_PARTY_SIZE,
)
from app.gen5_memory import GEN5_MEMORY, SAVE_PARTY_DATA  # noqa: E402

B2W2 = GEN5_MEMORY["b2w2"]
BW = GEN5_MEMORY["bw"]


# --------------------------------------------------------------------------
# La regla, contrastada contra las direcciones ya demostradas de Negro 2
# --------------------------------------------------------------------------

def test_la_regla_reproduce_todas_las_direcciones_de_negro_2() -> None:
    """Cada una se demostró por separado antes de conocerse la regla.

    Que todas encajen después no es una comprobación circular: es la prueba de
    que el bloque vivo es un espejo del guardado.
    """
    assert B2W2.party_data == PARTY_BASE
    assert B2W2.party_count == PARTY_COUNT
    assert B2W2.pc == PC_BASE
    assert B2W2.bag == BAG_BASE
    assert B2W2.money == MONEY_ADDRESS
    assert B2W2.badges == BADGES_ADDRESS


def test_el_contador_va_cuatro_bytes_antes_del_equipo() -> None:
    """La herramienta de captura leía -8 y daba el byte de cabecera."""
    assert B2W2.party_data - B2W2.party_count == 4
    assert BW.party_data - BW.party_count == 4


# --------------------------------------------------------------------------
# El ancla de Blanco
# --------------------------------------------------------------------------

def test_el_ancla_de_blanco_es_la_medida() -> None:
    assert BW.party_data == 0x02234974


def test_blanco_no_hereda_ninguna_direccion_de_negro_2() -> None:
    """Misma regla, números distintos. Copiar una habría leído basura."""
    assert BW.party_data != B2W2.party_data
    assert BW.money != B2W2.money
    assert BW.badges != B2W2.badges
    assert BW.pc != B2W2.pc
    assert BW.bag != B2W2.bag


def test_el_dinero_de_blanco_esta_donde_dice_pkhex() -> None:
    """0x21200 en el guardado, no 0x21100 como su segunda parte."""
    assert BW.save_money == 0x21200
    assert BW.save_badges == BW.save_money + 4
    assert BW.money == 0x0223CD6C


def test_las_direcciones_derivadas_de_blanco() -> None:
    assert BW.block_base == 0x0221BB6C
    assert BW.party_count == 0x02234970
    assert BW.pc == 0x0221BF6C
    assert BW.bag == 0x02233F6C
    assert BW.badges == 0x0223CD70


def test_lo_que_todavia_no_se_ha_demostrado_de_blanco() -> None:
    """No están en el bloque del guardado, así que no salen de la resta.

    Declararlas a ojo sería inventarlas. Mientras valgan None, el backend sabe
    que esas capacidades no están disponibles todavía.
    """
    assert BW.tm_table is None
    assert BW.battle_presentation is None
    assert BW.battle_logical is None
    assert B2W2.tm_table is not None, "Negro 2 sí las tiene demostradas"


# --------------------------------------------------------------------------
# La captura, anclada al archivo real
# --------------------------------------------------------------------------

CAPTURA = Path(__file__).resolve().parent.parent / "diagnostics" / "manual" / (
    "bw_anchor_latest.json"
)


@pytest.fixture(scope="module")
def captura():
    import json

    if not CAPTURA.exists():
        pytest.skip("No hay captura del ancla de Blanco en este equipo.")
    return json.loads(CAPTURA.read_text(encoding="utf-8"))


def test_la_captura_encontro_el_equipo_declarado(captura) -> None:
    """Cuatro PK5 seguidos separados 220 bytes, y el usuario declaró cuatro."""
    declarado = int(captura["declarado"]["equipo"])
    direcciones = [int(c["direccion"], 16) for c in captura["candidatos"][:declarado]]

    assert direcciones[0] == BW.party_data
    assert all(b - a == PK5_PARTY_SIZE for a, b in zip(direcciones, direcciones[1:]))


def test_solo_ese_candidato_predijo_el_dinero(captura) -> None:
    """La segunda confirmación, independiente de la forma del bloque."""
    dinero = captura["declarado"]["dinero"]
    aciertan = [
        c for c in captura["candidatos"]
        if c.get("prediccion", {}).get("dinero", {}).get("valor") == dinero
    ]

    assert len(aciertan) == 1
    assert int(aciertan[0]["direccion"], 16) == BW.party_data
