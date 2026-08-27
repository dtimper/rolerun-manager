"""Medallas de B2/W2 en tiempo real.

CÓMO SE DEDUJO LA DIRECCIÓN, SIN PEDIR NADA AL USUARIO

El dinero ya estaba demostrado en `0x022266A4` con una traza de dos estados.
Faltaba saber dónde caen las medallas respecto a él, y eso lo dice PKHeX: al
cambiar `Misc5B2W2.Badges` en un guardado en blanco se mueve el byte `0x21104`,
y al cambiar el dinero se mueven `0x21100..0x21102`. O sea, **medallas =
dinero + 4**. Es la misma vecindad que en ORAS, donde `ORAS_BADGES_ADDRESS`
también es `ORAS_MONEY_ADDRESS + 4`.

La equivalencia entre el guardado y la RAM está confirmada por partida doble: el
guardado real del usuario pone **4524** en `0x21100`, que es exactamente el valor
con el que empezó su traza de dinero.

DOS DIFERENCIAS CON ORAS

1. ORAS guarda el **número** de medallas; quinta guarda **un bit por medalla**,
   así que hay que contarlos.
2. El dinero de quinta ocupa **tres** bytes, no cuatro. Escribir cuatro pisaba
   el byte siguiente, que no le pertenece.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.b2w2_live import (  # noqa: E402
    BADGES_ADDRESS,
    BADGES_SIZE,
    BADGES_TOTAL,
    MONEY_ADDRESS,
    MONEY_MAX,
    MONEY_SIZE,
    B2W2LiveError,
    parse_b2w2_badges,
)
from app.realtime.models import badge_source_is_live  # noqa: E402

# El guardado del usuario, si está en este equipo. No se distribuye.
_SAVE = Path(
    "D:/Users/diego/Diego/Juegos/POKEMON ROLERUN/Pokémon Negro 2/"
    "z120 - Pokemon - Edicion Negra 2 (Spain) (NDSi Enhanced) [b].sav"
)
_SAVE_MONEY_OFFSET = 0x21100
_SAVE_BADGES_OFFSET = 0x21104


# --------------------------------------------------------------------------
# Dónde están
# --------------------------------------------------------------------------

def test_las_medallas_van_cuatro_bytes_detras_del_dinero() -> None:
    """Lo dice PKHeX: 0x21100 el dinero y 0x21104 las medallas."""
    assert BADGES_ADDRESS == MONEY_ADDRESS + 4
    assert BADGES_ADDRESS == 0x022266A8
    assert _SAVE_BADGES_OFFSET - _SAVE_MONEY_OFFSET == 4


def test_el_dinero_ocupa_tres_bytes_y_no_cuatro() -> None:
    """Escribir cuatro pisaba un byte que no es del dinero."""
    assert MONEY_SIZE == 3
    assert MONEY_MAX < 2 ** (8 * MONEY_SIZE), "el tope tiene que caber en tres bytes"


def test_la_misma_vecindad_que_oras() -> None:
    """No es una coincidencia: ORAS coloca las medallas justo detrás del dinero."""
    from app.oras_live import ORAS_BADGES_ADDRESS, ORAS_MONEY_ADDRESS

    assert ORAS_BADGES_ADDRESS - ORAS_MONEY_ADDRESS == BADGES_ADDRESS - MONEY_ADDRESS


# --------------------------------------------------------------------------
# Cómo se cuentan
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("byte", "esperadas"),
    [(0x00, 0), (0x01, 1), (0x03, 2), (0x07, 3), (0x0F, 4),
     (0x1F, 5), (0x3F, 6), (0x7F, 7), (0xFF, 8)],
)
def test_cada_bit_es_una_medalla(byte: int, esperadas: int) -> None:
    """Quinta guarda bits, no un número: ahí es donde ORAS y B2/W2 divergen."""
    assert parse_b2w2_badges(bytes([byte])) == esperadas


def test_ocho_es_el_maximo() -> None:
    assert parse_b2w2_badges(b"\xFF") == BADGES_TOTAL


def test_unas_medallas_desordenadas_se_cuentan_igual() -> None:
    """Un randomizer puede alterar el orden de los gimnasios; el total no."""
    assert parse_b2w2_badges(bytes([0b10100101])) == 4


def test_un_bloque_de_otro_tamano_se_rechaza() -> None:
    with pytest.raises(B2W2LiveError, match="un byte"):
        parse_b2w2_badges(b"\x00\x00")


def test_el_tamano_declarado_es_un_byte() -> None:
    assert BADGES_SIZE == 1


# --------------------------------------------------------------------------
# La lectura viva
# --------------------------------------------------------------------------

def _lector(byte_medallas: int, dinero: int = 4524):
    from app.b2w2_live import B2W2MelonDSReader

    pedidos: list[tuple[int, int]] = []

    def leer(lectura, guest, tamano):
        pedidos.append((guest, tamano))
        if guest == BADGES_ADDRESS:
            return bytes([byte_medallas])
        if guest == MONEY_ADDRESS:
            return int(dinero).to_bytes(tamano, "little")
        raise AssertionError(f"lectura no prevista en 0x{guest:08X}")

    lector = B2W2MelonDSReader()
    lector.read_party = lambda: object()
    lector._read_guest_twice = leer
    lector.pedidos = pedidos
    return lector


def test_se_leen_las_medallas_de_su_direccion() -> None:
    lector = _lector(0x07)

    assert lector.read_badges() == 3
    assert lector.pedidos == [(BADGES_ADDRESS, BADGES_SIZE)]


def test_el_dinero_se_lee_de_tres_bytes() -> None:
    lector = _lector(0x00, dinero=4524)

    assert lector.read_money() == 4524
    assert lector.pedidos == [(MONEY_ADDRESS, 3)]


# --------------------------------------------------------------------------
# Cómo llegan a la cabecera
# --------------------------------------------------------------------------

def test_la_procedencia_cuenta_como_lectura_viva() -> None:
    """Sin declararla, el contrato común la rechaza por defecto."""
    assert badge_source_is_live(f"melonDS vivo · 0x{BADGES_ADDRESS:08X}")


def test_una_procedencia_desconocida_sigue_cerrada() -> None:
    assert not badge_source_is_live("inventada")
    assert not badge_source_is_live(None)


def test_el_adaptador_publica_las_medallas_y_su_procedencia() -> None:
    """El snapshot tiene que llevar las dos cosas, no solo el número.

    Sin `badge_source` declarado, `badge_source_is_live` lo trataría como una
    procedencia desconocida y la cabecera no lo daría por lectura viva.
    """
    import inspect

    from app.realtime import b2w2_adapter

    fuente = inspect.getsource(b2w2_adapter.B2W2RealTimeAdapter._capture)
    assert "badges=medallas," in fuente
    assert "badge_source=" in fuente
    assert "self.reader.read_badges(raw)" in fuente


def test_si_no_se_pueden_leer_no_se_publica_un_cero() -> None:
    """Un cero sería indistinguible de no tener ninguna medalla."""
    import inspect

    from app.realtime import b2w2_adapter

    fuente = inspect.getsource(b2w2_adapter)
    assert "medallas = None" in fuente
    assert "no se inventa un cero" in fuente


# --------------------------------------------------------------------------
# Contra el guardado real del usuario, si está en este equipo
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def guardado() -> bytes:
    if not _SAVE.exists():
        pytest.skip("El guardado de Negro 2 no está en este equipo.")
    return _SAVE.read_bytes()


def test_el_guardado_confirma_la_equivalencia_con_la_ram(guardado) -> None:
    """4524 es el valor con el que empezó la traza de dinero del usuario.

    Que el guardado ponga lo mismo en `0x21100` demuestra que ese desplazamiento
    y la dirección de RAM describen el mismo campo, que es lo que permite
    derivar la de medallas sin una segunda captura.
    """
    dinero = int.from_bytes(
        guardado[_SAVE_MONEY_OFFSET:_SAVE_MONEY_OFFSET + MONEY_SIZE], "little",
    )
    assert dinero == 4524


def test_el_byte_que_la_escritura_de_cuatro_pisaba_no_es_del_dinero(guardado) -> None:
    """PKHeX solo toca tres bytes al cambiar el dinero."""
    assert guardado[_SAVE_MONEY_OFFSET + 3] == 0x00


def test_las_medallas_del_guardado_son_un_numero_posible(guardado) -> None:
    contadas = parse_b2w2_badges(guardado[_SAVE_BADGES_OFFSET:_SAVE_BADGES_OFFSET + 1])

    assert 0 <= contadas <= BADGES_TOTAL
