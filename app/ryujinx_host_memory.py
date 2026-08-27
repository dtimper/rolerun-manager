from __future__ import annotations

import json
import os
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol


RYUJINX_HOST_ADDRESS_SPACE_SIZE = 1 << 39
RYUJINX_HOST_DEFAULT_SCAN_BUDGET = 3 * 1024 * 1024 * 1024


class RyujinxHostMemoryError(RuntimeError):
    """Error presentable del transporte HostMapped de solo lectura."""


@dataclass(frozen=True, slots=True)
class RyujinxHostSettings:
    gdb_enabled: bool | None
    memory_manager_mode: str | None
    path: Path | None


@dataclass(frozen=True, slots=True)
class RyujinxHostProfile:
    """Huella demostrada para una revisión concreta de un juego."""

    key: str
    game_name: str
    revision: str
    title_id: int
    guest_main: int
    main_witness: bytes


@dataclass(frozen=True, slots=True)
class RyujinxHostProcess:
    pid: int
    exe_name: str
    window_title: str = ""
    title_id: int | None = None
    revision: str | None = None


@dataclass(frozen=True, slots=True)
class RyujinxHostRegion:
    base: int
    size: int
    state: int
    protect: int
    kind: int


@dataclass(frozen=True, slots=True)
class RyujinxHostSession:
    process: RyujinxHostProcess
    profile: RyujinxHostProfile
    host_main: int
    guest_to_host_delta: int
    paired_regions: int
    paired_region_bytes: int


class RyujinxHostBackend(Protocol):
    def list_processes(self) -> list[RyujinxHostProcess]: ...
    def open_read_only(self, pid: int): ...
    def close(self, handle) -> None: ...
    def regions(self, handle) -> Iterable[RyujinxHostRegion]: ...
    def read(self, handle, address: int, size: int) -> bytes: ...


def discover_ryujinx_host_settings() -> RyujinxHostSettings:
    appdata = os.environ.get("APPDATA")
    candidates = (Path(appdata) / "Ryujinx" / "Config.json",) if appdata else ()
    for path in candidates:
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        enabled = raw.get("enable_gdb_stub")
        gdb_enabled = bool(enabled) if isinstance(enabled, bool) else None
        mode = str(raw.get("memory_manager_mode") or "") or None
        return RyujinxHostSettings(gdb_enabled, mode, path)
    return RyujinxHostSettings(None, None, None)


_WINDOW_TITLE_ID_RE = re.compile(r"\(([0-9A-Fa-f]{16})\)")
_WINDOW_REVISION_RE = re.compile(r"(?:^|\s)v(\d+(?:\.\d+)+)(?=\s|\()")


def parse_ryujinx_window_identity(title: str) -> tuple[int, str] | None:
    """Extrae la identidad que Ryujinx 1.3.3 publica en su título activo.

    `TitleHelper.ActiveApplicationTitle` genera tanto la variante de una línea
    como la de barra personalizada, con `v<DisplayVersion>` y el Program ID de
    16 dígitos. Si falta cualquiera de los dos, la identidad no es suficiente.
    """

    normalized = str(title).replace("\r", " ").replace("\n", " ")
    title_id = _WINDOW_TITLE_ID_RE.search(normalized)
    revision = _WINDOW_REVISION_RE.search(normalized)
    if title_id is None or revision is None:
        return None
    return int(title_id.group(1), 16), revision.group(1)


def paired_hostmapped_regions(
    regions: Iterable[RyujinxHostRegion],
    *,
    address_space_size: int = RYUJINX_HOST_ADDRESS_SPACE_SIZE,
) -> tuple[RyujinxHostRegion, ...]:
    """Selecciona solo las vistas Base/Mirror demostradas por Ryujinx.

    `HostMappedUnsafe` reserva dos vistas MEM_MAPPED del mismo bloque separadas
    por el tamaño exacto del espacio invitado (39 bits). Exigir el par completo
    evita escanear heaps, JIT, módulos o regiones privadas del proceso.
    """

    values = tuple(regions)
    by_base = {int(region.base): region for region in values}
    result: list[RyujinxHostRegion] = []
    for region in values:
        mirror = by_base.get(int(region.base) + int(address_space_size))
        if mirror is None:
            continue
        if (
            int(region.state) == _MEM_COMMIT
            and int(region.kind) == _MEM_MAPPED
            and _is_readable(int(region.protect))
            and int(mirror.state) == int(region.state)
            and int(mirror.kind) == int(region.kind)
            and int(mirror.size) == int(region.size)
        ):
            result.append(region)
    return tuple(result)


