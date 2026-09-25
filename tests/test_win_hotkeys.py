from __future__ import annotations

from app.win_hotkeys import _effective_vk, _KEY_TO_VK, _NUMLOCK_OFF_ALIAS, WindowsHotkeyManager


def test_plain_text_keys_are_allowed_but_require_game_foreground_scope() -> None:
    assert WindowsHotkeyManager.normalize_key_name("d") == "d"
    assert WindowsHotkeyManager.normalize_key_name("D") == "d"
    assert WindowsHotkeyManager.normalize_key_name("7") == "7"
    assert WindowsHotkeyManager.normalize_key_name("space") == "space"
    assert WindowsHotkeyManager.requires_foreground_scope("d") is True
    assert WindowsHotkeyManager.requires_foreground_scope("7") is True
    assert WindowsHotkeyManager.requires_foreground_scope("space") is True


def test_every_supported_shortcut_requires_game_foreground_scope() -> None:
    assert WindowsHotkeyManager.normalize_key_name("f6") == "f6"
    assert WindowsHotkeyManager.normalize_key_name("num 7") == "num 7"
    assert WindowsHotkeyManager.normalize_key_name("ctrl+d") == "ctrl+d"
    assert WindowsHotkeyManager.requires_foreground_scope("ctrl+d") is True
    assert WindowsHotkeyManager.requires_foreground_scope("f6") is True


def test_numpad_seven_falls_back_to_home_without_num_lock() -> None:
    """Reportado por el usuario 09-09-2026: "sumar vida... el 7 del panel
    numérico... no veo que suba" -con Bloq Num apagado, esa tecla física
    manda VK_HOME (0x24), no VK_NUMPAD7 (0x67); `RegisterHotKey` solo
    escucha el VK exacto que se le pide, así que el atajo se quedaba mudo
    sin ningún aviso."""
    vidas_mas_vk = _KEY_TO_VK["num 7"]
    assert vidas_mas_vk == 0x67
    assert _effective_vk(vidas_mas_vk, num_lock_on=True) == 0x67
    assert _effective_vk(vidas_mas_vk, num_lock_on=False) == 0x24  # VK_HOME


def test_every_numpad_digit_and_decimal_has_a_num_lock_off_alias() -> None:
    for digit in range(10):
        vk = _KEY_TO_VK[f"num {digit}"]
        assert vk in _NUMLOCK_OFF_ALIAS, f"num {digit} sin alias para Bloq Num apagado"
    assert _KEY_TO_VK["decimal"] in _NUMLOCK_OFF_ALIAS


def test_non_numpad_keys_are_never_remapped_by_num_lock_state() -> None:
    for key in ("d", "7", "f6", "space", "enter", "add", "subtract"):
        vk = _KEY_TO_VK[key]
        assert _effective_vk(vk, num_lock_on=True) == vk
        assert _effective_vk(vk, num_lock_on=False) == vk
