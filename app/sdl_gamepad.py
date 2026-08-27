from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from pathlib import Path


SDL_INIT_GAMECONTROLLER = 0x00002000

BUTTON_NAMES = (
    "a", "b", "x", "y", "back", "guide", "start", "left stick",
    "right stick", "left shoulder", "right shoulder", "dpad up",
    "dpad down", "dpad left", "dpad right",
)


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_ulong), ("cntUsage", ctypes.c_ulong),
        ("th32ProcessID", ctypes.c_ulong), ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", ctypes.c_ulong), ("cntThreads", ctypes.c_ulong),
        ("th32ParentProcessID", ctypes.c_ulong), ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_ulong), ("szExeFile", ctypes.c_wchar * 260),
    ]


def find_ryujinx_process() -> tuple[int, Path] | None:
    """Localiza PID y ejecutable sin añadir una dependencia de psutil."""
    if os.name != "nt":
        return None
    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot in (0, -1):
        return None
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        found = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            if entry.szExeFile.casefold() == "ryujinx.exe":
                handle = kernel32.OpenProcess(0x1000, False, entry.th32ProcessID)
                if handle:
                    try:
                        size = ctypes.c_ulong(32768)
                        buffer = ctypes.create_unicode_buffer(size.value)
                        if kernel32.QueryFullProcessImageNameW(
                            handle, 0, buffer, ctypes.byref(size)
                        ):
                            return int(entry.th32ProcessID), Path(buffer.value)
                    finally:
                        kernel32.CloseHandle(handle)
            found = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return None


@dataclass(frozen=True, slots=True)
class GamepadSample:
    connected: bool
    name: str = ""
    pressed: frozenset[str] = frozenset()


class SDLGamepad:
    """Lector SDL2 pequeño y determinista para el mando activo de Ryujinx.

    Carga la misma SDL2.dll que usa el emulador. Esta clase solo lee estado;
    la exclusividad pertenece a ``RyujinxInputGate``.
    """

    def __init__(self, dll_path: Path) -> None:
        self.dll_path = Path(dll_path)
        self._dll = ctypes.CDLL(str(self.dll_path))
        self._controller = None
        self._configure_api()
        if self._dll.SDL_InitSubSystem(SDL_INIT_GAMECONTROLLER) != 0:
            raise OSError(self.error())

    def _configure_api(self) -> None:
        dll = self._dll
        dll.SDL_InitSubSystem.argtypes = [ctypes.c_uint32]
        dll.SDL_InitSubSystem.restype = ctypes.c_int
        dll.SDL_NumJoysticks.restype = ctypes.c_int
        dll.SDL_IsGameController.argtypes = [ctypes.c_int]
        dll.SDL_IsGameController.restype = ctypes.c_int
        dll.SDL_GameControllerOpen.argtypes = [ctypes.c_int]
        dll.SDL_GameControllerOpen.restype = ctypes.c_void_p
        dll.SDL_GameControllerClose.argtypes = [ctypes.c_void_p]
        dll.SDL_GameControllerName.argtypes = [ctypes.c_void_p]
        dll.SDL_GameControllerName.restype = ctypes.c_char_p
        dll.SDL_GameControllerGetAttached.argtypes = [ctypes.c_void_p]
        dll.SDL_GameControllerGetAttached.restype = ctypes.c_int
        dll.SDL_GameControllerGetButton.argtypes = [ctypes.c_void_p, ctypes.c_int]
        dll.SDL_GameControllerGetButton.restype = ctypes.c_uint8
        dll.SDL_GameControllerUpdate.restype = None
        dll.SDL_GetError.restype = ctypes.c_char_p

    def error(self) -> str:
        raw = self._dll.SDL_GetError()
        return raw.decode("utf-8", errors="replace") if raw else "Error SDL2 desconocido"

    def _ensure_open(self) -> bool:
        if self._controller and self._dll.SDL_GameControllerGetAttached(self._controller):
            return True
        self.close_controller()
        for index in range(max(0, self._dll.SDL_NumJoysticks())):
            if self._dll.SDL_IsGameController(index):
                controller = self._dll.SDL_GameControllerOpen(index)
                if controller:
                    self._controller = controller
                    return True
        return False

    def sample(self) -> GamepadSample:
        self._dll.SDL_GameControllerUpdate()
        if not self._ensure_open():
            return GamepadSample(False)
        raw_name = self._dll.SDL_GameControllerName(self._controller)
        name = raw_name.decode("utf-8", errors="replace") if raw_name else "Mando SDL2"
        pressed = frozenset(
            name for index, name in enumerate(BUTTON_NAMES)
            if self._dll.SDL_GameControllerGetButton(self._controller, index)
        )
        return GamepadSample(True, name, pressed)

    def close_controller(self) -> None:
        if self._controller:
            self._dll.SDL_GameControllerClose(self._controller)
            self._controller = None

    def close(self) -> None:
        self.close_controller()

    @classmethod
    def from_ryujinx_process(cls) -> "SDLGamepad | None":
        if os.name != "nt":
            return None
        try:
            process = find_ryujinx_process()
            if process is not None:
                _pid, executable = process
                dll = executable.with_name("SDL2.dll")
                if dll.is_file():
                    return cls(dll)
        except Exception:
            return None
        return None


class RyujinxInputGate:
    """Suspensión reversible del Ryujinx exacto mientras RoleRun usa el mando."""

    def __init__(self) -> None:
        self._process = None
        self._depth = 0

    @property
    def active(self) -> bool:
        return self._depth > 0

    def acquire(self) -> bool:
        if os.name != "nt":
            return False
        if self._depth:
            self._depth += 1
            return True
        try:
            process = find_ryujinx_process()
            if process is None:
                return False
            pid, _executable = process
            handle = ctypes.windll.kernel32.OpenProcess(0x0800, False, pid)
            if not handle:
                return False
            status = int(ctypes.windll.ntdll.NtSuspendProcess(handle))
            if status != 0:
                ctypes.windll.kernel32.CloseHandle(handle)
                return False
            self._process = handle
            self._depth = 1
            return True
        except Exception:
            self._process = None
            self._depth = 0
            return False

    def release(self, *, all_levels: bool = False) -> bool:
        if not self._depth:
            return True
        if not all_levels and self._depth > 1:
            self._depth -= 1
            return True
        handle, self._process = self._process, None
        self._depth = 0
        try:
            return int(ctypes.windll.ntdll.NtResumeProcess(handle)) == 0
        except Exception:
            return False
        finally:
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
