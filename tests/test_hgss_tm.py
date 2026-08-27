"""La tabla de MT de HeartGold.

CÓMO SE LOCALIZÓ, EL 28-08-2026

Las 92 MT son idénticas en toda la cuarta generación, así que su lista salió del
binario de las ROM de **Perla y Platino** del usuario —las dos dan exactamente la
misma, en `0x0F84EC` y `0x0F0C90`—. Esa firma de 92 movimientos se buscó en los
4 MiB de RAM del DS con HeartGold cargado: **aparece una sola vez**.

Y se valida sola. La MO05 que hay en esa dirección es **Torbellino**, no
Despejar: justo la diferencia conocida entre HeartGold y Platino. Lo encontrado
no es una copia de la referencia, es la tabla propia del juego. Las dos MT que el
usuario tenía en la mochila —MT51 y MT70— salieron Respiro y Destello.

El arm9 de HeartGold va comprimido, por eso no se pudo leer del archivo como en
Perla y Platino y hubo que buscarla en memoria.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.gen4_memory import GEN4_MEMORY  # noqa: E402
from app.hgss_live import TM_TABLE_COUNT  # noqa: E402
from app.hgss_tm_service import (  # noqa: E402
    TM_TABLE_ITEM_IDS,
    TM_TABLE_SLOTS,
    HgssTMError,
    build_tm_profile,
    reference_move_ids,
)


def test_la_tabla_tiene_92_mt_y_8_mo() -> None:
    assert TM_TABLE_COUNT == 100
    assert sum(1 for tipo, _n in TM_TABLE_SLOTS if tipo == "TM") == 92
    assert sum(1 for tipo, _n in TM_TABLE_SLOTS if tipo == "HM") == 8


def test_los_objetos_van_en_dos_tramos_seguidos() -> None:
    # MT01 es el objeto 328 y MO01 el 420 en cualquier juego de cuarta.
    assert TM_TABLE_ITEM_IDS[0] == 328
    assert TM_TABLE_ITEM_IDS[91] == 419
    assert TM_TABLE_ITEM_IDS[92] == 420
    assert TM_TABLE_ITEM_IDS[99] == 427
    assert list(TM_TABLE_ITEM_IDS) == sorted(TM_TABLE_ITEM_IDS)


def test_la_referencia_es_la_lista_de_cuarta() -> None:
    referencia = reference_move_ids()
    assert len(referencia) == TM_TABLE_COUNT
    assert referencia[0] == 264      # MT01 Puño Certero
    assert referencia[1] == 337      # MT02 Garra Dragón
    assert referencia[91] == 433     # MT92 Espacio Raro
    assert referencia[92] == 15      # MO01 Corte
    # La MO05 de Diamante, Perla y Platino es Despejar; HeartGold trae otra.
    assert referencia[96] == 432


def test_el_perfil_publica_las_mt_y_no_las_mo() -> None:
    perfil = build_tm_profile(reference_move_ids(), source="prueba")
    assert len(perfil.tms) == 92
    assert perfil.tm(1).move_id == 264
    assert perfil.tm(1).item_id == 328
    assert perfil.tm(1).label == "MT01"
    assert perfil.tm(92) is not None
    # Una MO aparecería con un número que no es el suyo.
    assert perfil.tm(93) is None


def test_el_perfil_dice_que_la_mt_se_gasta() -> None:
    """Es la diferencia gorda con quinta, y quien escriba tiene que saberlo."""
    assert build_tm_profile(reference_move_ids(), source="prueba").consumes_item


def test_se_busca_la_mt_por_su_objeto() -> None:
    perfil = build_tm_profile(reference_move_ids(), source="prueba")
    assert perfil.tm_for_item(378).number == 51
    assert perfil.tm_for_item(60000) is None


def test_una_tabla_de_otro_tamano_se_rechaza() -> None:
    with pytest.raises(HgssTMError, match="entradas"):
        build_tm_profile([1, 2, 3], source="prueba")


def test_una_tabla_con_un_hueco_vacio_se_rechaza() -> None:
    rota = list(reference_move_ids())
    rota[7] = 0
    with pytest.raises(HgssTMError, match="vacío"):
        build_tm_profile(rota, source="prueba")


def test_sin_rom_no_se_inventa_la_categoria() -> None:
    # En una partida randomizada el catálogo estático podría mentir.
    perfil = build_tm_profile(reference_move_ids(), source="prueba")
    assert perfil.damage_class(264) == "unknown"
    # Los PP sí salen de la tabla de cuarta de PKHeX.
    assert perfil.base_pp(264) == 20      # Puño Certero


def test_la_direccion_de_la_tabla_esta_declarada() -> None:
    assert GEN4_MEMORY["hgss"].tm_table == 0x021000B4
