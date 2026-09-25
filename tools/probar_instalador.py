"""Prueba ``RoleRunManager-Setup.exe`` como lo haría un ordenador sin nada.

Uso:

    python tools/probar_instalador.py build/salida/RoleRunManager-Setup.exe

GitHub lo ejecuta antes de publicar (``.github/workflows/publicar.yml``): si
algo falla, la versión no se publica. Comprueba:

1. que se instala en silencio (en una carpeta temporal y sin accesos directos:
   no pisa los de una instalación de verdad);
2. que lleva la marca de formato del motor (sin ella, ``SaveEngineClient``
   usaría en silencio el formato antiguo de marcas de rol);
3. que el motor funciona **sin .NET visible** (PATH mínimo y ``DOTNET_ROOT``
   apuntando a la nada): exporta el catálogo de movimientos;
4. que el programa arranca **sin Python ni .NET visibles** y sigue vivo;
5. que se desinstala y no deja la carpeta. Se desinstala pase lo que pase: una
   prueba fallida no deja una instalación a medias en el sistema.

No toca Documentos\\RoleRun Manager: el programa arranca en la pantalla de
elegir juego y se cierra sin abrir ninguna Run.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SEGUNDOS_VIVO = 15


class PruebaFallida(Exception):
    pass


def entorno_vacio() -> dict[str, str]:
    """El entorno de un ordenador sin Python ni .NET instalados."""
    raiz = os.environ.get("SystemRoot", r"C:\Windows")
    entorno = {
        clave: valor for clave, valor in os.environ.items()
        if not clave.upper().startswith(("PYTHON", "DOTNET", "CONDA", "VIRTUAL_ENV", "PIP_"))
    }
    entorno["PATH"] = rf"{raiz}\System32;{raiz}"
    entorno["DOTNET_ROOT"] = r"Z:\no_existe_dotnet"
    return entorno


def comprobar(condicion: bool, mensaje: str) -> None:
    print(("OK   " if condicion else "FALLO") + " " + mensaje, flush=True)
    if not condicion:
        raise PruebaFallida(mensaje)


def probar_lo_instalado(carpeta: Path, temporal: Path) -> None:
    programa = carpeta / "RoleRun Manager.exe"
    motor_dir = carpeta / "_internal" / "engine" / "publish"
    comprobar(programa.is_file(), "está RoleRun Manager.exe")
    marca = (motor_dir / "rolerun_engine_version.txt").read_text(encoding="utf-8")
    comprobar("role-markers-v3" in marca, "el motor lleva la marca role-markers-v3")

    catalogo = temporal / "catalogo.json"
    motor = subprocess.run(
        [str(motor_dir / "RoleRun.SaveEngine.exe"), "export-moves", "--output", str(catalogo)],
        env=entorno_vacio(), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    comprobar(motor.returncode == 0, f"el motor funciona sin .NET instalado (código {motor.returncode})")
    movimientos = json.loads(catalogo.read_text(encoding="utf-8-sig")).get("moves", [])
    comprobar(len(movimientos) > 100, f"el motor exporta el catálogo ({len(movimientos)} movimientos)")

    proceso = subprocess.Popen([str(programa)], env=entorno_vacio(), cwd=str(carpeta))
    try:
        time.sleep(SEGUNDOS_VIVO)
        comprobar(
            proceso.poll() is None,
            f"el programa sigue abierto a los {SEGUNDOS_VIVO} s sin Python ni .NET "
            f"(código {proceso.returncode})",
        )
    finally:
        subprocess.run(["taskkill", "/PID", str(proceso.pid), "/T", "/F"], capture_output=True)
        proceso.wait(timeout=30)
        time.sleep(2)


def desinstalar(carpeta: Path) -> None:
    desinstalador = carpeta / "unins000.exe"
    if not desinstalador.is_file():
        return
    resultado = subprocess.run([str(desinstalador), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
    comprobar(resultado.returncode == 0, f"se desinstala (código {resultado.returncode})")
    # El desinstalador se copia a sí mismo a una carpeta temporal y borra la
    # instalación desde allí: hay que darle un momento.
    programa = carpeta / "RoleRun Manager.exe"
    for _ in range(30):
        if not programa.exists():
            break
        time.sleep(1)
    comprobar(not programa.exists(), "la desinstalación quita el programa")


def main(argumentos: list[str]) -> int:
    if len(argumentos) != 1:
        print(__doc__)
        return 1
    instalador = Path(argumentos[0]).resolve()
    try:
        comprobar(instalador.is_file(), f"existe {instalador.name}")
        with tempfile.TemporaryDirectory(prefix="rr_") as nombre:
            temporal = Path(nombre)
            carpeta = temporal / "RoleRun Manager"
            instalado = subprocess.run([
                str(instalador), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                "/MERGETASKS=!escritorio", "/NOICONS",
                f"/DIR={carpeta}", f"/LOG={temporal / 'instalacion.log'}",
            ])
            try:
                comprobar(instalado.returncode == 0, f"se instala (código {instalado.returncode})")
                probar_lo_instalado(carpeta, temporal)
            finally:
                desinstalar(carpeta)
    except PruebaFallida:
        print("\nLa prueba del instalador ha FALLADO.")
        return 1
    print("\nTodas las comprobaciones han pasado.")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
