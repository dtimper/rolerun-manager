from __future__ import annotations

import ctypes
import functools
import json
import os
import struct
import threading
import time
from dataclasses import dataclass
from ctypes import wintypes
from pathlib import Path

from . import perf
from .gen5_memory import GEN5_MEMORY, Gen5Memory


DS_RAM_BASE = 0x02000000
# Las direcciones de Negro 2, que este módulo conserva como alias por
# compatibilidad. La fuente única es `gen5_memory`: ahí solo se mide el ancla
# del equipo y el resto sale de los desplazamientos del guardado. Derivarlas
# aquí evita que las dos copias puedan divergir.
_B2W2 = GEN5_MEMORY["b2w2"]
PARTY_COUNT = _B2W2.party_count
PARTY_BASE = _B2W2.party_data
PK5_PARTY_SIZE = 220
PK5_STORED_SIZE = 136
MAX_PARTY = 6
# Negro 2 España / melonDS 1.1. Captura controlada del 26-08-2026: con la
# party 6/6, Azurill, Lillipup y el Sewaddle recién capturado ocuparon Caja 1
# slots 1..3. La matriz completa dio 3 PK5 y 717 vacíos checksum-válidos en
# dos lecturas idénticas. Cada caja contiene 30*136 bytes y 16 bytes auxiliares.
PC_BASE = _B2W2.pc
PC_BOX_COUNT = 24
PC_BOX_SLOT_COUNT = 30
PC_BOX_STRIDE = 0x1000
PC_BOX_DATA_SIZE = PC_BOX_SLOT_COUNT * PK5_STORED_SIZE
PC_MATRIX_SIZE = PC_BOX_COUNT * PC_BOX_STRIDE
# Negro 2 España / melonDS 1.1. La captura física del 26-08-2026 demostró
# dos filas con el mismo Tepig. La segunda publicó el KO 3,36 s antes y es la
# fuente inmediata; la primera se conserva como testigo de convergencia.
BATTLE_MIRROR_BASE = _B2W2.battle_presentation
BATTLE_IMMEDIATE_BASE = _B2W2.battle_logical
BATTLE_ROW_SIZE = 14
# Captura controlada del 26-08-2026: el byte situado a +0x14 de la copia de
# presentación pasó 0 -> 1 al mostrarse PAR y volvió a 0 fuera del combate.
# Se lee junto a la fila, pero solo se publica el valor observado (1 = PAR).
BATTLE_STATUS_OFFSET = 0x14
BATTLE_READ_SIZE = BATTLE_STATUS_OFFSET + 1
# Una vez demostrada la base del mapeo, cada lectura la revalida con la misma
# doble lectura count+party. Aun asi se rehace el descubrimiento completo cada
# cierto tiempo: la comprobacion de ambiguedad -que solo existe en el recorrido
# completo- debe seguir ejecutandose por si aparece una segunda party valida
# dentro del mismo proceso a mitad de sesion.
BASE_REDISCOVERY_SECONDS = 60.0
# Negro 2 España / melonDS 1.1. Traza de dos estados del 27-08-2026: la Poción
# del jugador estaba en 0x0221E17C y paso de 2 a 3 unidades en esa misma
# direccion al usar una; la casilla contigua contenia Antiparalizador, un objeto
# por el que la busqueda no preguntaba. El mapa posterior encontro cuatro tiras
# de objetos coherentes por tipo, y las distancias entre sus inicios -1240, 1572
# y 2008- coinciden BYTE A BYTE con SAV5B2W2.Inventory.Pouches de PKHeX en tres
# fronteras independientes. El bolsillo Items empieza aqui.
BAG_BASE = _B2W2.bag
BAG_SLOT_SIZE = 4
BAG_MAX_QUANTITY = 999
# Demostrado con la traza de dos estados del 27-08-2026: de 2 candidatos
# iniciales, esta es la unica direccion que paso de 4524 a 4224 al gastar dinero
# dentro del juego (diagnostics/manual/b2w2_bag_latest.json).
MONEY_ADDRESS = _B2W2.money
# TRES bytes, no cuatro. PKHeX solo toca 0x21100..0x21102 del guardado al
# cambiar el dinero, y el guardado real del usuario confirma la equivalencia:
# ahi pone 4524, que es exactamente el valor con el que empezo la traza.
# Escribir cuatro pisaba el byte siguiente, que no es del dinero.
MONEY_SIZE = 3
# Es el tope que escribe la utilidad de RoleRun. Un limite mayor no esta
# demostrado en B2/W2, asi que no se admite.
MONEY_MAX = 999_999
# Cuatro bytes despues del dinero, un bit por medalla. La relacion sale del
# propio PKHeX: cambiar Misc5B2W2.Badges mueve el byte 0x21104 del guardado y
# el dinero los 0x21100..0x21102, o sea dinero + 4. Es la misma vecindad que
# ORAS, donde ORAS_BADGES_ADDRESS tambien es ORAS_MONEY_ADDRESS + 4.
BADGES_ADDRESS = _B2W2.badges
BADGES_SIZE = 1
BADGES_TOTAL = 8
# Demostrado con la captura del 27-08-2026 (b2w2_tm_table_latest.json). En los
# 4 MiB de RAM hay UN solo tramo con la forma de una tabla de MT —101 valores de
# 16 bits seguidos, todos entre 1 y 559 y todos distintos— y, indexado por
# objeto, coincide 101 de 101 con la lista derivada de PKHeX.
#
# El orden es el de los objetos, no el de los numeros de MT: MT01-MT92
# (objetos 328-419), MO01-MO06 (420-425) y MT93-MT95 (618-620).
#
# Se lee en vivo justamente porque RoleRun se juega en randomizers: un
# randomizer cambia el contenido de esta tabla, no su posicion.
TM_TABLE_BASE = _B2W2.tm_table
TM_TABLE_COUNT = 101
# Ultimo movimiento de quinta generacion.
MOVE_ID_MAX = 559
_BAG_LAYOUT_PATH = Path(__file__).resolve().parent.parent / "data" / "b2w2_bag_layout.json"


@dataclass(frozen=True, slots=True)
class B2W2BagPocket:
    tipo: str
    offset: int
    slots: int
    legal: frozenset[int]


@dataclass(frozen=True, slots=True)
class B2W2BagEntry:
    pocket: str
    slot: int
    item_id: int
    quantity: int


@dataclass(frozen=True, slots=True)
class B2W2BagRead:
    process_id: int
    process_name: str
    allocation_base: int
    guest_base: int
    raw: bytes
    entries: tuple[B2W2BagEntry, ...]

    def by_pocket(self, tipo: str) -> tuple[B2W2BagEntry, ...]:
        return tuple(entry for entry in self.entries if entry.pocket == tipo)

    def quantity_of(self, item_id: int) -> int:
        return sum(
            entry.quantity for entry in self.entries if entry.item_id == int(item_id)
        )


@functools.lru_cache(maxsize=1)
def bag_pockets() -> tuple[B2W2BagPocket, ...]:
    """Reparto de bolsillos y objetos legales, extraido de PKHeX.

    El numero de huecos de cada bolsillo se deduce de la distancia hasta el
    siguiente, que es exactamente lo que se midio en la RAM real.
    """
    try:
        documento = json.loads(_BAG_LAYOUT_PATH.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise B2W2LiveError("Falta data/b2w2_bag_layout.json.") from exc
    crudos = list(documento.get("bolsillos", []))
    if not crudos:
        raise B2W2LiveError("El reparto de bolsillos B2/W2 esta vacio.")
    pockets: list[B2W2BagPocket] = []
    for indice, bolsillo in enumerate(crudos):
        offset = int(bolsillo["desplazamiento"])
        if indice + 1 < len(crudos):
            siguiente = int(crudos[indice + 1]["desplazamiento"])
        else:
            siguiente = offset + int(bolsillo["huecos"]) * BAG_SLOT_SIZE
        huecos = (siguiente - offset) // BAG_SLOT_SIZE
        if huecos <= 0:
            raise B2W2LiveError("Reparto de bolsillos B2/W2 incoherente.")
        pockets.append(B2W2BagPocket(
            tipo=str(bolsillo["tipo"]),
            offset=offset,
            slots=huecos,
            legal=frozenset(int(value) for value in bolsillo.get("items_legales", ())),
        ))
    return tuple(pockets)


def bag_size() -> int:
    ultimo = bag_pockets()[-1]
    return ultimo.offset + ultimo.slots * BAG_SLOT_SIZE


def parse_bag(raw: bytes) -> tuple[B2W2BagEntry, ...]:
    """Decodifica la mochila entera y rechaza cualquier bolsillo incoherente.

    Cada bolsillo esta compactado: sus objetos ocupan los primeros huecos y el
    resto queda a cero. Un hueco vacio detras de uno lleno, un identificador que
    no pertenece a ese bolsillo, una cantidad imposible o un objeto repetido
    significan que no se esta leyendo una mochila, y se rechaza entera en lugar
    de publicar medio inventario inventado.
    """
    esperado = bag_size()
    if len(raw) != esperado:
        raise B2W2LiveError(f"El bloque de mochila B2/W2 no mide {esperado} bytes.")
    entradas: list[B2W2BagEntry] = []
    for pocket in bag_pockets():
        vistos: set[int] = set()
        terminado = False
        for hueco in range(pocket.slots):
            posicion = pocket.offset + hueco * BAG_SLOT_SIZE
            item_id, cantidad = struct.unpack_from("<HH", raw, posicion)
            if item_id == 0:
                terminado = True
                if cantidad != 0:
                    raise B2W2LiveError(
                        f"Hueco vacio con cantidad en el bolsillo {pocket.tipo} B2/W2."
                    )
                continue
            if terminado:
                raise B2W2LiveError(
                    f"El bolsillo {pocket.tipo} B2/W2 no esta compactado."
                )
            if pocket.legal and item_id not in pocket.legal:
                raise B2W2LiveError(
                    f"Objeto #{item_id} imposible en el bolsillo {pocket.tipo} B2/W2."
                )
            if not 1 <= cantidad <= BAG_MAX_QUANTITY:
                raise B2W2LiveError(
                    f"Cantidad imposible del objeto #{item_id} en B2/W2: {cantidad}."
                )
            if item_id in vistos:
                raise B2W2LiveError(
                    f"Objeto #{item_id} repetido en el bolsillo {pocket.tipo} B2/W2."
                )
            vistos.add(item_id)
            entradas.append(B2W2BagEntry(pocket.tipo, hueco, item_id, cantidad))
    return tuple(entradas)


def parse_b2w2_badges(raw: bytes) -> int:
    """Cuenta las medallas de un byte de bits. Ocho como maximo."""
    if len(raw) != BADGES_SIZE:
        raise B2W2LiveError("El byte de medallas B2/W2 no mide un byte.")
    return int(bin(raw[0]).count("1"))


def bag_pocket_for(item_id: int) -> B2W2BagPocket:
    """Bolsillo al que pertenece un objeto, segun el reparto de PKHeX."""
    for pocket in bag_pockets():
        if int(item_id) in pocket.legal:
            return pocket
    raise B2W2LiveError(
        f"El objeto #{int(item_id)} no pertenece a ningun bolsillo de B2/W2."
    )


def set_bag_quantity(raw: bytes, item_id: int, quantity: int) -> bytes:
    """Fija la cantidad de un objeto conservando el compactado del bolsillo.

    Si el objeto ya esta, solo cambia su cantidad y no mueve nada. Si no esta, se
    anade en el primer hueco libre, que es justo detras del ultimo ocupado: es la
    unica posicion que mantiene el bolsillo compactado, que es lo que el juego
    espera y lo que ``parse_bag`` exige.
    """
    item_id, quantity = int(item_id), int(quantity)
    if not 1 <= quantity <= BAG_MAX_QUANTITY:
        raise B2W2LiveError(
            f"B2/W2 admite entre 1 y {BAG_MAX_QUANTITY} unidades por objeto."
        )
    pocket = bag_pocket_for(item_id)
    # Releer con el parser de produccion: si la mochila de partida no fuera
    # valida, no se escribe encima de ella.
    actuales = [e for e in parse_bag(raw) if e.pocket == pocket.tipo]
    destino = next((e.slot for e in actuales if e.item_id == item_id), None)
    if destino is None:
        destino = len(actuales)
        if destino >= pocket.slots:
            raise B2W2LiveError(f"El bolsillo {pocket.tipo} de B2/W2 esta lleno.")
    nuevo = bytearray(raw)
    struct.pack_into(
        "<HH", nuevo, pocket.offset + destino * BAG_SLOT_SIZE, item_id, quantity,
    )
    resultado = bytes(nuevo)
    # El resultado tiene que seguir siendo una mochila legible; si no, se rechaza
    # antes de tocar un solo byte de la partida.
    parse_bag(resultado)
    return resultado



class _PROCESSENTRY32W(ctypes.Structure):
    """Entrada de la instantánea de procesos de Windows.

    Definida **una sola vez** a propósito. Estaba declarada dentro de la función
    que enumera procesos, de modo que cada llamada creaba una clase nueva y
    volvía a fijar ``argtypes``. Con dos hilos leyendo a la vez —el monitor, el
    sondeo del PC y una escritura pueden solaparse— uno pisaba los tipos del otro
    y la llamada en curso fallaba con:

        expected LP_PROCESSENTRY32W instance instead of pointer to PROCESSENTRY32W

    Dos clases distintas con el mismo nombre. El error se veía como «no se pudo
    aplicar la sustitución», que no tenía nada que ver con la sustitución.
    """

    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
    ]


