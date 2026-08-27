"""Dos hilos leyendo melonDS no pueden romperse los tipos entre ellos.

Fallo reportado el 27-08-2026: al aplicar una sustitución en Negro 2 saltaba

    argument 2: TypeError: expected LP_PROCESSENTRY32W instance
    instead of pointer to PROCESSENTRY32W

Un mensaje que no tenía nada que ver con la sustitución. Son **dos clases
distintas con el mismo nombre**.

Dos causas sumadas:

1. ``PROCESSENTRY32W`` estaba declarada *dentro* de la función que enumera
   procesos, así que cada llamada creaba una clase nueva y volvía a fijar
   ``argtypes``. Con dos hilos —monitor, sondeo del PC y escritura pueden
   solaparse— uno pisaba los tipos del otro en mitad de la llamada.
2. ``ctypes.windll.kernel32`` es un singleton de todo el proceso, y su caché de
   funciones también. Cuatro módulos de RoleRun declaran su propia
   ``PROCESSENTRY32W`` y fijan ``argtypes`` sobre ese mismo objeto compartido.

Se corrigen las dos: una única estructura de módulo y una instancia privada de
kernel32 para B2/W2. Y se serializa el lector, que es el riesgo de concurrencia
que la auditoría del 27-08-2026 ya señalaba como ALTO.
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.b2w2_live as b2w2  # noqa: E402

from test_b2w2_v026_foundation import (  # noqa: E402
    _FakeMelonDS,
    _pc_matrix_fixture,
    _pk5_fixture,
)


# --------------------------------------------------------------------------
# Los tipos
# --------------------------------------------------------------------------

def test_la_estructura_de_procesos_se_declara_una_sola_vez() -> None:
    """Si se declarara por llamada, cada una crearía una clase distinta."""
    assert isinstance(b2w2._PROCESSENTRY32W, type)
    assert issubclass(b2w2._PROCESSENTRY32W, ctypes.Structure)
    assert b2w2._PROCESSENTRY32W is b2w2._PROCESSENTRY32W


def test_nadie_vuelve_a_declararla_dentro_de_una_funcion() -> None:
    import inspect

    fuente = inspect.getsource(b2w2)
    assert fuente.count("class _PROCESSENTRY32W") == 1
    assert "class PROCESSENTRY32W" not in fuente


def test_el_lector_no_usa_el_kernel32_compartido() -> None:
    """El singleton lo comparten cuatro módulos que declaran tipos distintos."""
    import inspect

    fuente = inspect.getsource(b2w2)
    codigo = "\n".join(
        linea for linea in fuente.splitlines()
        if "ctypes.windll.kernel32" in linea and not linea.lstrip().startswith("#")
        and "``" not in linea
    )
    assert codigo == "", f"quedan usos del kernel32 compartido:\n{codigo}"


@pytest.mark.skipif(os.name != "nt", reason="kernel32 solo existe en Windows.")
def test_la_instancia_privada_no_es_la_compartida() -> None:
    assert b2w2._KERNEL32 is not None
    assert b2w2._KERNEL32 is not ctypes.windll.kernel32


@pytest.mark.skipif(os.name != "nt", reason="kernel32 solo existe en Windows.")
def test_otro_modulo_no_puede_invalidar_los_tipos_del_lector() -> None:
    """Reproduce la interferencia: otro módulo fija sus propios argtypes.

    Antes esto rompía la siguiente enumeración de procesos de B2/W2. Con la
    instancia privada, el lector sigue funcionando.
    """
    class OtraEntrada(ctypes.Structure):
        _fields_ = [("dwSize", ctypes.c_ulong)]

    compartido = ctypes.windll.kernel32
    original = compartido.Process32FirstW.argtypes
    try:
        compartido.Process32FirstW.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(OtraEntrada),
        ]
        # No se comprueba el resultado —melonDS puede no estar abierto—, solo que
        # los tipos del lector siguen siendo los suyos.
        assert b2w2._KERNEL32.Process32FirstW.argtypes[1] is ctypes.POINTER(
            b2w2._PROCESSENTRY32W,
        )
    finally:
        compartido.Process32FirstW.argtypes = original


# --------------------------------------------------------------------------
# La serialización
# --------------------------------------------------------------------------

def _reader() -> _FakeMelonDS:
    return _FakeMelonDS(1, _pk5_fixture(), _pc_matrix_fixture())


def test_el_lector_nace_con_su_cerrojo() -> None:
    reader = _reader()
    assert isinstance(reader._lock, type(threading.RLock()))


def test_el_cerrojo_es_reentrante() -> None:
    """Los writers releen party y PC dentro de su propia transacción."""
    reader = _reader()
    with reader._lock:
        with reader._lock:
            assert reader.read_party().count == 1


def test_dos_hilos_no_se_solapan_dentro_del_lector() -> None:
    reader = _reader()
    dentro = 0
    solapes = []
    barrera = threading.Lock()

    original = _FakeMelonDS.read_party

    def lectura_lenta(self):
        nonlocal dentro
        with barrera:
            dentro += 1
            if dentro > 1:
                solapes.append(dentro)
        try:
            for _ in range(200):
                pass
            return original(self)
        finally:
            with barrera:
                dentro -= 1

    reader.__class__.read_party = b2w2._serialized(lectura_lenta)
    try:
        hilos = [threading.Thread(target=reader.read_party) for _ in range(8)]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join()
    finally:
        reader.__class__.read_party = original

    assert solapes == [], "dos hilos entraron a la vez en el lector"
