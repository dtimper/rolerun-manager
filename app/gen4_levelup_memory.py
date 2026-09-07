"""Localiza y parchea la imagen de la ROM de HeartGold dentro de melonDS.

Mismo mecanismo que ``gen5_levelup_memory``, con una diferencia real de
formato: en quinta cada entrada son dos u16 separados (movimiento, nivel) y
basta con escribir los dos bytes del movimiento. En cuarta los dos datos
comparten el MISMO u16 (``valor = nivel<<9 | movimiento``, ver
``gen4_levelup_moves.py``), así que escribir un movimiento nuevo exige volver
a empaquetar el nivel que ya tenía esa entrada -si no, la escritura también
le cambiaría el nivel al que se aprende-.

Localizar la imagen usa la MISMA técnica ya validada en quinta: HeartGold
corre sobre el mismo melonDS, que mantiene la imagen entera de la ROM en su
propia memoria, en una región de escritura. El archivo .nds del usuario no se
toca nunca: es la fuente de la verdad vainilla y se abre siempre en solo
lectura.
"""

from __future__ import annotations

import ctypes
import os
import struct
from collections.abc import Mapping
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from .gen4_levelup_moves import ENTRY_SIZE, pack_entry, unpack_entry

#: Cuánto se mira al principio de una asignación candidata buscando la
#: cabecera del .nds. Ver ``gen5_levelup_memory.HEADER_PROBE_SIZE``.
HEADER_PROBE_SIZE = 1 * 1024 * 1024

#: Trozo de lectura para el barrido completo cuando la cabecera no aparece al
#: principio de la asignación.
CHUNK_SIZE = 16 * 1024 * 1024

#: Protecciones de página que siguen siendo legibles vía ``ReadProcessMemory``.
_READABLE = {0x02, 0x04, 0x08, 0x20, 0x40, 0x80}


class Gen4RomImageError(RuntimeError):
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

    Mismo criterio que ``gen5_levelup_memory._kernel32``: compartir la
    instancia de otro módulo deja que uno invalide los tipos del otro a mitad
    de llamada.
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
            raise Gen4RomImageError("El parcheo de la ROM de cuarta requiere Windows.")
        acceso = _PROCESS_VM_READ | _PROCESS_QUERY_INFORMATION
        if write:
            acceso |= _PROCESS_VM_WRITE | _PROCESS_VM_OPERATION
        self.value = _K32.OpenProcess(acceso, False, int(process_id))
        if not self.value:
            raise Gen4RomImageError("Windows no permitió abrir melonDS.")

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
    """La especie con más entradas: ``(especie, desplazamiento, longitud)``."""
    mejor = max(
        (item for item in entries_by_species.items() if item[1]),
        key=lambda item: len(item[1]),
        default=None,
    )
    if mejor is None:
        raise Gen4RomImageError("La tabla de aprendizajes de cuarta está vacía.")
    especie, entradas = mejor
    inicio = int(entradas[0][2])
    return int(especie), inicio, len(entradas) * ENTRY_SIZE


@dataclass(frozen=True, slots=True)
class Gen4RomImage:
    """La imagen de la ROM ya localizada en la memoria del emulador."""

    process_id: int
    base_address: int
    rom_path: Path

    def read_entry(self, rom_offset: int) -> tuple[int, int]:
        """``(movimiento, nivel)`` tal y como están AHORA en el emulador."""
        with _Handle(self.process_id, write=False) as handle:
            crudo = _read(handle.value, self.base_address + int(rom_offset), ENTRY_SIZE)
        if len(crudo) != ENTRY_SIZE:
            raise Gen4RomImageError("No se pudo leer la entrada de aprendizaje.")
        return unpack_entry(struct.unpack("<H", crudo)[0])

    def apply(
        self,
        patch: Mapping[int, int],
        *,
        expected_levels: Mapping[int, int],
    ) -> int:
        """Escribe cada entrada re-empaquetada con SU nivel, no el movimiento suelto.

        ``expected_levels`` da, por desplazamiento, el nivel que esa entrada
        DEBE tener ahora mismo -la misma tabla que ya usa ``compute_role_patch``
        para calcular el parche-. Se comprueba justo antes de escribir y, si no
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
                actual = _read(handle.value, direccion, ENTRY_SIZE)
                if len(actual) != ENTRY_SIZE:
                    continue
                _movimiento_actual, nivel_actual = unpack_entry(
                    struct.unpack("<H", actual)[0],
                )
                esperado = expected_levels.get(int(rom_offset))
                if esperado is None or int(nivel_actual) != int(esperado):
                    continue
                nuevo_valor = pack_entry(int(move_id), int(esperado))
                if _movimiento_actual == int(move_id) & 0x1FF:
                    escritas += 1
                    continue
                payload = struct.pack("<H", nuevo_valor)
                buffer = ctypes.create_string_buffer(payload)
                escrito = ctypes.c_size_t()
                ok = _K32.WriteProcessMemory(
                    handle.value, ctypes.c_void_p(direccion), buffer, ENTRY_SIZE,
                    ctypes.byref(escrito),
                )
                if not ok or escrito.value != ENTRY_SIZE:
                    continue
                # Readback: nunca se da por buena una escritura sin releerla, y
                # el nivel tiene que seguir intacto.
                confirmado = _read(handle.value, direccion, ENTRY_SIZE)
                if len(confirmado) == ENTRY_SIZE:
                    movimiento, nivel = unpack_entry(struct.unpack("<H", confirmado)[0])
                    if movimiento == (int(move_id) & 0x1FF) and nivel == int(esperado):
                        escritas += 1
        return escritas


def locate_rom_image(
    process_id: int,
    rom_path: Path | str,
    entries_by_species: Mapping[int, tuple[tuple[int, int, int], ...]],
    *,
    known_base: int | None = None,
) -> Gen4RomImage | None:
    """Encuentra dónde tiene melonDS cargada la imagen de esta ROM.

    Mismo algoritmo que ``gen5_levelup_memory.locate_rom_image``: ``known_base``
    permite revalidar una base ya encontrada sin repetir el barrido. Devuelve
    ``None`` si no se encuentra; solo lanza si encuentra varias bases
    distintas y válidas, que es ambigüedad real.
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
        raise Gen4RomImageError("No se pudo leer el ancla desde el archivo .nds.")

    # Segunda comprobación, independiente del ancla: otra especie cualquiera
    # con tabla no vacía, leída en su propia posición.
    testigo = next(
        (
            (entradas[0][2], struct.pack("<H", (entradas[0][1] << 9) | entradas[0][0]))
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
            return Gen4RomImage(int(process_id), int(known_base), ruta)

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
                int(mbi.State) == 0x1000
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
        for asignacion, regiones in candidatas:
            inicio = min(base for base, _tamano in regiones)
            sonda = _read(handle.value, inicio, HEADER_PROBE_SIZE)
            posicion = sonda.find(cabecera)
            while posicion != -1:
                if base_valida(handle.value, inicio + posicion):
                    bases.add(inicio + posicion)
                posicion = sonda.find(cabecera, posicion + 1)

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
        raise Gen4RomImageError(
            "melonDS expone varias imágenes válidas de esta ROM; no se elige "
            "ninguna por cercanía. No se escribió ningún byte."
        )
    if not bases:
        return None
    return Gen4RomImage(int(process_id), bases.pop(), ruta)
