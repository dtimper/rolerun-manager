from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

from app.sdl_gamepad import BUTTON_NAMES, GamepadSample

ERROR_SUCCESS = 0

#: Bits de `XINPUT_GAMEPAD.wButtons`, en el mismo vocabulario que `BUTTON_NAMES`
#: -así el resto de RoleRun (la pantalla de asignación, la navegación, los
#: atajos) no tiene que saber de dónde vino cada pulsación. XInput no expone
#: el botón Guide/Xbox -Microsoft lo reserva a propósito-, así que ese nombre
#: nunca aparece aquí.
_BUTTON_BITS: dict[str, int] = {
    "dpad up": 0x0001,
    "dpad down": 0x0002,
    "dpad left": 0x0004,
    "dpad right": 0x0008,
    "start": 0x0010,
    "back": 0x0020,
    "left stick": 0x0040,
    "right stick": 0x0080,
    "left shoulder": 0x0100,
    "right shoulder": 0x0200,
    "a": 0x1000,
    "b": 0x2000,
    "x": 0x4000,
    "y": 0x8000,
}
assert set(_BUTTON_BITS) <= set(BUTTON_NAMES)


class _XInputGamepadStruct(ctypes.Structure):
    _fields_ = [
        ("wButtons", wintypes.WORD),
        ("bLeftTrigger", ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]


class _XInputState(ctypes.Structure):
    _fields_ = [
        ("dwPacketNumber", wintypes.DWORD),
        ("Gamepad", _XInputGamepadStruct),
    ]


def _load_xinput():
    if os.name != "nt":
        return None
    for name in ("xinput1_4.dll", "xinput1_3.dll", "xinput9_1_0.dll"):
        try:
            dll = ctypes.WinDLL(name)
        except OSError:
            continue
        dll.XInputGetState.argtypes = [wintypes.DWORD, ctypes.POINTER(_XInputState)]
        dll.XInputGetState.restype = wintypes.DWORD
        return dll
    return None


class XInputGamepad:
    """Lee un mando por XInput -viene con Windows, no depende de ningún emulador.

    `SDLGamepad` (ver `sdl_gamepad.py`) solo puede leer un mando pidiéndole
    prestada a Ryujinx su copia de `SDL2.dll`: sin Ryujinx abierto, RoleRun no
    tenía ninguna otra forma de saber que se había pulsado un botón, ni
    siquiera para la propia pantalla de asignación. Azahar (el emulador de
    3DS) ni siquiera trae un `SDL2.dll` que pedir prestado -comprobado en la
    instalación real del usuario, `C:\\Program Files\\Azahar`, solo hay DLLs
    de Qt6/FFmpeg-, así que ese camino no era ampliable. XInput sí es un
    camino independiente de cualquier emulador: es la misma API con la que
    Windows habla con cualquier mando Xbox (o compatible) sin necesitar
    ningún controlador ni DLL de terceros.
    """

    def __init__(self) -> None:
        self._dll = _load_xinput()

    @property
    def available(self) -> bool:
        return self._dll is not None

    def sample(self) -> GamepadSample:
        if self._dll is None:
            return GamepadSample(False)
        state = _XInputState()
        for index in range(4):
            try:
                ok = self._dll.XInputGetState(index, ctypes.byref(state)) == ERROR_SUCCESS
            except Exception:
                return GamepadSample(False)
            if ok:
                buttons = int(state.Gamepad.wButtons)
                pressed = frozenset(
                    name for name, bit in _BUTTON_BITS.items() if buttons & bit
                )
                return GamepadSample(True, "Mando XInput", pressed)
        return GamepadSample(False)

    def close(self) -> None:
        return None
