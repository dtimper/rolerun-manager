from __future__ import annotations

"""Lectura en vivo de HeartGold/SoulSilver dentro de melonDS.

QUÉ SE HEREDA DE QUINTA

La disciplina, entera, porque es lo que ha funcionado:

* **Doble lectura estable.** Todo se lee dos veces seguidas y las dos capturas
  tienen que coincidir byte a byte. Si el juego estaba escribiendo justo en ese
  momento, la lectura se descarta en vez de publicarse a medias.
* **Validación antes de publicar.** El contador tiene que estar entre 1 y 6 y
  cada PK4 tiene que pasar su checksum. Un bloque que no cuadre no sale.
* **Ambigüedad = error.** Si dentro del mismo proceso aparecen dos equipos
  válidos, no se elige uno: se falla. Adivinar aquí sería escribir en la partida
  equivocada más adelante.
* **Base cacheada y revalidada.** Localizar la reserva cuesta recorrer todo el
  espacio de direcciones, así que se recuerda; pero cada lectura la revalida
  igual, y cada minuto se rehace el descubrimiento completo por si apareciera un
  segundo juego a mitad de sesión.

QUÉ CAMBIA

El formato: PK4 en vez de PK5, 236 bytes por miembro y 18 cajas en vez de 24.
Y una trampa propia de cuarta que costó caro descubrir: **hay cinco copias del
equipo en memoria**, dos de ellas idénticas al archivo guardado. Ver
`gen4_memory` para por qué el ancla es la que es.

Este módulo **solo lee**. No escribe en la partida, ni en la RAM, ni activa
ninguna capacidad.
"""

import ctypes
import functools
import os
import struct
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

from . import perf
from .gen4_memory import (
    BAG_MAX_COUNT,
    SAVE_PARTY_COUNT,
    SAVE_PARTY_DATA,
    BAG_SLOT_SIZE,
    GEN4_MEMORY,
    PC_BOX_COUNT,
    PC_BOX_SLOT_COUNT,
    PC_BOX_STRIDE,
    SAVE_MONEY_SIZE,
    Gen4Memory,
)
import json  # noqa: E402  (se usa para el reparto de la mochila)

from .pk4 import (
    MOVE_ID_MAX,
    PK4_PARTY_SIZE,
    PK4_STORED_SIZE,
    Pk4Error,
    Pk4Pokemon,
    parse_pk4_boxed,
    parse_pk4_party,
)

DS_RAM_BASE = 0x02000000
MAX_PARTY = 6
MONEY_MAX = 999999
PC_BOX_DATA_SIZE = PC_BOX_SLOT_COUNT * PK4_STORED_SIZE
PC_MATRIX_SIZE = PC_BOX_COUNT * PC_BOX_STRIDE
# Las 92 MT y las 8 MO, en el orden en que el juego las guarda.
TM_TABLE_COUNT = 100
# Misma política que en quinta: la base se recuerda, pero el descubrimiento
# completo -el único que detecta ambigüedad- se rehace cada minuto.
BASE_REDISCOVERY_SECONDS = 60.0
# QUÉ DEMUESTRA QUE UNA LECTURA ES BUENA
#
# En quinta se exigía que dos lecturas seguidas coincidieran byte a byte. Con
# HeartGold eso no vale: medido el 27-08-2026 sobre la partida del usuario **con
# el juego en marcha**, de 400 intentos seguidos 304 tuvieron las dos lecturas
# distintas. Con el juego parado, 300 de 300 coincidieron. O sea: mientras se
# juega, ese bloque no para quieto, y esperar a que dos lecturas coincidan
# dejaba a RoleRun sin curar, sin PC y sin poder escribir.
#
# La prueba buena la trae el propio formato: **cada PK4 lleva su checksum de 16
# bits**, y son seis. Una lectura pillada a medias de una escritura del juego no
# los pasa —se comprobó: de las lecturas que no coincidían, una parte no pasaba
# el checksum del primer miembro—. Repetir la lectura es una prueba más débil
# que eso, no más fuerte.
#
# Así que se acepta una lectura cuando **el contador no ha cambiado alrededor de
# ella y los seis PK4 pasan su checksum**, y se reintenta cuando no. El contador
# sí se lee dos veces porque es un byte suelto, sin checksum que lo respalde.
INTENTOS_EN_LA_BUSQUEDA = 3
INTENTOS_EN_LA_BASE_CONOCIDA = 25
# Y si el recorrido entero no encuentra nada, se repite: puede haber caído justo
# en una racha mala.
INTENTOS_DE_RECORRIDO = 3
# Un dieciseisavo de la RAM del DS. Es lo mínimo que puede medir la reserva que
# contiene el mapeo del juego; por debajo de eso no vale la pena ni mirar.
TAMANO_RAM_DS = 0x00400000


class HgssLiveError(RuntimeError):
    """Error presentable de la lectura en vivo de HeartGold."""


@dataclass(frozen=True, slots=True)
class HgssPartyRead:
    process_id: int
    process_name: str
    allocation_base: int
    count: int
    raw: bytes
    pokemon: tuple[Pk4Pokemon, ...]


@dataclass(frozen=True, slots=True)
class HgssBattleRead:
    """Resultado de sondear el carril de combate de HeartGold.

    ``state``: ``"battle"`` con hueco y PS resueltos, ``"none"`` (combate
    terminado o nunca empezado) o ``"unknown"`` (las dos copias discreparon,
    o el PS no identifica un único miembro sin ambigüedad -no se inventa
    nada, se espera al siguiente sondeo).
    """

    state: str
    party_slot: int | None = None
    current_hp: int = 0
    max_hp: int = 0


@dataclass(frozen=True, slots=True)
class HgssPCRead:
    process_id: int
    process_name: str
    allocation_base: int
    guest_base: int
    raw: bytes
    empty_slots: int
    pokemon: tuple[Pk4Pokemon, ...]


@dataclass(frozen=True, slots=True)
class HgssBagPocket:
    """Un bolsillo de la mochila: dónde vive y qué objetos admite."""

    key: str
    label: str
    address: int
    slots: int
    max_count: int
    legal: frozenset[int]


@dataclass(frozen=True, slots=True)
class HgssBagRead:
    pockets: tuple[HgssBagPocket, ...]
    raw: dict[str, bytes]
    items: dict[int, int]


@dataclass(frozen=True, slots=True)
class HgssTrainerRead:
    money: int
    badges_johto: int
    badges_kanto: int

    @property
    def badge_count(self) -> int:
        return bin(self.badges_johto).count("1") + bin(self.badges_kanto).count("1")


def _kernel32():
    if os.name != "nt":
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.ReadProcessMemory.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel32.ReadProcessMemory.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    return kernel32


_KERNEL32 = _kernel32()


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260),
    ]


class _MBI(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD), ("PartitionId", wintypes.WORD),
        ("RegionSize", ctypes.c_size_t), ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD), ("Type", wintypes.DWORD),
    ]


if _KERNEL32 is not None:
    _KERNEL32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    _KERNEL32.Process32FirstW.restype = wintypes.BOOL
    _KERNEL32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    _KERNEL32.Process32NextW.restype = wintypes.BOOL
    _KERNEL32.VirtualQueryEx.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(_MBI), ctypes.c_size_t,
    ]
    _KERNEL32.VirtualQueryEx.restype = ctypes.c_size_t


def _serialized(metodo):
    """Una sola lectura a la vez: las capturas dobles no pueden entrelazarse."""

    @functools.wraps(metodo)
    def envoltorio(self, *args, **kwargs):
        with self._lock:
            return metodo(self, *args, **kwargs)

    return envoltorio


_BOLSILLOS_POR_TIPO = {
    "Items": ("items", "Objetos"),
    "KeyItems": ("key", "Objetos clave"),
    "TMHMs": ("tmhm", "MT y MO"),
    "MailItems": ("mail", "Cartas"),
    "Medicine": ("medicine", "Medicinas"),
    "Berries": ("berries", "Bayas"),
    "Balls": ("balls", "Poké Balls"),
    "BattleItems": ("battle", "Objetos de combate"),
}


@lru_cache(maxsize=1)
def _reparto_de_la_mochila() -> dict[str, tuple[int, int, frozenset[int]]]:
    """Qué objetos admite cada bolsillo, según PKHeX.

    El reparto no se supone por analogía con quinta: el Repelente Máximo vive
    en OBJETOS y el Caramelo Raro en MEDICINAS, y meterlos en el bolsillo
    equivocado los dejaría invisibles dentro del juego.
    """
    ruta = Path(__file__).resolve().parent.parent / "data" / "gen4_bag_layout.json"
    datos = json.loads(ruta.read_text(encoding="utf-8-sig"))
    salida: dict[str, tuple[int, int, frozenset[int]]] = {}
    for bolsillo in datos["bolsillos"]:
        clave, _etiqueta = _BOLSILLOS_POR_TIPO[str(bolsillo["tipo"])]
        salida[clave] = (
            int(bolsillo["huecos"]), int(bolsillo["tope"]),
            frozenset(int(valor) for valor in bolsillo["legales"]),
        )
    return salida


