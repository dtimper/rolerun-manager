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

No se dieron por buenos. Se comprobaron dos veces:

* Contra **PKHeX**, que generó veinticuatro Pokémon cifrados —uno por cada
  disposición de bloque— con valores conocidos. Todos los campos coinciden.
* Contra **la partida real del usuario**: sus Pokémon se leen enteros y sus seis
  estadísticas, recalculadas desde cero con la tabla personal, salen exactamente
  las que el juego dejó escritas al lado. Si el nivel, los IV, los EV o la
  naturaleza —que aquí sale del PID— estuvieran mal leídos, no cuadrarían.

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
# PS máximos, ataque, defensa, VELOCIDAD, at. especial y def. especial: el orden
# de la tabla personal, no el que usa RoleRun.
PK4_STATS = 0x90

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


def unshuffle_pk4(block: bytes):
    """Desbaraja un PK4 y dice si estaba cifrado.

    HAY DOS ESTADOS, Y HAY QUE RESPETAR EL QUE HAYA

    Un PK4 vive en memoria **cifrado o en claro**, y el juego pasa de uno a otro
    cuando trabaja con ese Pokémon. Medido el 28-08-2026 sobre la partida del
    usuario: de sus cinco miembros, cuatro estaban cifrados y el Hoothoot en
    claro, con `sanity` a 4 en vez de a 0. Leyéndolo descifrado daba la especie
    2288 y un mote de basura; leyéndolo tal cual, la especie 163 y «HOOTHOOT».

    Eso era lo que hacía fallar la lectura entera una y otra vez: no era una RAM
    inquieta, era un miembro en el otro estado.

    El estado **no se deduce del `sanity`**: se demuestra con el checksum, que es
    la prueba que ya se usa para todo lo demás. Si la suma del cuerpo tal cual
    cuadra, está en claro; si cuadra al descifrarlo, está cifrado; si no cuadra
    de ninguna forma, el bloque no vale.

    Todo el registro va en el mismo estado, extensión de combate incluida.

    Devuelve ``(pid, disposición, canónico, cifrado)``.
    """
    if len(block) < PK4_STORED_SIZE:
        raise Pk4Error("El bloque PK4 no llega a 136 bytes.")
    pid = struct.unpack_from("<I", block, 0)[0]
    checksum = struct.unpack_from("<H", block, 6)[0]
    claro = block[8:PK4_STORED_SIZE]
    if sum(struct.unpack("<64H", claro)) & 0xFFFF == checksum:
        cuerpo, cifrado = claro, False
    else:
        cuerpo = _crypt(claro, checksum)
        if sum(struct.unpack("<64H", cuerpo)) & 0xFFFF != checksum:
            raise Pk4Error("Checksum PK4 inválido.")
        cifrado = True
    revueltos = [
        cuerpo[indice * PK4_BLOCK_SIZE:(indice + 1) * PK4_BLOCK_SIZE]
        for indice in range(4)
    ]
    orden = _PERMUTATIONS[((pid >> 13) & 31) % 24]
    canonico = bytearray(block[:8] + b"".join(revueltos[indice] for indice in orden))
    return pid, orden, canonico, cifrado


def reshuffle_pk4(
    pid: int, orden, canonico: bytearray, *, cifrado: bool = True,
) -> bytes:
    """Vuelve a barajar los 136 bytes almacenados, con checksum nuevo.

    ``cifrado`` tiene que ser el estado en el que se leyó: devolver cifrado un
    bloque que el juego tenía en claro lo dejaría ilegible para él.
    """
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
    return bytes(cabecera) + (_crypt(cuerpo, checksum) if cifrado else cuerpo)


# Un nivel va de 1 a 100 y ningún Pokémon de cuarta pasa de 999 PS: con eso se
# distingue una extensión bien leída de una leída en el estado equivocado.
_NIVEL_MAXIMO = 100
_PS_MAXIMOS = 999


