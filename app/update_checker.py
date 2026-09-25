from __future__ import annotations

"""Comprobación de nuevas versiones publicadas en GitHub Releases.

RoleRun Manager no se autoactualiza: solo avisa. Al arrancar, consulta la
última Release pública del repositorio y, si es más nueva que la instalada,
se lo muestra al jugador con un enlace de descarga. Sin GITHUB_OWNER/REPO
configurados, o sin red, la comprobación no hace nada -nunca debe impedir
que el programa abra.
"""

import json
import os
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError

_USER_AGENT = "RoleRunManager-UpdateChecker"
_PRERELEASE_STAGE_ORDER = {"alpha": 0, "beta": 1, "rc": 2}

#: Nombre del instalador que adjunta a cada Release
#: ``.github/workflows/publicar.yml`` (ver ``tools/construir_instalador.py``).
NOMBRE_INSTALADOR = "RoleRunManager-Setup.exe"


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    version: str
    url: str
    notes: str
    #: Descarga directa del instalador, si la Release lo trae. Las anteriores
    #: a la 0.5.0 solo tienen el zip de código de GitHub.
    installer_url: str = ""


def _parse_version(version: str) -> tuple:
    """Convierte ``X.Y.Z[-alpha.N|-beta.N|-rc.N]`` en una tupla comparable.

    Sigue la precedencia de SemVer 2.0: una versión sin preestreno
    (``1.2.0``) es más nueva que cualquier preestreno del mismo número base
    (``1.2.0-alpha.9``). Un preestreno de etapa u orden desconocido se trata
    como el más antiguo de ese número base, para no anunciar por error una
    versión que en realidad es más vieja o experimental.
    """
    cleaned = version.strip().lstrip("vV")
    base, _, pre = cleaned.partition("-")
    core = tuple(int(part) for part in base.split(".") if part.strip().isdigit())
    if not core:
        raise ValueError(f"Versión sin número reconocible: {version!r}")
    if not pre:
        return (core, (1,))
    pre_label, _, pre_number = pre.partition(".")
    stage = _PRERELEASE_STAGE_ORDER.get(pre_label.strip().lower(), -1)
    number = int(pre_number) if pre_number.strip().isdigit() else 0
    return (core, (0, stage, number))


def is_newer(remote_version: str, local_version: str) -> bool:
    """``True`` si ``remote_version`` es estrictamente más nueva que ``local_version``.

    Cualquier versión ilegible se trata como "no es más nueva": un formato
    inesperado en la Release remota no debe convertirse en un aviso falso.
    """
    try:
        return _parse_version(remote_version) > _parse_version(local_version)
    except ValueError:
        return False


