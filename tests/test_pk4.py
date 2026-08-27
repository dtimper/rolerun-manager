from __future__ import annotations

"""El formato PK4, contrastado contra PKHeX.

Los casos los generó la propia PKHeX: veinticuatro Pokémon cifrados con
``WriteEncryptedDataParty``/``WriteEncryptedDataStored``, uno por cada una de las
24 disposiciones de bloque. Si el desbarajado estuviera mal, acertaría en unas y
fallaría en otras.

Al final hay además una lectura de la partida real de HeartGold del usuario, que
se salta si el archivo no está en la máquina.

Las estadísticas se comprueban contra la tabla personal de PKHeX que ya vive en
``data/``: si el nivel, los IV, los EV o la naturaleza —que en cuarta no se
guarda, sale del PID— estuvieran mal leídos, los números no cuadrarían.
"""

import json
from pathlib import Path

import pytest

from app.pk4 import (
    PK4_PARTY_SIZE,
    PK4_STORED_SIZE,
    Pk4Error,
    STAT_ORDER_PERSONAL,
    STAT_ORDER_ROLERUN,
    decode_gen4_string,
    gen4_final_stats,
    nature_from_pid,
    parse_pk4_boxed,
    parse_pk4_party,
    reshuffle_pk4,
    unshuffle_pk4,
)

_RAIZ = Path(__file__).resolve().parent.parent
_CASOS = json.loads((Path(__file__).resolve().parent / "data" / "pk4_cases.json").read_text(encoding="utf-8"))["cases"]
_PERSONAL = (_RAIZ / "data" / "pkhex_personal_hgss.bin").read_bytes()
_PERSONAL_RECORD = 0x2C


def _identificador(caso: dict) -> str:
    return f"disp{((caso['pid'] >> 13) & 31) % 24:02d}-{caso['species']}"


CASOS = pytest.mark.parametrize("caso", _CASOS, ids=[_identificador(c) for c in _CASOS])


def test_los_casos_cubren_las_veinticuatro_disposiciones():
    disposiciones = {((caso["pid"] >> 13) & 31) % 24 for caso in _CASOS}
    assert disposiciones == set(range(24))


@CASOS
def test_el_equipo_se_lee_igual_que_en_pkhex(caso):
    leido = parse_pk4_party(bytes.fromhex(caso["party_hex"]), 0)
    assert leido.pid == caso["pid"]
    assert leido.species_id == caso["species"]
    assert leido.nickname == caso["nickname"]
    assert leido.ot_name == caso["ot_name"]
    assert leido.level == caso["level"]
    assert leido.experience == caso["experience"]
    assert leido.held_item_id == caso["held_item"]
    assert leido.ability_id == caso["ability"]
    assert leido.tid == caso["tid"]
    assert leido.sid == caso["sid"]
    assert leido.form == caso["form"]
    assert leido.is_egg == caso["is_egg"]
    assert leido.move_ids == tuple(caso["moves"])
    assert leido.move_pp == tuple(caso["move_pp"])
    assert leido.move_pp_ups == tuple(caso["move_pp_ups"])
    assert leido.ivs == tuple(caso["ivs_rolerun"])
    assert leido.evs == tuple(caso["evs_rolerun"])
    assert leido.stats == tuple(caso["stats_stored"])
    assert leido.current_hp == caso["current_hp"]
    assert leido.max_hp == caso["stats_stored"][0]
    assert leido.status_condition == caso["status"]


@CASOS
def test_la_naturaleza_sale_del_pid_y_no_del_bloque(caso):
    # Es la diferencia grande con quinta: si se leyera de un byte, aquí saldrían
    # naturalezas distintas de las que declara PKHeX.
    assert nature_from_pid(caso["pid"]) == caso["nature"]
    assert parse_pk4_party(bytes.fromhex(caso["party_hex"]), 0).nature_id == caso["nature"]


@CASOS
def test_el_pc_se_lee_igual_que_en_pkhex(caso):
    leido = parse_pk4_boxed(bytes.fromhex(caso["boxed_hex"]), 3)
    assert leido is not None
    assert leido.slot == 3
    assert leido.pid == caso["pid"]
    assert leido.species_id == caso["species"]
    assert leido.nickname == caso["nickname"]
    assert leido.ot_name == caso["ot_name"]
    assert leido.experience == caso["experience"]
    assert leido.move_ids == tuple(caso["moves"])
    assert leido.ivs == tuple(caso["ivs_rolerun"])
    assert leido.evs == tuple(caso["evs_rolerun"])
    assert leido.nature_id == caso["nature"]
    # Un PK4 almacenado no lleva nivel ni estadísticas; cero es «no calculado».
    assert leido.level == 0
    assert leido.stats == (0, 0, 0, 0, 0, 0)


@CASOS
def test_las_estadisticas_cuadran_con_la_tabla_personal(caso):
    inicio = caso["species"] * _PERSONAL_RECORD
    crudo = _PERSONAL[inicio:inicio + 6]
    base = {clave: crudo[indice] for indice, clave in enumerate(STAT_ORDER_PERSONAL)}
    ivs = dict(zip(STAT_ORDER_ROLERUN, caso["ivs_rolerun"]))
    evs = dict(zip(STAT_ORDER_ROLERUN, caso["evs_rolerun"]))
    calculadas = gen4_final_stats(
        base=base, ivs=ivs, evs=evs,
        level=caso["level"], nature_id=caso["nature"],
    )
    assert [calculadas[clave] for clave in STAT_ORDER_PERSONAL] == caso["stats_stored"]


