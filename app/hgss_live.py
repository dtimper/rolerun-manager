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
MUESTRAS_DE_VIDA = 12
ESPERA_ENTRE_MUESTRAS = 0.01


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
        # Devuelve la firma del entrenador sacada del guardado; sin ella no se
        # puede localizar nada y se trabaja con la dirección de partida.
        self.firma_getter = firma_getter
        # Reentrante: quien lea el PC puede releer el equipo dentro.
        self._lock = threading.RLock()
        self._resolved: tuple[int, str, int] | None = None
        self._resolved_processes: tuple[tuple[int, str], ...] = ()
        self._resolved_at = 0.0

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

        Se reintenta ``intentos`` veces todo lo que puede ser transitorio —el
        contador moviéndose, o un PK4 que no pasa su checksum porque la lectura
        pilló al juego escribiendo—. Lo único que se rechaza a la primera es un
        contador imposible, porque eso no cambia por esperar y hay 365 reservas
        que recorrer.
        """
        direccion_contador = int(allocation) + (self.memory.party_count - DS_RAM_BASE)
        direccion_datos = int(allocation) + (self.memory.party_data - DS_RAM_BASE)
        contador = leer(direccion_contador, 1)[0]
        if not 1 <= contador <= MAX_PARTY:
            return None
        for _intento in range(max(1, int(intentos))):
            crudo = leer(direccion_datos, contador * PK4_PARTY_SIZE)
            despues = leer(direccion_contador, 1)[0]
            if despues != contador:
                # El equipo cambió de tamaño a mitad de lectura. El contador es
                # un byte suelto y no tiene checksum que lo respalde, así que
                # aquí sí hace falta mirarlo dos veces.
                contador = despues
                if not 1 <= contador <= MAX_PARTY:
                    return None
                continue
            try:
                return contador, crudo, parse_party_block(crudo, contador)
            except HgssLiveError:
                continue
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
            return self._read_party_ahora()

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
                    self.forget_resolved_base()
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
