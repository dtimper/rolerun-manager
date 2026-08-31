"""Leer el PC de ORAS sin haber guardado dentro del juego.

La matriz viva se localiza probando direcciones conocidas y confirmándolas con
Pokémon en posiciones sabidas. Esas posiciones salían del último ``main``, así
que un traslado hecho desde RoleRun —que vive en la RAM hasta que el jugador
guarda— las caducaba: la dirección probada ERA la correcta y se rechazaba por
una prueba vieja, no por estar equivocada. El PC quedaba ilegible.

La prueba estructural no mira el guardado: un PK6 válido exige checksum y
especie correctos, así que dos de ellos en la rejilla exacta de 232 bytes
demuestran la matriz igual de bien que dos identidades conocidas.
"""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

from app.oras_live import (
    ORAS_PC_BOX_SLOT_COUNT,
    ORAS_PC_KNOWN_ADDRESSES,
    ORAS_PC_SIZE,
    PK6_STORED_SIZE,
    ORASLiveError,
    ORASLiveReader,
)


def _pk6(*, species: int = 261, pid: int = 0x89ABCDEF, tid: int = 12345, sid: int = 54321) -> bytes:
    """Un PK6 almacenado, sin cifrar y con checksum correcto.

    ``parse_pk6_boxed`` prueba primero los bytes tal cual y solo descifra si no
    valen, así que esto recorre exactamente el mismo camino de validación.
    """
    data = bytearray(PK6_STORED_SIZE)
    struct.pack_into("<I", data, 0, 0x12345678)
    struct.pack_into("<H", data, 8, species)
    struct.pack_into("<H", data, 0x0C, tid)
    struct.pack_into("<H", data, 0x0E, sid)
    struct.pack_into("<I", data, 0x10, 125000)
    data[0x14] = 50
    struct.pack_into("<I", data, 0x18, pid)
    nickname = "Poochyena".encode("utf-16le")
    data[0x40:0x40 + len(nickname)] = nickname
    struct.pack_into("<4H", data, 0x5A, 33, 44, 0, 0)
    checksum = sum(struct.unpack_from("<112H", data, 8)) & 0xFFFF
    struct.pack_into("<H", data, 6, checksum)
    return bytes(data)


class _ClienteFalso:
    """Devuelve la matriz que se le ponga en la dirección que se le diga."""

    def __init__(self, matrices: dict[int, bytes]) -> None:
        self._matrices = matrices
        self.lecturas: list[tuple[int, int]] = []

    def read_memory(self, address: int, size: int) -> bytes:
        self.lecturas.append((int(address), int(size)))
        for base, contenido in self._matrices.items():
            if base <= address < base + len(contenido):
                inicio = address - base
                return contenido[inicio:inicio + size]
        return bytes(size)


def _matriz(ocupados: dict[int, bytes]) -> bytes:
    """Rejilla completa de cajas con PK6 en los índices indicados."""
    matriz = bytearray(ORAS_PC_SIZE)
    for indice, bloque in ocupados.items():
        inicio = indice * PK6_STORED_SIZE
        matriz[inicio:inicio + PK6_STORED_SIZE] = bloque
    return bytes(matriz)


def _lector() -> ORASLiveReader:
    return ORASLiveReader(Path("no-existe.json"), stable_delay=0)


def _indice(box: int, box_slot: int) -> int:
    return (box - 1) * ORAS_PC_BOX_SLOT_COUNT + (box_slot - 1)


def test_dos_pk6_validos_demuestran_la_matriz() -> None:
    base = int(ORAS_PC_KNOWN_ADDRESSES[0])
    cliente = _ClienteFalso({base: _matriz({
        _indice(1, 1): _pk6(species=261, pid=111),
        _indice(1, 2): _pk6(species=278, pid=222),
    })})

    assert _lector()._pc_base_looks_like_the_matrix(cliente, base) is True


def test_un_solo_pokemon_no_basta_como_prueba() -> None:
    """Mismo listón que las identidades: una coincidencia aislada no vale."""
    base = int(ORAS_PC_KNOWN_ADDRESSES[0])
    cliente = _ClienteFalso({base: _matriz({_indice(1, 1): _pk6()})})

    assert _lector()._pc_base_looks_like_the_matrix(cliente, base) is False