def _extension_coherente(cola: bytes) -> bool:
    """Si esos 100 bytes se pueden leer como una extensión de combate."""
    if len(cola) < 0x14:
        return False
    nivel = cola[PK4_LEVEL - PK4_STORED_SIZE]
    actual, maximo = struct.unpack_from("<2H", cola, PK4_CURRENT_HP - PK4_STORED_SIZE)
    return (
        1 <= nivel <= _NIVEL_MAXIMO
        and 0 < maximo <= _PS_MAXIMOS
        and actual <= maximo
    )


def _extension(block: bytes, pid: int, cifrado: bool) -> bytes:
    """La extensión de combate, en claro.

    Normalmente va en el mismo estado que el cuerpo, pero **no siempre**: se ha
    visto un Totodile cuyo cuerpo cuadraba cifrado y cuya extensión estaba en
    claro, y leerla al revés lo dejaba a nivel 50 con 52226 PS.

    La extensión no tiene checksum propio, así que se decide por coherencia: un
    nivel entre 1 y 100, unos PS máximos que quepan en el juego y unos actuales
    que no los pasen. Se prueba primero el estado del cuerpo, que es el caso
    normal, y solo se cambia si ese no sale.
    """
    cola = block[PK4_STORED_SIZE:]
    if not cola:
        return cola
    primera = _crypt(cola, pid) if cifrado else cola
    if _extension_coherente(primera):
        return primera
    segunda = cola if cifrado else _crypt(cola, pid)
    if _extension_coherente(segunda):
        return segunda
    raise Pk4Error(
        "La extensión de combate del PK4 no se puede leer de ninguna de las dos "
        "formas."
    )


def _con_extension(canonico, orden, pid, cifrado, extension) -> bytes:
    """Rearma el registro de combate en el mismo estado en que se leyó."""
    cola = bytes(extension)
    return (
        reshuffle_pk4(pid, orden, canonico, cifrado=cifrado)
        + (_crypt(cola, pid) if cifrado else cola)
    )


def empty_pk4_stored() -> bytes:
    """Como se ve un hueco vacio del PC, que NO son 136 ceros.

    El juego deja un PK4 cifrado con semilla cero: al descifrarlo salen 128
    ceros, su suma es cero y el checksum -tambien cero- cuadra. Se comprobo
    sobre la partida real: el sexto hueco del equipo, con cinco Pokemon dentro,
    pasa el checksum y declara la especie cero. Por eso la especie hay que
    comprobarla aparte.
    """
    return bytes(8) + _crypt(bytes(128), 0)


def empty_pk4_party() -> bytes:
    """Como se ve un hueco vacio del equipo."""
    return empty_pk4_stored() + _crypt(bytes(PK4_PARTY_SIZE - PK4_STORED_SIZE), 0)


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
    pid, _orden, canonico, cifrado = unshuffle_pk4(data[:PK4_STORED_SIZE])
    bloque = bytes(canonico) + _extension(data, pid, cifrado)

    especie = struct.unpack_from("<H", bloque, PK4_SPECIES)[0]
    palabra_iv = struct.unpack_from("<I", bloque, PK4_IV32)[0]
    ivs = _ivs_from_word(palabra_iv)
    evs = {
        clave: bloque[PK4_EV_BASE + indice]
        for indice, clave in enumerate(STAT_ORDER_PERSONAL)
    }
    marcas = bloque[PK4_MARKINGS]
    nivel = bloque[PK4_LEVEL]
    # El juego las guarda en el orden de la tabla personal -PS, Atq, Def, Vel,
    # AtEsp, DefEsp- y RoleRun las usa en el suyo, con la velocidad al final.
    # Se traducen aquí, igual que los IV y los EV, para que quien lea un
    # `Pk4Pokemon` no tenga que acordarse de cuál es cuál.
    crudas = struct.unpack_from("<6H", bloque, PK4_STATS)
    estadisticas = (crudas[0], crudas[1], crudas[2], crudas[4], crudas[5], crudas[3])

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
    pid, _orden, canonico, _cifrado = unshuffle_pk4(data)
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