def bag_pockets(memory: Gen4Memory) -> tuple[HgssBagPocket, ...]:
    """Los ocho bolsillos con su dirección viva y su lista de objetos."""
    reparto = _reparto_de_la_mochila()
    salida = []
    for clave, (direccion, huecos) in memory.bag_pouches.items():
        declarados, tope, legales = reparto[clave]
        if declarados != huecos:
            raise HgssLiveError(
                f"El bolsillo {clave} declara {huecos} huecos y el reparto {declarados}."
            )
        etiqueta = next(
            nombre for _tipo, (c, nombre) in _BOLSILLOS_POR_TIPO.items() if c == clave
        )
        salida.append(HgssBagPocket(clave, etiqueta, direccion, huecos, tope, legales))
    return tuple(salida)


def bag_pocket_for(memory: Gen4Memory, item_id: int) -> HgssBagPocket:
    """A qué bolsillo pertenece un objeto."""
    for bolsillo in bag_pockets(memory):
        if int(item_id) in bolsillo.legal:
            return bolsillo
    raise HgssLiveError(
        f"El objeto #{int(item_id)} no pertenece a ningún bolsillo de HeartGold."
    )


def parse_bag_pocket(crudo: bytes, bolsillo: HgssBagPocket) -> dict[int, int]:
    """Los objetos de un bolsillo, en orden y sin huecos por medio."""
    if len(crudo) != bolsillo.slots * BAG_SLOT_SIZE:
        raise HgssLiveError(f"El bolsillo {bolsillo.key} llegó con otro tamaño.")
    dentro: dict[int, int] = {}
    visto_vacio = False
    for indice in range(bolsillo.slots):
        item_id, cantidad = struct.unpack_from("<2H", crudo, indice * BAG_SLOT_SIZE)
        if item_id == 0:
            visto_vacio = True
            continue
        if visto_vacio:
            # Un hueco vacío delante de uno lleno no es una mochila válida: el
            # juego las mantiene compactadas.
            raise HgssLiveError(
                f"El bolsillo {bolsillo.key} tiene un hueco vacío antes del final."
            )
        if item_id in dentro:
            raise HgssLiveError(
                f"El bolsillo {bolsillo.key} repite el objeto #{item_id}."
            )
        if cantidad > BAG_MAX_COUNT:
            raise HgssLiveError(
                f"El objeto #{item_id} declara {cantidad} unidades, más del tope."
            )
        dentro[item_id] = cantidad
    return dentro


def set_bag_quantity(crudo: bytes, bolsillo: HgssBagPocket, item_id: int, cantidad: int) -> bytes:
    """Fija la cantidad de un objeto conservando el compactado del bolsillo.

    Con cantidad cero el objeto desaparece y los de detrás suben. Si el objeto
    no estaba, se añade al final.
    """
    item_id, cantidad = int(item_id), int(cantidad)
    if item_id not in bolsillo.legal:
        raise HgssLiveError(
            f"El objeto #{item_id} no cabe en el bolsillo {bolsillo.key}."
        )
    if not 0 <= cantidad <= bolsillo.max_count:
        raise HgssLiveError(
            f"{bolsillo.label} admite como máximo {bolsillo.max_count} unidades."
        )
    dentro = parse_bag_pocket(crudo, bolsillo)
    if cantidad:
        dentro[item_id] = cantidad
    else:
        dentro.pop(item_id, None)
    if len(dentro) > bolsillo.slots:
        raise HgssLiveError(f"El bolsillo {bolsillo.key} se quedó sin huecos.")
    nuevo = bytearray(len(crudo))
    for indice, (identificador, unidades) in enumerate(dentro.items()):
        struct.pack_into("<2H", nuevo, indice * BAG_SLOT_SIZE, identificador, unidades)
    return bytes(nuevo)


# --------------------------------------------------------------------------
# Dónde está el bloque del guardado, que no siempre está en el mismo sitio
# --------------------------------------------------------------------------

# Firma con la que se reconoce un bloque: el nombre del entrenador y sus
# identificadores, que no cambian mientras se juega.
FIRMA_OFFSET = 0x64
FIRMA_LARGO = 0x14
# Marca que cuarta generación pone al final del bloque general, con su tamaño.
MARCA_OFFSET = 0xF620
MARCA = 0x20060623
TAMANO_BLOQUE = 0xF628
# Cuántas muestras se toman para ver cuál de los bloques se mueve.
# Cuántas veces tiene que salir el mismo contenido para creérselo.
#
# `ReadProcessMemory` devuelve registros partidos: el contenido bueno sale entre
# el 66 % y el 99 % de las veces según el hueco, y cada variante partida es una
# rareza suelta. Con tres votos, el bueno gana la carrera muy holgadamente y una
# variante necesitaría repetirse tres veces antes que él.
VOTOS_PARA_CREERSELO = 3

MUESTRAS_DE_VIDA = 12
ESPERA_ENTRE_MUESTRAS = 0.01

# --------------------------------------------------------------------------
# El carril de combate tampoco tiene dirección fija
# --------------------------------------------------------------------------

# Desplazamiento entre la copia primaria y la secundaria del PS del
# combatiente activo, demostrado dos veces sobre la partida real -el
# 06-09-2026 en `0x022CC4EC`/`0x022CC484` y el 07-09-2026, tras una
# reubicación completa, en `0x022CC568`/`0x022CC500`-: la resta da 0x68 las
# dos veces. Es una propiedad de la estructura, no de una dirección
# concreta, así que sirve para descartar coincidencias del barrido dinámico
# sin tener que pedirle al usuario que juegue en directo cada vez.
COMBATE_DESPLAZAMIENTO_SECUNDARIA = 0x68

# Cuántas transiciones de valor DISTINTAS hace falta ver en la MISMA
# dirección antes de confiar en ella cuando hay más de un candidato
# estructural. Medido contra la partida real el 07-09-2026: con cientos de
# candidatos por sesión (tablas estáticas del juego que coinciden por azar
# con el PS máximo de un miembro real), la probabilidad de que ALGUNO -sin
# relación con el combate- cambie de valor una sola vez por su cuenta ya no
# es despreciable, y ese enganche falso no se corrige solo. Exigir una
# segunda transición reduce esa probabilidad multiplicativamente.
COMBATE_CAMBIOS_PARA_CONFIRMAR = 2

# Cuánto se espera entre dos barridos completos de los 4 MiB cuando el de
# antes no encontró nada útil. Sin este freno, salir de combate -o cualquier
# otro momento en que la dirección conocida deje de servir- dejaría
# recorriendo la RAM entera en cada sondeo mientras dura el resto de la
# partida.
COMBATE_ENFRIAMIENTO_TRAS_FALLO = 0.5

# Cuántos SEGUNDOS seguidos tiene que leerse `(0, 0)` en una dirección YA
# CONFIRMADA antes de dar el combate por terminado de verdad. Medido contra
# la partida real el 07-09-2026: un `(0, 0)` suelto entre lecturas correctas
# (42→(0,0)→39) no significa que el combate terminara -dura lo que dura la
# animación del golpe, más de un segundo-, y publicarlo tal cual hace que la
# interfaz enseñe el PS de reserva -completo- mientras dura el turno,
# corrigiéndose sola al volver al menú: el parpadeo que reportó el usuario,
# primero en vídeo y después confirmado con "sube... a full vida" durante
# el turno. Se mide en TIEMPO, no en número de sondeos, porque el ritmo de
# sondeo no es constante -depende de si se está en combate o no- y un
# contador de repeticiones fijo seguía cayendo dentro de animaciones
# normales.
COMBATE_SEGUNDOS_DE_CERO_PARA_CONFIRMAR_FIN = 4.0

# Igual que el anterior, pero para cuando la dirección conocida SÍ responde y
# dice "sin combate" (0, 0) -una lectura limpia, no basura-. Un «0/0» limpio
# puede ser una reserva anterior que nunca se reescribió, no la prueba de que
# ahora mismo no hay pelea; ver el comentario de `read_battle_probe`. Más
# largo que el de arriba a propósito: aquí no hay ninguna prisa -si de
# verdad no hay combate, tardar un poco más en confirmarlo no cuesta nada-,
# así que no merece la pena barrer los 4 MiB en cada sondeo mientras el
# jugador simplemente anda explorando.
COMBATE_RECONFIRMACION_SIN_COMBATE = 2.0


@dataclass(frozen=True, slots=True)
class HgssBloque:
    """Un bloque del guardado localizado dentro de la RAM del DS."""

    address: int
    live: bool


def bloques_del_guardado(ram: bytes, firma: bytes) -> tuple[int, ...]:
    """Dónde empieza cada bloque del guardado dentro de un volcado de RAM.

    Se reconocen por dos cosas a la vez: la firma del entrenador al principio y
    la marca ``0x20060623`` que cuarta pone al final del bloque general. Con la
    firma sola aparecían cuatro en la partida del usuario; con la marca, dos.
    """
    if len(firma) != FIRMA_LARGO:
        raise HgssLiveError("La firma del entrenador no mide lo que debe.")
    salida: list[int] = []
    desde = 0
    while True:
        indice = ram.find(firma, desde)
        if indice < 0:
            return tuple(salida)
        desde = indice + 1
        principio = indice - FIRMA_OFFSET
        if principio < 0 or principio % 4:
            continue
        if principio + TAMANO_BLOQUE > len(ram):
            continue
        marca = struct.unpack_from("<I", ram, principio + MARCA_OFFSET)[0]
        if marca == MARCA:
            salida.append(principio)


