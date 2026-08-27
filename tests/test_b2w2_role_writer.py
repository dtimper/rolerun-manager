"""Writer de roles de B2/W2: marcas, EV y estadísticas recalculadas.

Hasta alpha.23, asignar un rol en Negro 2 no hacía nada visible: el cambio se
quedaba en la cola porque no existía writer, los seis Pokémon seguían mostrando
"SIN ROL" y los EV seguían a cero. Peor aún, como
``_oras_live_reconciliation_can_read`` exige la cola vacía, ese cambio atascado
**congelaba el monitor en vivo**, así que tampoco se actualizaba la salud.

El rol de RoleRun vive en las seis marcas del PK5 y, cuando el rol define un
reparto de esfuerzo, también en los EV. Cambiar EV sin recalcular las
estadísticas dejaría al Pokémon con los valores antiguos y un PS máximo que no
cuadra con el actual, así que el writer las recalcula con la misma tabla personal
que ya usa el resto de RoleRun.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.b2w2_live import (  # noqa: E402
    STAT_ORDER_PERSONAL,
    B2W2LiveError,
    B2W2RoleWrite,
    gen5_final_stats,
    parse_pk5_party,
    pk5_party_with_role,
)
from app.boxed_metadata import base_stats_for  # noqa: E402
from app.models import PendingChange, PendingPCRoleChange, PendingRoleChange  # noqa: E402
from app.realtime.b2w2_adapter import B2W2RealTimeAdapter  # noqa: E402
from app.role_rules import ROLE_ORDER  # noqa: E402
from app.ui import RoleRunManager  # noqa: E402

from test_b2w2_v026_foundation import (  # noqa: E402
    _FakeMelonDS,
    _pc_matrix_fixture,
    _pk5_fixture,
)

TEPIG = 498


def _base(species: int = TEPIG, form: int = 0) -> dict[str, int]:
    return dict(zip(STAT_ORDER_PERSONAL, base_stats_for("b2w2", species, form)))


# --------------------------------------------------------------------------
# La fórmula
# --------------------------------------------------------------------------

def test_las_estadisticas_siguen_la_formula_de_tercera_generacion() -> None:
    """Tepig nivel 7, IV 31 y EV 252 en PS: ((2·65+31+63)·7)/100 + 7 + 10 = 32."""
    finales = gen5_final_stats(
        base=_base(),
        ivs=dict.fromkeys(STAT_ORDER_PERSONAL, 31),
        evs={**dict.fromkeys(STAT_ORDER_PERSONAL, 0), "hp": 252},
        level=7, nature_id=0,
    )
    assert finales["hp"] == 32


def test_la_naturaleza_sube_y_baja_un_diez_por_ciento() -> None:
    comun = dict(
        base=_base(), ivs=dict.fromkeys(STAT_ORDER_PERSONAL, 31),
        evs=dict.fromkeys(STAT_ORDER_PERSONAL, 0), level=50,
    )
    neutra = gen5_final_stats(nature_id=0, **comun)          # Fuerte: sin efecto
    sube_ataque = gen5_final_stats(nature_id=1, **comun)     # Huraña: +Atk -Def
    assert sube_ataque["attack"] == neutra["attack"] * 11 // 10
    assert sube_ataque["defense"] == neutra["defense"] * 9 // 10
    assert sube_ataque["hp"] == neutra["hp"], "la naturaleza nunca toca los PS"


def test_un_nivel_imposible_se_rechaza() -> None:
    with pytest.raises(B2W2LiveError, match="nivel"):
        gen5_final_stats(
            base=_base(), ivs=dict.fromkeys(STAT_ORDER_PERSONAL, 0),
            evs=dict.fromkeys(STAT_ORDER_PERSONAL, 0), level=0, nature_id=0,
        )


# --------------------------------------------------------------------------
# La reescritura del bloque
# --------------------------------------------------------------------------

def test_el_bloque_reescrito_lo_acepta_el_parser_de_produccion() -> None:
    nuevo = pk5_party_with_role(
        _pk5_fixture(),
        markings=(False, False, True, False, False, False),
        evs=(252, 0, 0, 252, 4, 0),
        base_stats=_base(),
    )
    despues = parse_pk5_party(nuevo, 0)

    assert despues.markings == (False, False, True, False, False, False)
    assert despues.evs == (252, 0, 0, 252, 4, 0)
    assert despues.max_hp == 32 and despues.stats[0] == 32


def test_la_reescritura_no_toca_nada_mas_del_pokemon() -> None:
    antes = parse_pk5_party(_pk5_fixture(), 0)
    despues = parse_pk5_party(
        pk5_party_with_role(
            _pk5_fixture(), markings=(False,) * 6, evs=(0,) * 6, base_stats=_base(),
        ),
        0,
    )
    assert (despues.pid, despues.tid, despues.sid) == (antes.pid, antes.tid, antes.sid)
    assert despues.species_id == antes.species_id
    assert despues.nickname == antes.nickname
    assert despues.level == antes.level
    assert despues.ivs == antes.ivs
    assert despues.move_ids == antes.move_ids
    assert despues.move_pp == antes.move_pp
    assert despues.nature_id == antes.nature_id


def test_se_conserva_el_dano_recibido_al_subir_el_ps_maximo() -> None:
    antes = parse_pk5_party(_pk5_fixture(), 0)
    faltaban = antes.max_hp - antes.current_hp

    despues = parse_pk5_party(
        pk5_party_with_role(
            _pk5_fixture(), markings=(False,) * 6, evs=(252, 0, 0, 0, 0, 0),
            base_stats=_base(),
        ),
        0,
    )

    assert despues.max_hp > antes.max_hp
    assert despues.max_hp - despues.current_hp == faltaban


def test_un_debilitado_sigue_debilitado() -> None:
    """Subir el PS máximo no puede revivir a nadie."""
    caido = _pk5_fixture(current_hp=0)
    despues = parse_pk5_party(
        pk5_party_with_role(
            caido, markings=(False,) * 6, evs=(252, 0, 0, 0, 0, 0), base_stats=_base(),
        ),
        0,
    )
    assert despues.current_hp == 0


@pytest.mark.parametrize(
    "evs", [(255, 255, 255, 0, 0, 0), (300, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0)],
)
def test_se_rechazan_los_ev_imposibles(evs) -> None:
    with pytest.raises(B2W2LiveError):
        pk5_party_with_role(
            _pk5_fixture(), markings=(False,) * 6, evs=evs, base_stats=_base(),
        )


def test_no_se_reescribe_un_bloque_con_checksum_invalido() -> None:
    corrupto = bytearray(_pk5_fixture())
    corrupto[20] ^= 0xFF
    with pytest.raises(B2W2LiveError, match="Checksum"):
        pk5_party_with_role(
            bytes(corrupto), markings=(False,) * 6, evs=(0,) * 6, base_stats=_base(),
        )


# --------------------------------------------------------------------------
# El writer transaccional
# --------------------------------------------------------------------------

def _reader_con_dos_miembros() -> _FakeMelonDS:
    return _FakeMelonDS(2, _pk5_fixture() + _pk5_fixture(pid=5 << 13), _pc_matrix_fixture())


def _peticion(slot: int, identity, *, markings, evs) -> B2W2RoleWrite:
    return B2W2RoleWrite(
        slot=slot, identity=identity, markings=markings, evs=evs, base_stats=_base(),
    )


def test_el_writer_aplica_y_verifica_el_rol() -> None:
    reader = _reader_con_dos_miembros()
    party = reader.read_party()
    objetivo = party.pokemon[0]

    despues = reader.write_party_roles(party, [
        _peticion(
            0, (objetivo.pid, objetivo.tid, objetivo.sid),
            markings=(False, True, False, False, False, False),
            evs=(0, 252, 0, 0, 4, 252),
        ),
    ])

    assert despues.pokemon[0].markings == (False, True, False, False, False, False)
    assert despues.pokemon[0].evs == (0, 252, 0, 0, 4, 252)
    # El otro miembro no se toca.
    assert despues.pokemon[1].evs == party.pokemon[1].evs
    assert despues.count == party.count


def test_el_writer_hace_rollback_si_la_identidad_cambio() -> None:
    reader = _reader_con_dos_miembros()
    party = reader.read_party()
    antes = bytes(reader.party_raw)

    with pytest.raises(B2W2LiveError, match="identidad"):
        reader.write_party_roles(party, [
            _peticion(0, (0xDEADBEEF, 1, 2),
                      markings=(True,) + (False,) * 5, evs=(0,) * 6),
        ])

    assert bytes(reader.party_raw) == antes, "la RAM debía quedar intacta"


def test_el_writer_rechaza_dos_cambios_sobre_el_mismo_slot() -> None:
    reader = _reader_con_dos_miembros()
    party = reader.read_party()
    objetivo = party.pokemon[0]
    identidad = (objetivo.pid, objetivo.tid, objetivo.sid)

    with pytest.raises(B2W2LiveError, match="mismo slot"):
        reader.write_party_roles(party, [
            _peticion(0, identidad, markings=(True,) + (False,) * 5, evs=(0,) * 6),
            _peticion(0, identidad, markings=(False, True) + (False,) * 4, evs=(0,) * 6),
        ])


def test_el_writer_rechaza_un_slot_fuera_de_la_party() -> None:
    reader = _reader_con_dos_miembros()
    party = reader.read_party()

    with pytest.raises(B2W2LiveError, match="fuera de rango"):
        reader.write_party_roles(party, [
            _peticion(5, (1, 2, 3), markings=(False,) * 6, evs=(0,) * 6),
        ])


def test_el_writer_hace_rollback_si_el_readback_no_cuadra() -> None:
    """Si melonDS no acepta la escritura, la party debe quedar como estaba."""
    reader = _reader_con_dos_miembros()
    party = reader.read_party()
    objetivo = party.pokemon[0]
    antes = bytes(reader.party_raw)

    original = reader._write_process_bytes
    llamadas = {"n": 0}

    def escritura_que_se_pierde(process_id, host_address, payload):
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            return  # melonDS ignora la escritura
        original(process_id, host_address, payload)

    reader._write_process_bytes = escritura_que_se_pierde

    with pytest.raises(B2W2LiveError, match="readback"):
        reader.write_party_roles(party, [
            _peticion(0, (objetivo.pid, objetivo.tid, objetivo.sid),
                      markings=(True,) + (False,) * 5, evs=(0,) * 6),
        ])

    assert bytes(reader.party_raw) == antes


# --------------------------------------------------------------------------
# El adaptador y la compuerta
# --------------------------------------------------------------------------

def _adapter() -> B2W2RealTimeAdapter:
    return B2W2RealTimeAdapter(reader=_reader_con_dos_miembros())


def _identidad(miembro) -> str:
    return f"{miembro.species_id}:{miembro.pid}:{miembro.tid}:{miembro.sid}"


@pytest.mark.parametrize("indice_rol", range(6))
def test_cada_rol_marca_exactamente_su_casilla(indice_rol: int) -> None:
    adapter = _adapter()
    party = adapter.reader.read_party()
    miembro = party.pokemon[0]

    peticion = adapter._role_write_for(party, PendingRoleChange(
        0, "Tepig", "Tepig", "SIN ROL", ROLE_ORDER[indice_rol],
        pokemon_identity=_identidad(miembro),
    ))

    assert peticion.markings == tuple(i == indice_rol for i in range(6))
    assert peticion.slot == 0


def test_sin_rol_borra_todas_las_marcas() -> None:
    adapter = _adapter()
    party = adapter.reader.read_party()
    miembro = party.pokemon[0]

    peticion = adapter._role_write_for(party, PendingRoleChange(
        0, "Tepig", "Tepig", "Mago", "SIN ROL", pokemon_identity=_identidad(miembro),
    ))

    assert peticion.markings == (False,) * 6


def test_sin_ev_nuevos_se_conservan_los_que_ya_tenia() -> None:
    adapter = _adapter()
    party = adapter.reader.read_party()
    miembro = party.pokemon[0]

    peticion = adapter._role_write_for(party, PendingRoleChange(
        0, "Tepig", "Tepig", "SIN ROL", "Mago", pokemon_identity=_identidad(miembro),
    ))

    assert peticion.evs == tuple(miembro.evs)


def test_una_identidad_ausente_no_escribe_nada() -> None:
    adapter = _adapter()
    party = adapter.reader.read_party()

    with pytest.raises(B2W2LiveError, match="forma única"):
        adapter._role_write_for(party, PendingRoleChange(
            0, "Fantasma", "Fantasma", "SIN ROL", "Mago",
            pokemon_identity="1:2:3:4",
        ))


def test_la_compuerta_ya_admite_los_cambios_de_rol_en_b2w2() -> None:
    ui = SimpleNamespace(_active_azahar_realtime_key=lambda: "b2w2")
    rol = PendingRoleChange(0, "Tepig", "Tepig", "SIN ROL", "Mago")

    assert RoleRunManager._oras_live_unsupported_changes(ui, [rol]) == []


def test_abrir_roles_no_abre_de_rebote_lo_que_no_tiene_writer() -> None:
    """Una capacidad solo atraviesa la compuerta cuando tiene writer propio.

    La curación se abrió en alpha.26, los movimientos sueltos en alpha.46. Lo
    que esta prueba protege es la regla, no la lista: el rol de un Pokémon que
    se queda en el PC sigue sin writer en B2/W2 y no debe pasar.
    """
    ui = SimpleNamespace(_active_azahar_realtime_key=lambda: "b2w2")
    change = PendingPCRoleChange(
        box=0, box_slot=0, pokemon="Tepig", species="Tepig",
        pokemon_identity="1:2:3:4", old_role="SIN ROL", new_role="Mago",
    )
    assert RoleRunManager._oras_live_unsupported_changes(ui, [change]) == [
        "roles del PC",
    ]


def test_un_cambio_de_rol_llega_a_la_auto_aplicacion() -> None:
    rol = PendingRoleChange(0, "Tepig", "Tepig", "SIN ROL", "Mago")
    manager = SimpleNamespace(
        _active_azahar_realtime_key=lambda: "b2w2",
        run=SimpleNamespace(pending_changes=[rol]),
        _oras_live_auto_apply_available=lambda: True,
        _oras_live_auto_apply_ids=set(),
        _schedule_oras_live_auto_apply=lambda *args, **kwargs: None,
        save_engine=SimpleNamespace(key="b2w2"),
    )

    RoleRunManager._request_oras_live_auto_apply(manager, [rol])

    assert manager._oras_live_auto_apply_ids == {id(rol)}
