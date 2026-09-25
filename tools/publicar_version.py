"""Prepara y comprueba la publicación de una versión nueva de RoleRun.

El aviso de actualización (``app/update_checker.py``) compara dos números que
viven en sitios distintos: ``APP_VERSION`` en ``app/config.py`` -lo que cada
jugador tiene instalado- y la etiqueta de la última Release de GitHub. Si se
publica la Release ``v0.4.0`` con un ``config.py`` que todavía dice ``0.3.1``,
quien descargue la versión nueva verá "hay una versión nueva" en cada
arranque, para siempre. Este script existe para que eso no pueda pasar.

Uso (desde la carpeta de RoleRun):

    python tools/publicar_version.py preparar 0.4.0
        Sube APP_VERSION a 0.4.0, tras comprobar que es más nueva que la
        instalada y que la última publicada, y explica los pasos siguientes.

    python tools/publicar_version.py comprobar
        Tras publicar: confirma que el config.py de la última Release de
        GitHub dice la misma versión que su etiqueta.

    python tools/publicar_version.py etiqueta v0.4.0
        Falla si APP_VERSION no coincide con esa etiqueta. Lo usa GitHub
        (.github/workflows/publicar.yml) antes de construir nada.

Desde la 0.5.0 la Release no se crea a mano: al subir la etiqueta, GitHub
construye el instalador, lo prueba y publica la Release con él y con las
notas de la cabecera «# vX.Y.Z» del CHANGELOG (tools/notas_de_version.py).
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path
from urllib.error import HTTPError, URLError

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.config import GITHUB_OWNER, GITHUB_REPO  # noqa: E402
from app.update_checker import _parse_version, is_newer  # noqa: E402

CONFIG = RAIZ / "app" / "config.py"
_LINEA_VERSION = re.compile(r'^APP_VERSION = "([^"]*)"$', re.MULTILINE)


def leer_app_version(texto_config: str) -> str:
    coincidencias = _LINEA_VERSION.findall(texto_config)
    if len(coincidencias) != 1:
        raise ValueError(
            f"Se esperaba exactamente una línea APP_VERSION en config.py; hay {len(coincidencias)}."
        )
    return coincidencias[0]


def con_nueva_version(texto_config: str, version: str) -> str:
    leer_app_version(texto_config)  # misma validación: una y solo una línea
    return _LINEA_VERSION.sub(f'APP_VERSION = "{version}"', texto_config)


def _pedir_json(url: str) -> dict | None:
    peticion = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json", "User-Agent": "RoleRunManager-Publicar"},
    )
    try:
        with urllib.request.urlopen(peticion, timeout=10) as respuesta:
            datos = json.load(respuesta)
    except HTTPError as error:
        if error.code == 404:
            return None
        raise
    return datos if isinstance(datos, dict) else None


def ultima_release_publicada() -> str | None:
    datos = _pedir_json(f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest")
    if not datos:
        return None
    return str(datos.get("tag_name") or "").strip() or None


def preparar(version: str) -> int:
    version = version.strip().lstrip("vV")
    try:
        _parse_version(version)
    except ValueError:
        print(f"«{version}» no es un número de versión válido (ejemplo: 0.4.0).")
        return 1

    # En bytes: en Windows, read_text/write_text convertirían los saltos de
    # línea LF del repositorio a CRLF y el diff tocaría el archivo entero.
    texto = CONFIG.read_bytes().decode("utf-8")
    actual = leer_app_version(texto)
    if not is_newer(version, actual):
        print(f"{version} no es más nueva que la versión actual del código ({actual}).")
        return 1
    try:
        publicada = ultima_release_publicada()
    except (URLError, HTTPError, OSError, ValueError) as error:
        print(f"No se pudo consultar GitHub ({error}). Sin esa comprobación no se sigue.")
        return 1
    if publicada and not is_newer(version, publicada):
        print(f"{version} no es más nueva que la última publicada en GitHub ({publicada}).")
        return 1

    CONFIG.write_bytes(con_nueva_version(texto, version).encode("utf-8"))
    etiqueta = f"v{version}"
    print(f"APP_VERSION: {actual} -> {version}")
    print()
    print("Pasos siguientes, en este orden:")
    print(f"  1. Añadir al principio de CHANGELOG.md la cabecera «# {etiqueta}» y,")
    print("     debajo, qué trae para el jugador: son las notas de la Release y del")
    print("     aviso de versión nueva (tools/notas_de_version.py).")
    print(f'  2. git add -A && git commit -m "Publica {etiqueta}"')
    print(f"  3. git tag {etiqueta} && git push origin main {etiqueta}")
    print("  4. GitHub construye, prueba y publica solo (pestaña Actions, ~10 min):")
    print(f"     https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/actions")
    print("  5. python tools/publicar_version.py comprobar")
    return 0


def etiqueta(nombre: str) -> int:
    actual = leer_app_version(CONFIG.read_bytes().decode("utf-8"))
    if nombre.strip().lstrip("vV") != actual:
        print(f"La etiqueta {nombre} no coincide con APP_VERSION = \"{actual}\".")
        return 1
    print(f"La etiqueta {nombre} coincide con APP_VERSION.")
    return 0


def comprobar() -> int:
    try:
        etiqueta = ultima_release_publicada()
    except (URLError, HTTPError, OSError, ValueError) as error:
        print(f"No se pudo consultar GitHub ({error}).")
        return 1
    if not etiqueta:
        print("GitHub no tiene ninguna Release publicada todavía.")
        return 1
    url = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{etiqueta}/app/config.py"
    try:
        with urllib.request.urlopen(url, timeout=10) as respuesta:
            publicada_en_codigo = leer_app_version(respuesta.read().decode("utf-8"))
    except (URLError, HTTPError, OSError, ValueError) as error:
        print(f"No se pudo leer el config.py de {etiqueta} ({error}).")
        return 1
    if publicada_en_codigo != etiqueta.lstrip("vV"):
        print(
            f"MAL: la Release {etiqueta} lleva APP_VERSION = \"{publicada_en_codigo}\". "
            "Quien la descargue verá el aviso de versión nueva en cada arranque."
        )
        return 1
    print(f"Bien: la Release {etiqueta} y su APP_VERSION coinciden.")
    return 0


def main(argumentos: list[str]) -> int:
    if len(argumentos) == 2 and argumentos[0] == "preparar":
        return preparar(argumentos[1])
    if argumentos == ["comprobar"]:
        return comprobar()
    if len(argumentos) == 2 and argumentos[0] == "etiqueta":
        return etiqueta(argumentos[1])
    print(__doc__)
    return 1


if __name__ == "__main__":
    # Con la salida redirigida (Git Bash, una tubería), Windows usaba cp1252 y
    # los acentos salían rotos.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    raise SystemExit(main(sys.argv[1:]))
