"""Identidad del rival activo en B2/W2, para la regla del combate de seis.

La primera dirección demostrada (`0x0214701C`, especie+PS máximo, hallada con
una traza de dos estados sobre un solo golpe) resultó ser una coincidencia:
una traza real de seis cambios de rival narrados por el usuario en directo
(patrat, bibarel, lillipup, zangoose, lickitung, smeargle) demostró que esa
dirección solo ciclaba entre cuatro especies ajenas al combate real.

Reemplazada por `0x0226170A`, hallada monitorizando TODA la RAM cada ~1,2 s
durante el combate real, buscando exactamente esas seis especies: una única
dirección las mostró las seis, EN ESE ORDEN, con 3,7-4,9 s entre cada una. A
diferencia de la fila del jugador, aquí no hay PS máximo/actual acompañando a
la especie -fuera de combate los 12 bytes siguientes están a cero mientras la
especie persiste-, así que la identidad del rival en B2/W2 se basa solo en la
especie, sin un segundo campo que distinga individuos repetidos como en X/Y.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.b2w2_live import (  # noqa: E402
    B2W2BattleRead,
    B2W2LiveError,
    B2W2MelonDSReader,
    B2W2PartyRead,
    B2W2Pokemon,
)
from app.gen5_memory import GEN5_MEMORY  # noqa: E402
from app.realtime.b2w2_adapter import B2W2RealTimeAdapter  # noqa: E402
from app.save_engine_client import SaveGameData, SavePokemon  # noqa: E402


# --------------------------------------------------------------------------
# La dirección medida
# --------------------------------------------------------------------------

def test_negro_2_declara_el_carril_del_rival() -> None:
    assert GEN5_MEMORY["b2w2"].battle_opponent_active == 0x0226170A


def test_blanco_negro_tiene_su_propia_direccion_demostrada() -> None:
    """BW comparte lector con B2/W2 pero su dirección es propia, no heredada."""
    assert GEN5_MEMORY["bw"].battle_opponent_active == 0x022A7DCC
    assert GEN5_MEMORY["bw"].battle_opponent_active != GEN5_MEMORY["b2w2"].battle_opponent_active


# --------------------------------------------------------------------------
# El lector aislado
# --------------------------------------------------------------------------

def _lector(direccion=GEN5_MEMORY["b2w2"]) -> tuple[B2W2MelonDSReader, list]:
    reader = B2W2MelonDSReader(direccion)
    llamadas: list[tuple[int, int]] = []

    def leer(lectura, guest, tamano):
        llamadas.append((guest, tamano))
        return struct.pack("<H", 235)

    reader._read_guest_twice = leer
    return reader, llamadas


def test_lee_solo_la_especie_de_la_direccion_demostrada() -> None:
    reader, llamadas = _lector()
    identidad = reader.read_battle_opponent_identity(object())
    assert identidad == (235, 235)
    assert llamadas == [(0x0226170A, 2)]


def test_sin_direccion_demostrada_devuelve_none_sin_leer_nada() -> None:
    from dataclasses import replace

    sin_demostrar = replace(GEN5_MEMORY["bw"], battle_opponent_active=None)
    reader, llamadas = _lector(sin_demostrar)
    assert reader.read_battle_opponent_identity(object()) is None
    assert llamadas == []


def test_blanco_negro_lee_solo_la_especie_de_su_propia_direccion() -> None:
    reader, llamadas = _lector(GEN5_MEMORY["bw"])
    identidad = reader.read_battle_opponent_identity(object())
    assert identidad == (235, 235)
    assert llamadas == [(0x022A7DCC, 2)]


def test_una_especie_implausible_se_descarta() -> None:
    reader = B2W2MelonDSReader(GEN5_MEMORY["b2w2"])
    reader._read_guest_twice = lambda *_: struct.pack("<H", 0)
    assert reader.read_battle_opponent_identity(object()) is None


def test_un_fallo_de_lectura_devuelve_none_en_vez_de_lanzar() -> None:
    """Aislado a propósito: la falta del rival no puede tirar el resto del sondeo."""
    reader = B2W2MelonDSReader(GEN5_MEMORY["b2w2"])

    def leer(*_args):
        raise B2W2LiveError("melonDS desapareció")

    reader._read_guest_twice = leer
    assert reader.read_battle_opponent_identity(object()) is None


def test_la_traza_real_narrada_confirma_la_secuencia() -> None:
    """El orden que el usuario narró en directo, decodificado por especie.

    No es un valor inventado: son los seis nombres reales que reportó tras el
    combate de prueba (patrat, bibarel, lillipup, zangoose, lickitung,
    smeargle), convertidos a su National Dex, en el mismo orden en que la
    monitorización de RAM los capturó en `0x0226170A`.
    """
    orden_narrado = ["patrat", "bibarel", "lillipup", "zangoose", "lickitung", "smeargle"]
    especies = {"patrat": 504, "bibarel": 400, "lillipup": 506,
                "zangoose": 335, "lickitung": 108, "smeargle": 235}
    reader = B2W2MelonDSReader(GEN5_MEMORY["b2w2"])
    secuencia_leida = []
    for nombre in orden_narrado:
        reader._read_guest_twice = lambda *_ , n=nombre: struct.pack("<H", especies[n])
        identidad = reader.read_battle_opponent_identity(object())
        secuencia_leida.append(identidad[0])
    assert secuencia_leida == [504, 400, 506, 335, 108, 235]


def test_bw_la_traza_real_narrada_confirma_la_secuencia() -> None:
    """El orden real narrado en Blanco/Negro: tepig, foongus, hippowdon,
    gulpin, purrloin, togetic. `0x022A7DCC` capturó las cinco últimas -tepig
    ya estaba en el campo antes de arrancar la monitorización- en ese orden
    exacto, con 9-11 s entre cada una."""
    orden_narrado = ["foongus", "hippowdon", "gulpin", "purrloin", "togetic"]
    especies = {"tepig": 498, "foongus": 590, "hippowdon": 450,
                "gulpin": 316, "purrloin": 509, "togetic": 176}
    reader = B2W2MelonDSReader(GEN5_MEMORY["bw"])
    secuencia_leida = []
    for nombre in orden_narrado:
        reader._read_guest_twice = lambda *_ , n=nombre: struct.pack("<H", especies[n])
        identidad = reader.read_battle_opponent_identity(object())
        secuencia_leida.append(identidad[0])
    assert secuencia_leida == [590, 450, 316, 509, 176]


# --------------------------------------------------------------------------
# El paso por el adaptador
# --------------------------------------------------------------------------

def _party_read() -> B2W2PartyRead:
    live = B2W2Pokemon(
        slot=0, pid=0x89E50000, tid=1234, sid=5678,
        species_id=498, form=0, nickname="Tepig", level=7,
        held_item_id=0, ability_id=66, move_ids=(33, 39, 52, 0),
        move_pp=(35, 30, 25, 0), move_pp_ups=(1, 0, 2, 0),
        markings=(True, False, False, False, False, False),
        nature_id=3, is_egg=False, status_condition=0,
        stats=(26, 14, 12, 13, 10, 11),
        ivs=(31, 30, 29, 28, 27, 26), evs=(4, 8, 12, 20, 16, 24),
        current_hp=13, max_hp=26,
    )
    return B2W2PartyRead(
        14896, "melonDS.exe", 0x1B26C190000, 1, b"fixture", (live,),
    )


def _current_game() -> SaveGameData:
    pokemon = SavePokemon(
        slot=0, species_id=498, species="Tepig", nickname="Tepig", level=7,
        held_item="Ninguno", ability="Mar Llamas", moves=["Placaje"],
        move_ids=[33], is_egg=False,
        markings=[True, False, False, False, False, False],
        role="Líbero", role_symbol="•", pid=0x89E50000, tid=1234, sid=5678,
    )
    return SaveGameData("B2W2", "SAV5B2W2", 5, "Tester", [pokemon], {})


def _battle_activa() -> B2W2BattleRead:
    return B2W2BattleRead(
        active=True, party_slot=0, current_hp=13, max_hp=26,
        mirror_hp=13, immediate_hp=13, converged=True, status_condition=0,
    )


def _reader(*, opponent_identity=(235, 235), falla_rival=False):
    party_read = _party_read()

    def read_battle_opponent_identity(self, raw):
        if falla_rival:
            raise B2W2LiveError("carril del rival caído")
        return opponent_identity

    return type("Reader", (), {
        "memory": GEN5_MEMORY["b2w2"],
        "read_party": lambda self: party_read,
        "read_battle_party": lambda self, raw: (_battle_activa(),),
        "read_badges": lambda self, raw: 1,
        "read_battle_opponent_identity": read_battle_opponent_identity,
    })()


def test_la_identidad_del_rival_llega_al_battlestate() -> None:
    snapshot = B2W2RealTimeAdapter(reader=_reader()).capture_full(
        _current_game(), save_path=None,
    )
    assert snapshot.battle.state == "battle"
    assert snapshot.battle.opponent_identity == (235, 235)


def test_un_fallo_al_leer_el_rival_no_rompe_la_deteccion_primaria() -> None:
    """El mismo fallo que rompió BDSP: aislar en su propio try/except."""
    snapshot = B2W2RealTimeAdapter(reader=_reader(falla_rival=True)).capture_full(
        _current_game(), save_path=None,
    )
    assert snapshot.battle.state == "battle"
    assert snapshot.battle.opponent_identity is None
    assert snapshot.game.party[0].current_hp == 13


def test_sin_metodo_de_rival_en_el_lector_tampoco_rompe_nada() -> None:
    """Un lector sin `read_battle_opponent_identity` (p.ej. Blanco/Negro sin
    demostrar todavía) debe seguir publicando el combate con normalidad."""
    party_read = _party_read()
    reader = type("Reader", (), {
        "memory": GEN5_MEMORY["bw"],
        "read_party": lambda self: party_read,
        "read_battle_party": lambda self, raw: (_battle_activa(),),
        "read_badges": lambda self, raw: 1,
    })()
    snapshot = B2W2RealTimeAdapter(reader=reader).capture_full(
        _current_game(), save_path=None,
    )
    assert snapshot.battle.state == "battle"
    assert snapshot.battle.opponent_identity is None


def test_la_llamada_al_rival_esta_aislada_de_la_deteccion_primaria_en_el_codigo() -> None:
    """Regresión BDSP (14-09-2026): meter la sonda en el try/except principal
    rompía la detección cuando el lector no tenía el método nuevo."""
    import inspect

    from app.realtime import b2w2_adapter

    fuente = inspect.getsource(b2w2_adapter.B2W2RealTimeAdapter._capture)
    assert "read_battle_opponent_identity" in fuente
    # La llamada vive dentro del bloque `else:` de batalla activa, no del
    # `try:` que decide si hay combate o no.
    inicio = fuente.index("battle_raw.active")
    llamada = fuente.index("read_battle_opponent_identity")
    assert llamada > inicio
