"""Lectura de mando por XInput -viene con Windows, no depende de ningún

emulador-, ver el porqué en el docstring de `XInputGamepad`
(`app/xinput_gamepad.py`): sin esto, ningún botón se detectaba nunca sin
Ryujinx abierto -reportado por el usuario 08-09-2026 en la pantalla de
asignación de botón de mando.
"""

from __future__ import annotations

import ctypes

from app.sdl_gamepad import BUTTON_NAMES
from app.xinput_gamepad import ERROR_SUCCESS, XInputGamepad, _BUTTON_BITS, _XInputState


def test_button_bits_match_the_documented_xinput_gamepad_enum() -> None:
    """Constantes públicas y estables de `XINPUT_GAMEPAD_BUTTON` (Microsoft).

    Fijarlas aquí protege contra un despiste al escribirlas a mano -no hay
    mando físico con el que probar esto en este entorno-, y contra que
    alguien las cambie sin darse cuenta de que son un contrato externo, no un
    número inventado.
    """
    assert _BUTTON_BITS == {
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


def test_every_xinput_button_name_is_a_recognised_button_name() -> None:
    assert set(_BUTTON_BITS) <= set(BUTTON_NAMES)


def test_guide_is_never_reported_xinput_does_not_expose_it() -> None:
    """XInput no expone el botón Guide/Xbox -Microsoft lo reserva-, a
    diferencia de SDL (ver `test_controller_ui_does_not_expose_a_hidden_guide_chord`
    en `test_sdl_gamepad.py`, que lo oculta por una razón de UX distinta)."""
    assert "guide" not in _BUTTON_BITS


def test_sample_reports_disconnected_without_any_dll_loaded() -> None:
    pad = XInputGamepad.__new__(XInputGamepad)
    pad._dll = None
    assert pad.available is False
    sample = pad.sample()
    assert sample.connected is False
    assert sample.pressed == frozenset()


def test_sample_parses_the_first_connected_slot() -> None:
    """Simula `XInputGetState` sin depender de tener un mando físico enchufado."""

    class FakeDLL:
        def __init__(self, connected_slot: int, buttons: int) -> None:
            self.connected_slot = connected_slot
            self.buttons = buttons
            self.calls: list[int] = []

        def XInputGetState(self, index, state_ptr) -> int:
            self.calls.append(index)
            if index != self.connected_slot:
                return 1167  # ERROR_DEVICE_NOT_CONNECTED
            casted = ctypes.cast(state_ptr, ctypes.POINTER(_XInputState))
            casted.contents.Gamepad.wButtons = self.buttons
            return ERROR_SUCCESS

    pad = XInputGamepad.__new__(XInputGamepad)
    # a (0x1000) + back (0x0020): justo el tipo de combinación que la
    # pantalla de asignación necesita distinguir botón a botón.
    pad._dll = FakeDLL(connected_slot=2, buttons=0x1000 | 0x0020)

    sample = pad.sample()

    assert sample.connected is True
    assert sample.pressed == frozenset({"a", "back"})
    # Prueba los slots en orden hasta encontrar el primero conectado -mismo
    # criterio que `SDLGamepad` usa para el primer mando disponible.
    assert pad._dll.calls == [0, 1, 2]


def test_sample_reports_disconnected_when_no_slot_answers() -> None:
    class FakeDLL:
        def XInputGetState(self, index, state_ptr) -> int:
            return 1167

    pad = XInputGamepad.__new__(XInputGamepad)
    pad._dll = FakeDLL()

    sample = pad.sample()

    assert sample.connected is False
    assert sample.pressed == frozenset()


def test_a_broken_dll_call_is_swallowed_not_raised() -> None:
    """Un mando puede desconectarse a media lectura; no debe tirar el sondeo
    de 60 Hz que lo llama -mismo principio que ya sigue `SDLGamepad`."""

    class ExplodingDLL:
        def XInputGetState(self, index, state_ptr) -> int:
            raise OSError("mando desconectado a media lectura")

    pad = XInputGamepad.__new__(XInputGamepad)
    pad._dll = ExplodingDLL()

    sample = pad.sample()

    assert sample.connected is False