def _load_kernel32():
    """Instancia **privada** de kernel32 para B2/W2.

    ``ctypes.windll.kernel32`` es un singleton de todo el proceso y su caché de
    funciones también. Cuatro módulos de RoleRun declaran su propia
    ``PROCESSENTRY32W`` y fijan ``argtypes`` sobre ese mismo objeto compartido,
    así que cualquiera podía invalidar los tipos de otro en mitad de una llamada.
    Con una instancia propia, B2/W2 queda aislado de los demás.
    """
    if os.name != "nt":
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.ReadProcessMemory.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel32.ReadProcessMemory.restype = wintypes.BOOL
    kernel32.WriteProcessMemory.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel32.WriteProcessMemory.restype = wintypes.BOOL
    kernel32.VirtualQueryEx.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
    ]
    kernel32.VirtualQueryEx.restype = ctypes.c_size_t
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


_KERNEL32 = _load_kernel32()


def _serialized(method):
    """Serializa una operación del lector sobre la RAM de melonDS.

    El monitor, el sondeo del PC y las escrituras corren en hilos distintos y
    comparten este lector. Sin serializar, dos lecturas podían solaparse sobre el
    mismo estado y una escritura podía intercalarse entre la doble lectura de
    seguridad que precede a cada commit. Es reentrante a propósito: los writers
    releen la party y el PC dentro de su propia transacción.
    """

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


class B2W2LiveError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class B2W2Pokemon:
    slot: int
    pid: int
    species_id: int
    nickname: str
    level: int
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


@dataclass(frozen=True, slots=True)
class B2W2PartyRead:
    process_id: int
    process_name: str
    allocation_base: int
    count: int
    raw: bytes
    pokemon: tuple[B2W2Pokemon, ...]


@dataclass(frozen=True, slots=True)
class B2W2BoxPokemon:
    box: int
    slot: int
    pid: int
    species_id: int
    nickname: str
    experience: int
    held_item_id: int
    ability_id: int
    move_ids: tuple[int, int, int, int]
    markings: tuple[bool, bool, bool, bool, bool, bool]
    tid: int
    sid: int
    form: int
    nature_id: int
    is_egg: bool
    ivs: tuple[int, int, int, int, int, int]
    evs: tuple[int, int, int, int, int, int]


@dataclass(frozen=True, slots=True)
class B2W2PCRead:
    process_id: int
    process_name: str
    allocation_base: int
    guest_base: int
    raw: bytes
    empty_slots: int
    pokemon: tuple[B2W2BoxPokemon, ...]


@dataclass(frozen=True, slots=True)
class B2W2RoleWrite:
    """Petición de cambio de rol sobre un miembro concreto de la party.

    ``base_stats`` lo aporta el adaptador, que es quien conoce la tabla personal
    de la edición. El lector no consulta datos de juego por su cuenta.
    """

    slot: int
    identity: tuple[int, int, int]
    markings: tuple[bool, bool, bool, bool, bool, bool]
    evs: tuple[int, int, int, int, int, int]
    base_stats: dict


@dataclass(frozen=True, slots=True)
class B2W2PCMovePlan:
    source_offset: int
    destination_offset: int
    source: bytes
    destination: bytes
    expected: bytes
    pokemon: B2W2BoxPokemon


@dataclass(frozen=True, slots=True)
class B2W2BattleRead:
    active: bool
    party_slot: int | None = None
    current_hp: int = 0
    max_hp: int = 0
    mirror_hp: int = 0
    immediate_hp: int = 0
    converged: bool = False
    status_condition: int = 0


def _crypt(data: bytes, seed: int) -> bytes:
    out = bytearray(data)
    for offset in range(0, len(out), 2):
        seed = (0x41C64E6D * seed + 0x6073) & 0xFFFFFFFF
        value = struct.unpack_from("<H", out, offset)[0] ^ (seed >> 16)
        struct.pack_into("<H", out, offset, value)
    return bytes(out)


def empty_pk5_stored() -> bytes:
    """Representación vacía de un slot PC (136 B) en Negro 2.

    Un slot PC liberado **no** queda a ceros: el juego deja un PK5 almacenado
    cifrado con semilla 0. La captura física ``b2w2_party_resize_latest.json``
    lo demuestra: tras retirar un Pokémon desde el propio juego, el parser de
    producción leyó ``pc_empty: 717`` sin lanzar, y ese parser rechaza 136 ceros
    por checksum inválido. Es además el mismo prefijo que la cola de party ya
    validada físicamente en alpha.13.
    """
    return bytes(8) + _crypt(bytes(128), 0)


def empty_pk5_party() -> bytes:
    """Representación vacía observada al compactar party en Negro 2."""
    return empty_pk5_stored() + _crypt(bytes(84), 0)


# Desplazamientos dentro del PK5 canónico (bloque descifrado y desbarajado).
# Demostrados por el propio lector: ``parse_pk5_boxed`` lee las marcas en 0x16 y
# los EV en 0x18-0x1D, y esa lectura ya está validada físicamente.
PK5_MARKINGS_OFFSET = 0x16
# Orden de la tabla personal de PKHeX y de la extensión de party de Gen 5.
STAT_ORDER_PERSONAL = ("hp", "attack", "defense", "speed", "sp_attack", "sp_defense")
# Orden con el que RoleRun presenta y almacena IV y EV.
STAT_ORDER_ROLERUN = ("hp", "attack", "defense", "sp_attack", "sp_defense", "speed")
# ``parse_pk5_party`` lee los PP en 0x30-0x33 y los Más PP en 0x34-0x37.
PK5_MOVE_OFFSET = 0x28
PK5_MOVE_PP_OFFSET = 0x30
PK5_MOVE_PP_UPS_OFFSET = 0x34
PK5_EV_OFFSETS = {
    "hp": 0x18, "attack": 0x19, "defense": 0x1A,
    "speed": 0x1B, "sp_attack": 0x1C, "sp_defense": 0x1D,
}
# NatureAmp: fila = característica que sube, columna = la que baja.
_NATURE_STAT_ORDER = ("attack", "defense", "speed", "sp_attack", "sp_defense")


