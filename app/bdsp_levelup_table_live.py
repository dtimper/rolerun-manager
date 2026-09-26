"""Localización y parcheo en vivo de WazaOboeTable (BDSP, Ryujinx).

Homólogo en memoria de ``bdsp_levelup_moves.py`` (que solo lee la tabla
desde el archivo ``personal_masterdatas``): esto localiza y parchea la misma
tabla ya cargada por el juego en RAM. Demostrado el 2026-09-03 contra la
partida real del usuario — Stantler (localizada, verificada byte a byte
contra las 15 entradas del archivo) y Staravia (parcheada en vivo; el
diálogo nativo del juego mostró el movimiento sustituto, no el vainilla, al
subir de nivel de verdad). El formato en RAM es un array de pares ``int16``
(nivel, movimiento) por especie/forma, en el mismo orden que ya produce
``parse_wazaoboe_table``.

La entrada parcheada no se revierte tras enseñarse: es un dato de solo
lectura del juego, no forma parte del save, y dejarla parcheada también
beneficia al Recordador de Movimientos. Un reinicio del juego recarga la
tabla desde el archivo original sin intervención — confirmado el mismo día
(una sesión de vigilancia de 100 s sin ningún cambio espontáneo mientras el
juego seguía abierto; la única reversión observada coincidió con haber
cerrado y reabierto el juego, no con ningún reseteo en caliente).
"""
from __future__ import annotations

import re
import struct
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Sequence

from .ryujinx_host_memory import RyujinxHostMappedClient
from .ryujinx_host_write import RyujinxHostWriteTransport


class WazaOboeLiveError(RuntimeError):
    """Error presentable del parche en vivo de WazaOboeTable."""


@dataclass(frozen=True, slots=True)
class WazaOboeAnchor:
    species_form: tuple[int, int]
    pattern: bytes
    entry_count: int
    level_offsets: tuple[int, ...]
    move_offsets: tuple[int, ...]
    search_regex: bytes


def build_species_anchor(
    species_form: tuple[int, int],
    entries: tuple[tuple[int, int, int], ...],
    *,
    wildcard_keys: frozenset[int] | None = None,
    alternatives: Mapping[int, Iterable[int]] | None = None,
) -> WazaOboeAnchor:
    """``entries`` en el mismo formato que produce ``parse_wazaoboe_table``:
    ``(move_id, level, key)`` por entrada, en el orden original de la tabla.
    El patrón en vivo demostrado es ``<h nivel, <h movimiento`` intercalado,
    4 bytes por entrada.

    ``search_regex`` exige los bytes de nivel EXACTOS (nunca se escriben)
    siempre. Para el campo de movimiento: exacto (bytes vainilla) salvo que
    su ``key`` esté en ``wildcard_keys``, donde acepta cualquier valor
    (comodín de 2 bytes) — a diferencia de ``pattern`` (los bytes vainilla
    exactos siempre, útil como referencia/para tests).

    ``wildcard_keys=None`` pone comodín en TODOS los movimientos (localizar
    sin saber todavía qué se va a parchear). Cuando el llamador YA sabe qué
    entradas parcheará esta sesión (las claves de ``compute_species_patch``),
    debe pasarlas aquí: comodín solo en esas, exacto en el resto. Sin esto,
    una especie con muchos niveles bajos y repetidos (p. ej. varias entradas
    de nivel 1) produce un patrón demasiado genérico — suficientes bytes
    pequeños y comunes como para coincidir por azar en OTRO punto de la
    memoria, dando una coincidencia ambigua y perdiendo la especie —
    demostrado el 2026-09-04 con Absol (359): comodín en las 13 entradas
    encontró 2 coincidencias, mientras que solo 1-2 de esas 13 realmente
    necesitaban parchearse esa sesión.

    ``alternatives`` (2026-09-26): para una ``key`` sin comodín, además del
    vainilla acepta exactamente estos movimientos -los sustitutos que algún
    rol pondría ahí-. Una fila que se quedó con la tabla de OTRO rol (un
    cambio de rol, o una sesión anterior) se sigue encontrando sin volver al
    comodín de 2 bytes que hizo ambiguo a Absol.
    """
    if not entries:
        raise ValueError("No hay entradas para construir un ancla.")
    parts: list[bytes] = []
    regex_parts: list[bytes] = []
    level_offsets: list[int] = []
    move_offsets: list[int] = []
    offset = 0
    for move_id, level, key in entries:
        level_bytes = struct.pack("<h", int(level))
        parts.append(level_bytes)
        regex_parts.append(re.escape(level_bytes))
        level_offsets.append(offset)
        offset += 2
        move_bytes = struct.pack("<h", int(move_id))
        parts.append(move_bytes)
        if wildcard_keys is None or key in wildcard_keys:
            regex_parts.append(b"..")
        elif alternatives is not None and key in alternatives:
            options = sorted({move_bytes, *(struct.pack("<h", int(v)) for v in alternatives[key])})
            regex_parts.append(b"(?:" + b"|".join(re.escape(option) for option in options) + b")")
        else:
            regex_parts.append(re.escape(move_bytes))
        move_offsets.append(offset)
        offset += 2
    return WazaOboeAnchor(
        species_form=species_form,
        pattern=b"".join(parts),
        entry_count=len(entries),
        level_offsets=tuple(level_offsets),
        move_offsets=tuple(move_offsets),
        search_regex=b"".join(regex_parts),
    )