def check_for_update(
    current_version: str,
    owner: str,
    repo: str,
    *,
    timeout: float = 5.0,
) -> UpdateInfo | None:
    """Consulta la última Release pública de GitHub del repositorio dado.

    Devuelve ``None`` ante cualquier fallo -sin ``owner``/``repo``, sin red,
    repositorio sin Releases todavía, respuesta inesperada- para que la
    comprobación jamás bloquee ni interrumpa el arranque del programa.
    """
    owner = (owner or "").strip()
    repo = (repo or "").strip()
    if not owner or not repo:
        return None

    request = urllib.request.Request(
        f"https://api.github.com/repos/{owner}/{repo}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": _USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except (URLError, HTTPError, OSError, ValueError):
        return None

    if not isinstance(payload, dict):
        return None
    tag = str(payload.get("tag_name") or "").strip()
    if not tag or not is_newer(tag, current_version):
        return None

    return UpdateInfo(
        version=tag.lstrip("vV"),
        url=str(payload.get("html_url") or f"https://github.com/{owner}/{repo}/releases/latest"),
        notes=str(payload.get("body") or "").strip(),
        installer_url=_url_del_instalador(payload.get("assets")),
    )


def pasos_para_actualizar(info: UpdateInfo, carpeta_de_datos: str | Path) -> str:
    """Qué hacer después de pulsar DESCARGAR, según lo que traiga la Release."""
    runs = f"Tus Runs no se pierden: se guardan aparte, en {carpeta_de_datos}."
    if info.installer_url:
        # DESCARGAR baja el instalador directamente. Sin firma digital de
        # pago, Windows SmartScreen avisa la primera vez.
        return (
            f"1. Pulsa DESCARGAR: se bajará {NOMBRE_INSTALADOR}.\n"
            "2. Ábrelo. Si Windows avisa de que «protegió su PC», pulsa «Más información» "
            "y luego «Ejecutar de todas formas».\n"
            "3. Sigue los pasos: se instala encima. Si RoleRun está abierto, el "
            "instalador te ofrecerá cerrarlo.\n"
            + runs
        )
    # Solo el zip de código: copiar encima de la carpeta actual conserva el
    # motor ya compilado (`engine/publish` no viaja en el zip).
    return (
        "1. Pulsa DESCARGAR. En la página que se abre, baja «Source code (zip)».\n"
        "2. Cierra RoleRun Manager.\n"
        "3. Descomprime el zip y copia todo lo que hay dentro de su carpeta en tu "
        "carpeta de RoleRun Manager, aceptando reemplazar los archivos.\n"
        "4. Abre instalar_y_abrir.bat.\n"
        + runs
    )


def _url_del_instalador(adjuntos: object) -> str:
    if not isinstance(adjuntos, list):
        return ""
    for adjunto in adjuntos:
        if isinstance(adjunto, dict) and adjunto.get("name") == NOMBRE_INSTALADOR:
            return str(adjunto.get("browser_download_url") or "")
    return ""


_MARKDOWN_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_MARKDOWN_BULLET = re.compile(r"^(\s*)[-*+]\s+")
_MARKDOWN_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_MARKDOWN_EMPHASIS = re.compile(r"(\*\*|__)(.+?)\1")


def notas_legibles(notas: str) -> str:
    """Pasa las notas de una Release de Markdown a texto que se lee tal cual.

    GitHub guarda las notas en Markdown y el aviso las pinta en un cuadro de
    texto plano: sin esto, el jugador vería ``## Novedades`` o ``**vida**``
    con los símbolos. Solo se tratan las marcas que se usan al escribir unas
    notas normales -títulos, viñetas, negrita, enlaces y código-; lo demás
    se deja como está.
    """
    lineas = []
    for linea in notas.replace("\r\n", "\n").split("\n"):
        titulo = _MARKDOWN_HEADING.match(linea)
        if titulo:
            linea = titulo.group(1).upper()
        linea = _MARKDOWN_BULLET.sub(r"\1• ", linea)
        linea = _MARKDOWN_LINK.sub(r"\1", linea)
        linea = _MARKDOWN_EMPHASIS.sub(r"\2", linea)
        lineas.append(linea.replace("`", ""))
    return "\n".join(lineas).strip()


class DismissedVersionStore:
    """Recuerda qué versión anunciada el jugador ya pidió no volver a ver.

    "Más tarde" no escribe aquí a propósito: solo pospone el aviso hasta el
    próximo arranque. Solo "No avisar de esta versión" persiste, y solo para
    esa versión concreta -una Release posterior siempre vuelve a avisar.
    """

    def __init__(self, store_path: str | Path) -> None:
        self.store_path = Path(store_path)
        self._dismissed_version = ""
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.store_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, TypeError):
            return
        if isinstance(raw, dict):
            self._dismissed_version = str(raw.get("dismissed_version", "") or "")

    def is_dismissed(self, version: str) -> bool:
        return bool(version) and version == self._dismissed_version

    def dismiss(self, version: str) -> None:
        self._dismissed_version = version
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.store_path.with_name(self.store_path.name + ".tmp")
        payload = {"dismissed_version": version}
        try:
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(temporary, self.store_path)
        except OSError:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
