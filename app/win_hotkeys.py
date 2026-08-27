from __future__ import annotations

import ctypes
import sys
import threading
from ctypes import wintypes
from typing import Callable


IS_WINDOWS = sys.platform.startswith("win")

# Win32 virtual-key codes supported by the RoleRun shortcut editor.
_KEY_TO_VK: dict[str, int] = {
    **{f"num {i}": 0x60 + i for i in range(10)},
    **{str(i): 0x30 + i for i in range(10)},
    **{chr(code).lower(): code for code in range(ord("A"), ord("Z") + 1)},
    **{f"f{i}": 0x6F + i for i in range(1, 13)},
    "home": 0x24,
    "end": 0x23,
    "insert": 0x2D,
    "delete": 0x2E,
    "page up": 0x21,
    "page down": 0x22,
    "space": 0x20,
    "enter": 0x0D,
    "add": 0x6B,
    "subtract": 0x6D,
    "multiply": 0x6A,
    "divide": 0x6F,
    "decimal": 0x6E,
}
_VK_TO_KEY = {value: key for key, value in _KEY_TO_VK.items()}

# Modifier virtual-key codes are intentionally excluded from capture as standalone shortcuts.
_CAPTURE_VKS = tuple(sorted(_VK_TO_KEY))

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_TIMER = 0x0113
WM_QUIT = 0x0012


