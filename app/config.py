from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

APP_NAME = "RoleRun Manager"
APP_VERSION = "0.2.6-alpha.102"
GOLD = "#C29C58"
BG = "#111111"
PANEL = "#1B1B1B"
PANEL_ALT = "#242424"
TEXT = "#F5F5F5"
MUTED = "#A8A8A8"
SUCCESS = "#62B57A"
DANGER = "#D96C6C"

# Recursos de solo lectura que viajan junto al programa.
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
RESOURCES_DIR = ROOT_DIR / "resources"
ENGINE_DIR = ROOT_DIR / "engine"
ENGINE_PUBLISH_DIR = ENGINE_DIR / "publish"
SPRITE_DIR = RESOURCES_DIR / "sprites"


def _windows_documents_dir() -> Path:
    """Obtiene la carpeta Documentos real de Windows, aunque esté redirigida."""
    if os.name != "nt":
        return Path.home() / "Documents"
    try:
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        folder_id = GUID(
            0xFDD39AD0, 0x238F, 0x46AF,
            (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7),
        )
        path_ptr = ctypes.c_wchar_p()
        result = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(folder_id), 0, None, ctypes.byref(path_ptr)
        )
        if result == 0 and path_ptr.value:
            path = Path(path_ptr.value)
            ctypes.windll.ole32.CoTaskMemFree(path_ptr)
            return path
    except Exception:
        pass
    return Path.home() / "Documents"


DOCUMENTS_DIR = _windows_documents_dir()
USER_DATA_DIR = DOCUMENTS_DIR / APP_NAME
RUNS_DIR = USER_DATA_DIR / "Runs"
GLOBAL_OBS_DIR = USER_DATA_DIR / "OBS"
BACKUP_DIR = USER_DATA_DIR / "Backups"
LOG_DIR = USER_DATA_DIR / "Logs"
CONFIG_DIR = USER_DATA_DIR / "Config"

for _folder in (USER_DATA_DIR, RUNS_DIR, GLOBAL_OBS_DIR, BACKUP_DIR, LOG_DIR, CONFIG_DIR):
    _folder.mkdir(parents=True, exist_ok=True)
