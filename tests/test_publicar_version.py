"""El script de publicación sube APP_VERSION sin tocar nada más de config.py.

Si la línea no se encontrara o se duplicara, publicar dejaría el número del
programa y el de la Release desincronizados: quien descargara la versión
nueva vería el aviso de actualización en cada arranque.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_RUTA = Path(__file__).resolve().parent.parent / "tools" / "publicar_version.py"
_spec = importlib.util.spec_from_file_location("publicar_version", _RUTA)
publicar_version = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(publicar_version)

CONFIG = 'APP_NAME = "RoleRun Manager"\nAPP_VERSION = "0.3.1"\n\nGITHUB_OWNER = "dtimper"\n'


def test_lee_la_version_del_config_real() -> None:
    texto = (_RUTA.parent.parent / "app" / "config.py").read_text(encoding="utf-8")
    assert publicar_version.leer_app_version(texto)


def test_cambia_solo_la_linea_de_version() -> None:
    nuevo = publicar_version.con_nueva_version(CONFIG, "0.4.0")
    assert nuevo == CONFIG.replace('"0.3.1"', '"0.4.0"')
    assert publicar_version.leer_app_version(nuevo) == "0.4.0"


@pytest.mark.parametrize("texto", ["APP_NAME = 'x'\n", CONFIG + 'APP_VERSION = "9.9.9"\n'])
def test_se_niega_si_no_hay_exactamente_una_linea_de_version(texto: str) -> None:
    with pytest.raises(ValueError):
        publicar_version.con_nueva_version(texto, "0.4.0")


def test_preparar_rechaza_una_version_que_no_es_mas_nueva(capsys) -> None:
    assert publicar_version.preparar("0.0.1") == 1
    assert "no es más nueva" in capsys.readouterr().out


def test_tambien_con_saltos_de_linea_de_windows() -> None:
    """GitHub descarga el código con CRLF: con la versión anterior del patrón,
    la comprobación de la etiqueta de v0.5.0 falló allí y aquí no."""
    windows = CONFIG.replace("\n", "\r\n")
    assert publicar_version.leer_app_version(windows) == "0.3.1"
    nuevo = publicar_version.con_nueva_version(windows, "0.4.0")
    assert nuevo == windows.replace('"0.3.1"', '"0.4.0"')
