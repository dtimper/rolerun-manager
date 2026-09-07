from __future__ import annotations

import re
import struct
from types import SimpleNamespace

import pytest

from app.bdsp_levelup_table_live import (
    WazaOboeLiveError,
    WazaOboeLiveLocator,
    WazaOboeLivePatcher,
    build_species_anchor,
)

THUNDER, EARTHQUAKE, TACKLE, THUNDERBOLT = 87, 89, 33, 85


def _entries(*pairs: tuple[int, int]) -> tuple[tuple[int, int, int], ...]:
    """``pairs`` = (move_id, level); asigna la clave 0..N-1 en orden."""
    return tuple((move, level, index) for index, (move, level) in enumerate(pairs))


class _FakeHostMappedClient:
    """Simula las vistas HostMapped como un único blob host contiguo."""

    def __init__(self, host_base: int = 0x700000, delta: int = 0x1000000) -> None:
        self.host_base = host_base
        self.blob = bytearray()
        self.session = SimpleNamespace(
            process=SimpleNamespace(pid=99),
            guest_to_host_delta=delta,
        )

    def place(self, pattern: bytes) -> int:
        """Añade ``pattern`` al blob y devuelve su dirección GUEST."""
        host_address = self.host_base + len(self.blob)
        self.blob += pattern
        return host_address - self.session.guest_to_host_delta

    def read_memory(self, guest_address: int, size: int) -> bytes:
        host_address = int(guest_address) + int(self.session.guest_to_host_delta)
        start = host_address - self.host_base
        return bytes(self.blob[start:start + int(size)])

    def write_memory(self, guest_address: int, value: bytes) -> None:
        host_address = int(guest_address) + int(self.session.guest_to_host_delta)
        start = host_address - self.host_base
        self.blob[start:start + len(value)] = value

    def scan_regions_multi(self, patterns):
        result = {}
        for key, pattern in patterns.items():
            hits = []
            search_from = 0
            while True:
                position = self.blob.find(pattern, search_from)
                if position < 0:
                    break
                hits.append(self.host_base + position)
                search_from = position + 1
            result[key] = tuple(hits)
        return result

    def scan_regions_multi_regex(self, patterns):
        result = {}
        for key, (source, length) in patterns.items():
            compiled = re.compile(source, re.DOTALL)
            hits = [
                self.host_base + match.start()
                for match in compiled.finditer(bytes(self.blob))
            ]
            result[key] = tuple(hits)
        return result


class _Transport:
    def __init__(self, client: _FakeHostMappedClient, *, fail_on_write: int | None = None) -> None:
        self.client = client
        self.fail_on_write = fail_on_write
        self.write_calls = 0
        self.closed = False

    def open(self, pid: int):
        assert pid == 99
        return object()

    def close(self, _handle) -> None:
        self.closed = True

    def assert_writable(self, _handle, _address: int, _size: int) -> None:
        return None

    def read(self, _handle, host_address: int, size: int) -> bytes:
        guest = int(host_address) - int(self.client.session.guest_to_host_delta)
        return self.client.read_memory(guest, size)

    def write(self, _handle, host_address: int, value: bytes) -> None:
        self.write_calls += 1
        if self.fail_on_write == self.write_calls:
            raise OSError("fallo de escritura simulado")
        guest = int(host_address) - int(self.client.session.guest_to_host_delta)
        self.client.write_memory(guest, value)


def test_build_species_anchor_encodes_interleaved_level_move_int16_pairs() -> None:
    entries = _entries((THUNDER, 4), (EARTHQUAKE, 8))
    anchor = build_species_anchor((229, 0), entries)
    assert anchor.entry_count == 2
    assert anchor.pattern == struct.pack("<hhhh", 4, THUNDER, 8, EARTHQUAKE)
    assert anchor.level_offsets == (0, 4)
    assert anchor.move_offsets == (2, 6)


def test_build_species_anchor_rejects_empty_entries() -> None:
    with pytest.raises(ValueError):
        build_species_anchor((229, 0), ())


def test_build_species_anchor_wildcards_only_the_given_keys() -> None:
    entries = _entries((THUNDER, 4), (EARTHQUAKE, 8), (TACKLE, 12))
    anchor = build_species_anchor((229, 0), entries, wildcard_keys=frozenset({1}))
    # entrada 0 (índice 1 = EARTHQUAKE) tiene comodín; las demás son exactas.
    already_patched = bytearray(anchor.pattern)
    already_patched[6:8] = struct.pack("<h", THUNDERBOLT)  # movimiento de la entrada 1
    assert re.compile(anchor.search_regex, re.DOTALL).fullmatch(bytes(already_patched))

    # cambiar un movimiento NO incluido en wildcard_keys rompe la coincidencia.
    other_changed = bytearray(anchor.pattern)
    other_changed[2:4] = struct.pack("<h", THUNDERBOLT)  # movimiento de la entrada 0
    assert not re.compile(anchor.search_regex, re.DOTALL).fullmatch(bytes(other_changed))