def test_una_zona_de_ram_cualquiera_no_pasa_por_matriz() -> None:
    base = int(ORAS_PC_KNOWN_ADDRESSES[0])
    cliente = _ClienteFalso({base: bytes(range(256)) * (ORAS_PC_SIZE // 256 + 1)})

    assert _lector()._pc_base_looks_like_the_matrix(cliente, base) is False


def test_una_matriz_vacia_no_se_da_por_probada() -> None:
    base = int(ORAS_PC_KNOWN_ADDRESSES[0])
    cliente = _ClienteFalso({base: bytes(ORAS_PC_SIZE)})

    assert _lector()._pc_base_looks_like_the_matrix(cliente, base) is False


def test_un_hueco_roto_no_cuenta_en_contra() -> None:
    """Un hueco ilegible se ignora; lo que se exige es evidencia A FAVOR."""
    base = int(ORAS_PC_KNOWN_ADDRESSES[0])
    roto = bytearray(_pk6())
    roto[6] ^= 0xFF  # checksum destrozado
    cliente = _ClienteFalso({base: _matriz({
        _indice(1, 1): bytes(roto),
        _indice(1, 2): _pk6(species=261, pid=111),
        _indice(4, 9): _pk6(species=278, pid=222),
    })})

    assert _lector()._pc_base_looks_like_the_matrix(cliente, base) is True


def test_la_prueba_encuentra_pokemon_en_cualquier_caja() -> None:
    base = int(ORAS_PC_KNOWN_ADDRESSES[0])
    cliente = _ClienteFalso({base: _matriz({
        _indice(28, 30): _pk6(species=261, pid=111),
        _indice(31, 30): _pk6(species=278, pid=222),
    })})

    assert _lector()._pc_base_looks_like_the_matrix(cliente, base) is True


def test_un_error_de_lectura_no_se_convierte_en_una_matriz() -> None:
    class _ClienteRoto:
        def read_memory(self, address: int, size: int) -> bytes:
            raise OSError("el proceso desapareció")

    assert _lector()._pc_base_looks_like_the_matrix(
        _ClienteRoto(), int(ORAS_PC_KNOWN_ADDRESSES[0]),
    ) is False


# ---------- el localizador completo ----------

class _Proceso:
    process_id = 1
    title_id = 0x1234
    name = "azahar"


def test_se_localiza_el_pc_aunque_las_anclas_del_guardado_esten_caducadas() -> None:
    """Este es el caso real: mover desde RoleRun y no guardar en el juego."""
    base = int(ORAS_PC_KNOWN_ADDRESSES[0])
    cliente = _ClienteFalso({base: _matriz({
        _indice(1, 10): _pk6(species=261, pid=111),
        _indice(1, 20): _pk6(species=278, pid=222),
    })})
    lector = _lector()

    # Las anclas del ``main`` dicen los huecos 1 y 2; la RAM los tiene en 10 y
    # 20 porque el traslado no ha llegado al archivo. Ninguna coincide.
    localizada = lector._locate_pc_base_for_read(cliente, _Proceso(), [])

    assert localizada == base


def test_sin_matriz_en_ninguna_direccion_sigue_fallando() -> None:
    """La prueba estructural no puede inventar una matriz que no existe."""
    cliente = _ClienteFalso({})
    lector = _lector()

    with pytest.raises(ORASLiveError):
        lector._locate_pc_base_for_read(cliente, _Proceso(), [])


def test_las_identidades_siguen_teniendo_prioridad() -> None:
    """La prueba estructural es un respaldo, no un sustituto.

    Con dos direcciones conocidas, las identidades son lo único que distingue
    cuál de las dos es la de esta revisión del juego. Por eso se prueban antes.
    """
    import inspect

    fuente = inspect.getsource(ORASLiveReader._locate_pc_base_for_read)
    pos_identidades = fuente.index("_pc_anchor_matches")
    pos_estructura = fuente.index("_pc_base_looks_like_the_matrix")

    assert pos_identidades < pos_estructura