def gen5_final_stats(
    *, base: dict[str, int], ivs: dict[str, int], evs: dict[str, int],
    level: int, nature_id: int,
) -> dict[str, int]:
    """Estadísticas finales de tercera generación en adelante.

    PS = ((2·Base + IV + EV/4) · Nivel / 100) + Nivel + 10
    Resto = (((2·Base + IV + EV/4) · Nivel / 100) + 5) · modificador de naturaleza

    Todas las divisiones son enteras y el modificador se aplica al final, que es
    el orden que produce los valores que muestra el juego.
    """
    level = int(level)
    if not 1 <= level <= 100:
        raise B2W2LiveError("El nivel PK5 está fuera de rango para calcular estadísticas.")
    up_index, down_index = divmod(int(nature_id), 5)
    neutral = up_index == down_index
    increased = None if neutral else _NATURE_STAT_ORDER[up_index]
    decreased = None if neutral else _NATURE_STAT_ORDER[down_index]

    result: dict[str, int] = {}
    for key in STAT_ORDER_PERSONAL:
        common = (2 * int(base[key]) + int(ivs[key]) + int(evs[key]) // 4) * level // 100
        if key == "hp":
            result[key] = common + level + 10
            continue
        value = common + 5
        if key == increased:
            value = value * 11 // 10
        elif key == decreased:
            value = value * 9 // 10
        result[key] = value
    return result


def _unshuffle_pk5(block: bytes) -> tuple[int, tuple[int, ...], bytearray]:
    """Descifra y desbaraja un PK5, devolviendo (pid, permutación, canónico)."""
    pid = struct.unpack_from("<I", block, 0)[0]
    checksum = struct.unpack_from("<H", block, 6)[0]
    body = _crypt(block[8:136], checksum)
    if sum(struct.unpack("<64H", body)) & 0xFFFF != checksum:
        raise B2W2LiveError("Checksum PK5 inválido; RoleRun no reescribe ese bloque.")
    shuffled = [body[index * 32:(index + 1) * 32] for index in range(4)]
    order = _PERMUTATIONS[((pid >> 13) & 31) % 24]
    canonical = bytearray(block[:8] + b"".join(shuffled[index] for index in order))
    return pid, order, canonical


def _reshuffle_pk5(pid: int, order: tuple[int, ...], canonical: bytearray) -> bytes:
    """Recalcula el checksum, vuelve a barajar y cifra los 136 bytes almacenados."""
    checksum = sum(struct.unpack("<64H", bytes(canonical[8:136]))) & 0xFFFF
    canonical_blocks = [bytes(canonical[8 + index * 32:8 + (index + 1) * 32]) for index in range(4)]
    stored_blocks: list[bytes] = [b""] * 4
    for canonical_index, stored_index in enumerate(order):
        stored_blocks[stored_index] = canonical_blocks[canonical_index]
    header = bytes(canonical[:6]) + struct.pack("<H", checksum)
    return header + _crypt(b"".join(stored_blocks), checksum)


def pk5_party_healed(block: bytes, *, base_pp_for) -> bytes:
    """Devuelve el PK5 de party completamente curado.

    Curar en RoleRun es lo que hace un Centro Pokémon: PS al máximo, estado
    alterado a cero y PP de los cuatro movimientos al tope, contando los Más PP
    que cada movimiento tenga aplicados.

    ``base_pp_for`` debe devolver el PP base **de quinta generación**. No se
    admite un cero: varios movimientos cambiaron de PP entre generaciones, así
    que un PP desconocido detiene la curación en lugar de inventar un valor.
    """
    if len(block) != PK5_PARTY_SIZE:
        raise B2W2LiveError("El bloque PK5 de party no mide 220 bytes.")
    pid, order, canonical = _unshuffle_pk5(block)

    for index in range(4):
        move_id = struct.unpack_from("<H", canonical, PK5_MOVE_OFFSET + index * 2)[0]
        pp_ups = canonical[PK5_MOVE_PP_UPS_OFFSET + index]
        if move_id == 0:
            canonical[PK5_MOVE_PP_OFFSET + index] = 0
            continue
        if not 0 <= pp_ups <= 3:
            raise B2W2LiveError(
                f"Los Más PP del movimiento #{move_id} son incoherentes; no se curó nada."
            )
        base_pp = int(base_pp_for(int(move_id)) or 0)
        if base_pp <= 0:
            raise B2W2LiveError(
                f"No se pudo demostrar el PP máximo del movimiento #{move_id}; no se curó nada."
            )
        maximo = base_pp * (5 + int(pp_ups)) // 5
        if maximo > 0xFF:
            raise B2W2LiveError(f"El PP calculado del movimiento #{move_id} no cabe en PK5.")
        canonical[PK5_MOVE_PP_OFFSET + index] = maximo

    extension = bytearray(_crypt(block[136:], pid))
    # El estado alterado vive en los cuatro primeros bytes de la extensión de
    # party; los PS actuales, justo después del nivel.
    struct.pack_into("<I", extension, 0, 0)
    maximo_ps = struct.unpack_from("<H", extension, 0x90 - 0x88)[0]
    if maximo_ps <= 0:
        raise B2W2LiveError("Los PS máximos del PK5 son inválidos; no se curó nada.")
    struct.pack_into("<H", extension, 0x8E - 0x88, maximo_ps)

    return _reshuffle_pk5(pid, order, canonical) + _crypt(bytes(extension), pid)


def pk5_party_with_move(
    block: bytes, move_slot: int, move_id: int, *, base_pp_for,
) -> bytes:
    """Devuelve el PK5 de party con un movimiento nuevo en el hueco indicado.

    ``move_slot`` es 1..4, como lo cuenta la interfaz. Los PP quedan al máximo
    del movimiento nuevo y los Más PP de ese hueco vuelven a cero, que es lo que
    hace el juego al enseñar una MT: los Más PP se aplicaron al movimiento
    anterior y no se heredan.

    En quinta generación las MT son reutilizables, así que enseñar no gasta el
    objeto. Nada de la mochila se toca aquí.
    """
    if len(block) != PK5_PARTY_SIZE:
        raise B2W2LiveError("El bloque PK5 de party no mide 220 bytes.")
    move_slot = int(move_slot)
    if not 1 <= move_slot <= 4:
        raise B2W2LiveError("El hueco de movimiento B2/W2 tiene que estar entre 1 y 4.")
    move_id = int(move_id)
    if not 1 <= move_id <= MOVE_ID_MAX:
        raise B2W2LiveError(f"El movimiento #{move_id} no existe en quinta generación.")

    pid, order, canonical = _unshuffle_pk5(block)
    indice = move_slot - 1
    actuales = struct.unpack_from("<4H", canonical, PK5_MOVE_OFFSET)
    # Incluido el propio hueco: el juego tampoco deja enseñar un movimiento que
    # el Pokémon ya conoce, y reescribirlo encima le borraría los Más PP que
    # tuviera puestos. La interfaz ya filtra los movimientos conocidos, así que
    # llegar aquí significa que algo se ha desalineado.
    repetido = next(
        (posicion for posicion, valor in enumerate(actuales) if valor == move_id),
        None,
    )
    if repetido is not None:
        raise B2W2LiveError(
            f"Ese Pokémon ya conoce el movimiento #{move_id} en el hueco {repetido + 1}."
        )

    base_pp = int(base_pp_for(move_id) or 0)
    if base_pp <= 0:
        raise B2W2LiveError(
            f"No se pudo demostrar el PP del movimiento #{move_id}; no se enseñó nada."
        )
    if base_pp > 0xFF:
        raise B2W2LiveError(f"El PP del movimiento #{move_id} no cabe en PK5.")

    struct.pack_into("<H", canonical, PK5_MOVE_OFFSET + indice * 2, move_id)
    canonical[PK5_MOVE_PP_OFFSET + indice] = base_pp
    canonical[PK5_MOVE_PP_UPS_OFFSET + indice] = 0

    # La extensión de party no cambia: enseñar un movimiento no toca PS,
    # estado ni estadísticas. Se reescribe tal cual estaba.
    return _reshuffle_pk5(pid, order, canonical) + block[136:]


def pk5_party_without_moves(block: bytes, huecos) -> bytes:
    """Devuelve el PK5 sin los movimientos indicados, compactando los huecos.

    ``huecos`` son posiciones 1..4. Se borran de atrás hacia delante y el resto
    sube, que es lo que hace el juego: un Pokémon no puede tener un hueco vacío
    delante de uno lleno. Es la misma operación que `_remove_move_slots` en
    ORAS.
    """
    if len(block) != PK5_PARTY_SIZE:
        raise B2W2LiveError("El bloque PK5 de party no mide 220 bytes.")
    posiciones = sorted({int(valor) for valor in huecos}, reverse=True)
    if not posiciones:
        raise B2W2LiveError("No hay ningún movimiento B2/W2 que borrar.")
    for posicion in posiciones:
        if not 1 <= posicion <= 4:
            raise B2W2LiveError("El hueco de movimiento B2/W2 tiene que estar entre 1 y 4.")

    pid, order, canonical = _unshuffle_pk5(block)
    for posicion in posiciones:
        indice = posicion - 1
        if struct.unpack_from("<H", canonical, PK5_MOVE_OFFSET + indice * 2)[0] == 0:
            raise B2W2LiveError(f"El hueco {posicion} de ese Pokémon ya estaba vacío.")
        for actual in range(indice, 3):
            siguiente = actual + 1
            struct.pack_into(
                "<H", canonical, PK5_MOVE_OFFSET + actual * 2,
                struct.unpack_from("<H", canonical, PK5_MOVE_OFFSET + siguiente * 2)[0],
            )
            canonical[PK5_MOVE_PP_OFFSET + actual] = canonical[PK5_MOVE_PP_OFFSET + siguiente]
            canonical[PK5_MOVE_PP_UPS_OFFSET + actual] = (
                canonical[PK5_MOVE_PP_UPS_OFFSET + siguiente]
            )
        struct.pack_into("<H", canonical, PK5_MOVE_OFFSET + 3 * 2, 0)
        canonical[PK5_MOVE_PP_OFFSET + 3] = 0
        canonical[PK5_MOVE_PP_UPS_OFFSET + 3] = 0

    if struct.unpack_from("<H", canonical, PK5_MOVE_OFFSET)[0] == 0:
        raise B2W2LiveError("Un Pokémon no puede quedarse sin ningún movimiento.")

    return _reshuffle_pk5(pid, order, canonical) + block[136:]


def pk5_party_with_role(
    block: bytes, *, markings, evs, base_stats: dict[str, int],
) -> bytes:
    """Devuelve el PK5 de party con marcas, EV y estadísticas recalculadas.

    Cambiar EV sin recalcular las estadísticas dejaría al Pokémon con los valores
    antiguos hasta que el juego los recalculara por su cuenta, y el PS máximo
    podría no cuadrar con el actual. Se recalculan aquí con la misma tabla
    personal que ya usa el resto de RoleRun.

    El daño recibido se conserva: si sube el PS máximo, el actual sube lo mismo.
    Un Pokémon debilitado sigue debilitado.
    """
    if len(block) != PK5_PARTY_SIZE:
        raise B2W2LiveError("El bloque PK5 de party no mide 220 bytes.")
    marks = tuple(bool(value) for value in markings)
    if len(marks) != 6:
        raise B2W2LiveError("Las marcas PK5 deben ser exactamente seis.")
    ev_values = tuple(int(value) for value in evs)
    if len(ev_values) != 6 or any(not 0 <= value <= 255 for value in ev_values):
        raise B2W2LiveError("Los EV PK5 deben ser seis valores entre 0 y 255.")
    if sum(ev_values) > 510:
        raise B2W2LiveError("Los EV PK5 no pueden sumar más de 510.")

    pid, order, canonical = _unshuffle_pk5(block)
    canonical[PK5_MARKINGS_OFFSET] = sum(
        1 << index for index, marked in enumerate(marks) if marked
    )
    ev_by_key = dict(zip(STAT_ORDER_ROLERUN, ev_values))
    for key, offset in PK5_EV_OFFSETS.items():
        canonical[offset] = ev_by_key[key]

    iv32 = struct.unpack_from("<I", canonical, 0x38)[0]
    iv_by_key = dict(zip(
        STAT_ORDER_ROLERUN,
        tuple((iv32 >> shift) & 0x1F for shift in (0, 5, 10, 20, 25, 15)),
    ))
    extension = bytearray(_crypt(block[136:], pid))
    level = extension[0x8C - 0x88]
    old_current, old_max = struct.unpack_from("<2H", extension, 0x8E - 0x88)
    finals = gen5_final_stats(
        base=base_stats, ivs=iv_by_key, evs=ev_by_key,
        level=level, nature_id=int(canonical[0x41]),
    )
    new_max = int(finals["hp"])
    if old_current <= 0:
        new_current = 0
    else:
        new_current = max(1, min(new_max, int(old_current) + (new_max - int(old_max))))
    struct.pack_into(
        "<7H", extension, 0x8E - 0x88,
        new_current, new_max,
        finals["attack"], finals["defense"], finals["speed"],
        finals["sp_attack"], finals["sp_defense"],
    )
    return _reshuffle_pk5(pid, order, canonical) + _crypt(bytes(extension), pid)


_PERMUTATIONS = (
    (0,1,2,3),(0,1,3,2),(0,2,1,3),(0,3,1,2),(0,2,3,1),(0,3,2,1),
    (1,0,2,3),(1,0,3,2),(2,0,1,3),(3,0,1,2),(2,0,3,1),(3,0,2,1),
    (1,2,0,3),(1,3,0,2),(2,1,0,3),(3,1,0,2),(2,3,0,1),(3,2,0,1),
    (1,2,3,0),(1,3,2,0),(2,1,3,0),(3,1,2,0),(2,3,1,0),(3,2,1,0),
)


def parse_pk5_party(data: bytes, slot: int) -> B2W2Pokemon:
    if len(data) != PK5_PARTY_SIZE:
        raise B2W2LiveError("El bloque PK5 no mide 220 bytes.")
    pid = struct.unpack_from("<I", data, 0)[0]
    checksum = struct.unpack_from("<H", data, 6)[0]
    body = _crypt(data[8:136], checksum)
    if sum(struct.unpack("<64H", body)) & 0xFFFF != checksum:
        raise B2W2LiveError("Checksum PK5 inválido.")
    shuffled = [body[index * 32:(index + 1) * 32] for index in range(4)]
    order = _PERMUTATIONS[((pid >> 13) & 31) % 24]
    # PokeCrypto.Shuffle45 coloca en cada posición canónica el bloque cuyo
    # índice declara BlockPosition. Usar la permutación inversa parecía válido
    # para los PID cuyas disposiciones son autoinversas, pero corrompía otras
    # disposiciones (captura real: Lillipup y Patrat) aun con checksum correcto.
    blocks = [shuffled[index] for index in order]
    canonical = data[:8] + b"".join(blocks)
    extension = _crypt(data[136:], pid)
    species = struct.unpack_from("<H", canonical, 0x08)[0]
    if not 1 <= species <= 649:
        raise B2W2LiveError(f"Especie PK5 fuera de rango: {species}.")
    nickname = canonical[0x48:0x60].decode(
        "utf-16le", errors="ignore",
    ).split("\uffff", 1)[0].split("\0", 1)[0]
    level = extension[0x8C - 0x88]
    runtime_status = struct.unpack_from("<I", extension, 0)[0]
    # La prueba física de alpha.5 demostró que el runtime nominal usa 1 para
    # parálisis, no el bitmask PKHeX persistente (64). Los demás valores no se
    # etiquetan hasta observarlos de forma controlada.
    status_condition = 64 if runtime_status == 1 else 0
    current_hp, max_hp, attack, defense, speed, sp_attack, sp_defense = (
        struct.unpack_from("<7H", extension, 0x8E - 0x88)
    )
    iv32 = struct.unpack_from("<I", canonical, 0x38)[0]
    ivs = tuple((iv32 >> shift) & 0x1F for shift in (0, 5, 10, 20, 25, 15))
    evs = tuple(canonical[offset] for offset in (0x18, 0x19, 0x1A, 0x1C, 0x1D, 0x1B))
    move_ids = struct.unpack_from("<4H", canonical, 0x28)
    move_pp = tuple(canonical[0x30:0x34])
    move_pp_ups = tuple(canonical[0x34:0x38])
    marking_value = canonical[0x16]
    if (
        not 1 <= level <= 100 or max_hp <= 0 or current_hp > max_hp
        or any(move_id > 559 for move_id in move_ids)
        or any(pp_up > 3 for pp_up in move_pp_ups)
        or runtime_status > 0xFF
    ):
        raise B2W2LiveError("Estadísticas anexas PK5 incoherentes.")
    return B2W2Pokemon(
        slot=slot,
        pid=pid,
        species_id=species,
        nickname=nickname,
        level=level,
        held_item_id=struct.unpack_from("<H", canonical, 0x0A)[0],
        ability_id=canonical[0x15],
        move_ids=move_ids,
        move_pp=move_pp,
        move_pp_ups=move_pp_ups,
        markings=tuple(bool(marking_value & (1 << index)) for index in range(6)),
        tid=struct.unpack_from("<H", canonical, 0x0C)[0],
        sid=struct.unpack_from("<H", canonical, 0x0E)[0],
        form=(canonical[0x40] >> 3) & 0x1F,
        nature_id=canonical[0x41],
        is_egg=bool(iv32 & (1 << 30)),
        status_condition=status_condition,
        stats=(max_hp, attack, defense, sp_attack, sp_defense, speed),
        ivs=ivs,
        evs=evs,
        current_hp=current_hp,
        max_hp=max_hp,
    )


def parse_pk5_boxed(data: bytes, box: int, slot: int) -> B2W2BoxPokemon | None:
    """Decodifica un PK5 stored; ``None`` representa el vacío PK5 validado."""
    if len(data) != PK5_STORED_SIZE:
        raise B2W2LiveError("El bloque PK5 almacenado no mide 136 bytes.")
    pid, sanity, checksum = struct.unpack_from("<IHH", data, 0)
    body = _crypt(data[8:], checksum)
    if sum(struct.unpack("<64H", body)) & 0xFFFF != checksum:
        raise B2W2LiveError("Checksum PK5 almacenado inválido.")
    shuffled = [body[index * 32:(index + 1) * 32] for index in range(4)]
    order = _PERMUTATIONS[((pid >> 13) & 31) % 24]
    canonical = data[:8] + b"".join(shuffled[index] for index in order)
    species = struct.unpack_from("<H", canonical, 0x08)[0]
    if species == 0:
        if pid or sanity or checksum:
            raise B2W2LiveError("El vacío PK5 no coincide con la representación observada.")
        return None
    if sanity != 0 or not 1 <= species <= 649:
        raise B2W2LiveError("Identidad PK5 almacenada incoherente.")
    move_ids = struct.unpack_from("<4H", canonical, 0x28)
    pp_ups = tuple(canonical[0x34:0x38])
    nature = int(canonical[0x41])
    if any(move > 559 for move in move_ids) or any(value > 3 for value in pp_ups):
        raise B2W2LiveError("Movimientos PK5 almacenados incoherentes.")
    if not 0 <= nature < 25:
        raise B2W2LiveError("Naturaleza PK5 almacenada incoherente.")
    iv32 = struct.unpack_from("<I", canonical, 0x38)[0]
    marking_value = canonical[0x16]
    nickname = canonical[0x48:0x60].decode(
        "utf-16le", errors="ignore",
    ).split("\uffff", 1)[0].split("\0", 1)[0]
    return B2W2BoxPokemon(
        box=int(box), slot=int(slot), pid=pid, species_id=species,
        nickname=nickname,
        experience=struct.unpack_from("<I", canonical, 0x10)[0],
        held_item_id=struct.unpack_from("<H", canonical, 0x0A)[0],
        ability_id=canonical[0x15], move_ids=move_ids,
        markings=tuple(bool(marking_value & (1 << index)) for index in range(6)),
        tid=struct.unpack_from("<H", canonical, 0x0C)[0],
        sid=struct.unpack_from("<H", canonical, 0x0E)[0],
        form=(canonical[0x40] >> 3) & 0x1F, nature_id=nature,
        is_egg=bool(iv32 & (1 << 30)),
        ivs=tuple((iv32 >> shift) & 0x1F for shift in (0, 5, 10, 20, 25, 15)),
        evs=tuple(canonical[offset] for offset in (0x18, 0x19, 0x1A, 0x1C, 0x1D, 0x1B)),
    )


class B2W2MelonDSReader:
    """Lector cerrado de la party nominal B2/W2 dentro del mapeo de melonDS."""

    def __init__(self, memory: Gen5Memory | None = None) -> None:
        # Qué juego de quinta se está leyendo. Sin descriptor, Negro 2: es el
        # que tenía todas las direcciones demostradas cuando esto se escribió.
        #
        # Solo el ancla del equipo se mide contra cada juego; el resto de
        # direcciones del bloque del guardado salen de ella. Ver gen5_memory.
        self.memory = memory or GEN5_MEMORY["b2w2"]
        # Reentrante: los writers releen party y PC dentro de su transacción.
        self._lock = threading.RLock()
        # Base ya demostrada: (pid, nombre, allocation_base). Evita recorrer el
        # espacio de direcciones completo de melonDS en cada lectura.
        self._resolved: tuple[int, str, int] | None = None
        # Conjunto de procesos melonDS con el que se resolvio. Si cambia, se
        # vuelve a descubrir: la deteccion de lecturas ambiguas depende de el.
        self._resolved_processes: tuple[tuple[int, str], ...] = ()
        self._resolved_at = 0.0

    def _demostrada(self, direccion: int | None, capacidad: str) -> int:
        """Direccion de una capacidad, o una negativa clara si no se demostro.

        Un juego puede tener ancla y todavia no tener batalla o MT: esas dos no
        viven en el bloque del guardado, asi que no salen de la resta. Sin esto,
        la lectura fallaria mas adelante con un error que no dice nada.
        """
        if direccion is None:
            raise B2W2LiveError(
                f"{capacidad} todavia no esta demostrado en {self.memory.label}."
            )
        return int(direccion)

    def forget_resolved_base(self) -> None:
        """Olvida la base cacheada; la siguiente lectura vuelve a descubrirla."""
        self._resolved = None
        self._resolved_processes = ()
        self._resolved_at = 0.0

    def _cached_party_read(
        self, signature: tuple[tuple[int, str], ...], *, now: float,
    ) -> B2W2PartyRead | None:
        """Relee en la base ya demostrada, o devuelve ``None`` para redescubrir.

        No es un atajo que se salte validaciones: se ejecuta exactamente la misma
        doble lectura estable de count+party y el mismo parseo con checksum. Lo
        unico que se omite es la busqueda de donde esta esa base.
        """
        resolved = self._resolved
        if resolved is None or signature != self._resolved_processes:
            return None
        if now - self._resolved_at >= BASE_REDISCOVERY_SECONDS:
            return None
        pid, name, allocation = resolved
        try:
            return self._read_process(pid, name, known_allocation=allocation)
        except (OSError, B2W2LiveError):
            return None

    @_serialized
    @perf.timed("b2w2.read_party")
    def read_party(self) -> B2W2PartyRead:
        if os.name != "nt":
            raise B2W2LiveError("melonDS en Windows es obligatorio.")
        candidates = self._list_melonds_processes()
        if not candidates:
            self.forget_resolved_base()
            raise B2W2LiveError("melonDS no está abierto.")
        signature = tuple(sorted(candidates))
        now = time.monotonic()

        cached = self._cached_party_read(signature, now=now)
        if cached is not None:
            perf.record("b2w2.base_cache", 0.0, hit=True)
            return cached

        perf.record("b2w2.base_cache", 0.0, hit=False)
        last_error = "No se localizó la RAM DS validada de B2/W2."
        for pid, name in sorted(candidates, reverse=True):
            try:
                result = self._read_process(pid, name)
                if result is not None:
                    self._resolved = (
                        result.process_id, result.process_name, result.allocation_base,
                    )
                    self._resolved_processes = signature
                    self._resolved_at = now
                    return result
            except (OSError, B2W2LiveError) as exc:
                last_error = str(exc)
        self.forget_resolved_base()
        raise B2W2LiveError(last_error)

    @staticmethod
    def parse_battle_copies(
        mirror: bytes, immediate: bytes, party: tuple[B2W2Pokemon, ...],
    ) -> B2W2BattleRead:
        if len(mirror) != BATTLE_READ_SIZE or len(immediate) != BATTLE_READ_SIZE:
            raise B2W2LiveError("La fila de batalla B2/W2 tiene tamaño inválido.")
        old = struct.unpack("<7H", mirror[:BATTLE_ROW_SIZE])
        live = struct.unpack("<7H", immediate[:BATTLE_ROW_SIZE])
        if old[0] == live[0] == 0:
            return B2W2BattleRead(False)
        if old[0] == 0:
            # Sin copia de presentación no hay nada que publicar sin arriesgarse
            # a adelantar el daño a la animación.
            return B2W2BattleRead(False)

        # La copia de presentación (``old``) es la autoridad de la HUD. La
        # segunda fila solo **corrobora**.
        #
        # Hasta alpha.31 un desacuerdo entre ambas anulaba la lectura entera. La
        # traza física del 27-08-2026 con seis miembros lo refutó: durante todo
        # el combate la presentación siguió correctamente al Patrat activo
        # (16 -> 3 -> 0) mientras la segunda fila se quedó congelada describiendo
        # a otro miembro del equipo y con un nivel imposible (516). Es decir,
        # estaba obsoleta. Con la lectura anulada, RoleRun caía al bloque de
        # party, que en Gen 5 **no se actualiza hasta que termina el combate**:
        # de ahí que ni los PS ni la baja se vieran en tiempo real.
        corrobora = (old[0], old[1], old[5], old[6]) == (live[0], live[1], live[5], live[6])

        matches = [
            pokemon for pokemon in party
            if (
                pokemon.species_id, pokemon.max_hp, pokemon.ability_id, pokemon.level
            ) == (old[0], old[1], old[5], old[6])
        ]
        if len(matches) != 1:
            raise B2W2LiveError(
                "La fila de batalla no identifica de forma única un miembro del equipo."
            )
        if old[1] <= 0 or old[2] > old[1]:
            raise B2W2LiveError("Los PS de batalla B2/W2 son incoherentes.")
        if corrobora and (live[1] <= 0 or live[2] > live[1]):
            raise B2W2LiveError("Los PS de batalla B2/W2 son incoherentes.")
        runtime_status = int(mirror[BATTLE_STATUS_OFFSET])
        if runtime_status not in (0, 1):
            raise B2W2LiveError(
                f"Estado de batalla B2/W2 no demostrado: {runtime_status}."
            )
        # Con corroboración se conserva el comportamiento validado en alpha.5:
        # ``live`` adelanta el resultado del golpe y ``old`` converge tras la
        # animación, así que la HUD muestra ``old``. Sin corroboración se muestra
        # igualmente ``old``, que es exactamente la misma fuente y la que nunca
        # adelanta daño; simplemente no hay nada pendiente de converger.
        return B2W2BattleRead(
            active=True,
            party_slot=matches[0].slot,
            current_hp=old[2],
            max_hp=old[1],
            mirror_hp=old[2],
            immediate_hp=live[2] if corrobora else old[2],
            converged=(old[2] == live[2]) if corrobora else True,
            status_condition=64 if runtime_status == 1 else 0,
        )

    def _read_battle_rows(self, party_read: B2W2PartyRead) -> B2W2BattleRead:
        # Se comprueba ANTES de abrir el proceso: si el juego no tiene el carril
        # demostrado, no hay nada que leer y no hace falta molestar a melonDS.
        presentacion = self._demostrada(
            self.memory.battle_presentation, "El carril de batalla",
        )
        logica = self._demostrada(self.memory.battle_logical, "El carril de batalla")
        # Instancia privada: los tipos ya están fijados una sola vez y ningún
        # otro módulo puede invalidarlos a mitad de llamada.
        kernel32 = _KERNEL32
        if kernel32 is None:
            raise B2W2LiveError("melonDS en Windows es obligatorio.")
        handle = kernel32.OpenProcess(0x0400 | 0x0010, False, party_read.process_id)
        if not handle:
            raise B2W2LiveError("melonDS desapareció antes de leer batalla.")

        def read_guest(guest: int) -> bytes:
            address = party_read.allocation_base + (guest - DS_RAM_BASE)
            buffer = ctypes.create_string_buffer(BATTLE_READ_SIZE)
            received = ctypes.c_size_t()
            if (
                not kernel32.ReadProcessMemory(
                    handle, ctypes.c_void_p(address), buffer, BATTLE_READ_SIZE,
                    ctypes.byref(received),
                )
                or received.value != BATTLE_READ_SIZE
            ):
                raise B2W2LiveError("Lectura incompleta de la fila de batalla.")
            return buffer.raw

        try:
            first = (read_guest(presentacion), read_guest(logica))
            second = (read_guest(presentacion), read_guest(logica))
            if first != second:
                raise B2W2LiveError("La fila de batalla cambió durante la doble lectura.")
            return B2W2MelonDSReader.parse_battle_copies(
                first[0], first[1], party_read.pokemon,
            )
        finally:
            kernel32.CloseHandle(handle)

    @_serialized
    def read_battle_party(
        self, party_read: B2W2PartyRead,
    ) -> tuple[B2W2BattleRead | None, ...]:
        """Una fila de combate por miembro del equipo.

        Solo para los juegos con `battle_stride` medido. En Blanco se demostró
        que hay dos tablas de filas, una por miembro, con un paso de 0x228:
        Purrloin, primero del equipo, tenía las suyas 0x228 antes que las del
        Serperior, segundo, en las dos tablas.

        Eso permite publicar los PS vivos del **equipo entero** durante el
        combate, y no solo los del que está en el campo. Cada fila se valida
        contra su propio miembro: si la que corresponde al tercero no describe
        al tercero, esa posición se descarta en vez de publicarse.

        Un miembro sin fila válida devuelve ``None``, y quien llama conserva
        para él lo que diga el bloque de equipo.
        """
        paso = self.memory.battle_stride
        if paso is None:
            raise B2W2LiveError(
                f"El paso entre filas de combate no está medido en {self.memory.label}."
            )
        presentacion = self._demostrada(
            self.memory.battle_presentation, "El carril de batalla",
        )
        logica = self._demostrada(self.memory.battle_logical, "El carril de batalla")

        kernel32 = _KERNEL32
        if kernel32 is None:
            raise B2W2LiveError("melonDS en Windows es obligatorio.")
        handle = kernel32.OpenProcess(0x0400 | 0x0010, False, party_read.process_id)
        if not handle:
            raise B2W2LiveError("melonDS desapareció antes de leer batalla.")

        def read_guest(guest: int) -> bytes:
            address = party_read.allocation_base + (guest - DS_RAM_BASE)
            buffer = ctypes.create_string_buffer(BATTLE_READ_SIZE)
            received = ctypes.c_size_t()
            if (
                not kernel32.ReadProcessMemory(
                    handle, ctypes.c_void_p(address), buffer, BATTLE_READ_SIZE,
                    ctypes.byref(received),
                )
                or received.value != BATTLE_READ_SIZE
            ):
                raise B2W2LiveError("Lectura incompleta de la fila de batalla.")
            return buffer.raw

        salida: list[B2W2BattleRead | None] = []
        try:
            for indice, miembro in enumerate(party_read.pokemon):
                desplazamiento = indice * paso
                try:
                    # Doble lectura, como el resto: una fila a medio escribir no
                    # se publica.
                    primera = (
                        read_guest(presentacion + desplazamiento),
                        read_guest(logica + desplazamiento),
                    )
                    segunda = (
                        read_guest(presentacion + desplazamiento),
                        read_guest(logica + desplazamiento),
                    )
                    if primera != segunda:
                        salida.append(None)
                        continue
                    salida.append(
                        self.parse_battle_copies(primera[0], primera[1], (miembro,)),
                    )
                except B2W2LiveError:
                    # La fila de ese miembro no se pudo validar. Se descarta esa
                    # sola, no el combate entero.
                    salida.append(None)
        finally:
            kernel32.CloseHandle(handle)
        return tuple(salida)

    def read_battle(self, party_read: B2W2PartyRead) -> B2W2BattleRead:
        return self._read_battle_rows(party_read)

    @staticmethod
    def prepare_pc_move(
        raw: bytes, source_box: int, source_slot: int,
        destination_box: int, destination_slot: int,
    ) -> B2W2PCMovePlan:
        if len(raw) != PC_MATRIX_SIZE:
            raise B2W2LiveError("La matriz PC B2/W2 tiene tamaño inválido.")
        for box, slot in ((source_box, source_slot), (destination_box, destination_slot)):
            if not 1 <= int(box) <= PC_BOX_COUNT or not 1 <= int(slot) <= PC_BOX_SLOT_COUNT:
                raise B2W2LiveError("Origen o destino PC B2/W2 fuera de rango.")
        if (source_box, source_slot) == (destination_box, destination_slot):
            raise B2W2LiveError("Origen y destino PC B2/W2 son el mismo slot.")
        source_offset = (source_box - 1) * PC_BOX_STRIDE + (source_slot - 1) * PK5_STORED_SIZE
        destination_offset = (
            (destination_box - 1) * PC_BOX_STRIDE
            + (destination_slot - 1) * PK5_STORED_SIZE
        )
        source = raw[source_offset:source_offset + PK5_STORED_SIZE]
        destination = raw[destination_offset:destination_offset + PK5_STORED_SIZE]
        pokemon = parse_pk5_boxed(source, source_box, source_slot)
        if pokemon is None:
            raise B2W2LiveError("El origen PC B2/W2 está vacío.")
        if parse_pk5_boxed(destination, destination_box, destination_slot) is not None:
            raise B2W2LiveError("El destino PC B2/W2 debe estar vacío.")
        expected = bytearray(raw)
        expected[source_offset:source_offset + PK5_STORED_SIZE] = destination
        expected[destination_offset:destination_offset + PK5_STORED_SIZE] = source
        return B2W2PCMovePlan(
            source_offset, destination_offset, source, destination,
            bytes(expected), pokemon,
        )

    @staticmethod
    def _write_process_bytes(process_id: int, host_address: int, payload: bytes) -> None:
        # Instancia privada: los tipos ya están fijados una sola vez y ningún
        # otro módulo puede invalidarlos a mitad de llamada.
        kernel32 = _KERNEL32
        if kernel32 is None:
            raise B2W2LiveError("melonDS en Windows es obligatorio.")
        handle = kernel32.OpenProcess(0x0400 | 0x0008 | 0x0020, False, process_id)
        if not handle:
            raise B2W2LiveError("Windows no permitió abrir melonDS para escritura.")
        try:
            buffer = ctypes.create_string_buffer(payload)
            written = ctypes.c_size_t()
            if (
                not kernel32.WriteProcessMemory(
                    handle, ctypes.c_void_p(host_address), buffer, len(payload),
                    ctypes.byref(written),
                )
                or written.value != len(payload)
            ):
                raise B2W2LiveError("Escritura PC B2/W2 incompleta.")
        finally:
            kernel32.CloseHandle(handle)

    @_serialized
    def move_pc_slot(
        self, party_read: B2W2PartyRead, source_box: int, source_slot: int,
        destination_box: int, destination_slot: int,
        *, expected_identity: tuple[int, int, int] | None = None,
    ) -> B2W2PCRead:
        before = self.read_pc(party_read)
        plan = self.prepare_pc_move(
            before.raw, source_box, source_slot, destination_box, destination_slot,
        )
        if expected_identity is not None and expected_identity != (
            plan.pokemon.pid, plan.pokemon.tid, plan.pokemon.sid,
        ):
            raise B2W2LiveError(
                "La identidad del origen PC B2/W2 cambió justo antes de escribir."
            )
        matrix_host = party_read.allocation_base + (self.memory.pc - DS_RAM_BASE)

        def restore() -> None:
            self._write_process_bytes(
                party_read.process_id, matrix_host + plan.source_offset, plan.source,
            )
            self._write_process_bytes(
                party_read.process_id, matrix_host + plan.destination_offset, plan.destination,
            )
            if self.read_pc(party_read).raw != before.raw:
                raise B2W2LiveError(
                    "Rollback PC B2/W2 no confirmado; no guardes la partida."
                )

        try:
            # Destino primero: ante interrupción nunca se pierde la única copia.
            self._write_process_bytes(
                party_read.process_id, matrix_host + plan.destination_offset, plan.source,
            )
            self._write_process_bytes(
                party_read.process_id, matrix_host + plan.source_offset, plan.destination,
            )
            after = self.read_pc(party_read)
            if after.raw != plan.expected:
                raise B2W2LiveError("El readback completo PC B2/W2 no coincide.")
            moved = next((
                item for item in after.pokemon
                if (item.box, item.slot) == (destination_box, destination_slot)
            ), None)
            if moved is None or (moved.pid, moved.tid, moved.sid) != (
                plan.pokemon.pid, plan.pokemon.tid, plan.pokemon.sid,
            ):
                raise B2W2LiveError("La identidad escrita en el destino no coincide.")
            return after
        except Exception:
            restore()
            raise

    @_serialized
    def swap_party_pc(
        self, party_read: B2W2PartyRead, party_slot: int, box: int, box_slot: int,
        incoming_party: bytes, *, incoming_identity: tuple[int, int, int],
        outgoing_identity: tuple[int, int, int],
    ) -> tuple[B2W2PartyRead, B2W2PCRead]:
        if len(incoming_party) != PK5_PARTY_SIZE:
            raise B2W2LiveError("El PK5 entrante de party no mide 220 bytes.")
        before_party = self.read_party()
        if (
            before_party.process_id != party_read.process_id
            or before_party.allocation_base != party_read.allocation_base
            or not 0 <= party_slot < before_party.count
        ):
            raise B2W2LiveError("La party B2/W2 cambió antes del intercambio.")
        outgoing = before_party.pokemon[party_slot]
        if (outgoing.pid, outgoing.tid, outgoing.sid) != outgoing_identity:
            raise B2W2LiveError("La identidad saliente de party B2/W2 cambió.")
        before_pc = self.read_pc(before_party)
        pc_offset = (box - 1) * PC_BOX_STRIDE + (box_slot - 1) * PK5_STORED_SIZE
        if not 0 <= pc_offset <= len(before_pc.raw) - PK5_STORED_SIZE:
            raise B2W2LiveError("El slot PC B2/W2 está fuera de rango.")
        incoming_stored = before_pc.raw[pc_offset:pc_offset + PK5_STORED_SIZE]
        incoming = parse_pk5_boxed(incoming_stored, box, box_slot)
        if incoming is None or (incoming.pid, incoming.tid, incoming.sid) != incoming_identity:
            raise B2W2LiveError("La identidad entrante del PC B2/W2 cambió.")
        parsed_incoming = parse_pk5_party(incoming_party, party_slot)
        if (parsed_incoming.pid, parsed_incoming.tid, parsed_incoming.sid) != incoming_identity:
            raise B2W2LiveError("El PK5 de party construido no coincide con el entrante.")
        party_offset = party_slot * PK5_PARTY_SIZE
        outgoing_party = before_party.raw[party_offset:party_offset + PK5_PARTY_SIZE]
        outgoing_stored = outgoing_party[:PK5_STORED_SIZE]
        party_host = before_party.allocation_base + (self.memory.party_data - DS_RAM_BASE) + party_offset
        pc_host = before_party.allocation_base + (self.memory.pc - DS_RAM_BASE) + pc_offset

        def restore() -> None:
            self._write_process_bytes(before_party.process_id, pc_host, incoming_stored)
            self._write_process_bytes(before_party.process_id, party_host, outgoing_party)
            restored_party = self.read_party()
            restored_pc = self.read_pc(restored_party)
            if (
                restored_party.pokemon[party_slot].pid != outgoing.pid
                or not any(
                    p.pid == incoming.pid and (p.box, p.slot) == (box, box_slot)
                    for p in restored_pc.pokemon
                )
            ):
                raise B2W2LiveError(
                    "Rollback Equipo↔PC B2/W2 no confirmado; no guardes la partida."
                )

        try:
            self._write_process_bytes(before_party.process_id, pc_host, outgoing_stored)
            self._write_process_bytes(before_party.process_id, party_host, incoming_party)
            after_party = self.read_party()
            after_pc = self.read_pc(after_party)
            live = after_party.pokemon[party_slot]
            if (
                (live.pid, live.tid, live.sid) != incoming_identity
                or live.current_hp != live.max_hp
                or not any(
                    (p.pid, p.tid, p.sid) == outgoing_identity
                    and (p.box, p.slot) == (box, box_slot)
                    for p in after_pc.pokemon
                )
            ):
                raise B2W2LiveError("El readback Equipo↔PC B2/W2 no coincide.")
            return after_party, after_pc
        except Exception:
            restore()
            raise

    @_serialized
    def replace_fainted_party_pc(
        self, party_read: B2W2PartyRead, party_slot: int,
        box: int, box_slot: int, graveyard_box: int, graveyard_box_slot: int,
        incoming_party: bytes, *,
        incoming_identity: tuple[int, int, int],
        outgoing_identity: tuple[int, int, int],
    ) -> tuple[B2W2PartyRead, B2W2PCRead]:
        """Sustituye a un debilitado por un Pokémon del PC y lo lleva al Cementerio.

        A diferencia de ``swap_party_pc``, aquí intervienen **tres** posiciones:
        el sustituto sale de ``box/box_slot``, el debilitado se deposita en
        ``graveyard_box/graveyard_box_slot`` y la casilla de origen queda vacía.

        El orden de escritura no es casual. Se copia primero al debilitado al
        Cementerio, después entra el sustituto en la party y solo al final se
        vacía su casilla de origen. En ningún punto intermedio existe un Pokémon
        con una única copia en juego: como mucho hay un duplicado transitorio,
        que es recuperable; una pérdida no lo sería.
        """
        if len(incoming_party) != PK5_PARTY_SIZE:
            raise B2W2LiveError("El PK5 entrante de party no mide 220 bytes.")
        if (int(box), int(box_slot)) == (int(graveyard_box), int(graveyard_box_slot)):
            raise B2W2LiveError(
                "El origen del sustituto y el Cementerio no pueden ser la misma casilla."
            )
        before_party = self.read_party()
        if (
            before_party.process_id != party_read.process_id
            or before_party.allocation_base != party_read.allocation_base
            or not 0 <= party_slot < before_party.count
        ):
            raise B2W2LiveError("La party B2/W2 cambió antes de la sustitución.")
        outgoing = before_party.pokemon[party_slot]
        if (outgoing.pid, outgoing.tid, outgoing.sid) != tuple(outgoing_identity):
            raise B2W2LiveError("La identidad del Pokémon debilitado B2/W2 cambió.")

        before_pc = self.read_pc(before_party)
        origen = (int(box) - 1) * PC_BOX_STRIDE + (int(box_slot) - 1) * PK5_STORED_SIZE
        cementerio = (
            (int(graveyard_box) - 1) * PC_BOX_STRIDE
            + (int(graveyard_box_slot) - 1) * PK5_STORED_SIZE
        )
        for offset in (origen, cementerio):
            if not 0 <= offset <= len(before_pc.raw) - PK5_STORED_SIZE:
                raise B2W2LiveError("Una casilla PC B2/W2 de la sustitución está fuera de rango.")

        incoming_stored = before_pc.raw[origen:origen + PK5_STORED_SIZE]
        incoming = parse_pk5_boxed(incoming_stored, int(box), int(box_slot))
        if incoming is None or (incoming.pid, incoming.tid, incoming.sid) != tuple(incoming_identity):
            raise B2W2LiveError("La identidad del sustituto en el PC B2/W2 cambió.")
        if parse_pk5_boxed(
            before_pc.raw[cementerio:cementerio + PK5_STORED_SIZE],
            int(graveyard_box), int(graveyard_box_slot),
        ) is not None:
            raise B2W2LiveError("La casilla del Cementerio B2/W2 ya está ocupada.")
        parsed_incoming = parse_pk5_party(incoming_party, party_slot)
        if (parsed_incoming.pid, parsed_incoming.tid, parsed_incoming.sid) != tuple(incoming_identity):
            raise B2W2LiveError("El PK5 de party construido no coincide con el sustituto.")

        party_offset = party_slot * PK5_PARTY_SIZE
        outgoing_party = before_party.raw[party_offset:party_offset + PK5_PARTY_SIZE]
        outgoing_stored = outgoing_party[:PK5_STORED_SIZE]
        cementerio_antes = before_pc.raw[cementerio:cementerio + PK5_STORED_SIZE]

        base_party = before_party.allocation_base + (self.memory.party_data - DS_RAM_BASE)
        base_pc = before_party.allocation_base + (self.memory.pc - DS_RAM_BASE)
        party_host = base_party + party_offset
        origen_host = base_pc + origen
        cementerio_host = base_pc + cementerio

        def restore() -> None:
            self._write_process_bytes(before_party.process_id, party_host, outgoing_party)
            self._write_process_bytes(before_party.process_id, origen_host, incoming_stored)
            self._write_process_bytes(before_party.process_id, cementerio_host, cementerio_antes)
            restored_party = self.read_party()
            restored_pc = self.read_pc(restored_party)
            if restored_party.raw != before_party.raw or restored_pc.raw != before_pc.raw:
                raise B2W2LiveError(
                    "Rollback de la sustitución B2/W2 no confirmado; no guardes la partida."
                )

        try:
            self._write_process_bytes(before_party.process_id, cementerio_host, outgoing_stored)
            self._write_process_bytes(before_party.process_id, party_host, incoming_party)
            self._write_process_bytes(before_party.process_id, origen_host, empty_pk5_stored())
            after_party = self.read_party()
            after_pc = self.read_pc(after_party)
            vivo = after_party.pokemon[party_slot]
            if (vivo.pid, vivo.tid, vivo.sid) != tuple(incoming_identity):
                raise B2W2LiveError("El sustituto B2/W2 no ocupó su casilla de party.")
            if after_party.count != before_party.count:
                raise B2W2LiveError("La sustitución B2/W2 alteró el tamaño del equipo.")
            if not any(
                (p.pid, p.tid, p.sid) == tuple(outgoing_identity)
                and (p.box, p.slot) == (int(graveyard_box), int(graveyard_box_slot))
                for p in after_pc.pokemon
            ):
                raise B2W2LiveError("El debilitado B2/W2 no llegó al Cementerio.")
            if any((p.box, p.slot) == (int(box), int(box_slot)) for p in after_pc.pokemon):
                raise B2W2LiveError("La casilla de origen B2/W2 no quedó vacía.")
            return after_party, after_pc
        except Exception:
            restore()
            raise

    @_serialized
    def write_party_roles(
        self, party_read: B2W2PartyRead, writes,
    ) -> B2W2PartyRead:
        """Escribe marcas y EV de uno o varios miembros como una transacción.

        Mismo contrato que el resto de writers B2/W2: relectura fresca de la
        party inmediatamente antes de escribir, verificación de identidad fuerte
        por slot, readback con el parser de producción y rollback completo ante
        cualquier divergencia.

        No toca el contador de party ni el orden: solo reescribe el bloque PK5 de
        los miembros indicados.
        """
        peticiones = list(writes)
        if not peticiones:
            raise B2W2LiveError("No hay ningún cambio de rol B2/W2 que escribir.")
        before = self.read_party()
        if before.process_id != party_read.process_id:
            raise B2W2LiveError("melonDS cambió antes de escribir los roles B2/W2.")
        old_raw = before.raw
        new_raw = bytearray(old_raw)
        esperado: dict[int, B2W2RoleWrite] = {}
        for peticion in peticiones:
            slot = int(peticion.slot)
            if not 0 <= slot < before.count:
                raise B2W2LiveError("El slot de party B2/W2 está fuera de rango.")
            if slot in esperado:
                raise B2W2LiveError("Dos cambios de rol B2/W2 sobre el mismo slot.")
            member = before.pokemon[slot]
            if (member.pid, member.tid, member.sid) != tuple(peticion.identity):
                raise B2W2LiveError("La identidad del rol B2/W2 cambió antes de escribir.")
            offset = slot * PK5_PARTY_SIZE
            new_raw[offset:offset + PK5_PARTY_SIZE] = pk5_party_with_role(
                bytes(old_raw[offset:offset + PK5_PARTY_SIZE]),
                markings=peticion.markings,
                evs=peticion.evs,
                base_stats=peticion.base_stats,
            )
            esperado[slot] = peticion

        party_host = before.allocation_base + (self.memory.party_data - DS_RAM_BASE)

        def restore() -> None:
            self._write_process_bytes(before.process_id, party_host, old_raw)
            restored = self.read_party()
            if restored.raw != old_raw:
                raise B2W2LiveError("Rollback de roles B2/W2 no confirmado; no guardes.")

        try:
            self._write_process_bytes(before.process_id, party_host, bytes(new_raw))
            after = self.read_party()
            if after.count != before.count or after.raw != bytes(new_raw):
                raise B2W2LiveError("El readback de roles B2/W2 no coincide.")
            for slot, peticion in esperado.items():
                verificado = after.pokemon[slot]
                if (verificado.pid, verificado.tid, verificado.sid) != tuple(peticion.identity):
                    raise B2W2LiveError("La identidad B2/W2 verificada no coincide.")
                if tuple(verificado.markings) != tuple(peticion.markings):
                    raise B2W2LiveError("La verificación semántica de las marcas B2/W2 falló.")
                if tuple(verificado.evs) != tuple(peticion.evs):
                    raise B2W2LiveError("La verificación semántica de EV B2/W2 falló.")
            return after
        except Exception:
            restore()
            raise

    @_serialized
    def write_party_heal(
        self, party_read: B2W2PartyRead, heals, *, base_pp_for,
    ) -> B2W2PartyRead:
        """Cura uno o varios miembros de la party como una única transacción.

        ``heals`` son pares ``(slot, identidad)``. Mismo contrato que el resto de
        writers B2/W2: relectura fresca, identidad fuerte por slot, readback con
        el parser de producción, verificación semántica y rollback completo.
        """
        peticiones = list(heals)
        if not peticiones:
            raise B2W2LiveError("No hay ningún miembro del equipo B2/W2 que curar.")
        before = self.read_party()
        if before.process_id != party_read.process_id:
            raise B2W2LiveError("melonDS cambió antes de curar el equipo B2/W2.")
        old_raw = before.raw
        new_raw = bytearray(old_raw)
        objetivos: dict[int, tuple[int, int, int]] = {}
        for slot, identidad in peticiones:
            slot = int(slot)
            if not 0 <= slot < before.count:
                raise B2W2LiveError("El slot de party B2/W2 está fuera de rango.")
            if slot in objetivos:
                raise B2W2LiveError("Dos curaciones B2/W2 sobre el mismo slot.")
            member = before.pokemon[slot]
            if (member.pid, member.tid, member.sid) != tuple(identidad):
                raise B2W2LiveError("La identidad de la curación B2/W2 cambió antes de escribir.")
            offset = slot * PK5_PARTY_SIZE
            new_raw[offset:offset + PK5_PARTY_SIZE] = pk5_party_healed(
                bytes(old_raw[offset:offset + PK5_PARTY_SIZE]), base_pp_for=base_pp_for,
            )
            objetivos[slot] = tuple(identidad)

        if bytes(new_raw) == old_raw:
            # Ya estaban curados: no se escribe un solo byte en la partida.
            return before

        party_host = before.allocation_base + (self.memory.party_data - DS_RAM_BASE)

        def restore() -> None:
            self._write_process_bytes(before.process_id, party_host, old_raw)
            restored = self.read_party()
            if restored.raw != old_raw:
                raise B2W2LiveError("Rollback de curación B2/W2 no confirmado; no guardes.")

        try:
            self._write_process_bytes(before.process_id, party_host, bytes(new_raw))
            after = self.read_party()
            if after.count != before.count or after.raw != bytes(new_raw):
                raise B2W2LiveError("El readback de la curación B2/W2 no coincide.")
            for slot, identidad in objetivos.items():
                verificado = after.pokemon[slot]
                if (verificado.pid, verificado.tid, verificado.sid) != identidad:
                    raise B2W2LiveError("La identidad B2/W2 verificada no coincide.")
                if verificado.current_hp != verificado.max_hp:
                    raise B2W2LiveError("La verificación semántica de los PS curados falló.")
                if verificado.status_condition != 0:
                    raise B2W2LiveError("La verificación semántica del estado curado falló.")
                for indice, move_id in enumerate(verificado.move_ids):
                    if int(move_id) <= 0:
                        continue
                    esperado = int(base_pp_for(int(move_id))) * (
                        5 + int(verificado.move_pp_ups[indice])
                    ) // 5
                    if int(verificado.move_pp[indice]) != esperado:
                        raise B2W2LiveError("La verificación semántica de los PP curados falló.")
            return after
        except Exception:
            restore()
            raise

    @_serialized
    def write_party_moves(
        self, party_read: B2W2PartyRead, ensenanzas, *, base_pp_for,
    ) -> B2W2PartyRead:
        """Cambia uno o varios movimientos como una única transacción.

        ``ensenanzas`` son tuplas ``(slot, identidad, hueco, move_id)``. Un
        ``move_id`` de cero **borra** ese movimiento y compacta los huecos, que
        es lo que necesita un Support al perder los ataques que le sobran.

        Dentro de un mismo Pokémon se escriben primero los movimientos nuevos y
        después los borrados, de atrás hacia delante: así cada hueco significa
        lo mismo que cuando el usuario lo eligió, y las compactaciones no se
        pisan entre sí.

        Mismo contrato que el resto de writers B2/W2: relectura fresca,
        identidad fuerte por slot, readback con el parser de producción,
        verificación semántica y rollback completo. En quinta las MT son
        reutilizables, así que la mochila no se toca nunca.
        """
        peticiones = list(ensenanzas)
        if not peticiones:
            raise B2W2LiveError("No hay ningún movimiento B2/W2 que cambiar.")
        before = self.read_party()
        if before.process_id != party_read.process_id:
            raise B2W2LiveError("melonDS cambió antes de escribir el movimiento B2/W2.")
        old_raw = before.raw
        new_raw = bytearray(old_raw)

        por_pokemon: dict[int, list[tuple[int, int]]] = {}
        identidades: dict[int, tuple[int, int, int]] = {}
        vistos: set[tuple[int, int]] = set()
        for slot, identidad, hueco, move_id in peticiones:
            slot, hueco, move_id = int(slot), int(hueco), int(move_id)
            if not 0 <= slot < before.count:
                raise B2W2LiveError("El slot de party B2/W2 está fuera de rango.")
            if (slot, hueco) in vistos:
                raise B2W2LiveError("Dos cambios B2/W2 sobre el mismo hueco.")
            vistos.add((slot, hueco))
            member = before.pokemon[slot]
            if (member.pid, member.tid, member.sid) != tuple(identidad):
                raise B2W2LiveError("La identidad del cambio B2/W2 cambió antes de escribir.")
            identidades[slot] = tuple(identidad)
            por_pokemon.setdefault(slot, []).append((hueco, move_id))

        # Qué se espera ver en cada Pokémon después de escribir: los que tienen
        # que estar, los que ya no, y en qué hueco exacto cuando no ha habido
        # borrados que muevan nada de sitio.
        esperados: dict[int, tuple[set[int], set[int], dict[int, int]]] = {}
        for slot, cambios in por_pokemon.items():
            offset = slot * PK5_PARTY_SIZE
            bloque = bytes(new_raw[offset:offset + PK5_PARTY_SIZE])
            original = before.pokemon[slot]
            borrados = [hueco for hueco, move_id in cambios if move_id <= 0]
            presentes: set[int] = set()
            ausentes = {int(original.move_ids[hueco - 1]) for hueco in borrados}
            posiciones: dict[int, int] = {}

            for hueco, move_id in cambios:
                if move_id <= 0:
                    continue
                bloque = pk5_party_with_move(
                    bloque, hueco, move_id, base_pp_for=base_pp_for,
                )
                presentes.add(move_id)
                if not borrados:
                    posiciones[hueco] = move_id
            if borrados:
                bloque = pk5_party_without_moves(bloque, borrados)
            new_raw[offset:offset + PK5_PARTY_SIZE] = bloque
            esperados[slot] = (presentes, ausentes - presentes, posiciones)

        if bytes(new_raw) == old_raw:
            # El equipo ya estaba así: no se escribe un solo byte.
            return before

        party_host = before.allocation_base + (self.memory.party_data - DS_RAM_BASE)

        def restore() -> None:
            self._write_process_bytes(before.process_id, party_host, old_raw)
            restored = self.read_party()
            if restored.raw != old_raw:
                raise B2W2LiveError(
                    "Rollback del cambio de movimientos B2/W2 no confirmado; no guardes."
                )

        try:
            self._write_process_bytes(before.process_id, party_host, bytes(new_raw))
            after = self.read_party()
            if after.count != before.count or after.raw != bytes(new_raw):
                raise B2W2LiveError("El readback del cambio de movimientos B2/W2 no coincide.")
            for slot, (presentes, ausentes, posiciones) in esperados.items():
                verificado = after.pokemon[slot]
                if (verificado.pid, verificado.tid, verificado.sid) != identidades[slot]:
                    raise B2W2LiveError("La identidad B2/W2 verificada no coincide.")
                actuales = [int(valor) for valor in verificado.move_ids]
                for move_id in presentes:
                    if move_id not in actuales:
                        raise B2W2LiveError(
                            "La verificación semántica del movimiento escrito falló."
                        )
                    posicion = actuales.index(move_id)
                    esperado = int(base_pp_for(move_id) or 0)
                    if int(verificado.move_pp[posicion]) != esperado:
                        raise B2W2LiveError("La verificación semántica de los PP falló.")
                for move_id in ausentes:
                    if move_id in actuales:
                        raise B2W2LiveError(
                            "El movimiento que había que borrar sigue ahí."
                        )
                # Con borrados, el hueco final cambia; sin ellos, tiene que ser
                # exactamente el que eligió el usuario.
                for hueco, move_id in posiciones.items():
                    if actuales[hueco - 1] != move_id:
                        raise B2W2LiveError(
                            "El movimiento escrito no quedó en el hueco elegido."
                        )
                # Un hueco vacío delante de uno lleno no es un moveset válido.
                vacio = False
                for move_id in actuales:
                    if move_id == 0:
                        vacio = True
                    elif vacio:
                        raise B2W2LiveError(
                            "El Pokémon quedó con un hueco vacío delante de un movimiento."
                        )
            return after
        except Exception:
            restore()
            raise

    @_serialized
    def resize_party_pc(
        self, party_read: B2W2PartyRead, *, operation: str,
        party_slot: int, box: int, box_slot: int,
        expected_identity: tuple[int, int, int], incoming_party: bytes | None = None,
    ) -> tuple[B2W2PartyRead, B2W2PCRead]:
        before_party = self.read_party()
        before_pc = self.read_pc(before_party)
        if before_party.process_id != party_read.process_id:
            raise B2W2LiveError("melonDS cambió antes de redimensionar la party.")
        pc_offset = (box - 1) * PC_BOX_STRIDE + (box_slot - 1) * PK5_STORED_SIZE
        if not 0 <= pc_offset <= len(before_pc.raw) - PK5_STORED_SIZE:
            raise B2W2LiveError("El slot PC B2/W2 está fuera de rango.")
        pc_before = before_pc.raw[pc_offset:pc_offset + PK5_STORED_SIZE]
        party_host = before_party.allocation_base + (self.memory.party_data - DS_RAM_BASE)
        count_host = before_party.allocation_base + (self.memory.party_count - DS_RAM_BASE)
        pc_host = before_party.allocation_base + (self.memory.pc - DS_RAM_BASE) + pc_offset
        old_count = before_party.count
        old_raw = before_party.raw

        if operation == "party-to-box":
            if old_count <= 1 or not 0 <= party_slot < old_count:
                raise B2W2LiveError("No se puede depositar ese miembro de la party B2/W2.")
            outgoing = before_party.pokemon[party_slot]
            if (outgoing.pid, outgoing.tid, outgoing.sid) != expected_identity:
                raise B2W2LiveError("La identidad saliente B2/W2 cambió.")
            if parse_pk5_boxed(pc_before, box, box_slot) is not None:
                raise B2W2LiveError("El destino PC B2/W2 ya está ocupado.")
            new_count = old_count - 1
            new_raw = (
                old_raw[:party_slot * PK5_PARTY_SIZE]
                + old_raw[(party_slot + 1) * PK5_PARTY_SIZE:]
                + empty_pk5_party()
            )
            pc_after = old_raw[party_slot * PK5_PARTY_SIZE:party_slot * PK5_PARTY_SIZE + PK5_STORED_SIZE]
        elif operation == "box-to-party":
            if old_count >= MAX_PARTY or incoming_party is None:
                raise B2W2LiveError("No hay una casilla libre de party B2/W2.")
            incoming = parse_pk5_boxed(pc_before, box, box_slot)
            if incoming is None or (incoming.pid, incoming.tid, incoming.sid) != expected_identity:
                raise B2W2LiveError("La identidad entrante B2/W2 cambió.")
            parsed = parse_pk5_party(incoming_party, old_count)
            if (parsed.pid, parsed.tid, parsed.sid) != expected_identity:
                raise B2W2LiveError("El PK5 party entrante B2/W2 no coincide.")
            party_slot = old_count
            new_count = old_count + 1
            new_raw = old_raw + incoming_party
            # El slot PC liberado debe quedar como lo deja el juego: un PK5
            # almacenado cifrado con semilla 0. Escribir 136 ceros hacía que el
            # readback de este mismo writer los rechazara por checksum y toda
            # retirada terminase en rollback.
            pc_after = empty_pk5_stored()
        else:
            raise B2W2LiveError("Operación de tamaño B2/W2 no admitida.")

        def restore() -> None:
            self._write_process_bytes(before_party.process_id, party_host, old_raw)
            self._write_process_bytes(before_party.process_id, pc_host, pc_before)
            self._write_process_bytes(before_party.process_id, count_host, bytes((old_count,)))
            restored = self.read_party()
            restored_pc = self.read_pc(restored)
            if restored.raw != old_raw or restored_pc.raw != before_pc.raw:
                raise B2W2LiveError("Rollback de tamaño B2/W2 no confirmado; no guardes.")

        try:
            self._write_process_bytes(before_party.process_id, pc_host, pc_after)
            self._write_process_bytes(before_party.process_id, party_host, new_raw)
            self._write_process_bytes(before_party.process_id, count_host, bytes((new_count,)))
            after_party = self.read_party()
            after_pc = self.read_pc(after_party)
            if after_party.count != new_count or after_party.raw != new_raw[:new_count * PK5_PARTY_SIZE]:
                raise B2W2LiveError("El readback de party redimensionada B2/W2 no coincide.")
            if operation == "party-to-box":
                if not any(
                    (p.pid, p.tid, p.sid) == expected_identity and (p.box, p.slot) == (box, box_slot)
                    for p in after_pc.pokemon
                ):
                    raise B2W2LiveError("El depositado B2/W2 no aparece en destino.")
            elif any((p.box, p.slot) == (box, box_slot) for p in after_pc.pokemon):
                raise B2W2LiveError("El origen PC B2/W2 no quedó vacío.")
            return after_party, after_pc
        except Exception:
            restore()
            raise

    def _read_pc_rows(self, party_read: B2W2PartyRead) -> B2W2PCRead:
        # Instancia privada: los tipos ya están fijados una sola vez y ningún
        # otro módulo puede invalidarlos a mitad de llamada.
        kernel32 = _KERNEL32
        if kernel32 is None:
            raise B2W2LiveError("melonDS en Windows es obligatorio.")
        handle = kernel32.OpenProcess(0x0400 | 0x0010, False, party_read.process_id)
        if not handle:
            raise B2W2LiveError("melonDS desapareció antes de leer el PC.")

        def read_matrix() -> bytes:
            address = party_read.allocation_base + (self.memory.pc - DS_RAM_BASE)
            buffer = ctypes.create_string_buffer(PC_MATRIX_SIZE)
            received = ctypes.c_size_t()
            if not kernel32.ReadProcessMemory(
                handle, ctypes.c_void_p(address), buffer, PC_MATRIX_SIZE,
                ctypes.byref(received),
            ) or received.value != PC_MATRIX_SIZE:
                raise B2W2LiveError("Lectura incompleta de la matriz PC B2/W2.")
            return buffer.raw

        try:
            first, second = read_matrix(), read_matrix()
            if first != second:
                raise B2W2LiveError("La matriz PC B2/W2 cambió durante la doble lectura.")
            empty, pokemon = B2W2MelonDSReader.parse_pc_matrix(first)
            return B2W2PCRead(
                party_read.process_id, party_read.process_name,
                party_read.allocation_base, self.memory.pc, first, empty, pokemon,
            )
        finally:
            kernel32.CloseHandle(handle)

    @_serialized
    @perf.timed("b2w2.read_pc")
    def read_pc(self, party_read: B2W2PartyRead | None = None) -> B2W2PCRead:
        return self._read_pc_rows(party_read or self.read_party())

    @_serialized
    @perf.timed("b2w2.read_bag")
    def read_bag(self, party_read: B2W2PartyRead | None = None) -> B2W2BagRead:
        """Lee la mochila completa con doble lectura estable.

        Misma disciplina que el resto de lecturas B2/W2: dos capturas seguidas
        que deben coincidir byte a byte, y validacion completa antes de publicar.
        """
        lectura = party_read or self.read_party()
        kernel32 = _KERNEL32
        if kernel32 is None:
            raise B2W2LiveError("melonDS en Windows es obligatorio.")
        tamano = bag_size()
        direccion = lectura.allocation_base + (self.memory.bag - DS_RAM_BASE)
        handle = kernel32.OpenProcess(0x0400 | 0x0010, False, lectura.process_id)
        if not handle:
            raise B2W2LiveError("melonDS desaparecio antes de leer la mochila.")
        try:
            def leer() -> bytes:
                buffer = ctypes.create_string_buffer(tamano)
                recibido = ctypes.c_size_t()
                if not kernel32.ReadProcessMemory(
                    handle, ctypes.c_void_p(direccion), buffer, tamano,
                    ctypes.byref(recibido),
                ) or recibido.value != tamano:
                    raise B2W2LiveError("Lectura incompleta de la mochila B2/W2.")
                return buffer.raw

            primera = leer()
            segunda = leer()
        finally:
            kernel32.CloseHandle(handle)
        if primera != segunda:
            raise B2W2LiveError("La mochila B2/W2 cambio durante la doble lectura.")
        return B2W2BagRead(
            lectura.process_id, lectura.process_name, lectura.allocation_base,
            self.memory.bag, primera, parse_bag(primera),
        )

    @staticmethod
    def _read_guest_twice(lectura: B2W2PartyRead, guest: int, tamano: int) -> bytes:
        """Doble lectura estable de una direccion invitada ya demostrada."""
        kernel32 = _KERNEL32
        if kernel32 is None:
            raise B2W2LiveError("melonDS en Windows es obligatorio.")
        direccion = lectura.allocation_base + (guest - DS_RAM_BASE)
        handle = kernel32.OpenProcess(0x0400 | 0x0010, False, lectura.process_id)
        if not handle:
            raise B2W2LiveError("melonDS desaparecio antes de leer la memoria B2/W2.")
        try:
            def leer() -> bytes:
                buffer = ctypes.create_string_buffer(tamano)
                recibido = ctypes.c_size_t()
                if not kernel32.ReadProcessMemory(
                    handle, ctypes.c_void_p(direccion), buffer, tamano,
                    ctypes.byref(recibido),
                ) or recibido.value != tamano:
                    raise B2W2LiveError("Lectura incompleta de la memoria B2/W2.")
                return buffer.raw

            primera = leer()
            segunda = leer()
        finally:
            kernel32.CloseHandle(handle)
        if primera != segunda:
            raise B2W2LiveError("La memoria B2/W2 cambio durante la doble lectura.")
        return primera

    @_serialized
    def read_tm_table(self, party_read: B2W2PartyRead | None = None) -> tuple[int, ...]:
        """Lee la lista MT/MO que el juego tiene cargada, en orden de objeto.

        No se usa una tabla guardada en disco: RoleRun se juega en randomizers y
        un randomizer cambia que movimiento ensena cada MT. Lo que no cambia es
        la forma, y por eso se comprueba entera antes de publicarla.
        """
        lectura = party_read or self.read_party()
        crudo = self._read_guest_twice(
            lectura, self._demostrada(self.memory.tm_table, "La tabla de MT"),
            TM_TABLE_COUNT * 2,
        )
        movimientos = struct.unpack(f"<{TM_TABLE_COUNT}H", crudo)
        fuera = [m for m in movimientos if not 1 <= m <= MOVE_ID_MAX]
        if fuera:
            raise B2W2LiveError(
                f"La tabla de MT B2/W2 contiene {fuera[0]}, que no es un movimiento de quinta."
            )
        if len(set(movimientos)) != TM_TABLE_COUNT:
            raise B2W2LiveError("La tabla de MT B2/W2 repite un movimiento.")
        return movimientos

    @_serialized
    def read_money(self, party_read: B2W2PartyRead | None = None) -> int:
        lectura = party_read or self.read_party()
        crudo = self._read_guest_twice(lectura, self.memory.money, MONEY_SIZE)
        return int.from_bytes(crudo, "little")

    @_serialized
    def read_badges(self, party_read: B2W2PartyRead | None = None) -> int:
        """Cuenta las medallas conseguidas. Quinta las guarda como bits.

        A diferencia de ORAS, que guarda el numero, aqui cada bit es una
        medalla, asi que se cuentan los encendidos.
        """
        lectura = party_read or self.read_party()
        crudo = self._read_guest_twice(lectura, self.memory.badges, BADGES_SIZE)
        return parse_b2w2_badges(crudo)

    @_serialized
    def write_bag_items(self, party_read: B2W2PartyRead, peticiones) -> B2W2BagRead:
        """Fija cantidades de objetos como una unica transaccion.

        ``peticiones`` son pares ``(item_id, cantidad)``. Mismo contrato que el
        resto de writers B2/W2: relectura fresca, construccion validada con el
        parser de produccion, readback, verificacion semantica y rollback
        completo si algo no cuadra.
        """
        pedidos = [(int(item), int(cantidad)) for item, cantidad in peticiones]
        if not pedidos:
            raise B2W2LiveError("No hay ningun objeto B2/W2 que escribir.")
        vistos: set[int] = set()
        for item_id, _cantidad in pedidos:
            if item_id in vistos:
                raise B2W2LiveError("Dos utilidades B2/W2 sobre el mismo objeto.")
            vistos.add(item_id)

        before = self.read_bag(party_read)
        if before.process_id != party_read.process_id:
            raise B2W2LiveError("melonDS cambio antes de escribir la mochila B2/W2.")
        old_raw = before.raw
        new_raw = old_raw
        for item_id, cantidad in pedidos:
            new_raw = set_bag_quantity(new_raw, item_id, cantidad)

        if new_raw == old_raw:
            # Ya tenia esas cantidades: no se escribe un solo byte en la partida.
            return before

        bag_host = before.allocation_base + (self.memory.bag - DS_RAM_BASE)

        def restore() -> None:
            self._write_process_bytes(before.process_id, bag_host, old_raw)
            restored = self.read_bag(party_read)
            if restored.raw != old_raw:
                raise B2W2LiveError("Rollback de la mochila B2/W2 no confirmado; no guardes.")

        try:
            self._write_process_bytes(before.process_id, bag_host, new_raw)
            after = self.read_bag(party_read)
            if after.raw != new_raw:
                raise B2W2LiveError("El readback de la mochila B2/W2 no coincide.")
            for item_id, cantidad in pedidos:
                if after.quantity_of(item_id) != cantidad:
                    raise B2W2LiveError(
                        "La verificacion semantica de la mochila B2/W2 fallo."
                    )
            return after
        except Exception:
            restore()
            raise

    @_serialized
    def write_money(self, party_read: B2W2PartyRead, amount: int) -> int:
        """Fija el dinero con el mismo contrato transaccional de la mochila."""
        amount = int(amount)
        if not 0 <= amount <= MONEY_MAX:
            raise B2W2LiveError(f"B2/W2 admite como maximo {MONEY_MAX} P.")
        antes = self._read_guest_twice(party_read, self.memory.money, MONEY_SIZE)
        deseado = amount.to_bytes(MONEY_SIZE, "little")
        if antes == deseado:
            # Ya tenia esa cantidad: no se escribe un solo byte en la partida.
            return amount

        money_host = party_read.allocation_base + (self.memory.money - DS_RAM_BASE)

        def restore() -> None:
            self._write_process_bytes(party_read.process_id, money_host, antes)
            restaurado = self._read_guest_twice(party_read, self.memory.money, MONEY_SIZE)
            if restaurado != antes:
                raise B2W2LiveError("Rollback del dinero B2/W2 no confirmado; no guardes.")

        try:
            self._write_process_bytes(party_read.process_id, money_host, deseado)
            despues = self._read_guest_twice(party_read, self.memory.money, MONEY_SIZE)
            if despues != deseado:
                raise B2W2LiveError("El readback del dinero B2/W2 no coincide.")
            return amount
        except Exception:
            restore()
            raise

    @staticmethod
    def parse_pc_matrix(raw: bytes) -> tuple[int, tuple[B2W2BoxPokemon, ...]]:
        if len(raw) != PC_MATRIX_SIZE:
            raise B2W2LiveError("La matriz PC B2/W2 no mide 24 bloques de 0x1000.")
        pokemon: list[B2W2BoxPokemon] = []
        empty = 0
        for box_index in range(PC_BOX_COUNT):
            start = box_index * PC_BOX_STRIDE
            box_data = raw[start:start + PC_BOX_DATA_SIZE]
            for slot_index in range(PC_BOX_SLOT_COUNT):
                offset = slot_index * PK5_STORED_SIZE
                parsed = parse_pk5_boxed(
                    box_data[offset:offset + PK5_STORED_SIZE],
                    box_index + 1, slot_index + 1,
                )
                if parsed is None:
                    empty += 1
                else:
                    pokemon.append(parsed)
        if empty + len(pokemon) != PC_BOX_COUNT * PC_BOX_SLOT_COUNT:
            raise B2W2LiveError("La matriz PC B2/W2 no contiene 720 slots.")
        return empty, tuple(pokemon)

    @staticmethod
    def _list_melonds_processes() -> list[tuple[int, str]]:
        kernel32 = _KERNEL32
        if kernel32 is None:
            raise B2W2LiveError("melonDS en Windows es obligatorio.")
        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
        if ctypes.cast(snapshot, ctypes.c_void_p).value == ctypes.c_void_p(-1).value:
            raise B2W2LiveError("No se pudieron enumerar los procesos de Windows.")
        result: list[tuple[int, str]] = []
        try:
            entry = _PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(entry)
            ok = bool(kernel32.Process32FirstW(snapshot, ctypes.byref(entry)))
            while ok:
                name = str(entry.szExeFile)
                if name.casefold() == "melonds.exe":
                    result.append((int(entry.th32ProcessID), name))
                ok = bool(kernel32.Process32NextW(snapshot, ctypes.byref(entry)))
        finally:
            kernel32.CloseHandle(snapshot)
        return result

    def _capture_nominal_candidate(self, read, allocation: int):
        """Valida dos capturas estables de la unidad completa count+party."""
        nominal_count = int(allocation) + (self.memory.party_count - DS_RAM_BASE)
        count_1 = read(nominal_count, 1)[0]
        if not 1 <= count_1 <= MAX_PARTY:
            return None
        span = count_1 * PK5_PARTY_SIZE
        raw_1 = read(nominal_count + 4, span)
        count_2 = read(nominal_count, 1)[0]
        raw_2 = read(nominal_count + 4, span)
        if count_1 != count_2 or raw_1 != raw_2:
            return None
        pokemon = tuple(
            parse_pk5_party(
                raw_1[index * PK5_PARTY_SIZE:(index + 1) * PK5_PARTY_SIZE],
                index,
            )
            for index in range(count_1)
        )
        return count_1, raw_1, pokemon

    def _read_process(
        self, pid: int, name: str, *, known_allocation: int | None = None,
    ) -> B2W2PartyRead | None:
        """Resuelve la party dentro del proceso indicado.

        Con ``known_allocation`` se relee directamente en una base ya demostrada
        y se omite unicamente el recorrido del espacio de direcciones. Todas las
        validaciones -doble lectura estable de count+party, rango del contador y
        checksum de cada PK5- se ejecutan igual.
        """
        # Instancia privada: los tipos ya están fijados una sola vez y ningún
        # otro módulo puede invalidarlos a mitad de llamada.
        kernel32 = _KERNEL32
        if kernel32 is None:
            raise B2W2LiveError("melonDS en Windows es obligatorio.")
        handle = kernel32.OpenProcess(0x0400 | 0x0010, False, pid)
        if not handle:
            return None

        class MBI(ctypes.Structure):
            _fields_ = [
                ("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wintypes.DWORD), ("PartitionId", wintypes.WORD),
                ("RegionSize", ctypes.c_size_t), ("State", wintypes.DWORD),
                ("Protect", wintypes.DWORD), ("Type", wintypes.DWORD),
            ]

        def read(address: int, size: int) -> bytes:
            buffer = ctypes.create_string_buffer(size)
            received = ctypes.c_size_t()
            if (
                not kernel32.ReadProcessMemory(
                    handle, ctypes.c_void_p(address), buffer, size,
                    ctypes.byref(received),
                )
                or received.value != size
            ):
                raise OSError("Lectura incompleta de melonDS.")
            return buffer.raw

        try:
            if known_allocation is not None:
                with perf.span("b2w2.known_base_read") as measure:
                    candidate = self._capture_nominal_candidate(
                        read, int(known_allocation),
                    )
                    measure.add(revalidated=candidate is not None)
                if candidate is None:
                    return None
                count, raw, pokemon = candidate
                return B2W2PartyRead(pid, name, int(known_allocation), count, raw, pokemon)
            address = 0
            seen: set[int] = set()
            candidates = []
            # Instrumentación: este recorrido visita todo el espacio de
            # direcciones de melonDS en cada ciclo. Se cuentan regiones y
            # allocations sondeadas para dimensionar el coste real antes de
            # sustituirlo por una base cacheada.
            regions = 0
            with perf.span("b2w2.region_walk") as measure:
                while address < 0x7FFFFFFFFFFF:
                    mbi = MBI()
                    if not kernel32.VirtualQueryEx(
                        handle, ctypes.c_void_p(address), ctypes.byref(mbi),
                        ctypes.sizeof(mbi),
                    ):
                        break
                    regions += 1
                    base = int(mbi.BaseAddress or 0)
                    size = int(mbi.RegionSize or 0)
                    allocation = int(mbi.AllocationBase or 0)
                    if mbi.State == 0x1000 and allocation and allocation not in seen:
                        seen.add(allocation)
                        try:
                            candidate = self._capture_nominal_candidate(
                                read, allocation,
                            )
                            if candidate is not None:
                                candidates.append((allocation, *candidate))
                        except (OSError, B2W2LiveError, IndexError):
                            pass
                    address = base + max(size, 0x1000)
                measure.add(
                    regions=regions,
                    allocations=len(seen),
                    candidates=len(candidates),
                )
            if len(candidates) > 1:
                raise B2W2LiveError(
                    "melonDS expone varias parties B2/W2 válidas; la lectura es ambigua."
                )
            if not candidates:
                return None
            allocation, count, raw, pokemon = candidates[0]
            return B2W2PartyRead(pid, name, allocation, count, raw, pokemon)
        finally:
            kernel32.CloseHandle(handle)
