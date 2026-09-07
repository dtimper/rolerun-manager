"""Localiza y parchea la imagen de la ROM de quinta dentro de melonDS.

En 3DS el parche de aprendizajes es un archivo (LayeredFS) que el emulador
relee. En NDS no existe nada equivalente, pero **melonDS mantiene la imagen
entera de la ROM en su propia memoria y en una región de escritura** —medido
el 06-09-2026 contra la partida real: base ``0x023029D61040``, región de 344
MB con protección ``READWRITE``, cabecera ``POKEMON B2`` en la base y la tabla
de aprendizajes idéntica byte a byte a la del archivo .nds—.

Aquí solo vive la parte de MEMORIA: encontrar dónde está la imagen y escribir
o restaurar entradas sueltas. Qué escribir lo decide
``app/gen5_levelup_moves.py``, y el archivo .nds del usuario **no se toca
nunca**: es la fuente de la verdad vainilla y se abre siempre en solo lectura.

Cómo se localiza, sin suponer nada:

1. Se elige como ancla la especie con la tabla de aprendizajes MÁS LARGA. Es
   una secuencia larga y muy específica (100 bytes en B2/W2), imposible de
   encontrar por azar: en el barrido real de 1,8 GB de melonDS apareció
   exactamente una vez.
2. Se recorren las regiones de memoria del proceso buscándola. De cada
   coincidencia se deduce dónde empezaría la ROM y se **verifica** con dos
   comprobaciones independientes: la cabecera del .nds en esa base, y una
   segunda especie leída en su posición. Una base que no pase las dos se
   descarta.
3. Si quedan varias bases distintas y válidas, se rechaza por ambigua en vez
   de elegir una: nunca se escribe sobre una dirección que no se ha podido
   demostrar.
"""

from __future__ import annotations

import ctypes
import os
import struct
from collections.abc import Mapping
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

#: Cuánto se mira al principio de una asignación candidata buscando la
#: cabecera del .nds. Medido: melonDS deja la imagen a 0x1040 del inicio de su
#: asignación, así que en la práctica se encuentra en la primera lectura. Si no
#: apareciera ahí, se recurre al barrido completo de esa misma asignación.
HEADER_PROBE_SIZE = 1 * 1024 * 1024

#: Leer memoria de otro proceso ronda los 25 MB/s, así que el barrido completo
#: se hace por trozos y solo dentro de las asignaciones que ya han pasado el
#: filtro de tamaño.
CHUNK_SIZE = 16 * 1024 * 1024

_MEM_COMMIT = 0x1000
#: Protecciones sobre las que tiene sentido buscar. Se excluyen las de solo
#: ejecución y las inaccesibles; la imagen medida estaba en `READWRITE`, pero
#: no se presupone: si melonDS la mapeara como copia en escritura seguiría
#: encontrándose, y el parcheo fallaría de forma visible en vez de en silencio.
_READABLE = {0x02, 0x04, 0x08, 0x20, 0x40, 0x80}


class Gen5RomImageError(RuntimeError):
    """No se pudo localizar o escribir la imagen de la ROM en el emulador."""


class _MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("__alignment1", ctypes.c_uint32),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("__alignment2", ctypes.c_uint32),
    ]


def _kernel32():
    """Instancia propia, con sus tipos fijados una sola vez.

    Mismo criterio que ``b2w2_live._load_kernel32``: varios módulos de RoleRun
    fijan ``argtypes`` sobre ``kernel32``, y compartir la instancia deja que
    uno invalide los tipos de otro a mitad de llamada.
    """
    if os.name != "nt":
        return None
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenProcess.restype = wintypes.HANDLE
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.CloseHandle.restype = wintypes.BOOL
    k.ReadProcessMemory.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    k.ReadProcessMemory.restype = wintypes.BOOL
    k.WriteProcessMemory.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    k.WriteProcessMemory.restype = wintypes.BOOL
    k.VirtualQueryEx.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
    ]
    k.VirtualQueryEx.restype = ctypes.c_size_t
    return k


_K32 = _kernel32()

_PROCESS_VM_READ = 0x0010
_PROCESS_QUERY_INFORMATION = 0x0400
_PROCESS_VM_WRITE = 0x0020
_PROCESS_VM_OPERATION = 0x0008