@CASOS
def test_volver_a_barajar_devuelve_los_mismos_bytes(caso):
    almacenado = bytes.fromhex(caso["boxed_hex"])
    pid, orden, canonico = unshuffle_pk4(almacenado)
    assert reshuffle_pk4(pid, orden, canonico) == almacenado


def test_un_checksum_que_no_cuadra_se_rechaza():
    original = bytearray(bytes.fromhex(_CASOS[0]["boxed_hex"]))
    original[6] ^= 0xFF
    with pytest.raises(Pk4Error):
        unshuffle_pk4(bytes(original))


def test_un_bloque_corto_se_rechaza():
    with pytest.raises(Pk4Error):
        unshuffle_pk4(b"\x00" * 100)
    with pytest.raises(Pk4Error):
        parse_pk4_party(b"\x00" * (PK4_PARTY_SIZE - 1), 0)
    with pytest.raises(Pk4Error):
        parse_pk4_boxed(b"\x00" * (PK4_STORED_SIZE - 1), 0)


def test_un_hueco_del_pc_a_ceros_no_es_un_pokemon():
    assert parse_pk4_boxed(b"\x00" * PK4_STORED_SIZE, 0) is None


def test_los_nombres_paran_en_el_terminador():
    # 0x012B es la «A» en la tabla de cuarta; 0xFFFF cierra la cadena.
    crudo = b"\x2b\x01\x2c\x01\xff\xff\x2d\x01"
    assert decode_gen4_string(crudo) == "AB"


def test_los_nombres_traducen_los_simbolos_propios_de_la_saga():
    leidos = {caso["nickname"] for caso in _CASOS}
    assert any("♂" in mote or "♀" in mote for mote in leidos)
    assert any("ñ" in mote.lower() or "ú" in mote.lower() for mote in leidos)


# --------------------------------------------------------------------------
# Contra la partida real del usuario
# --------------------------------------------------------------------------

# Medidos el 27-08-2026 recorriendo el guardado entero de HeartGold y quedándose
# con los bloques cuyo checksum PK4 cuadra: salieron cinco, seguidos y separados
# exactamente 236 bytes, con el contador justo delante.
#
# El archivo son dos copias de 0x40000 y el juego alterna entre ellas, así que
# el bloque general no siempre está en la misma mitad: se prueban las dos y vale
# la que declare un equipo con sentido.
GUARDADO_HGSS = Path(
    "D:/Users/diego/Diego/Juegos/POKEMON ROLERUN/Pokémon HeartGold/"
    "4832 - Pokemon - Edicion Oro HeartGold (Spain) [b].sav"
)
SAVE_PARTY_COUNT_HGSS = 0x94
SAVE_PARTY_DATA_HGSS = 0x98


MITADES_HGSS = (0x00000, 0x40000)


def _guardado_real() -> bytes:
    if not GUARDADO_HGSS.exists():
        pytest.skip("La partida de HeartGold no está en esta máquina.")
    return GUARDADO_HGSS.read_bytes()


def _equipo_real() -> list:
    import struct

    crudo = _guardado_real()
    for base in MITADES_HGSS:
        cuantos = struct.unpack_from("<I", crudo, base + SAVE_PARTY_COUNT_HGSS)[0]
        if not 1 <= cuantos <= 6:
            continue
        try:
            equipo = [
                parse_pk4_party(
                    crudo[
                        base + SAVE_PARTY_DATA_HGSS + indice * PK4_PARTY_SIZE:
                        base + SAVE_PARTY_DATA_HGSS + (indice + 1) * PK4_PARTY_SIZE
                    ],
                    indice,
                )
                for indice in range(cuantos)
            ]
        except Pk4Error:
            continue
        if all(1 <= miembro.species_id <= 493 for miembro in equipo):
            return equipo
    pytest.skip("La partida no tiene equipo que leer ahora mismo.")


def test_el_equipo_de_la_partida_real_se_lee_entero() -> None:
    for leido in _equipo_real():
        assert 1 <= leido.species_id <= 493
        assert 1 <= leido.level <= 100
        assert 0 < leido.max_hp
        assert leido.current_hp <= leido.max_hp
        assert leido.ot_name
        assert leido.nickname


def test_las_estadisticas_de_la_partida_real_cuadran_con_la_tabla_personal() -> None:
    """La prueba de fuego: si el nivel, los IV, los EV o la naturaleza salieran
    mal de un PK4 de verdad, estos números no coincidirían con los que el propio
    juego dejó escritos al lado."""
    for leido in _equipo_real():
        inicio = leido.species_id * _PERSONAL_RECORD
        crudo = _PERSONAL[inicio:inicio + 6]
        base = {clave: crudo[indice] for indice, clave in enumerate(STAT_ORDER_PERSONAL)}
        calculadas = gen4_final_stats(
            base=base,
            ivs=dict(zip(STAT_ORDER_ROLERUN, leido.ivs)),
            evs=dict(zip(STAT_ORDER_ROLERUN, leido.evs)),
            level=leido.level,
            nature_id=leido.nature_id,
        )
        assert tuple(calculadas[clave] for clave in STAT_ORDER_PERSONAL) == leido.stats, (
            f"{leido.nickname} (#{leido.species_id})"
        )
