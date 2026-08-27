from __future__ import annotations

"""Transporte Win32 de escritura cerrado para la vista HostMapped de Ryujinx.

La calibración guest→host y la identidad del juego siguen perteneciendo al
cliente de solo lectura. Esta clase no busca procesos, direcciones ni patrones:
solo abre el PID ya demostrado, exige que el rango concreto sea PAGE_READWRITE
y permite a un writer transaccional hacer prelectura, write, readback y rollback.
"""

import os


class RyujinxHostWriteError(RuntimeError):
    pass


_PROCESS_QUERY_INFORMATION = 0x0400
_PROCESS_VM_OPERATION = 0x0008
_PROCESS_VM_READ = 0x0010
_PROCESS_VM_WRITE = 0x0020
_MEM_COMMIT = 0x1000
_MEM_MAPPED = 0x40000
_PAGE_NOACCESS = 0x01
_PAGE_GUARD = 0x100
_PAGE_READWRITE = 0x04


class RyujinxHostWriteTransport:
    """Primitivas mínimas; todas las decisiones semánticas quedan fuera."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise RyujinxHostWriteError(
                "La escritura HostMapped de Ryujinx solo está disponible en Windows."
            )
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        self.wintypes = wintypes
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class MEMORY_BASIC_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BaseAddress", ctypes.c_void_p),
                ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wintypes.DWORD),
                ("RegionSize", ctypes.c_size_t),
                ("State", wintypes.DWORD),
                ("Protect", wintypes.DWORD),
                ("Type", wintypes.DWORD),
            ]

        self.MEMORY_BASIC_INFORMATION = MEMORY_BASIC_INFORMATION
        k32 = self.kernel32
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.CloseHandle.restype = wintypes.BOOL
        k32.VirtualQueryEx.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p,
            ctypes.POINTER(MEMORY_BASIC_INFORMATION), ctypes.c_size_t,
        ]
        k32.VirtualQueryEx.restype = ctypes.c_size_t
        k32.ReadProcessMemory.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        k32.ReadProcessMemory.restype = wintypes.BOOL
        k32.WriteProcessMemory.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        k32.WriteProcessMemory.restype = wintypes.BOOL

    def _error(self, message: str) -> RyujinxHostWriteError:
        return RyujinxHostWriteError(
            f"{message} (Win32 error {int(self.ctypes.get_last_error())})."
        )

    def open(self, pid: int):
        rights = (
            _PROCESS_QUERY_INFORMATION | _PROCESS_VM_OPERATION
            | _PROCESS_VM_READ | _PROCESS_VM_WRITE
        )
        handle = self.kernel32.OpenProcess(rights, False, int(pid))
        if not handle:
            raise self._error(f"No se pudo abrir Ryujinx PID {int(pid)} para escritura")
        return handle

    def close(self, handle) -> None:
        if handle:
            self.kernel32.CloseHandle(handle)

    def read(self, handle, address: int, size: int) -> bytes:
        if int(size) <= 0:
            return b""
        c = self.ctypes
        buffer = (c.c_ubyte * int(size))()
        read = c.c_size_t(0)
        ok = bool(self.kernel32.ReadProcessMemory(
            handle, c.c_void_p(int(address)), buffer, int(size), c.byref(read),
        ))
        if not ok or int(read.value) != int(size):
            raise self._error(f"ReadProcessMemory falló en 0x{int(address):X}")
        return bytes(buffer)

    def write(self, handle, address: int, data: bytes) -> None:
        raw = bytes(data)
        if not raw:
            return
        c = self.ctypes
        buffer = (c.c_ubyte * len(raw)).from_buffer_copy(raw)
        written = c.c_size_t(0)
        ok = bool(self.kernel32.WriteProcessMemory(
            handle, c.c_void_p(int(address)), buffer, len(raw), c.byref(written),
        ))
        if not ok or int(written.value) != len(raw):
            raise self._error(f"WriteProcessMemory falló en 0x{int(address):X}")

    def assert_writable(self, handle, address: int, size: int) -> None:
        if int(size) <= 0:
            raise RyujinxHostWriteError("El rango HostMapped a escribir está vacío.")
        c = self.ctypes
        mbi = self.MEMORY_BASIC_INFORMATION()
        queried = int(self.kernel32.VirtualQueryEx(
            handle, c.c_void_p(int(address)), c.byref(mbi), c.sizeof(mbi),
        ))
        if queried == 0:
            raise self._error(f"VirtualQueryEx falló en 0x{int(address):X}")
        base = int(mbi.BaseAddress or 0)
        region_size = int(mbi.RegionSize or 0)
        protection = int(mbi.Protect)
        writable = (
            int(mbi.State) == _MEM_COMMIT
            and int(mbi.Type) == _MEM_MAPPED
            and not protection & (_PAGE_GUARD | _PAGE_NOACCESS)
            and (protection & 0xFF) == _PAGE_READWRITE
        )
        if (
            not writable
            or int(address) < base
            or int(address) + int(size) > base + region_size
        ):
            raise RyujinxHostWriteError(
                f"El rango 0x{int(address):X}+0x{int(size):X} no pertenece "
                "completo a una vista HostMapped escribible."
            )