# --------------------------------------------------------------------------
# Mutaciones: devuelven un bloque nuevo, nunca tocan el que se les pasa
# --------------------------------------------------------------------------

def pk4_party_with_role(
    block: bytes, *, markings, evs, base_stats: dict[str, int],
) -> bytes:
    """El PK4 de combate con marcas, EV y estadísticas recalculadas.

    Cambiar los EV sin recalcular las estadísticas dejaría al Pokémon con los
    valores viejos hasta que el juego los rehiciera por su cuenta, y el PS
    máximo podría no cuadrar con el actual.

    El daño recibido se conserva: si sube el PS máximo, el actual sube lo mismo.
    Un Pokémon debilitado sigue debilitado.

    A diferencia de quinta, la naturaleza **no se lee de un byte**: sale del PID,
    y por eso no hay nada que escribir para ella.
    """
    if len(block) != PK4_PARTY_SIZE:
        raise Pk4Error(f"El bloque PK4 de combate no mide {PK4_PARTY_SIZE} bytes.")
    marcas = tuple(bool(valor) for valor in markings)
    if len(marcas) != 6:
        raise Pk4Error("Las marcas PK4 deben ser exactamente seis.")
    valores_ev = tuple(int(valor) for valor in evs)
    if len(valores_ev) != 6 or any(not 0 <= valor <= 255 for valor in valores_ev):
        raise Pk4Error("Los EV PK4 deben ser seis valores entre 0 y 255.")
    if sum(valores_ev) > 510:
        raise Pk4Error("Los EV PK4 no pueden sumar más de 510.")

    pid, orden, canonico, cifrado = unshuffle_pk4(block[:PK4_STORED_SIZE])
    canonico[PK4_MARKINGS] = sum(
        1 << indice for indice, marcado in enumerate(marcas) if marcado
    )
    ev_por_clave = dict(zip(STAT_ORDER_ROLERUN, valores_ev))
    for indice, clave in enumerate(STAT_ORDER_PERSONAL):
        canonico[PK4_EV_BASE + indice] = ev_por_clave[clave]

    palabra_iv = struct.unpack_from("<I", canonico, PK4_IV32)[0]
    iv_por_clave = _ivs_from_word(palabra_iv)
    extension = bytearray(_extension(block, pid, cifrado))
    nivel = extension[PK4_LEVEL - PK4_STORED_SIZE]
    ps_actual, ps_maximo = struct.unpack_from(
        "<2H", extension, PK4_CURRENT_HP - PK4_STORED_SIZE,
    )
    finales = gen4_final_stats(
        base=base_stats, ivs=iv_por_clave, evs=ev_por_clave,
        level=nivel, nature_id=nature_from_pid(pid),
    )
    nuevo_maximo = int(finales["hp"])
    if ps_actual <= 0:
        nuevo_actual = 0
    else:
        nuevo_actual = max(
            1, min(nuevo_maximo, int(ps_actual) + (nuevo_maximo - int(ps_maximo))),
        )
    struct.pack_into(
        "<7H", extension, PK4_CURRENT_HP - PK4_STORED_SIZE,
        nuevo_actual, nuevo_maximo,
        finales["attack"], finales["defense"], finales["speed"],
        finales["sp_attack"], finales["sp_defense"],
    )
    return _con_extension(canonico, orden, pid, cifrado, extension)