class RyujinxHostMappedClient:
    """Traduce direcciones guest a la vista Windows sin habilitar GDB.

    La clase no expone ninguna operación de escritura. La sesión se acepta solo
    si la configuración es HostMappedUnsafe, GDB está apagado, existe un único
    proceso Ryujinx y la huella completa de la revisión aparece una sola vez en
    las vistas Base/Mirror justificadas.
    """

    def __init__(
        self,
        profile: RyujinxHostProfile,
        *,
        backend: RyujinxHostBackend | None = None,
        settings: RyujinxHostSettings | None = None,
        scan_budget: int = RYUJINX_HOST_DEFAULT_SCAN_BUDGET,
        chunk_size: int = 8 * 1024 * 1024,
    ) -> None:
        self.profile = profile
        self.backend = backend if backend is not None else _WindowsRyujinxReadOnlyBackend()
        self.settings = settings
        self.scan_budget = max(len(profile.main_witness), int(scan_budget))
        self.chunk_size = max(4096, int(chunk_size))
        self._handle = None
        self._session: RyujinxHostSession | None = None

    def __enter__(self) -> "RyujinxHostMappedClient":
        self.connect()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    @property
    def session(self) -> RyujinxHostSession:
        if self._session is None:
            raise RyujinxHostMemoryError("La sesión HostMapped de Ryujinx no está conectada.")
        return self._session

    def connect(self) -> None:
        if self._handle is not None:
            return
        settings = self.settings if self.settings is not None else discover_ryujinx_host_settings()
        if settings.memory_manager_mode != "HostMappedUnsafe":
            raise RyujinxHostMemoryError(
                "Ryujinx debe usar HostMappedUnsafe para habilitar la lectura directa demostrada."
            )
        if settings.gdb_enabled is not False:
            raise RyujinxHostMemoryError(
                "El GDB Stub debe estar desactivado: su penalización de rendimiento está demostrada."
            )
        processes = self.backend.list_processes()
        if len(processes) != 1:
            raise RyujinxHostMemoryError(
                f"Se esperaba un único proceso Ryujinx y se encontraron {len(processes)}."
            )
        process = processes[0]
        if process.title_id != int(self.profile.title_id) or process.revision != self.profile.revision:
            observed_id = "desconocido" if process.title_id is None else f"{int(process.title_id):016X}"
            observed_revision = process.revision or "desconocida"
            raise RyujinxHostMemoryError(
                f"Ryujinx ejecuta Title ID {observed_id}, revisión {observed_revision}; "
                f"el perfil exige {int(self.profile.title_id):016X}, revisión {self.profile.revision}."
            )
        handle = self.backend.open_read_only(process.pid)
        try:
            regions = paired_hostmapped_regions(self.backend.regions(handle))
            total = sum(int(region.size) for region in regions)
            if not regions:
                raise RyujinxHostMemoryError(
                    "Ryujinx no expone las vistas HostMapped Base/Mirror esperadas."
                )
            if total > self.scan_budget:
                raise RyujinxHostMemoryError(
                    f"Las vistas HostMapped ({total} bytes) superan el presupuesto de diagnóstico "
                    f"({self.scan_budget} bytes)."
                )
            hits: list[int] = []
            for region in regions:
                for hit in self._scan_region(handle, region, self.profile.main_witness):
                    hits.append(hit)
                    if len(hits) > 1:
                        break
                if len(hits) > 1:
                    break
            if len(hits) != 1:
                raise RyujinxHostMemoryError(
                    f"La huella {self.profile.key} produjo {len(hits)} candidatos; se rechaza la sesión."
                )
            host_main = hits[0]
            delta = int(host_main) - int(self.profile.guest_main)
            if delta <= 0:
                raise RyujinxHostMemoryError("La traducción guest→host obtenida no es válida.")
            if self.backend.read(handle, host_main, len(self.profile.main_witness)) != self.profile.main_witness:
                raise RyujinxHostMemoryError("La huella principal cambió durante la calibración.")
        except Exception:
            self.backend.close(handle)
            raise
        self._handle = handle
        self._session = RyujinxHostSession(
            process=process,
            profile=self.profile,
            host_main=host_main,
            guest_to_host_delta=delta,
            paired_regions=len(regions),
            paired_region_bytes=total,
        )

    def close(self) -> None:
        handle = self._handle
        self._handle = None
        self._session = None
        if handle is not None:
            self.backend.close(handle)

    def _scan_region(
        self,
        handle,
        region: RyujinxHostRegion,
        pattern: bytes,
    ) -> Iterable[int]:
        overlap = max(0, len(pattern) - 1)
        offset = 0
        tail = b""
        while offset < int(region.size):
            amount = min(self.chunk_size, int(region.size) - offset)
            try:
                block = self.backend.read(handle, int(region.base) + offset, amount)
            except RyujinxHostMemoryError:
                return
            haystack = tail + block
            search_from = 0
            while True:
                position = haystack.find(pattern, search_from)
                if position < 0:
                    break
                absolute = int(region.base) + offset - len(tail) + position
                if int(region.base) <= absolute and absolute + len(pattern) <= int(region.base) + int(region.size):
                    yield absolute
                search_from = position + 1
            tail = haystack[-overlap:] if overlap else b""
            offset += amount

    def read_memory(self, guest_address: int, size: int) -> bytes:
        if size < 0:
            raise ValueError("size no puede ser negativo")
        if size == 0:
            return b""
        if not 0 <= int(guest_address) < RYUJINX_HOST_ADDRESS_SPACE_SIZE:
            raise RyujinxHostMemoryError(f"La dirección guest 0x{int(guest_address):X} queda fuera de 39 bits.")
        if int(guest_address) + int(size) > RYUJINX_HOST_ADDRESS_SPACE_SIZE:
            raise RyujinxHostMemoryError("La lectura guest cruza el límite del espacio de direcciones.")
        if self._handle is None:
            self.connect()
        assert self._handle is not None
        host_address = int(guest_address) + int(self.session.guest_to_host_delta)
        return self.backend.read(self._handle, host_address, int(size))

    def read_u64(self, guest_address: int) -> int:
        return int(struct.unpack("<Q", self.read_memory(int(guest_address), 8))[0])

    def resolve_main_pointer(
        self,
        jumps: Iterable[int],
        *,
        minimum_address: int = 0x1000,
    ) -> int:
        chain = tuple(int(value) for value in jumps)
        if len(chain) < 2:
            raise ValueError("Una cadena de punteros necesita al menos dos saltos.")
        address = int(self.profile.guest_main) + chain[0]
        for jump in chain[1:]:
            pointer = self.read_u64(address)
            if not int(minimum_address) <= pointer < RYUJINX_HOST_ADDRESS_SPACE_SIZE:
                raise RyujinxHostMemoryError(
                    f"La cadena produjo el puntero inválido 0x{pointer:X} en 0x{address:X}."
                )
            address = pointer + jump
        return address


