from __future__ import annotations

"""Formato PK4: los Pokémon de cuarta generación.

QUÉ SE HEREDA DE QUINTA Y QUÉ NO

El cifrado es el mismo (``PokeCrypto.Shuffle45`` en PKHeX): el mismo generador
congruencial, la misma semilla —el checksum para el cuerpo y el PID para la
extensión de combate— y las mismas 24 disposiciones de bloque elegidas con
``((pid >> 13) & 31) % 24``. Los cuatro bloques miden 32 bytes igual que en
quinta.

Lo que cambia:

* El registro de combate mide **236 bytes** (136 almacenados + 100), no 220.
* **La naturaleza no se guarda**: en cuarta se deduce del PID (``pid % 25``).
  Quinta la escribió en el bloque B a partir de Blanco/Negro.
* **Los nombres no son UTF-16**: cuarta usa su propia tabla de caracteres, la
  que se volcó de PKHeX en ``data/gen4_charmap.json``.
* La habilidad se guarda tal cual (un byte), sin el bit de habilidad oculta.

CÓMO SE DEMOSTRARON LOS DESPLAZAMIENTOS

No se dieron por buenos: se comprobaron contra el guardado real del usuario.
El recorrido de ``tools_hgss_save_probe.py`` recorre el archivo entero, se
queda con los bloques cuyo checksum cuadra y, para cada uno, recalcula las seis
estadísticas con las bases que declara la ROM. Si el nivel, los IV, los EV o la
naturaleza estuvieran mal leídos, los números no coincidirían con los que el
propio juego dejó escritos al lado.

Este módulo no escribe nunca: solo interpreta bloques que le pasan.
"""

import json
import struct
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PK4_STORED_SIZE = 136
PK4_PARTY_SIZE = 236
PK4_BLOCK_SIZE = 32

_DATA = Path(__file__).resolve().parent.parent / "data"
_CHARMAP_FILE = _DATA / "gen4_charmap.json"
_TERMINATOR = 0xFFFF

# Compartida con quinta: PokeCrypto.Shuffle45.
_PERMUTATIONS = (
    (0, 1, 2, 3), (0, 1, 3, 2), (0, 2, 1, 3), (0, 3, 1, 2), (0, 2, 3, 1), (0, 3, 2, 1),
    (1, 0, 2, 3), (1, 0, 3, 2), (2, 0, 1, 3), (3, 0, 1, 2), (2, 0, 3, 1), (3, 0, 2, 1),
    (1, 2, 0, 3), (1, 3, 0, 2), (2, 1, 0, 3), (3, 1, 0, 2), (2, 3, 0, 1), (3, 2, 0, 1),
    (1, 2, 3, 0), (1, 3, 2, 0), (2, 1, 3, 0), (3, 1, 2, 0), (2, 3, 1, 0), (3, 2, 1, 0),
)

# Desplazamientos dentro del PK4 canónico (descifrado y desbarajado).
PK4_SPECIES = 0x08
PK4_HELD_ITEM = 0x0A
PK4_TID = 0x0C
PK4_SID = 0x0E
PK4_EXPERIENCE = 0x10
PK4_FRIENDSHIP = 0x14
PK4_ABILITY = 0x15
PK4_MARKINGS = 0x16
PK4_LANGUAGE = 0x17
PK4_EV_BASE = 0x18
PK4_MOVES = 0x28
PK4_MOVE_PP = 0x30
PK4_MOVE_PP_UPS = 0x34
PK4_IV32 = 0x38
PK4_FORM_FLAGS = 0x40
PK4_NICKNAME = 0x48
PK4_NICKNAME_CHARS = 11
PK4_OT_NAME = 0x68
PK4_OT_NAME_CHARS = 8

# Extensión de combate, solo en los 236 bytes.
PK4_STATUS = 0x88
PK4_LEVEL = 0x8C
PK4_CURRENT_HP = 0x8E
PK4_MAX_HP = 0x90
PK4_STATS = 0x90        # PS máx., ataque, defensa, velocidad, at. esp., def. esp.

