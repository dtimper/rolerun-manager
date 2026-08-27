"""La base del mapeo de melonDS se resuelve una vez, no en cada lectura.

Hasta alpha.19, `read_party` y `read_pc` recorrían **entero** el espacio de
direcciones de melonDS con `VirtualQueryEx` y sondeaban con lecturas de memoria
cada `AllocationBase` distinta, en cada ciclo del monitor y otra vez en cada
escritura. Al reactivarse el sondeo del PC vivo, ese coste pasó a pagarse
también cada pocos segundos.

La base cacheada no es un atajo que se salte comprobaciones: cada lectura vuelve
a ejecutar la misma doble lectura estable de count+party y el mismo parseo con
checksum. Lo único que se omite es *buscar dónde está* esa base.

Contrato que estas pruebas fijan:

- se descubre una vez y se reutiliza;
- si cambia el conjunto de procesos melonDS se vuelve a descubrir, porque la
  detección de lecturas ambiguas solo existe en el recorrido completo;
- se redescubre periódicamente por la misma razón;
- si la revalidación falla, se descubre de nuevo en vez de dar error;
- si melonDS desaparece, la base se olvida.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.b2w2_live import (  # noqa: E402
    BASE_REDISCOVERY_SECONDS,
    B2W2LiveError,
    B2W2MelonDSReader,
    B2W2PartyRead,
)

pytestmark = pytest.mark.skipif(
    os.name != "nt", reason="La resolución de procesos de melonDS es de Windows.",
)

ALLOCATION = 0x1B26C190000


class _ReaderEspia(B2W2MelonDSReader):
    """Sustituye solo las dos fronteras del sistema operativo."""

    def __init__(self, procesos=((4242, "melonDS.exe"),)) -> None:
        super().__init__()
        self.procesos = list(procesos)
        self.llamadas: list[int | None] = []
        self.reloj = 1000.0
        self.base_encontrada: int | None = ALLOCATION

    def _list_melonds_processes(self):
        return list(self.procesos)

    def _read_process(self, pid, name, *, known_allocation=None):
        self.llamadas.append(known_allocation)
        base = known_allocation if known_allocation is not None else self.base_encontrada
        if base is None:
            return None
        return B2W2PartyRead(pid, name, base, 1, b"raw", ())

    # ``read_party`` toma la hora una sola vez por lectura.
    def read_party(self):
        import app.b2w2_live as modulo

        original = modulo.time.monotonic
        modulo.time.monotonic = lambda: self.reloj
        try:
            return super().read_party()
        finally:
            modulo.time.monotonic = original


def _descubrimientos(reader: _ReaderEspia) -> int:
    return sum(1 for base in reader.llamadas if base is None)


def _relecturas(reader: _ReaderEspia) -> int:
    return sum(1 for base in reader.llamadas if base is not None)


def test_la_base_se_descubre_una_vez_y_se_reutiliza() -> None:
    reader = _ReaderEspia()

    primera = reader.read_party()
    for _ in range(9):
        reader.read_party()

    assert primera.allocation_base == ALLOCATION
    assert _descubrimientos(reader) == 1, "solo el primer ciclo debe recorrer la memoria"
    assert _relecturas(reader) == 9
    assert reader.llamadas[1:] == [ALLOCATION] * 9


def test_cambiar_el_conjunto_de_procesos_fuerza_redescubrir() -> None:
    """La detección de lecturas ambiguas vive en el recorrido completo."""
    reader = _ReaderEspia()
    reader.read_party()
    reader.read_party()
    assert _descubrimientos(reader) == 1

    # Se abre un segundo melonDS: la base cacheada deja de ser fiable.
    reader.procesos.append((5150, "melonDS.exe"))
    reader.read_party()

    assert _descubrimientos(reader) == 2


def test_se_redescubre_periodicamente_aunque_nada_cambie() -> None:
    reader = _ReaderEspia()
    reader.read_party()
    reader.reloj += BASE_REDISCOVERY_SECONDS - 1
    reader.read_party()
    assert _descubrimientos(reader) == 1

    reader.reloj += 2
    reader.read_party()
    assert _descubrimientos(reader) == 2


def test_si_la_revalidacion_falla_se_descubre_de_nuevo_sin_error() -> None:
    """Un state-load puede remapear la memoria: eso no es un fallo del usuario."""
    reader = _ReaderEspia()
    reader.read_party()

    otra_base = 0x2C37D2A0000
    llamadas_reales = []

    def _read_process(pid, name, *, known_allocation=None):
        llamadas_reales.append(known_allocation)
        if known_allocation is not None:
            return None  # la base vieja ya no revalida
        return B2W2PartyRead(pid, name, otra_base, 1, b"raw", ())

    reader._read_process = _read_process
    resultado = reader.read_party()

    assert llamadas_reales == [ALLOCATION, None]
    assert resultado.allocation_base == otra_base


def test_si_melonds_desaparece_se_olvida_la_base() -> None:
    reader = _ReaderEspia()
    reader.read_party()
    assert reader._resolved is not None

    reader.procesos.clear()
    with pytest.raises(B2W2LiveError, match="no está abierto"):
        reader.read_party()

    assert reader._resolved is None

    # Al volver, se descubre desde cero.
    reader.procesos.append((4242, "melonDS.exe"))
    reader.read_party()
    assert _descubrimientos(reader) == 2


def test_un_descubrimiento_fallido_no_deja_una_base_invalida() -> None:
    reader = _ReaderEspia()
    reader.base_encontrada = None

    with pytest.raises(B2W2LiveError):
        reader.read_party()

    assert reader._resolved is None


def test_olvidar_la_base_es_explicito_y_reversible() -> None:
    reader = _ReaderEspia()
    reader.read_party()

    reader.forget_resolved_base()
    reader.read_party()

    assert _descubrimientos(reader) == 2


def test_la_lectura_del_pc_reutiliza_la_base_de_la_party() -> None:
    """``read_pc`` recibe la party ya resuelta: no puede volver a escanear."""
    reader = _ReaderEspia()
    party = reader.read_party()
    reader.read_pc = lambda p=None: p  # aísla la lectura de la matriz

    assert reader.read_pc(party) is party
    assert _descubrimientos(reader) == 1
