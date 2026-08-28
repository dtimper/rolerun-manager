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


def _hueco(box: int, box_slot: int) -> int:
    return (box - 1) * PC_BOX_STRIDE + (box_slot - 1) * PK4_STORED_SIZE


class _Emulador:
    """Equipo y PC en dos búferes, con la memoria estropeable a voluntad."""

    def __init__(self, miembros: int = 3, guardados=((0, 1, 1, 10),)) -> None:
        self.memory = HGSS
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

    def read_party(self) -> HgssPartyRead:
        crudo = bytes(self.party[:self.count * PK4_PARTY_SIZE])
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
        super().__init__(reader=emulador)
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
