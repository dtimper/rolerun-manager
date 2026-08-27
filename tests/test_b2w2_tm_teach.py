"""Enseñanza de MT en B2/W2.

En quinta generación las MT son **reutilizables**: enseñar no gasta el objeto,
así que este writer no toca la mochila. Es la misma regla que ORAS y X/Y; solo
Perla Reluciente consume la máquina.

Qué enseña cada MT no sale de ninguna tabla de disco, sino de la lista que el
juego tiene cargada (ver `test_b2w2_tm_table.py`): RoleRun se juega en
randomizers y ahí la MT21 puede enseñar cualquier cosa.

Quién puede aprenderla lo decide el **rol** del Pokémon, no la compatibilidad de
especie del juego. Es una decisión deliberada de RoleRun y estas pruebas no la
contradicen.
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.b2w2_live import (  # noqa: E402
    MOVE_ID_MAX,
    PK5_PARTY_SIZE,
    B2W2LiveError,
    parse_pk5_party,
    pk5_party_with_move,
)
from app.models import PendingTMTeach  # noqa: E402
from app.realtime.b2w2_adapter import B2W2RealTimeAdapter  # noqa: E402

from test_b2w2_v026_foundation import (  # noqa: E402
    _FakeMelonDS,
    _pc_matrix_fixture,
    _pk5_fixture,
)

RAIZ = Path(__file__).resolve().parent.parent
TABLA_PP = json.loads(
    (RAIZ / "data" / "b2w2_move_pp.json").read_text(encoding="utf-8-sig")
)["pp"]

# El fixture conoce Placaje(33), Ataque Ala(39) y Ascuas(52); el hueco 4 vacío.
TERREMOTO = 89          # PP 10
DANZA_ESPADA = 14       # PP 30


def _base_pp(move_id: int) -> int:
    return int(TABLA_PP.get(str(int(move_id)), 0))


def _bloque() -> bytes:
    return _pk5_fixture()


# --------------------------------------------------------------------------
# El bloque PK5
# --------------------------------------------------------------------------

def test_ensenar_pone_el_movimiento_y_sus_pp_al_maximo() -> None:
    nuevo = pk5_party_with_move(_bloque(), 4, TERREMOTO, base_pp_for=_base_pp)

    leido = parse_pk5_party(nuevo, 0)
    assert leido.move_ids[3] == TERREMOTO
    assert leido.move_pp[3] == _base_pp(TERREMOTO) == 10


def test_los_demas_huecos_no_se_tocan() -> None:
    antes = parse_pk5_party(_bloque(), 0)

    despues = parse_pk5_party(
        pk5_party_with_move(_bloque(), 4, TERREMOTO, base_pp_for=_base_pp), 0,
    )

    assert despues.move_ids[:3] == antes.move_ids[:3]
    assert despues.move_pp[:3] == antes.move_pp[:3]
    assert despues.move_pp_ups[:3] == antes.move_pp_ups[:3]


def test_sustituir_un_movimiento_existente_reinicia_sus_mas_pp() -> None:
    """Los Más PP se aplicaron al movimiento viejo: no se heredan.

    El fixture tiene 1 Más PP en el primer hueco. Al enseñar encima, el
    movimiento nuevo empieza con sus PP base y sin Más PP, que es lo que hace
    el juego.
    """
    antes = parse_pk5_party(_bloque(), 0)
    assert antes.move_pp_ups[0] == 1

    despues = parse_pk5_party(
        pk5_party_with_move(_bloque(), 1, TERREMOTO, base_pp_for=_base_pp), 0,
    )

    assert despues.move_ids[0] == TERREMOTO
    assert despues.move_pp_ups[0] == 0
    assert despues.move_pp[0] == _base_pp(TERREMOTO)


def test_ensenar_no_toca_ps_estado_ni_estadisticas() -> None:
    """La extensión de party se reescribe tal cual: enseñar no cura ni hiere."""
    original = _bloque()
    antes = parse_pk5_party(original, 0)

    nuevo = pk5_party_with_move(original, 4, TERREMOTO, base_pp_for=_base_pp)
    despues = parse_pk5_party(nuevo, 0)

    assert nuevo[136:] == original[136:]
    assert (despues.current_hp, despues.max_hp) == (antes.current_hp, antes.max_hp)
    assert despues.status_condition == antes.status_condition
    assert despues.stats == antes.stats


def test_el_bloque_resultante_sigue_siendo_legible() -> None:
    """Si el checksum quedara mal, el juego rechazaría el Pokémon."""
    nuevo = pk5_party_with_move(_bloque(), 4, DANZA_ESPADA, base_pp_for=_base_pp)

    leido = parse_pk5_party(nuevo, 0)
    assert leido.pid == parse_pk5_party(_bloque(), 0).pid
    assert leido.nickname == "Tepig"
    assert len(nuevo) == PK5_PARTY_SIZE


# --------------------------------------------------------------------------
# Lo que no se escribe
# --------------------------------------------------------------------------

def test_no_se_deja_aprender_dos_veces_el_mismo_movimiento() -> None:
    """El juego no admite un movimiento repetido en dos huecos."""
    with pytest.raises(B2W2LiveError, match="ya conoce"):
        pk5_party_with_move(_bloque(), 4, 33, base_pp_for=_base_pp)   # Placaje


def test_tampoco_se_reensena_encima_del_mismo_hueco() -> None:
    """El juego tampoco lo permite, y borraría los Más PP del jugador.

    El primer hueco del fixture tiene 1 Más PP aplicado. Reescribir Placaje
    encima de Placaje pondría los PP base y perdería ese Más PP a cambio de
    nada. La interfaz ya filtra los movimientos conocidos: llegar aquí
    significa que algo se ha desalineado, y entonces no se escribe.
    """
    with pytest.raises(B2W2LiveError, match="ya conoce"):
        pk5_party_with_move(_bloque(), 1, 33, base_pp_for=_base_pp)


@pytest.mark.parametrize("hueco", [0, 5, -1])
def test_un_hueco_fuera_de_rango_se_rechaza(hueco: int) -> None:
    with pytest.raises(B2W2LiveError, match="entre 1 y 4"):
        pk5_party_with_move(_bloque(), hueco, TERREMOTO, base_pp_for=_base_pp)


@pytest.mark.parametrize("movimiento", [0, MOVE_ID_MAX + 1, 9999])
def test_un_movimiento_que_no_existe_en_quinta_se_rechaza(movimiento: int) -> None:
    with pytest.raises(B2W2LiveError, match="no existe en quinta"):
        pk5_party_with_move(_bloque(), 4, movimiento, base_pp_for=_base_pp)


def test_un_pp_no_demostrado_detiene_la_ensenanza() -> None:
    """Sin PP no se podría verificar la escritura ni curar después."""
    with pytest.raises(B2W2LiveError, match="demostrar el PP"):
        pk5_party_with_move(_bloque(), 4, TERREMOTO, base_pp_for=lambda _mid: 0)


def test_un_bloque_de_otro_tamano_se_rechaza() -> None:
    with pytest.raises(B2W2LiveError, match="220"):
        pk5_party_with_move(b"\x00" * 100, 4, TERREMOTO, base_pp_for=_base_pp)


# --------------------------------------------------------------------------
# El contrato transaccional
# --------------------------------------------------------------------------

def _lector(count: int = 2) -> _FakeMelonDS:
    party = b"".join(
        _pk5_fixture(pid=0x89E50000 + indice * 0x10000) for indice in range(count)
    )
    return _FakeMelonDS(count, party, _pc_matrix_fixture())


def _identidad(member) -> tuple[int, int, int]:
    return (int(member.pid), int(member.tid), int(member.sid))


def test_la_ensenanza_se_escribe_y_se_verifica() -> None:
    lector = _lector()
    party = lector.read_party()

    despues = lector.write_party_moves(
        party, [(0, _identidad(party.pokemon[0]), 4, TERREMOTO)],
        base_pp_for=_base_pp,
    )

    assert despues.pokemon[0].move_ids[3] == TERREMOTO
    assert despues.pokemon[0].move_pp[3] == _base_pp(TERREMOTO)


def test_el_resto_del_equipo_no_se_toca() -> None:
    lector = _lector()
    party = lector.read_party()
    antes = party.pokemon[1].move_ids

    despues = lector.write_party_moves(
        party, [(0, _identidad(party.pokemon[0]), 4, TERREMOTO)],
        base_pp_for=_base_pp,
    )

    assert despues.pokemon[1].move_ids == antes


def test_dos_ensenanzas_entran_como_una_sola_transaccion() -> None:
    lector = _lector()
    party = lector.read_party()

    despues = lector.write_party_moves(
        party,
        [
            (0, _identidad(party.pokemon[0]), 4, TERREMOTO),
            (1, _identidad(party.pokemon[1]), 4, DANZA_ESPADA),
        ],
        base_pp_for=_base_pp,
    )

    assert despues.pokemon[0].move_ids[3] == TERREMOTO
    assert despues.pokemon[1].move_ids[3] == DANZA_ESPADA


def test_dos_ensenanzas_sobre_el_mismo_hueco_se_rechazan() -> None:
    lector = _lector()
    party = lector.read_party()
    identidad = _identidad(party.pokemon[0])

    with pytest.raises(B2W2LiveError, match="mismo hueco"):
        lector.write_party_moves(
            party,
            [(0, identidad, 4, TERREMOTO), (0, identidad, 4, DANZA_ESPADA)],
            base_pp_for=_base_pp,
        )


def test_una_identidad_que_cambio_no_escribe_nada() -> None:
    """Si el equipo se movió entre preparar y escribir, no se escribe encima."""
    lector = _lector()
    party = lector.read_party()

    with pytest.raises(B2W2LiveError, match="identidad"):
        lector.write_party_moves(
            party, [(0, (1, 2, 3), 4, TERREMOTO)], base_pp_for=_base_pp,
        )


def test_un_movimiento_ya_conocido_no_escribe_nada() -> None:
    """Se detiene antes de tocar la RAM, no a mitad de la transacción."""
    lector = _lector()
    party = lector.read_party()
    escritas: list[int] = []
    original = lector._write_process_bytes
    lector._write_process_bytes = lambda *args: (
        escritas.append(1) or original(*args)
    )

    with pytest.raises(B2W2LiveError, match="ya conoce"):
        lector.write_party_moves(
            party, [(0, _identidad(party.pokemon[0]), 4, 33)],   # Placaje, ya está
            base_pp_for=_base_pp,
        )

    assert escritas == []


def test_un_slot_fuera_del_equipo_se_rechaza() -> None:
    lector = _lector(count=2)
    party = lector.read_party()

    with pytest.raises(B2W2LiveError, match="fuera de rango"):
        lector.write_party_moves(
            party, [(5, _identidad(party.pokemon[0]), 4, TERREMOTO)],
            base_pp_for=_base_pp,
        )


# --------------------------------------------------------------------------
# El adaptador
# --------------------------------------------------------------------------

def _cambio(identidad: str, hueco: int, move_id: int) -> PendingTMTeach:
    return PendingTMTeach(
        role="Mago", pokemon_slot=0, pokemon="Tepig", species="Tepig",
        move_slot=hueco, old_move="", old_move_id=0,
        new_move="Terremoto", new_move_id=move_id,
        pokemon_identity=identidad, item_id=353, tm_number=26,
        item_name="MT26", quantity_before=1,
    )


def _clave(member) -> str:
    return f"{int(member.species_id)}:{int(member.pid)}:{int(member.tid)}:{int(member.sid)}"


def test_el_adaptador_localiza_al_pokemon_por_identidad_no_por_slot() -> None:
    """El índice que traía el cambio puede haber quedado obsoleto."""
    lector = _lector()
    adaptador = B2W2RealTimeAdapter(reader=lector)
    party = lector.read_party()
    segundo = party.pokemon[1]

    objetivo = adaptador._move_target_for(party, _cambio(_clave(segundo), 4, TERREMOTO))

    assert objetivo[0] == 1, "encuentra al segundo miembro, no al slot 0 del cambio"
    assert objetivo[1] == _identidad(segundo)
    assert objetivo[2:] == (4, TERREMOTO)


def test_una_identidad_ausente_no_escribe_nada() -> None:
    lector = _lector()
    adaptador = B2W2RealTimeAdapter(reader=lector)

    with pytest.raises(B2W2LiveError, match="forma única"):
        adaptador._move_target_for(
            lector.read_party(), _cambio("1:2:3:4", 4, TERREMOTO),
        )


def test_el_adaptador_aplica_la_ensenanza() -> None:
    lector = _lector()
    adaptador = B2W2RealTimeAdapter(reader=lector)
    primero = lector.read_party().pokemon[0]

    from test_b2w2_v026_foundation import _current_game

    resultado = adaptador.apply_changes(
        _current_game(), [_cambio(_clave(primero), 4, TERREMOTO)],
    )

    assert resultado.applied_count == 1
    assert lector.read_party().pokemon[0].move_ids[3] == TERREMOTO


def test_la_mochila_no_se_toca_al_ensenar() -> None:
    """En quinta las MT son reutilizables: enseñar no gasta el objeto."""
    lector = _lector()
    adaptador = B2W2RealTimeAdapter(reader=lector)
    primero = lector.read_party().pokemon[0]
    destinos: list[int] = []
    original = lector._write_process_bytes

    def espiar(process_id, host_address, payload):
        destinos.append(int(host_address))
        return original(process_id, host_address, payload)

    lector._write_process_bytes = espiar

    from app.b2w2_live import BAG_BASE, DS_RAM_BASE
    from test_b2w2_v026_foundation import _current_game

    adaptador.apply_changes(_current_game(), [_cambio(_clave(primero), 4, TERREMOTO)])

    mochila = lector.ALLOCATION + (BAG_BASE - DS_RAM_BASE)
    assert mochila not in destinos
    assert destinos, "sí se escribió el equipo"


# --------------------------------------------------------------------------
# Las compuertas de la interfaz
# --------------------------------------------------------------------------

def test_la_compuerta_ya_admite_la_ensenanza_de_mt_en_b2w2() -> None:
    from types import SimpleNamespace

    from app.ui import RoleRunManager

    ui = SimpleNamespace(_active_azahar_realtime_key=lambda: "b2w2")
    mt = _cambio("1:2:3:4", 4, TERREMOTO)

    assert RoleRunManager._oras_live_unsupported_changes(ui, [mt]) == []


def test_una_mt_llega_a_la_auto_aplicacion() -> None:
    from types import SimpleNamespace

    from app.ui import RoleRunManager

    mt = _cambio("1:2:3:4", 4, TERREMOTO)
    manager = SimpleNamespace(
        _active_azahar_realtime_key=lambda: "b2w2",
        run=SimpleNamespace(pending_changes=[mt]),
        _oras_live_auto_apply_available=lambda: True,
        _oras_live_auto_apply_ids=set(),
        _schedule_oras_live_auto_apply=lambda *args, **kwargs: None,
        save_engine=SimpleNamespace(key="b2w2"),
    )

    RoleRunManager._request_oras_live_auto_apply(manager, [mt])

    assert manager._oras_live_auto_apply_ids == {id(mt)}


def test_el_drafteo_comparte_writer_con_la_ensenanza_de_mt() -> None:
    """Cambiar un movimiento a mano y enseñar una MT escriben lo mismo.

    Lo único que cambia es de dónde sale el movimiento. Mantener dos writers
    para la misma escritura habría sido la clase de duplicado que este proyecto
    ya pagó caro entre Sol/Luna y UltraSol.
    """
    from types import SimpleNamespace

    from app.models import PendingChange
    from app.ui import RoleRunManager

    ui = SimpleNamespace(_active_azahar_realtime_key=lambda: "b2w2")
    movimiento = PendingChange(
        role="Mago", pokemon_slot=0, pokemon="Tepig", species="Tepig",
        move_slot=1, old_move="Placaje", old_move_id=33,
        new_move="Ascuas", new_move_id=52, pokemon_identity="1:2:3:4",
    )

    assert RoleRunManager._oras_live_unsupported_changes(ui, [movimiento]) == []


def test_la_pantalla_de_mt_pide_el_perfil_al_adaptador_vivo() -> None:
    """B2/W2 no pide ninguna ROM: la tabla está en la RAM del juego."""
    from types import SimpleNamespace

    from app.ui import RoleRunManager

    perfil = object()
    manager = SimpleNamespace(
        b2w2_realtime_adapter=SimpleNamespace(read_tm_profile=lambda: perfil),
    )

    assert RoleRunManager._get_b2w2_tm_profile(manager) is perfil


def test_sin_adaptador_no_se_inventa_un_perfil() -> None:
    from types import SimpleNamespace

    from app.ui import RoleRunManager

    manager = SimpleNamespace(b2w2_realtime_adapter=None)

    assert RoleRunManager._get_b2w2_tm_profile(manager) is None


def test_la_pantalla_global_de_mt_ya_acepta_b2w2() -> None:
    from types import SimpleNamespace

    from app.ui import RoleRunManager

    perfil = object()
    manager = SimpleNamespace(
        save_engine=SimpleNamespace(key="b2w2"),
        current_save=SimpleNamespace(path="partida.sav"),
        _oras_live_active=True,
        _get_b2w2_tm_profile=lambda: perfil,
    )

    assert RoleRunManager._resolve_global_tm_profile(manager) is perfil


def test_sin_melonds_enlazado_la_pantalla_de_mt_no_lee_nada(monkeypatch) -> None:
    """No se sirve el último guardado como si fuera tiempo real."""
    from types import SimpleNamespace

    import app.ui as ui
    from app.ui import RoleRunManager

    avisos: list[str] = []
    monkeypatch.setattr(
        ui.messagebox, "showinfo",
        lambda titulo, *args, **kwargs: avisos.append(titulo),
    )
    manager = SimpleNamespace(
        save_engine=SimpleNamespace(key="b2w2"),
        current_save=SimpleNamespace(path="partida.sav"),
        _oras_live_active=False,
        _dialog_parent=lambda: None,
        _get_b2w2_tm_profile=lambda: pytest.fail("no debe leerse sin enlace"),
    )

    assert RoleRunManager._resolve_global_tm_profile(manager) is None
    assert avisos