def test_narrow_wildcard_avoids_an_ambiguity_that_a_full_wildcard_would_cause() -> None:
    """Pedido por el usuario el 2026-09-04: comodín en TODOS los movimientos
    (en vez de solo en los que hace falta parchear esta sesión) puede
    coincidir por azar en otro punto de la memoria si hay suficientes bytes
    de nivel pequeños y repetidos -demostrado con Absol, cuya progresión de
    niveles (varias entradas de nivel 1) producía dos coincidencias con el
    comodín completo pero solo una con el comodín acotado a lo que de
    verdad necesitaba sustituto-."""
    entries = _entries((THUNDER, 1), (EARTHQUAKE, 1), (TACKLE, 1))
    client = _FakeHostMappedClient()
    real = client.place(build_species_anchor((229, 0), entries).pattern)
    # una coincidencia "señuelo" en otro punto de la memoria: incidental,
    # bytes de nivel iguales (todo nivel 1) con movimientos distintos.
    decoy_entries = _entries((THUNDERBOLT, 1), (99, 1), (100, 1))
    client.place(build_species_anchor((0, 0), decoy_entries).pattern)

    full_wildcard = build_species_anchor((229, 0), entries)
    locator_full = WazaOboeLiveLocator(client)
    assert (229, 0) not in locator_full.locate_many((full_wildcard,))  # ambiguo

    narrow = build_species_anchor((229, 0), entries, wildcard_keys=frozenset({1}))
    locator_narrow = WazaOboeLiveLocator(client)
    found = locator_narrow.locate_many((narrow,))
    assert found[(229, 0)].address == real


def test_locate_many_finds_a_unique_hit_and_caches_the_guest_address() -> None:
    client = _FakeHostMappedClient()
    entries = _entries((THUNDER, 4), (EARTHQUAKE, 8))
    anchor = build_species_anchor((229, 0), entries)
    guest = client.place(anchor.pattern)

    locator = WazaOboeLiveLocator(client)
    found = locator.locate_many((anchor,))
    assert found[(229, 0)].address == guest


def test_locate_many_finds_a_row_already_patched_in_a_previous_session() -> None:
    """Pedido por el usuario el 2026-09-04: si el juego sigue abierto entre
    dos sesiones de RoleRun, una fila ya parcheada en la anterior ya no
    tiene los bytes de movimiento vainilla — el patrón exacto nunca la
    encontraría, causando un reescaneo completo en cada sondeo para
    siempre. La búsqueda debe tolerar el campo de movimiento ya cambiado."""
    client = _FakeHostMappedClient()
    entries = _entries((THUNDER, 4), (EARTHQUAKE, 8))
    anchor = build_species_anchor((229, 0), entries)
    # simula que el campo de movimiento de la primera entrada ya se parcheó:
    # el nivel (invariante) sigue igual, pero el movimiento ya no es THUNDER.
    already_patched = bytearray(anchor.pattern)
    already_patched[2:4] = struct.pack("<h", THUNDERBOLT)
    guest = client.place(bytes(already_patched))

    locator = WazaOboeLiveLocator(client)
    found = locator.locate(anchor)
    assert found is not None
    assert found.address == guest


def test_locate_many_discards_ambiguous_matches() -> None:
    client = _FakeHostMappedClient()
    entries = _entries((THUNDER, 4), (EARTHQUAKE, 8))
    anchor = build_species_anchor((229, 0), entries)
    client.place(anchor.pattern)
    client.place(b"\x00")  # separador para no fundir ambas coincidencias en una
    client.place(anchor.pattern)

    locator = WazaOboeLiveLocator(client)
    found = locator.locate_many((anchor,))
    assert (229, 0) not in found


def test_locate_all_does_not_rescan_a_species_still_within_the_failure_cooldown() -> None:
    """Pedido por el usuario el 2026-09-04: una especie ambigua (dos
    coincidencias con el patrón de comodines, p. ej. otra especie con la
    misma progresión de niveles) no debe forzar un escaneo completo de
    ~1 GiB en CADA sondeo para siempre — solo cada
    ``FAILURE_COOLDOWN_SECONDS``."""
    client = _FakeHostMappedClient()
    entries = _entries((THUNDER, 4), (EARTHQUAKE, 8))
    anchor = build_species_anchor((229, 0), entries)
    client.place(anchor.pattern)
    client.place(b"\x00")
    client.place(anchor.pattern)  # ambiguo a propósito: dos coincidencias

    locator = WazaOboeLiveLocator(client)
    first = locator.locate_all((anchor,))
    assert (229, 0) not in first

    def _boom(_patterns):
        raise AssertionError("no debería reescanear dentro del margen de enfriamiento")

    client.scan_regions_multi_regex = _boom
    second = locator.locate_all((anchor,))  # no debe lanzar
    assert (229, 0) not in second