# Cuarta guarda los EV y las estadísticas en el orden de la tabla personal.
STAT_ORDER_PERSONAL = ("hp", "attack", "defense", "speed", "sp_attack", "sp_defense")
STAT_ORDER_ROLERUN = ("hp", "attack", "defense", "sp_attack", "sp_defense", "speed")
# NatureAmp: fila = característica que sube, columna = la que baja.
_NATURE_STAT_ORDER = ("attack", "defense", "speed", "sp_attack", "sp_defense")


class Pk4Error(ValueError):
    """El bloque no es un PK4 válido; RoleRun no lo interpreta ni lo reescribe."""


@lru_cache(maxsize=1)
def _charmap() -> dict[int, str]:
    datos = json.loads(_CHARMAP_FILE.read_text(encoding="utf-8"))
    return {int(codigo): texto for codigo, texto in datos["chars"].items()}


def decode_gen4_string(crudo: bytes) -> str:
    """Traduce un nombre de cuarta a texto, parando en el terminador."""
    tabla = _charmap()
    salida: list[str] = []
    for offset in range(0, len(crudo) - 1, 2):
        codigo = struct.unpack_from("<H", crudo, offset)[0]
        if codigo == _TERMINATOR:
            break
        caracter = tabla.get(codigo)
        if caracter is None:
            # Un código sin asignar no invalida el bloque: el resto del PK4 se
            # ha demostrado por checksum. Se marca y se sigue.
            salida.append("?")
            continue
        salida.append(caracter)
    return "".join(salida).strip()


def _crypt(data: bytes, seed: int) -> bytes:
    out = bytearray(data)
    for offset in range(0, len(out), 2):
        seed = (0x41C64E6D * seed + 0x6073) & 0xFFFFFFFF
        value = struct.unpack_from("<H", out, offset)[0] ^ (seed >> 16)
        struct.pack_into("<H", out, offset, value)
    return bytes(out)


def unshuffle_pk4(block: bytes) -> tuple[int, tuple[int, ...], bytearray]:
    """Descifra y desbaraja un PK4, devolviendo (pid, disposición, canónico)."""
    if len(block) < PK4_STORED_SIZE:
        raise Pk4Error("El bloque PK4 no llega a 136 bytes.")
    pid = struct.unpack_from("<I", block, 0)[0]
    checksum = struct.unpack_from("<H", block, 6)[0]
    body = _crypt(block[8:PK4_STORED_SIZE], checksum)
    if sum(struct.unpack("<64H", body)) & 0xFFFF != checksum:
        raise Pk4Error("Checksum PK4 inválido.")
    revueltos = [
        body[indice * PK4_BLOCK_SIZE:(indice + 1) * PK4_BLOCK_SIZE] for indice in range(4)
    ]
    orden = _PERMUTATIONS[((pid >> 13) & 31) % 24]
    canonico = bytearray(block[:8] + b"".join(revueltos[indice] for indice in orden))
    return pid, orden, canonico


def reshuffle_pk4(pid: int, orden: tuple[int, ...], canonico: bytearray) -> bytes:
    """Vuelve a barajar y cifrar los 136 bytes almacenados, con checksum nuevo."""
    bloques = [
        bytes(canonico[8 + indice * PK4_BLOCK_SIZE:8 + (indice + 1) * PK4_BLOCK_SIZE])
        for indice in range(4)
    ]
    revueltos = [b""] * 4
    for destino, origen in enumerate(orden):
        revueltos[origen] = bloques[destino]
    cuerpo = b"".join(revueltos)
    checksum = sum(struct.unpack("<64H", cuerpo)) & 0xFFFF
    cabecera = bytearray(canonico[:8])
    struct.pack_into("<H", cabecera, 6, checksum)
    return bytes(cabecera) + _crypt(cuerpo, checksum)


def nature_from_pid(pid: int) -> int:
    """En cuarta la naturaleza no se guarda: sale del PID."""
    return int(pid) % 25


