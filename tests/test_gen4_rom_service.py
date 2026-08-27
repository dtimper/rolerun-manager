"""Datos de juego de cuarta generación leídos de la ROM.

POR QUÉ EXISTE

El mismo motivo que en quinta: RoleRun se juega en randomizers, y con tablas
estáticas aplicar un rol recalcularía las estadísticas con valores falsos y
**las escribiría en la partida**.

CÓMO SE DEMOSTRÓ EL FORMATO (27-08-2026), contra las ROM reales del usuario:

* HeartGold guarda la tabla personal en `pbr/personal.narc`: 501 registros de
  44 bytes. Comparados con `data/pkhex_personal_hgss.bin`, **las estadísticas
  base, el ritmo de crecimiento y la habilidad 1 coinciden en las 501**. Lo que
  difiere está explicado y comprobado sin excepciones: los tipos por el hueco
  del «???» y la habilidad 2 por el relleno que hace PKHeX.
* La tabla de movimientos (`pbr/waza_tbl.narc`, y `poketool/waza/waza_tbl.narc`
  en Perla y Platino) trae 471 registros de 16 bytes, con los campos en otro
  orden que quinta y la categoría invertida. De los 467 movimientos reales,
  los 170 de categoría 2 tienen potencia cero y los 297 de categoría 0 y 1
  tienen potencia mayor que cero, sin una sola excepción.

Las pruebas que necesitan una ROM se saltan si no está: no se distribuyen con
el proyecto. Las que fijan el contrato funcionan siempre, con una ROM sintética
construida con la misma especificación.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.gen4_rom_service import (  # noqa: E402
    GEN4_GAMES,
    MOVE_COUNT,
    MOVE_RECORD_SIZE,
    PERSONAL_RECORD_SIZE,
    Gen4RomError,
    discover_gen4_rom,
    game_for_title,
    load_gen4_rom_profile,
    load_gen4_rom_profile_cached,
    normalize_type,
)

RAIZ = Path(__file__).resolve().parent.parent
REFERENCIA_PKHEX = RAIZ / "data" / "pkhex_personal_hgss.bin"

_HGSS = GEN4_GAMES["hgss"]
PERSONAL_PATH = _HGSS.personal_paths[0]
MOVE_PATH = _HGSS.move_paths[0]

ROMS_REALES = {
    "hgss": Path(
        "D:/Users/diego/Diego/Juegos/POKEMON ROLERUN/Pokémon HeartGold/"
        "4832 - Pokemon - Edicion Oro HeartGold (Spain) [b].nds"
    ),
    "pt": Path(
        "D:/Users/diego/Diego/Juegos/POKEMON ROLERUN/Pokémon Platino/"
        "3787 - Pokemon - Edicion Platino (Spain).nds"
    ),
    "dp": Path(
        "D:/Users/diego/Diego/Juegos/POKEMON ROLERUN/Pokémon Perla/"
        "1286 - Pokemon - Pearl Version (Europe) (Rev 13).nds"
    ),
}


# --------------------------------------------------------------------------
# Una ROM sintética, construida con la misma especificación
# --------------------------------------------------------------------------

def _narc(archivos: list[bytes]) -> bytes:
    datos = b"".join(archivos)
    fatb = bytearray(b"BTAF")
    fatb += struct.pack("<II", 12 + len(archivos) * 8, len(archivos))
    posicion = 0
    for archivo in archivos:
        fatb += struct.pack("<II", posicion, posicion + len(archivo))
        posicion += len(archivo)
    btnf = b"BTNF" + struct.pack("<I", 16) + struct.pack("<IHH", 4, 0, 1)
    gmif = b"GMIF" + struct.pack("<I", 8 + len(datos)) + datos
    cuerpo = bytes(fatb) + btnf + gmif
    cabecera = b"NARC" + struct.pack("<HHIHH", 0xFFFE, 0x0100, 16 + len(cuerpo), 16, 3)
    return cabecera + cuerpo


def _registro_personal(hp: int = 45) -> bytes:
    registro = bytearray(PERSONAL_RECORD_SIZE)
    registro[:6] = bytes((hp, 49, 49, 45, 65, 65))
    registro[0x06] = 12       # tipo 1 en el esquema de cuarta: Planta
    registro[0x07] = 3        # Veneno
    registro[0x13] = 3        # ritmo de crecimiento
    registro[0x16] = 65       # habilidad 1
    return bytes(registro)


def _registro_movimiento(categoria: int = 0, potencia: int = 40) -> bytes:
    registro = bytearray(MOVE_RECORD_SIZE)
    registro[0x02] = categoria
    registro[0x03] = potencia
    registro[0x04] = 10       # Fuego en el esquema de cuarta
    registro[0x05] = 100
    registro[0x06] = 35
    return bytes(registro)


def _rom(
    titulo: bytes = b"POKEMON HG\x00\x00",
    personal: list[bytes] | None = None,
    movimientos: list[bytes] | None = None,
) -> bytes:
    if personal is None:
        personal = [_registro_personal()] * _HGSS.personal_count
    if movimientos is None:
        movimientos = [_registro_movimiento()] * MOVE_COUNT

    contenedores = [_narc(personal), _narc(movimientos)]

    cuerpo = bytearray()
    fat = []
    for blob in contenedores:
        fat.append((len(cuerpo), len(cuerpo) + len(blob)))
        cuerpo += blob

    def entrada(nombre: str, sub_id: int | None) -> bytes:
        crudo = bytes([len(nombre) | (0x80 if sub_id is not None else 0)])
        crudo += nombre.encode("ascii")
        if sub_id is not None:
            crudo += struct.pack("<H", 0xF000 | sub_id)
        return crudo

    # 0 = raíz, 1 = pbr. Los dos archivos cuelgan de pbr, en el orden del FAT.
    subtablas = [
        entrada("pbr", 1) + b"\x00",
        entrada("personal.narc", None) + entrada("waza_tbl.narc", None) + b"\x00",
    ]
    cabeceras = bytearray()
    desplazamiento = len(subtablas) * 8
    for indice, sub in enumerate(subtablas):
        cabeceras += struct.pack(
            "<IHH", desplazamiento, 0, len(subtablas) if indice == 0 else 0,
        )
        desplazamiento += len(sub)
    fnt = bytes(cabeceras) + b"".join(subtablas)

    cabecera = bytearray(0x200)
    cabecera[0:12] = titulo
    cabecera[12:16] = b"IPKS"
    inicio_datos = 0x200 + len(fnt) + len(fat) * 8
    struct.pack_into(
        "<4I", cabecera, 0x40,
        0x200, len(fnt), 0x200 + len(fnt), len(fat) * 8,
    )
    tabla = b"".join(
        struct.pack("<II", inicio_datos + a, inicio_datos + b) for a, b in fat
    )
    return bytes(cabecera) + fnt + tabla + bytes(cuerpo)


@pytest.fixture
def rom_sintetica(tmp_path) -> Path:
    ruta = tmp_path / "sintetica.nds"
    ruta.write_bytes(_rom())
    return ruta


# --------------------------------------------------------------------------
# El contrato del formato
# --------------------------------------------------------------------------

def test_se_lee_una_rom_bien_formada(rom_sintetica) -> None:
    perfil = load_gen4_rom_profile(rom_sintetica)

    assert perfil.title == "POKEMON HG"
    assert perfil.game.key == "hgss"
    assert perfil.game_code == "IPKS"
    assert len(perfil.personal) == _HGSS.personal_count * PERSONAL_RECORD_SIZE
    assert len(perfil.moves) == MOVE_COUNT


def test_un_archivo_que_no_es_de_cuarta_se_rechaza(tmp_path) -> None:
    ruta = tmp_path / "otro.nds"
    ruta.write_bytes(_rom(titulo=b"POKEMON B2\x00\x00"))

    with pytest.raises(Gen4RomError, match="no es una ROM de cuarta"):
        load_gen4_rom_profile(ruta)


def test_pedir_un_juego_concreto_rechaza_a_su_vecino(tmp_path) -> None:
    ruta = tmp_path / "hgss.nds"
    ruta.write_bytes(_rom())

    with pytest.raises(Gen4RomError, match="Platino"):
        load_gen4_rom_profile(ruta, "pt")


def test_una_tabla_personal_con_otro_numero_de_especies_se_rechaza(tmp_path) -> None:
    ruta = tmp_path / "corta.nds"
    ruta.write_bytes(_rom(personal=[_registro_personal()] * 400))

    with pytest.raises(Gen4RomError, match="declara 400 especies"):
        load_gen4_rom_profile(ruta)


def test_una_tabla_personal_con_estadisticas_imposibles_se_rechaza(tmp_path) -> None:
    registros = [_registro_personal()] * _HGSS.personal_count
    registros[7] = bytes(PERSONAL_RECORD_SIZE)
    ruta = tmp_path / "rota.nds"
    ruta.write_bytes(_rom(personal=registros))

    with pytest.raises(Gen4RomError, match="estadísticas"):
        load_gen4_rom_profile(ruta)


def test_una_categoria_desconocida_se_rechaza(tmp_path) -> None:
    movimientos = [_registro_movimiento()] * MOVE_COUNT
    movimientos[3] = _registro_movimiento(categoria=9)
    ruta = tmp_path / "categoria.nds"
    ruta.write_bytes(_rom(movimientos=movimientos))

    with pytest.raises(Gen4RomError, match="categoría desconocida"):
        load_gen4_rom_profile(ruta)


def test_la_categoria_de_cuarta_esta_invertida_respecto_a_quinta(tmp_path) -> None:
    movimientos = [_registro_movimiento(categoria=0)] * MOVE_COUNT
    movimientos[1] = _registro_movimiento(categoria=1)
    movimientos[2] = _registro_movimiento(categoria=2, potencia=0)
    ruta = tmp_path / "categorias.nds"
    ruta.write_bytes(_rom(movimientos=movimientos))

    perfil = load_gen4_rom_profile(ruta)
    assert perfil.damage_class(0) == "physical"
    assert perfil.damage_class(1) == "special"
    assert perfil.damage_class(2) == "status"


def test_un_movimiento_fuera_de_rango_no_revienta(rom_sintetica) -> None:
    perfil = load_gen4_rom_profile(rom_sintetica)
    assert perfil.move(9999) is None
    assert perfil.damage_class(9999) == "unknown"
    assert perfil.base_pp(9999) == 0
    assert perfil.power(9999) == 0
    assert perfil.accuracy(9999) == 0


def test_la_precision_por_encima_de_cien_se_traduce_a_cero(tmp_path) -> None:
    movimientos = [_registro_movimiento()] * MOVE_COUNT
    infalible = bytearray(_registro_movimiento())
    infalible[0x05] = 200
    movimientos[5] = bytes(infalible)
    ruta = tmp_path / "precision.nds"
    ruta.write_bytes(_rom(movimientos=movimientos))

    assert load_gen4_rom_profile(ruta).accuracy(5) == 0


# --------------------------------------------------------------------------
# El hueco del tipo «???»
# --------------------------------------------------------------------------

def test_los_tipos_por_debajo_del_hueco_no_se_mueven() -> None:
    for tipo in range(9):
        assert normalize_type(tipo) == tipo


def test_los_tipos_por_encima_del_hueco_bajan_uno() -> None:
    # Fuego es 10 en cuarta y 9 en el esquema que usa el resto de RoleRun.
    assert normalize_type(10) == 9
    assert normalize_type(11) == 10        # Agua
    assert normalize_type(13) == 12        # Eléctrico
    assert normalize_type(17) == 16        # Siniestro


def test_el_tipo_interrogante_se_traduce_a_normal() -> None:
    assert normalize_type(9) == 0


def test_el_perfil_publica_los_tipos_ya_traducidos(rom_sintetica) -> None:
    # El registro sintético declara tipo 10 (Fuego en cuarta).
    assert load_gen4_rom_profile(rom_sintetica).move(1).type_id == 9


# --------------------------------------------------------------------------
# Descriptores y descubrimiento
# --------------------------------------------------------------------------

def test_cada_juego_de_cuarta_tiene_su_propio_titulo() -> None:
    assert game_for_title(b"POKEMON HG\x00\x00").key == "hgss"
    assert game_for_title(b"POKEMON SS\x00\x00").key == "hgss"
    assert game_for_title(b"POKEMON PL\x00\x00").key == "pt"
    assert game_for_title(b"POKEMON P\x00\x00\x00").key == "dp"
    assert game_for_title(b"POKEMON D\x00\x00\x00").key == "dp"
    assert game_for_title(b"POKEMON B2\x00\x00") is None


def test_platino_no_usa_la_tabla_vieja_de_diamante_y_perla() -> None:
    # Platino lleva las dos dentro; la que usa el juego es la suya.
    assert GEN4_GAMES["pt"].personal_paths == ("poketool/personal/pl_personal.narc",)
    assert GEN4_GAMES["pt"].personal_count == 508


def test_la_rom_se_busca_junto_al_guardado(tmp_path) -> None:
    ruta = tmp_path / "partida.nds"
    ruta.write_bytes(_rom())
    (tmp_path / "partida.sav").write_bytes(b"\x00" * 16)

    assert discover_gen4_rom(tmp_path / "partida.sav") == ruta


def test_sin_guardado_no_se_busca_nada() -> None:
    assert discover_gen4_rom(None) is None
    assert discover_gen4_rom("") is None


def test_un_guardado_sin_rom_al_lado_no_inventa_ninguna(tmp_path) -> None:
    (tmp_path / "partida.sav").write_bytes(b"\x00" * 16)
    assert discover_gen4_rom(tmp_path / "partida.sav") is None


def test_una_rom_que_cambia_se_relee(tmp_path) -> None:
    ruta = tmp_path / "cambiante.nds"
    ruta.write_bytes(_rom())
    primero = load_gen4_rom_profile_cached(ruta)

    personal = [_registro_personal(hp=99)] * _HGSS.personal_count
    ruta.write_bytes(_rom(personal=personal))
    import os
    os.utime(ruta, (0, 0))

    segundo = load_gen4_rom_profile_cached(ruta)
    assert segundo.personal[:1] != primero.personal[:1]


def test_una_rom_que_no_existe_se_rechaza_con_mensaje(tmp_path) -> None:
    with pytest.raises(Gen4RomError):
        load_gen4_rom_profile_cached(tmp_path / "no_existe.nds")


# --------------------------------------------------------------------------
# Contra las ROM reales del usuario
# --------------------------------------------------------------------------

def _rom_real(clave: str) -> Path:
    ruta = ROMS_REALES[clave]
    if not ruta.exists():
        pytest.skip(f"La ROM de {clave} no está en esta máquina.")
    return ruta


@pytest.mark.parametrize("clave", sorted(ROMS_REALES))
def test_las_tres_rom_de_cuarta_se_leen(clave: str) -> None:
    perfil = load_gen4_rom_profile(_rom_real(clave), clave)
    assert perfil.game.key == clave
    assert len(perfil.moves) == MOVE_COUNT
    assert len(perfil.personal) == GEN4_GAMES[clave].personal_count * PERSONAL_RECORD_SIZE


@pytest.mark.parametrize("clave", sorted(ROMS_REALES))
def test_los_movimientos_conocidos_salen_con_sus_datos_de_siempre(clave: str) -> None:
    perfil = load_gen4_rom_profile(_rom_real(clave), clave)
    placaje = perfil.move(1)
    assert (placaje.category, placaje.power, placaje.accuracy, placaje.pp) == (
        "physical", 40, 100, 35,
    )
    ascuas = perfil.move(52)
    assert (ascuas.category, ascuas.power, ascuas.type_id, ascuas.pp) == (
        "special", 40, 9, 25,
    )
    danza = perfil.move(14)
    assert (danza.category, danza.power, danza.pp) == ("status", 0, 30)


@pytest.mark.parametrize("clave", sorted(ROMS_REALES))
def test_la_categoria_y_la_potencia_no_se_contradicen_en_ninguna_rom(clave: str) -> None:
    perfil = load_gen4_rom_profile(_rom_real(clave), clave)
    reales = perfil.moves[1:468]
    assert all(m.power == 0 for m in reales if m.category == "status")
    assert all(m.power > 0 for m in reales if m.category != "status")


def test_la_tabla_de_heartgold_cuadra_con_la_copia_de_pkhex() -> None:
    if not REFERENCIA_PKHEX.exists():
        pytest.skip("No está la copia de PKHeX.")
    perfil = load_gen4_rom_profile(_rom_real("hgss"), "hgss")
    pkhex = REFERENCIA_PKHEX.read_bytes()
    tamano = PERSONAL_RECORD_SIZE
    especies = len(perfil.personal) // tamano

    for indice in range(especies):
        rom = perfil.personal[indice * tamano:(indice + 1) * tamano]
        ref = pkhex[indice * tamano:(indice + 1) * tamano]
        assert rom[:6] == ref[:6], f"estadísticas base distintas en #{indice}"
        assert rom[0x13] == ref[0x13], f"ritmo de crecimiento distinto en #{indice}"
        assert rom[0x16] == ref[0x16], f"habilidad 1 distinta en #{indice}"
        # Los tipos difieren por el hueco del «???», y la habilidad 2 porque
        # PKHeX rellena con la 1 los ceros que la ROM deja.
        assert normalize_type(rom[0x06]) == ref[0x06], f"tipo 1 distinto en #{indice}"
        assert normalize_type(rom[0x07]) == ref[0x07], f"tipo 2 distinto en #{indice}"
        assert ref[0x17] == (rom[0x17] or rom[0x16]), f"habilidad 2 distinta en #{indice}"