@dataclass(frozen=True, slots=True)
class WazaOboeLiveLocation:
    """``address`` es GUEST (el dominio que usa ``client.read_memory``), no
    host — igual que el resto de la API del cliente. La conversión a host
    (para ``RyujinxHostWriteTransport``, que sí trabaja en host) se hace
    solo en el borde de escritura, con el mismo patrón que ya usa
    ``BDSPLiveWriter`` (``host = guest + session.guest_to_host_delta``)."""

    address: int
    anchor: WazaOboeAnchor
    located_at: float


class WazaOboeLiveLocator:
    """Cachea ``(species_id, form_id) -> dirección`` durante la sesión.

    Vive y muere con el ``RyujinxHostMappedClient`` que recibe: una sesión
    nueva (reconexión) invalida cualquier dirección ya localizada.
    """

    #: Tras no localizar una especie (0 o >1 coincidencias — p. ej. dos
    #: especies distintas comparten la misma progresión de niveles bajo el
    #: patrón con comodines), cuánto se espera antes de volver a pagar un
    #: escaneo completo por ella. Sin este margen, una especie ambigua o
    #: genuinamente ilocalizable fuerza un reescaneo de ~1 GiB en CADA
    #: sondeo para siempre — demostrado el 2026-09-04 como la causa de una
    #: ralentización general y persistente de toda la aplicación.
    FAILURE_COOLDOWN_SECONDS = 10.0

    def __init__(self, client: RyujinxHostMappedClient) -> None:
        self.client = client
        self._cache: dict[tuple[int, int], WazaOboeLiveLocation] = {}
        self._failed_until: dict[tuple[int, int], float] = {}

    def _level_bytes_match(self, location: WazaOboeLiveLocation) -> bool:
        """Verificación barata de que la caché sigue siendo válida.

        Una sola lectura de todo el span (no una por cada nivel): con hasta
        20 entradas por especie y hasta 6 especies en el equipo, leer campo a
        campo son cientos de llamadas ``ReadProcessMemory`` por sondeo bajo
        el mismo candado que ya sirve party/PC/batalla — demostrado el
        2026-09-04 como la causa de una ralentización general de toda la
        aplicación tras activar el parche proactivo.
        """
        anchor = location.anchor
        try:
            actual = self.client.read_memory(location.address, len(anchor.pattern))
            return all(
                actual[offset:offset + 2] == anchor.pattern[offset:offset + 2]
                for offset in anchor.level_offsets
            )
        except Exception:
            return False

    def locate(self, anchor: WazaOboeAnchor) -> WazaOboeLiveLocation | None:
        return self.locate_all((anchor,)).get(anchor.species_form)

    def locate_all(
        self, anchors: Sequence[WazaOboeAnchor],
    ) -> dict[tuple[int, int], WazaOboeLiveLocation]:
        """Como ``locate`` pero para varias anclas: primero comprueba la
        caché de cada una por separado (barato), y agrupa TODAS las que
        siguen sin caché válida en un único ``locate_many`` — para no pagar
        un escaneo completo por especie cuando varias necesitan localizarse
        a la vez (p. ej. la primera vez que se conecta la sesión)."""
        result: dict[tuple[int, int], WazaOboeLiveLocation] = {}
        stale: list[WazaOboeAnchor] = []
        now = time.monotonic()
        for anchor in anchors:
            cached = self._cache.get(anchor.species_form)
            if (
                cached is not None
                and cached.anchor.pattern == anchor.pattern
                and self._level_bytes_match(cached)
            ):
                result[anchor.species_form] = cached
                continue
            failed_until = self._failed_until.get(anchor.species_form)
            if failed_until is not None and now < failed_until:
                continue
            stale.append(anchor)
        if stale:
            result.update(self.locate_many(stale))
        return result

    def locate_many(
        self, anchors: Sequence[WazaOboeAnchor],
    ) -> dict[tuple[int, int], WazaOboeLiveLocation]:
        """Un único paso de escaneo para todas las anclas pedidas.

        Solo confía en una clave cuando aparece exactamente una vez; 0 o
        más de 1 coincidencias se descartan de la caché y quedan ausentes
        del resultado — el llamador decide si insistir en el próximo sondeo.
        """
        if not anchors:
            return {}
        # Con comodines de bytes en los campos de movimiento (no el patrón
        # exacto): una especie ya parcheada en una sesión anterior ya no
        # tiene los bytes vainilla en RAM, y buscar el patrón exacto nunca
        # la volvería a encontrar — ver la nota en ``build_species_anchor``.
        patterns = {
            anchor.species_form: (anchor.search_regex, len(anchor.pattern))
            for anchor in anchors
        }
        hits = self.client.scan_regions_multi_regex(patterns)
        delta = int(self.client.session.guest_to_host_delta)
        now = time.monotonic()
        result: dict[tuple[int, int], WazaOboeLiveLocation] = {}
        by_form = {anchor.species_form: anchor for anchor in anchors}
        for species_form, addresses in hits.items():
            if len(addresses) != 1:
                self._cache.pop(species_form, None)
                self._failed_until[species_form] = now + self.FAILURE_COOLDOWN_SECONDS
                continue
            # scan_regions_multi busca en las vistas HostMapped y devuelve
            # direcciones host (mismo dominio que la huella principal de
            # connect()); se convierte a guest aquí para que el resto de la
            # API (read_memory, y el borde de escritura) trabaje siempre en
            # guest, igual que el resto del proyecto.
            location = WazaOboeLiveLocation(
                address=addresses[0] - delta, anchor=by_form[species_form], located_at=now,
            )
            self._cache[species_form] = location
            self._failed_until.pop(species_form, None)
            result[species_form] = location
        return result

    def discard(self, species_form: tuple[int, int]) -> None:
        self._cache.pop(species_form, None)
        self._failed_until.pop(species_form, None)

    def clear(self) -> None:
        self._cache.clear()
        self._failed_until.clear()


