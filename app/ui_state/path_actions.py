from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExplorerTarget:
    requested: Path
    exists: bool
    open_path: Path | None
    select_file: bool


def resolve_explorer_target(value: str | Path | None) -> ExplorerTarget:
    """Resuelve qué abrir sin realizar ningún efecto externo."""
    requested = Path(str(value or "")).expanduser()
    exists = bool(str(value or "").strip()) and requested.exists()
    if not exists:
        return ExplorerTarget(requested, False, None, False)
    if requested.is_file():
        return ExplorerTarget(requested, True, requested.parent, True)
    return ExplorerTarget(requested, True, requested, False)

