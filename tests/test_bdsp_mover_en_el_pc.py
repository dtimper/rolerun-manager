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


# ---------------------------------------------------------------------------
# El vacío del JUEGO no es el vacío que escribe RoleRun (06-09-2026).
#
# Medido sobre el PC real del usuario, 1.200 huecos: 11 ocupados, 1.189
# vacíos. De esos, **1.185 no coinciden byte a byte con el vacío canónico**.
# La diferencia está entera en los 16 bytes de cola (el espejo de stats de
# party, que no describe al Pokémon): el juego los deja con un residuo
# constante y RoleRun escribe ceros. Los 328 bytes del Pokémon están a cero
# en los 1.189.
#
# Exigir los 344 idénticos rechazaba casi todo el PC: mover a otra caja
# fallaba siempre, y solo funcionaba sobre los huecos que RoleRun misma
# había vaciado antes.
# ---------------------------------------------------------------------------

# Cola exacta observada en los 1.185 huecos vacíos del juego (bytes 328..343).
COLA_DEL_JUEGO = bytes.fromhex("00007ee97152b031428ecce2c5afdb67")


def _vacio_del_juego() -> bytes:
    """El vacío tal y como lo deja Perla Reluciente, no RoleRun."""
    from app.bdsp_live import PB8_STORED_SIZE

    return encrypt_pb8(bytes(PB8_STORED_SIZE) + COLA_DEL_JUEGO)


def test_el_vacio_del_juego_no_es_el_canonico_pero_es_igual_de_vacio() -> None:
    canonico = encrypt_pb8(bytes(PB8_PARTY_SIZE))
    del_juego = _vacio_del_juego()

    assert del_juego != canonico, "si fueran iguales, esta prueba no probaría nada"
    # Los dos son «sin Pokémon» para el parser de producción.
    assert parse_bdsp_box_pokemon(canonico, box=1, slot=3) is None
    assert parse_bdsp_box_pokemon(del_juego, box=1, slot=3) is None
    # Y los dos están limpios en los 328 bytes que sí describen al Pokémon.
    assert BDSPLiveWriter._box_slot_is_clean_empty(canonico) is True
    assert BDSPLiveWriter._box_slot_is_clean_empty(del_juego) is True


def test_se_puede_mover_a_un_hueco_vacio_del_juego() -> None:
    """El bug que reportó el usuario: «no se puede cambiar de caja al Pokémon».

    Con el check viejo -344 bytes idénticos al canónico- esto fallaba con «El
    hueco de destino no contiene el vacío canónico demostrado» en 1.185 de los
    1.189 huecos libres de su PC.
    """
    cliente, transporte, escritor, movido, _vacio = _escenario()
    cliente.segments[cliente.destino_data] = bytearray(_vacio_del_juego())

    recibo = escritor.apply([_cambio()])

    assert bytes(cliente.read_memory(cliente.destino_data, PB8_PARTY_SIZE)) == movido
    assert recibo.applied_count == 1


def test_un_hueco_con_restos_de_un_pokemon_anterior_se_niega() -> None:
    """La garantía que sí importa: los 328 bytes del Pokémon, a cero.

    Un hueco con `species == 0` pero con residuo en el bloque guardado no es
    un vacío limpio y se sigue rechazando, aunque el parser lo lea como vacío.
    """
    from app.bdsp_live import PB8_STORED_SIZE, pb8_checksum

    plano = bytearray(PB8_PARTY_SIZE)
    plano[0x20] = 0x42          # residuo dentro del bloque guardado
    struct_checksum = pb8_checksum(bytes(plano))
    plano[6:8] = int(struct_checksum).to_bytes(2, "little")
    sucio = encrypt_pb8(bytes(plano))
    assert parse_bdsp_box_pokemon(sucio, box=1, slot=3) is None, "el parser lo ve vacío"
    assert BDSPLiveWriter._box_slot_is_clean_empty(sucio) is False

    cliente, transporte, escritor, movido, _vacio = _escenario()
    cliente.segments[cliente.destino_data] = bytearray(sucio)

    with pytest.raises(BDSPLiveError, match="no está limpio"):
        escritor.apply([_cambio()])

    assert transporte.write_calls == 0
    assert bytes(cliente.read_memory(cliente.box_data, PB8_PARTY_SIZE)) == movido


