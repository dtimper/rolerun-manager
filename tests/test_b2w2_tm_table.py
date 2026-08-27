"""La tabla de MT/MO de B2/W2.

No está copiada a mano. `tools_extract_gen5_tm` la deriva de la propia lógica
de PKHeX: enciende un solo bit de MT en una ficha personal en blanco y pregunta
qué movimiento queda enseñable.

Lo que estas pruebas contrastan son **hechos independientes de la extracción**:
la MT que el usuario tiene realmente en su partida, las seis MO de B2/W2 (con
Buceo como MO06, que es lo que distingue B2/W2 de Negro/Blanco) y los objetos
de la misma tabla de PKHeX que ya validó físicamente su mochila.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.b2w2_tm_service import (  # noqa: E402
    B2W2TMError,
    load_b2w2_tm_profile,
)

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def perfil():
    return load_b2w2_tm_profile()


# --------------------------------------------------------------------------
# Contraste con hechos que no dependen de la extracción
# --------------------------------------------------------------------------

def test_la_mt_que_el_usuario_tiene_en_su_partida(perfil) -> None:
    """MT21 = objeto 348 en su mochila real; en quinta generación es Frustración."""
    mt21 = perfil.tm(21)
    assert mt21 is not None
    assert (mt21.item_id, mt21.move_id, mt21.label) == (348, 218, "TM21")


@pytest.mark.parametrize(
    ("numero", "etiqueta", "item", "movimiento"),
    [
        (96, "HM01", 420, 15),    # Corte
        (97, "HM02", 421, 19),    # Vuelo
        (98, "HM03", 422, 57),    # Surf
        (99, "HM04", 423, 70),    # Fuerza
        (100, "HM05", 424, 127),  # Cascada
        (101, "HM06", 425, 291),  # Buceo: MO06 solo en B2/W2, no en Negro/Blanco
    ],
)
def test_las_seis_mo_son_las_de_b2w2(perfil, numero, etiqueta, item, movimiento) -> None:
    mo = perfil.tm(numero)
    assert mo is not None
    assert (mo.label, mo.item_id, mo.move_id, mo.kind) == (etiqueta, item, movimiento, "HM")


@pytest.mark.parametrize(
    ("numero", "item", "movimiento"),
    [
        (1, 328, 468),    # Afilagarras
        (2, 329, 337),    # Garra Dragón
        (26, 353, 89),    # Terremoto
        (92, 419, 433),   # Espacio Raro: fin del tramo contiguo de objetos
        (93, 618, 528),   # Voltio Cruel: las tres últimas MT saltan a 618-620
        (95, 620, 555),   # Alarido
    ],
)
def test_los_tramos_de_objeto_son_los_de_quinta(perfil, numero, item, movimiento) -> None:
    """MT01-92 = 328..419, MO01-06 = 420..425, MT93-95 = 618..620."""
    tm = perfil.tm(numero)
    assert tm is not None
    assert (tm.item_id, tm.move_id) == (item, movimiento)


def test_el_objeto_de_cada_mt_es_el_que_dice_la_tabla_de_pkhex(perfil) -> None:
    """La misma tabla con la que se leyó su mochila real (MT21 = 348)."""
    from app.boxed_metadata import item_name

    for tm in perfil.tms.values():
        esperado = tm.label.replace("TM", "MT").replace("HM", "MO")
        assert item_name(tm.item_id) == esperado, tm.label


# --------------------------------------------------------------------------
# Coherencia interna
# --------------------------------------------------------------------------

def test_son_noventa_y_cinco_mt_y_seis_mo(perfil) -> None:
    assert len(perfil.tms) == 101
    assert sum(1 for tm in perfil.tms.values() if tm.kind == "TM") == 95
    assert sum(1 for tm in perfil.tms.values() if tm.kind == "HM") == 6


def test_las_mo_se_numeran_detras_de_las_mt(perfil) -> None:
    """La interfaz indexa por un solo número: MO01 no puede chocar con MT01."""
    assert perfil.tm(1).kind == "TM"
    assert perfil.tm(96).kind == "HM"
    assert sorted(perfil.tms) == list(range(1, 102))


def test_ninguna_mt_repite_movimiento_ni_objeto(perfil) -> None:
    assert len({tm.move_id for tm in perfil.tms.values()}) == 101
    assert len({tm.item_id for tm in perfil.tms.values()}) == 101


def test_todas_las_mt_se_pueden_buscar_por_su_objeto(perfil) -> None:
    """Es la vía por la que la mochila viva se cruza con la tabla."""
    for tm in perfil.tms.values():
        assert perfil.tm_for_item(tm.item_id) is tm
    assert perfil.tm_for_item(17) is None      # Poción no es una MT


def test_todas_las_mt_caen_en_el_bolsillo_de_mt(perfil) -> None:
    """Si una MT no fuera legal en su bolsillo, la mochila viva la rechazaría."""
    from app.b2w2_live import bag_pocket_for

    for tm in perfil.tms.values():
        assert bag_pocket_for(tm.item_id).tipo == "TMHMs", tm.label


# --------------------------------------------------------------------------
# Los PP, que es lo que la interfaz pide al perfil
# --------------------------------------------------------------------------

def test_cada_mt_tiene_pp_de_quinta_generacion(perfil) -> None:
    for tm in perfil.tms.values():
        assert perfil.base_pp(tm.move_id) > 0, tm.label


@pytest.mark.parametrize(
    ("movimiento", "pp"),
    [(218, 20), (89, 10), (57, 15), (15, 30)],   # Frustración, Terremoto, Surf, Corte
)
def test_los_pp_son_los_de_la_tabla_ya_extraida(perfil, movimiento, pp) -> None:
    assert perfil.base_pp(movimiento) == pp


def test_un_movimiento_que_no_existe_en_quinta_no_inventa_pp(perfil) -> None:
    assert perfil.base_pp(9999) == 0


# --------------------------------------------------------------------------
# La procedencia queda escrita en el propio archivo
# --------------------------------------------------------------------------

def test_el_archivo_declara_de_donde_sale(perfil) -> None:
    documento = json.loads(perfil.source.read_text(encoding="utf-8-sig"))

    assert "PKHeX.Core" in documento["source"]
    assert "LearnSource5B2W2" in documento["source"]
    assert documento["total_indices"] == 101
    assert "deriva" in documento["metodo"]


def test_una_tabla_incoherente_no_se_publica(tmp_path, monkeypatch) -> None:
    """Antes de servir media tabla, se falla."""
    import app.b2w2_tm_service as servicio

    roto = tmp_path / "roto.json"
    roto.write_text(json.dumps({"entradas": [
        {"indice": 0, "etiqueta": "TM01", "numero": 1, "tipo": "TM",
         "item_id": 328, "move_id": 468},
        {"indice": 1, "etiqueta": "TM02", "numero": 2, "tipo": "TM",
         "item_id": 329, "move_id": 468},   # mismo movimiento
    ]}), encoding="utf-8")
    monkeypatch.setattr(servicio, "_TM_TABLE_PATH", roto)
    servicio.load_b2w2_tm_profile.cache_clear()

    try:
        with pytest.raises(B2W2TMError, match="mismo movimiento"):
            servicio.load_b2w2_tm_profile()
    finally:
        servicio.load_b2w2_tm_profile.cache_clear()


def test_sin_archivo_se_dice_cual_falta(tmp_path, monkeypatch) -> None:
    import app.b2w2_tm_service as servicio

    monkeypatch.setattr(servicio, "_TM_TABLE_PATH", tmp_path / "no_existe.json")
    servicio.load_b2w2_tm_profile.cache_clear()

    try:
        with pytest.raises(B2W2TMError, match="b2w2_tm_table.json"):
            servicio.load_b2w2_tm_profile()
    finally:
        servicio.load_b2w2_tm_profile.cache_clear()
