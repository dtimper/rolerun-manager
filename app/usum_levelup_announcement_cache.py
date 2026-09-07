"""USUM: parcheo en vivo del búfer de anuncio de aprendizajes por nivel.

2026-09-04, validado físicamente contra la partida real del usuario (Eevee,
Asesino→Mago→Asesino): el diálogo "X quiere aprender Y" de USUM no lee la
tabla de aprendizajes (``a/0/1/3``, ya parcheada por
``usum_levelup_moves.py``) en cada aprendizaje — el juego decodifica esa
tabla UNA VEZ para cada Pokémon (al cargar la escena/mapa, o al abrir su
ficha) en un búfer de trabajo en RAM: una lista plana de pares
``(movimiento, nivel)`` para TODA la tabla de esa especie/``personal_id``,
en el mismo orden que el GARC. Ese búfer, no el archivo, es lo que decide
qué anuncia el diálogo — así que un cambio de rol a mitad de sesión no se
refleja en el anuncio hasta que ese búfer se reconstruye (comprobado:
entrar a la ficha del Pokémon SÍ lo reconstruye; cerrar y abrir la mochila
NO).

Esta pieza localiza y reescribe ese búfer directamente, sin depender de
que el usuario abra ninguna ficha ni cambie de mapa — la misma técnica de
"parcheo de tablas en vivo" ya usada para BDSP, aplicada aquí a una
estructura de RAM en vez de a un archivo.

**Cómo se localiza (dos pasos, cada uno demostrado por lectura antes de
escribir nada):**

1. Los NIVELES de cada par nunca cambian aunque el movimiento se sustituya
   (solo cambia qué movimiento aprende, no a qué nivel) — así que la
   secuencia completa de niveles de la tabla vainilla de una especie es un
   ancla estable y muy específica (17 niveles para Eevee, por ejemplo:
   ninguna coincidencia falsa en 8 MiB de RAM real). Se busca por RPC en
   la RAM huésped (direcciones "3DS") con un patrón de bytes: 2 bytes
   comodín (el movimiento) + 2 bytes fijos (el nivel, little-endian) por
   cada entrada.
2. Azahar RECHAZA escrituras RPC en el rango de memoria donde vive este
   búfer (``NEW_LINEAR_HEAP``, confirmado en ``usum_live.py`` para otra
   estructura ya conocida) — la escritura se acepta pero no se aplica de
   verdad. Hace falta escribir por la vía Windows directa
   (``WindowsProcessMemory``), que exige traducir la dirección huésped a
   la dirección real de Windows: se localiza buscando el contenido EXACTO
   ya leído por RPC dentro de las regiones de memoria del proceso real de
   Azahar (validado: todas las copias reales cayeron dentro de la región
   FCRAM más grande, así que solo se escanea esa).

Nunca se toca el nivel de cada par, solo los 2 bytes del movimiento — y
solo cuando el nivel leído justo antes de escribir coincide exactamente
con el esperado (si algo movió el búfer entre localizarlo y escribir, se
aborta esa entrada en vez de escribir a ciegas).
"""

from __future__ import annotations

import re
import struct
from collections.abc import Sequence

from .azahar_rpc import AzaharRPCClient
from .win_process_memory import WindowsProcessMemory

PAIR_STRIDE = 4
GUEST_SCAN_SPAN = 0x800000  # 8 MiB centrados en la base de la party, ya demostrado suficiente.
_MIN_HOST_REGION_SIZE = 32 * 1024 * 1024  # Solo la(s) región(es) FCRAM-sized; evita escanear ~1 GiB.


def _level_anchor_pattern(levels: Sequence[int]) -> bytes:
    """Patrón de expresión regular binaria: comodín+nivel fijo por par."""
    parts: list[bytes] = []
    for level in levels:
        parts.append(b"..")
        parts.append(re.escape(struct.pack("<H", int(level) & 0xFFFF)))
    return b"".join(parts)