def gen4_final_stats(
    *, base: dict[str, int], ivs: dict[str, int], evs: dict[str, int],
    level: int, nature_id: int,
) -> dict[str, int]:
    """Estadísticas finales; la fórmula es la misma que en quinta."""
    level = int(level)
    if not 1 <= level <= 100:
        raise Pk4Error("El nivel PK4 está fuera de rango para calcular estadísticas.")
    sube, baja = divmod(int(nature_id), 5)
    neutra = sube == baja
    aumentada = None if neutra else _NATURE_STAT_ORDER[sube]
    reducida = None if neutra else _NATURE_STAT_ORDER[baja]

    salida: dict[str, int] = {}
    for clave in STAT_ORDER_PERSONAL:
        comun = (2 * int(base[clave]) + int(ivs[clave]) + int(evs[clave]) // 4) * level // 100
        if clave == "hp":
            salida[clave] = comun + level + 10
            continue
        valor = comun + 5
        if clave == aumentada:
            valor = valor * 11 // 10
        elif clave == reducida:
            valor = valor * 9 // 10
        salida[clave] = valor
    return salida


@dataclass(frozen=True, slots=True)
class Pk4Pokemon:
    slot: int
    pid: int
    species_id: int
    nickname: str
    ot_name: str
    level: int
    experience: int
    held_item_id: int
    ability_id: int
    move_ids: tuple[int, int, int, int]
    move_pp: tuple[int, int, int, int]
    move_pp_ups: tuple[int, int, int, int]
    markings: tuple[bool, bool, bool, bool, bool, bool]
    tid: int
    sid: int
    form: int
    nature_id: int
    is_egg: bool
    status_condition: int
    stats: tuple[int, int, int, int, int, int]
    ivs: tuple[int, int, int, int, int, int]
    evs: tuple[int, int, int, int, int, int]
    current_hp: int
    max_hp: int


def _ivs_from_word(palabra: int) -> dict[str, int]:
    return {
        "hp": palabra & 31,
        "attack": (palabra >> 5) & 31,
        "defense": (palabra >> 10) & 31,
        "speed": (palabra >> 15) & 31,
        "sp_attack": (palabra >> 20) & 31,
        "sp_defense": (palabra >> 25) & 31,
    }


def parse_pk4_party(data: bytes, slot: int) -> Pk4Pokemon:
    """Interpreta los 236 bytes de un miembro del equipo."""
    if len(data) != PK4_PARTY_SIZE:
        raise Pk4Error(f"Un PK4 de combate mide {PK4_PARTY_SIZE} bytes.")
    pid, _orden, canonico = unshuffle_pk4(data[:PK4_STORED_SIZE])
    extension = _crypt(data[PK4_STORED_SIZE:], pid)
    bloque = bytes(canonico) + extension

    especie = struct.unpack_from("<H", bloque, PK4_SPECIES)[0]
    palabra_iv = struct.unpack_from("<I", bloque, PK4_IV32)[0]
    ivs = _ivs_from_word(palabra_iv)
    evs = {
        clave: bloque[PK4_EV_BASE + indice]
        for indice, clave in enumerate(STAT_ORDER_PERSONAL)
    }
    marcas = bloque[PK4_MARKINGS]
    nivel = bloque[PK4_LEVEL]
    estadisticas = struct.unpack_from("<6H", bloque, PK4_STATS)

    return Pk4Pokemon(
        slot=int(slot),
        pid=pid,
        species_id=especie,
        nickname=decode_gen4_string(bloque[PK4_NICKNAME:PK4_NICKNAME + PK4_NICKNAME_CHARS * 2]),
        ot_name=decode_gen4_string(bloque[PK4_OT_NAME:PK4_OT_NAME + PK4_OT_NAME_CHARS * 2]),
        level=nivel,
        experience=struct.unpack_from("<I", bloque, PK4_EXPERIENCE)[0],
        held_item_id=struct.unpack_from("<H", bloque, PK4_HELD_ITEM)[0],
        ability_id=bloque[PK4_ABILITY],
        move_ids=tuple(struct.unpack_from("<4H", bloque, PK4_MOVES)),
        move_pp=tuple(bloque[PK4_MOVE_PP:PK4_MOVE_PP + 4]),
        move_pp_ups=tuple(bloque[PK4_MOVE_PP_UPS:PK4_MOVE_PP_UPS + 4]),
        markings=tuple(bool(marcas & (1 << indice)) for indice in range(6)),
        tid=struct.unpack_from("<H", bloque, PK4_TID)[0],
        sid=struct.unpack_from("<H", bloque, PK4_SID)[0],
        form=bloque[PK4_FORM_FLAGS] >> 3,
        nature_id=nature_from_pid(pid),
        # El bit de huevo vive en el mismo entero que los IV.
        is_egg=bool((palabra_iv >> 30) & 1),
        status_condition=bloque[PK4_STATUS],
        stats=tuple(estadisticas),
        ivs=tuple(ivs[clave] for clave in STAT_ORDER_ROLERUN),
        evs=tuple(evs[clave] for clave in STAT_ORDER_ROLERUN),
        current_hp=struct.unpack_from("<H", bloque, PK4_CURRENT_HP)[0],
        max_hp=estadisticas[0],
    )


def parse_pk4_boxed(data: bytes, slot: int) -> Pk4Pokemon | None:
    """Interpreta los 136 bytes de un hueco del PC, o ``None`` si está vacío."""
    if len(data) != PK4_STORED_SIZE:
        raise Pk4Error(f"Un PK4 almacenado mide {PK4_STORED_SIZE} bytes.")
    if not any(data):
        return None
    pid, _orden, canonico = unshuffle_pk4(data)
    bloque = bytes(canonico)
    especie = struct.unpack_from("<H", bloque, PK4_SPECIES)[0]
    if especie == 0:
        return None
    palabra_iv = struct.unpack_from("<I", bloque, PK4_IV32)[0]
    ivs = _ivs_from_word(palabra_iv)
    evs = {
        clave: bloque[PK4_EV_BASE + indice]
        for indice, clave in enumerate(STAT_ORDER_PERSONAL)
    }
    marcas = bloque[PK4_MARKINGS]
    return Pk4Pokemon(
        slot=int(slot),
        pid=pid,
        species_id=especie,
        nickname=decode_gen4_string(bloque[PK4_NICKNAME:PK4_NICKNAME + PK4_NICKNAME_CHARS * 2]),
        ot_name=decode_gen4_string(bloque[PK4_OT_NAME:PK4_OT_NAME + PK4_OT_NAME_CHARS * 2]),
        # Un PK4 almacenado no lleva nivel: se deduce de la experiencia con la
        # curva de la especie, cosa que este módulo no sabe. Cero significa
        # «todavía no calculado», nunca «nivel cero».
        level=0,
        experience=struct.unpack_from("<I", bloque, PK4_EXPERIENCE)[0],
        held_item_id=struct.unpack_from("<H", bloque, PK4_HELD_ITEM)[0],
        ability_id=bloque[PK4_ABILITY],
        move_ids=tuple(struct.unpack_from("<4H", bloque, PK4_MOVES)),
        move_pp=tuple(bloque[PK4_MOVE_PP:PK4_MOVE_PP + 4]),
        move_pp_ups=tuple(bloque[PK4_MOVE_PP_UPS:PK4_MOVE_PP_UPS + 4]),
        markings=tuple(bool(marcas & (1 << indice)) for indice in range(6)),
        tid=struct.unpack_from("<H", bloque, PK4_TID)[0],
        sid=struct.unpack_from("<H", bloque, PK4_SID)[0],
        form=bloque[PK4_FORM_FLAGS] >> 3,
        nature_id=nature_from_pid(pid),
        is_egg=bool((palabra_iv >> 30) & 1),
        status_condition=0,
        stats=(0, 0, 0, 0, 0, 0),
        ivs=tuple(ivs[clave] for clave in STAT_ORDER_ROLERUN),
        evs=tuple(evs[clave] for clave in STAT_ORDER_ROLERUN),
        current_hp=0,
        max_hp=0,
    )
