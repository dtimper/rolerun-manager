"""ORAS: corrección de las copias en RAM de la tabla que decide el anuncio.

2026-09-26, partida real del usuario: con el archivo del mod ya en la tabla de
Mago, Houndoom seguía ofreciendo Afilagarras (tabla de Asesino) porque el
juego anuncia desde dos copias de la tabla en su memoria. Reescribirlas a mano
hizo que ofreciera Aligerar (Mago): validado. Estas pruebas usan una memoria
simulada; nunca tocan un proceso real.
"""

from __future__ import annotations

import struct
from types import SimpleNamespace

from app.oras_levelup_announcement_cache import (
    MIN_REGION_SIZE, find_copies, patch_copies, table_payload,
)
from app.ui import RoleRunManager

LEVELS = [1, 4, 8, 13, 16, 20]
ASESINO = table_payload([33, 394, 457, 424, 468, 400], LEVELS)
MAGO = table_payload([33, 394, 284, 284, 505, 414], LEVELS)
VAINILLA = table_payload([33, 394, 399, 424, 468, 400], LEVELS)


class MemoriaFalsa:
    """Una región grande de memoria, con lecturas/escrituras como las de Windows."""

    def __init__(self, contenido: dict[int, bytes], *, base: int = 0x10000, falla_escritura: bool = False):
        self.base = base
        self.datos = bytearray(64 * 1024)
        for offset, datos in contenido.items():
            self.datos[offset:offset + len(datos)] = datos
        self.falla_escritura = falla_escritura
        self.escrituras: list[int] = []

    def iter_writable_regions(self, handle):
        yield self.base, MIN_REGION_SIZE  # finge ser la región de ~256 MiB
        yield 0x900000, 4096  # región pequeña: no se barre

    def read(self, handle, address, size):
        offset = address - self.base
        trozo = bytes(self.datos[max(0, offset):max(0, offset) + size])
        return trozo + b"\0" * (size - len(trozo))

    def write(self, handle, address, data):
        self.escrituras.append(address)
        offset = address - self.base
        if self.falla_escritura and data != self.read(handle, address, len(data)):
            data = bytes(len(data))  # se queda a medias
            self.falla_escritura = False
        self.datos[offset:offset + len(data)] = data


def test_encuentra_las_copias_por_su_secuencia_de_niveles() -> None:
    memoria = MemoriaFalsa({0x100: ASESINO, 0x2000: ASESINO})
    assert find_copies(memoria, None, {229: LEVELS}) == {229: [0x10100, 0x12000]}


def test_reescribe_una_copia_de_una_tabla_conocida() -> None:
    memoria = MemoriaFalsa({0x100: ASESINO, 0x2000: VAINILLA})
    copias = [0x10100, 0x12000]
    hechas = patch_copies(memoria, None, copias, known_payloads=[VAINILLA, ASESINO, MAGO], target=MAGO)
    assert hechas == 2
    assert memoria.read(None, 0x10100, len(MAGO)) == MAGO
    assert memoria.read(None, 0x12000, len(MAGO)) == MAGO


def test_nunca_toca_algo_que_solo_comparte_los_niveles() -> None:
    """El ancla de niveles sola no basta: el contenido entero debe ser una tabla conocida."""
    extrano = table_payload([1, 2, 3, 4, 5, 6], LEVELS)
    memoria = MemoriaFalsa({0x100: extrano})
    assert patch_copies(memoria, None, [0x10100], known_payloads=[ASESINO], target=MAGO) == 0
    assert memoria.escrituras == []
    assert memoria.read(None, 0x10100, len(extrano)) == extrano


def test_una_copia_que_ya_esta_bien_no_se_reescribe() -> None:
    memoria = MemoriaFalsa({0x100: MAGO})
    assert patch_copies(memoria, None, [0x10100], known_payloads=[ASESINO], target=MAGO) == 1
    assert memoria.escrituras == []


def test_si_la_escritura_no_queda_bien_se_deja_como_estaba() -> None:
    memoria = MemoriaFalsa({0x100: ASESINO}, falla_escritura=True)
    assert patch_copies(memoria, None, [0x10100], known_payloads=[ASESINO], target=MAGO) == 0
    assert memoria.read(None, 0x10100, len(ASESINO)) == ASESINO


# --------------------------------------------------------------------------
# Qué especies se corrigen tras escribir el archivo
# --------------------------------------------------------------------------

def _blob(tabla: dict[int, list[int]]) -> bytes:
    """Un bloque con las entradas de cada especie en offsets fijos."""
    datos = bytearray(256)
    for species, moves in tabla.items():
        for i, move in enumerate(moves):
            struct.pack_into("<h", datos, species * 40 + 4 * i, move)
    return bytes(datos)


def _manager(entradas: dict[int, tuple]) -> SimpleNamespace:
    manager = SimpleNamespace(
        _oras_levelup_moves_vanilla_entries=entradas,
        engine=SimpleNamespace(
            pools={}, damage_classes={}, speed_status_moves=set(),
            self_healing_damage_moves=set(), allowed_move_ids=None,
        ),
    )
    manager._oras_levelup_usable_move_ids = RoleRunManager._oras_levelup_usable_move_ids.__get__(manager)
    return manager


def test_solo_se_corrigen_las_especies_cuya_tabla_cambio() -> None:
    entradas = {
        1: tuple((33, level, 40 + 4 * i) for i, level in enumerate((1, 5))),
        2: tuple((52, level, 80 + 4 * i) for i, level in enumerate((1, 9))),
    }
    manager = _manager(entradas)
    party = SimpleNamespace(party=[SimpleNamespace(species_id=1), SimpleNamespace(species_id=2)])
    antes = _blob({1: [33, 33], 2: [52, 52]})
    ahora = _blob({1: [33, 99], 2: [52, 52]})

    objetivos = RoleRunManager._oras_announcement_targets(manager, party, antes, ahora)

    assert set(objetivos) == {1}
    niveles, conocidas, destino = objetivos[1]
    assert niveles == [1, 5]
    assert destino == table_payload([33, 99], [1, 5])
    assert table_payload([33, 33], [1, 5]) in conocidas  # la vainilla


def test_sin_escritura_anterior_se_revisan_todas_las_del_equipo() -> None:
    """RoleRun recién abierto con el juego en marcha: puede haber copias viejas."""
    entradas = {1: ((33, 1, 40),), 2: ((52, 1, 80),)}
    manager = _manager(entradas)
    party = SimpleNamespace(party=[SimpleNamespace(species_id=1), SimpleNamespace(species_id=2)])
    objetivos = RoleRunManager._oras_announcement_targets(manager, party, None, _blob({1: [33], 2: [52]}))
    assert set(objetivos) == {1, 2}


def test_la_correccion_va_en_un_hilo_y_no_pierde_peticiones() -> None:
    lanzados: list[dict] = []
    manager = SimpleNamespace(
        _oras_announcement_cache_running=True,
        _oras_announcement_cache_pending={1: "a"},
    )
    RoleRunManager._sync_oras_levelup_announcement_cache(manager, {2: "b"})
    assert manager._oras_announcement_cache_pending == {1: "a", 2: "b"}
    assert lanzados == []


def test_se_engancha_justo_despues_de_escribir_el_archivo() -> None:
    import inspect

    fuente = inspect.getsource(RoleRunManager._sync_oras_levelup_moves_mod)
    escritura = fuente.index("oras_levelup_moves_mod.write_blob(")
    correccion = fuente.index("self._sync_oras_levelup_announcement_cache(")
    assert escritura < correccion