def parse_party_block(crudo: bytes, cuantos: int) -> tuple[Pk4Pokemon, ...]:
    """Interpreta el bloque de equipo, o falla sin publicar nada.

    Un miembro que no cuadre invalida la lectura entera: publicar cinco de seis
    daría un equipo que el jugador no tiene.
    """
    cuantos = int(cuantos)
    if not 1 <= cuantos <= MAX_PARTY:
        raise HgssLiveError("El contador de equipo de HeartGold está fuera de rango.")
    if len(crudo) < cuantos * PK4_PARTY_SIZE:
        raise HgssLiveError("El bloque de equipo de HeartGold llegó incompleto.")
    equipo: list[Pk4Pokemon] = []
    for indice in range(cuantos):
        trozo = crudo[indice * PK4_PARTY_SIZE:(indice + 1) * PK4_PARTY_SIZE]
        try:
            miembro = parse_pk4_party(trozo, indice)
        except Pk4Error as exc:
            raise HgssLiveError(f"El miembro {indice + 1} del equipo no es un PK4: {exc}")
        if not 1 <= miembro.species_id <= 493:
            raise HgssLiveError(
                f"El miembro {indice + 1} declara la especie {miembro.species_id}."
            )
        if not 1 <= miembro.level <= 100:
            raise HgssLiveError(
                f"El miembro {indice + 1} declara el nivel {miembro.level}."
            )
        equipo.append(miembro)
    return tuple(equipo)


def parse_pc_matrix(crudo: bytes) -> tuple[int, tuple[Pk4Pokemon, ...]]:
    """Recorre las 18 cajas y devuelve (huecos vacíos, Pokémon)."""
    if len(crudo) != PC_MATRIX_SIZE:
        raise HgssLiveError("La matriz del PC de HeartGold tiene tamaño inválido.")
    vacios = 0
    dentro: list[Pk4Pokemon] = []
    for caja in range(PC_BOX_COUNT):
        inicio = caja * PC_BOX_STRIDE
        for hueco in range(PC_BOX_SLOT_COUNT):
            desde = inicio + hueco * PK4_STORED_SIZE
            trozo = crudo[desde:desde + PK4_STORED_SIZE]
            try:
                guardado = parse_pk4_boxed(trozo, caja * PC_BOX_SLOT_COUNT + hueco)
            except Pk4Error:
                # Un hueco ilegible no invalida el PC entero: se cuenta como
                # vacío y se sigue. En el equipo sí invalida, porque ahí cada
                # miembro es una casilla concreta de la pantalla.
                vacios += 1
                continue
            if guardado is None or not 1 <= guardado.species_id <= 493:
                vacios += 1
                continue
            dentro.append(guardado)
    return vacios, tuple(dentro)