class _Handle:
    """Abre el proceso y lo cierra pase lo que pase."""

    def __init__(self, process_id: int, *, write: bool) -> None:
        if _K32 is None:
            raise Gen5RomImageError("El parcheo de la ROM de quinta requiere Windows.")
        acceso = _PROCESS_VM_READ | _PROCESS_QUERY_INFORMATION
        if write:
            acceso |= _PROCESS_VM_WRITE | _PROCESS_VM_OPERATION
        self.value = _K32.OpenProcess(acceso, False, int(process_id))
        if not self.value:
            raise Gen5RomImageError("Windows no permitió abrir melonDS.")

    def __enter__(self) -> "_Handle":
        return self

    def __exit__(self, *_exc) -> None:
        _K32.CloseHandle(self.value)


def _read(handle, address: int, size: int) -> bytes:
    buffer = (ctypes.c_ubyte * size)()
    leidos = ctypes.c_size_t()
    ok = _K32.ReadProcessMemory(
        handle, ctypes.c_void_p(int(address)), buffer, size, ctypes.byref(leidos),
    )
    return bytes(buffer[:leidos.value]) if ok else b""


def _anchor_species(
    entries_by_species: Mapping[int, tuple[tuple[int, int, int], ...]],
) -> tuple[int, int, int]:
    """La especie con más entradas: ``(especie, desplazamiento, longitud)``.

    Cuantas más entradas, más largo y específico el patrón de bytes. La tabla
    de una especie es contigua, así que su primer desplazamiento y el número
    de entradas bastan para reconstruir el tramo.
    """
    mejor = max(
        (item for item in entries_by_species.items() if item[1]),
        key=lambda item: len(item[1]),
        default=None,
    )
    if mejor is None:
        raise Gen5RomImageError("La tabla de aprendizajes de quinta está vacía.")
    especie, entradas = mejor
    inicio = int(entradas[0][2])
    return int(especie), inicio, len(entradas) * 4


@dataclass(frozen=True, slots=True)
class Gen5RomImage:
    """La imagen de la ROM ya localizada en la memoria del emulador."""

    process_id: int
    base_address: int
    rom_path: Path

    def read_entry(self, rom_offset: int) -> tuple[int, int]:
        """``(movimiento, nivel)`` tal y como están AHORA en el emulador."""
        with _Handle(self.process_id, write=False) as handle:
            crudo = _read(handle.value, self.base_address + int(rom_offset), 4)
        if len(crudo) != 4:
            raise Gen5RomImageError("No se pudo leer la entrada de aprendizaje.")
        return tuple(struct.unpack("<HH", crudo))  # type: ignore[return-value]

    def apply(
        self,
        patch: Mapping[int, int],
        *,
        expected_levels: Mapping[int, int],
    ) -> int:
        """Escribe solo los dos bytes del movimiento de cada entrada.

        ``expected_levels`` da, por desplazamiento, el nivel que esa entrada
        DEBE tener ahora mismo. Se comprueba justo antes de escribir y, si no
        coincide, esa entrada se salta: el nivel es lo único que nunca cambia
        aunque el movimiento se sustituya, así que un nivel distinto significa
        que ahí ya no está la tabla que creíamos y no se escribe a ciegas.

        Devuelve cuántas entradas se escribieron y verificaron.
        """
        if not patch:
            return 0
        escritas = 0
        with _Handle(self.process_id, write=True) as handle:
            for rom_offset, move_id in patch.items():
                direccion = self.base_address + int(rom_offset)
                actual = _read(handle.value, direccion, 4)
                if len(actual) != 4:
                    continue
                _movimiento_actual, nivel_actual = struct.unpack("<HH", actual)
                esperado = expected_levels.get(int(rom_offset))
                if esperado is None or int(nivel_actual) != int(esperado):
                    continue
                if _movimiento_actual == int(move_id):
                    escritas += 1
                    continue
                payload = struct.pack("<H", int(move_id) & 0xFFFF)
                buffer = ctypes.create_string_buffer(payload)
                escrito = ctypes.c_size_t()
                ok = _K32.WriteProcessMemory(
                    handle.value, ctypes.c_void_p(direccion), buffer, 2,
                    ctypes.byref(escrito),
                )
                if not ok or escrito.value != 2:
                    continue
                # Readback: nunca se da por buena una escritura sin releerla, y
                # el nivel tiene que seguir intacto.
                confirmado = _read(handle.value, direccion, 4)
                if len(confirmado) == 4:
                    movimiento, nivel = struct.unpack("<HH", confirmado)
                    if movimiento == (int(move_id) & 0xFFFF) and nivel == int(esperado):
                        escritas += 1
        return escritas


