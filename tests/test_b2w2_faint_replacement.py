"""Bajas y sustitución en B2/W2.

Es el corazón de una RoleRun: cuando un Pokémon cae, se descuenta una vida, el
debilitado va al Cementerio y entra un sustituto que hereda su rol.

Sus tres dependencias quedaron validadas físicamente por el usuario el
27-08-2026: la lane de combate, el writer de roles y la escritura del PC. Hasta
entonces la rama B2/W2 del monitor ni siquiera llegaba a la detección de bajas.

Intervienen **tres** posiciones, no dos: el sustituto sale de su casilla, el
debilitado va a otra distinta y la casilla de origen queda vacía. Por eso no vale
reutilizar ``swap_party_pc``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.b2w2_live import (  # noqa: E402
    PC_BOX_STRIDE,
    PK5_STORED_SIZE,
    B2W2LiveError,
    empty_pk5_stored,
    parse_pk5_boxed,
)
from app.models import PendingTeamChange  # noqa: E402
from app.ui import RoleRunManager  # noqa: E402

from test_b2w2_v026_foundation import (  # noqa: E402
    _FakeMelonDS,
    _pc_matrix_fixture,
    _pk5_fixture,
)

CEMENTERIO = (4, 5)


def _reader() -> _FakeMelonDS:
    """Party de dos y un sustituto en Caja 1 slot 1 (del fixture del PC)."""
    return _FakeMelonDS(
        2,
        _pk5_fixture(current_hp=0) + _pk5_fixture(pid=7 << 13),
        _pc_matrix_fixture(),
    )


def _slot_pc(reader: _FakeMelonDS, box: int, slot: int) -> bytes:
    offset = (box - 1) * PC_BOX_STRIDE + (slot - 1) * PK5_STORED_SIZE
    return bytes(reader.pc_raw[offset:offset + PK5_STORED_SIZE])


def _sustituto(reader: _FakeMelonDS):
    return parse_pk5_boxed(_slot_pc(reader, 1, 1), 1, 1)


def _identidad(pokemon) -> tuple[int, int, int]:
    return (pokemon.pid, pokemon.tid, pokemon.sid)


def _ejecutar(reader: _FakeMelonDS, **cambios):
    party = reader.read_party()
    entrante = _sustituto(reader)
    saliente = party.pokemon[0]
    argumentos = dict(
        party_slot=0, box=1, box_slot=1,
        graveyard_box=CEMENTERIO[0], graveyard_box_slot=CEMENTERIO[1],
        incoming_party=_pk5_fixture(pid=3 << 13),
        incoming_identity=_identidad(entrante),
        outgoing_identity=_identidad(saliente),
    )
    argumentos.update(cambios)
    incoming_party = argumentos.pop("incoming_party")
    return reader.replace_fainted_party_pc(
        party,
        argumentos.pop("party_slot"), argumentos.pop("box"), argumentos.pop("box_slot"),
        argumentos.pop("graveyard_box"), argumentos.pop("graveyard_box_slot"),
        incoming_party, **argumentos,
    )


# --------------------------------------------------------------------------
# El writer
# --------------------------------------------------------------------------

def test_la_sustitucion_mueve_las_tres_posiciones() -> None:
    reader = _reader()
    entrante = _sustituto(reader)
    saliente = reader.read_party().pokemon[0]

    after_party, after_pc = _ejecutar(reader)

    assert _identidad(after_party.pokemon[0]) == _identidad(entrante)
    assert after_party.count == 2, "el equipo no cambia de tamaño"
    enterrado = next(p for p in after_pc.pokemon if (p.box, p.slot) == CEMENTERIO)
    assert _identidad(enterrado) == _identidad(saliente)
    assert not any((p.box, p.slot) == (1, 1) for p in after_pc.pokemon)


def test_la_casilla_de_origen_queda_como_la_deja_el_juego() -> None:
    """El vacío es un PK5 semilla-0, no 136 ceros. Es el arreglo de B1."""
    reader = _reader()
    _ejecutar(reader)
    assert _slot_pc(reader, 1, 1) == empty_pk5_stored()


def test_el_orden_de_escritura_nunca_deja_a_nadie_sin_copia() -> None:
    """Primero el Cementerio, luego la party y por último vaciar el origen.

    En cada punto intermedio puede haber un duplicado —recuperable—, pero jamás
    un Pokémon con cero copias, que no lo sería.
    """
    reader = _reader()
    entrante_id = _identidad(_sustituto(reader))
    saliente_id = _identidad(reader.read_party().pokemon[0])
    copias: list[tuple[int, int]] = []

    original = reader._write_process_bytes

    def contar(process_id, host_address, payload):
        original(process_id, host_address, payload)
        party = reader.read_party()
        _vacios, pc = reader.__class__.parse_pc_matrix(bytes(reader.pc_raw))
        presentes = [_identidad(p) for p in party.pokemon] + [_identidad(p) for p in pc]
        copias.append((presentes.count(saliente_id), presentes.count(entrante_id)))

    reader._write_process_bytes = contar
    _ejecutar(reader)

    assert copias, "no se registró ninguna escritura"
    for saliente, entrante in copias:
        assert saliente >= 1, "el debilitado se quedó sin ninguna copia"
        assert entrante >= 1, "el sustituto se quedó sin ninguna copia"


def test_el_cementerio_ocupado_detiene_la_sustitucion() -> None:
    reader = _reader()
    ocupado = (1, 1)          # la casilla del fixture que sí tiene un Pokémon
    antes = bytes(reader.pc_raw)

    with pytest.raises(B2W2LiveError, match="Cementerio"):
        _ejecutar(reader, graveyard_box=ocupado[0], graveyard_box_slot=ocupado[1])

    assert bytes(reader.pc_raw) == antes


def test_origen_y_cementerio_no_pueden_ser_la_misma_casilla() -> None:
    reader = _reader()
    with pytest.raises(B2W2LiveError, match="misma casilla"):
        _ejecutar(reader, graveyard_box=1, graveyard_box_slot=1)


def test_si_el_debilitado_ya_no_es_el_mismo_no_se_escribe_nada() -> None:
    reader = _reader()
    antes_pc, antes_party = bytes(reader.pc_raw), bytes(reader.party_raw)

    with pytest.raises(B2W2LiveError, match="debilitado"):
        _ejecutar(reader, outgoing_identity=(0xDEADBEEF, 1, 2))

    assert bytes(reader.pc_raw) == antes_pc
    assert bytes(reader.party_raw) == antes_party


def test_si_el_sustituto_ya_no_esta_en_su_casilla_no_se_escribe_nada() -> None:
    reader = _reader()
    antes_pc, antes_party = bytes(reader.pc_raw), bytes(reader.party_raw)

    with pytest.raises(B2W2LiveError, match="sustituto"):
        _ejecutar(reader, incoming_identity=(0xDEADBEEF, 1, 2))

    assert bytes(reader.pc_raw) == antes_pc
    assert bytes(reader.party_raw) == antes_party


def test_el_rollback_devuelve_las_tres_posiciones() -> None:
    reader = _reader()
    antes_pc, antes_party = bytes(reader.pc_raw), bytes(reader.party_raw)

    original = reader._write_process_bytes
    llamadas = {"n": 0}

    def escritura_que_se_pierde(process_id, host_address, payload):
        llamadas["n"] += 1
        if llamadas["n"] == 2:     # la party no llega a escribirse
            return
        original(process_id, host_address, payload)

    reader._write_process_bytes = escritura_que_se_pierde

    with pytest.raises(B2W2LiveError):
        _ejecutar(reader)

    assert bytes(reader.pc_raw) == antes_pc
    assert bytes(reader.party_raw) == antes_party


# --------------------------------------------------------------------------
# Las compuertas
# --------------------------------------------------------------------------

def _cambio() -> PendingTeamChange:
    return PendingTeamChange(
        operation="replace-fainted", party_slot=0, box=1, box_slot=1,
        graveyard_box=CEMENTERIO[0], graveyard_box_slot=CEMENTERIO[1],
    )


def test_la_sustitucion_atraviesa_la_compuerta_de_b2w2() -> None:
    ui = SimpleNamespace(_active_azahar_realtime_key=lambda: "b2w2")
    assert RoleRunManager._oras_live_unsupported_changes(ui, [_cambio()]) == []


def test_la_sustitucion_llega_a_la_auto_aplicacion() -> None:
    cambio = _cambio()
    manager = SimpleNamespace(
        _active_azahar_realtime_key=lambda: "b2w2",
        run=SimpleNamespace(pending_changes=[cambio]),
        _oras_live_auto_apply_available=lambda: True,
        _oras_live_auto_apply_ids=set(),
        _schedule_oras_live_auto_apply=lambda *args, **kwargs: None,
        save_engine=SimpleNamespace(key="b2w2"),
    )

    RoleRunManager._request_oras_live_auto_apply(manager, [cambio])

    assert manager._oras_live_auto_apply_ids == {id(cambio)}


def test_una_operacion_de_equipo_sin_writer_sigue_bloqueada() -> None:
    """Abrir la sustitución no abre de rebote cualquier otra operación."""
    ui = SimpleNamespace(_active_azahar_realtime_key=lambda: "b2w2")
    inventado = PendingTeamChange(operation="operacion-inventada", party_slot=0)

    assert RoleRunManager._oras_live_unsupported_changes(ui, [inventado]) == [
        "cambios Equipo ↔ PC",
    ]