def test_locate_uses_cache_without_rescanning_when_level_bytes_still_match() -> None:
    client = _FakeHostMappedClient()
    entries = _entries((THUNDER, 4), (EARTHQUAKE, 8))
    anchor = build_species_anchor((229, 0), entries)
    client.place(anchor.pattern)

    locator = WazaOboeLiveLocator(client)
    first = locator.locate(anchor)

    def _boom(_patterns):
        raise AssertionError("no debería reescanear con la caché aún válida")

    client.scan_regions_multi = _boom
    second = locator.locate(anchor)
    assert second.address == first.address


def test_locate_rescans_when_level_bytes_no_longer_match() -> None:
    client = _FakeHostMappedClient()
    entries = _entries((THUNDER, 4), (EARTHQUAKE, 8))
    anchor = build_species_anchor((229, 0), entries)
    client.place(anchor.pattern)
    locator = WazaOboeLiveLocator(client)
    locator.locate(anchor)

    # simula una tabla desplazada: corrompe los bytes de nivel cacheados y
    # coloca una copia intacta más adelante en el blob.
    client.blob[0:2] = b"\xff\xff"
    new_guest = client.place(anchor.pattern)

    found = locator.locate(anchor)
    assert found is not None
    assert found.address == new_guest


def test_apply_patch_is_a_no_op_when_nothing_changes() -> None:
    client = _FakeHostMappedClient()
    entries = _entries((THUNDER, 4), (EARTHQUAKE, 8))
    anchor = build_species_anchor((229, 0), entries)
    client.place(anchor.pattern)
    locator = WazaOboeLiveLocator(client)
    location = locator.locate(anchor)

    transport = _Transport(client)
    patcher = WazaOboeLivePatcher(client, transport_factory=lambda: transport)
    outcome = patcher.apply_patch(location, {})
    assert outcome.changed is False
    assert transport.write_calls == 0

    # parche que pide exactamente el valor ya presente tampoco escribe nada.
    outcome_same = patcher.apply_patch(location, {0: THUNDER})
    assert outcome_same.changed is False
    assert transport.write_calls == 0


def test_apply_patch_writes_only_the_move_field_and_verifies_guest_readback() -> None:
    client = _FakeHostMappedClient()
    entries = _entries((THUNDER, 4), (EARTHQUAKE, 8))
    anchor = build_species_anchor((229, 0), entries)
    client.place(anchor.pattern)
    locator = WazaOboeLiveLocator(client)
    location = locator.locate(anchor)

    transport = _Transport(client)
    patcher = WazaOboeLivePatcher(client, transport_factory=lambda: transport)
    outcome = patcher.apply_patch(location, {0: THUNDERBOLT})

    assert outcome.changed is True
    assert outcome.patched_indices == (0,)
    raw = client.read_memory(location.address, len(anchor.pattern))
    assert raw == struct.pack("<hhhh", 4, THUNDERBOLT, 8, EARTHQUAKE)


def test_apply_patch_rolls_back_when_the_write_fails() -> None:
    client = _FakeHostMappedClient()
    entries = _entries((THUNDER, 4), (EARTHQUAKE, 8))
    anchor = build_species_anchor((229, 0), entries)
    client.place(anchor.pattern)
    locator = WazaOboeLiveLocator(client)
    location = locator.locate(anchor)
    original = client.read_memory(location.address, len(anchor.pattern))

    transport = _Transport(client, fail_on_write=1)
    patcher = WazaOboeLivePatcher(client, transport_factory=lambda: transport)
    with pytest.raises(OSError):
        patcher.apply_patch(location, {0: THUNDERBOLT})

    assert client.read_memory(location.address, len(anchor.pattern)) == original


def test_apply_patch_rolls_back_when_the_readback_mismatches() -> None:
    client = _FakeHostMappedClient()
    entries = _entries((THUNDER, 4), (EARTHQUAKE, 8))
    anchor = build_species_anchor((229, 0), entries)
    client.place(anchor.pattern)
    locator = WazaOboeLiveLocator(client)
    location = locator.locate(anchor)
    original = client.read_memory(location.address, len(anchor.pattern))

    class _StaleReadTransport(_Transport):
        def write(self, _handle, host_address, value) -> None:
            self.write_calls += 1
            if self.write_calls == 1:
                return  # simula una escritura que no llegó a aplicarse
            super().write(_handle, host_address, value)

    transport = _StaleReadTransport(client)
    patcher = WazaOboeLivePatcher(client, transport_factory=lambda: transport)
    with pytest.raises(WazaOboeLiveError):
        patcher.apply_patch(location, {0: THUNDERBOLT})

    assert client.read_memory(location.address, len(anchor.pattern)) == original


def test_apply_patch_rejects_an_out_of_range_index() -> None:
    client = _FakeHostMappedClient()
    entries = _entries((THUNDER, 4), (EARTHQUAKE, 8))
    anchor = build_species_anchor((229, 0), entries)
    client.place(anchor.pattern)
    locator = WazaOboeLiveLocator(client)
    location = locator.locate(anchor)

    transport = _Transport(client)
    patcher = WazaOboeLivePatcher(client, transport_factory=lambda: transport)
    with pytest.raises(WazaOboeLiveError):
        patcher.apply_patch(location, {5: THUNDERBOLT})
    assert transport.write_calls == 0