@dataclass(frozen=True, slots=True)
class WazaOboePatchOutcome:
    species_form: tuple[int, int]
    address: int
    changed: bool
    patched_indices: tuple[int, ...]


class WazaOboeLivePatcher:
    """Escritor transaccional de una fila de WazaOboeTable en vivo.

    Mismo patrón que ``BDSPLiveWriter.apply()``: doble lectura de
    precondición, escribir solo si difiere de lo ya presente, releer y
    verificar, revertir si algo no cuadra. No reutiliza ``BDSPLiveWriter``
    porque sus precondiciones (identidad de party, estado de batalla) son
    específicas de un PB8 concreto, no de una tabla de solo lectura
    compartida por especie/forma.
    """

    def __init__(
        self,
        client: RyujinxHostMappedClient,
        *,
        transport_factory: Callable[[], object] = RyujinxHostWriteTransport,
    ) -> None:
        self.client = client
        self.transport_factory = transport_factory

    def apply_patch(
        self,
        location: WazaOboeLiveLocation,
        patch: Mapping[int, int],
    ) -> WazaOboePatchOutcome:
        anchor = location.anchor
        if not patch:
            return WazaOboePatchOutcome(anchor.species_form, location.address, False, ())

        span = len(anchor.pattern)
        first = self.client.read_memory(location.address, span)
        second = self.client.read_memory(location.address, span)
        if first != second:
            raise WazaOboeLiveError(
                f"La fila de {anchor.species_form} cambió durante la precondición."
            )
        current = bytearray(second)
        desired = bytearray(second)
        patched_indices: list[int] = []
        for index, new_move_id in patch.items():
            if not 0 <= index < anchor.entry_count:
                raise WazaOboeLiveError(
                    f"Índice de entrada {index} fuera de rango para {anchor.species_form}."
                )
            offset = anchor.move_offsets[index]
            before = bytes(current[offset:offset + 2])
            after = struct.pack("<h", int(new_move_id))
            if before != after:
                patched_indices.append(index)
            desired[offset:offset + 2] = after

        if not patched_indices:
            return WazaOboePatchOutcome(anchor.species_form, location.address, False, ())

        # location.address es guest; RyujinxHostWriteTransport trabaja en
        # host (no convierte nada por su cuenta) — mismo borde que ya usa
        # BDSPLiveWriter (host = guest + guest_to_host_delta).
        host_address = location.address + int(self.client.session.guest_to_host_delta)
        transport = self.transport_factory()
        handle = transport.open(self.client.session.process.pid)
        try:
            transport.assert_writable(handle, host_address, span)
            precheck = transport.read(handle, host_address, span)
            if bytes(precheck) != bytes(current):
                raise WazaOboeLiveError(
                    f"La fila de {anchor.species_form} cambió justo antes de escribir."
                )
            transport.write(handle, host_address, bytes(desired))
            readback = transport.read(handle, host_address, span)
            guest_readback = self.client.read_memory(location.address, span)
            if bytes(readback) != bytes(desired) or bytes(guest_readback) != bytes(desired):
                transport.write(handle, host_address, bytes(current))
                rollback_readback = transport.read(handle, host_address, span)
                if bytes(rollback_readback) != bytes(current):
                    raise WazaOboeLiveError(
                        f"Escritura y reversión fallidas para {anchor.species_form}; "
                        "la tabla en vivo puede haber quedado inconsistente."
                    )
                raise WazaOboeLiveError(
                    f"La relectura no coincidió para {anchor.species_form}; se revirtió con éxito."
                )
        finally:
            transport.close(handle)

        return WazaOboePatchOutcome(
            anchor.species_form, location.address, True, tuple(patched_indices),
        )