def test_el_rollback_devuelve_el_vacio_REAL_del_destino_no_el_canonico() -> None:
    """Si el rollback restaurase el canónico, «restaurar» cambiaría los bytes.

    Es el fallo que asomó al relajar la precondición: los bytes originales del
    destino son los del juego, no los que RoleRun escribiría.
    """
    cliente, transporte, escritor, _movido, _vacio = _escenario()
    del_juego = _vacio_del_juego()
    cliente.segments[cliente.destino_data] = bytearray(del_juego)
    antes_destino = bytes(cliente.read_memory(cliente.destino_data, PB8_PARTY_SIZE))
    antes_origen = bytes(cliente.read_memory(cliente.box_data, PB8_PARTY_SIZE))

    transporte.fail_on_write = 2      # falla al vaciar el origen

    with pytest.raises(BDSPLiveError):
        escritor.apply([_cambio()])

    # Con dientes: hay que haber PASADO la precondición y escrito el destino,
    # o esto no estaría probando el rollback. Si los bytes originales del
    # destino fueran el canónico en vez de los reales, la precondición habría
    # abortado con CERO escrituras y el resto de la prueba pasaría en falso.
    # (Son 4: las dos de ida más las dos que restaura el rollback.)
    assert transporte.write_calls >= 2
    assert bytes(cliente.read_memory(cliente.destino_data, PB8_PARTY_SIZE)) == antes_destino
    assert bytes(cliente.read_memory(cliente.box_data, PB8_PARTY_SIZE)) == antes_origen
    # Y lo restaurado es el vacío DEL JUEGO, no el que RoleRun escribiría.
    assert antes_destino == del_juego != encrypt_pb8(bytes(PB8_PARTY_SIZE))


# ---------------------------------------------------------------------------
# Intercambio de dos huecos OCUPADOS (05-09-2026, pedido del usuario).
#
# Deja de ser exclusivo de sexta. No hay ninguna escritura nueva: son las dos
# de 344 bytes que `party-to-box` ya hace sobre esta misma matriz, cruzadas.
# Y aquí no interviene ningún vacío canónico, así que ninguna casilla queda
# libre en ningún momento del plan.
# ---------------------------------------------------------------------------

def _escenario_intercambio():
    """Dos Pokémon DISTINTOS, uno en Caja 1 · 11 y otro en Caja 1 · 3."""
    origen = _pb8(
        species=304, pid=0x0BADC0DE, tid=321, sid=654,
        current_hp=18, max_hp=18, level=4,
    )
    destino = _pb8(
        species=147, pid=0x0FEEDBAC, tid=321, sid=654,
        current_hp=22, max_hp=22, level=9,
    )
    cliente = _MutableGuestClient(
        _pb8(species=300, current_hp=17, max_hp=25, level=12), item_id=328, quantity=2,
    )
    cliente.box_pointer_base = 0x90000
    cliente.box_data = 0xA0020
    cliente.destino_data = 0xB0020
    cliente.segments[cliente.box_data] = bytearray(origen)
    cliente.segments[cliente.destino_data] = bytearray(destino)
    transporte = _Transport(cliente)
    escritor = BDSPLiveWriter(
        cliente,
        tm_profile_getter=_profile,
        transport_factory=lambda: transporte,
        battle_reader_factory=_NoBattleReader,
        box_reader_factory=_MoveBoxReader,
    )
    return cliente, transporte, escritor, origen, destino


