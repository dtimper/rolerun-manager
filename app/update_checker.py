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
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError

_USER_AGENT = "RoleRunManager-UpdateChecker"
_PRERELEASE_STAGE_ORDER = {"alpha": 0, "beta": 1, "rc": 2}


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    version: str
    url: str
    notes: str


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
    )


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
