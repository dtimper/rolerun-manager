"""Lectura de la mochila de B2/W2.

La estructura no se supone: se demostró el 27-08-2026. La traza de dos estados
fijó el bolsillo de medicinas en `0x0221E17C` (Poción 2→3 en esa misma
dirección), el mapa posterior encontró cuatro tiras coherentes por tipo, y las
distancias entre sus inicios —1240, 1572 y 2008— coinciden **byte a byte** con
`SAV5B2W2.Inventory.Pouches` de PKHeX en tres fronteras independientes.

El contenido de estas pruebas es la mochila **real** del usuario en esa traza.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.b2w2_live import (  # noqa: E402
    BAG_BASE,
    BAG_SLOT_SIZE,
    PARTY_COUNT,
    B2W2LiveError,
    bag_pockets,
    bag_size,
    parse_bag,
)

# Exactamente lo que la traza encontró en la partida del usuario.
MOCHILA_REAL = {
    "Items": [(4, 3), (57, 1)],                      # Poke Ball, Ataque X
    "KeyItems": [(621, 1), (437, 1), (442, 1)],      # Videomisor, Bloc, Mapa
    "TMHMs": [(348, 1)],                             # MT21
    "Medicine": [(17, 3), (22, 2)],                  # Pocion, Antiparalizador
    "Berries": [],
}


def _construir(contenido: dict[str, list[tuple[int, int]]]) -> bytes:
    crudo = bytearray(bag_size())
    for pocket in bag_pockets():
        for indice, (item_id, cantidad) in enumerate(contenido.get(pocket.tipo, [])):
            struct.pack_into(
                "<HH", crudo, pocket.offset + indice * BAG_SLOT_SIZE, item_id, cantidad,
            )
    return bytes(crudo)


# --------------------------------------------------------------------------
# El reparto, derivado de los desplazamientos reales
# --------------------------------------------------------------------------

def test_los_bolsillos_estan_donde_se_midieron() -> None:
    """1240, 1572 y 2008 son las distancias medidas en la RAM del usuario."""
    por_tipo = {p.tipo: p.offset for p in bag_pockets()}
    assert por_tipo["Items"] == 0
    assert por_tipo["KeyItems"] == 1240
    assert por_tipo["TMHMs"] == 1572
    assert por_tipo["Medicine"] == 2008
    assert por_tipo["Berries"] == 2200


def test_cada_bolsillo_tiene_sitio_para_sus_objetos_legales() -> None:
    """Si hubiera menos huecos que objetos posibles, el reparto estaría mal."""
    for pocket in bag_pockets():
        assert pocket.slots >= len(pocket.legal), pocket.tipo


def test_la_mochila_cabe_antes_del_equipo() -> None:
    """El equipo está en una dirección ya demostrada: no pueden solaparse."""
    assert BAG_BASE + bag_size() <= PARTY_COUNT


# --------------------------------------------------------------------------
# La mochila real del usuario
# --------------------------------------------------------------------------

def test_se_lee_la_mochila_real_del_usuario() -> None:
    entradas = parse_bag(_construir(MOCHILA_REAL))

    assert len(entradas) == 8
    medicinas = [(e.item_id, e.quantity) for e in entradas if e.pocket == "Medicine"]
    assert medicinas == [(17, 3), (22, 2)]
    assert [(e.item_id, e.quantity) for e in entradas if e.pocket == "TMHMs"] == [(348, 1)]


def test_todos_los_objetos_reales_son_legales_en_su_bolsillo() -> None:
    """Si la lista de PKHeX no cubriera un objeto real, el reader lo rechazaría."""
    por_tipo = {p.tipo: p for p in bag_pockets()}
    for tipo, contenido in MOCHILA_REAL.items():
        for item_id, _cantidad in contenido:
            assert item_id in por_tipo[tipo].legal, (tipo, item_id)


def test_una_mochila_vacia_es_valida() -> None:
    assert parse_bag(_construir({})) == ()


# --------------------------------------------------------------------------
# Lo que se rechaza antes que publicar medio inventario inventado
# --------------------------------------------------------------------------

def test_un_bolsillo_sin_compactar_se_rechaza() -> None:
    """Un hueco vacío delante de uno lleno no es una mochila."""
    crudo = bytearray(_construir(MOCHILA_REAL))
    medicinas = next(p for p in bag_pockets() if p.tipo == "Medicine")
    struct.pack_into("<HH", crudo, medicinas.offset, 0, 0)
    with pytest.raises(B2W2LiveError, match="compactado"):
        parse_bag(bytes(crudo))


def test_un_objeto_ajeno_al_bolsillo_se_rechaza() -> None:
    crudo = bytearray(_construir(MOCHILA_REAL))
    medicinas = next(p for p in bag_pockets() if p.tipo == "Medicine")
    struct.pack_into("<HH", crudo, medicinas.offset, 348, 1)   # una MT en medicinas
    with pytest.raises(B2W2LiveError, match="imposible en el bolsillo"):
        parse_bag(bytes(crudo))


@pytest.mark.parametrize("cantidad", [0, 1000, 65535])
def test_una_cantidad_imposible_se_rechaza(cantidad: int) -> None:
    crudo = bytearray(_construir(MOCHILA_REAL))
    medicinas = next(p for p in bag_pockets() if p.tipo == "Medicine")
    struct.pack_into("<HH", crudo, medicinas.offset, 17, cantidad)
    with pytest.raises(B2W2LiveError):
        parse_bag(bytes(crudo))


def test_un_objeto_repetido_se_rechaza() -> None:
    """El juego agrupa cada objeto en un solo hueco."""
    crudo = bytearray(_construir({**MOCHILA_REAL, "Medicine": [(17, 3), (17, 2)]}))
    with pytest.raises(B2W2LiveError, match="repetido"):
        parse_bag(bytes(crudo))


def test_un_hueco_vacio_con_cantidad_se_rechaza() -> None:
    crudo = bytearray(_construir(MOCHILA_REAL))
    medicinas = next(p for p in bag_pockets() if p.tipo == "Medicine")
    struct.pack_into("<HH", crudo, medicinas.offset + 2 * BAG_SLOT_SIZE, 0, 7)
    with pytest.raises(B2W2LiveError, match="Hueco vacio"):
        parse_bag(bytes(crudo))


def test_un_bloque_de_otro_tamano_se_rechaza() -> None:
    with pytest.raises(B2W2LiveError, match="no mide"):
        parse_bag(b"\x00" * 16)


def test_un_bolsillo_lleno_hasta_el_ultimo_hueco_sigue_siendo_valido() -> None:
    """El compactado no puede confundirse con «no cabe nadie más»."""
    medicinas = next(p for p in bag_pockets() if p.tipo == "Medicine")
    legales = sorted(medicinas.legal)[:medicinas.slots]
    entradas = parse_bag(_construir({"Medicine": [(i, 1) for i in legales]}))
    assert len(entradas) == len(legales)


# --------------------------------------------------------------------------
# El adaptador publica la mochila por el contrato común
# --------------------------------------------------------------------------

def test_el_adaptador_publica_la_mochila_por_el_contrato_comun() -> None:
    """Es la vía por la que la interfaz y las MT leerán el inventario."""
    from types import SimpleNamespace

    from app.b2w2_live import BAG_BASE, B2W2BagEntry, B2W2BagRead
    from app.realtime.b2w2_adapter import B2W2RealTimeAdapter

    entradas = (
        B2W2BagEntry("Medicine", 0, 17, 3),
        B2W2BagEntry("TMHMs", 0, 348, 1),
    )
    lector = SimpleNamespace(
        read_party=lambda: SimpleNamespace(process_id=42, process_name="melonDS.exe"),
        read_bag=lambda party: B2W2BagRead(
            42, "melonDS.exe", 0x1000, BAG_BASE, b"", entradas,
        ),
    )

    inventario, proceso, base = B2W2RealTimeAdapter(reader=lector).read_tm_inventory()

    assert inventario == {17: 3, 348: 1}
    assert base == BAG_BASE
    assert proceso.process_id == 42


def test_un_testigo_del_guardado_no_sustituye_a_la_ram() -> None:
    """Coger o gastar un objeto hace que difieran: manda siempre la RAM."""
    from types import SimpleNamespace

    from app.b2w2_live import BAG_BASE, B2W2BagEntry, B2W2BagRead
    from app.realtime.b2w2_adapter import B2W2RealTimeAdapter

    lector = SimpleNamespace(
        read_party=lambda: SimpleNamespace(process_id=1, process_name="melonDS.exe"),
        read_bag=lambda party: B2W2BagRead(
            1, "melonDS.exe", 0x1000, BAG_BASE, b"", (B2W2BagEntry("Medicine", 0, 17, 3),),
        ),
    )

    inventario, _proceso, _base = B2W2RealTimeAdapter(reader=lector).read_tm_inventory(
        {17: 99, 4: 5},
    )

    assert inventario == {17: 3}
