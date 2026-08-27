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
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass

from . import perf
from .gen4_memory import (
    GEN4_MEMORY,
    PC_BOX_COUNT,
    PC_BOX_SLOT_COUNT,
    PC_BOX_STRIDE,
    SAVE_MONEY_SIZE,
    Gen4Memory,
)
from .pk4 import (
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
# Misma política que en quinta: la base se recuerda, pero el descubrimiento
# completo -el único que detecta ambigüedad- se rehace cada minuto.
BASE_REDISCOVERY_SECONDS = 60.0
# Cuántas veces se reintenta la doble lectura antes de darla por imposible.
#
# En quinta bastaba con una: su bloque de equipo está quieto. El de HeartGold
# **no**. Medido el 27-08-2026 sobre la partida del usuario, con el juego
# corriendo: de 3000 tripletes de lecturas seguidas, 129 no coincidieron, y en
# 121 de esos las tres salieron distintas —o sea, no es un cambio que se asiente,
# es trasiego continuo—. En una parte de esas lecturas el checksum del primer
# miembro ni siquiera cuadraba, así que lo que se lee a veces es un estado roto.
#
# El checksum lo caza y nunca se publica; el problema era rendirse al primer
# intento. Con la reserva ya localizada, la captura se rechazaba en 41 de 161
# intentos —una de cada cuatro—, y la lectura entera fallaba más de la mitad de
# las veces con el juego en marcha. Eso dejaba a RoleRun sin curar, sin fijar
# roles y sin PC.
#
# Reintentar NO afloja la garantía: se sigue exigiendo que dos lecturas seguidas
# coincidan byte a byte y que cada PK4 pase su checksum. Solo se es paciente.
LECTURAS_ESTABLES_MAXIMAS = 8
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

    def __init__(self, memory: Gen4Memory | None = None) -> None:
        self.memory = memory or GEN4_MEMORY["hgss"]
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

    def _capture_nominal_candidate(self, leer, allocation: int):
        """Doble lectura estable de contador + equipo en una reserva concreta.

        Se reintenta **solo** cuando las dos lecturas no coinciden, que es lo
        único que significa «el juego estaba escribiendo justo ahora». Los dos
        veredictos de «esto no es un equipo» —contador imposible o PK4 que no
        pasa su checksum— no se reintentan nunca: repetirlos sobre las 365
        reservas del proceso costaría tiempo para llegar a la misma conclusión.
        """
        direccion_contador = int(allocation) + (self.memory.party_count - DS_RAM_BASE)
        direccion_datos = int(allocation) + (self.memory.party_data - DS_RAM_BASE)
        for _intento in range(LECTURAS_ESTABLES_MAXIMAS):
            contador_1 = leer(direccion_contador, 1)[0]
            if not 1 <= contador_1 <= MAX_PARTY:
                return None
            extension = contador_1 * PK4_PARTY_SIZE
            crudo_1 = leer(direccion_datos, extension)
            contador_2 = leer(direccion_contador, 1)[0]
            crudo_2 = leer(direccion_datos, extension)
            if contador_1 != contador_2 or crudo_1 != crudo_2:
                continue
            try:
                return contador_1, crudo_1, parse_party_block(crudo_1, contador_1)
            except HgssLiveError:
                return None
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
                candidato = self._capture_nominal_candidate(leer, int(known_allocation))
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
                        candidato = self._capture_nominal_candidate(leer, allocation)
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
        for pid, nombre in sorted(candidatos, reverse=True):
            try:
                lectura = self._read_process(pid, nombre)
                if lectura is not None:
                    self._resolved = (
                        lectura.process_id, lectura.process_name, lectura.allocation_base,
                    )
                    self._resolved_processes = firma
                    self._resolved_at = ahora
                    return lectura
            except (OSError, HgssLiveError) as exc:
                ultimo = str(exc)
        self.forget_resolved_base()
        raise HgssLiveError(ultimo)

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
            # Misma paciencia que con el equipo, y por el mismo motivo: la
            # matriz mide 72 KiB, así que es aún más fácil pillarla a mitad de
            # una escritura del juego. Fallar aquí dejaba a RoleRun sin PC.
            primera = None
            for _intento in range(LECTURAS_ESTABLES_MAXIMAS):
                primera, segunda = leer_matriz(), leer_matriz()
                if primera == segunda:
                    break
                primera = None
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
            for _intento in range(LECTURAS_ESTABLES_MAXIMAS):
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
