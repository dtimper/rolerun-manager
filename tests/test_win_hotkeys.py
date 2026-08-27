from __future__ import annotations

from app.win_hotkeys import WindowsHotkeyManager


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
