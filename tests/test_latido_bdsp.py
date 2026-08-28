"""El reloj del juego, para que un congelado deje de ser invisible.

Al enseñar una MT desde RoleRun el juego se queda congelado. La traza no lo veía:
después de la escritura siguió leyendo con normalidad **68 segundos**, porque un
juego congelado se ve exactamente igual desde fuera —proceso vivo, memoria
legible— y con el personaje quieto ni los PS ni el equipo cambian.

Demostrado leyendo la partida viva, con el personaje quieto en el mapa:

===============  ====  ==========================================
SaveData+0x118   u16   horas       (0x000A = 10)
SaveData+0x11A   u8    minutos     (0x28 → 0x29 al pasar de 59 s)
SaveData+0x11B   u8    segundos    (39, 41, 43 … 59, 0, 2, 4)
===============  ====  ==========================================

Es el único campo conocido que avanza sin que el jugador haga nada. Si deja de
moverse entre dos capturas, el juego se ha parado.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.bdsp_live import (  # noqa: E402
    BDSP_PLAYTIME_SIZE,
    BDSP_SP_130_PLAYTIME_POINTER,
    read_bdsp_play_time,
)


class _Cliente:
    def __init__(self, crudo: bytes, *, revienta: bool = False) -> None:
        self.crudo = crudo
        self.revienta = revienta
        self.pedidas: list[tuple[int, int]] = []

    def resolve_main_pointer(self, cadena):
        if self.revienta:
            raise RuntimeError("la cadena produjo un puntero invalido")
        assert tuple(cadena) == BDSP_SP_130_PLAYTIME_POINTER
        return 0x1000

    def read_memory(self, direccion: int, tamano: int) -> bytes:
        self.pedidas.append((direccion, tamano))
        return self.crudo[:tamano]


def _reloj(horas: int, minutos: int, segundos: int) -> bytes:
    return struct.pack("<HBB", horas, minutos, segundos)


def test_se_lee_el_reloj_tal_y_como_esta_en_memoria() -> None:
    cliente = _Cliente(_reloj(10, 40, 39))

    assert read_bdsp_play_time(cliente) == (10, 40, 39)
    assert cliente.pedidas == [(0x1000, BDSP_PLAYTIME_SIZE)]


def test_las_horas_ocupan_dos_bytes() -> None:
    """Una Run larga pasa de 255 horas y el reloj no puede darse la vuelta."""
    assert read_bdsp_play_time(_Cliente(_reloj(300, 5, 7))) == (300, 5, 7)


def test_el_segundero_da_la_vuelta_en_59() -> None:
    """Lo observado en la partida viva: 59 -> 0, y el minuto sube."""
    assert read_bdsp_play_time(_Cliente(_reloj(10, 40, 59))) == (10, 40, 59)
    assert read_bdsp_play_time(_Cliente(_reloj(10, 41, 0))) == (10, 41, 0)


def test_si_no_se_puede_leer_no_revienta_la_captura() -> None:
    """Es una señal de diagnóstico: no puede tumbar una lectura real.

    Un ``None`` en la traza significa «no se pudo leer», que ya es información.
    """
    assert read_bdsp_play_time(_Cliente(b"", revienta=True)) is None
    assert read_bdsp_play_time(object()) is None


def test_cada_captura_y_cada_escritura_dejan_el_reloj_anotado() -> None:
    """Sin esto, un congelado es indistinguible de estarse quieto."""
    import inspect

    from app.realtime import bdsp_adapter

    fuente = inspect.getsource(bdsp_adapter)
    captura = fuente[fuente.index('"event": "snapshot"'):][:600]
    escritura = fuente[fuente.index('"event": "write-verified"'):][:600]

    assert '"reloj": read_bdsp_play_time(client)' in captura
    assert '"reloj": read_bdsp_play_time(client)' in escritura
