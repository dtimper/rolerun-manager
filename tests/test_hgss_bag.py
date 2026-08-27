"""La mochila y el dinero de HeartGold.

Los desplazamientos se sondearon en PKHeX tocando un hueco de cada bolsillo y
mirando qué bytes se movían, y después se comprobaron **contra el juego vivo**:
las Pociones, las Poké Balls y las dos MT del usuario aparecieron en el bolsillo
que les toca.

El reparto de objetos tampoco se supone por analogía con quinta: PKHeX dice que
el Repelente Máximo vive en OBJETOS y el Caramelo Raro en MEDICINAS. Meterlos en
el bolsillo equivocado los dejaría invisibles dentro del juego.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.gen4_memory import BAG_MAX_COUNT, GEN4_MEMORY, MONEY_MAX  # noqa: E402
from app.hgss_live import (  # noqa: E402
    HgssLiveError,
    bag_pocket_for,
    bag_pockets,
    parse_bag_pocket,
    set_bag_quantity,
)

HGSS = GEN4_MEMORY["hgss"]
MEDICINAS = next(p for p in bag_pockets(HGSS) if p.key == "medicine")


def _bolsillo(*pares) -> bytes:
    crudo = bytearray(MEDICINAS.slots * 4)
    for indice, (item_id, cantidad) in enumerate(pares):
        struct.pack_into("<2H", crudo, indice * 4, item_id, cantidad)
    return bytes(crudo)


# --------------------------------------------------------------------------
# El reparto
# --------------------------------------------------------------------------

def test_los_ocho_bolsillos_estan_y_no_se_solapan() -> None:
    bolsillos = bag_pockets(HGSS)
    assert len(bolsillos) == 8
    ordenados = sorted(bolsillos, key=lambda p: p.address)
    for antes, despues in zip(ordenados, ordenados[1:]):
        assert antes.address + antes.slots * 4 <= despues.address, (
            f"{antes.key} se mete dentro de {despues.key}"
        )


def test_cada_utilidad_de_la_cabecera_va_a_su_bolsillo() -> None:
    # Comprobado contra PKHeX, no supuesto: en el bolsillo equivocado el juego
    # no los enseñaría.
    assert bag_pocket_for(HGSS, 50).key == "medicine"      # Caramelo Raro
    assert bag_pocket_for(HGSS, 77).key == "items"         # Repelente Máximo
    # Y los que el propio juego tenía guardados en la partida del usuario.
    assert bag_pocket_for(HGSS, 17).key == "medicine"      # Poción
    assert bag_pocket_for(HGSS, 4).key == "balls"          # Poké Ball


def test_un_objeto_que_no_existe_no_tiene_bolsillo() -> None:
    with pytest.raises(HgssLiveError, match="no pertenece"):
        bag_pocket_for(HGSS, 60000)


def test_las_mt_tienen_su_propio_tope() -> None:
    tmhm = next(p for p in bag_pockets(HGSS) if p.key == "tmhm")
    assert tmhm.max_count == 99
    assert MEDICINAS.max_count == BAG_MAX_COUNT == 999


# --------------------------------------------------------------------------
# Lectura de un bolsillo
# --------------------------------------------------------------------------

def test_se_leen_los_objetos_en_orden() -> None:
    assert parse_bag_pocket(_bolsillo((17, 3), (18, 1)), MEDICINAS) == {17: 3, 18: 1}


def test_un_bolsillo_vacio_no_trae_nada() -> None:
    assert parse_bag_pocket(_bolsillo(), MEDICINAS) == {}


def test_un_hueco_vacio_por_medio_invalida_el_bolsillo() -> None:
    # El juego mantiene la lista compacta; un agujero significa que lo leído no
    # es una mochila.
    crudo = bytearray(_bolsillo((17, 3), (18, 1)))
    struct.pack_into("<2H", crudo, 0, 0, 0)
    with pytest.raises(HgssLiveError, match="hueco vacío"):
        parse_bag_pocket(bytes(crudo), MEDICINAS)


def test_un_objeto_repetido_invalida_el_bolsillo() -> None:
    with pytest.raises(HgssLiveError, match="repite"):
        parse_bag_pocket(_bolsillo((17, 3), (17, 1)), MEDICINAS)


def test_una_cantidad_imposible_invalida_el_bolsillo() -> None:
    with pytest.raises(HgssLiveError, match="tope"):
        parse_bag_pocket(_bolsillo((17, 5000)), MEDICINAS)


def test_un_bolsillo_de_otro_tamano_se_rechaza() -> None:
    with pytest.raises(HgssLiveError, match="otro tamaño"):
        parse_bag_pocket(b"\x00" * 8, MEDICINAS)


# --------------------------------------------------------------------------
# Escritura de un bolsillo
# --------------------------------------------------------------------------

def test_subir_una_cantidad_no_mueve_a_los_demas() -> None:
    antes = _bolsillo((17, 3), (18, 1), (22, 1))
    despues = set_bag_quantity(antes, MEDICINAS, 18, 999)
    assert parse_bag_pocket(despues, MEDICINAS) == {17: 3, 18: 999, 22: 1}


def test_un_objeto_nuevo_se_anade_al_final() -> None:
    antes = _bolsillo((17, 3))
    despues = set_bag_quantity(antes, MEDICINAS, 50, 999)
    assert parse_bag_pocket(despues, MEDICINAS) == {17: 3, 50: 999}


def test_poner_cero_borra_el_objeto_y_compacta() -> None:
    antes = _bolsillo((17, 3), (18, 1), (22, 1))
    despues = set_bag_quantity(antes, MEDICINAS, 18, 0)
    assert parse_bag_pocket(despues, MEDICINAS) == {17: 3, 22: 1}
    # Y de verdad quedan seguidos, sin agujero por medio.
    assert struct.unpack_from("<2H", despues, 4) == (22, 1)


def test_no_se_mete_un_objeto_en_el_bolsillo_equivocado() -> None:
    with pytest.raises(HgssLiveError, match="no cabe"):
        set_bag_quantity(_bolsillo(), MEDICINAS, 77, 999)


def test_no_se_pasa_del_tope_del_bolsillo() -> None:
    with pytest.raises(HgssLiveError, match="máximo"):
        set_bag_quantity(_bolsillo(), MEDICINAS, 50, 1000)


# --------------------------------------------------------------------------
# Dinero
# --------------------------------------------------------------------------

def test_el_dinero_tiene_el_tope_que_declara_el_juego() -> None:
    assert MONEY_MAX == 999999


def test_las_utilidades_comprueban_el_nombre_antes_de_escribir() -> None:
    """En BDSP una utilidad rotulada «Repelente Máximo» tocó el Repelente normal.

    Por eso el identificador no basta: el nombre que trae el cambio tiene que
    ser el del objeto que se va a escribir.
    """
    from app.models import PendingInventoryChange
    from app.realtime.hgss_adapter import HgssRealTimeAdapter

    bueno = PendingInventoryChange(
        item_key="rare-candy", item_name="Caramelo Raro", quantity=999,
    )
    assert HgssRealTimeAdapter._utility_item_for(bueno) == 50

    mentiroso = PendingInventoryChange(
        item_key="rare-candy", item_name="Repelente Máximo", quantity=999,
    )
    with pytest.raises(HgssLiveError, match="dice ser"):
        HgssRealTimeAdapter._utility_item_for(mentiroso)

    desconocida = PendingInventoryChange(
        item_key="inventada", item_name="Nada", quantity=1,
    )
    with pytest.raises(HgssLiveError, match="no tiene objeto demostrado"):
        HgssRealTimeAdapter._utility_item_for(desconocida)
