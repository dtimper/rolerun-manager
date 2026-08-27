"""El perfil de MT de B2/W2, leído del juego que hay delante.

RoleRun se juega en randomizers, así que qué enseña cada MT se lee de la RAM y
no de una tabla guardada. La dirección quedó demostrada el 27-08-2026: en los
4 MiB hay **un solo** tramo con la forma de una tabla de MT —101 movimientos de
16 bits seguidos, todos válidos y todos distintos— y, indexado por objeto,
coincide 101 de 101 con la lista derivada de PKHeX.

La captura reveló además algo que se había asumido mal: el juego guarda la lista
en **orden de objeto** (MT01–92, MO01–06, MT93–95), no en orden de número de MT.

Lo que sí es fijo, randomizada la partida o no, es qué objeto es cada MT.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.b2w2_live import (  # noqa: E402
    MOVE_ID_MAX,
    TM_TABLE_BASE,
    TM_TABLE_COUNT,
    B2W2LiveError,
    B2W2MelonDSReader,
)
from app.b2w2_tm_service import (  # noqa: E402
    TM_TABLE_ITEM_IDS,
    TM_TABLE_SLOTS,
    B2W2TMError,
    build_tm_profile,
    reference_move_ids,
)


@pytest.fixture(scope="module")
def referencia():
    return reference_move_ids()


@pytest.fixture(scope="module")
def perfil(referencia):
    return build_tm_profile(referencia, source="referencia")


# --------------------------------------------------------------------------
# El orden que reveló la captura
# --------------------------------------------------------------------------

def test_la_tabla_va_en_orden_de_objeto() -> None:
    """MT01-92 (328-419), MO01-06 (420-425) y MT93-95 (618-620), seguidos."""
    assert len(TM_TABLE_ITEM_IDS) == TM_TABLE_COUNT
    assert TM_TABLE_ITEM_IDS[0] == 328
    assert TM_TABLE_ITEM_IDS[91] == 419      # MT92, fin del primer tramo
    assert TM_TABLE_ITEM_IDS[92] == 420      # MO01 va AQUÍ, no detrás de MT95
    assert TM_TABLE_ITEM_IDS[97] == 425      # MO06
    assert TM_TABLE_ITEM_IDS[98] == 618      # MT93
    assert TM_TABLE_ITEM_IDS[100] == 620     # MT95


def test_cada_posicion_sabe_si_es_mt_o_mo() -> None:
    assert TM_TABLE_SLOTS[0] == ("TM", 1)
    assert TM_TABLE_SLOTS[92] == ("HM", 1)
    assert TM_TABLE_SLOTS[98] == ("TM", 93)
    assert sum(1 for tipo, _ in TM_TABLE_SLOTS if tipo == "TM") == 95
    assert sum(1 for tipo, _ in TM_TABLE_SLOTS if tipo == "HM") == 6


def test_los_objetos_no_se_repiten() -> None:
    assert len(set(TM_TABLE_ITEM_IDS)) == TM_TABLE_COUNT


def test_todos_los_objetos_caen_en_el_bolsillo_de_mt() -> None:
    """Si uno no fuera legal ahí, la mochila viva lo rechazaría."""
    from app.b2w2_live import bag_pocket_for

    for item_id in TM_TABLE_ITEM_IDS:
        assert bag_pocket_for(item_id).tipo == "TMHMs", item_id


def test_el_objeto_de_cada_posicion_es_el_que_dice_pkhex() -> None:
    """La misma tabla de objetos que ya leyó su mochila real (MT21 = 348)."""
    from app.boxed_metadata import item_name

    for item_id, (tipo, numero) in zip(TM_TABLE_ITEM_IDS, TM_TABLE_SLOTS):
        esperado = f"{'MT' if tipo == 'TM' else 'MO'}{numero:02d}"
        assert item_name(item_id) == esperado, item_id


# --------------------------------------------------------------------------
# El perfil que se publica
# --------------------------------------------------------------------------

def test_se_publican_las_noventa_y_cinco_mt(perfil) -> None:
    assert sorted(perfil.tms) == list(range(1, 96))


def test_las_mo_se_leen_pero_no_se_publican(perfil) -> None:
    """La interfaz rotula todo como MT: una MO saldría con un número ajeno."""
    for item_id in range(420, 426):
        assert perfil.tm_for_item(item_id) is None


def test_la_mt_que_el_usuario_tiene_en_su_partida(perfil) -> None:
    """Objeto 348 en su mochila real; sin randomizar, es Frustración."""
    mt21 = perfil.tm(21)
    assert (mt21.item_id, mt21.move_id, mt21.label) == (348, 218, "MT21")


def test_las_tres_ultimas_mt_saltan_de_objeto(perfil) -> None:
    assert perfil.tm(92).item_id == 419
    assert perfil.tm(93).item_id == 618
    assert perfil.tm(95).item_id == 620


def test_cada_mt_se_puede_buscar_por_su_objeto(perfil) -> None:
    """Es la vía por la que la mochila viva se cruza con la tabla."""
    for tm in perfil.tms.values():
        assert perfil.tm_for_item(tm.item_id) is tm
    assert perfil.tm_for_item(17) is None      # Poción no es una MT


def test_una_tabla_randomizada_produce_un_perfil_distinto(referencia) -> None:
    """Es el caso que motiva leer de la RAM en vez de servir un archivo."""
    randomizada = list(reversed(referencia))

    otro = build_tm_profile(randomizada, source="randomizada")

    assert otro.tm(21).item_id == 348, "el objeto de la MT21 no cambia"
    assert otro.tm(21).move_id != 218, "lo que enseña sí"


# --------------------------------------------------------------------------
# Lo que se rechaza antes que publicar medio perfil
# --------------------------------------------------------------------------

def test_una_tabla_de_otro_tamano_se_rechaza(referencia) -> None:
    with pytest.raises(B2W2TMError, match="entradas"):
        build_tm_profile(referencia[:-1], source="corta")


def test_dos_mt_que_ensenan_lo_mismo_se_rechazan(referencia) -> None:
    roto = list(referencia)
    roto[40] = roto[7]

    with pytest.raises(B2W2TMError, match="mismo movimiento"):
        build_tm_profile(roto, source="rota")


def test_un_movimiento_sin_pp_en_quinta_se_rechaza(referencia) -> None:
    """Sin PP no se podría curar ni verificar la enseñanza."""
    roto = list(referencia)
    roto[0] = MOVE_ID_MAX + 1000

    with pytest.raises(B2W2TMError, match="sin PP"):
        build_tm_profile(roto, source="rota")


def test_todas_las_mt_tienen_pp(perfil) -> None:
    for tm in perfil.tms.values():
        assert perfil.base_pp(tm.move_id) > 0, tm.label


@pytest.mark.parametrize(
    ("movimiento", "pp"),
    [(218, 20), (89, 10), (57, 15), (15, 30)],   # Frustración, Terremoto, Surf, Corte
)
def test_los_pp_son_los_de_la_tabla_ya_extraida(perfil, movimiento, pp) -> None:
    assert perfil.base_pp(movimiento) == pp


# --------------------------------------------------------------------------
# La lectura viva
# --------------------------------------------------------------------------

def _lector(movimientos) -> B2W2MelonDSReader:
    """Lector real con la lectura de memoria sustituida por una tabla dada."""
    crudo = struct.pack(f"<{len(movimientos)}H", *movimientos)
    pedidos: list[tuple[int, int]] = []

    lector = B2W2MelonDSReader()
    lector.read_party = lambda: object()
    lector._read_guest_twice = lambda lectura, guest, tamano: (
        pedidos.append((guest, tamano)) or crudo[:tamano]
    )
    lector.pedidos = pedidos
    return lector


def test_la_direccion_es_la_que_demostro_la_captura() -> None:
    """Único tramo con esa forma en 4 MiB, y 101/101 contra PKHeX."""
    assert TM_TABLE_BASE == 0x02090C54


def test_se_lee_la_tabla_de_la_direccion_demostrada(referencia) -> None:
    lector = _lector(referencia)

    assert lector.read_tm_table() == tuple(referencia)
    assert lector.pedidos == [(TM_TABLE_BASE, TM_TABLE_COUNT * 2)]


def test_un_movimiento_imposible_no_se_publica(referencia) -> None:
    roto = list(referencia)
    roto[10] = MOVE_ID_MAX + 1

    with pytest.raises(B2W2LiveError, match="no es un movimiento de quinta"):
        _lector(roto).read_tm_table()


def test_un_cero_tampoco_es_una_tabla(referencia) -> None:
    roto = list(referencia)
    roto[10] = 0

    with pytest.raises(B2W2LiveError, match="no es un movimiento de quinta"):
        _lector(roto).read_tm_table()


def test_un_movimiento_repetido_no_se_publica(referencia) -> None:
    roto = list(referencia)
    roto[10] = roto[11]

    with pytest.raises(B2W2LiveError, match="repite"):
        _lector(roto).read_tm_table()


def test_el_adaptador_publica_el_perfil_de_la_partida_viva(referencia) -> None:
    from app.realtime.b2w2_adapter import B2W2RealTimeAdapter

    adaptador = B2W2RealTimeAdapter(reader=_lector(referencia))

    publicado = adaptador.read_tm_profile()

    assert len(publicado.tms) == 95
    assert publicado.tm(21).move_id == 218
    assert "0x02090C54" in publicado.source


# --------------------------------------------------------------------------
# La referencia de PKHeX, degradada a referencia
# --------------------------------------------------------------------------

def test_la_referencia_viene_en_orden_de_objeto(referencia) -> None:
    assert len(referencia) == TM_TABLE_COUNT
    assert referencia[92] == 15, "posición 92 = MO01 = Corte"
    assert referencia[98] == 528, "posición 98 = MT93 = Voltio Cruel"


def test_sin_el_archivo_de_referencia_se_dice_cual_falta(tmp_path, monkeypatch) -> None:
    import app.b2w2_tm_service as servicio

    monkeypatch.setattr(servicio, "_REFERENCE_PATH", tmp_path / "no_existe.json")
    servicio.reference_move_ids.cache_clear()
    try:
        with pytest.raises(B2W2TMError, match="b2w2_tm_table.json"):
            servicio.reference_move_ids()
    finally:
        servicio.reference_move_ids.cache_clear()


# --------------------------------------------------------------------------
# La captura física del usuario, que es lo que demostró la dirección
# --------------------------------------------------------------------------

CAPTURA = Path(__file__).resolve().parent.parent / "diagnostics" / "manual" / (
    "b2w2_tm_table_latest.json"
)


@pytest.fixture(scope="module")
def captura():
    import json

    if not CAPTURA.exists():
        pytest.skip("No hay captura de la tabla de MT en este equipo.")
    return json.loads(CAPTURA.read_text(encoding="utf-8"))


def test_la_captura_encontro_un_solo_tramo_con_esa_forma(captura) -> None:
    """En 4 MiB, un único sitio parece una tabla de MT."""
    assert len(captura["candidatos"]) == 1


def test_el_unico_tramo_esta_donde_lo_lee_produccion(captura) -> None:
    assert captura["candidatos"][0]["direccion"] == f"0x{TM_TABLE_BASE:08X}"


def test_la_captura_coincide_con_pkhex_en_las_ciento_una(captura, referencia) -> None:
    """La segunda prueba, independiente de la forma.

    La captura original se comparó en orden de número de MT y dio 92/101; los
    9 que «fallaban» eran los mismos movimientos colocados en orden de objeto,
    que es como el juego los guarda. Indexada bien, no falla ninguna.
    """
    leidos = captura["candidatos"][0]["movimientos"]

    assert leidos == list(referencia)


def test_el_perfil_de_la_captura_es_el_que_ve_el_usuario(captura) -> None:
    """Su partida no está randomizada: la MT21 tiene que ser Frustración."""
    publicado = build_tm_profile(
        captura["candidatos"][0]["movimientos"], source="captura",
    )

    assert len(publicado.tms) == 95
    assert publicado.tm(21).move_id == 218
    assert publicado.tm(1).move_id == 468       # MT01 = Afilagarras
