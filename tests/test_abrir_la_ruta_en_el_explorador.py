r"""ABRIR JUEGO abría la carpeta de Documentos en vez de la del juego.

El usuario lo describió tal cual: *«en ABRIR JUEGO se abre la carpeta de
documentos, sin más»*. No era que la ruta estuviera mal —el `.nsp` existe y está
bien guardado en `game_sources.json`—, era la forma de invocar al explorador.

Pasando una lista, Python entrecomilla el argumento entero porque lleva
espacios:

    explorer.exe "/select,D:\...\Pokemon Shining Pearl [...].nsp"

y `explorer.exe` no sabe leer eso. No falla ni avisa: se rinde y abre su carpeta
por defecto, que es Documentos. Las comillas tienen que rodear **solo la ruta**.
"""

from __future__ import annotations

import inspect
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui import RoleRunManager  # noqa: E402
from app.ui_state import resolve_explorer_target  # noqa: E402

#: La ruta real del usuario, con espacios y corchetes.
JUEGO = r"D:\Juegos\Pokemon Shining Pearl [010018E011D92800][USA][v393216].nsp"


def test_la_forma_antigua_entrecomillaba_el_argumento_entero() -> None:
    """La demostración del fallo, para que no se pierda el porqué."""
    linea = subprocess.list2cmdline(["explorer.exe", f"/select,{JUEGO}"])

    assert linea.startswith('explorer.exe "/select,'), linea
    assert '"/select,' in linea, "explorer.exe no sabe leer esto"


def test_ahora_las_comillas_rodean_solo_la_ruta() -> None:
    fuente = inspect.getsource(RoleRunManager._open_path_in_explorer)
    codigo = "\n".join(
        linea for linea in fuente.splitlines() if not linea.strip().startswith("#")
    )

    assert 'f\'explorer.exe /select,"{target.requested}"\'' in codigo
    assert 'subprocess.Popen(["explorer.exe"' not in codigo


def test_la_linea_que_se_manda_es_la_que_explorer_entiende() -> None:
    esperada = f'explorer.exe /select,"{JUEGO}"'

    assert esperada.count('"') == 2
    assert esperada.startswith("explorer.exe /select,")


def test_un_archivo_se_selecciona_y_una_carpeta_se_abre(tmp_path) -> None:
    """La distinción de la que depende todo esto no ha cambiado."""
    archivo = tmp_path / "partida.sav"
    archivo.write_bytes(b"x")

    destino = resolve_explorer_target(archivo)
    assert destino.select_file is True
    assert destino.open_path == tmp_path

    carpeta = resolve_explorer_target(tmp_path)
    assert carpeta.select_file is False
    assert carpeta.open_path == tmp_path


def test_una_ruta_que_no_existe_no_se_abre_a_ciegas(tmp_path) -> None:
    destino = resolve_explorer_target(tmp_path / "no-esta.nsp")

    assert destino.exists is False
    assert destino.open_path is None
