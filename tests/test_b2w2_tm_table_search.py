"""La búsqueda de la tabla MT/MO viva dentro de la RAM de B2/W2.

RoleRun se juega en randomizers, así que la tabla que manda es la que el juego
tiene cargada, no una extraída de PKHeX una vez. Estas pruebas comprueban que la
búsqueda encuentra esa tabla y —lo que más importa— que **no la confunde** con
cualquier otro tramo de memoria.

La firma es fuerte: 101 valores de 16 bits seguidos, todos entre 1 y 559 y todos
distintos. Lo que estas pruebas fijan es que esa firma se aplica entera.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.b2w2_live import DS_RAM_BASE  # noqa: E402
from app.b2w2_tm_service import reference_move_ids  # noqa: E402
from tools_b2w2_tm_table_capture import (  # noqa: E402
    MOVIMIENTO_MAXIMO,
    TOTAL_MT,
    _candidatos,
)


def _referencia() -> list[int]:
    """En orden de objeto, que es como el juego guarda la tabla."""
    return list(reference_move_ids())


def _ram(contenido: dict[int, list[int]], palabras: int = 4096) -> bytes:
    """Memoria simulada: ceros salvo las tablas que se coloquen a propósito."""
    crudo = bytearray(palabras * 2)
    for indice, valores in contenido.items():
        struct.pack_into(f"<{len(valores)}H", crudo, indice * 2, *valores)
    return bytes(crudo)


# --------------------------------------------------------------------------
# Lo que tiene que encontrar
# --------------------------------------------------------------------------

def test_encuentra_la_tabla_donde_esta() -> None:
    tabla = _referencia()

    encontrados = _candidatos(_ram({1000: tabla}))

    assert len(encontrados) == 1
    assert encontrados[0]["direccion"] == f"0x{DS_RAM_BASE + 2000:08X}"
    assert encontrados[0]["movimientos"] == tabla


def test_encuentra_una_tabla_randomizada_igual_de_bien() -> None:
    """Es el caso que motiva todo esto: el contenido cambia, la forma no."""
    randomizada = list(range(200, 200 + TOTAL_MT))
    assert randomizada != _referencia()

    encontrados = _candidatos(_ram({1500: randomizada}))

    assert [c["movimientos"] for c in encontrados] == [randomizada]


def test_una_tabla_pegada_al_final_de_la_memoria_no_se_pierde() -> None:
    tabla = _referencia()
    palabras = 1000 + TOTAL_MT

    encontrados = _candidatos(_ram({1000: tabla}, palabras=palabras))

    assert len(encontrados) == 1


# --------------------------------------------------------------------------
# Lo que NO puede confundir con una tabla
# --------------------------------------------------------------------------

def test_una_memoria_a_ceros_no_produce_nada() -> None:
    """Cero no es un movimiento: un bloque vacío no es una tabla."""
    assert _candidatos(_ram({})) == []


def test_cien_valores_validos_no_bastan() -> None:
    tabla = _referencia()

    assert _candidatos(_ram({1000: tabla[:TOTAL_MT - 1]})) == []


def test_un_valor_repetido_descarta_el_tramo() -> None:
    """El juego no puede tener dos MT que enseñen lo mismo."""
    tabla = _referencia()
    tabla[40] = tabla[7]

    assert _candidatos(_ram({1000: tabla})) == []


def test_un_movimiento_de_otra_generacion_descarta_el_tramo() -> None:
    tabla = _referencia()
    tabla[60] = MOVIMIENTO_MAXIMO + 1

    assert _candidatos(_ram({1000: tabla})) == []


def test_una_cuesta_de_numeros_pequenos_no_es_una_tabla_de_mt() -> None:
    """Datos consecutivos crecientes son comunes en memoria y son distintos.

    Aquí la firma sí acierta por poco: 101 valores crecientes distintos dentro
    del rango son indistinguibles de una tabla. Por eso la herramienta no se
    queda con «hay un candidato», sino que exige además que en una partida sin
    randomizar coincida con la referencia de PKHeX.
    """
    cuesta = list(range(1, TOTAL_MT + 1))

    encontrados = _candidatos(_ram({1000: cuesta}))

    assert [c["movimientos"] for c in encontrados] == [cuesta]
    assert encontrados[0]["movimientos"] != _referencia()


def test_dos_copias_de_la_tabla_se_reportan_las_dos() -> None:
    """Si el juego tuviera copias, hay que verlas para elegir, no ocultarlas."""
    tabla = _referencia()

    encontrados = _candidatos(_ram({1000: tabla, 2000: tabla}))

    assert len(encontrados) == 2
    assert {c["direccion"] for c in encontrados} == {
        f"0x{DS_RAM_BASE + 2000:08X}", f"0x{DS_RAM_BASE + 4000:08X}",
    }


def test_un_tramo_largo_de_valores_validos_se_revisa_entero() -> None:
    """La optimización por tramos no puede saltarse arranques intermedios.

    La tabla va precedida de 50 valores válidos, así que el tramo sin ningún
    valor imposible mide 151 y la tabla **no** empieza donde empieza el tramo.
    El relleno termina repitiendo el primer movimiento de la tabla, de modo que
    cualquier ventana que lo pise tiene un repetido y el único arranque bueno
    es el de la tabla de verdad.
    """
    tabla = _referencia()
    relleno = [7] * 49 + [tabla[0]]
    encontrados = _candidatos(_ram({1000: relleno + tabla}))

    assert [c["movimientos"] for c in encontrados] == [tabla]
    assert encontrados[0]["direccion"] == f"0x{DS_RAM_BASE + (1000 + 50) * 2:08X}"