def pk4_party_healed(block: bytes, *, base_pp_for) -> bytes:
    """El PK4 de combate curado: PS al máximo, estado a cero y PP al tope.

    ``base_pp_for`` lo aporta quien llama, que es quien sabe de qué partida se
    trata. Un randomizer puede cambiar los PP de un movimiento, y curar con el
    valor original dejaría el PP mal escrito.
    """
    if len(block) != PK4_PARTY_SIZE:
        raise Pk4Error(f"El bloque PK4 de combate no mide {PK4_PARTY_SIZE} bytes.")
    pid, orden, canonico, cifrado = unshuffle_pk4(block[:PK4_STORED_SIZE])
    extension = bytearray(_extension(block, pid, cifrado))

    # El estado ocupa los cuatro bytes que abren la extensión.
    struct.pack_into("<I", extension, PK4_STATUS - PK4_STORED_SIZE, 0)
    ps_maximo = struct.unpack_from("<H", extension, PK4_MAX_HP - PK4_STORED_SIZE)[0]
    if ps_maximo <= 0:
        raise Pk4Error("El PK4 declara cero PS máximos; no se cura a ciegas.")
    struct.pack_into("<H", extension, PK4_CURRENT_HP - PK4_STORED_SIZE, ps_maximo)

    movimientos = struct.unpack_from("<4H", canonico, PK4_MOVES)
    for indice, move_id in enumerate(movimientos):
        if int(move_id) <= 0:
            canonico[PK4_MOVE_PP + indice] = 0
            continue
        base = int(base_pp_for(int(move_id)))
        if base <= 0:
            raise Pk4Error(
                f"No se conocen los PP base del movimiento #{int(move_id)}; "
                "no se cura con un valor inventado."
            )
        mas_pp = int(canonico[PK4_MOVE_PP_UPS + indice])
        if not 0 <= mas_pp <= 3:
            raise Pk4Error("El PK4 declara unos Más PP fuera de rango.")
        canonico[PK4_MOVE_PP + indice] = min(255, base * (5 + mas_pp) // 5)

    return _con_extension(canonico, orden, pid, cifrado, extension)


# Cuarta generación llega hasta Ataque Aéreo (#467). Un identificador mayor no
# es un movimiento que este juego pueda enseñar.
MOVE_ID_MAX = 467


def pk4_party_with_move(
    block: bytes, move_slot: int, move_id: int, *, base_pp_for,
) -> bytes:
    """El PK4 de combate con un movimiento nuevo en el hueco indicado.

    ``move_slot`` es 1..4, como lo cuenta la interfaz. Los PP quedan al máximo
    del movimiento nuevo y los Más PP de ese hueco vuelven a cero: se aplicaron
    al movimiento anterior y no se heredan.

    No toca la extensión de combate: enseñar un movimiento no cambia PS, estado
    ni estadísticas.
    """
    if len(block) != PK4_PARTY_SIZE:
        raise Pk4Error(f"El bloque PK4 de combate no mide {PK4_PARTY_SIZE} bytes.")
    move_slot = int(move_slot)
    if not 1 <= move_slot <= 4:
        raise Pk4Error("El hueco de movimiento tiene que estar entre 1 y 4.")
    move_id = int(move_id)
    if not 1 <= move_id <= MOVE_ID_MAX:
        raise Pk4Error(f"El movimiento #{move_id} no existe en cuarta generación.")

    pid, orden, canonico, cifrado = unshuffle_pk4(block[:PK4_STORED_SIZE])
    indice = move_slot - 1
    actuales = struct.unpack_from("<4H", canonico, PK4_MOVES)
    # Incluido el propio hueco: el juego tampoco deja enseñar un movimiento que
    # el Pokémon ya conoce, y reescribirlo encima le borraría sus Más PP.
    repetido = next(
        (posicion for posicion, valor in enumerate(actuales) if valor == move_id), None,
    )
    if repetido is not None:
        raise Pk4Error(
            f"Ese Pokémon ya conoce el movimiento #{move_id} en el hueco {repetido + 1}."
        )

    base = int(base_pp_for(move_id) or 0)
    if base <= 0:
        raise Pk4Error(
            f"No se pudo demostrar el PP del movimiento #{move_id}; no se enseñó nada."
        )
    if base > 0xFF:
        raise Pk4Error(f"El PP del movimiento #{move_id} no cabe en un PK4.")

    struct.pack_into("<H", canonico, PK4_MOVES + indice * 2, move_id)
    canonico[PK4_MOVE_PP + indice] = base
    canonico[PK4_MOVE_PP_UPS + indice] = 0
    return (
        reshuffle_pk4(pid, orden, canonico, cifrado=cifrado)
        + block[PK4_STORED_SIZE:]
    )


def pk4_party_without_moves(block: bytes, huecos) -> bytes:
    """El PK4 sin los movimientos indicados, compactando los huecos.

    ``huecos`` son posiciones 1..4. Se borran de atrás hacia delante y el resto
    sube: un Pokémon no puede tener un hueco vacío delante de uno lleno.
    """
    if len(block) != PK4_PARTY_SIZE:
        raise Pk4Error(f"El bloque PK4 de combate no mide {PK4_PARTY_SIZE} bytes.")
    posiciones = sorted({int(valor) for valor in huecos}, reverse=True)
    if not posiciones:
        raise Pk4Error("No hay ningún movimiento que borrar.")
    for posicion in posiciones:
        if not 1 <= posicion <= 4:
            raise Pk4Error("El hueco de movimiento tiene que estar entre 1 y 4.")

    pid, orden, canonico, cifrado = unshuffle_pk4(block[:PK4_STORED_SIZE])
    for posicion in posiciones:
        indice = posicion - 1
        if struct.unpack_from("<H", canonico, PK4_MOVES + indice * 2)[0] == 0:
            raise Pk4Error(f"El hueco {posicion} de ese Pokémon ya estaba vacío.")
        for actual in range(indice, 3):
            siguiente = actual + 1
            struct.pack_into(
                "<H", canonico, PK4_MOVES + actual * 2,
                struct.unpack_from("<H", canonico, PK4_MOVES + siguiente * 2)[0],
            )
            canonico[PK4_MOVE_PP + actual] = canonico[PK4_MOVE_PP + siguiente]
            canonico[PK4_MOVE_PP_UPS + actual] = canonico[PK4_MOVE_PP_UPS + siguiente]
        struct.pack_into("<H", canonico, PK4_MOVES + 3 * 2, 0)
        canonico[PK4_MOVE_PP + 3] = 0
        canonico[PK4_MOVE_PP_UPS + 3] = 0
    return (
        reshuffle_pk4(pid, orden, canonico, cifrado=cifrado)
        + block[PK4_STORED_SIZE:]
    )


def pk4_party_block(stored: bytes, *, pid: int, level: int, stats) -> bytes:
    """Convierte un PK4 del PC (136 B) en uno de combate (236 B).

    Un Pokémon guardado no lleva nivel ni estadísticas: las calcula el juego al
    sacarlo. ``stats`` llega en el orden de RoleRun —PS, Atq, Def, AtEsp, DefEsp,
    Vel— y el bloque las quiere con la velocidad en medio.

    Entra con los PS al máximo, que es como sale del PC.
    """
    if len(stored) != PK4_STORED_SIZE:
        raise Pk4Error(f"Un PK4 almacenado mide {PK4_STORED_SIZE} bytes.")
    # La extensión va en el mismo estado que el cuerpo: si el juego tenía ese
    # Pokémon en claro, cifrar solo la cola lo dejaría ilegible para él.
    _pid, _orden, _canonico, cifrado = unshuffle_pk4(stored)
    level = int(level)
    if not 1 <= level <= 100:
        raise Pk4Error("El nivel del PK4 que entra al equipo está fuera de rango.")
    valores = tuple(int(valor) for valor in stats)
    if len(valores) != 6 or any(valor <= 0 for valor in valores):
        raise Pk4Error("Las estadísticas del PK4 que entra al equipo no son válidas.")
    extension = bytearray(PK4_PARTY_SIZE - PK4_STORED_SIZE)
    extension[PK4_LEVEL - PK4_STORED_SIZE] = level
    struct.pack_into(
        "<7H", extension, PK4_CURRENT_HP - PK4_STORED_SIZE,
        valores[0], valores[0], valores[1], valores[2],
        valores[5], valores[3], valores[4],
    )
    cola = bytes(extension)
    return stored + (_crypt(cola, int(pid)) if cifrado else cola)
