"""Drafteo en B2/W2: cambiar un movimiento a mano, y borrarlo.

Enseñar una MT y draftear un movimiento escriben exactamente lo mismo en el
PK5; lo único que cambia es de dónde sale el movimiento. Por eso comparten
writer: mantener dos para la misma escritura habría sido la clase de duplicado
que este proyecto ya pagó caro entre Sol/Luna y UltraSol.

Lo que el drafteo añade es el **borrado**. Un Support que pasa a tener más de
dos ataques de daño pierde los que sobran, y eso llega como un cambio con
movimiento cero. Al borrar hay que compactar: un Pokémon no puede tener un
hueco vacío delante de uno lleno. Es la misma operación que `_remove_move_slots`
en ORAS.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.b2w2_live import (  # noqa: E402
    B2W2LiveError,
    parse_pk5_party,
    pk5_party_without_moves,
)
from app.models import PendingChange  # noqa: E402
from app.realtime.b2w2_adapter import B2W2RealTimeAdapter  # noqa: E402

from test_b2w2_v026_foundation import (  # noqa: E402
    _FakeMelonDS,
    _current_game,
    _pc_matrix_fixture,
    _pk5_fixture,
)

RAIZ = Path(__file__).resolve().parent.parent
TABLA_PP = json.loads(
    (RAIZ / "data" / "b2w2_move_pp.json").read_text(encoding="utf-8-sig")
)["pp"]

# El fixture conoce Placaje(33), Ataque Ala(39) y Ascuas(52); el hueco 4 vacío.
PLACAJE, ATAQUE_ALA, ASCUAS = 33, 39, 52
TERREMOTO = 89


def _base_pp(move_id: int) -> int:
    return int(TABLA_PP.get(str(int(move_id)), 0))


def _bloque() -> bytes:
    return _pk5_fixture()


# --------------------------------------------------------------------------
# El borrado compacta
# --------------------------------------------------------------------------

def test_borrar_el_primer_movimiento_sube_los_demas() -> None:
    """Un hueco vacío delante de uno lleno no es un moveset válido."""
    leido = parse_pk5_party(pk5_party_without_moves(_bloque(), [1]), 0)

    assert leido.move_ids == (ATAQUE_ALA, ASCUAS, 0, 0)


def test_los_pp_y_los_mas_pp_suben_con_su_movimiento() -> None:
    """Si solo subiera el identificador, cada ataque heredaría PP ajenos."""
    antes = parse_pk5_party(_bloque(), 0)

    despues = parse_pk5_party(pk5_party_without_moves(_bloque(), [1]), 0)

    assert despues.move_pp[:2] == antes.move_pp[1:3]
    assert despues.move_pp_ups[:2] == antes.move_pp_ups[1:3]
    assert despues.move_pp[3] == 0 and despues.move_pp_ups[3] == 0


def test_borrar_el_de_en_medio_deja_el_resto_en_orden() -> None:
    leido = parse_pk5_party(pk5_party_without_moves(_bloque(), [2]), 0)

    assert leido.move_ids == (PLACAJE, ASCUAS, 0, 0)


def test_borrar_varios_a_la_vez_no_se_pisa() -> None:
    """Se borran de atrás hacia delante para que cada hueco siga significando lo mismo."""
    leido = parse_pk5_party(pk5_party_without_moves(_bloque(), [1, 3]), 0)

    assert leido.move_ids == (ATAQUE_ALA, 0, 0, 0)


def test_borrar_no_toca_ps_estado_ni_estadisticas() -> None:
    original = _bloque()
    antes = parse_pk5_party(original, 0)

    nuevo = pk5_party_without_moves(original, [2])

    assert nuevo[136:] == original[136:]
    assert parse_pk5_party(nuevo, 0).current_hp == antes.current_hp


def test_el_bloque_borrado_sigue_siendo_legible() -> None:
    """Si el checksum quedara mal, el juego rechazaría el Pokémon."""
    leido = parse_pk5_party(pk5_party_without_moves(_bloque(), [2]), 0)

    assert leido.nickname == "Tepig"


# --------------------------------------------------------------------------
# Lo que no se borra
# --------------------------------------------------------------------------

def test_no_se_deja_a_un_pokemon_sin_ningun_movimiento() -> None:
    """El juego no admite un Pokémon con los cuatro huecos vacíos."""
    with pytest.raises(B2W2LiveError, match="sin ningún movimiento"):
        pk5_party_without_moves(_bloque(), [1, 2, 3])


def test_borrar_un_hueco_ya_vacio_se_rechaza() -> None:
    """Si el hueco no tenía nada, el cambio venía de un estado que ya no existe."""
    with pytest.raises(B2W2LiveError, match="ya estaba vacío"):
        pk5_party_without_moves(_bloque(), [4])


@pytest.mark.parametrize("hueco", [0, 5, -1])
def test_un_hueco_fuera_de_rango_se_rechaza(hueco: int) -> None:
    with pytest.raises(B2W2LiveError, match="entre 1 y 4"):
        pk5_party_without_moves(_bloque(), [hueco])


def test_sin_huecos_no_hay_nada_que_borrar() -> None:
    with pytest.raises(B2W2LiveError, match="ningún movimiento"):
        pk5_party_without_moves(_bloque(), [])


# --------------------------------------------------------------------------
# La transacción
# --------------------------------------------------------------------------

def _lector(count: int = 2) -> _FakeMelonDS:
    party = b"".join(
        _pk5_fixture(pid=0x89E50000 + indice * 0x10000) for indice in range(count)
    )
    return _FakeMelonDS(count, party, _pc_matrix_fixture())


def _identidad(member) -> tuple[int, int, int]:
    return (int(member.pid), int(member.tid), int(member.sid))


def test_un_drafteo_se_escribe_y_se_verifica() -> None:
    lector = _lector()
    party = lector.read_party()

    despues = lector.write_party_moves(
        party, [(0, _identidad(party.pokemon[0]), 2, TERREMOTO)],
        base_pp_for=_base_pp,
    )

    assert despues.pokemon[0].move_ids == (PLACAJE, TERREMOTO, ASCUAS, 0)
    assert despues.pokemon[0].move_pp[1] == _base_pp(TERREMOTO)


def test_un_borrado_se_escribe_y_se_verifica() -> None:
    lector = _lector()
    party = lector.read_party()

    despues = lector.write_party_moves(
        party, [(0, _identidad(party.pokemon[0]), 1, 0)], base_pp_for=_base_pp,
    )

    assert despues.pokemon[0].move_ids == (ATAQUE_ALA, ASCUAS, 0, 0)


def test_dar_uno_y_quitar_otro_al_mismo_pokemon_es_una_sola_transaccion() -> None:
    """El nuevo se escribe primero y el borrado compacta después.

    Es lo que pasa cuando un Support recibe un movimiento y pierde a la vez un
    ataque que le sobraba. El hueco elegido para el nuevo significa lo que el
    usuario vio, y la compactación posterior lo desplaza como haría el juego.
    """
    lector = _lector()
    party = lector.read_party()
    identidad = _identidad(party.pokemon[0])
    escrituras: list[int] = []
    original = lector._write_process_bytes
    lector._write_process_bytes = lambda *args: (
        escrituras.append(1) or original(*args)
    )

    despues = lector.write_party_moves(
        party,
        [(0, identidad, 4, TERREMOTO), (0, identidad, 1, 0)],
        base_pp_for=_base_pp,
    )

    assert despues.pokemon[0].move_ids == (ATAQUE_ALA, ASCUAS, TERREMOTO, 0)
    assert escrituras == [1], "un único bloque, no una escritura por cambio"


def test_el_resto_del_equipo_no_se_toca() -> None:
    lector = _lector()
    party = lector.read_party()
    antes = party.pokemon[1].move_ids

    despues = lector.write_party_moves(
        party, [(0, _identidad(party.pokemon[0]), 1, 0)], base_pp_for=_base_pp,
    )

    assert despues.pokemon[1].move_ids == antes


def test_dos_cambios_sobre_el_mismo_hueco_se_rechazan() -> None:
    lector = _lector()
    party = lector.read_party()
    identidad = _identidad(party.pokemon[0])

    with pytest.raises(B2W2LiveError, match="mismo hueco"):
        lector.write_party_moves(
            party, [(0, identidad, 2, TERREMOTO), (0, identidad, 2, 0)],
            base_pp_for=_base_pp,
        )


def test_un_borrado_que_dejaria_al_pokemon_vacio_no_escribe_nada() -> None:
    lector = _lector()
    party = lector.read_party()
    identidad = _identidad(party.pokemon[0])
    original = bytes(lector.party_raw)

    with pytest.raises(B2W2LiveError, match="sin ningún movimiento"):
        lector.write_party_moves(
            party,
            [(0, identidad, 1, 0), (0, identidad, 2, 0), (0, identidad, 3, 0)],
            base_pp_for=_base_pp,
        )

    assert bytes(lector.party_raw) == original


# --------------------------------------------------------------------------
# El adaptador
# --------------------------------------------------------------------------

def _clave(member) -> str:
    return f"{int(member.species_id)}:{int(member.pid)}:{int(member.tid)}:{int(member.sid)}"


def _drafteo(identidad: str, hueco: int, move_id: int) -> PendingChange:
    return PendingChange(
        role="Mago", pokemon_slot=0, pokemon="Tepig", species="Tepig",
        move_slot=hueco, old_move="Placaje", old_move_id=PLACAJE,
        new_move="Terremoto", new_move_id=move_id,
        pokemon_identity=identidad,
    )


def test_el_adaptador_aplica_un_drafteo() -> None:
    lector = _lector()
    adaptador = B2W2RealTimeAdapter(reader=lector)
    primero = lector.read_party().pokemon[0]

    resultado = adaptador.apply_changes(
        _current_game(), [_drafteo(_clave(primero), 2, TERREMOTO)],
    )

    assert resultado.applied_count == 1
    assert lector.read_party().pokemon[0].move_ids[1] == TERREMOTO


def test_el_adaptador_aplica_un_borrado() -> None:
    lector = _lector()
    adaptador = B2W2RealTimeAdapter(reader=lector)
    primero = lector.read_party().pokemon[0]

    adaptador.apply_changes(_current_game(), [_drafteo(_clave(primero), 1, 0)])

    assert lector.read_party().pokemon[0].move_ids == (ATAQUE_ALA, ASCUAS, 0, 0)


def test_el_adaptador_localiza_al_pokemon_por_identidad_no_por_slot() -> None:
    """El índice de party que traía el cambio puede haber quedado obsoleto."""
    lector = _lector()
    adaptador = B2W2RealTimeAdapter(reader=lector)
    party = lector.read_party()
    segundo = party.pokemon[1]

    objetivo = adaptador._move_target_for(party, _drafteo(_clave(segundo), 2, TERREMOTO))

    assert objetivo == (1, _identidad(segundo), 2, TERREMOTO)


def test_un_cambio_sin_identidad_no_escribe_nada() -> None:
    """Sin identidad no se puede saber a quién se le escribe."""
    lector = _lector()
    adaptador = B2W2RealTimeAdapter(reader=lector)

    with pytest.raises(B2W2LiveError, match="no trae identidad"):
        adaptador._move_target_for(lector.read_party(), _drafteo("", 2, TERREMOTO))


def test_una_mt_y_un_drafteo_pueden_ir_en_el_mismo_lote() -> None:
    """Comparten writer, así que no hace falta separarlos en dos transacciones."""
    from test_b2w2_tm_teach import _cambio as _mt

    lector = _lector()
    adaptador = B2W2RealTimeAdapter(reader=lector)
    party = lector.read_party()

    resultado = adaptador.apply_changes(_current_game(), [
        _drafteo(_clave(party.pokemon[0]), 2, TERREMOTO),
        _mt(_clave(party.pokemon[1]), 4, TERREMOTO),
    ])

    assert resultado.applied_count == 2
    despues = lector.read_party()
    assert despues.pokemon[0].move_ids[1] == TERREMOTO
    assert despues.pokemon[1].move_ids[3] == TERREMOTO
