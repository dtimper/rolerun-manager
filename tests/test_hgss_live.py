"""La lectura en vivo de HeartGold, en lo que se puede probar sin melonDS.

El recorrido del proceso necesita Windows y el emulador abierto, así que aquí se
fija todo lo demás: la interpretación del bloque de equipo, la del PC, el cálculo
de direcciones y la disciplina de rechazo. Los bloques de prueba salen de los
mismos PK4 que generó PKHeX para `test_pk4.py`.

Hay además una prueba estructural. En alpha.57 se coló un `self.memory` dentro
de un `@staticmethod` y ninguna prueba lo vio, porque los dobles de prueba
sustituían el método entero. Esa comprobación mira el código, no el
comportamiento.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.gen4_memory import (  # noqa: E402
    GEN4_MEMORY,
    PC_BOX_COUNT,
    PC_BOX_SLOT_COUNT,
    PC_BOX_STRIDE,
)
from app.hgss_live import (  # noqa: E402
    MAX_PARTY,
    PC_MATRIX_SIZE,
    HgssLiveError,
    HgssTrainerRead,
    parse_party_block,
    parse_pc_matrix,
    party_block_offsets,
    pc_slot_offset,
)
from app.pk4 import PK4_PARTY_SIZE, PK4_STORED_SIZE  # noqa: E402

_CASOS = json.loads(
    (Path(__file__).resolve().parent / "data" / "pk4_cases.json").read_text(encoding="utf-8")
)["cases"]
HGSS = GEN4_MEMORY["hgss"]


def _equipo(cuantos: int) -> bytes:
    return b"".join(
        bytes.fromhex(_CASOS[indice]["party_hex"]) for indice in range(cuantos)
    )


def _pc_vacio() -> bytearray:
    return bytearray(PC_MATRIX_SIZE)


# --------------------------------------------------------------------------
# El bloque de equipo
# --------------------------------------------------------------------------

@pytest.mark.parametrize("cuantos", [1, 2, 3, 6])
def test_se_lee_un_equipo_completo(cuantos: int) -> None:
    equipo = parse_party_block(_equipo(cuantos), cuantos)
    assert len(equipo) == cuantos
    for indice, miembro in enumerate(equipo):
        assert miembro.slot == indice
        assert miembro.species_id == _CASOS[indice]["species"]
        assert miembro.nickname == _CASOS[indice]["nickname"]


def test_un_contador_fuera_de_rango_se_rechaza() -> None:
    for cuantos in (0, 7, -1, 255):
        with pytest.raises(HgssLiveError, match="fuera de rango"):
            parse_party_block(_equipo(1), cuantos)


def test_un_bloque_corto_se_rechaza() -> None:
    with pytest.raises(HgssLiveError, match="incompleto"):
        parse_party_block(_equipo(2)[:-1], 2)


def test_un_miembro_con_checksum_roto_invalida_el_equipo_entero() -> None:
    # Publicar cinco de seis daría un equipo que el jugador no tiene.
    crudo = bytearray(_equipo(3))
    crudo[PK4_PARTY_SIZE + 6] ^= 0xFF
    with pytest.raises(HgssLiveError, match="miembro 2"):
        parse_party_block(bytes(crudo), 3)


def test_un_hueco_vacio_no_se_acepta_como_miembro() -> None:
    """Un hueco vacío **pasa el checksum**, así que hay que mirar la especie.

    No son 136 ceros: el juego deja un PK4 cifrado con semilla cero, que al
    descifrarlo da 128 ceros cuya suma cuadra con el checksum. Se vio en la
    partida real del usuario, cuyo sexto hueco pasa el checksum y declara la
    especie cero. Sin la comprobación de especie el equipo saldría con un
    miembro fantasma.
    """
    from app.pk4 import empty_pk4_party, unshuffle_pk4

    vacio = empty_pk4_party()
    unshuffle_pk4(vacio)        # no lanza: el checksum de un hueco vacío cuadra
    # Lo caza antes la extensión, que a ceros no describe a nadie: nivel cero y
    # sin PS máximos. Y si pasara, la especie cero lo pararía igual.
    with pytest.raises(HgssLiveError, match="miembro 2"):
        parse_party_block(_equipo(1) + vacio, 2)


# --------------------------------------------------------------------------
# El PC
# --------------------------------------------------------------------------

def test_un_pc_vacio_no_publica_ningun_pokemon() -> None:
    vacios, dentro = parse_pc_matrix(bytes(_pc_vacio()))
    assert dentro == ()
    assert vacios == PC_BOX_COUNT * PC_BOX_SLOT_COUNT


def test_se_leen_los_pokemon_de_cada_caja() -> None:
    matriz = _pc_vacio()
    colocados = [(0, 0), (0, 29), (1, 0), (17, 29)]
    for indice, (caja, hueco) in enumerate(colocados):
        desde = caja * PC_BOX_STRIDE + hueco * PK4_STORED_SIZE
        matriz[desde:desde + PK4_STORED_SIZE] = bytes.fromhex(_CASOS[indice]["boxed_hex"])

    vacios, dentro = parse_pc_matrix(bytes(matriz))
    assert len(dentro) == len(colocados)
    assert vacios == PC_BOX_COUNT * PC_BOX_SLOT_COUNT - len(colocados)
    for guardado, (caja, hueco) in zip(dentro, colocados):
        assert divmod(guardado.slot, PC_BOX_SLOT_COUNT) == (caja, hueco)


def test_un_hueco_ilegible_no_tumba_el_pc_entero() -> None:
    # A diferencia del equipo: una caja con basura no puede dejar al jugador sin
    # ver el resto de sus Pokémon.
    matriz = _pc_vacio()
    matriz[0:PK4_STORED_SIZE] = bytes.fromhex(_CASOS[0]["boxed_hex"])
    roto = PC_BOX_STRIDE + 0
    matriz[roto:roto + PK4_STORED_SIZE] = bytes(range(PK4_STORED_SIZE))

    vacios, dentro = parse_pc_matrix(bytes(matriz))
    assert len(dentro) == 1
    assert dentro[0].species_id == _CASOS[0]["species"]
    assert vacios == PC_BOX_COUNT * PC_BOX_SLOT_COUNT - 1


def test_una_matriz_de_otro_tamano_se_rechaza() -> None:
    with pytest.raises(HgssLiveError, match="tamaño inválido"):
        parse_pc_matrix(bytes(PC_MATRIX_SIZE - 1))


def test_la_matriz_mide_lo_que_dice_el_reparto_medido() -> None:
    assert PC_MATRIX_SIZE == 18 * 0x1000
    assert PC_BOX_SLOT_COUNT * PK4_STORED_SIZE <= PC_BOX_STRIDE


# --------------------------------------------------------------------------
# Direcciones
# --------------------------------------------------------------------------

def test_cada_miembro_va_236_bytes_despues_del_anterior() -> None:
    for hueco in range(MAX_PARTY):
        direccion, tamano = party_block_offsets(HGSS, hueco)
        assert tamano == PK4_PARTY_SIZE
        assert direccion == HGSS.party_data + hueco * PK4_PARTY_SIZE


def test_un_hueco_de_equipo_fuera_de_rango_se_rechaza() -> None:
    for hueco in (-1, 6, 99):
        with pytest.raises(HgssLiveError):
            party_block_offsets(HGSS, hueco)


def test_las_direcciones_del_pc_cuadran_con_lo_sondeado() -> None:
    # Sondeado en PKHeX escribiendo en esos huecos concretos: caja 1 hueco 1 en
    # 0xF700, hueco 2 a 136 bytes, caja 2 a 0x1000 y la última en 0x21668.
    assert pc_slot_offset(HGSS, 1, 1) == HGSS.block_base + 0x0F700
    assert pc_slot_offset(HGSS, 1, 2) == HGSS.block_base + 0x0F788
    assert pc_slot_offset(HGSS, 2, 1) == HGSS.block_base + 0x10700
    assert pc_slot_offset(HGSS, 18, 30) == HGSS.block_base + 0x21668


def test_una_caja_o_un_hueco_fuera_de_rango_se_rechazan() -> None:
    for caja, hueco in ((0, 1), (19, 1), (1, 0), (1, 31)):
        with pytest.raises(HgssLiveError):
            pc_slot_offset(HGSS, caja, hueco)


# --------------------------------------------------------------------------
# Entrenador
# --------------------------------------------------------------------------

def test_las_medallas_se_cuentan_sumando_johto_y_kanto() -> None:
    # HeartGold reparte sus dieciséis medallas en dos bytes.
    assert HgssTrainerRead(0, 0b00000000, 0b00000000).badge_count == 0
    assert HgssTrainerRead(0, 0b00000111, 0b00000000).badge_count == 3
    assert HgssTrainerRead(0, 0b11111111, 0b11111111).badge_count == 16
    assert HgssTrainerRead(0, 0b00001000, 0b00000011).badge_count == 3


# --------------------------------------------------------------------------
# Estructura
# --------------------------------------------------------------------------

def test_ningun_metodo_estatico_usa_el_descriptor_de_direcciones() -> None:
    """`self.memory` dentro de un `@staticmethod` es un fallo silencioso.

    Pasó en quinta: la lectura del PC se rompió en los dos juegos y ninguna
    prueba lo vio, porque los dobles sustituían el método entero.
    """
    ruta = Path(__file__).resolve().parent.parent / "app" / "hgss_live.py"
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    culpables: list[str] = []
    for clase in [n for n in ast.walk(arbol) if isinstance(n, ast.ClassDef)]:
        for metodo in [n for n in clase.body if isinstance(n, ast.FunctionDef)]:
            estatico = any(
                isinstance(d, ast.Name) and d.id == "staticmethod"
                for d in metodo.decorator_list
            )
            if not estatico:
                continue
            usa_self = any(
                isinstance(n, ast.Name) and n.id == "self"
                for n in ast.walk(metodo)
            )
            if usa_self:
                culpables.append(f"{clase.name}.{metodo.name}")
    assert not culpables, f"métodos estáticos que usan self: {culpables}"


def test_el_lector_no_escribe_en_la_memoria_del_emulador() -> None:
    """Ni una llamada de escritura. El lector es de solo lectura por contrato."""
    fuente = (
        Path(__file__).resolve().parent.parent / "app" / "hgss_live.py"
    ).read_text(encoding="utf-8")
    for prohibida in ("WriteProcessMemory", "VirtualProtectEx", ".write("):
        assert prohibida not in fuente, f"el lector no debería usar {prohibida}"


# --------------------------------------------------------------------------
# La paciencia con una RAM que no se está quieta
# --------------------------------------------------------------------------

def test_una_lectura_con_los_checksums_buenos_se_acepta_aunque_la_anterior_fallara():
    """Lo que demuestra una lectura buena es el checksum, no repetirla.

    Medido el 27-08-2026 sobre la partida del usuario **con el juego en marcha**:
    de 400 intentos, 304 tuvieron las dos lecturas distintas. Con el juego
    parado, 300 de 300 coincidieron. Exigir que dos lecturas seguidas fueran
    idénticas dejaba a RoleRun sin curar, sin PC y sin poder escribir mientras se
    jugaba. Cada PK4 lleva su checksum de 16 bits y son seis: una lectura pillada
    a medias no los pasa.
    """
    from app.hgss_live import HgssMelonDSReader

    crudo = _equipo(2)
    basura = bytes(len(crudo))
    lector = HgssMelonDSReader()
    llamadas = {"datos": 0}

    def leer(direccion: int, tamano: int) -> bytes:
        if tamano == 1:
            return bytes([2])
        llamadas["datos"] += 1
        return basura if llamadas["datos"] <= 3 else crudo

    resultado = lector._capture_nominal_candidate(leer, 0x1000, intentos=8)
    assert resultado is not None, "se rindió con una lectura buena disponible"
    contador, publicado, equipo = resultado
    assert contador == 2 and publicado == crudo and len(equipo) == 2


def test_un_contador_imposible_no_se_reintenta() -> None:
    """Repetirlo sobre las 365 reservas del proceso solo costaría tiempo."""
    from app.hgss_live import HgssMelonDSReader

    lector = HgssMelonDSReader()
    llamadas = {"n": 0}

    def leer(direccion: int, tamano: int) -> bytes:
        llamadas["n"] += 1
        return bytes([99])

    assert lector._capture_nominal_candidate(leer, 0x1000, intentos=25) is None
    assert llamadas["n"] == 1


def test_si_el_equipo_cambia_de_tamano_a_media_lectura_se_reintenta() -> None:
    # El contador es un byte suelto, sin checksum que lo respalde: ahí sí hace
    # falta mirarlo dos veces.
    from app.hgss_live import HgssMelonDSReader

    lector = HgssMelonDSReader()
    crudo = _equipo(2)
    estado = {"vuelta": 0}

    def leer(direccion: int, tamano: int) -> bytes:
        if tamano == 1:
            estado["vuelta"] += 1
            # 2, luego 3 -el equipo crecio-, y a partir de ahi 2 otra vez.
            return bytes([2]) if estado["vuelta"] != 2 else bytes([3])
        return crudo if tamano == len(crudo) else _equipo(3)

    resultado = lector._capture_nominal_candidate(leer, 0x1000, intentos=8)
    assert resultado is not None
    assert resultado[0] in (2, 3)


def test_la_busqueda_es_impaciente_y_la_base_conocida_no() -> None:
    from app.hgss_live import (
        INTENTOS_DE_RECORRIDO, INTENTOS_EN_LA_BASE_CONOCIDA, INTENTOS_EN_LA_BUSQUEDA,
    )

    # Recorrer 365 reservas con mucha paciencia costaría tiempo para nada; la
    # reserva ya demostrada merece toda la del mundo.
    assert INTENTOS_EN_LA_BUSQUEDA < INTENTOS_EN_LA_BASE_CONOCIDA
    assert INTENTOS_EN_LA_BASE_CONOCIDA >= 20
    assert INTENTOS_DE_RECORRIDO >= 2


# --------------------------------------------------------------------------
# Localizar el bloque, que no está siempre en el mismo sitio
# --------------------------------------------------------------------------

def _ram_con_bloques(*posiciones, firma: bytes) -> bytes:
    """Una RAM de mentira con un bloque del guardado en cada posición."""
    import struct

    from app.hgss_live import FIRMA_OFFSET, MARCA, MARCA_OFFSET, TAMANO_BLOQUE

    ram = bytearray(0x40000)
    for posicion in posiciones:
        ram[posicion + FIRMA_OFFSET:posicion + FIRMA_OFFSET + len(firma)] = firma
        struct.pack_into("<I", ram, posicion + MARCA_OFFSET, MARCA)
    assert max(posiciones) + TAMANO_BLOQUE <= len(ram)
    return bytes(ram)


def test_los_bloques_se_reconocen_por_la_firma_y_la_marca() -> None:
    """Con la firma sola salían cuatro; con la marca, los dos de verdad."""
    from app.hgss_live import FIRMA_LARGO, FIRMA_OFFSET, bloques_del_guardado

    firma = bytes(range(FIRMA_LARGO))
    ram = bytearray(_ram_con_bloques(0x1000, 0x20000, firma=firma))
    # Un tercero con la firma pero sin la marca: no es un bloque.
    ram[0x8000 + FIRMA_OFFSET:0x8000 + FIRMA_OFFSET + FIRMA_LARGO] = firma

    assert bloques_del_guardado(bytes(ram), firma) == (0x1000, 0x20000)


def test_una_firma_de_otro_tamano_se_rechaza() -> None:
    from app.hgss_live import bloques_del_guardado

    with pytest.raises(HgssLiveError, match="firma"):
        bloques_del_guardado(b"\x00" * 100, b"corta")


def test_sin_firma_no_se_puede_relocalizar() -> None:
    """Sin el guardado delante no hay con qué reconocer el bloque."""
    from app.hgss_live import HgssMelonDSReader

    lector = HgssMelonDSReader(firma_getter=lambda: None)
    assert lector._relocalizar([(1, "melonDS.exe")]) is False
    assert lector.block_is_live is False


def test_el_bloque_no_se_da_por_vivo_sin_demostrarlo() -> None:
    """Escribir sin esa prueba fue lo que dejó un «Huevo malo»."""
    from app.hgss_live import HgssMelonDSReader

    assert HgssMelonDSReader().block_is_live is False