def _cambio_intercambio(**extra) -> PendingTeamChange:
    campos = dict(
        operation="swap-box-slots", party_slot=0,
        box=ORIGEN[0], box_slot=ORIGEN[1],
        destination_box=DESTINO[0], destination_box_slot=DESTINO[1],
        incoming_pokemon="Pipper", incoming_species="Aron",
        incoming_identity=f"304:{0x0BADC0DE}:321:654",
        outgoing_pokemon="Dratini", outgoing_species="Dratini",
        outgoing_identity=f"147:{0x0FEEDBAC}:321:654",
    )
    campos.update(extra)
    return PendingTeamChange(**campos)


def test_intercambio_cruza_los_dos_pb8_y_ninguno_se_pierde() -> None:
    cliente, transporte, escritor, origen, destino = _escenario_intercambio()

    recibo = escritor.apply([_cambio_intercambio()])

    assert bytes(cliente.read_memory(cliente.destino_data, PB8_PARTY_SIZE)) == origen
    assert bytes(cliente.read_memory(cliente.box_data, PB8_PARTY_SIZE)) == destino
    assert transporte.write_calls == 2, "son dos escrituras, ni una mas"
    assert [len(w.expected) for w in recibo.memory_watches] == [344, 344]
    assert recibo.applied_count == 1


def test_intercambio_no_escribe_ningun_vacio_canonico() -> None:
    """La diferencia real con `move-box-slot`: aquí no hay hueco que liberar."""
    _cliente, _transporte, escritor, origen, destino = _escenario_intercambio()
    vacio = encrypt_pb8(bytes(PB8_PARTY_SIZE))

    recibo = escritor.apply([_cambio_intercambio()])

    escrito = {bytes(w.expected) for w in recibo.memory_watches}
    assert escrito == {origen, destino}
    assert vacio not in escrito


def test_intercambio_con_un_destino_vacio_se_niega_sin_escribir() -> None:
    """Un destino libre es un traslado, no un intercambio."""
    cliente, transporte, escritor, origen, _destino = _escenario_intercambio()
    cliente.segments[cliente.destino_data] = bytearray(
        encrypt_pb8(bytes(PB8_PARTY_SIZE)),
    )

    with pytest.raises(BDSPLiveError, match="destino.*ya no contiene"):
        escritor.apply([_cambio_intercambio()])

    assert transporte.write_calls == 0
    assert bytes(cliente.read_memory(cliente.box_data, PB8_PARTY_SIZE)) == origen


def test_intercambio_exige_las_dos_identidades() -> None:
    _cliente, transporte, escritor, _origen, _destino = _escenario_intercambio()

    with pytest.raises(BDSPLiveError, match="identidad de los DOS"):
        escritor.apply([_cambio_intercambio(outgoing_identity=None)])

    assert transporte.write_calls == 0


def test_intercambio_si_el_destino_ya_no_es_ese_pokemon_no_se_escribe() -> None:
    """Las dos casillas son ancla: si una cambió, se aborta antes de escribir."""
    _cliente, transporte, escritor, _origen, _destino = _escenario_intercambio()

    with pytest.raises(BDSPLiveError, match="destino.*no coincide con la selección"):
        escritor.apply([_cambio_intercambio(outgoing_identity="999:1:2:3")])

    assert transporte.write_calls == 0


def test_intercambio_en_combate_no_se_reorganiza_el_pc() -> None:
    cliente, transporte, _escritor, _origen, _destino = _escenario_intercambio()

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
        escritor.apply([_cambio_intercambio()])

    assert transporte.write_calls == 0


def test_el_intercambio_llega_al_writer_correcto() -> None:
    import inspect

    fuente = inspect.getsource(BDSPLiveWriter.apply)

    assert 'if supported[0].operation == "swap-box-slots":' in fuente
    assert "self._apply_box_swap(supported[0])" in fuente


def test_el_intercambio_tambien_usa_la_party_como_testigo() -> None:
    import inspect

    fuente = inspect.getsource(BDSPLiveWriter._apply_box_swap)

    assert "_same_party(second_party, verified_party)" in fuente
    assert "_box_unchanged_except(" in fuente
    assert "{origen_pos, destino_pos}" in fuente
