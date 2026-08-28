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
import struct
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
    # PKHeX las vuelca en el orden de la tabla personal; `Pk4Pokemon` las
    # publica en el de RoleRun, con la velocidad al final.
    esperadas = caso["stats_stored"]
    assert leido.stats == (
        esperadas[0], esperadas[1], esperadas[2],
        esperadas[4], esperadas[5], esperadas[3],
    )
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
    pid, orden, canonico, cifrado = unshuffle_pk4(almacenado)
    assert cifrado, "PKHeX los genera cifrados"
    assert reshuffle_pk4(pid, orden, canonico, cifrado=cifrado) == almacenado


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
        assert tuple(calculadas[clave] for clave in STAT_ORDER_ROLERUN) == leido.stats, (
            f"{leido.nickname} (#{leido.species_id})"
        )


# --------------------------------------------------------------------------
# Los dos estados de un PK4 en memoria
# --------------------------------------------------------------------------

def _en_claro(cifrado: bytes) -> bytes:
    """El mismo PK4 tal y como el juego lo deja cuando trabaja con él.

    Grabado a 0,5 ms sobre la partida real: el mismo Pokémon, con el mismo
    checksum, sale una vez cifrado y a la siguiente en claro, y los dos dicen
    exactamente lo mismo.

    La cabecera **no se toca**. Aquí se forzaba `sanity` a 4 porque se creyó que
    era la marca del estado en claro; era falso, y el Hoothoot del que salió esa
    idea era casi con seguridad un «Huevo malo» ya estropeado.
    """
    import struct

    from app.pk4 import PK4_STORED_SIZE, _crypt

    pid, _sanity, checksum = struct.unpack_from("<IHH", cifrado, 0)
    cabecera = bytearray(cifrado[:8])
    cuerpo = _crypt(cifrado[8:PK4_STORED_SIZE], checksum)
    cola = cifrado[PK4_STORED_SIZE:]
    return bytes(cabecera) + cuerpo + (_crypt(cola, pid) if cola else b"")


@CASOS
def test_un_pk4_en_claro_se_lee_igual_que_uno_cifrado(caso):
    """Era lo que hacía fallar la lectura del equipo una y otra vez."""
    cifrado = bytes.fromhex(caso["party_hex"])
    claro = _en_claro(cifrado)
    assert claro != cifrado

    uno = parse_pk4_party(cifrado, 0)
    otro = parse_pk4_party(claro, 0)
    assert otro.species_id == uno.species_id
    assert otro.nickname == uno.nickname
    assert otro.level == uno.level
    assert otro.stats == uno.stats
    assert otro.move_ids == uno.move_ids


@CASOS
def test_el_estado_se_reconoce_solo_con_el_checksum(caso):
    # No se mira el `sanity`: se prueba a leerlo de las dos formas y manda la
    # que cuadre.
    almacenado = bytes.fromhex(caso["boxed_hex"])
    _pid, _orden, _canonico, cifrado = unshuffle_pk4(almacenado)
    assert cifrado is True
    _pid, _orden, _canonico, cifrado = unshuffle_pk4(_en_claro(almacenado))
    assert cifrado is False


def test_escribir_sobre_uno_en_claro_lo_devuelve_en_claro() -> None:
    """Devolverlo cifrado dejaría ese Pokémon ilegible para el juego."""
    from app.pk4 import pk4_party_healed

    claro = _en_claro(bytes.fromhex(_CASOS[0]["party_hex"]))
    curado = pk4_party_healed(claro, base_pp_for=lambda _m: 20)

    _pid, _orden, _canonico, cifrado = unshuffle_pk4(curado[:PK4_STORED_SIZE])
    assert cifrado is False
    leido = parse_pk4_party(curado, 0)
    assert leido.current_hp == leido.max_hp


# --------------------------------------------------------------------------
# La extensión de combate leída en el estado equivocado
# --------------------------------------------------------------------------

def test_una_extension_con_estadisticas_imposibles_no_cuela() -> None:
    """El caso que se midió sobre la partida viva, con el juego en el menú.

    Un Wooper de nivel 6 y 23 PS pasaba el filtro viejo -que solo miraba nivel y
    PS- y salía publicado con AtEsp 28801 y DefEsp 43367, porque esos dos
    números venían de la extensión leída al revés. Mirar las seis estadísticas
    lo corta. Y no es un detalle de lectura: mutar una ficha cuya extensión se
    leyó mal escribiría esa basura en la partida.
    """
    from app.pk4 import (
        PK4_CURRENT_HP, PK4_LEVEL, PK4_STATS, _extension_coherente,
    )

    cola = bytearray(100)
    cola[PK4_LEVEL - PK4_STORED_SIZE] = 6
    struct.pack_into("<H", cola, PK4_CURRENT_HP - PK4_STORED_SIZE, 23)

    struct.pack_into("<6H", cola, PK4_STATS - PK4_STORED_SIZE,
                     23, 10, 13, 7, 28801, 43367)
    assert not _extension_coherente(bytes(cola))

    struct.pack_into("<6H", cola, PK4_STATS - PK4_STORED_SIZE, 23, 10, 13, 7, 8, 8)
    assert _extension_coherente(bytes(cola))


def test_los_ps_actuales_no_pueden_pasar_de_los_maximos() -> None:
    from app.pk4 import (
        PK4_CURRENT_HP, PK4_LEVEL, PK4_STATS, _extension_coherente,
    )

    cola = bytearray(100)
    cola[PK4_LEVEL - PK4_STORED_SIZE] = 20
    struct.pack_into("<6H", cola, PK4_STATS - PK4_STORED_SIZE, 50, 30, 30, 30, 30, 30)
    struct.pack_into("<H", cola, PK4_CURRENT_HP - PK4_STORED_SIZE, 50)
    assert _extension_coherente(bytes(cola))
    struct.pack_into("<H", cola, PK4_CURRENT_HP - PK4_STORED_SIZE, 51)
    assert not _extension_coherente(bytes(cola))
