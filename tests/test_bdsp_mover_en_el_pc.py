"""Mover un Pokémon de un hueco del PC a otro, en Perla Reluciente.

No es una escritura nueva. Un movimiento dentro del PC son exactamente las dos
que el writer de tamaño ya hace sobre esta misma matriz de 1.200 slots:

===============  ====================================================
`party-to-box`   mete un PB8 completo en un hueco de caja
`box-to-party`   deja el vacío canónico en el hueco que se libera
===============  ====================================================

Aquí se aplican a dos huecos de caja en vez de a uno de caja y uno de party. La
estructura, el tamaño del registro y el vacío canónico son los mismos.

Lo que sigue bloqueado es el **intercambio** entre dos huecos ocupados: eso no
son estas dos escrituras y no está demostrado. El destino tiene que estar vacío.

Y hay una condición que no es obvia: la party **no se toca**, así que su captura
sirve de testigo. Si cambia durante la operación, algo más estaba escribiendo y
hay que abortar.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.bdsp_live import (
    PB8_PARTY_SIZE,
    BDSPBoxRead,
    BDSPBoxStorageSlot,
    BDSPLiveError,
    BDSPLiveWriter,
    encrypt_pb8,
    parse_bdsp_box_pokemon,
)
from app.models import PendingTeamChange
from tests.test_bdsp_live_foundation import _pb8
from tests.test_bdsp_live_write import (
    _MutableGuestClient,
    _NoBattleReader,
    _profile,
    _Transport,
)

ORIGEN = (1, 11)
DESTINO = (1, 3)


class _MoveBoxReader:
    """Matriz completa con dos huecos mutables: el de origen y el de destino."""

    def __init__(self, client: _MutableGuestClient) -> None:
        self.client = client

    def read(self) -> BDSPBoxRead:
        empty = encrypt_pb8(bytes(PB8_PARTY_SIZE))
        crudo = {
            ORIGEN: self.client.read_memory(self.client.box_data, PB8_PARTY_SIZE),
            DESTINO: self.client.read_memory(self.client.destino_data, PB8_PARTY_SIZE),
        }
        direccion = {
            ORIGEN: self.client.box_data,
            DESTINO: self.client.destino_data,
        }
        storage, pokemon = [], []
        for box in range(1, 41):
            for slot in range(1, 31):
                pos = (box, slot)
                raw = crudo.get(pos, empty)
                address = direccion.get(pos, 0x200000 + ((box - 1) * 30 + slot) * 0x200)
                storage.append(BDSPBoxStorageSlot(
                    box=box, slot=slot, data_pointer=address, encrypted=raw,
                ))
                parsed = parse_bdsp_box_pokemon(raw, box=box, slot=slot)
                if parsed is not None:
                    pokemon.append(replace(parsed, data_pointer=address))
        return BDSPBoxRead(
            pokemon=tuple(pokemon), total_slots=1200,
            empty_slots=1200 - len(pokemon),
            pointer_base=self.client.box_pointer_base,
            storage_slots=tuple(storage),
        )


def _escenario(*, destino_ocupado: bool = False):
    """Un Pokémon en Caja 1 · 11 y el destino en Caja 1 · 3."""
    vacio = encrypt_pb8(bytes(PB8_PARTY_SIZE))
    party = _pb8(species=300, current_hp=17, max_hp=25, level=12)
    movido = _pb8(
        species=304, pid=0x0BADC0DE, tid=321, sid=654,
        current_hp=18, max_hp=18, level=4,
    )
    cliente = _MutableGuestClient(party, item_id=328, quantity=2)
    cliente.box_pointer_base = 0x90000
    cliente.box_data = 0xA0020
    cliente.destino_data = 0xB0020
    cliente.segments[cliente.box_data] = bytearray(movido)
    cliente.segments[cliente.destino_data] = bytearray(
        movido if destino_ocupado else vacio,
    )
    transporte = _Transport(cliente)
    escritor = BDSPLiveWriter(
        cliente,
        tm_profile_getter=_profile,
        transport_factory=lambda: transporte,
        battle_reader_factory=_NoBattleReader,
        box_reader_factory=_MoveBoxReader,
    )
    return cliente, transporte, escritor, movido, vacio


def _cambio(**extra) -> PendingTeamChange:
    campos = dict(
        operation="move-box-slot", party_slot=0,
        box=ORIGEN[0], box_slot=ORIGEN[1],
        destination_box=DESTINO[0], destination_box_slot=DESTINO[1],
        incoming_pokemon="Pipper", incoming_species="Aron",
        incoming_identity=f"304:{0x0BADC0DE}:321:654",
    )
    campos.update(extra)
    return PendingTeamChange(**campos)


def test_el_pokemon_llega_al_destino_y_el_origen_queda_vacio() -> None:
    cliente, transporte, escritor, movido, vacio = _escenario()

    recibo = escritor.apply([_cambio()])

    assert bytes(cliente.read_memory(cliente.destino_data, PB8_PARTY_SIZE)) == movido
    assert bytes(cliente.read_memory(cliente.box_data, PB8_PARTY_SIZE)) == vacio
    assert transporte.write_calls == 2, "son dos escrituras, ni una mas"
    assert [len(w.expected) for w in recibo.memory_watches] == [344, 344]
    assert recibo.applied_count == 1


def test_son_las_dos_escrituras_ya_demostradas_y_de_344_bytes() -> None:
    """Meter un PB8 en un hueco y dejar el vacio canonico en otro."""
    _cliente, _transporte, escritor, movido, vacio = _escenario()

    recibo = escritor.apply([_cambio()])

    escrito = {w.address: bytes(w.expected) for w in recibo.memory_watches}
    assert set(escrito.values()) == {movido, vacio}


def test_un_destino_ocupado_se_niega_sin_escribir_nada() -> None:
    """El intercambio entre dos huecos ocupados no esta demostrado."""
    cliente, transporte, escritor, movido, _vacio = _escenario(destino_ocupado=True)

    with pytest.raises(BDSPLiveError, match="destino ya no está vacío"):
        escritor.apply([_cambio()])

    assert transporte.write_calls == 0
    assert bytes(cliente.read_memory(cliente.box_data, PB8_PARTY_SIZE)) == movido


def test_mover_a_su_propio_hueco_no_hace_nada() -> None:
    _cliente, transporte, escritor, _movido, _vacio = _escenario()

    with pytest.raises(BDSPLiveError, match="mismo hueco"):
        escritor.apply([_cambio(
            destination_box=ORIGEN[0], destination_box_slot=ORIGEN[1],
        )])

    assert transporte.write_calls == 0


def test_si_el_origen_ya_no_es_ese_pokemon_no_se_escribe() -> None:
    """La caja pudo cambiar dentro del juego entre elegir y soltar."""
    _cliente, transporte, escritor, _movido, _vacio = _escenario()

    with pytest.raises(BDSPLiveError, match="ya no coincide con la selección"):
        escritor.apply([_cambio(incoming_identity="999:1:2:3")])

    assert transporte.write_calls == 0


def test_un_origen_vacio_se_niega() -> None:
    cliente, transporte, escritor, _movido, vacio = _escenario()
    cliente.segments[cliente.box_data] = bytearray(vacio)

    with pytest.raises(BDSPLiveError, match="origen ya no contiene"):
        escritor.apply([_cambio()])

    assert transporte.write_calls == 0


def test_sin_hueco_de_destino_no_se_intenta() -> None:
    _cliente, transporte, escritor, _movido, _vacio = _escenario()

    with pytest.raises(BDSPLiveError, match="destino"):
        escritor.apply([_cambio(destination_box=None, destination_box_slot=None)])

    assert transporte.write_calls == 0


def test_en_combate_no_se_reorganiza_el_pc() -> None:
    cliente, transporte, _escritor, _movido, _vacio = _escenario()

    class _EnCombate:
        def __init__(self, _cliente) -> None:
            pass

        def read(self):
            return object()

    escritor = BDSPLiveWriter(
        cliente,
        tm_profile_getter=_profile,
        transport_factory=lambda: transporte,
        battle_reader_factory=_EnCombate,
        box_reader_factory=_MoveBoxReader,
    )

    with pytest.raises(BDSPLiveError, match="combate"):
        escritor.apply([_cambio()])

    assert transporte.write_calls == 0


def test_la_operacion_llega_al_writer_correcto() -> None:
    """`apply` reparte por operacion: sin esta rama caeria en el mensaje generico."""
    import inspect

    fuente = inspect.getsource(BDSPLiveWriter.apply)

    assert 'if supported[0].operation == "move-box-slot":' in fuente
    assert "self._apply_box_move(supported[0])" in fuente


def test_la_party_es_testigo_de_que_nadie_mas_escribio() -> None:
    """El movimiento no la toca, asi que si cambia es que algo mas lo hizo."""
    import inspect

    fuente = inspect.getsource(BDSPLiveWriter._apply_box_move)

    assert "_same_party(second_party, verified_party)" in fuente
    assert "La party cambió durante un movimiento que no la toca" in fuente


def test_ningun_otro_hueco_de_caja_puede_cambiar() -> None:
    import inspect

    fuente = inspect.getsource(BDSPLiveWriter._apply_box_move)

    assert "_box_unchanged_except(" in fuente
    assert "{origen_pos, destino_pos}" in fuente
