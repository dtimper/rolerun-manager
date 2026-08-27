from __future__ import annotations

from dataclasses import dataclass
from typing import Hashable, Iterable


@dataclass(frozen=True, slots=True)
class SpatialTarget:
    """Destino seleccionable situado en una cuadrícula lógica."""

    key: Hashable
    row: int
    column: int


class SpatialSelection:
    """Selector direccional puro, independiente de Tkinter.

    No existe selección implícita: la primera flecha activa el primer destino
    disponible. ``clear`` vuelve exactamente a ese estado inicial.
    """

    def __init__(self, targets: Iterable[SpatialTarget] = ()) -> None:
        self.targets: tuple[SpatialTarget, ...] = ()
        self.selected_key: Hashable | None = None
        self.reset(targets)

    def reset(self, targets: Iterable[SpatialTarget], *, preserve: bool = True) -> None:
        ordered = tuple(sorted(targets, key=lambda target: (target.row, target.column, str(target.key))))
        previous = self.selected_key if preserve else None
        self.targets = ordered
        keys = {target.key for target in ordered}
        self.selected_key = previous if previous in keys else None

    def clear(self) -> None:
        self.selected_key = None

    @property
    def current(self) -> SpatialTarget | None:
        return next((target for target in self.targets if target.key == self.selected_key), None)

    def move(self, direction: str) -> SpatialTarget | None:
        if not self.targets:
            self.selected_key = None
            return None
        current = self.current
        if current is None:
            target = self.targets[0]
            self.selected_key = target.key
            return target

        direction = str(direction).casefold()
        if direction == "left":
            candidates = [target for target in self.targets if target.column < current.column]
            score = lambda target: (
                abs(target.row - current.row), current.column - target.column,
                target.row, target.column,
            )
        elif direction == "right":
            candidates = [target for target in self.targets if target.column > current.column]
            score = lambda target: (
                abs(target.row - current.row), target.column - current.column,
                target.row, target.column,
            )
        elif direction == "up":
            candidates = [target for target in self.targets if target.row < current.row]
            score = lambda target: (
                abs(target.column - current.column), current.row - target.row,
                target.row, target.column,
            )
        elif direction == "down":
            candidates = [target for target in self.targets if target.row > current.row]
            score = lambda target: (
                abs(target.column - current.column), target.row - current.row,
                target.row, target.column,
            )
        else:
            return current

        if candidates:
            target = min(candidates, key=score)
            self.selected_key = target.key
            return target
        return current


def event_targets_text_input(event) -> bool:
    """Evita secuestrar flechas o letras mientras se escribe en un campo."""

    widget = getattr(event, "widget", None)
    try:
        widget_class = str(widget.winfo_class()).casefold()
    except Exception:
        return False
    return any(name in widget_class for name in ("entry", "text", "spinbox"))
def keypress_sequences(key: str) -> tuple[str, ...]:
    """Secuencias Tk para una tecla configurable, incluidas ambas cajas."""
    value = str(key or "").strip()
    if not value:
        return ()
    names = (value.lower(), value.upper()) if len(value) == 1 and value.isalpha() else (value,)
    return tuple(dict.fromkeys(f"<KeyPress-{name}>" for name in names))