def find_guest_cache_addresses(
    client: AzaharRPCClient, *, party_base: int, levels: Sequence[int],
    scan_span: int = GUEST_SCAN_SPAN,
) -> list[int]:
    """Direcciones "3DS" (huésped) donde vive una copia del búfer de anuncio.

    ``levels`` debe ser la secuencia COMPLETA de niveles de la tabla
    vainilla de la especie (en el mismo orden que el GARC) — cuantas más
    entradas, más específico e inequívoco el ancla.
    """
    if not levels:
        return []
    base = int(party_base) - scan_span // 2
    data = client.read_memory(base, scan_span)
    regex = re.compile(_level_anchor_pattern(levels), re.DOTALL)
    return [base + match.start() for match in regex.finditer(data)]


def find_host_addresses_for_pattern(
    wpm: WindowsProcessMemory, handle, pattern: bytes,
    *, min_region_size: int = _MIN_HOST_REGION_SIZE,
) -> list[int]:
    """Direcciones reales de Windows que contienen ``pattern`` exacto.

    Limitado a las regiones grandes (FCRAM-sized) del proceso: escanear
    cada región committed/escribible del proceso (~1 GiB) es demasiado
    lento para hacerlo en cada cambio de rol; las copias reales del búfer
    demostraron caer siempre dentro de la región FCRAM más grande.
    """
    hits: list[int] = []
    for base, size in wpm.iter_writable_regions(handle):
        if size < min_region_size:
            continue
        hits.extend(wpm._scan_region(handle, base, size, pattern))
    return hits


def patch_species_announcement_cache(
    client: AzaharRPCClient,
    wpm: WindowsProcessMemory,
    handle,
    *,
    party_base: int,
    entries: Sequence[tuple[int, int, object]],
    move_ids_by_key: dict[object, int],
    scan_span: int = GUEST_SCAN_SPAN,
) -> int:
    """Reescribe todas las copias del búfer de anuncio de una especie.

    ``entries`` es la tabla VAINILLA completa (``(movimiento, nivel,
    clave)``, la misma forma que ``parse_levelup_garc``). ``move_ids_by_key``
    da el movimiento que DEBERÍA anunciarse para cada ``clave`` — ya
    calculado por quien llama (normalmente copiado directamente del
    archivo del mod, ya demostrado correcto, para no volver a calcular con
    datos que aquí no están disponibles).

    ``scan_span`` es la ventana de búsqueda centrada en ``party_base``
    (por defecto ``GUEST_SCAN_SPAN``, la que demostró bastar para
    USUM/SM). 2026-09-05: para X/Y este búfer vive a ~13 MiB de
    ``XY_PARTY_ADDRESS`` -confirmado leyendo la partida real, 0 coincidencias
    con 8/16 MiB y 2 coincidencias estables con 32 MiB o más-, así que su
    orquestación pasa una ventana más ancha en vez de asumir la misma
    cercanía que Gen 7.

    Devuelve cuántas copias huésped se reescribieron con éxito. Nunca
    lanza por un búfer no encontrado (0 copias es un resultado válido: el
    búfer solo existe mientras el juego lo tiene cargado).
    """
    if not entries:
        return 0
    levels = [int(level) for _move_id, level, _key in entries]
    want_move_ids = [int(move_ids_by_key.get(key, move_id)) for move_id, _level, key in entries]
    guest_addresses = find_guest_cache_addresses(
        client, party_base=party_base, levels=levels, scan_span=scan_span,
    )
    patched = 0
    for guest_address in guest_addresses:
        expected_current = client.read_memory(guest_address, len(entries) * PAIR_STRIDE)
        # Revalida que los niveles siguen donde se esperaba justo antes de
        # traducir a Windows y escribir — si algo movió el búfer entre la
        # localización y este punto, esta copia se descarta sin tocarla.
        current_levels = [
            struct.unpack_from("<H", expected_current, i * PAIR_STRIDE + 2)[0]
            for i in range(len(entries))
        ]
        if current_levels != levels:
            continue
        host_addresses = find_host_addresses_for_pattern(wpm, handle, bytes(expected_current))
        if not host_addresses:
            continue
        payload = b"".join(
            struct.pack("<HH", move_id, level)
            for move_id, level in zip(want_move_ids, levels)
        )
        for host_address in host_addresses:
            readback_before = wpm.read(handle, host_address, len(payload))
            if readback_before != expected_current:
                continue
            wpm.write(handle, host_address, payload)
        patched += 1
    return patched
