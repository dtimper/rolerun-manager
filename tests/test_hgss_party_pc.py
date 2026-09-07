"""Equipo ↔ PC en HeartGold.

Todo esto puede dejar una Run inservible, así que lo que se comprueba no es solo
que funcione: es que **no escriba nada** cuando algo no cuadra, y que lo deshaga
entero cuando falla a mitad.

Dos cosas medidas sobre la partida real del usuario y que aquí se dan por
sentadas:

* Un hueco vacío del PC **no son 136 ceros**: es un PK4 cifrado con semilla cero.
  Se comprobó sobre los 539 huecos vacíos de su PC. Escribir ceros haría que el
  readback de este mismo writer los rechazara por checksum.
* El contador del equipo se escribe **el último**. Mientras el equipo nuevo no
  esté entero en memoria, el juego no debe verlo declarado.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.gen4_memory import (  # noqa: E402
    GEN4_MEMORY, PC_BOX_COUNT, PC_BOX_SLOT_COUNT, PC_BOX_STRIDE,
)
from app.hgss_live import (  # noqa: E402
    PC_MATRIX_SIZE, HgssLiveError, HgssPartyRead, HgssPCRead,
    parse_party_block, parse_pc_matrix,
)
from app.hgss_write import HgssMelonDSWriter  # noqa: E402
from app.pk4 import (  # noqa: E402
    PK4_PARTY_SIZE, PK4_STORED_SIZE, empty_pk4_stored, parse_pk4_boxed,
    parse_pk4_party, pk4_party_block,
)

_CASOS = json.loads(
    (Path(__file__).resolve().parent / "data" / "pk4_cases.json").read_text(encoding="utf-8")
)["cases"]
HGSS = GEN4_MEMORY["hgss"]


def _del_reves(bloque: bytes) -> bytes:
    """La misma ficha guardada al revés: cifrada si estaba en claro, y al revés.

    Es lo que hace el juego solo, muchas veces por segundo. Cambia los 236 bytes
    enteros y no cambia ni un dato del Pokémon.
    """
    from app.pk4 import PK4_STORED_SIZE, _con_extension, _extension, unshuffle_pk4

    pid, orden, canonico, cifrado = unshuffle_pk4(bloque[:PK4_STORED_SIZE])
    return _con_extension(
        canonico, orden, pid, not cifrado, _extension(bloque, pid, cifrado),
    )


def _hueco(box: int, box_slot: int) -> int:
    return (box - 1) * PC_BOX_STRIDE + (box_slot - 1) * PK4_STORED_SIZE


class _Emulador:
    """Equipo y PC en dos búferes, con la memoria estropeable a voluntad."""

    def __init__(self, miembros: int = 3, guardados=((0, 1, 1, 10),)) -> None:
        self.memory = HGSS
        self.block_is_live = True
        self.process_id = 4242
        self.count = miembros
        self.party = bytearray(
            b"".join(bytes.fromhex(_CASOS[i]["party_hex"]) for i in range(miembros))
        )
        # Cada caja mide 0x1000 y solo 30 x 136 son huecos: el resto es relleno.
        self.pc = bytearray(PC_MATRIX_SIZE)
        for caja in range(PC_BOX_COUNT):
            for hueco in range(PC_BOX_SLOT_COUNT):
                desde = caja * PC_BOX_STRIDE + hueco * PK4_STORED_SIZE
                self.pc[desde:desde + PK4_STORED_SIZE] = empty_pk4_stored()
        for caso, box, box_slot, _n in guardados:
            desde = _hueco(box, box_slot)
            self.pc[desde:desde + PK4_STORED_SIZE] = bytes.fromhex(_CASOS[caso]["boxed_hex"])
        self.party_original = bytes(self.party)
        self.pc_original = bytes(self.pc)
        self.escrituras: list[tuple[int, int]] = []
        # Qué hueco alterna entre cifrado y en claro en cada lectura, como hacen
        # las fichas de verdad: medido, 7 de 25 pares de lecturas seguidas del
        # equipo dan bytes distintos y 0 dan contenido distinto.
        self.parpadea: int | None = None
        # 06-09-2026: simula una lectura pillada a medias en un hueco que NO
        # tiene nada que ver con la operación -exactamente lo que le pasó a
        # Rattata al enviar OTRO Pokémon al PC-. En esas llamadas concretas,
        # ese hueco devuelve otro Pokémon válido (mismo formato, nivel y
        # estado distintos), sin tocar `self.party`.
        self.llamadas_a_read_party = 0
        self.nivel_torcido_en_llamadas: set[int] = set()
        self.nivel_torcido_hueco: int = 0

    def read_party(self) -> HgssPartyRead:
        self.llamadas_a_read_party += 1
        if self.parpadea is not None:
            desde = self.parpadea * PK4_PARTY_SIZE
            self.party[desde:desde + PK4_PARTY_SIZE] = _del_reves(
                bytes(self.party[desde:desde + PK4_PARTY_SIZE]),
            )
        crudo = bytearray(self.party[:self.count * PK4_PARTY_SIZE])
        if self.llamadas_a_read_party in self.nivel_torcido_en_llamadas:
            desde = self.nivel_torcido_hueco * PK4_PARTY_SIZE
            crudo[desde:desde + PK4_PARTY_SIZE] = bytes.fromhex(_CASOS[2]["party_hex"])
        crudo = bytes(crudo)
        return HgssPartyRead(
            self.process_id, "melonDS.exe", 0, self.count, crudo,
            parse_party_block(crudo, self.count),
        )

    def read_pc(self, party_read=None) -> HgssPCRead:
        crudo = bytes(self.pc)
        vacios, dentro = parse_pc_matrix(crudo)
        return HgssPCRead(
            self.process_id, "melonDS.exe", 0, HGSS.pc, crudo, vacios, dentro,
        )


class _Writer(HgssMelonDSWriter):
    def __init__(self, emulador: _Emulador, *, rompe_pc: bool = False) -> None:
        # Los tests no esperan de verdad la segunda verificación (06-09-2026).
        super().__init__(reader=emulador, segunda_verificacion_espera=0.0)
        self.emulador = emulador
        self.rompe_pc = rompe_pc

    def _write_process_bytes(self, process_id, host_address, payload) -> None:
        emu = self.emulador
        self.emulador.escrituras.append((host_address, len(payload)))
        base_equipo = HGSS.party_data - 0x02000000
        base_contador = HGSS.party_count - 0x02000000
        base_pc = HGSS.pc - 0x02000000
        if host_address == base_contador:
            emu.count = payload[0]
        elif host_address == base_equipo:
            emu.party[:len(payload)] = payload
        elif base_pc <= host_address < base_pc + PC_MATRIX_SIZE:
            desde = host_address - base_pc
            if self.rompe_pc and payload != emu.pc_original[desde:desde + len(payload)]:
                return          # la escritura no llega
            emu.pc[desde:desde + len(payload)] = payload
        else:
            raise AssertionError(f"escritura fuera de sitio: 0x{host_address:X}")


def _identidad(pokemon) -> tuple[int, int, int]:
    return (pokemon.pid, pokemon.tid, pokemon.sid)


def _bloque_de_combate(guardado: bytes) -> bytes:
    leido = parse_pk4_boxed(guardado, 0)
    return pk4_party_block(
        guardado, pid=leido.pid, level=25, stats=(60, 50, 40, 30, 20, 10),
    )


# --------------------------------------------------------------------------
# Dentro del PC
# --------------------------------------------------------------------------

def test_mover_dentro_del_pc_deja_el_origen_vacio_de_verdad() -> None:
    emu = _Emulador()
    writer = _Writer(emu)
    quien = parse_pk4_boxed(bytes(emu.pc[_hueco(1, 1):_hueco(1, 1) + PK4_STORED_SIZE]), 0)

    _equipo, pc = writer.move_pc_slot(
        emu.read_party(), (1, 1), (2, 5), expected_identity=_identidad(quien),
    )
    origen = bytes(emu.pc[_hueco(1, 1):_hueco(1, 1) + PK4_STORED_SIZE])
    # No son 136 ceros: es la forma que deja el juego.
    assert origen == empty_pk4_stored()
    assert parse_pk4_boxed(origen, 0) is None
    llegado = parse_pk4_boxed(
        bytes(emu.pc[_hueco(2, 5):_hueco(2, 5) + PK4_STORED_SIZE]), 0,
    )
    assert _identidad(llegado) == _identidad(quien)


def test_no_se_mueve_a_un_hueco_ocupado() -> None:
    emu = _Emulador(guardados=((0, 1, 1, 10), (1, 2, 5, 10)))
    writer = _Writer(emu)
    quien = parse_pk4_boxed(bytes(emu.pc[_hueco(1, 1):_hueco(1, 1) + PK4_STORED_SIZE]), 0)

    with pytest.raises(HgssLiveError, match="ya está ocupado"):
        writer.move_pc_slot(
            emu.read_party(), (1, 1), (2, 5), expected_identity=_identidad(quien),
        )
    assert emu.escrituras == []


def test_una_caja_fuera_de_rango_se_rechaza() -> None:
    emu = _Emulador()
    writer = _Writer(emu)
    with pytest.raises(HgssLiveError, match="caja del PC"):
        writer.move_pc_slot(
            emu.read_party(), (0, 1), (2, 1), expected_identity=(1, 2, 3),
        )
    with pytest.raises(HgssLiveError, match="hueco del PC"):
        writer.move_pc_slot(
            emu.read_party(), (1, 31), (2, 1), expected_identity=(1, 2, 3),
        )


def test_intercambiar_dos_huecos_ocupados_cruza_los_dos_pk4() -> None:
    """05-09-2026, pedido del usuario: el intercambio deja de ser de sexta.

    `move_pc_slot` exige el destino libre y deja el vacío cifrado en el origen.
    Aquí no interviene ningún vacío: son los mismos dos bloques de 136 bytes,
    cruzados, con las dos identidades como ancla.
    """
    emu = _Emulador(guardados=((0, 1, 1, 10), (1, 2, 5, 10)))
    writer = _Writer(emu)
    uno = parse_pk4_boxed(bytes(emu.pc[_hueco(1, 1):_hueco(1, 1) + PK4_STORED_SIZE]), 0)
    otro = parse_pk4_boxed(bytes(emu.pc[_hueco(2, 5):_hueco(2, 5) + PK4_STORED_SIZE]), 0)
    assert _identidad(uno) != _identidad(otro)

    _equipo, _pc = writer.swap_pc_slots(
        emu.read_party(), (1, 1), (2, 5),
        source_identity=_identidad(uno), destination_identity=_identidad(otro),
    )

    quedo = parse_pk4_boxed(bytes(emu.pc[_hueco(1, 1):_hueco(1, 1) + PK4_STORED_SIZE]), 0)
    llego = parse_pk4_boxed(bytes(emu.pc[_hueco(2, 5):_hueco(2, 5) + PK4_STORED_SIZE]), 0)
    assert _identidad(quedo) == _identidad(otro)
    assert _identidad(llego) == _identidad(uno)
    # Ninguna casilla pasa por el vacío en ningún momento.
    assert quedo is not None and llego is not None


def test_no_se_intercambia_con_un_hueco_vacio() -> None:
    """Un destino libre es un traslado (`move_pc_slot`), no un intercambio."""
    emu = _Emulador()
    writer = _Writer(emu)
    quien = parse_pk4_boxed(bytes(emu.pc[_hueco(1, 1):_hueco(1, 1) + PK4_STORED_SIZE]), 0)

    with pytest.raises(HgssLiveError, match="destino del PC no hay nadie"):
        writer.swap_pc_slots(
            emu.read_party(), (1, 1), (2, 5),
            source_identity=_identidad(quien), destination_identity=(1, 2, 3),
        )
    assert emu.escrituras == []


def test_el_intercambio_rechaza_una_identidad_desfasada_sin_escribir() -> None:
    emu = _Emulador(guardados=((0, 1, 1, 10), (1, 2, 5, 10)))
    writer = _Writer(emu)
    uno = parse_pk4_boxed(bytes(emu.pc[_hueco(1, 1):_hueco(1, 1) + PK4_STORED_SIZE]), 0)

    with pytest.raises(HgssLiveError, match="identidad del Pokémon de destino"):
        writer.swap_pc_slots(
            emu.read_party(), (1, 1), (2, 5),
            source_identity=_identidad(uno), destination_identity=(99, 98, 97),
        )
    assert emu.escrituras == []


def test_el_intercambio_no_admite_el_mismo_pokemon_dos_veces() -> None:
    emu = _Emulador(guardados=((0, 1, 1, 10), (1, 2, 5, 10)))
    writer = _Writer(emu)
    uno = parse_pk4_boxed(bytes(emu.pc[_hueco(1, 1):_hueco(1, 1) + PK4_STORED_SIZE]), 0)

    with pytest.raises(HgssLiveError, match="mismo Pokémon"):
        writer.swap_pc_slots(
            emu.read_party(), (1, 1), (2, 5),
            source_identity=_identidad(uno), destination_identity=_identidad(uno),
        )
    assert emu.escrituras == []


# --------------------------------------------------------------------------
# Depositar y retirar
# --------------------------------------------------------------------------

def test_depositar_encoge_el_equipo_y_compacta() -> None:
    emu = _Emulador(miembros=3, guardados=())
    writer = _Writer(emu)
    antes = emu.read_party()
    saliente = antes.pokemon[1]

    equipo, _pc = writer.resize_party_pc(
        antes, operation="party-to-box", party_slot=1, box=1, box_slot=1,
        expected_identity=_identidad(saliente),
    )
    assert equipo.count == 2
    assert [_identidad(p) for p in equipo.pokemon] == [
        _identidad(antes.pokemon[0]), _identidad(antes.pokemon[2]),
    ]
    guardado = parse_pk4_boxed(bytes(emu.pc[:PK4_STORED_SIZE]), 0)
    assert _identidad(guardado) == _identidad(saliente)


def test_una_ficha_ajena_inestable_impide_depositar() -> None:
    """06-09-2026, corrupción real: enviar OTRO Pokémon al PC dejó a Rattata

    -sin ninguna relación con la operación- mostrando «Envenenado» donde iba
    el nivel. El armazón reescribe el bloque de equipo entero en cada
    operación, así que una lectura inestable en CUALQUIER hueco tiene que
    bloquear la escritura, no solo la del hueco que se declara mover.
    """
    emu = _Emulador(miembros=3, guardados=())
    emu.nivel_torcido_en_llamadas = {2}  # solo la lectura `primera` interna
    emu.nivel_torcido_hueco = 0  # el hueco 0 no tiene nada que ver con el 1
    writer = _Writer(emu)
    antes = emu.read_party()
    saliente = antes.pokemon[1]

    with pytest.raises(HgssLiveError, match="no se estabilizó"):
        writer.resize_party_pc(
            antes, operation="party-to-box", party_slot=1, box=1, box_slot=1,
            expected_identity=_identidad(saliente),
        )
    assert emu.escrituras == []
    assert bytes(emu.party) == emu.party_original


def test_no_se_deja_el_equipo_vacio() -> None:
    emu = _Emulador(miembros=1, guardados=())
    writer = _Writer(emu)
    antes = emu.read_party()
    with pytest.raises(HgssLiveError, match="vacío"):
        writer.resize_party_pc(
            antes, operation="party-to-box", party_slot=0, box=1, box_slot=1,
            expected_identity=_identidad(antes.pokemon[0]),
        )
    assert emu.escrituras == []


def test_retirar_agranda_el_equipo_y_vacia_el_hueco() -> None:
    emu = _Emulador(miembros=3, guardados=((5, 1, 1, 10),))
    writer = _Writer(emu)
    guardado = bytes(emu.pc[:PK4_STORED_SIZE])
    entrante = parse_pk4_boxed(guardado, 0)

    equipo, _pc = writer.resize_party_pc(
        emu.read_party(), operation="box-to-party", party_slot=3, box=1, box_slot=1,
        expected_identity=_identidad(entrante),
        incoming_party=_bloque_de_combate(guardado),
    )
    assert equipo.count == 4
    assert _identidad(equipo.pokemon[3]) == _identidad(entrante)
    assert bytes(emu.pc[:PK4_STORED_SIZE]) == empty_pk4_stored()


def test_un_toque_tardio_del_juego_tras_retirar_se_deshace() -> None:
    """06-09-2026: la segunda verificación que le faltaba a este armazón.

    `_transaccion_de_equipo` ya la tiene desde el incidente de Gastly; esta
    transacción -la que usan mover/depositar/retirar del PC- nunca la tuvo,
    y el cuarto incidente real (Spinarak Huevo malo al retirarlo) pasó
    precisamente aquí. No se ha demostrado que esto sea la causa exacta,
    pero si el juego toca el hueco recién llegado un instante después del
    readback inmediato, ahora se detecta y se deshace en vez de darlo por
    bueno.
    """
    emu = _Emulador(miembros=3, guardados=((5, 1, 1, 10),))
    emu.nivel_torcido_en_llamadas = {6}  # la lectura de la segunda verificación
    emu.nivel_torcido_hueco = 3  # el hueco recién llegado, el cuarto
    writer = _Writer(emu)
    guardado = bytes(emu.pc[:PK4_STORED_SIZE])
    entrante = parse_pk4_boxed(guardado, 0)

    with pytest.raises(HgssLiveError, match="tocó el equipo después de confirmar"):
        writer.resize_party_pc(
            emu.read_party(), operation="box-to-party", party_slot=3, box=1, box_slot=1,
            expected_identity=_identidad(entrante),
            incoming_party=_bloque_de_combate(guardado),
        )
    # Y el rollback dejó la partida exactamente como estaba: el PC con el
    # depositado de vuelta y el equipo con sus tres miembros originales.
    assert bytes(emu.pc[:PK4_STORED_SIZE]) == guardado
    restaurado = emu.read_party()
    assert restaurado.count == 3


def test_no_se_retira_a_un_equipo_lleno() -> None:
    emu = _Emulador(miembros=6, guardados=((6, 1, 1, 10),))
    writer = _Writer(emu)
    guardado = bytes(emu.pc[:PK4_STORED_SIZE])
    entrante = parse_pk4_boxed(guardado, 0)
    with pytest.raises(HgssLiveError, match="lleno"):
        writer.resize_party_pc(
            emu.read_party(), operation="box-to-party", party_slot=6,
            box=1, box_slot=1, expected_identity=_identidad(entrante),
            incoming_party=_bloque_de_combate(guardado),
        )
    assert emu.escrituras == []


def test_una_operacion_desconocida_no_escribe_nada() -> None:
    emu = _Emulador()
    writer = _Writer(emu)
    with pytest.raises(HgssLiveError, match="no está admitida"):
        writer.resize_party_pc(
            emu.read_party(), operation="inventada", party_slot=0,
            box=1, box_slot=2, expected_identity=(1, 2, 3),
        )
    assert emu.escrituras == []


def test_el_contador_se_escribe_el_ultimo() -> None:
    """Con el contador subido antes de tiempo, el juego vería un miembro a medias."""
    emu = _Emulador(miembros=3, guardados=((5, 1, 1, 10),))
    writer = _Writer(emu)
    guardado = bytes(emu.pc[:PK4_STORED_SIZE])
    entrante = parse_pk4_boxed(guardado, 0)
    writer.resize_party_pc(
        emu.read_party(), operation="box-to-party", party_slot=3, box=1, box_slot=1,
        expected_identity=_identidad(entrante),
        incoming_party=_bloque_de_combate(guardado),
    )
    base_contador = HGSS.party_count - 0x02000000
    direcciones = [direccion for direccion, _n in emu.escrituras]
    assert direcciones.index(base_contador) == len(direcciones) - 1


# --------------------------------------------------------------------------
# Intercambio y sustitución
# --------------------------------------------------------------------------

def test_el_intercambio_no_cambia_el_tamano_del_equipo() -> None:
    emu = _Emulador(miembros=3, guardados=((5, 1, 1, 10),))
    writer = _Writer(emu)
    antes = emu.read_party()
    saliente = antes.pokemon[1]
    guardado = bytes(emu.pc[:PK4_STORED_SIZE])
    entrante = parse_pk4_boxed(guardado, 0)

    equipo, _pc = writer.swap_party_box(
        antes, party_slot=1, box=1, box_slot=1,
        outgoing_identity=_identidad(saliente),
        incoming_identity=_identidad(entrante),
        incoming_party=_bloque_de_combate(guardado),
    )
    assert equipo.count == 3
    assert _identidad(equipo.pokemon[1]) == _identidad(entrante)
    quedo = parse_pk4_boxed(bytes(emu.pc[:PK4_STORED_SIZE]), 0)
    assert _identidad(quedo) == _identidad(saliente)


def test_no_se_sustituye_a_quien_no_esta_debilitado() -> None:
    """La Run cuenta las bajas: sustituir a alguien vivo sería falsear una."""
    emu = _Emulador(miembros=3, guardados=((5, 1, 1, 10), (4, 18, 30, 10)))
    writer = _Writer(emu)
    antes = emu.read_party()
    guardado = bytes(emu.pc[:PK4_STORED_SIZE])
    entrante = parse_pk4_boxed(guardado, 0)
    assert antes.pokemon[0].current_hp > 0

    with pytest.raises(HgssLiveError, match="no está debilitado"):
        writer.replace_fainted_party_pc(
            antes, party_slot=0, box=1, box_slot=1,
            graveyard_box=2, graveyard_box_slot=1,
            incoming_party=_bloque_de_combate(guardado),
            outgoing_identity=_identidad(antes.pokemon[0]),
            incoming_identity=_identidad(entrante),
        )
    assert emu.escrituras == []


def test_el_sustituto_y_el_cementerio_no_pueden_ser_el_mismo_hueco() -> None:
    emu = _Emulador()
    writer = _Writer(emu)
    with pytest.raises(HgssLiveError, match="comparten hueco"):
        writer.replace_fainted_party_pc(
            emu.read_party(), party_slot=0, box=1, box_slot=1,
            graveyard_box=1, graveyard_box_slot=1, incoming_party=b"",
            outgoing_identity=(1, 2, 3), incoming_identity=(4, 5, 6),
        )


# --------------------------------------------------------------------------
# Rollback
# --------------------------------------------------------------------------

def test_si_el_pc_no_recibe_la_escritura_se_deshace_todo() -> None:
    emu = _Emulador(miembros=3, guardados=())
    writer = _Writer(emu, rompe_pc=True)
    antes = emu.read_party()
    saliente = antes.pokemon[1]

    with pytest.raises(HgssLiveError):
        writer.resize_party_pc(
            antes, operation="party-to-box", party_slot=1, box=1, box_slot=1,
            expected_identity=_identidad(saliente),
        )
    # Ni el equipo ni el contador ni el PC quedaron a medias.
    assert emu.count == 3
    assert bytes(emu.party) == emu.party_original
    assert bytes(emu.pc) == emu.pc_original


# --------------------------------------------------------------------------
# Que el cambio llegue a salir de la interfaz
# --------------------------------------------------------------------------

def test_preparar_un_cambio_equipo_pc_lo_envia_al_emulador() -> None:
    """Preparar no es aplicar, y la pantalla decía «APLICANDO CAMBIO».

    El cambio se creaba, se pintaba en el equipo proyectado y **nadie lo enviaba
    nunca**: se quedaba en la cola. El Pokémon aparecía en el equipo con «PS no
    disponible» y en el juego no estaba. Afectaba a todos los juegos, no solo a
    HeartGold.
    """
    import inspect

    from app.ui import RoleRunManager

    fuente = inspect.getsource(RoleRunManager._team_pc_execute_change)
    assert "_request_oras_live_auto_apply_since(pending_before)" in fuente
    # Y va después de crear los cambios, no antes.
    assert fuente.index("pending_before = {") < fuente.index(
        "_request_oras_live_auto_apply_since(pending_before)"
    )


def test_equipo_al_pc_con_una_ficha_parpadeando() -> None:
    """El mismo fallo que dejaba la curación sin hacer, en Equipo↔PC.

    Cada ficha alterna entre cifrada y en claro por su cuenta -medido: 7 de 25
    pares de lecturas seguidas dan bytes distintos, 0 dan contenido distinto-.
    Comparar los bytes del equipo hacía fallar la operación sin que pasara nada.
    """
    emu = _Emulador(miembros=3, guardados=())
    writer = _Writer(emu)
    antes = emu.read_party()
    saliente = antes.pokemon[1]
    emu.parpadea = 0            # una ficha que ni se mueve, cambiando de estado

    equipo, _pc = writer.resize_party_pc(
        antes, operation="party-to-box", party_slot=1, box=1, box_slot=1,
        expected_identity=_identidad(saliente),
    )

    assert equipo.count == 2
    guardado = parse_pk4_boxed(bytes(emu.pc[:PK4_STORED_SIZE]), 0)
    assert _identidad(guardado) == _identidad(saliente)


def test_ningun_camino_compara_los_bytes_del_equipo() -> None:
    """La regresión que costó tres «Huevo malo» y una tarde entera.

    Los bytes del equipo no valen como criterio: cada ficha parpadea entre
    cifrada y en claro sin que la partida cambie -medido: 7 de 25 pares de
    lecturas seguidas dan bytes distintos, 0 dan contenido distinto-. Lo que
    distingue una copia del bloque de otra es su dirección, que sí se exige.

    El PC y la mochila **sí** son estables -1 contenido en 12 lecturas- y se
    siguen comparando byte a byte: por eso esta prueba solo mira el equipo.
    """
    from pathlib import Path

    fuente = (
        Path(__file__).resolve().parent.parent / "app" / "hgss_write.py"
    ).read_text(encoding="utf-8")

    del_equipo = ("read_party()", "antes.raw", "antes_equipo.raw",
                  "despues_equipo.raw", "restaurado.raw", "ahora.raw")
    # `antes.raw` también es la mochila en `write_bag_items`, y ahí sí vale.
    de_otros = ("bolsillo", "read_bag", "bolsa", "read_pc", "_pc.raw")
    culpables = [
        linea.strip() for linea in fuente.splitlines()
        if ".raw" in linea and ("!=" in linea or "==" in linea)
        and any(nombre in linea for nombre in del_equipo)
        and not any(nombre in linea for nombre in de_otros)
    ]
    assert not culpables, (
        "vuelve a comparar bytes del equipo: " + " | ".join(culpables)
    )