class HgssMelonDSReader:
    """Lector cerrado del equipo, el PC y el entrenador de HeartGold."""

    def __init__(
        self, memory: Gen4Memory | None = None, firma_getter=None,
    ) -> None:
        # La dirección del bloque **no es fija**: se localiza. El descriptor
        # base solo aporta los desplazamientos y una dirección de partida.
        self._memoria_base = memory or GEN4_MEMORY["hgss"]
        self._memoria_detectada: Gen4Memory | None = None
        # Solo se marca cuando se ha demostrado que ese bloque es el que el
        # juego actualiza. Sin eso no se escribe.
        self._bloque_vivo = False
        # La reserva donde se localizó el bloque. Se guarda aparte de la caché
        # de lectura porque esa se olvida al fallar, y justo entonces es cuando
        # hace falta para explicar por qué.
        self._reserva_localizada: tuple[int, str, int] | None = None
        # Devuelve la firma del entrenador sacada del guardado; sin ella no se
        # puede localizar nada y se trabaja con la dirección de partida.
        self.firma_getter = firma_getter
        # Reentrante: quien lea el PC puede releer el equipo dentro.
        self._lock = threading.RLock()
        self._resolved: tuple[int, str, int] | None = None
        self._resolved_processes: tuple[tuple[int, str], ...] = ()
        self._resolved_at = 0.0
        # 06-09-2026: el combatiente activo se identifica por su PS máximo, la
        # única ancla disponible sin una fila por miembro (ver
        # `read_battle_probe`). Si dos miembros comparten ese PS máximo -nada
        # raro a nivel bajo, dos Pokémon de estadísticas parecidas-, la
        # coincidencia deja de ser única en CADA sondeo mientras siga en
        # combate, no solo en el instante del cambio: el usuario reportó que
        # el daño y el desmayo no se veían en tiempo real, solo al salir del
        # combate. Se recuerda el último hueco confirmado sin ambigüedad y,
        # si sigue siendo uno de los candidatos del sondeo actual, se sigue
        # usando su identidad en vez de rendirse.
        self._battle_ultimo_hueco: int | None = None
        # 07-09-2026: ni siquiera la dirección recién relocalizada a mano
        # es fija de verdad -el usuario reportó daño sin registrar en una
        # pelea nueva, y una lectura en vivo confirmó basura en las dos
        # direcciones sin que el juego ni el emulador se hubieran
        # reiniciado-. La estructura se reserva en tiempo de ejecución en
        # cada combate, así que se localiza igual que el bloque del
        # guardado: sin dirección fija, buscando el propio contenido.
        # Se guarda con el mismo formato que `battle_hp_primary`/
        # `battle_hp_secondary` (relativo a `DS_RAM_BASE`) para que el
        # resto del sondeo no tenga que distinguir "de la configuración" de
        # "encontrada sola" -las dos se leen exactamente igual-.
        self._battle_hp_ubicacion: tuple[int, int] | None = None
        # 07-09-2026, tercera vuelta: si `_battle_hp_ubicacion` es la
        # primera pista de `Gen4Memory` sin probar todavía, o la última que
        # `read_battle_probe` intentó y no sirvió, un `(0, 0)` ahí NO
        # demuestra que el combate haya terminado -puede que nunca haya
        # apuntado al sitio correcto-. Solo cuando el barrido dinámico ha
        # demostrado que esta dirección es el combatiente real
        # (`_battle_hp_ubicacion_confirmada = True`) un `(0, 0)` posterior
        # es una señal fiable de "combate terminado", y solo entonces se
        # olvida el historial de abajo con seguridad.
        self._battle_hp_ubicacion_confirmada: bool = False
        # Desde cuándo la dirección confirmada lleva viendo `(0, 0)` sin
        # interrupción -`None` mientras no se haya visto ninguno todavía-.
        # Ver `COMBATE_SEGUNDOS_DE_CERO_PARA_CONFIRMAR_FIN`.
        self._battle_confirmada_cero_desde: float | None = None
        self._battle_ultimo_intento_localizar: float = 0.0
        # 07-09-2026, segunda vuelta: un PS máximo compartido con un
        # candidato estructural NO basta -contra la partida real, cientos
        # de tablas estáticas del juego lo cumplen por azar-. Lo único que
        # distingue al combatiente real es que CAMBIA de valor entre dos
        # barridos, igual que `_cual_se_mueve` ya usa para el bloque del
        # guardado. Se recuerda qué valor tenía cada candidato la última vez
        # (`_battle_historial_valores`) y cuántas veces DISTINTAS ha
        # cambiado cada uno (`_battle_direcciones_cambios`); ver
        # `_localizar_combate_dinamicamente`. Séptima vuelta: un solo
        # cambio no basta -contra la partida real, algún candidato sin
        # relación con el combate cambió de valor por su cuenta una vez y
        # se quedó "confirmado" enganchado a un Pokémon que no era el que
        # combatía-, hace falta ver la MISMA dirección cambiar dos veces.
        self._battle_historial_valores: dict[int, int] = {}
        self._battle_direcciones_cambios: dict[int, int] = {}
        # Estado del último barrido (bruto/rango/final/vivas), para
        # diagnóstico -no lo usa ninguna decisión de este módulo, es
        # introspección para quien necesite entender por qué un barrido no
        # resolvió nada-. Ver `_localizar_combate_dinamicamente`.
        self._diag_ultimo_barrido: dict | None = None

    # ------------------------------------------------------------------
    # Proceso y memoria
    # ------------------------------------------------------------------

    @staticmethod
    def _list_melonds_processes() -> list[tuple[int, str]]:
        if _KERNEL32 is None:
            raise HgssLiveError("melonDS en Windows es obligatorio.")
        snapshot = _KERNEL32.CreateToolhelp32Snapshot(0x00000002, 0)
        if ctypes.cast(snapshot, ctypes.c_void_p).value == ctypes.c_void_p(-1).value:
            raise HgssLiveError("No se pudieron enumerar los procesos de Windows.")
        salida: list[tuple[int, str]] = []
        try:
            entrada = _PROCESSENTRY32W()
            entrada.dwSize = ctypes.sizeof(entrada)
            ok = bool(_KERNEL32.Process32FirstW(snapshot, ctypes.byref(entrada)))
            while ok:
                nombre = str(entrada.szExeFile)
                if nombre.casefold() == "melonds.exe":
                    salida.append((int(entrada.th32ProcessID), nombre))
                ok = bool(_KERNEL32.Process32NextW(snapshot, ctypes.byref(entrada)))
        finally:
            _KERNEL32.CloseHandle(snapshot)
        return salida

    def forget_resolved_base(self) -> None:
        """Olvida la base cacheada; la siguiente lectura vuelve a descubrirla."""
        self._resolved = None
        self._resolved_processes = ()
        self._resolved_at = 0.0

    def _capture_nominal_candidate(self, leer, allocation: int, *, intentos: int = 1):
        """Captura el equipo de una reserva, o ``None`` si no lo hay.

        UNA LECTURA SOLA NO VALE

        `ReadProcessMemory` compite con el hilo del emulador y devuelve registros
        **partidos**: medio de un instante y medio de otro. Medido sobre la
        partida viva, 300 lecturas seguidas de cada miembro a dirección fija:

            hueco 1: 288 iguales de 300      hueco 4: 286 de 300
            hueco 2: 199 iguales de 300      hueco 5: 292 de 300
            hueco 3: 297 iguales de 300      hueco 6: 293 de 300

        y las variantes siempre difieren en **tramos contiguos que acaban en
        0x87 o en 0xEB**, que son justo la frontera cuerpo/extensión y el final
        del registro. Es una lectura pillada a medias, no un cambio del juego.

        Lo peligroso es que **la extensión de combate no tiene checksum**, así
        que una lectura partida ahí pasa todas las validaciones: se vio publicar
        un Wooper con AtEsp 28801 y DefEsp 43367. Y si esa lectura se usa de base
        para escribir, lo que se escribe es un registro incoherente: eso es
        exactamente lo que el juego enseña como «Huevo malo».

        Por eso aquí no gana la primera lectura que cuadre, sino **la primera que
        se repita tres veces**. El contenido de verdad es mayoría abrumadora, así
        que llega a tres mucho antes que cualquier variante partida.

        Lo único que se rechaza a la primera es un contador imposible, porque eso
        no cambia por esperar y hay 365 reservas que recorrer.
        """
        direccion_contador = int(allocation) + (self.memory.party_count - DS_RAM_BASE)
        direccion_datos = int(allocation) + (self.memory.party_data - DS_RAM_BASE)
        contador = leer(direccion_contador, 1)[0]
        if not 1 <= contador <= MAX_PARTY:
            return None
        veces: dict[bytes, int] = {}
        for _intento in range(max(VOTOS_PARA_CREERSELO, int(intentos))):
            crudo = leer(direccion_datos, contador * PK4_PARTY_SIZE)
            despues = leer(direccion_contador, 1)[0]
            if despues != contador:
                # El equipo cambió de tamaño a mitad de lectura. El contador es
                # un byte suelto y no tiene checksum que lo respalde, así que
                # aquí sí hace falta mirarlo dos veces.
                contador = despues
                if not 1 <= contador <= MAX_PARTY:
                    return None
                veces.clear()
                continue
            veces[crudo] = veces.get(crudo, 0) + 1
            if veces[crudo] < VOTOS_PARA_CREERSELO:
                continue
            try:
                return contador, crudo, parse_party_block(crudo, contador)
            except HgssLiveError:
                # Un contenido estable que no se puede leer no mejora repitiendo:
                # que no vuelva a ganar la votación.
                veces[crudo] = -10 ** 6
        return None

    def _read_process(
        self, pid: int, nombre: str, *, known_allocation: int | None = None,
    ) -> HgssPartyRead | None:
        if _KERNEL32 is None:
            raise HgssLiveError("melonDS en Windows es obligatorio.")
        handle = _KERNEL32.OpenProcess(0x0400 | 0x0010, False, pid)
        if not handle:
            return None

        def leer(direccion: int, tamano: int) -> bytes:
            buffer = ctypes.create_string_buffer(tamano)
            recibido = ctypes.c_size_t()
            if (
                not _KERNEL32.ReadProcessMemory(
                    handle, ctypes.c_void_p(direccion), buffer, tamano,
                    ctypes.byref(recibido),
                )
                or recibido.value != tamano
            ):
                raise OSError("Lectura incompleta de melonDS.")
            return buffer.raw

        try:
            if known_allocation is not None:
                candidato = self._capture_nominal_candidate(
                    leer, int(known_allocation), intentos=INTENTOS_EN_LA_BASE_CONOCIDA,
                )
                if candidato is None:
                    return None
                contador, crudo, equipo = candidato
                return HgssPartyRead(
                    pid, nombre, int(known_allocation), contador, crudo, equipo,
                )

            direccion = 0
            vistas: set[int] = set()
            candidatos = []
            while direccion < 0x7FFFFFFFFFFF:
                mbi = _MBI()
                if not _KERNEL32.VirtualQueryEx(
                    handle, ctypes.c_void_p(direccion), ctypes.byref(mbi),
                    ctypes.sizeof(mbi),
                ):
                    break
                base = int(mbi.BaseAddress or 0)
                tamano = int(mbi.RegionSize or 0)
                allocation = int(mbi.AllocationBase or 0)
                if mbi.State == 0x1000 and allocation and allocation not in vistas:
                    vistas.add(allocation)
                    try:
                        candidato = self._capture_nominal_candidate(
                            leer, allocation, intentos=INTENTOS_EN_LA_BUSQUEDA,
                        )
                        if candidato is not None:
                            candidatos.append((allocation, *candidato))
                    except (OSError, HgssLiveError, IndexError):
                        pass
                direccion = base + max(tamano, 0x1000)

            if len(candidatos) > 1:
                raise HgssLiveError(
                    "melonDS expone varios equipos de HeartGold válidos; "
                    "la lectura es ambigua."
                )
            if not candidatos:
                return None
            allocation, contador, crudo, equipo = candidatos[0]
            return HgssPartyRead(pid, nombre, allocation, contador, crudo, equipo)
        finally:
            _KERNEL32.CloseHandle(handle)

    # ------------------------------------------------------------------
    # Lecturas públicas
    # ------------------------------------------------------------------

    @_serialized
    @perf.timed("hgss.read_party")
    def read_party(self) -> HgssPartyRead:
        """Lee el equipo, relocalizando el bloque si hiciera falta.

        El bloque del guardado se mueve dentro de la RAM, así que fallar una vez
        no significa que no esté: significa que hay que volver a buscarlo.
        """
        try:
            return self._read_party_ahora()
        except HgssLiveError:
            if not self._relocalizar(self._list_melonds_processes()):
                raise
            try:
                return self._read_party_ahora()
            except HgssLiveError:
                # El bloque está localizado y aun así no se puede leer: el
                # motivo de verdad está en el propio equipo, no en «no se
                # encontró la RAM». Decirlo por su nombre es la diferencia
                # entre saber qué pasa y no saberlo.
                self._explicar_el_bloque()
                raise

    def read_battle_probe(self, current: HgssPartyRead) -> HgssBattleRead | None:
        """Sonda conservadora del combatiente activo de HeartGold.

        Localizadas el 06-09-2026 sobre la partida real, con búsqueda de valor
        exacto en tres instantes: a diferencia de Gen5 (ORAS, X/Y, Blanco,
        Negro 2), cuarta NO mantiene una fila por miembro del equipo -se buscó
        alrededor de cada candidato y no apareció ninguna tabla-. Solo se
        demuestra al que está en el campo, igual que el diseño ORIGINAL
        -antes de la tabla- de X/Y: dos copias redundantes, ninguna basta
        sola.

        `battle_hp_primary` siguió correctamente a Totodile (38/42) y, tras un
        cambio de combatiente en la misma pelea, a Spinarak (20/23) sin
        retraso. `battle_hp_secondary` solo trae el PS actual, pero coincidió
        en los tres instantes y sirve de confirmación. Las dos vuelven a 0 al
        salir de combate, lo que da la detección de "hay combate" gratis: el
        PS máximo de la primaria es 0 fuera de una pelea.

        LA DIRECCIÓN TAMPOCO ES FIJA (07-09-2026)

        Igual que el bloque del guardado, esta estructura se reserva en
        tiempo de ejecución: se vio recolocarse tanto entre reinicios como
        DENTRO de la misma sesión, sin avisar. `self.memory.battle_hp_primary`
        /`_secondary` solo sirven de primera pista; en cuanto una lectura
        confirmada demuestra que ya no valen, se barren los 4 MiB buscando el
        propio contenido -el mismo método que sirvió para relocalizarla a
        mano el 06 y el 07-09-2026, ahora automático-.

        UN «0/0» LIMPIO TAMPOCO SE DA POR BUENO PARA SIEMPRE (07-09-2026)

        El primer barrido automático confiaba en `(0, 0)` sin condiciones,
        igual que la versión manual: es la lectura normal fuera de combate.
        Pero el usuario reportó un combate real (Rattata a 4/14) sin ver PS
        en vivo ni una sola vez, y la dirección conocida leía `(0, 0)`
        *limpio* -no basura-. La estructura vieja no tiene por qué
        reescribirse con basura al abandonarla: puede quedar sobre memoria
        nunca tocada, que ya era cero. Confiar en eso para siempre deja el
        carril ciego en CADA combate nuevo si la reserva cambia de sitio,
        que es el caso normal, no la excepción. Por eso un `(0, 0)` también
        se reconfirma por barrido -con un enfriamiento propio, más largo que
        el de una dirección claramente inválida, porque aquí no hay ninguna
        prisa: si de verdad no hay combate, no pasa nada por tardar un poco
        más en confirmarlo-.

        NO TODO «0/0» SIGNIFICA LO MISMO (07-09-2026, tercera vuelta)

        Con el barrido de "el único que cambia" ya puesto (ver
        `_localizar_combate_dinamicamente`), el usuario SIGUIÓ sin ver PS en
        vivo -ni un solo golpe en varios minutos reales-. La causa esta vez
        estaba aquí mismo: la dirección de `Gen4Memory` lee `(0, 0)` limpio
        EN CADA sondeo -nunca ha sido la correcta esta sesión-, y este
        método marcaba eso como "combate confirmado terminado" y borraba el
        historial acumulado por el barrido EN CADA LLAMADA, justo antes de
        que el barrido tuviera ocasión de acumular una segunda lectura del
        mismo candidato. El historial nunca sobrevivía de un sondeo al
        siguiente. Un `(0, 0)` en una dirección que NUNCA se ha demostrado
        correcta no es prueba de que el combate haya terminado -puede que
        nunca haya empezado a apuntar ahí-; solo un `(0, 0)` en una
        dirección que el barrido SÍ demostró ser el combatiente real es una
        señal fiable de que la pelea acabó. `_battle_hp_ubicacion_confirmada`
        distingue las dos cosas.
        """
        if _KERNEL32 is None:
            return None
        handle = _KERNEL32.OpenProcess(0x0400 | 0x0010, False, current.process_id)
        if not handle:
            return None
        try:
            ubicacion = self._battle_hp_ubicacion
            confirmada = self._battle_hp_ubicacion_confirmada
            if ubicacion is None:
                primaria = self.memory.battle_hp_primary
                secundaria = self.memory.battle_hp_secondary
                if primaria is not None and secundaria is not None:
                    ubicacion = (primaria, secundaria)
                confirmada = False

            resultado = (
                self._leer_par_combate(handle, ubicacion, current)
                if ubicacion is not None else None
            )
            if resultado is not None and resultado.state in ("battle", "unknown"):
                # El PS máximo coincidió con un miembro real del equipo -para
                # "unknown" también, `_leer_par_combate` ya descarta un PS
                # máximo que no encaje con nadie antes de llegar aquí-, así
                # que la dirección sigue siendo la correcta y no hace falta
                # reconfirmar nada por barrido.
                self._battle_hp_ubicacion = ubicacion
                self._battle_hp_ubicacion_confirmada = True
                self._battle_confirmada_cero_desde = None
                return resultado

            if confirmada and (resultado is None or resultado.state == "none"):
                # Medido contra la partida real el 07-09-2026 (quinta y sexta
                # vuelta, tras el vídeo del usuario y un caso real de OHKO
                # tras cambiar de combatiente): una dirección YA confirmada
                # puede fallar durante TODA la animación del golpe -no solo
                # con un `(0, 0)` limpio (`resultado.state == "none"`),
                # también con basura que no coincide con NINGÚN miembro del
                # equipo si la lectura se parte de otra forma
                # (`resultado is None`, ver `_leer_par_combate`)-. Las dos
                # formas de fallo son la MISMA animación vista por dos
                # caminos distintos, así que las dos merecen el mismo
                # margen: dura más de un segundo, más de lo que un simple
                # contador de repeticiones podía cubrir sin arriesgar a
                # tardar demasiado en notar un combate que sí ha terminado.
                # Tratar solo el `(0, 0)` limpio con margen y la basura sin
                # margen dejaba la MISMA interfaz enseñando el PS de reserva
                # -completo- durante el turno cada vez que la animación
                # partía la lectura de la otra forma, exactamente el mismo
                # parpadeo con un disfraz distinto. Por eso aquí no se
                # cuenta CUÁNTAS veces seguidas ha fallado, se mide CUÁNTO
                # TIEMPO lleva fallando -una animación real no dura tanto
                # como un combate entero-.
                ahora = time.monotonic()
                if self._battle_confirmada_cero_desde is None:
                    self._battle_confirmada_cero_desde = ahora
                if ahora - self._battle_confirmada_cero_desde < COMBATE_SEGUNDOS_DE_CERO_PARA_CONFIRMAR_FIN:
                    self._battle_hp_ubicacion = ubicacion
                    return HgssBattleRead(state="unknown")
                # El fallo lleva viéndose más que cualquier animación
                # normal: combate confirmado terminado de verdad. Ahora sí
                # se olvida el historial -lo que recordaba pertenece a una
                # pelea que ya no existe, y arrastrarlo solo podría causar
                # una "vivas" falsa en la siguiente-.
                self._battle_historial_valores.clear()
                self._battle_direcciones_cambios.clear()
                self._battle_hp_ubicacion = ubicacion
                self._battle_hp_ubicacion_confirmada = False
                self._battle_confirmada_cero_desde = None
                return resultado if resultado is not None else HgssBattleRead(state="none")

            # A partir de aquí `resultado` es `None` -la dirección conocida ya
            # no sirve, ni siquiera coincide con nadie- o dice "sin combate",
            # y en NINGUNO de los dos casos hay una dirección confirmada
            # detrás -si la había, ya se resolvió arriba, con margen-. Puede
            # ser cierto que no hay combate, o puede ser una dirección que
            # nunca ha demostrado nada mientras el combate real vive en un
            # hueco recién asignado. Ninguno de los dos es prueba tan fuerte
            # como para no reconfirmar nunca por barrido, y ninguno borra el
            # historial: solo cambia la prisa con la que se vuelve a mirar.
            ahora = time.monotonic()
            enfriamiento = (
                COMBATE_ENFRIAMIENTO_TRAS_FALLO if resultado is None
                else COMBATE_RECONFIRMACION_SIN_COMBATE
            )
            if ahora - self._battle_ultimo_intento_localizar < enfriamiento:
                # Todavía no ha pasado el enfriamiento desde el último
                # barrido: no se repite un barrido completo en cada sondeo,
                # pero tampoco se anuncia "sin combate" solo por no haber
                # mirado -eso perdería el último PS bueno de golpe-.
                if resultado is not None:
                    self._battle_hp_ubicacion = ubicacion
                    return resultado
                return HgssBattleRead(state="unknown")
            self._battle_ultimo_intento_localizar = ahora

            ram = self._volcar_reserva(handle, current.allocation_base)
            encontrada = (
                self._localizar_combate_dinamicamente(ram, current.pokemon)
                if ram is not None else None
            )
            if encontrada is not None:
                confirmado = self._leer_par_combate(handle, encontrada, current)
                if confirmado is not None:
                    self._battle_hp_ubicacion = encontrada
                    self._battle_hp_ubicacion_confirmada = True
                    return confirmado

            # El barrido no encontró nada mejor que lo que ya había -o ni
            # siquiera se pudo volcar la memoria-. Se conserva la última
            # lectura buena en vez de inventar nada.
            if resultado is not None:
                self._battle_hp_ubicacion = ubicacion
                return resultado
            if ram is None:
                # No se ha podido leer memoria en absoluto -no es que no haya
                # combate, es que no se ha podido comprobar nada-.
                return None
            self._battle_hp_ubicacion = None
            self._battle_hp_ubicacion_confirmada = False
            self._battle_ultimo_hueco = None
            return HgssBattleRead(state="none")
        finally:
            _KERNEL32.CloseHandle(handle)

    def _leer_par_combate(
        self, handle, ubicacion: tuple[int, int], current: HgssPartyRead,
    ) -> HgssBattleRead | None:
        """Lee y valida una ubicación candidata del carril de combate.

        Devuelve ``None`` cuando la ubicación YA NO SIRVE -hay que buscar
        otra-, y un `HgssBattleRead` en cualquier otro caso, incluida la
        ambigüedad transitoria, que no es motivo para descartar la dirección.
        Separado de `read_battle_probe` porque se prueba hasta dos veces en
        el mismo sondeo: primero la dirección conocida, y si esa ya no vale,
        la que acaba de encontrar el barrido dinámico.
        """
        primaria, secundaria = ubicacion
        direccion_primaria = current.allocation_base + (primaria - DS_RAM_BASE)
        direccion_secundaria = current.allocation_base + (secundaria - DS_RAM_BASE)
        datos_primaria = self._leer_directo(handle, direccion_primaria, 4)
        datos_secundaria = self._leer_directo(handle, direccion_secundaria, 2)
        if datos_primaria is None or datos_secundaria is None:
            return None

        current_hp, max_hp = struct.unpack("<HH", datos_primaria)
        current_hp_secundaria = struct.unpack("<H", datos_secundaria)[0]
        if max_hp == 0:
            self._battle_ultimo_hueco = None
            # NO se toca aquí el historial del barrido -esta función no sabe
            # si `ubicacion` es una dirección ya demostrada o solo la
            # primera pista sin probar de `Gen4Memory`-. Esa distinción
            # vive en `read_battle_probe`, que es quien decide cuándo un
            # `(0, 0)` de verdad significa "combate terminado" y cuándo
            # borrarlo sería tirar evidencia acumulada de una pelea que
            # sigue en marcha en otro sitio.
            return HgssBattleRead(state="none")

        # El PS máximo tiene que corresponder a un miembro real ANTES de
        # conceder ninguna otra indulgencia: basura de otra estructura puede
        # coincidir por azar en que las dos copias estén de acuerdo -sobre
        # todo si las dos leen 0-, pero que su PS máximo sea EXACTAMENTE el
        # de un miembro concreto del equipo actual ya no es azar. Sin este
        # orden, una dirección movida a basura permanente podía quedarse
        # leyendo "unknown" para siempre y no disparar nunca la relocalización.
        candidatos = [
            pokemon for pokemon in current.pokemon
            if int(pokemon.max_hp) == max_hp
        ]
        if not candidatos:
            return None
        if current_hp != current_hp_secundaria:
            # Instante de transición entre las dos copias: no se publica nada
            # nuevo, y quien llama conserva la última lectura buena. Esto NO
            # invalida la dirección: es ruido normal a mitad de tick.
            return HgssBattleRead(state="unknown")
        if not (0 <= current_hp <= max_hp):
            return None
        if len(candidatos) == 1:
            self._battle_ultimo_hueco = candidatos[0].slot
            return HgssBattleRead(
                state="battle", party_slot=candidatos[0].slot,
                current_hp=current_hp, max_hp=max_hp,
            )
        # Sin especie en esta copia, el PS máximo es la única ancla, y dos
        # miembros con el mismo máximo son indistinguibles A PRIMERA VISTA.
        # Pero si uno de ellos es el que ya se había confirmado como
        # combatiente activo, esa identidad no ha dejado de ser válida solo
        # porque el sondeo de AHORA vuelva a ser ambiguo -el PS máximo no
        # cambia mientras no suba de nivel, así que seguir siendo uno de los
        # candidatos es la misma prueba que ya sirvió antes-. Sin esto, dos
        # miembros con el mismo PS máximo dejaban el combate entero sin PS en
        # vivo, no solo el instante del cambio.
        if self._battle_ultimo_hueco is not None:
            confirmado = next(
                (p for p in candidatos if p.slot == self._battle_ultimo_hueco), None,
            )
            if confirmado is not None:
                return HgssBattleRead(
                    state="battle", party_slot=confirmado.slot,
                    current_hp=current_hp, max_hp=max_hp,
                )
        return HgssBattleRead(state="unknown")

    def _localizar_combate_dinamicamente(
        self, ram: bytes, pokemon: tuple,
    ) -> tuple[int, int] | None:
        """Busca en un volcado de RAM el par <PS actual, PS máximo>.

        LA DIRECCIÓN NO ES FIJA, TAMPOCO AQUÍ

        Igual que el bloque del guardado, la estructura de combate se reserva
        en tiempo de ejecución y puede recolocarse -medido el 07-09-2026: se
        movió entre dos peleas de la MISMA sesión, sin reiniciar el juego ni
        el emulador-. Sin firma de bytes que buscar, la única ancla es el
        propio contenido: un PS máximo que coincida con un miembro real del
        equipo actual, con su PS actual dentro de rango.

        Eso solo, sin embargo, puede coincidir por azar en 4 MiB -y de sobra,
        medido contra la partida real: no es una coincidencia rara, es
        normal-. La copia secundaria, `COMBATE_DESPLAZAMIENTO_SECUNDARIA`
        bytes antes, tiene que traer el mismo PS actual por separado, pero
        ESO SOLO TAMPOCO BASTA.

        UN PS MÁXIMO COMPARTIDO NO ES SUFICIENTE (07-09-2026, segunda vuelta)

        El primer barrido automático se paró aquí y nunca encontró nada
        durante un combate real: el usuario recibió golpes de verdad y
        siguió sin ver PS en vivo. Medido con un volcado real: un solo
        barrido produce entre cien y varios cientos de posiciones que
        cumplen LAS DOS comprobaciones de arriba -el PS máximo de un
        miembro real, con su PS actual en rango y la secundaria de
        acuerdo-. La inmensa mayoría son tablas estáticas del propio juego
        -niveles, movimientos, estadísticas base...- que por pura
        casualidad repiten números pequeños a `COMBATE_DESPLAZAMIENTO_
        SECUNDARIA` bytes de distancia. Con las estadísticas del equipo
        real (14/21/27/51) esto dio 327 candidatos en un solo barrido.

        La única propiedad que de verdad distingue al combatiente activo es
        la misma que ya usa `_cual_se_mueve` para el bloque del guardado:
        ES EL ÚNICO QUE CAMBIA. Medido con el usuario recibiendo golpes
        durante 20 segundos reales: de 327 candidatos estructurales,
        exactamente UNO cambió de valor -el verdadero-. Por eso, cuando hay
        más de un candidato, este método NO resuelve nada en la primera
        llamada: recuerda qué valor tenía cada uno la última vez que se le
        vio (`_battle_historial_valores`), y solo publica una dirección
        cuando ha demostrado cambiar de valor entre dos barridos Y sigue
        siendo un candidato válido ahora mismo. Si el barrido ya da un único
        candidato en TODA la RAM, esa prueba basta sola, sin esperar a
        verlo cambiar -es el caso ideal, y ya lo cubrían los tests
        anteriores-.
        """
        maximos_conocidos = {int(p.max_hp) for p in pokemon if int(p.max_hp) > 0}
        # DIAGNÓSTICO TEMPORAL 07-09-2026: cuenta en qué etapa se descartan
        # los candidatos. Quitar en cuanto se confirme que el mecanismo de
        # "el único que cambia" resuelve de verdad en la partida real.
        bruto = rango = 0
        candidatos: dict[int, int] = {}
        for maximo in maximos_conocidos:
            necesita = struct.pack("<H", maximo)
            inicio = 0
            while True:
                pos = ram.find(necesita, inicio)
                if pos == -1:
                    break
                inicio = pos + 1
                bruto += 1
                base_estructura = pos - 2
                base_secundaria = base_estructura - COMBATE_DESPLAZAMIENTO_SECUNDARIA
                if base_estructura < 0 or base_secundaria < 0:
                    continue
                actual = struct.unpack_from("<H", ram, base_estructura)[0]
                if not (0 <= actual <= maximo):
                    continue
                rango += 1
                actual_secundaria = struct.unpack_from("<H", ram, base_secundaria)[0]
                if actual_secundaria != actual:
                    continue
                candidatos[DS_RAM_BASE + base_estructura] = actual

        if len(candidatos) == 1:
            (direccion, _valor), = candidatos.items()
            self._diag_ultimo_barrido = {
                "maximos": sorted(maximos_conocidos), "bruto": bruto,
                "rango": rango, "final": 1, "vivas": None,
            }
            return direccion, direccion - COMBATE_DESPLAZAMIENTO_SECUNDARIA

        # 07-09-2026, séptima vuelta: UN cambio no basta. Medido contra la
        # partida real -Rattata combatiendo de verdad, y el lector se quedó
        # enganchado a Totodile en `51/51` sin moverse nunca-: con cientos
        # de candidatos estructurales por sesión, la probabilidad de que
        # ALGUNO de ellos -sin tener nada que ver con el combate- cambie de
        # valor una sola vez por pura casualidad -otro sistema del juego
        # tocando esa misma memoria por su cuenta- ya no es despreciable, y
        # ese enganche falso no se corrige nunca solo porque una dirección
        # NO tiene por qué dejar de cumplir las comprobaciones estructurales
        # después de "confirmada" una sola vez. Exigir una SEGUNDA
        # transición distinta reduce esa probabilidad multiplicativamente
        # -que la MISMA dirección equivocada cambie dos veces por
        # casualidad, y las dos veces siga pasando ambas comprobaciones, es
        # mucho menos probable que una sola vez-, a costa de tardar un poco
        # más en confirmar el combate real.
        # Octava vuelta, el mismo día: exigir SIEMPRE dos transiciones deja
        # sin forma de confirmarse a un Pokémon rematado de un solo golpe
        # -medido en vivo: Rattata a 14/14, un golpe y muerto, sin que
        # quedara combate después para dar una segunda transición-. Una
        # transición QUE LLEGA A CERO es una señal mucho más fuerte que
        # cualquier otra: que una coincidencia sin relación con el combate
        # aterrice justo en cero, ADEMÁS de coincidir con el PS máximo
        # EXACTO de un miembro real, es mucho menos probable que aterrizar
        # en cualquier otro valor del rango. Por eso esa transición sola ya
        # basta, mientras que cualquier otra sigue exigiendo la segunda.
        vivas_ahora: list[int] = []
        for direccion, valor in candidatos.items():
            visto_antes = self._battle_historial_valores.get(direccion)
            if visto_antes is not None and visto_antes != valor:
                self._battle_direcciones_cambios[direccion] = (
                    self._battle_direcciones_cambios.get(direccion, 0) + 1
                )
            self._battle_historial_valores[direccion] = valor
            cambios = self._battle_direcciones_cambios.get(direccion, 0)
            confirmada_por_desmayo = cambios >= 1 and valor == 0
            if cambios >= COMBATE_CAMBIOS_PARA_CONFIRMAR or confirmada_por_desmayo:
                vivas_ahora.append(direccion)

        self._diag_ultimo_barrido = {
            "maximos": sorted(maximos_conocidos), "bruto": bruto, "rango": rango,
            "final": len(candidatos), "vivas": len(vivas_ahora),
        }
        if len(vivas_ahora) != 1:
            return None
        direccion = vivas_ahora[0]
        return direccion, direccion - COMBATE_DESPLAZAMIENTO_SECUNDARIA

    def _explicar_el_bloque(self) -> None:
        """Lanza el motivo real por el que no se puede leer el equipo localizado.

        Si un miembro está dañado —por ejemplo un «Huevo malo»—, el equipo entero
        deja de poder leerse, y sin esto el mensaje culpaba a la búsqueda de la
        RAM en vez de señalar al Pokémon.
        """
        recordada = self._reserva_localizada
        if recordada is None or _KERNEL32 is None:
            return
        pid, _nombre, allocation = recordada
        handle = _KERNEL32.OpenProcess(0x0400 | 0x0010, False, pid)
        if not handle:
            return
        try:
            contador = self._leer_directo(
                handle, allocation + (self.memory.party_count - DS_RAM_BASE), 1,
            )
            if contador is None or not 1 <= contador[0] <= MAX_PARTY:
                return
            crudo = self._leer_directo(
                handle, allocation + (self.memory.party_data - DS_RAM_BASE),
                contador[0] * PK4_PARTY_SIZE,
            )
            if crudo is None:
                return
            # Si esto lanza, lanza con el motivo bueno; si no, no se dice nada y
            # gana el error de arriba.
            parse_party_block(crudo, contador[0])
        finally:
            _KERNEL32.CloseHandle(handle)

    def _read_party_ahora(self) -> HgssPartyRead:
        if os.name != "nt":
            raise HgssLiveError("melonDS en Windows es obligatorio.")
        candidatos = self._list_melonds_processes()
        if not candidatos:
            self.forget_resolved_base()
            raise HgssLiveError("melonDS no está abierto.")
        firma = tuple(sorted(candidatos))
        ahora = time.monotonic()

        recordada = self._resolved
        if (
            recordada is not None
            and firma == self._resolved_processes
            and ahora - self._resolved_at < BASE_REDISCOVERY_SECONDS
        ):
            pid, nombre, allocation = recordada
            try:
                lectura = self._read_process(pid, nombre, known_allocation=allocation)
            except (OSError, HgssLiveError):
                lectura = None
            if lectura is not None:
                return lectura

        ultimo = "No se localizó la RAM DS validada de HeartGold."
        for _vuelta in range(INTENTOS_DE_RECORRIDO):
            for pid, nombre in sorted(candidatos, reverse=True):
                try:
                    lectura = self._read_process(pid, nombre)
                    if lectura is not None:
                        self._resolved = (
                            lectura.process_id, lectura.process_name,
                            lectura.allocation_base,
                        )
                        self._resolved_processes = firma
                        self._resolved_at = ahora
                        return lectura
                except (OSError, HgssLiveError) as exc:
                    ultimo = str(exc)
        self.forget_resolved_base()
        raise HgssLiveError(ultimo)

    # ------------------------------------------------------------------
    # Localizar el bloque, que no siempre está en el mismo sitio
    # ------------------------------------------------------------------

    def _volcar_reserva(self, handle, base: int) -> bytes | None:
        buffer = ctypes.create_string_buffer(TAMANO_RAM_DS)
        recibido = ctypes.c_size_t()
        ok = _KERNEL32.ReadProcessMemory(
            handle, ctypes.c_void_p(base), buffer, TAMANO_RAM_DS,
            ctypes.byref(recibido),
        )
        return buffer.raw if ok and recibido.value == TAMANO_RAM_DS else None

    def _reservas(self, handle) -> list[int]:
        direccion, vistas = 0, {}
        while direccion < 0x7FFFFFFFFFFF:
            mbi = _MBI()
            if not _KERNEL32.VirtualQueryEx(
                handle, ctypes.c_void_p(direccion), ctypes.byref(mbi),
                ctypes.sizeof(mbi),
            ):
                break
            base = int(mbi.BaseAddress or 0)
            tamano = int(mbi.RegionSize or 0)
            reserva = int(mbi.AllocationBase or 0)
            if mbi.State == 0x1000 and reserva:
                vistas[reserva] = vistas.get(reserva, 0) + tamano
            direccion = base + max(tamano, 0x1000)
        return [
            reserva for reserva, tamano in sorted(vistas.items())
            if TAMANO_RAM_DS <= tamano <= 0x40000000
        ]

    def _cual_se_mueve(self, handle, reserva: int, principios) -> int | None:
        """De varios bloques, el que el juego está actualizando.

        Medido el 28-08-2026 sobre la partida del usuario: en 30 muestras
        tomadas en tres décimas de segundo, el bloque vivo cambió **nueve
        veces** y la copia congelada **ninguna**. No hacía falta ni que
        estuviera en combate.

        Es la misma prueba de dos estados que localizó las filas de combate de
        Blanco, y es la única que distingue de verdad: por dentro los dos
        bloques se parecen tanto que tienen hasta el mismo pie.
        """
        if len(principios) == 1:
            return principios[0]
        vistos: dict[int, set[bytes]] = {p: set() for p in principios}
        for _muestra in range(MUESTRAS_DE_VIDA):
            for principio in principios:
                crudo = self._leer_directo(
                    handle, reserva + principio + SAVE_PARTY_COUNT,
                    4 + MAX_PARTY * PK4_PARTY_SIZE,
                )
                if crudo is not None:
                    vistos[principio].add(crudo)
            time.sleep(ESPERA_ENTRE_MUESTRAS)
        moviles = [p for p, contenidos in vistos.items() if len(contenidos) > 1]
        return moviles[0] if len(moviles) == 1 else None

    @staticmethod
    def _leer_directo(handle, direccion: int, tamano: int) -> bytes | None:
        buffer = ctypes.create_string_buffer(tamano)
        recibido = ctypes.c_size_t()
        ok = _KERNEL32.ReadProcessMemory(
            handle, ctypes.c_void_p(direccion), buffer, tamano, ctypes.byref(recibido),
        )
        return buffer.raw if ok and recibido.value == tamano else None

    def _relocalizar(self, candidatos) -> bool:
        """Vuelve a buscar el bloque del guardado y actualiza las direcciones.

        La dirección **no es fija**: el bloque del equipo estuvo en
        `0x0227C304` y apareció después treinta y seis bytes más allá. Dar la
        dirección por sabida fue lo que dejó un «Huevo malo» en la partida del
        usuario, así que aquí se busca de verdad cada vez que hace falta.
        """
        firma = None
        obtener = self.firma_getter
        if callable(obtener):
            try:
                firma = obtener()
            except Exception:
                firma = None
        if not firma or len(firma) != FIRMA_LARGO:
            return False

        for pid, _nombre in sorted(candidatos, reverse=True):
            handle = _KERNEL32.OpenProcess(0x0400 | 0x0010, False, pid)
            if not handle:
                continue
            try:
                for reserva in self._reservas(handle):
                    ram = self._volcar_reserva(handle, reserva)
                    if ram is None or firma not in ram:
                        continue
                    principios = bloques_del_guardado(ram, firma)
                    if not principios:
                        continue
                    elegido = self._cual_se_mueve(handle, reserva, principios)
                    if elegido is None:
                        # Varios bloques y ninguno se mueve: el juego está
                        # parado. Se puede leer, pero no se marca como vivo, y
                        # sin eso la escritura no se permite.
                        elegido, vivo = principios[0], False
                    else:
                        vivo = True
                    self._memoria_detectada = replace(
                        self._memoria_base,
                        party_data=DS_RAM_BASE + elegido + SAVE_PARTY_DATA,
                    )
                    self._bloque_vivo = vivo
                    # Y se recuerda la reserva: acabamos de demostrar cuál es,
                    # así que la siguiente lectura debe ir directa y con toda la
                    # paciencia, no recorrer otra vez las 365 con la justa.
                    self._reserva_localizada = (pid, _nombre, reserva)
                    self._resolved = (pid, _nombre, reserva)
                    self._resolved_processes = tuple(sorted(candidatos))
                    self._resolved_at = time.monotonic()
                    return True
            finally:
                _KERNEL32.CloseHandle(handle)
        return False

    def _abrir(self, party_read: HgssPartyRead, para: str):
        if _KERNEL32 is None:
            raise HgssLiveError("melonDS en Windows es obligatorio.")
        handle = _KERNEL32.OpenProcess(0x0400 | 0x0010, False, party_read.process_id)
        if not handle:
            raise HgssLiveError(f"melonDS desapareció antes de leer {para}.")
        return handle

    @_serialized
    @perf.timed("hgss.read_pc")
    def read_pc(self, party_read: HgssPartyRead | None = None) -> HgssPCRead:
        lectura = party_read or self.read_party()
        handle = self._abrir(lectura, "el PC")

        def leer_matriz() -> bytes:
            direccion = lectura.allocation_base + (self.memory.pc - DS_RAM_BASE)
            buffer = ctypes.create_string_buffer(PC_MATRIX_SIZE)
            recibido = ctypes.c_size_t()
            if not _KERNEL32.ReadProcessMemory(
                handle, ctypes.c_void_p(direccion), buffer, PC_MATRIX_SIZE,
                ctypes.byref(recibido),
            ) or recibido.value != PC_MATRIX_SIZE:
                raise HgssLiveError("Lectura incompleta de la matriz PC de HeartGold.")
            return buffer.raw

        try:
            # La matriz mide 72 KiB, así que es todavía más fácil pillarla a
            # mitad de una escritura del juego. Se exige que dos lecturas
            # coincidan; si no lo consiguen, basta con que **digan lo mismo**:
            # los mismos Pokémon en los mismos huecos. Eso descarta publicar un
            # estado mezclado sin depender de que 72 KiB no se muevan.
            primera = anterior = None
            contenido_anterior = None
            for _intento in range(INTENTOS_EN_LA_BASE_CONOCIDA):
                actual = leer_matriz()
                vacios, dentro = parse_pc_matrix(actual)
                contenido = tuple(
                    (p.slot, p.pid, p.tid, p.sid, p.species_id) for p in dentro
                )
                if anterior is not None and (
                    actual == anterior or contenido == contenido_anterior
                ):
                    primera = actual
                    break
                anterior, contenido_anterior = actual, contenido
            if primera is None:
                raise HgssLiveError(
                    "La matriz PC de HeartGold no se quedó quieta el tiempo "
                    "suficiente para leerla entera."
                )
            vacios, dentro = parse_pc_matrix(primera)
            return HgssPCRead(
                lectura.process_id, lectura.process_name, lectura.allocation_base,
                self.memory.pc, primera, vacios, dentro,
            )
        finally:
            _KERNEL32.CloseHandle(handle)

    @_serialized
    @perf.timed("hgss.read_tm_table")
    def read_tm_table(self, party_read: HgssPartyRead | None = None) -> tuple[int, ...]:
        """Qué movimiento enseña cada MT **en esta partida**.

        Se lee del juego y no de una tabla guardada: RoleRun se juega en
        randomizers, y ahí cada MT enseña otra cosa. Un randomizer cambia el
        contenido de la tabla, no su posición.
        """
        direccion = self._demostrada(self.memory.tm_table, "La tabla de MT")
        lectura = party_read or self.read_party()
        handle = self._abrir(lectura, "la tabla de MT")
        tamano = TM_TABLE_COUNT * 2

        def capturar() -> bytes:
            buffer = ctypes.create_string_buffer(tamano)
            recibido = ctypes.c_size_t()
            if not _KERNEL32.ReadProcessMemory(
                handle,
                ctypes.c_void_p(lectura.allocation_base + (direccion - DS_RAM_BASE)),
                buffer, tamano, ctypes.byref(recibido),
            ) or recibido.value != tamano:
                raise HgssLiveError("Lectura incompleta de la tabla de MT.")
            return buffer.raw

        try:
            crudo = None
            for _intento in range(INTENTOS_EN_LA_BASE_CONOCIDA):
                primera, segunda = capturar(), capturar()
                if primera == segunda:
                    crudo = primera
                    break
            if crudo is None:
                raise HgssLiveError("La tabla de MT de HeartGold no se quedó quieta.")
            tabla = struct.unpack(f"<{TM_TABLE_COUNT}H", crudo)
            if any(not 1 <= valor <= MOVE_ID_MAX for valor in tabla):
                raise HgssLiveError(
                    "La tabla de MT declara un movimiento que no existe en cuarta."
                )
            return tabla
        finally:
            _KERNEL32.CloseHandle(handle)

    @property
    def memory(self) -> Gen4Memory:
        """Las direcciones que valen ahora mismo, no las de la primera vez."""
        return self._memoria_detectada or self._memoria_base

    @property
    def block_is_live(self) -> bool:
        """Si se demostró que el bloque localizado es el que el juego actualiza."""
        return bool(self._bloque_vivo)

    @_serialized
    def retry_block_liveness(self) -> bool:
        """Repite la muestra de "cuál bloque se mueve" bajo demanda.

        06-09-2026: `read_party()` solo repite la localización completa
        -incluida esta prueba- cuando la lectura barata falla con una
        excepción; si la PRIMERA muestra de esta sesión cayó en un instante
        sin movimiento en la RAM del equipo, `block_is_live` se queda en
        `False` el resto de la conexión aunque el juego siga corriendo con
        normalidad -reintentar una escritura no ayuda, la lectura barata
        sigue sirviendo la misma base ya resuelta-. La muestra en sí es
        barata (`MUESTRAS_DE_VIDA` × `ESPERA_ENTRE_MUESTRAS`, ~0,12 s), así
        que pedirla de nuevo justo antes de escribir, cuando ya salió
        negativa una vez, no cuesta nada frente al beneficio.
        """
        if self._bloque_vivo:
            return True
        candidatos = self._list_melonds_processes()
        if not candidatos:
            return False
        self._relocalizar(candidatos)
        return bool(self._bloque_vivo)

    def _demostrada(self, direccion: int | None, capacidad: str) -> int:
        """Dirección de una capacidad, o un error claro si no se demostró.

        Un juego puede tener ancla y todavía no tener tabla de MT: esa no vive
        en el bloque del guardado, así que no sale de la resta.
        """
        if direccion is None:
            raise HgssLiveError(
                f"{capacidad} todavía no está demostrada en {self.memory.label}."
            )
        return int(direccion)

    @_serialized
    @perf.timed("hgss.read_bag")
    def read_bag(self, party_read: HgssPartyRead | None = None) -> HgssBagRead:
        """Lee los ocho bolsillos, con la misma paciencia que el resto."""
        lectura = party_read or self.read_party()
        handle = self._abrir(lectura, "la mochila")
        bolsillos = bag_pockets(self.memory)

        def leer(invitado: int, tamano: int) -> bytes:
            direccion = lectura.allocation_base + (invitado - DS_RAM_BASE)
            buffer = ctypes.create_string_buffer(tamano)
            recibido = ctypes.c_size_t()
            if not _KERNEL32.ReadProcessMemory(
                handle, ctypes.c_void_p(direccion), buffer, tamano,
                ctypes.byref(recibido),
            ) or recibido.value != tamano:
                raise HgssLiveError("Lectura incompleta de la mochila de HeartGold.")
            return buffer.raw

        def capturar() -> dict[str, bytes]:
            return {
                bolsillo.key: leer(bolsillo.address, bolsillo.slots * BAG_SLOT_SIZE)
                for bolsillo in bolsillos
            }

        try:
            crudo = None
            for _intento in range(INTENTOS_EN_LA_BASE_CONOCIDA):
                primera, segunda = capturar(), capturar()
                if primera == segunda:
                    crudo = primera
                    break
            if crudo is None:
                raise HgssLiveError("La mochila de HeartGold no se quedó quieta.")
            objetos: dict[int, int] = {}
            for bolsillo in bolsillos:
                objetos.update(parse_bag_pocket(crudo[bolsillo.key], bolsillo))
            return HgssBagRead(bolsillos, crudo, objetos)
        finally:
            _KERNEL32.CloseHandle(handle)

    @_serialized
    @perf.timed("hgss.read_trainer")
    def read_trainer(self, party_read: HgssPartyRead | None = None) -> HgssTrainerRead:
        """Dinero y medallas, con la misma doble lectura estable."""
        lectura = party_read or self.read_party()
        handle = self._abrir(lectura, "los datos del entrenador")

        def leer(invitado: int, tamano: int) -> bytes:
            direccion = lectura.allocation_base + (invitado - DS_RAM_BASE)
            buffer = ctypes.create_string_buffer(tamano)
            recibido = ctypes.c_size_t()
            if not _KERNEL32.ReadProcessMemory(
                handle, ctypes.c_void_p(direccion), buffer, tamano,
                ctypes.byref(recibido),
            ) or recibido.value != tamano:
                raise HgssLiveError("Lectura incompleta de los datos del entrenador.")
            return buffer.raw

        def capturar() -> tuple[int, int, int]:
            return (
                int.from_bytes(leer(self.memory.money, SAVE_MONEY_SIZE), "little"),
                leer(self.memory.badges, 1)[0],
                leer(self.memory.badges_kanto, 1)[0],
            )

        try:
            primera = None
            for _intento in range(INTENTOS_EN_LA_BASE_CONOCIDA):
                primera, segunda = capturar(), capturar()
                if primera == segunda:
                    break
                primera = None
            if primera is None:
                raise HgssLiveError(
                    "Los datos del entrenador de HeartGold no se quedaron quietos."
                )
            dinero, johto, kanto = primera
            if dinero > MONEY_MAX:
                raise HgssLiveError(
                    f"El dinero leído ({dinero}) supera el máximo del juego."
                )
            return HgssTrainerRead(dinero, johto, kanto)
        finally:
            _KERNEL32.CloseHandle(handle)


def party_block_offsets(memory: Gen4Memory, slot: int) -> tuple[int, int]:
    """Dirección invitada y tamaño del miembro ``slot`` (0-5) del equipo."""
    if not 0 <= int(slot) < MAX_PARTY:
        raise HgssLiveError("El hueco del equipo está fuera de rango.")
    return memory.party_data + int(slot) * PK4_PARTY_SIZE, PK4_PARTY_SIZE


def pc_slot_offset(memory: Gen4Memory, box: int, slot: int) -> int:
    """Dirección invitada del hueco ``slot`` (1-30) de la caja ``box`` (1-18)."""
    if not 1 <= int(box) <= PC_BOX_COUNT:
        raise HgssLiveError("La caja del PC está fuera de rango.")
    if not 1 <= int(slot) <= PC_BOX_SLOT_COUNT:
        raise HgssLiveError("El hueco del PC está fuera de rango.")
    return (
        memory.pc
        + (int(box) - 1) * PC_BOX_STRIDE
        + (int(slot) - 1) * PK4_STORED_SIZE
    )
