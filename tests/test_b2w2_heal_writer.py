"""Writer de curación de B2/W2.

Curar en RoleRun es lo que hace un Centro Pokémon: PS al máximo, estado alterado
a cero y PP de los cuatro movimientos al tope, contando los Más PP aplicados.

El PP base **no** se toma de la tabla de sexta generación que ya existía en el
proyecto: varios movimientos cambiaron de PP entre generaciones y darlos por
equivalentes sería una analogía no demostrada. Se extrae de la propia
PKHeX.Core que usa el motor de guardados, con
``MoveInfo.GetPPTable(EntityContext.Gen5)``, mediante
``tools_extract_gen5_move_pp``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.b2w2_live import B2W2LiveError, parse_pk5_party, pk5_party_healed  # noqa: E402
from app.models import PendingPartyHeal  # noqa: E402
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


def _base_pp(move_id: int) -> int:
    return int(TABLA_PP.get(str(int(move_id)), 0))


# --------------------------------------------------------------------------
# La tabla de PP
# --------------------------------------------------------------------------

def test_la_tabla_cubre_exactamente_los_movimientos_de_quinta() -> None:
    """Quinta generación llega hasta el movimiento 559."""
    ids = {int(clave) for clave in TABLA_PP}
    assert min(ids) == 1
    assert max(ids) == 559
    assert len(ids) == 559


def test_la_tabla_declara_de_donde_sale() -> None:
    documento = json.loads(
        (RAIZ / "data" / "b2w2_move_pp.json").read_text(encoding="utf-8-sig")
    )
    assert documento["version"] == "b2w2-gen5"
    assert "PKHeX.Core" in documento["source"]
    assert "Gen5" in documento["source"]


def test_no_se_reutiliza_la_tabla_de_sexta_generacion() -> None:
    """Si fueran idénticas, la tabla propia no aportaría nada y sobraría."""
    sexta = json.loads(
        (RAIZ / "data" / "oras_move_pp.json").read_text(encoding="utf-8-sig")
    )["pp"]
    diferencias = [
        clave for clave in TABLA_PP
        if clave in sexta and int(sexta[clave]) != int(TABLA_PP[clave])
    ]
    assert diferencias, "no habría motivo para mantener una tabla Gen 5 aparte"


@pytest.mark.parametrize(
    ("move_id", "pp"), [(33, 35), (52, 25), (84, 30), (165, 1)],
)
def test_valores_contrastables_de_la_tabla(move_id: int, pp: int) -> None:
    """Placaje, Ascuas, Impactrueno y Forcejeo, que el fixture ya usaba."""
    assert _base_pp(move_id) == pp


# --------------------------------------------------------------------------
# La curación del bloque
# --------------------------------------------------------------------------

def test_curar_deja_ps_al_maximo_estado_limpio_y_pp_al_tope() -> None:
    herido = _pk5_fixture(current_hp=3, runtime_status=1)   # 1 = parálisis
    antes = parse_pk5_party(herido, 0)
    assert (antes.current_hp, antes.status_condition) == (3, 64)

    curado = parse_pk5_party(pk5_party_healed(herido, base_pp_for=_base_pp), 0)

    assert curado.current_hp == curado.max_hp
    assert curado.status_condition == 0
    esperado = tuple(
        (_base_pp(move) * (5 + ups) // 5) if move else 0
        for move, ups in zip(antes.move_ids, antes.move_pp_ups)
    )
    assert curado.move_pp == esperado


def test_los_mas_pp_se_tienen_en_cuenta() -> None:
    """Placaje son 35 PP base; con un Más PP, 42. Con dos Más PP, Ascuas 25 -> 35."""
    curado = parse_pk5_party(
        pk5_party_healed(_pk5_fixture(current_hp=1), base_pp_for=_base_pp), 0,
    )
    assert curado.move_pp_ups == (1, 0, 2, 0)
    assert curado.move_pp[0] == 42
    assert curado.move_pp[2] == 35


def test_curar_no_toca_nada_mas_del_pokemon() -> None:
    antes = parse_pk5_party(_pk5_fixture(current_hp=3), 0)
    curado = parse_pk5_party(
        pk5_party_healed(_pk5_fixture(current_hp=3), base_pp_for=_base_pp), 0,
    )
    assert (curado.pid, curado.tid, curado.sid) == (antes.pid, antes.tid, antes.sid)
    assert curado.species_id == antes.species_id
    assert curado.nickname == antes.nickname
    assert curado.level == antes.level
    assert curado.evs == antes.evs and curado.ivs == antes.ivs
    assert curado.move_ids == antes.move_ids
    assert curado.markings == antes.markings
    assert curado.max_hp == antes.max_hp


def test_un_pp_desconocido_detiene_la_curacion() -> None:
    """Antes que inventar un PP, no se cura: es la partida del usuario."""
    with pytest.raises(B2W2LiveError, match="PP máximo"):
        pk5_party_healed(_pk5_fixture(), base_pp_for=lambda move_id: 0)


def test_un_hueco_de_movimiento_queda_con_cero_pp() -> None:
    curado = parse_pk5_party(
        pk5_party_healed(_pk5_fixture(), base_pp_for=_base_pp), 0,
    )
    assert curado.move_ids[3] == 0
    assert curado.move_pp[3] == 0


# --------------------------------------------------------------------------
# El writer transaccional
# --------------------------------------------------------------------------

def _reader(*, current_hp: int = 3, runtime_status: int = 1) -> _FakeMelonDS:
    return _FakeMelonDS(
        2,
        _pk5_fixture(current_hp=current_hp, runtime_status=runtime_status)
        + _pk5_fixture(pid=5 << 13, current_hp=current_hp),
        _pc_matrix_fixture(),
    )


def _identidad(miembro):
    return (miembro.pid, miembro.tid, miembro.sid)


def test_el_writer_cura_y_verifica() -> None:
    reader = _reader()
    party = reader.read_party()

    despues = reader.write_party_heal(
        party,
        [(indice, _identidad(miembro)) for indice, miembro in enumerate(party.pokemon)],
        base_pp_for=_base_pp,
    )

    for miembro in despues.pokemon:
        assert miembro.current_hp == miembro.max_hp
        assert miembro.status_condition == 0


def test_curar_a_quien_ya_esta_curado_no_escribe_ni_un_byte() -> None:
    reader = _reader(current_hp=26, runtime_status=0)
    party = reader.read_party()
    # Primero se cura de verdad para dejar los PP al tope.
    reader.write_party_heal(party, [(0, _identidad(party.pokemon[0]))], base_pp_for=_base_pp)

    ya_curado = reader.read_party()
    antes = bytes(reader.party_raw)
    escrituras = []
    original = reader._write_process_bytes
    reader._write_process_bytes = lambda *args: escrituras.append(args) or original(*args)

    reader.write_party_heal(
        ya_curado, [(0, _identidad(ya_curado.pokemon[0]))], base_pp_for=_base_pp,
    )

    assert escrituras == []
    assert bytes(reader.party_raw) == antes


def test_el_writer_hace_rollback_si_la_identidad_cambio() -> None:
    reader = _reader()
    party = reader.read_party()
    antes = bytes(reader.party_raw)

    with pytest.raises(B2W2LiveError, match="identidad"):
        reader.write_party_heal(party, [(0, (0xDEADBEEF, 1, 2))], base_pp_for=_base_pp)

    assert bytes(reader.party_raw) == antes


def test_el_writer_rechaza_dos_curaciones_del_mismo_slot() -> None:
    reader = _reader()
    party = reader.read_party()
    identidad = _identidad(party.pokemon[0])

    with pytest.raises(B2W2LiveError, match="mismo slot"):
        reader.write_party_heal(
            party, [(0, identidad), (0, identidad)], base_pp_for=_base_pp,
        )


def test_el_writer_rechaza_un_slot_fuera_de_la_party() -> None:
    reader = _reader()
    party = reader.read_party()

    with pytest.raises(B2W2LiveError, match="fuera de rango"):
        reader.write_party_heal(party, [(5, (1, 2, 3))], base_pp_for=_base_pp)


def test_el_writer_hace_rollback_si_el_readback_no_cuadra() -> None:
    reader = _reader()
    party = reader.read_party()
    antes = bytes(reader.party_raw)

    original = reader._write_process_bytes
    llamadas = {"n": 0}

    def escritura_que_se_pierde(process_id, host_address, payload):
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            return
        original(process_id, host_address, payload)

    reader._write_process_bytes = escritura_que_se_pierde

    with pytest.raises(B2W2LiveError, match="readback"):
        reader.write_party_heal(
            party, [(0, _identidad(party.pokemon[0]))], base_pp_for=_base_pp,
        )

    assert bytes(reader.party_raw) == antes


# --------------------------------------------------------------------------
# El adaptador
# --------------------------------------------------------------------------

def test_el_adaptador_carga_los_pp_de_quinta() -> None:
    adapter = B2W2RealTimeAdapter(reader=_reader())
    assert adapter.base_pp_for(33) == 35
    assert adapter.base_pp_for(52) == 25
    assert adapter.base_pp_for(9999) == 0, "un id desconocido no puede inventarse un PP"


def test_el_adaptador_localiza_al_objetivo_por_identidad_fuerte() -> None:
    adapter = B2W2RealTimeAdapter(reader=_reader())
    party = adapter.reader.read_party()
    miembro = party.pokemon[1]
    identidad = f"{miembro.species_id}:{miembro.pid}:{miembro.tid}:{miembro.sid}"

    slot, fuerte = adapter._heal_target_for(party, PendingPartyHeal(
        pokemon_slot=0, pokemon="Tepig", species="Tepig", pokemon_identity=identidad,
    ))

    assert slot == 1
    assert fuerte == _identidad(miembro)


def test_una_identidad_ausente_no_cura_a_nadie() -> None:
    adapter = B2W2RealTimeAdapter(reader=_reader())
    party = adapter.reader.read_party()

    with pytest.raises(B2W2LiveError, match="forma única"):
        adapter._heal_target_for(party, PendingPartyHeal(
            pokemon_slot=0, pokemon="Fantasma", species="Fantasma",
            pokemon_identity="1:2:3:4",
        ))
