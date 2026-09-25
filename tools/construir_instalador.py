"""Fabrica ``RoleRunManager-Setup.exe``: un instalador que no necesita nada más.

Uso (desde la carpeta de RoleRun):

    python tools/construir_instalador.py

Es el mismo script que ejecuta GitHub al publicar una versión
(``.github/workflows/publicar.yml``), para que lo que se prueba aquí sea lo
mismo que se publica. Tres pasos:

1. **Motor** (``engine/RoleRun.SaveEngine``) compilado *self-contained*: lleva
   su propio .NET dentro, así que el jugador no necesita instalar .NET. Hasta
   la 0.4.1 cada jugador tenía que compilarlo con el SDK de .NET 10
   (``preparar_motor.bat``), y a quien no lo tenía no le funcionaba.
2. **Programa** congelado con PyInstaller: lleva su propio Python y sus
   librerías.
3. **Instalador** con Inno Setup (``tools/instalador.iss``): instalación por
   usuario, sin pedir administrador, con acceso directo y desinstalador.

Solo se empaquetan archivos que Git conoce (``git ls-files``): así la copia
local y la de GitHub son idénticas y no viaja nada privado ni descargado a
mano (``data/reporte_correo.dat``, sprites en caché…).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
#: ROLERUN_BUILD permite construir en otra carpeta (p. ej. si la habitual está
#: bloqueada por una prueba anterior que sigue abierta).
BUILD = Path(os.environ.get("ROLERUN_BUILD") or RAIZ / "build")
PREPARADO = BUILD / "preparado"
PROGRAMA = BUILD / "dist" / "RoleRun Manager"
SALIDA = BUILD / "salida"
NOMBRE_INSTALADOR = "RoleRunManager-Setup"

#: Lo mismo que escribe ``preparar_motor.bat``: sin «role-markers-v3»,
#: ``SaveEngineClient`` usaría en silencio el formato antiguo de marcas de rol.
MARCA_DEL_MOTOR = "oras-inventory-live-v2+role-markers-v3"
CARPETAS_DE_DATOS = ("data", "resources", "lang")


def _ejecutar(orden: list[str], **opciones) -> None:
    print("\n>", " ".join(str(parte) for parte in orden), flush=True)
    subprocess.run(orden, check=True, cwd=RAIZ, **opciones)


def version_del_programa() -> str:
    texto = (RAIZ / "app" / "config.py").read_text(encoding="utf-8")
    return re.search(r'^APP_VERSION = "([^"]+)"$', texto, re.MULTILINE).group(1)


def buscar_iscc() -> Path:
    candidatos = [
        os.environ.get("ISCC"),
        shutil.which("ISCC"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
    ]
    for candidato in candidatos:
        if candidato and Path(candidato).is_file():
            return Path(candidato)
    raise SystemExit("No se encontró Inno Setup 6 (ISCC.exe).")


def compilar_motor() -> Path:
    destino = PREPARADO / "engine" / "publish"
    _ejecutar([
        "dotnet", "publish", "engine/RoleRun.SaveEngine/RoleRun.SaveEngine.csproj",
        "-c", "Release", "-r", "win-x64", "--self-contained", "true",
        "-p:DebugType=none", "-o", str(destino),
    ])
    (destino / "rolerun_engine_version.txt").write_text(MARCA_DEL_MOTOR + "\n", encoding="utf-8")
    return destino


def copiar_datos() -> None:
    conocidos = subprocess.run(
        ["git", "ls-files", "-z", "--", *CARPETAS_DE_DATOS],
        check=True, cwd=RAIZ, capture_output=True,
    ).stdout.decode("utf-8").split("\0")
    copiados = 0
    for relativo in filter(None, conocidos):
        origen = RAIZ / relativo
        if not origen.is_file():
            continue
        destino = PREPARADO / relativo
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origen, destino)
        copiados += 1
    print(f"\n{copiados} archivos de datos copiados.")


def congelar_programa() -> None:
    # PyInstaller guarda los --add-data en `_internal/<destino>`, y
    # `app/config.py` calcula ROOT_DIR como dos carpetas por encima de sí
    # mismo: congelado, eso es justo `_internal`.
    datos = [f"--add-data={PREPARADO / carpeta};{carpeta}" for carpeta in (*CARPETAS_DE_DATOS, "engine")]
    _ejecutar([
        sys.executable, "-m", "PyInstaller", "main.py",
        "--noconfirm", "--clean", "--onedir", "--windowed",
        "--name", "RoleRun Manager",
        "--icon", str(RAIZ / "resources" / "icono_sin_fondo.ico"),
        "--distpath", str(BUILD / "dist"),
        "--workpath", str(BUILD / "work"),
        "--specpath", str(BUILD),
        "--collect-data", "customtkinter",
        # RoleRun no usa numpy, pero si está instalado en el Python que
        # construye, los hooks de Pillow lo arrastran: 27 MB para nada.
        "--exclude-module", "numpy",
        *datos,
    ])


def crear_instalador(version: str) -> Path:
    _ejecutar([
        str(buscar_iscc()),
        f"/DAppVersion={version}",
        f"/DSourceDir={PROGRAMA}",
        f"/DOutputDir={SALIDA}",
        f"/DOutputName={NOMBRE_INSTALADOR}",
        f"/DIconFile={RAIZ / 'resources' / 'icono_sin_fondo.ico'}",
        str(RAIZ / "tools" / "instalador.iss"),
    ])
    return SALIDA / f"{NOMBRE_INSTALADOR}.exe"


def main() -> int:
    version = version_del_programa()
    print(f"RoleRun Manager {version}")
    # Sin ignore_errors: si algo tiene abierta la carpeta (el programa de una
    # prueba anterior, una consola dentro), mejor saberlo aquí que mezclar
    # restos de la construcción anterior en el instalador.
    if BUILD.exists():
        shutil.rmtree(BUILD)
    compilar_motor()
    copiar_datos()
    congelar_programa()
    instalador = crear_instalador(version)
    megas = instalador.stat().st_size / 1024 / 1024
    print(f"\nListo: {instalador} ({megas:.0f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