def locate_rom_image(
    process_id: int,
    rom_path: Path | str,
    entries_by_species: Mapping[int, tuple[tuple[int, int, int], ...]],
    *,
    known_base: int | None = None,
) -> Gen5RomImage | None:
    """Encuentra dónde tiene melonDS cargada la imagen de esta ROM.

    ``known_base`` permite revalidar una base ya encontrada antes sin repetir
    el barrido: si sigue valiendo se devuelve tal cual, y si no, se busca de
    nuevo. Devuelve ``None`` si no se encuentra; solo lanza si encuentra
    varias bases válidas distintas, que es ambigüedad real.
    """
    if _K32 is None:
        return None
    ruta = Path(rom_path)
    especie, inicio_ancla, longitud_ancla = _anchor_species(entries_by_species)
    with ruta.open("rb") as archivo:
        cabecera = archivo.read(0x20)
        archivo.seek(inicio_ancla)
        ancla = archivo.read(longitud_ancla)
    if len(ancla) != longitud_ancla or not cabecera:
        raise Gen5RomImageError("No se pudo leer el ancla desde el archivo .nds.")

    # Segunda comprobación, independiente del ancla: otra especie cualquiera
    # con tabla no vacía, leída en su propia posición.
    testigo = next(
        (
            (entradas[0][2], struct.pack("<HH", entradas[0][0], entradas[0][1]))
            for otra, entradas in sorted(entries_by_species.items())
            if entradas and otra != especie
        ),
        None,
    )

    def base_valida(handle, base: int) -> bool:
        if base < 0:
            return False
        if _read(handle, base, len(cabecera)) != cabecera:
            return False
        if testigo is not None:
            desplazamiento, esperado = testigo
            if _read(handle, base + int(desplazamiento), len(esperado)) != esperado:
                return False
        return True

    tamano_rom = ruta.stat().st_size

    with _Handle(int(process_id), write=False) as handle:
        if known_base is not None and base_valida(handle.value, int(known_base)):
            return Gen5RomImage(int(process_id), int(known_base), ruta)

        # La imagen tiene que CABER: solo se miran asignaciones cuyo tamaño
        # legible total llegue al del archivo .nds. En la medición real eso deja
        # 1 asignación de 343, y es la que contiene la ROM.
        asignaciones: dict[int, list[tuple[int, int]]] = {}
        direccion = 0
        mbi = _MEMORY_BASIC_INFORMATION()
        while direccion < 0x7FFFFFFF0000:
            if not _K32.VirtualQueryEx(
                handle.value, ctypes.c_void_p(direccion), ctypes.byref(mbi),
                ctypes.sizeof(mbi),
            ):
                break
            base = int(mbi.BaseAddress or 0)
            tamano = int(mbi.RegionSize or 0)
            if tamano <= 0:
                break
            asignacion = int(mbi.AllocationBase or 0)
            if (
                int(mbi.State) == _MEM_COMMIT
                and int(mbi.Protect) in _READABLE
                and asignacion
            ):
                asignaciones.setdefault(asignacion, []).append((base, tamano))
            direccion = base + tamano

        candidatas = [
            (asignacion, regiones)
            for asignacion, regiones in asignaciones.items()
            if sum(tamano for _base, tamano in regiones) >= tamano_rom
        ]

        bases: set[int] = set()
        # Camino rápido: la cabecera del .nds cerca del inicio de la asignación.
        for asignacion, regiones in candidatas:
            inicio = min(base for base, _tamano in regiones)
            sonda = _read(handle.value, inicio, HEADER_PROBE_SIZE)
            posicion = sonda.find(cabecera)
            while posicion != -1:
                if base_valida(handle.value, inicio + posicion):
                    bases.add(inicio + posicion)
                posicion = sonda.find(cabecera, posicion + 1)

        # Camino lento, solo si la cabecera no apareció al principio: barrido
        # del ancla por toda la asignación candidata, en trozos.
        if not bases:
            for _asignacion, regiones in candidatas:
                for base, tamano in regiones:
                    leido = 0
                    cola = b""
                    while leido < tamano:
                        trozo = _read(
                            handle.value, base + leido, min(CHUNK_SIZE, tamano - leido),
                        )
                        if not trozo:
                            break
                        combinado = cola + trozo
                        posicion = combinado.find(ancla)
                        while posicion != -1:
                            candidata = base + leido - len(cola) + posicion - inicio_ancla
                            if base_valida(handle.value, candidata):
                                bases.add(candidata)
                            posicion = combinado.find(ancla, posicion + 1)
                        cola = trozo[-(len(ancla) - 1):] if len(ancla) > 1 else b""
                        leido += len(trozo)

    if len(bases) > 1:
        raise Gen5RomImageError(
            "melonDS expone varias imágenes válidas de esta ROM; no se elige "
            "ninguna por cercanía. No se escribió ningún byte."
        )
    if not bases:
        return None
    return Gen5RomImage(int(process_id), bases.pop(), ruta)
