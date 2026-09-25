from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

APP_NAME = "RoleRun Manager"
APP_VERSION = "0.4.1"

# Repositorio de GitHub donde se publican las Releases (pestaña "Releases" del
# repo, cada una con su tag de versión). Con cualquiera de los dos vacío, la
# comprobación de actualizaciones queda desactivada sin más -ver
# app/update_checker.py-. Rellenar en cuanto el repositorio exista.
GITHUB_OWNER = "dtimper"
GITHUB_REPO = "rolerun-manager"
UPDATE_CHECK_TIMEOUT_SECONDS = 5.0
GOLD = "#C29C58"
BG = "#111111"
PANEL = "#1B1B1B"
PANEL_ALT = "#242424"
TEXT = "#F5F5F5"
MUTED = "#A8A8A8"
SUCCESS = "#62B57A"
DANGER = "#D96C6C"

# Nombre y color por tipo elemental, indexados por el id que ya usa el resto
# de RoleRun (ver `gen4_rom_service.normalize_type`): 0=normal…16=siniestro,
# 17=hada. El color es una elección de la interfaz, no un dato de partida —el
# id de cada movimiento sí sale siempre de lo que demuestra el juego activo.
def mix_hex_colors(source: str, target: str, ratio: float) -> str:
    """Interpola dos colores ``#RRGGBB``. ``ratio=0`` da ``source``, ``ratio=1`` da ``target``."""
    ratio = max(0.0, min(float(ratio), 1.0))
    source_rgb = tuple(int(source[index:index + 2], 16) for index in (1, 3, 5))
    target_rgb = tuple(int(target[index:index + 2], 16) for index in (1, 3, 5))
    mixed = tuple(round(start + (end - start) * ratio) for start, end in zip(source_rgb, target_rgb))
    return "#" + "".join(f"{value:02X}" for value in mixed)


def move_type_fill(type_color: str, background: str = "#1B1B1B") -> str:
    """Teñido sutil del interior de una casilla de movimiento con su tipo.

    Pedido del usuario 02-09-2026: que se note el tipo también por dentro,
    distinguiéndose del borde -que se queda con el color saturado-, no solo
    por el marco y la esquina.
    """
    return mix_hex_colors(type_color, background, 0.82)


MOVE_TYPE_INFO: dict[int, tuple[str, str]] = {
    0: ("NORMAL", "#A8A878"),
    1: ("LUCHA", "#C03028"),
    2: ("VOLADOR", "#A890F0"),
    3: ("VENENO", "#A040A0"),
    4: ("TIERRA", "#E0C068"),
    5: ("ROCA", "#B8A038"),
    6: ("BICHO", "#A8B820"),
    7: ("FANTASMA", "#705898"),
    8: ("ACERO", "#B8B8D0"),
    9: ("FUEGO", "#F08030"),
    10: ("AGUA", "#6890F0"),
    11: ("PLANTA", "#78C850"),
    12: ("ELÉCTRICO", "#F8D030"),
    13: ("PSÍQUICO", "#F85888"),
    14: ("HIELO", "#98D8D8"),
    15: ("DRAGÓN", "#7038F8"),
    16: ("SINIESTRO", "#705848"),
    17: ("HADA", "#EE99AC"),
}

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