class WindowsHotkeyManager:
    """Registers reliable system-wide shortcuts through Win32.

    Unlike the third-party ``keyboard`` package, RegisterHotKey distinguishes
    numeric-keypad virtual keys and does not require an elevated process.
    """

    def __init__(
        self,
        callback: Callable[[str], None],
        active_predicate: Callable[[], bool] | None = None,
    ) -> None:
        self.callback = callback
        self.active_predicate = active_predicate or (lambda: True)
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready = threading.Event()
        self._hotkeys: dict[str, str] = {}
        self.errors: list[str] = []

    @staticmethod
    def available() -> bool:
        return IS_WINDOWS

    @staticmethod
    def normalize_key_name(name: str) -> str | None:
        normalized = " ".join(str(name).strip().lower().replace("_", " ").split())
        aliases = {
            "numpad 0": "num 0", "numpad 1": "num 1", "numpad 2": "num 2",
            "numpad 3": "num 3", "numpad 4": "num 4", "numpad 5": "num 5",
            "numpad 6": "num 6", "numpad 7": "num 7", "numpad 8": "num 8",
            "numpad 9": "num 9", "kp add": "add", "kp subtract": "subtract",
            "kp multiply": "multiply", "kp divide": "divide", "kp decimal": "decimal",
            "escape": "esc", "return": "enter", "prior": "page up", "next": "page down",
        }
        normalized = aliases.get(normalized, normalized)
        # Los nombres de teclas simples pueden contener espacios (por ejemplo, NUM 7).
        if normalized in _KEY_TO_VK:
            return normalized
        # Las combinaciones se almacenan siempre como ctrl+alt+shift+win+tecla.
        compact = normalized.replace(" ", "")
        parts = [part for part in compact.split("+") if part]
        if len(parts) < 2:
            return None
        modifiers: list[str] = []
        key = parts[-1]
        for part in parts[:-1]:
            if part not in {"alt", "ctrl", "control", "shift", "win", "windows"}:
                return None
            canonical = {"control": "ctrl", "windows": "win"}.get(part, part)
            if canonical not in modifiers:
                modifiers.append(canonical)
        key = aliases.get(key, key)
        if key not in _KEY_TO_VK:
            return None
        order = [item for item in ("ctrl", "alt", "shift", "win") if item in modifiers]
        return "+".join([*order, key])

    @staticmethod
    def split_hotkey(name: str) -> tuple[int, str] | None:
        normalized = WindowsHotkeyManager.normalize_key_name(name)
        if normalized is None:
            return None
        parts = normalized.split("+")
        key = parts[-1]
        modifiers = 0
        for part in parts[:-1]:
            modifiers |= {"alt": MOD_ALT, "ctrl": MOD_CONTROL, "shift": MOD_SHIFT, "win": MOD_WIN}[part]
        return modifiers, key

    @staticmethod
    def requires_foreground_scope(name: str) -> bool:
        """Todos los atajos de la aplicación pertenecen al juego en primer plano."""
        return WindowsHotkeyManager.normalize_key_name(name) is not None

    @staticmethod
    def pressed_supported_keys() -> set[str]:
        if not IS_WINDOWS:
            return set()
        user32 = ctypes.windll.user32
        pressed: set[str] = set()
        active_modifiers: list[str] = []
        if user32.GetAsyncKeyState(0x11) & 0x8000:
            active_modifiers.append("ctrl")
        if user32.GetAsyncKeyState(0x12) & 0x8000:
            active_modifiers.append("alt")
        if user32.GetAsyncKeyState(0x10) & 0x8000:
            active_modifiers.append("shift")
        if (user32.GetAsyncKeyState(0x5B) | user32.GetAsyncKeyState(0x5C)) & 0x8000:
            active_modifiers.append("win")
        for vk in _CAPTURE_VKS:
            if user32.GetAsyncKeyState(vk) & 0x8000:
                key = _VK_TO_KEY[vk]
                pressed.add("+".join([*active_modifiers, key]) if active_modifiers else key)
        return pressed

    def start(self, hotkeys: dict[str, str]) -> list[str]:
        self.stop()
        self.errors = []
        if not IS_WINDOWS:
            self.errors.append("Los atajos globales Win32 solo están disponibles en Windows.")
            return self.errors

        normalized: dict[str, str] = {}
        for action, raw_key in hotkeys.items():
            if not raw_key:
                continue
            key = self.normalize_key_name(raw_key)
            if key is None:
                self.errors.append(f"Tecla no compatible: {raw_key}")
                continue
            normalized[action] = key

        self._hotkeys = normalized
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="RoleRunHotkeys", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2.0)
        return list(self.errors)

    def _run(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()

        # Force creation of this thread's message queue before the main thread can stop it.
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)

        definitions: dict[int, tuple[str, str, int, int, bool]] = {}
        for hotkey_id, (action, key) in enumerate(self._hotkeys.items(), start=1001):
            parsed = self.split_hotkey(key)
            if parsed is None:
                self.errors.append(f"Atajo inválido: {key}")
                continue
            modifiers, base_key = parsed
            vk = _KEY_TO_VK[base_key]
            definitions[hotkey_id] = (
                action, key, modifiers | MOD_NOREPEAT, vk,
                self.requires_foreground_scope(key),
            )

        id_to_action: dict[int, str] = {}
        failed_ids: set[int] = set()

        def reconcile_registrations() -> None:
            try:
                scoped_active = bool(self.active_predicate())
            except Exception:
                scoped_active = False
            for hotkey_id, (action, key, modifiers, vk, scoped) in definitions.items():
                desired = bool(scoped_active) if scoped else True
                registered = hotkey_id in id_to_action
                if desired and not registered:
                    if user32.RegisterHotKey(None, hotkey_id, modifiers, vk):
                        id_to_action[hotkey_id] = action
                        failed_ids.discard(hotkey_id)
                    elif hotkey_id not in failed_ids:
                        failed_ids.add(hotkey_id)
                        self.errors.append(
                            f"Windows no pudo registrar {key.upper()} para {action} (puede estar en uso)."
                        )
                elif not desired and registered:
                    user32.UnregisterHotKey(None, hotkey_id)
                    id_to_action.pop(hotkey_id, None)

        reconcile_registrations()
        timer_id = int(user32.SetTimer(None, 1, 100, None) or 0)

        self._ready.set()
        try:
            while True:
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result <= 0:
                    break
                if msg.message == WM_HOTKEY:
                    action = id_to_action.get(int(msg.wParam))
                    if action:
                        try:
                            self.callback(action)
                        except Exception:
                            pass
                elif msg.message == WM_TIMER:
                    reconcile_registrations()
        finally:
            if timer_id:
                user32.KillTimer(None, timer_id)
            for hotkey_id in id_to_action:
                user32.UnregisterHotKey(None, hotkey_id)
            self._thread_id = None

    def stop(self) -> None:
        if IS_WINDOWS and self._thread_id:
            try:
                ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None
        self._thread_id = None
        self._ready.clear()