# Win32 constants. The production handle deliberately excludes VM_WRITE and
# VM_OPERATION. No write symbol is bound anywhere in this module.
_TH32CS_SNAPPROCESS = 0x00000002
_PROCESS_QUERY_INFORMATION = 0x0400
_PROCESS_VM_READ = 0x0010
_MEM_COMMIT = 0x1000
_MEM_MAPPED = 0x40000
_PAGE_NOACCESS = 0x01
_PAGE_GUARD = 0x100
_INVALID_HANDLE_VALUE = -1


def _is_readable(protect: int) -> bool:
    return not (int(protect) & (_PAGE_NOACCESS | _PAGE_GUARD))


class _WindowsRyujinxReadOnlyBackend:
    def __init__(self) -> None:
        if os.name != "nt":
            raise RyujinxHostMemoryError("El transporte HostMapped de Ryujinx requiere Windows.")
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        self.wintypes = wintypes
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
            ]

        class MEMORY_BASIC_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wintypes.DWORD), ("RegionSize", ctypes.c_size_t),
                ("State", wintypes.DWORD), ("Protect", wintypes.DWORD), ("Type", wintypes.DWORD),
            ]

        self.PROCESSENTRY32W = PROCESSENTRY32W
        self.MEMORY_BASIC_INFORMATION = MEMORY_BASIC_INFORMATION
        self.WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        k32 = self.kernel32
        k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        k32.Process32FirstW.restype = wintypes.BOOL
        k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        k32.Process32NextW.restype = wintypes.BOOL
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.CloseHandle.restype = wintypes.BOOL
        k32.VirtualQueryEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(MEMORY_BASIC_INFORMATION), ctypes.c_size_t]
        k32.VirtualQueryEx.restype = ctypes.c_size_t
        k32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        k32.ReadProcessMemory.restype = wintypes.BOOL
        user32 = self.user32
        user32.EnumWindows.argtypes = [self.WNDENUMPROC, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int

    def _error(self, message: str) -> RyujinxHostMemoryError:
        return RyujinxHostMemoryError(f"{message} (Win32 error {int(self.ctypes.get_last_error())}).")

    def list_processes(self) -> list[RyujinxHostProcess]:
        c = self.ctypes
        snapshot = self.kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
        if int(c.cast(snapshot, c.c_void_p).value or 0) == c.c_void_p(_INVALID_HANDLE_VALUE).value:
            raise self._error("No se pudieron enumerar los procesos")
        process_rows: list[tuple[int, str]] = []
        try:
            entry = self.PROCESSENTRY32W()
            entry.dwSize = c.sizeof(entry)
            ok = bool(self.kernel32.Process32FirstW(snapshot, c.byref(entry)))
            while ok:
                name = str(entry.szExeFile)
                if name.casefold() == "ryujinx.exe":
                    process_rows.append((int(entry.th32ProcessID), name))
                ok = bool(self.kernel32.Process32NextW(snapshot, c.byref(entry)))
        finally:
            self.kernel32.CloseHandle(snapshot)
        titles = self._window_titles_by_pid()
        result: list[RyujinxHostProcess] = []
        for pid, name in process_rows:
            candidates = [
                (title, parse_ryujinx_window_identity(title))
                for title in titles.get(pid, ())
            ]
            identified = [(title, identity) for title, identity in candidates if identity is not None]
            if len(identified) == 1:
                title, identity = identified[0]
                assert identity is not None
                result.append(RyujinxHostProcess(pid, name, title, identity[0], identity[1]))
            else:
                result.append(RyujinxHostProcess(pid, name))
        return result

    def _window_titles_by_pid(self) -> dict[int, tuple[str, ...]]:
        c = self.ctypes
        values: dict[int, list[str]] = {}
        def visit(window, _parameter) -> bool:
            length = int(self.user32.GetWindowTextLengthW(window))
            if length <= 0:
                return True
            pid = self.wintypes.DWORD(0)
            self.user32.GetWindowThreadProcessId(window, c.byref(pid))
            buffer = c.create_unicode_buffer(length + 1)
            if self.user32.GetWindowTextW(window, buffer, length + 1) > 0:
                values.setdefault(int(pid.value), []).append(str(buffer.value))
            return True

        callback = self.WNDENUMPROC(visit)
        if not self.user32.EnumWindows(callback, 0):
            raise self._error("No se pudieron enumerar las ventanas de Ryujinx")
        return {pid: tuple(items) for pid, items in values.items()}

    def open_read_only(self, pid: int):
        rights = _PROCESS_QUERY_INFORMATION | _PROCESS_VM_READ
        handle = self.kernel32.OpenProcess(rights, False, int(pid))
        if not handle:
            raise self._error(f"No se pudo abrir Ryujinx PID {int(pid)} en modo de solo lectura")
        return handle

    def close(self, handle) -> None:
        if handle:
            self.kernel32.CloseHandle(handle)

    def regions(self, handle) -> Iterable[RyujinxHostRegion]:
        c = self.ctypes
        address = 0x10000
        maximum = 0x00007FFFFFFFFFFF if c.sizeof(c.c_void_p) == 8 else 0x7FFF0000
        while address < maximum:
            info = self.MEMORY_BASIC_INFORMATION()
            queried = int(self.kernel32.VirtualQueryEx(handle, c.c_void_p(address), c.byref(info), c.sizeof(info)))
            if queried == 0:
                break
            base = int(c.cast(info.BaseAddress, c.c_void_p).value or 0)
            size = int(info.RegionSize or 0)
            if size <= 0:
                break
            yield RyujinxHostRegion(base, size, int(info.State), int(info.Protect), int(info.Type))
            next_address = base + size
            if next_address <= address:
                break
            address = next_address

    def read(self, handle, address: int, size: int) -> bytes:
        if size <= 0:
            return b""
        c = self.ctypes
        buffer = (c.c_ubyte * int(size))()
        received = c.c_size_t(0)
        ok = bool(self.kernel32.ReadProcessMemory(
            handle, c.c_void_p(int(address)), buffer, int(size), c.byref(received),
        ))
        if not ok or int(received.value) != int(size):
            raise self._error(f"ReadProcessMemory falló en 0x{int(address):X}")
        return bytes(buffer)
